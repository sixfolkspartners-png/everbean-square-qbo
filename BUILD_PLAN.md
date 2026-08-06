# BUILD_PLAN.md — execute top to bottom

Autonomous build plan for the prototype in `docs/04-prototype-spec.md`. Each milestone ends with a checkpoint you can self-verify. Commit after each. Don't wait for the user between milestones — only stop for the human-only inputs noted in `docs/decisions.md`, and even then keep building everything that doesn't depend on them (use the seed/demo path).

## M0 — Scaffold
- Create `app/` package: FastAPI app, config, `docker-compose.yml` (app + Postgres), `Dockerfile`, `requirements.txt` (include engine deps + fastapi, uvicorn, sqlalchemy, alembic, psycopg, jinja2, python-multipart, cryptography, apscheduler, httpx, pytest).
- Vendor the engine: import from `engine/` (add it to the path or `pip install -e`), do NOT fork its accounting code.
- **Checkpoint:** `docker compose up` serves a health page; `cd engine && python tests/test_transform.py` still passes.

## M1 — Data model + migrations
- SQLAlchemy models: organizations, users, memberships, connections, mappings, sync_runs (per `docs/03-architecture.md`). Unique(org_id, business_date) on sync_runs.
- Alembic initial migration.
- Fernet token encryption helpers (`APP_SECRET_KEY`), with a round-trip test.
- **Checkpoint:** migrations apply; token encrypt/decrypt test passes.

## M2 — Canonical model + adapters
- `DailySalesSummary` dataclass.
- `SourceAdapter`/`DestinationAdapter` interfaces.
- `SquareSource` wrapping `engine/src/square_client.py`; `QBODestination` wrapping `engine/src/transform.py` + `qbo_client.py`. Correctness logic reused unchanged.
- **Checkpoint:** unit test builds a `DailySalesSummary` from sample data and produces the same SalesReceipt JSON the engine test expects.

## M3 — SyncService + Scheduler
- `SyncService.run_day(org, date, dry_run)`: fetch → `reconcile.check_day` → post if clean & not dry-run → upsert `sync_runs`. Idempotent (query DocNumber; unique constraint backstop).
- APScheduler daily job over active orgs.
- **Checkpoint:** idempotency test (run_day twice → one receipt, one row); over_short>$25 → status 'review', not posted.

## M4 — Auth + onboarding wizard
- Email/password auth, sessions.
- OAuth connect+callback routes for Square and QuickBooks; store encrypted tokens; refresh-on-use with rotated-token persistence to DB.
- Onboarding steps 1–4 incl. auto-detect/create item template + capture deposit account & fee timing.
- **Checkpoint:** wizard renders end-to-end; with sandbox creds a connection is stored encrypted; without creds the wizard still renders and explains what's needed.

## M5 — Reconciliation dashboard
- Org dashboard table (status badges, over/short, tie-out), filters, day-detail (line preview + reconciliation + QBO link), actions (dry-run, run, backfill, re-run) via htmx.
- Top summary tiles.
- **Checkpoint:** dashboard renders from `sync_runs`; day detail matches engine output; actions work.

## M6 — Seed/demo + polish
- `python -m app.seed`: create demo "EverBean" org with the known mapping and load the Jul 24–30 sample as `sync_runs` (offline data — NO live creds). Dashboard is populated and clickable out of the box.
- Root `README.md`: run + demo in under a page.
- **Checkpoint:** clean checkout → `docker compose up` → `python -m app.seed` → open dashboard → 7 reconciled days, each drillable. Meets all acceptance criteria in `docs/04-prototype-spec.md`.

## M7 — Tests + handoff notes
- Tests: adapter mapping, SyncService idempotency, token round-trip, org-scoping isolation, plus engine tests wired into CI.
- `NEXT_STEPS.md`: what's stubbed (Stripe, single source/dest), and the human inputs still outstanding.
- **Checkpoint:** `pytest` green; acceptance criteria 1–7 all demonstrably met.

## Sample data for the seed (offline — from the validated week)
`(business_date, gross, discounts, tax, tips, gift_card_sales, total_collected, redemptions)`
```
2026-07-24, 2434.32, -18.80, 107.37, 335.41,   0.00, 2858.33, 122.90
2026-07-25, 3772.87, -58.35, 163.69, 455.53,   0.00, 4329.97, 116.88
2026-07-26, 3086.83, -15.55, 137.17, 394.44,   0.00, 3589.07,  26.19
2026-07-27, 2085.70, -17.77,  92.89, 254.88, 240.00, 2649.40, 141.65
2026-07-28, 2033.97, -38.30,  89.28, 236.93, 100.00, 2421.85,  55.14
2026-07-29, 2070.62, -23.20,  90.78, 279.44, 250.00, 2667.69, 104.23
2026-07-30, 1782.51, -16.70,  79.71, 229.35, 150.00, 2224.88, 122.66
```
These are the same figures in `engine/tests/test_transform.py` — reuse them so the demo and the tests agree.
