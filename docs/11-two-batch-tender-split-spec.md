# 11 — Two-Batch Tender Split (execute against the engine + app)

**Change:** a day no longer posts one SalesReceipt. It posts **two deposit batches — CARD and
CASH — each with the same line breakdown**, split by the *actual tender* of each order, because
card and cash settle to the bank differently (card via Square payout net of fees; cash via a
physical deposit). Gift-card tender is handled as a liability movement, not a bank batch.

This preserves every rule in `docs/01-correctness-spec.md`; it adds a tender dimension.

## Tender routing (the model)
For each day, every order's money is split by the tender that actually paid it:

**There are exactly TWO batches: Credit-card (CC) and Cash.** Gift-card redemption is NOT a
third batch — its *sale* belongs in the CC batch, and the gift-card payment comes off as a
**reduction line** (see below).

| Tender (Square `type`) | Goes to | Deposits via | Fees? | Tips? |
|---|---|---|---|---|
| `CARD` | **CC batch** | Square payout → bank | yes | card tips → CC batch |
| `SQUARE_GIFT_CARD` | **CC batch** — sale recognized here; the payment is a **reduction line** drawing down Gift Card Outstanding | (reduces the CC deposit) | no | gift-card tips → CC batch |
| `CASH` | **Cash batch** | physical cash deposit → bank | no | **none** (cash tips excluded, see below) |
| `EXTERNAL` / other | configurable; default excluded from both bank batches | — | — | — |
| `SPLIT_TENDER` | **decompose** — cash portion → Cash batch; card/gift portions → CC batch (rule 1) | per portion | per portion | per portion |

### Why gift-card redemption is a reduction *inside* the CC batch
The sale (gross, tax, tips) is real revenue and is recognized in the CC batch. But it was paid
from a gift card, not a card swipe — so that amount can't deposit. It comes off as
`Less: gift card redemptions` (debit **Gift Card Outstanding**), which is exactly how Square's
reconciliation treats it ("gift card (non-transferable)"). The CC batch then foots to the actual
Square payout. Net gift-card liability movement = gift cards **sold** (added, in CC) − **redeemed**
(reduction, in CC).

### Andrew's two rules (non-negotiable)
1. **Split-tender allocates to the real tender.** A mixed-payment order is decomposed by its
   actual tender amounts: the cash portion goes to the **cash** batch/deposit, the card portion to
   the **card** batch. Never bucket a whole split order into one tender.
2. **Cash tips are excluded entirely.** Square doesn't record cash tips and they go directly to
   staff — so the cash batch shows **$0 tips**, and no cash-tip line appears anywhere.

## Data source change (this is the real work)
The current `SquareSource` is reporting-only; reporting's `payment_method` dimension lumps mixed
orders into `SPLIT_TENDER`, which rule 1 forbids. So the tender split must come from order/payment
detail:

- **Orders API** (`POST /v2/orders/search`, location + day window) — primary. Per order:
  `net_amounts` (total, tax, discount, tip, service charge) and **`tenders[]`** each with
  `{type, amount_money, tip_money}`. Sum tenders across the day by `type`. **Paginate** (cursor).
- **Payouts API** — **the source of truth for the card batch's fees, deductions, and net deposit.**
  Card fees are NOT just `Payments.processing_fee`. Square deducts **multiple** fee/deduction
  types from the transfer — at minimum **payment processing fees** AND **gift-card load fees**
  (charged when gift cards are sold, ~2.5% of gift cards sold). Summing `Payments.processing_fee`
  alone under-deducts and the batch won't tie out (this bit us on Jul 29: missed a $6.25 gift-card
  load fee → deposit was $6.25 high).
