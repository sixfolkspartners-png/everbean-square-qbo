# QuickBooks (Intuit) app setup — one time, ~15–20 minutes

This is the only piece I can't do for you: it authorizes the pipeline to write
to *your* QuickBooks. Do these steps once and paste the results into the repo's
GitHub secrets. After that it's hands-off.

> Intuit occasionally renames buttons; the concepts below don't change:
> create an app → get **Production** keys → authorize once → capture the first
> **refresh token** and your **realm (company) ID**.

## 1. Create the Intuit Developer app
1. Go to **developer.intuit.com** → sign in with your QuickBooks login → **Dashboard**.
2. **Create an app** → choose **QuickBooks Online and Payments**.
3. Name it e.g. "EverBean Sales Sync".
4. Under the app, open **Keys & credentials**. There are two key sets:
   **Development** (sandbox) and **Production** (your real books). You want
   **Production** — but Intuit requires the app to go through a short
   "Production" enablement (fill in basic app info). Do that so Production keys
   appear.
5. Copy the **Client ID** and **Client Secret** (Production).

## 2. Add a redirect URI
In the app's **Keys & credentials**, add a redirect URI. For the quick
token-capture method below, use:
```
https://developer.intuit.com/v2/OAuth2Playground/RedirectUrl
```

## 3. Capture the first refresh token + realm ID (OAuth Playground)
1. Open the **OAuth 2.0 Playground** (linked from your app, or search
   "Intuit OAuth Playground").
2. Select your app, scope **`com.intuit.quickbooks.accounting`**.
3. Click **Get authorization code** → choose the **EverBean** company → approve.
4. Click **Get tokens**. You'll see an **access token** (ignore, it's short-lived)
   and a **refresh token** — copy the refresh token.
5. The **Realm ID / Company ID** shown is `9130357334018486` for EverBean
   (already in config; confirm it matches).

## 4. Put the values into GitHub secrets
In the repo → **Settings → Secrets and variables → Actions → New repository secret**,
add:

| Secret | Value |
|---|---|
| `QBO_CLIENT_ID` | from step 1 |
| `QBO_CLIENT_SECRET` | from step 1 |
| `QBO_REFRESH_TOKEN` | from step 3 |
| `QBO_REALM_ID` | `9130357334018486` |
| `SQUARE_ACCESS_TOKEN` | your Square production token |
| `GH_PAT_SECRETS` | a fine-grained PAT (see step 6) |

## 5. Fill in the remaining QuickBooks IDs
Run the lookup helper once (locally, with the three QBO secrets exported) to get
the last IDs, then add them as secrets:
```
python -m scripts.lookup_ids
```
Add: `QBO_ITEM_SQUARE_FEES`, `QBO_ITEM_OVER_SHORT`, `QBO_DEPOSIT_ACCOUNT_ID`,
`QBO_TAX_CODE_ID`, `QBO_TAX_RATE_ID`.

## 6. PAT for token rotation
QuickBooks refresh tokens rotate (~100 days). So the job can save the new one:
1. GitHub → **Settings → Developer settings → Fine-grained tokens** → generate one
   scoped to **this repo only**, with **Secrets: Read and write**.
2. Add it as the secret `GH_PAT_SECRETS`.

## 7. Test before going live
From the repo's **Actions** tab → **EverBean daily sales sync** → **Run workflow**,
set a date (e.g. `2026-07-27`) and **dry_run = true**. It builds the SalesReceipt
and prints it without posting. When that looks right, run it with dry_run off for
one day, check it in QuickBooks, then let the daily schedule take over.
