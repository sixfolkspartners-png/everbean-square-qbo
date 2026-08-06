# From EverBean fix → product: "Accountant-grade" Square→QuickBooks sync
## Product & monetization strategy

**Prepared:** July 31, 2026 · for Andrew (EverBean Coffee Co)
**Working name:** *DailyLedger* (placeholder)
**One-liner:** *Books your POS sales the way an accountant would — a paid sales receipt, exact tax, tips & gift cards as liabilities, reconciled to the penny — not messy invoices you clean up later.*

---

## 1. Why this is a real business, not just a script

We didn't invent a market — we walked into a proven one and found the leaders cutting the exact corners that caused your pain. People already pay $18–$1,199/month for tools that sync Square to QuickBooks. The wedge is **correctness**: during your build we *demonstrated*, with your live books, that the mainstream approaches misbook the money. That's a credibility asset most startups don't have on day one.

**Market is validated and segmented by volume/entity count:**

| Product | Price/mo | How it books | Notable gaps (our openings) |
|---|---|---|---|
| **Amaka** | Free / $18 / $49 | **As invoices** (A/R) | Same phantom-A/R problem we rejected; customer has to clear receivables |
| **Commerce Sync** | $19 / $45 | Daily sales transfer | **No gift cards, no deposit detail**, no COGS |
| **Bookkeep** | $19 → $1,199 | Journal entries + deposits | Upmarket/complex; deposit splitting is a $3.99/transfer add-on; sales-tax filing $75/filing |
| **Synder** | ~$48+ | Per-transaction sync | Heavier/reconciliation-oriented, not clean daily summaries |
| **DailyLedger (us)** | TBD | **SalesReceipt, exact tax, full liabilities, penny deposit tie-out** | — this is the pitch |

The two most common Square choices (Amaka, Commerce Sync) each have a concrete correctness gap we already solved for EverBean. That's the whole opening.

---

## 2. The wedge: "accountant-grade," and we can prove it

Every competitor claims "automated bookkeeping." Our differentiation is provable correctness, and we have the receipts from your build:

