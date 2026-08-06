# QBO API — sandbox first, exact tax override, draft-and-approve

Goal for this phase: post the two daily SalesReceipts (CARD + CASH) into an
Intuit **sandbox** company via the raw QBO REST API, reproduce the validated
Aug 4 receipts to the penny, then graduate to production behind a draft-approve
gate. Nothing touches EverBean's live books until sandbox is proven.

The code is already here: `src/qbo_client.py` (OAuth refresh + idempotency +
create), `src/transform_batches.py` (the two-batch payload builder), and
`scripts/dryrun_two_batch.py` (builds + ties out with NO credentials — run it now
to see the exact JSON).

## What only you can do (≈15 min) — the blocker
1. **developer.intuit.com → your app → Keys & credentials → Development (sandbox)**.
   Copy the **Client ID** and **Client Secret** (the *Development* set, not Production).
2. **Add a redirect URI** (Keys & credentials):
   `https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl`
3. **OAuth 2.0 Playground** → select your app → scope
   `com.intuit.quickbooks.accounting` → **Get authorization code** → choose your
   **sandbox company** → **Get tokens**. Copy the **refresh token** and the
   **Realm ID** (this is the *sandbox* company id, different from production's
   9130357334018486).
4. Put them in the environment (local `.env` for now — never commit):
   ```
   QBO_ENV=sandbox
   QBO_CLIENT_ID=...            # Development
   QBO_CLIENT_SECRET=...        # Development
   QBO_REFRESH_TOKEN=...        # from the sandbox playground
   QBO_REALM_ID=...             # SANDBOX company id
   ```

## Then I (or you) finish the wiring
5. **Discover / create the sandbox entities.** The sandbox is a blank QBO company,
   so it won't have "Square sales item", "Tips", "Gift Card", "Square Fees",
   "Over and Short", the deposit account, or a tax code/rate yet. Run:
   ```
   cd engine && python -m scripts.lookup_ids
   ```
   It lists what exists. Create the missing items/accounts (sandbox UI or API),
   then set the IDs in `.env`:
   `QBO_ITEM_SQUARE_FEES`, `QBO_ITEM_OVER_SHORT`, `QBO_DEPOSIT_ACCOUNT_ID`
   (optionally `QBO_DEPOSIT_ACCOUNT_CC` / `QBO_DEPOSIT_ACCOUNT_CASH` to split
   card vs cash deposit accounts), `QBO_TAX_CODE_ID`, `QBO_TAX_RATE_ID`.
   (`ITEM_SALES=23`, `ITEM_DISCOUNT=20`, `ITEM_TIPS=10`, `ITEM_GIFT_CARD=7` are
   EverBean *production* ids — re-map them to the sandbox ids too.)
6. **Dry-run against the real builder** (still no posting):
   `python -m scripts.dryrun_two_batch` — confirm both receipts tie out.
7. **Post the two Aug 4 receipts to sandbox** and open them in the sandbox UI.
   They must match the manual receipts: CC total $2,076.45, cash $221.95.

## THE ONE THING TO VALIDATE IN SANDBOX (make-or-break)
Does QBO honor `TxnTaxDetail.TotalTax` **exactly**, or does it recompute tax from
the rate and overwrite it? We send `TotalTax` AND a fixed-amount
(`PercentBased:false`) `TaxLine` so the posted tax equals Square to the penny.
After posting, read the receipt back and confirm the tax line reads **$80.39**
(not a rate-recomputed value). If QBO recomputes, we adjust the TaxLine strategy
until Square's exact tax survives — this is the whole reason we went to the raw
API, so it has to be right before production.

## Rollout: draft-and-approve (your choice)
Once sandbox posts cleanly, wire posting into the morning job as **propose, then
approve**:
- The morning run reconciles the day (must tie to the payout to the penny — the
  §0 hard rule), builds both receipts, and emails them as a **proposal** (the
  same email, with the two receipts and a one-click/`reply APPROVE` action).
- Posting to **production** happens only after you approve; the DocNumber
  (`SQ-YYYYMMDD-CC` / `-CASH`) keeps it idempotent so approving twice can't
  double-post. A day that doesn't reconcile is never proposed — it goes out
  flagged `[NEEDS REVIEW]`.
- After a few clean days, flip the switch to auto-post when reconciled.

## Guardrails already enforced
- **Idempotency:** `create_sales_receipt` queries by DocNumber first; re-runs skip.
- **Tie-out:** a receipt that doesn't equal the actual payout / cash deposit is
  not posted — reconcile or flag, never plug.
- **Sandbox isolation:** `QBO_ENV=sandbox` routes every call to
  `sandbox-quickbooks.api.intuit.com`; production is impossible until you flip it.
