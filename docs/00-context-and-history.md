# 00 — Context & History (read first)

This is the full story so nobody has to repeat it. It's written for an engineer/agent picking the project up cold.

## The origin
EverBean Coffee Co (SixFolks Partners LLC dba EverBean Coffee Co, a Denver coffee shop) runs **Square** for POS and **QuickBooks Online** for accounting. The native Square↔QuickBooks connector is unreliable ("trash"). The owner (Andrew) wanted each day's Square sales posted to QuickBooks **correctly, automatically, and balancing to the penny** — broken down as: gross product sales, discounts, sales tax, tips, gift-card purchases, gift-card redemptions.

We built and proved that against his live accounts. Then he decided to **productize it as a micro-SaaS (Path B)** aimed at the bookkeeper/accountant channel. This repo is that productization.

## What was tested against live QuickBooks — and RULED OUT (with evidence)
This history matters: the product's differentiation *is* these findings. Don't rediscover them.

1. **`transaction_import` (bank-feed-style categorized entries) — REJECTED.**
   It can only classify amounts as income (+) or expense (−). On a live test day it mis-routed: **sales tax → "Services" income** (should be a liability), **discount → "Bank fees" expense**, **gift-card redemption → "Advertising" expense**. Structurally cannot post to liability accounts. Verified on the balance sheet (Square Sales Tax Payable didn't move). Dead end.

2. **Invoice with tax as a line item — CORRECT ACCOUNTS, WRONG DOC TYPE.**
   Line items reference real QB items, so tax→Square Sales Tax Payable, tips→Tips, gift cards→Gift Card Outstanding all posted correctly (verified: Sales Tax Payable $8.27→$101.16, Tips +$254.88, Gift Card Outstanding +$98.35). Matches Square to the penny. BUT an invoice creates **Accounts Receivable** (the money sits as "owed," not deposited), and the connector has no tool to record payment/clear it. Also doesn't feed the Sales Tax Center. **This is exactly how competitor Amaka works — and why it's flawed.**

3. **Invoice with native computed tax — DRIFTS.**
   Marking sales+discount taxable let QuickBooks compute 4.5% tax into its native Total Tax field (feeds the Sales Tax Center). For 7/27 QB computed **$93.06 vs Square's actual $92.89** (+$0.17/day; ~+$7.63 over the sample week). QuickBooks recomputes by rate; Square taxes per order on the real mix, so they never tie to the penny.

4. **Tax override — the crux.**
   Overriding the computed tax to Square's exact figure is possible in the QuickBooks **UI** and in the QuickBooks **API** (`TxnTaxDetail.TotalTax`), but **NOT** in the MCP connector tools we had. That gap is why the real solution is a **direct QuickBooks API integration** — which is what `engine/` is.

## The chosen solution (built, in `engine/`)
A **SalesReceipt** posted via the direct Intuit Accounting API:
- Cash sale → **no A/R**, money to a deposit account.
- Line items reference the existing QB items → income + liabilities route correctly.
- `TxnTaxDetail.TotalTax` = **Square's exact collected tax** (the override the connector couldn't do) → matches what's remitted AND feeds the Sales Tax Center.
- Square Fees line + Over/Short plug so the receipt total = the real bank deposit → auto-reconciles.
- Idempotent (`DocNumber = SQ-YYYYMMDD`, query-before-post).
- Refresh-token rotation handled (QBO tokens rotate ~100 days).

The engine's accounting logic is offline-validated on the Jul 24–30 2026 sample week — all seven days reconcile. See `engine/tests/test_transform.py`.

## Live QuickBooks facts (EverBean = reference tenant)
- Realm/company id: **9130357334018486**
- "Square customer" id **2**
- Items: Square sales item **23**, Square discount item **20**, Square sales tax item **21**, Tips **10** (liability), Gift Card **7** (liability)
- Liability accounts: **Square Sales Tax Payable**, **Gift Card Outstanding**, **Tips**
- Tax rate configured: **4.5%**
- Notable: EverBean's QB already had the "Square sales item / Square Fees / Over and Short / Square customer" template — the *signature of Commerce Sync / Amaka*. Most Square shops that tried a sync tool have this. Onboarding should auto-detect or create it.

## Square extraction (built, proven)
- **Reporting API** (`/v1/reporting/load`, `Sales` view, `reporting_day` day granularity): gross (`top_line_product_sales`), discounts, comps, `sales_tax_amount`, `tips_amount`, `gift_card_sales_amount`, `total_collected_amount`.
- **GiftCardActivities API** (`/v2/gift-cards/activities`, type `REDEEM`): redemptions — COMPLETED only, exclude CANCELED.
- **Payouts API** (`/v2/payouts`): fees + actual deposit for tie-out (fees settle at payout, may lag the sale day).
- Reconciliation proven: gross − discounts + tax + tips + gift-card purchases = Square total_collected within $0.03/day.

## Where we are
Engine works single-tenant. Productizing into multi-tenant onboarding + reconciliation dashboard = this prototype. See `docs/04-prototype-spec.md` and `BUILD_PLAN.md`.
