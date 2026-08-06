# 01 — Correctness Spec (non-negotiable)

These rules are the product. Every one was validated against live QuickBooks. If a code change would violate one, it is a bug, not a simplification.

## The daily SalesReceipt (per tenant, per day)
Document type: **SalesReceipt** (a cash sale). NEVER an Invoice (invoices create Accounts Receivable — the incumbent flaw we exist to beat).

Lines (each references a QuickBooks item whose account link does the routing).
**Every line is non-taxable** (`TaxCodeRef = "NON"`) — see Tax handling:

| Line | Source amount | Sign | Routes to |
|---|---|---|---|
| Gross product sales | `Sales.top_line_product_sales` | + | Income |
| Discounts | `Sales.discounts_amount` | − (already neg) | Contra-income |
| Sales tax | Square's exact `sales_tax_amount` | + | **Square Sales Tax Payable** (liability) |
| Tips collected | `Sales.tips_amount` | + | Tips **liability** |
| Gift card purchases | `Sales.gift_card_sales_amount` | + | Gift Card **liability** |
| Gift card redemptions | GiftCardActivities REDEEM (COMPLETED) | − | Gift Card **liability** |
| Square fees | Payouts API | − | Expense |
| Over and short | plug (see below) | ± | Over/Short |

Sales tax **IS a line** (to a liability item), not `TxnTaxDetail`.

## Tax handling (the crux — REVISED after live sandbox validation, Aug 2026)
- **Do NOT use QuickBooks' tax engine.** Validated against a live QBO sandbox:
  QuickBooks' **Automated Sales Tax ignores `TxnTaxDetail.TotalTax`** and
  recomputes tax from its own rate (it applied the sandbox's 8% instead of our
  exact figure). The override approach does not survive AST.
- **Instead:** every line is non-taxable (`TaxCodeRef = "NON"`), so QuickBooks
  computes **$0** tax, and Square's exact `sales_tax_amount` rides as its **own
  line item** to `ITEM_SALES_TAX` → "Square Sales Tax Payable" (a liability).
  The receipt has **no `TxnTaxDetail`**.
- Result: `TotalAmt` equals Square's money-to-deposit **to the penny, immune to
  AST** — no dependency on QBO's tax rate matching Square's. Proven live:
  Aug 4 CC receipt $2,076.45 (QBO tax $0), cash $221.95 (QBO tax $0), each
  carrying the exact $80.39 / $9.56 as a liability line.
- Rationale unchanged: what you remit must equal what Square collected — but the
  liability line, not QBO's recompute, is what guarantees it. The old
  `TxnTaxDetail`/`TaxLine` refs in `config.py` are retained only as dead legacy
  and are unused.

## Over/Short plug
`over_short = total_collected − (gross + discounts + tax + tips + gift_card_sales)`
This makes the receipt's pre-redemption subtotal equal Square's own `total_collected`, absorbing rounding/refund-timing pennies. Normal range is a few dollars. If `|over_short| > $25`, **do not post** — flag the day for review (something is genuinely off).

## Receipt total must equal money to deposit
`receipt_total = total_collected − gift_card_redemptions − fees`
i.e., what actually hits the bank. When the Square payout lands, it should match → auto-reconciles. (Fees settle at payout and may lag the sale day; posting on sale day + truing up at payout is acceptable and is a per-tenant setting.)

## Idempotency
`DocNumber = "SQ-" + YYYYMMDD`. Always query QuickBooks for an existing SalesReceipt with that DocNumber before posting. Re-runs and backfills must never duplicate a day.

## Gift card redemptions
Only `redeem_activity_details.status == "COMPLETED"`. Exclude CANCELED (they appear in the feed with amount 0 or reversed).

## Reconciliation gates (a day is "clean" only if)
1. Internal: `|over_short| ≤ $25`.
2. Deposit tie-out (when payout data available): `|receipt_total − actual_deposit| ≤ $0.05`.
A day failing (1) is not posted and is surfaced for review. A day failing (2) is posted but flagged for attention.

## Reference implementation
`engine/src/transform.py` (`build_sales_receipt`, `expected_receipt_total`) and `engine/src/reconcile.py` (`check_day`) already implement all of the above and pass `engine/tests/test_transform.py`. Reuse them.
