# CLAUDE.md — DailyLedger

You are picking up a project mid-stream. **Read the four docs below in order before writing code.** They contain the entire history and every decision already made, so you do not need to re-derive anything or ask the user to repeat context.

1. `docs/00-context-and-history.md` — the whole story: the problem, everything already tested and *ruled out with evidence*, and why we're here. Read this first.
2. `docs/01-correctness-spec.md` — the accounting rules that MUST hold. These are non-negotiable and are the product's entire reason to exist. Do not "simplify" them away.
3. `docs/03-architecture.md` — the multi-tenant architecture, data model, and the stack (already chosen — don't relitigate).
4. `docs/04-prototype-spec.md` — exactly what to build now, screen by screen, with acceptance criteria.

Then follow `BUILD_PLAN.md` — an ordered, autonomous execution plan with checkpoints. Work through it top to bottom.

## What this is
A micro-SaaS (Path B) that syncs Square POS sales into QuickBooks Online **correctly** — as a paid SalesReceipt with exact tax, tips & gift cards booked to liabilities, and penny-perfect deposit reconciliation. The differentiation is *provable correctness* vs. incumbents (Amaka books as invoices; Commerce Sync ignores gift cards/deposits). See `docs/02-product-strategy.md`.

## Your job right now
Generalize the working single-tenant engine in `engine/` into a **multi-tenant web app with onboarding + a reconciliation dashboard** — the artifact that turns "a script" into "a product." Build the prototype defined in `docs/04-prototype-spec.md`.

## The engine is already built and proven
`engine/` is the EverBean single-tenant pipeline. Its accounting logic is validated offline (`cd engine && python tests/test_transform.py` — all 7 sample days pass: exact-tax override, correct taxable flags, Over/Short capture, receipt total = Square total_collected − gift-card redemptions). **Reuse `engine/src/transform.py` and `engine/src/reconcile.py` as-is where possible — that's the correctness core.** Do not rewrite the accounting math; wrap it in multi-tenancy.

## Ground rules
- **Preserve correctness.** If a change would make the books wrong (e.g. dropping the tax override, booking tax to income, ignoring gift-card redemptions), stop — that's the product.
- **Pre-made decisions live in `docs/decisions.md`.** Follow them; don't re-open settled questions.
- **Idempotency is sacred.** Every posted day carries `DocNumber = SQ-YYYYMMDD`; query before posting so re-runs never duplicate.
- **Secrets never touch git.** OAuth tokens are encrypted at rest (see architecture).
- **Ask the user only for things only they can provide** (OAuth app credentials, hosting choices). Everything technical is already decided — build it.
- Tests + a working `docker compose up` demo are part of "done," per the prototype spec.

## Human-only inputs still outstanding (don't block the build on these — stub/config them)
- Intuit Developer app + Square OAuth app credentials (see `engine/docs/INTUIT_SETUP.md`).
- Deposit-account and fee-timing choices per tenant (captured in onboarding UI).
