# EverBean — Square → QuickBooks daily sales sync

Posts each day's Square sales to QuickBooks Online as a **SalesReceipt**, with
every line routed to the correct account (income *and* liabilities), sales tax
**overridden to Square's exact collected figure**, and the total tied to the
real bank deposit. Runs itself daily on GitHub Actions. No third-party
subscription, ~$0/month to operate.

## Why this exists
The native Square↔QuickBooks connector is unreliable, and QuickBooks' own
connector tools can't (a) post to liability accounts correctly, or (b) override
the computed tax to match what Square actually collected. This does both by
calling the Intuit Accounting API directly.

## How it works
```
GitHub Actions (daily cron)
   └─ src/main.py
        ├─ SquareClient      Reporting + GiftCardActivities + Payouts  → day's numbers
        ├─ reconcile         internal consistency + deposit tie-out
        ├─ transform         → QuickBooks SalesReceipt (items + TxnTaxDetail override)
        └─ QBOClient         OAuth refresh → idempotent POST (skip if DocNumber exists)
```

Each day becomes one SalesReceipt with `DocNumber = SQ-YYYYMMDD`, so re-runs
never duplicate. Refresh-token rotation is handled automatically (see docs).

## What's proven vs. pending
- ✅ **Square extraction + all accounting logic** — validated offline against the
  Jul 24–30 2026 sample week (`python tests/test_transform.py`): exact-tax
  override, correct taxable flags, Over/Short capture, receipt total = Square
  total_collected − gift-card redemptions, all seven days.
- ⬜ **Live QuickBooks POST** — needs your Intuit app (see `docs/INTUIT_SETUP.md`).
- ⬜ **Final config IDs** — Square Fees item, Over/Short item, deposit account,
  tax code/rate — fetched once via `scripts/lookup_ids.py`.

## Quick start
1. Do `docs/INTUIT_SETUP.md` (one time).
2. Add the GitHub secrets it lists.
3. `python -m scripts.lookup_ids` → paste the remaining IDs as secrets.
4. Actions → run the workflow with `dry_run=true` for one day; review the printed
   SalesReceipt; then run for real.
5. Leave the daily schedule on.

## Layout
```
config.py                     mappings + settings
src/square_client.py          Square pulls
src/transform.py              SalesReceipt builder (the tax-override core)
src/reconcile.py              consistency + deposit tie-out
src/qbo_client.py             OAuth + idempotent SalesReceipt POST
src/token_store.py            rotate refresh token into a GitHub secret
src/main.py                   entrypoint (daily / --date / --backfill / --dry-run)
scripts/lookup_ids.py         one-time ID finder
tests/test_transform.py       offline validation on the sample week
.github/workflows/            daily cron + manual run
docs/INTUIT_SETUP.md          the one-time QuickBooks setup
```

## Notes / decisions
- Sales & discount lines are taxable; tips, gift cards, fees, over/short are not.
- Square fees settle at payout (may lag the sale day) — the receipt can post on
  the sale day and the fee/deposit tie-out reconciles when the payout lands.
- Gift-card redemptions use COMPLETED activity only (CANCELED excluded).
