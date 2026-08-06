"""DailyLedger web shell (FastAPI): multi-tenant reconciliation dashboard + control
panel over the same models the pipeline writes. HTTP Basic Auth gates every route
once AUTH_PASS is set in the environment (leave it unset and the app stays open —
so you never lock yourself out before configuring it). /health and the OAuth
callbacks stay open (Render's health check + Intuit/Square redirects need them; the
callbacks are already protected by an unguessable state token).
"""
from __future__ import annotations
import os, json, base64, secrets
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from .models import make_session, Org, Connection, SyncRun, Approval
from . import connect, approvals

app = FastAPI(title="DailyLedger")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
Session = make_session()   # DATABASE_URL in prod, sqlite file locally

_pending_state: dict[str, int] = {}   # oauth state -> org_id (dev-only; use signed session in prod)

AUTH_USER = os.environ.get("AUTH_USER", "everbean")
AUTH_PASS = os.environ.get("AUTH_PASS", "")     # set this in Render to turn auth ON
_OPEN = ("/health", "/callback/qbo", "/callback/square")

# ledger key -> friendly label for the account-map view
FRIENDLY = {
    "checking": "Bank / deposit account",
    "sales_income": "Sales of Product Income",
    "discounts": "Discounts given",
    "sales_tax_payable": "Square Sales Tax Payable",
    "tips_payable": "Tips Payable",
    "gift_card_liability": "Gift Card Outstanding",
    "square_fees": "Square Fees",
    "over_short": "Over and Short",
}


