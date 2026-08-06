# Deploy DailyLedger — clear & easy (≈30 min to a live URL)

Host: **Render** (simplest managed host with a database + HTTPS out of the box).
The repo already has a `render.yaml` that provisions everything in one shot.

## Step 1 — put the code in GitHub
Create a new **private** GitHub repo and push this project to it
(`git init && git add . && git commit -m "DailyLedger" && git push`). Render
deploys from GitHub. (Nothing secret is committed — `.env` is gitignored.)

## Step 2 — deploy to Render (the one click)
1. Sign up at **render.com** → **New → Blueprint**.
2. Connect your GitHub and pick the repo. Render reads `render.yaml` and creates
   **two things automatically**: the web service (`dailyledger`) and a Postgres
   database (`dailyledger-db`), already wired together, with the token-vault key
   generated for you.
3. Click **Apply**. First build takes a few minutes. You'll get a URL like
   `https://dailyledger.onrender.com`.

## Step 3 — note your real URL
If Render gave you a different name (e.g. `dailyledger-abc.onrender.com`), open
the web service → **Environment** and update `QBO_APP_REDIRECT_URI` and
`SQUARE_APP_REDIRECT_URI` to match (…/callback/qbo and …/callback/square).

## Step 4 — get production keys + register redirect URIs
**QuickBooks** (developer.intuit.com → your app):
- Complete the **production** checklist (EULA, privacy policy, host/launch/
  disconnect URLs, category) to unlock Production keys.
- Add the redirect URI: `https://YOUR-APP.onrender.com/callback/qbo`
- Copy the **Production** Client ID + Secret.

**Square** (developer.squareup.com → your app):
- Add the redirect URL: `https://YOUR-APP.onrender.com/callback/square`
- Copy the **Production** Application ID + Secret.

## Step 5 — paste the four secrets into Render
Web service → **Environment** → fill the four `sync:false` values:
`QBO_APP_CLIENT_ID`, `QBO_APP_CLIENT_SECRET`, `SQUARE_APP_CLIENT_ID`,
`SQUARE_APP_CLIENT_SECRET`. Save → Render redeploys.

## Step 6 — create your org + connect
- Visit `https://YOUR-APP.onrender.com/` (the dashboard).
- Connect QuickBooks: open `…/connect/qbo?org_id=1` → approve in QuickBooks →
  it auto-provisions your chart of accounts and stores the encrypted connection.
- Connect Square: `…/connect/square?org_id=1` → approve.

## Step 7 — first day, draft-and-approve
- The org defaults to **draft-and-approve**: each day builds the journal entries
  and emails you a one-click **Review & approve** link; nothing posts until you
  click. Verify the first day in QuickBooks, then switch to auto-post if you want.

## Step 8 — schedule the morning run (optional now)
Point the existing morning job at `run_day` for "yesterday" and send the approval
email via Resend. (Already have the report email working; this swaps in the
approve link.)

---
### Local run (to try it first)
```
cd dailyledger
pip install -r app/requirements.txt
python -m app.demo        # seeds EverBean (sandbox) + posts a sample day
uvicorn app.web:app --reload   # http://localhost:8000
```

### Costs
Render starter web + starter Postgres ≈ a few dollars/month; free tier works to
test. No Apple-style revenue cut from Intuit for listing later.
