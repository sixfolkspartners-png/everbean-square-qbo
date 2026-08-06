# 04 — Prototype Spec (what to build now)

Goal: the artifact that turns "a script" into "a product" — **multi-tenant onboarding + a reconciliation dashboard**, wrapping the proven engine. A user can onboard an org, connect Square + QuickBooks, run a day, and see it reconcile in a dashboard.

## Screens (Jinja2 + Tailwind + htmx)

### 1. Sign up / log in
Email + password, sessions. On sign up, create an `organization` + `user` + `membership`.

### 2. Onboarding wizard (per org)
- **Step 1 — Connect Square:** OAuth connect button → callback stores encrypted tokens + merchant/location ids in `connections`.
- **Step 2 — Connect QuickBooks:** OAuth connect → store realm id + tokens.
- **Step 3 — Map & confirm:** auto-detect the QB item template (Square sales item / discount / tips / gift card / fees / over-and-short) via the Item query; if missing, offer to create them. Show the resulting mapping for confirmation. Capture **deposit account** and **fee timing** (sale_day | payout). Save to `mappings` + `organizations`.
- **Step 4 — Done:** org is `active`; daily job will include it.

### 3. Reconciliation dashboard (the core screen)
- A table of recent business days for the org: date, status badge (posted / skipped / **review** / error), over/short, receipt total, deposit, tie-out ✓/✗.
- Filters: date range, status.
- Row → **day detail**: the SalesReceipt line preview (from `transform.build_sales_receipt`), the reconciliation report (`reconcile.check_day`), the QuickBooks link if posted.
- Actions (htmx): **Dry-run preview** (build + show, no post), **Run/Post this day**, **Backfill range**, **Re-run**.
- A top summary: last successful sync, # days needing review, this-month totals.

### 4. Settings
Connections status (reconnect), mapping view/edit, deposit/fee prefs, plan (stubbed).

## Backend (FastAPI)
- Adapters: `SquareSource` (wrap engine square_client), `QBODestination` (wrap engine transform + qbo_client). Canonical `DailySalesSummary` dataclass between them.
- `SyncService.run_day(org, date, dry_run)`: fetch → reconcile → (post if clean & not dry-run) → upsert `sync_runs`. Idempotent.
- `Scheduler`: daily APScheduler job iterating active orgs for yesterday.
- OAuth routes for Square + QuickBooks (connect + callback), token refresh on use, rotated-token persistence to DB.
- All queries scoped by org_id.

## Seed / demo
- A `seed` command that creates a demo org ("EverBean") pre-populated with the known mapping (realm 9130357334018486; items 23/20/21/10/7) and loads the **Jul 24–30 2026 sample** as `sync_runs` using the offline sample data, so the dashboard is populated and clickable **without live credentials**. This is how the demo works out of the box.
- With live credentials present, the same flows hit real Square/QuickBooks.

## Acceptance criteria (definition of done)
1. `docker compose up` → app + Postgres running; migrations applied.
2. `python -m app.seed` → demo "EverBean" org visible with 7 reconciled days in the dashboard; each day drillable showing correct line preview + tie-out. **No live credentials needed for this.**
3. Onboarding wizard renders and walks Square→QBO→map→done; OAuth callbacks store encrypted tokens (works against sandbox creds when provided).
4. Dry-run preview for a day shows the exact SalesReceipt JSON + reconciliation, matching the engine's output.
5. A day with `|over_short| > $25` shows **review** status and is not posted.
6. Existing engine tests still pass; new tests cover: adapter mapping, `SyncService` idempotency (re-run doesn't duplicate), token encryption round-trip, and org-scoping isolation.
7. `README.md` at repo root explains run + demo in under a page.

## Non-goals (see decisions.md)
Real Stripe charges, multiple POS/ledgers, tax filing, firm UI, production hardening.
