# DailyLedger

Accountant-grade daily sales sync: **Square → QuickBooks Online**, booked the way an accountant would — a paid **SalesReceipt** (never an invoice), sales tax **exact to what Square collected**, tips & gift cards as **liabilities**, and **penny-perfect deposit reconciliation**. Built to beat the incumbents on the one thing they get wrong: correctness.

This repo is a **handoff package for Claude Code** to build the Path-B micro-SaaS prototype (multi-tenant onboarding + reconciliation dashboard) on top of a proven single-tenant engine.

## Start here (Claude Code)
Read `CLAUDE.md`, then work through `BUILD_PLAN.md`. Everything you need is in `docs/`:

- `docs/00-context-and-history.md` — full story; what was tested and ruled out, with evidence. **Read first.**
- `docs/01-correctness-spec.md` — the accounting rules that must hold (the product).
- `docs/02-product-strategy.md` — market, competitors, positioning, monetization.
- `docs/03-architecture.md` — multi-tenant design, data model, stack.
- `docs/04-prototype-spec.md` — exactly what to build + acceptance criteria.
- `docs/decisions.md` — pre-made choices; don't relitigate.

## What's already built
`engine/` — the working, offline-validated single-tenant pipeline (Square pull → SalesReceipt with tax override → idempotent post). Its accounting math is the correctness core; reuse it, don't rewrite it.

```
cd engine && python tests/test_transform.py   # all 7 sample days reconcile
```

## What to build
A FastAPI + Postgres + Jinja/htmx web app that wraps the engine in multi-tenancy: sign up an org, connect Square + QuickBooks via OAuth, auto-map the item template, run daily syncs, and see every day reconcile in a dashboard. A `seed` command loads a demo org (EverBean) with 7 reconciled days so the product is clickable with **no live credentials**. Full spec in `docs/04-prototype-spec.md`.

## Human inputs still needed (don't block on them)
- Intuit Developer app + Square OAuth app credentials (`engine/docs/INTUIT_SETUP.md`).
- Per-tenant deposit account + fee timing (captured in onboarding).

## Origin
Built for EverBean Coffee Co, whose live QuickBooks is the reference tenant. The native Square↔QuickBooks connector was unreliable; the connector-based alternatives misbook tax, tips, and gift cards. This does it right by calling the Intuit API directly.
