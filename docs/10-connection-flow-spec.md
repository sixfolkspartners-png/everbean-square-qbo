# 10 — Connection Flow Spec (real OAuth, seamless UX)

The connection experience must be a **real OAuth redirect**, not a stub. Click → land on
the provider's own hosted login → approve → return connected. Visual reference:
`docs/connect_flow_storyboard.html` (extract from the delivery). Build exactly that journey.

## Why it currently feels disjointed
The redirect only works when a **registered OAuth app** exists for each provider with
DailyLedger's callback URL whitelisted. If `client_id` isn't configured, the button has
nowhere to send the user and falls back to a stub — the disjointed feeling. Fix: implement
the real flow **and** make the un-configured state honest (see "Env-gating" below), so it's
never a broken redirect.

## Routes (per provider: `square`, `qbo`, `xero`)
- `GET /connect/{provider}/start`
  - Generate a random `state` (store in session, for CSRF). For Xero, also generate a PKCE
    `code_verifier`/`code_challenge`.
  - Build the provider **authorize URL** with `client_id`, exact `redirect_uri`, `scope`,
    `state` (+ `code_challenge` for Xero) and **302 redirect** to it. (Optional: a ~300ms
    interstitial page "Taking you to {Provider} to sign in securely…" then JS-redirect — nicer,
    not required.)
- `GET /connect/{provider}/callback`
  - Verify `state` matches the session (reject if not). Handle `error`/`denied` (user cancelled) →
    render the friendly retry state, don't 500.
  - Exchange `code` → tokens at the provider **token URL** (Basic-auth client creds; PKCE verifier
    for Xero). Store `access_token`+`refresh_token` **encrypted**, plus token expiry.
  - Capture and store the provider's org identifier: Square `merchant_id` (+ list locations),
    QuickBooks `realmId` (returned as a query param on the callback), Xero `tenant_id`
    (from `/connections`). Kick off the display-name resolution (spec 09).
  - Redirect to the next onboarding step (or back to Connections with a success flash).

## Provider specifics
| | Square | QuickBooks (Intuit) | Xero |
|---|---|---|---|
| Authorize | `connect.squareup.com/oauth2/authorize` | `appcenter.intuit.com/connect/oauth2` | `login.xero.com/identity/connect/authorize` (PKCE) |
| Token | `connect.squareup.com/oauth2/token` | `oauth.platform.intuit.com/oauth2/v1/tokens/bearer` | `identity.xero.com/connect/token` |
| Scopes | `ORDERS_READ PAYMENTS_READ GIFTCARDS_READ PAYOUTS_READ MERCHANT_PROFILE_READ` | `com.intuit.quickbooks.accounting` | `accounting.transactions accounting.settings offline_access` |
| Org id | `merchant_id` + locations | `realmId` (callback param) | `tenant_id` (`/connections`) |
| Notes | long-lived access token + refresh | refresh token **rotates** (persist new one, per engine) | must pick a tenant/organisation |

Redirect URIs must be **exact string matches** of what's registered in each provider's app
(e.g. `https://app.dailyledger.co/connect/square/callback`). One per provider per environment.

## UX states (match the storyboard, component 6 in spec 09)
1. **Not connected** — card with provider logo, one-line "what we access (read-only)", a single
   primary **Connect** button.
2. **Interstitial** (optional) — "Taking you to {Provider} to sign in securely…" + spinner.
3. **Provider hosted page** — Square/Intuit/Xero render this; we don't. (User logs in there — never
   in DailyLedger.)
4. **Return / success** — "{Provider} connected · matching your accounts…" then the connected state.
5. **Connected** — green check + what's connected (merchant/company/tenant + location count).
6. **Denied / error** — "Connection cancelled" or "Something went wrong" + **Try again** (re-enters
   step 1). Never a stack trace.
7. **Reconnect** — when a stored token is invalid/expired, the card shows an amber "Reconnect"
   state and the same flow refreshes it.

## Env-gating (kills the "disjointed stub" feeling honestly)
- If `{PROVIDER}_CLIENT_ID` is unset, the Connect button renders a disabled state labelled
  **"Not configured — add {Provider} app credentials"** (admin-only hint), instead of a redirect
  that goes nowhere. Demo/seed mode says so explicitly rather than faking a connection.
- Config per provider: `{PROVIDER}_CLIENT_ID`, `{PROVIDER}_CLIENT_SECRET`, `{PROVIDER}_REDIRECT_URI`.

## One-time human setup (the actual gate)
Register a **Square OAuth app**, an **Intuit app**, and (for the Xero adapter) a **Xero app** —
each with the exact callback URL whitelisted, and put the client id/secret/redirect in env.
Reference: the go-live playbook (to be written) + `engine/docs/INTUIT_SETUP.md`.

## Acceptance
1. With real credentials in env, clicking Connect performs a real 302 to the provider's hosted
   login; approving returns to the callback and stores encrypted tokens; the org id + locations are
   captured; the connected state renders.
2. `state` is verified (CSRF); Xero uses PKCE; redirect_uri matches exactly.
3. User-cancel and provider error render the friendly retry state, not a 500.
4. Reconnect refreshes an expired connection.
5. Without credentials, the button shows the honest "not configured" state — no broken redirect.
6. No production code path "connects" an account without completing real OAuth.