- **NEVER estimate, derive, or hand-sum the fee or the deposit — RECONCILE or FLAG.** This is
  financial data. When a payout exists, the fee **and** the CC deposit come from the **fully
  paginated** payout decomposition, and the batch must tie to the payout **to the penny**. Concretely:
  call `Payouts.listEntries` and **follow the cursor to the last page** — loop until the response has
  **no `cursor`** (a day routinely exceeds one page; the page cap is ~96–100 entries, so one page is
  almost never the whole payout). Then `fee = Σ fee_amount_money` over **all** entries and
  `deposit = Σ net_amount_money` over **all** entries, and `deposit` must equal the payout's
  `amount_money` exactly. **Do NOT** reconstruct fees as `Σ Payments.processing_fee + a gift-card-load
  guess` when a payout is available — that reconstruction is the thing that caused this rule. If the
  built batch does **not** reconcile to the payout to the penny, **do not publish a plugged/derived
  number** — emit the report flagged **"DID NOT RECONCILE — needs review"** with the exact
  discrepancy and the raw components, and stop. Reconcile or flag; never approximate. (The effective
  rate wobbles daily — 3.10% Jul 31, 3.29% Jul 29, 3.35% Jul 30, 3.18% Aug 3 — which is *why* a
  fixed-% or Payments-only estimate is wrong.)
- **Provisional same-day fallback — ONLY when no payout exists yet (weekend lag).** If, and only if,
  the sale day's payout has not been created yet (Friday reported Saturday), you may post a
  provisional `eligible-for-transfer = net card sales − Σ Payments.processing_fee (real card) −
  gift-card load fee`, and it **must be labeled provisional / awaiting transfer** and trued up to the
  payout once it lands. This fallback is never used when a payout is available — a real payout always
  wins, fully paginated and reconciled to the penny.
- **The payout can LAG.** Friday sales settle Monday (no weekend transfers) — the Payouts API may
  return nothing for a day or two, and the transfer shows "in Square balance / awaiting transfer".
  So: **post the batch on the sale day** with fees computed as above; the CC deposit target is the
  settlement's "eligible for transfer" amount. **Reconcile/true-up to the payout** once it lands and
  book any difference (chargebacks, adjustments) to Square Fees / Over-Short.
- **Gift-card redemptions carry source `CARD` in the Payments API — do NOT mistake them for card
  charges or for "unsettled" sales.** Square files a stored-value redemption as a Payment with
  `source_type == "CARD"` but `card_details.card.card_brand == "SQUARE_GIFT_CARD"`, `status
  COMPLETED`, and **no `processing_fee`** (there's no interchange on spending stored value, and it
  never settles to the bank). On Aug 3, filtering "CARD source + no processing_fee" wrongly flagged the
  day's 5 gift-card redemptions ($62.71) as "late unsettled card sales" — they are neither late nor
  card. **Detect real card by `card_brand`, and exclude `SQUARE_GIFT_CARD` before summing card
  charges.** Redemptions come from `GiftCardActivities` (REDEEM/COMPLETED) or the GC-brand payments —
  both tie to the same number.