1. **SalesReceipt, not invoice** — cash sale, money to the bank, **no phantom Accounts Receivable** (Amaka's approach creates A/R that someone has to clear).
2. **Exact sales tax** — we override QuickBooks' recomputed tax to match **what Square actually collected**, so what you remit equals what you took. Competitors recompute or bundle it.
3. **Full liability handling** — tips, gift card **purchases *and* redemptions** each hit the right liability (Commerce Sync ignores gift cards entirely).
4. **Penny-perfect deposit tie-out** — Square fees + Over/Short so the receipt equals the actual bank deposit and auto-reconciles.
5. **Transparency** — a daily "does it tie out?" reconciliation view with anomaly flags, instead of a black box.

Positioning line for accountants: **"The only Square→QuickBooks sync your bookkeeper won't have to fix."**

---

## 3. Future-proof architecture (build once, expand sideways)

The EverBean pipeline is already the right shape — we generalize it into a platform with four clean seams so new POS systems and ledgers are adapters, not rewrites.

```
   SOURCE adapters          CANONICAL model            DESTINATION adapters
  ┌───────────────┐      ┌──────────────────┐        ┌────────────────────┐
  │ Square  ✅     │─────▶│ DailySalesSummary │───────▶│ QuickBooks Online ✅│
  │ Clover        │      │  gross, discounts │        │ Xero               │
  │ Toast         │      │  tax, tips, gift  │        │ QuickBooks Desktop │
  │ Shopify       │      │  cards, fees,     │        │ Zoho / NetSuite    │
  │ Stripe        │      │  deposit, over/sh │        │                    │
  └───────────────┘      └──────────────────┘        └────────────────────┘
                                  │
                    ┌─────────────┴──────────────┐
                    │  CORRECTNESS ENGINE (moat)  │  reconciliation, over/short,
                    │  deposit match, tax override│  anomaly detection, audit log
                    └────────────────────────────┘
```

**Platform services around it:**
- **Tenant + connection vault** — encrypted OAuth tokens per customer (Square + ledger), auto-refresh/rotation (already solved).
- **Mapping engine** — per-tenant item/account/tax mapping, generalized from EverBean's `config`. Onboarding **auto-detects or creates** the item template (the "Square sales item / Fees / Over-and-Short" set) so setup is one click.
- **Orchestrator** — per-tenant daily jobs, idempotent (DocNumber), retries, backfill.
- **Reconciliation dashboard** — status per tenant per day, tie-out, error resolution. This is the trust surface *and* the accountant's daily home screen.
- **Billing** (Stripe) + **monitoring/alerting**.

Nothing here is exotic — it's the EverBean code plus multi-tenancy, a token vault, an onboarding flow, and a dashboard.

---

## 4. Monetization

**Model:** SaaS subscription, per location, mirroring the market but priced on *correctness + transparency*, with an accountant channel as the real growth engine.

| Tier | Target | Price (indicative) | Included |
|---|---|---|---|
| **Solo** | 1 location | ~$15/mo | Square→QBO, daily receipt, reconciliation view |
| **Multi** | 2–10 locations | ~$39/mo | Multi-location, gift cards, deposit tie-out, backfill |
| **Firm** | Bookkeepers/accountants | per-client (e.g. $9/client) or $99+/mo | Manage many clients, white-label, bulk onboarding, alerts |
| **Self-host (open-core)** | Technical DIY | Free | The EverBean repo, community support — a funnel to managed |

**Revenue levers beyond subscription:** historical backfill (one-time), premium reconciliation/close-assist, and eventually a sales-tax filing hand-off (Bookkeep charges $75/filing — a proven add-on).

**Why the accountant/firm channel is the move:** one bookkeeper onboards 20–50 clients. Bookkeep and Amaka both run partner programs because it's the cheapest path to volume. Your correctness story is *aimed at exactly the person who feels the pain of bad syncs* — the bookkeeper cleaning them up.

**Open-core angle (optional but powerful):** give away the single-tenant self-host version (what EverBean already has) to build trust and a developer funnel; sell the managed multi-tenant platform + dashboard + support to everyone who doesn't want to run cron and rotate tokens. Turns "we built our own" into a marketing asset.

---

## 5. Roadmap

- **Phase 0 — EverBean as design partner (now).** Finish the QBO app, run it live for EverBean, harden the single-tenant pipeline. Your books are the reference implementation and first testimonial.
- **Phase 1 — Multi-tenant MVP (Square→QBO only).** Onboarding OAuth flows, token vault, mapping auto-setup, reconciliation dashboard, Stripe billing. Pilot with 5–10 shops (your network + a couple of local bookkeepers).
- **Phase 2 — Channel + distribution.** Accountant/firm tier, **QuickBooks App Store** and **Square App Marketplace** listings (where competitors get discovered), add **Xero** as a second ledger.
- **Phase 3 — Breadth.** Second POS source (Clover or Toast — coffee/restaurant adjacency to EverBean), sales-tax filing add-on, scale the firm channel.

---

## 6. Risks & how we hold an edge

- **Incumbents & platform risk.** Intuit or Square could build this; incumbents have distribution. *Edge:* correctness reputation + accountant channel + multi-source breadth + a trust/transparency UX. This is a GTM-and-brand moat, not a patent — so execution and the accountant relationship matter most.
- **Support & accounting edge cases.** Every tenant's chart of accounts differs. *Edge:* the mapping engine + auto-template + reconciliation dashboard turn support into self-serve; the firm channel concentrates expertise.
- **Sales-tax liability.** Booking tax wrong is a real-world harm. *Edge:* our "match what Square collected" stance is the conservative, correct one — lean into it, and keep filing as a *hand-off*, not a promise, early on.
- **Low switching cost cuts both ways.** Easy for customers to leave — but also easy to *win* from Amaka/Commerce Sync with a "we book it right" migration.

---

## 7. Recommendation — pick the ambition, then I build to it

Three honest paths, smallest to biggest:

- **A. Sharpen the tool** — polish the open-source EverBean pipeline, publish it, let it quietly generate goodwill/leads. Near-zero cost. Optionality without commitment.
- **B. Micro-SaaS** — Phase 1 MVP, a few dozen paying shops, run it as a profitable side product. Realistic with the code we have + an onboarding UI + dashboard.
- **C. Venture** — go after the accountant channel hard, multi-POS/multi-ledger, raise or bootstrap toward the Bookkeep tier of the market.

My read: **B, aimed so it can become C** — the architecture above is built for that from day one, and EverBean de-risks it as the live proof. The single most valuable next artifact is the **multi-tenant onboarding + reconciliation dashboard**, because that's the line between "a script" and "a product people pay for."

---

### Sources
- Amaka Square→QuickBooks — https://amaka.com/integrations/square/quickbooks/
- Commerce Sync (Square) — https://www.commercesync.com/square
- Bookkeep pricing — https://www.bookkeep.com/pricing
- Synder QuickBooks POS guide — https://synder.com/blog/quickbooks-pos-software/
