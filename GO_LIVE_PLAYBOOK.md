# GO_LIVE_PLAYBOOK.md — turn on real connections & post EverBean's first live day

This is an execution brief for **Claude Code**, with a clearly-marked checklist of
**browser steps only Andrew can do** (registering OAuth apps — an agent can't log into a
provider dashboard). Claude Code does the code/config/verify work and hands Andrew the human
checklist with the **exact callback URLs** derived from the deploy target.

Goal: the real OAuth flow from `docs/10-connection-flow-spec.md` lights up, and EverBean's
daily sales post to live QuickBooks — solving the original problem and dogfooding the product.

---

## The sequence (5 steps)
1. **Claude Code:** finalize env + redirect URIs + the connection flow, and print the exact
   callback URLs to whitelist.
2. **Andrew (browser):** register the Square, Intuit, (optional) Xero, and Stripe apps using
   those URLs; paste credentials into the secret store.
3. **Claude Code:** run `verify_setup`, deploy, confirm health.
4. **Andrew:** click Connect Square + Connect QuickBooks in the live app (the storyboard flow).
5. **Both:** post one real EverBean day (dry-run → real), confirm it reconciles in QuickBooks.

---

## PART 1 — Claude Code: wire it up (do first)
- **Decide BASE_URL** for each environment and use it everywhere the callback is built:
  - Local: `http://localhost:8000`
  - Prod: `https://<your-domain>` (pick the deploy host now; Fly/Render/Railway give a URL).
- **Config** (env, per provider): `SQUARE_CLIENT_ID/SECRET`, `QBO_CLIENT_ID/SECRET`,
  `XERO_CLIENT_ID/SECRET`, each `..._REDIRECT_URI`, plus `STRIPE_SECRET_KEY`,
  `STRIPE_WEBHOOK_SECRET`, `APP_SECRET_KEY`. Load from the platform secret store, never `.env` in git.
- **Redirect/callback URLs** the code will use (register these exactly in Part 2):
  - Square: `{BASE_URL}/connect/square/callback`
  - QuickBooks: `{BASE_URL}/connect/qbo/callback`
  - Xero: `{BASE_URL}/connect/xero/callback`
  - Stripe webhook: `{BASE_URL}/webhooks/stripe`
- **Implement/confirm** the real OAuth flow per `docs/10-connection-flow-spec.md` (start→redirect→
  callback→token exchange→encrypted store→org id capture→name resolution), the CSRF `state` check,
  PKCE for Xero, and the **"Not configured"** button state when a `client_id` is missing.
- **Add `python -m app.tools.verify_setup`** — for each configured provider: assert creds present,
  assert the redirect URI matches config, and (where possible) do a token/ping call; print a
  ✓/✗ table and the exact callback URLs. This is the go/no-go check.
- **Print the human checklist** (Part 2) filled in with the actual URLs for the chosen BASE_URL,
  so Andrew registers against real values, not placeholders.

## PART 2 — Andrew (browser, ~45 min): register the apps
> Exact button labels shift over time; the concepts don't. Use the callback URLs Claude Code prints.

### A. Square  (developer.squareup.com)
1. Sign in → **Create an application** → name it "DailyLedger".
2. Switch to **Production** credentials. Copy **Application ID** (= client id) and **Application Secret**.
3. Open **OAuth** → set the **Redirect URL** to `{BASE_URL}/connect/square/callback` → save.
4. Scopes are requested by the app at connect time: `ORDERS_READ PAYMENTS_READ GIFTCARDS_READ PAYOUTS_READ MERCHANT_PROFILE_READ`.
5. Paste `SQUARE_CLIENT_ID` + `SQUARE_CLIENT_SECRET` into the secret store.

### B. QuickBooks / Intuit  (developer.intuit.com) — see also `engine/docs/INTUIT_SETUP.md`
1. Sign in → **Create an app** → **QuickBooks Online and Payments**.
2. Enable **Production** keys (fill the short app info). Copy **Client ID** + **Client Secret**.
3. **Keys & credentials → Redirect URIs** → add `{BASE_URL}/connect/qbo/callback`.
4. Scope: `com.intuit.quickbooks.accounting`. Realm/company id is returned on connect
   (EverBean = `9130357334018486`).
5. Paste `QBO_CLIENT_ID` + `QBO_CLIENT_SECRET`.

### C. Xero  (developer.xero.com) — only needed for the Xero adapter
1. **New app → Web app**. Set redirect URI `{BASE_URL}/connect/xero/callback`.
2. Grant scopes `accounting.transactions accounting.settings offline_access` (PKCE).
3. Copy client id/secret → `XERO_CLIENT_ID` + `XERO_CLIENT_SECRET`.

### D. Stripe  (dashboard.stripe.com) — for billing (test mode first)
1. **Developers → API keys** → copy the **test** Secret key → `STRIPE_SECRET_KEY`.
2. Create Products/Prices for the plans (Solo/Multi/Firm) → put the Price IDs in config.
3. **Developers → Webhooks** → add endpoint `{BASE_URL}/webhooks/stripe` → copy the **Signing
   secret** → `STRIPE_WEBHOOK_SECRET`.

## PART 3 — Claude Code: verify & deploy
- Run `python -m app.tools.verify_setup` → every configured provider ✓.
- Deploy: one container + managed Postgres; run migrations; **exactly one instance** sets
  `RUN_SCHEDULER=1` (avoid double-posting); HTTPS enforced; secrets from the store.
- Confirm `/readyz` green and the Connections page shows real **Connect** buttons (not "Not configured").

## PART 4 — Connect EverBean & post the first live day
1. Andrew opens the live app → **Connect Square** → approve on squareup.com → **Connect QuickBooks**
   → approve on intuit.com (pick the EverBean company). Accounts auto-match.
2. Claude Code (or the UI): **dry-run** a recent day → confirm the SalesReceipt preview + reconciliation.
3. Post that one day for real → open it in QuickBooks → confirm: SalesReceipt (not invoice), tax
   exact, tips/gift cards in liabilities, total = the Square deposit. (This is the same gate we
   proved manually for 7/27.)
4. Turn the daily schedule on.

## Acceptance (go-live done)
- `verify_setup` all ✓; `/readyz` green on the deployed URL.
- Clicking Connect performs a real redirect to squareup.com / intuit.com and returns connected.
- EverBean posts a real day that reconciles in QuickBooks to the penny.
- Daily schedule runs on one instance; secrets only in the store; no stub "connection" path remains.

## Notes
- Register **both** localhost and prod callback URLs in each app so dev and prod both work.
- Square = the original EverBean goal; Xero/Stripe can follow once QBO is live.
- Keep the refresh-token rotation from the engine (QBO tokens rotate ~100 days) — the DB is the store.