- **The reconciliation report and the payout are the source of truth for tender totals — the Orders
  API is not.** This bit us in both directions in one week: Aug 1–2 Orders **undercounted** (dropped 8
  orders / $117.62); Aug 3 Orders **overstated** card by **$64.02** (reported $2,067.26 of card tender
  vs Square's actual **$2,003.24** collected — an auth that never became a settled charge). The Aug 3
  Square reconciliation CSV is authoritative and ties end to end: gross $1,932.93 − discounts $19.25 =
  net $1,913.68; + tax $84.80 + tips $234.59 → payments collected $2,233.15 (card $2,003.24 + cash
  $167.20 + gift card $62.71); − non-transferable $229.91 (cash + gift) − fees $63.67 = **eligible /
  transferred $1,939.57**. **Rule:** anchor every day's totals to the reconciliation report + payout;
  use Orders only to attribute the **cash-vs-card proportion**, never as the amount. Decompose each
  payout via `Payouts.listEntries` (paginate — can exceed 100 entries) and sum `net_amount_money`; it
  ties to the payout exactly and gives real per-charge fees (Aug 3 blended 3.18%, with 25 keyed /
  card-not-present charges at 4–6% — another reason never to estimate).
- **Square's reporting/reconciliation "day" is a fixed window (Aug 3 CSV: 5:30 AM–6:00 PM MT), not
  calendar midnight.** Match the reconciliation window, not a naive `00:00–24:00` local pull, when you
  reconcile to the payout. Carry Square's own sales↔payments rounding (Aug 3: $0.08) as Over/Short.
- **Fully-comped orders and drawer no-sales carry no tender** and are invisible to a deposit-basis
  (tender-driven) build — Aug 3 had $10.90 of 100%-comped orders and 4 `NO_SALE` drawer opens. They
  net to zero and don't affect deposits, but they **understate gross sales and discounts**. If gross-
  sales accuracy (incl. comps) is required, source gross/discount from the Reporting Sales view.
- **GiftCardActivities** (`REDEEM`, COMPLETED) — reconcile the gift-card tender total.

Allocation: tax and discount are **order-level**, not per-tender, so split them across an order's
tenders **proportionally by tender amount**. Put any cent residual on Over/Short.

**`tender.amount_money` INCLUDES the tip — strip it before deriving net product sales.** This was the
first variance we hit (Jul 29): a tender's `amount_money` is the full amount charged to that tender,
tip included. Per-tender net product sales = `tender.amount_money − tender.tip_money − (tax × w) −
(gift_cards_sold × w)`, where `w = tender.amount_money / Σ(tender amounts on the order)`. If you skip
the `− tip_money`, every card day is overstated by its entire tip total (tips are large here — e.g.
$234.59 on Aug 3, $340.83 on Jul 31) and the batch won't tie. Tips are recognized on their own line
(→ Tips Payable), never folded into product sales. The same `w` is what you use to attribute the
cash-vs-card **proportion** when splitting reconciliation totals — so a correct tip-inclusive weight
matters even when the day's totals come from the reconciliation report.

**Selecting the right payout when several settle the same day (the Monday problem).** `Payouts.list`
can return multiple transfers at once — on Aug 3 it returned **three**: Aug 3's own $1,939.57 plus two
weekend catch-ups ($2,842.87 for Jul 31 and $6,962.41 for Aug 1–2). Do **not** grab the first/latest
payout. Match each payout to its sales day by decomposing it (`Payouts.listEntries`) and reading the
charges' effective dates / the payout's own window, then reconcile that day's CC batch to the payout
whose charges fall in that day's reporting window. Two corollaries seen this week: (a) a single
weekend payout can cover **more than one sales day** (the $6,962.41 batched Aug 1 **and** Aug 2), so
payout→day is not always 1:1 — when it spans days, its target equals the **sum** of those days'
eligible-for-transfer amounts; and (b) a sale day's transfer may not appear until a later calendar day
(weekend lag). Rule: reconcile by **matching charge windows**, not by payout arrival order or count.

**Discounts — do NOT trust the order objects.** `Order.total_discount_money` is unreliable: it
summed to only $18.45 on Jul 29 (real: $23.20) and **$0.00 on Jul 30** (real: $16.70). Pull the
day's **discount total from the reporting Sales view** (`Sales.discounts_amount`) and allocate it
across tenders by each tender's share of net sales. (Net product sales *do* reconcile from the
order tenders — Jul 30 order-net tied to reporting net $1,765.81 exactly — so derive
`gross = net + allocated discount`.) Same caution applies to any figure you take from orders:
cross-check daily totals against the reporting Sales view before trusting them.

Keep the reporting pull if you want the category breakdown for display, but tender money must come
from Orders/Payments.

**Orders and Reporting can disagree — anchor totals to Reporting + payout, never to raw orders.**
On the combined Aug 1–2 pull, the Orders API returned **410 revenue orders / $7,667.61**, while the
reporting Sales view returned **418 orders / $7,785.23** — the Orders endpoint silently dropped
**8 orders / $117.62**. (Our tender-summing was correct — it matched the orders it *was* given — the
APIs themselves disagreed.) The dropped orders were all card: adding them back put net card sales at
$7,187.98, which nets to the **actual $6,962.41 payout** at a 3.14% fee — consistent with the week's
other days, confirming the gap was card. **Rule:** use Orders only for the *tender split* (cash vs.
card proportions); the day's **totals must foot to the reporting Sales view**, and the CC batch must
foot to the **actual payout**. Compute each batch as `reporting_total − other_batch`, put any cent
residual on Over/Short, and treat the payout as the CC tie-out target. If `|orders_total −
reporting_total| > $1`, log it and reconcile to reporting — do not post off the raw orders.

