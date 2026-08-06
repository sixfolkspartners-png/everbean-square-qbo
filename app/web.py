"""DailyLedger web shell (FastAPI). Multi-tenant reconciliation dashboard over the
same models the pipeline writes. Connect flows are stubbed to the real OAuth URLs
(Phase-A wires the callback + token exchange). Account names only — never raw IDs.
"""
from __future__ import annotations
import os, json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from .models import make_session, Org, Connection, SyncRun
from . import connect, approvals

app = FastAPI(title="DailyLedger")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
Session = make_session()   # DATABASE_URL in prod, sqlite file locally

_pending_state: dict[str, int] = {}   # oauth state -> org_id (dev-only; use signed session in prod)


def _mask(c: Connection) -> dict:
    return {"provider": c.provider, "environment": c.environment,
            "realm_or_location": c.realm_or_location, "status": c.status,
            "has_token": bool(c.refresh_token_enc), "accounts_mapped": len(c.account_map)}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/setup", response_class=HTMLResponse)
def setup():
    """One-time bootstrap: ensure the EverBean org row exists, then offer connect links.
    (The deployed instance has no seed step; this stands in for `python -m app.demo`.)"""
    s = Session()
    org = s.query(Org).filter_by(name="EverBean Coffee Co").first()
    if not org:
        org = Org(name="EverBean Coffee Co", timezone="America/Denver",
                  posting_format="journal_entry", rollout_mode="draft_approve")
        s.add(org); s.commit()
    return HTMLResponse(
        f"<div style='font-family:system-ui,Arial,sans-serif;max-width:560px;margin:40px auto'>"
        f"<h2 style='margin-bottom:4px'>Org ready</h2>"
        f"<p style='color:#555'>{org.name} &middot; id {org.id} &middot; "
        f"{org.posting_format} &middot; {org.rollout_mode}</p>"
        f"<p><a href='/connect/qbo?org_id={org.id}'>Connect QuickBooks &rarr;</a></p>"
        f"<p><a href='/connect/square?org_id={org.id}'>Connect Square &rarr;</a></p>"
        f"<p style='margin-top:24px'><a href='/'>Dashboard</a></p></div>")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    s = Session()
    orgs = s.query(Org).all()
    data = []
    for o in orgs:
        runs = (s.query(SyncRun).filter_by(org_id=o.id)
                .order_by(SyncRun.business_date.desc(), SyncRun.batch).limit(20).all())
        posted = sum(1 for r in runs if r.status == "posted")
        review = sum(1 for r in runs if r.status == "review")
        data.append({"org": o, "conns": [_mask(c) for c in o.connections],
                     "runs": runs, "posted": posted, "review": review})
    return templates.TemplateResponse(request, "dashboard.html", {"data": data})


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
    import urllib.parse, secrets
    state = secrets.token_urlsafe(16); _pending_state[state] = org_id
    q = {"client_id": SQUARE.CLIENT_ID, "scope": SQUARE.SCOPE,
         "session": "false", "redirect_uri": SQUARE.REDIRECT_URI, "state": state}
    return RedirectResponse(f"{SQUARE.AUTHORIZE}?{urllib.parse.urlencode(q)}")
