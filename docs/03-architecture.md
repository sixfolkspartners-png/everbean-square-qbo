# 03 — Architecture (multi-tenant) & stack

## Stack (decided — see docs/decisions.md; do not relitigate)
- **Language:** Python 3.12 (matches the engine; reuse it directly).
- **Web framework:** FastAPI.
- **DB:** PostgreSQL via SQLAlchemy 2.x + Alembic migrations. SQLite allowed for local dev/tests.
- **Frontend:** server-rendered Jinja2 templates + Tailwind (CDN) + htmx for interactivity. Rationale: fastest path to a credible working dashboard an agent can ship end-to-end. (A React/Next front-end is a valid later swap; not for the prototype.)
- **Background work:** APScheduler in-process for the prototype (one daily job that iterates active tenants). Note in code where this becomes a proper worker/queue at scale.
- **Secrets/token encryption:** Fernet (cryptography lib), key from env `APP_SECRET_KEY`. Tokens encrypted at rest in the DB.
- **Billing:** Stripe in test mode, stubbed behind a `BillingService` interface — real keys optional for the prototype.
- **Packaging:** `docker compose up` brings up app + Postgres. Must work from a clean checkout.

## The four seams (why it generalizes)
```
SOURCE adapter → CANONICAL DailySalesSummary → DESTINATION adapter
                          │
                  CORRECTNESS ENGINE (reused from engine/)
```
- `SourceAdapter` interface: `fetch_day(tenant, date) -> DailySalesSummary`. First impl: `SquareSource` (wraps engine/src/square_client.py logic).
- `DailySalesSummary`: canonical dataclass — gross, discounts, comps, tax, tips, gift_card_sales, gift_card_redemptions, fees, total_collected, deposit. Source- and destination-agnostic.
- `DestinationAdapter` interface: `post_day(tenant, summary) -> PostResult` (idempotent). First impl: `QBODestination` (wraps engine/src/transform.py + qbo_client.py).
- Correctness engine = `engine/src/transform.py` + `reconcile.py`, called by the destination adapter. **Unchanged accounting logic.**

Adding Xero later = a new `DestinationAdapter`. Adding Clover/Toast = a new `SourceAdapter`. No core rewrite. Keep the interfaces clean now even though only Square+QBO exist.

## Data model (Postgres)
- **organizations** (tenant): id, name, created_at, plan, deposit_account_pref, fee_timing ('sale_day'|'payout'), status.
- **users**: id, email, org_id (FK), role. (Firm tier later = user ↔ many orgs; model the join now as `memberships` even if 1:1 in the prototype.)
- **connections**: id, org_id, kind ('square'|'qbo'), status, encrypted_access_token, encrypted_refresh_token, token_expires_at, external_ids (JSON: realm_id / merchant_id / location_ids).
- **mappings**: id, org_id, JSON of item ids + account ids + tax code/rate (generalized `engine/config.py`). Populated at onboarding via auto-detect/create.
- **sync_runs**: id, org_id, business_date, status ('pending'|'posted'|'skipped'|'review'|'error'), doc_number, receipt_id, over_short, receipt_total, deposit, tie_out_ok, error, payload_json, created_at. One row per org per day (unique on org_id+business_date).

## Multi-tenant flow
1. **Onboarding** (per org): sign up → connect Square (OAuth) → connect QuickBooks (OAuth) → auto-detect/create item template + build mapping → confirm deposit account & fee timing → active.
2. **Daily job** (APScheduler, ~07:15 tenant-local or a global early-UTC run): for each active org, for yesterday: `SquareSource.fetch_day` → `reconcile.check_day` → if clean, `QBODestination.post_day` (idempotent) → write `sync_runs` row. Failures alert + mark 'error'/'review'.
3. **Dashboard**: per org, a table of days with status/over-short/tie-out; drill into a day (line preview + reconciliation); actions: re-run, dry-run preview, backfill a range.

## Token management
- OAuth callbacks store encrypted tokens in `connections`.
- Before each destination call, refresh the QBO access token; persist any rotated refresh token back to the DB (replaces the GitHub-secret hack in `engine/src/token_store.py` — in the platform the DB is the store).
- Square token is a long-lived access token per tenant (OAuth or PAT).

## Security
- Encrypt tokens at rest (Fernet). Never log tokens. Secrets via env only.
- Per-org data isolation enforced in every query (scope by org_id).
- HTTPS assumed at deploy; CSRF on state-changing routes.