## Canonical model
Replace the single `DailySalesSummary` with a **`DailyBatches`** result per day:
```
DailyBatches(date, location):
  cc:    Batch(gross, discounts, tax, tips, gift_cards_sold,   # card + gift-card-tendered orders
               gift_card_redemptions,   # reduction line (debit Gift Card Outstanding)
               fees, over_short, deposit)                       # deposit == Square payout
  cash:  Batch(gross, discounts, tax, tips=0, over_short, deposit)   # cash orders; no fees, no tips
```
CC batch flow: `collected = gross − discounts + tax + tips + gift_cards_sold`; then
`net_card = collected − gift_card_redemptions`; then `deposit = net_card − fees`. `deposit` must
equal the Square payout/transfer for the day.
`build_sales_receipt` is called **once per non-empty batch**; the accounting math per batch is the
existing engine logic, unchanged — it just receives one tender's numbers.

## Posting (two receipts)
- **CC receipt** — `DocNumber = SQ-YYYYMMDD-CC`; DepositTo = the Square-clearing/bank account.
  Lines: card **and** gift-card-tendered sales (gross, discounts, tax, tips, gift cards sold), then a
  **`Less: gift card redemptions`** reduction line (debit Gift Card Outstanding), then the fee lines
  (processing + gift-card load + any payout deductions). Total nets to the **Square payout**.
- **Cash receipt** — `DocNumber = SQ-YYYYMMDD-CASH`; DepositTo = the cash/undeposited account; no
  fees, no tips; total = the cash deposit.
- Revenue on gift-card-paid orders is recognized in the CC receipt (it's real sales); the reduction
  line moves the *payment* to the liability. No separate gift-card batch, no double-counted revenue.
- Idempotency per batch (query each DocNumber before posting); a batch with $0 activity is skipped.

## Reconciliation (per batch)
- **CC batch:** `gross − discounts + tax + tips + gift-cards-sold − gift-card-redemptions − fees + over/short`
  == the **Square payout** deposit. **`fees` = processing fees + gift-card load fees + any other payout
  deductions** (take them from the payout, not a hand-summed number). The payout amount is the tie-out
  target; any residual → Square Fees expense / Over-Short. Tight tie-out to the actual bank transfer.
- **Cash batch:** `cash gross − discounts + tax + gift-cards-sold(cash) + over/short` == the **cash
  deposit**. (No fees, no tips.)
- Over/short is computed **per batch**; `|over/short| > $25` on a batch → that batch is `review`, not posted.

## Data model + UI
- **`sync_runs`**: add a `batch` column (`card` | `cash`); unique key `(org_id, business_date, batch)`.
  One row per batch per day.
- **Dashboard:** each day shows its two batches (a day row expands to Card / Cash, each with status +
  tie-out), or two rows grouped by date. KPIs unchanged (day totals = sum of batches).
- **Day detail:** show both batch statements side by side (Card with its fee line; Cash without),
  plus the gift-card liability movement. Account names only (spec 09).

## Acceptance
1. A day posts a Card receipt and a Cash receipt, each with the correct tender's breakdown.
2. A split-tender order's cash and card portions land in the correct batches (test with a synthetic
   split order); tax/discount allocated proportionally.
3. Cash batch has **$0 tips** and **no fees**; card batch carries all card tips and the Square fees.
4. Gift-card-tendered sales post as a liability draw-down, not into either bank batch.
5. Each batch reconciles to its own deposit (card→payout, cash→cash deposit); per-batch over/short
   review gate works.
6. `sync_runs` keyed by (org, date, batch); idempotent re-runs; $0 batches skipped.
7. Engine accounting tests still pass (per-batch); add tests for split-tender allocation and the
   cash-tips-excluded / fees-card-only rules.
8. **Tip-inclusive tender:** a synthetic order whose tender `amount_money` includes a tip yields net
   product sales with the tip stripped (assert net = amount − tip − allocated tax/gc), and the day's
   tips land only on the Tips Payable line — never in product sales.
9. **Payout selection:** given a `Payouts.list` returning several transfers on one day (fixture: one
   same-day + two weekend catch-ups), the engine matches each day to the payout whose charge window
   covers it — and reconciles a multi-day weekend payout to the **sum** of the covered days' eligible
   amounts, not to a single day.
10. **Reconciliation anchor:** when `|orders_total − reconciliation_total| > $1` (both the Aug 1–2
    undercount and the Aug 3 overstatement), the engine reconciles to the reconciliation report +
    payout and logs the Orders variance — it never posts off raw order tenders.
