# Decisions (pre-made — don't re-open)

These are settled so the build doesn't stall on choices. Each has a reason; follow unless a hard technical blocker forces a change (document it if so).

| # | Decision | Why |
|---|---|---|
| D1 | Python 3.12 + FastAPI | Reuse the proven engine directly; fast to build. |
| D2 | Postgres + SQLAlchemy 2.x + Alembic | Real multi-tenant persistence; migrations from day one. |
| D3 | Jinja2 + Tailwind (CDN) + htmx for UI | Fastest path to a working dashboard one agent can ship. React is a later swap, not now. |
| D4 | APScheduler in-process for scheduling | Prototype-appropriate; mark where it graduates to a queue/worker. |
| D5 | Fernet encryption for tokens at rest; key in `APP_SECRET_KEY` | Simple, adequate for prototype; DB is the token store (not GitHub secrets). |
| D6 | Stripe in test mode, behind a `BillingService` stub | Billing shouldn't block the core demo; wire real keys later. |
| D7 | Reuse `engine/src/transform.py` + `reconcile.py` verbatim for accounting | It's validated; wrap, don't rewrite. |
| D8 | SalesReceipt only (never Invoice) | Correctness spec; the whole differentiator. |
| D9 | One `sync_runs` row per org per day, unique(org_id, business_date); DocNumber `SQ-YYYYMMDD` | Idempotency + a clean dashboard grain. |
| D10 | Clean `SourceAdapter` / `DestinationAdapter` interfaces even with one impl each | Future-proof for Xero / Clover / Toast without a rewrite. |
| D11 | `docker compose up` = the demo; tests must pass | "Done" is a running product an agent/user can click through. |
| D12 | Auth for the app: email + password (simple), sessions | Enough for a prototype; SSO/magic-link later. |

## Explicitly OUT of scope for the prototype
- Real payment processing / going live on Stripe.
- More than one source (Square) or one destination (QuickBooks Online).
- Sales-tax *filing* (that's a later add-on; we only book the tax correctly).
- Firm/white-label UI (model the data for it — `memberships` — but don't build the UI yet).
- Production hardening (rate limiting, full observability) beyond basic error handling + alerts.

## Human inputs required (surface clearly; don't block on them)
- Intuit Developer app + Square OAuth app client id/secret/redirect (see engine/docs/INTUIT_SETUP.md). Until provided, use env placeholders and a "connect" flow that can run against sandbox.
- Deposit account + fee-timing choices per tenant → collected in onboarding UI.