@app.middleware("http")
async def _auth(request: Request, call_next):
    p = request.url.path
    if AUTH_PASS and not any(p == o or p.startswith(o) for o in _OPEN):
        hdr = request.headers.get("authorization", "")
        ok = False
        if hdr.startswith("Basic "):
            try:
                u, _, pw = base64.b64decode(hdr[6:]).decode().partition(":")
                ok = secrets.compare_digest(u, AUTH_USER) and secrets.compare_digest(pw, AUTH_PASS)
            except Exception:
                ok = False
        if not ok:
            return Response("Authentication required.", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="DailyLedger"'})
    return await call_next(request)


@app.get("/health")
def health():
    return {"ok": True}


def _ensure_org(s):
    org = s.query(Org).filter_by(name="EverBean Coffee Co").first()
    if not org:
        org = Org(name="EverBean Coffee Co", timezone="America/Denver",
                  posting_format="journal_entry", rollout_mode="draft_approve")
        s.add(org); s.commit()
    return org


@app.get("/setup")
def setup():
    """Bootstrap the EverBean org row if it doesn't exist yet, then go to the dashboard."""
    _ensure_org(Session())
    return RedirectResponse("/", status_code=303)


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    s = Session()
    orgs = s.query(Org).all()
    data = []
    for o in orgs:
        runs = (s.query(SyncRun).filter_by(org_id=o.id)
                .order_by(SyncRun.business_date.desc(), SyncRun.batch).limit(40).all())
        run_rows = []
        for r in runs:
            try:
                detail = json.loads(r.detail_json or "{}")
            except Exception:
                detail = {}
            note = ""
            if r.status == "review":
                note = f"implied ${detail.get('implied', '?')} vs deposit ${detail.get('deposit', '?')}"
            elif detail.get("lines"):
                note = f"{detail['lines']} lines"
            run_rows.append({"date": r.business_date, "batch": r.batch, "status": r.status,
                             "doc": r.doc_number, "deposit": r.deposit, "qbo_id": r.qbo_id, "note": note})
        posted = sum(1 for r in runs if r.status == "posted")
        review = sum(1 for r in runs if r.status == "review")
        drafted = sum(1 for r in runs if r.status == "drafted")

        conns = []
        amap_rows = []
        for c in o.connections:
            conns.append({"provider": c.provider, "environment": c.environment,
                          "realm": c.realm_or_location, "status": c.status,
                          "has_token": bool(c.refresh_token_enc), "n_accts": len(c.account_map)})
            if c.provider == "qbo":
                m = c.account_map
                for k, label in FRIENDLY.items():
                    if k in m:
                        amap_rows.append({"key": k, "label": label, "id": m[k]})
        has_qbo = any(c["provider"] == "qbo" and c["has_token"] for c in conns)
        has_square = any(c["provider"] == "square" and c["has_token"] for c in conns)

        pend = (s.query(Approval).filter_by(org_id=o.id, status="pending")
                .order_by(Approval.business_date.desc()).all())
        pending = [{"date": a.business_date, "token": a.token} for a in pend]

        data.append({"org": o, "conns": conns, "runs": run_rows, "posted": posted,
                     "review": review, "drafted": drafted, "pending": pending, "amap": amap_rows,
                     "has_qbo": has_qbo, "has_square": has_square})
    return templates.TemplateResponse(request, "dashboard.html",
                                      {"data": data, "auth_on": bool(AUTH_PASS)})


@app.get("/run", response_class=HTMLResponse)
def run_route(org_id: int, date: str):
    """Run one business day through the pipeline (draft-and-approve builds the JEs
    and returns a review link; nothing posts until approved)."""
    from .pipeline import run_day
    try:
        result = run_day(Session(), org_id, date)
    except Exception as e:
        return HTMLResponse(
            f"<div style='font-family:system-ui,Arial,sans-serif;max-width:680px;margin:40px auto'>"
            f"<h2>Couldn't run {date}</h2>"
            f"<pre style='background:#fdecec;padding:12px;border-radius:8px'>{type(e).__name__}: {e}</pre>"
            f"<p style='color:#555'>Live days need a Square connection; without one only the "
            f"built-in sample days are available.</p>"
            f"<p><a href='/'>&larr; Back to dashboard</a></p></div>", status_code=400)
    link = result.get("review") or {}
    rp = link.get("review_path", "")
    body = f"<div style='font-family:system-ui,Arial,sans-serif;max-width:680px;margin:40px auto'>"
    body += f"<h2>Ran {result['org']} &middot; {result['date']} &middot; {result['rollout']}</h2>"
    body += f"<pre style='background:#f5f5f5;padding:12px;border-radius:8px;overflow:auto'>{json.dumps(result['batches'], indent=2)}</pre>"
    if rp:
        body += f"<p><a href='{rp}'>Review &amp; approve &rarr;</a></p>"
    body += f"<p><a href='/'>&larr; Back to dashboard</a></p></div>"
    return HTMLResponse(body)


@app.post("/settings/rollout")
def set_rollout(org_id: int):
    """Toggle the org between draft-and-approve and auto-post."""
    s = Session()
    o = s.get(Org, org_id)
    if o:
        o.rollout_mode = "auto_post" if o.rollout_mode == "draft_approve" else "draft_approve"
        s.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/disconnect/{provider}")
def disconnect(provider: str, org_id: int):
    """Remove a provider connection (deletes the stored encrypted token). Reconnect
    via the Connect button to re-establish it."""
    s = Session()
    c = s.query(Connection).filter_by(org_id=org_id, provider=provider).first()
    if c:
        s.delete(c); s.commit()
    return RedirectResponse("/", status_code=303)


@app.get("/review/{token}", response_class=HTMLResponse)
def review(request: Request, token: str):
    s = Session()
    appr, org, drafts = approvals.load(s, token)
    if not appr:
        return HTMLResponse("<p>Approval not found.</p>", status_code=404)
    return templates.TemplateResponse(request, "review.html",
                                      {"appr": appr, "org": org, "drafts": drafts})


@app.post("/approve/{token}")
def approve(token: str):
    approvals.post_approved(Session(), token)
    return RedirectResponse(f"/review/{token}", status_code=303)


@app.post("/reject/{token}")
def reject_route(token: str):
    approvals.reject(Session(), token)
    return RedirectResponse(f"/review/{token}", status_code=303)


@app.get("/connect/qbo")
def connect_qbo(org_id: int):
    """Kick off the QuickBooks OAuth: redirect the tenant to Intuit to approve."""
    url, state = connect.qbo_authorize_url()
    _pending_state[state] = org_id
    return RedirectResponse(url)


@app.get("/callback/qbo")
def callback_qbo(code: str, realmId: str, state: str):
    """Intuit redirects here after approval: exchange code, provision the chart of
    accounts, and store the encrypted Connection."""
    org_id = _pending_state.pop(state, None)
    if org_id is None:
        return HTMLResponse("<p>Invalid or expired state.</p>", status_code=400)
    tok = connect.qbo_exchange_code(code)
    boot = connect.bootstrap_qbo_accounts(tok["access_token"], realmId, connect.QBO.ENV)
    s = Session()
    connect.save_qbo_connection(s, org_id, realmId, tok, boot["account_map"])
    return RedirectResponse("/", status_code=303)


@app.get("/connect/square")
def connect_square(org_id: int):
    from .settings import SQUARE
    import urllib.parse, secrets as _secrets
    state = _secrets.token_urlsafe(16); _pending_state[state] = org_id
    q = {"client_id": SQUARE.CLIENT_ID, "scope": SQUARE.SCOPE,
         "session": "false", "redirect_uri": SQUARE.REDIRECT_URI, "state": state}
    return RedirectResponse(f"{SQUARE.AUTHORIZE}?{urllib.parse.urlencode(q)}")
