"""Draft-and-approve: render drafted JEs for review, and post them to QuickBooks
only on approval. Idempotent (post_batch queries DocNumber first)."""
from __future__ import annotations
import json
from decimal import Decimal
from . import vault
from .models import Org, Connection, SyncRun, Approval
from .qbo import QboDestination


def load(session, token: str):
    appr = session.query(Approval).filter_by(token=token).first()
    if not appr:
        return None, None, []
    org = session.get(Org, appr.org_id)
    runs = (session.query(SyncRun)
            .filter_by(org_id=appr.org_id, business_date=appr.business_date)
            .order_by(SyncRun.batch).all())
    drafts = []
    for r in runs:
        detail = json.loads(r.detail_json or "{}")
        body = detail.get("body")
        lines = []
        if body:
            for ln in body["Line"]:
                jd = ln["JournalEntryLineDetail"]; amt = Decimal(str(ln["Amount"]))
                lines.append({"type": jd["PostingType"], "amount": amt, "desc": ln.get("Description", "")})
        d = sum(Decimal(str(l["amount"])) for l in lines if l["type"] == "Debit")
        c = sum(Decimal(str(l["amount"])) for l in lines if l["type"] == "Credit")
        drafts.append({"batch": r.batch, "status": r.status, "doc": r.doc_number,
                       "qbo_id": r.qbo_id, "deposit": r.deposit, "lines": lines,
                       "debit": d, "credit": c, "balanced": d == c})
    return appr, org, drafts


def post_approved(session, token: str) -> dict:
    appr = session.query(Approval).filter_by(token=token).first()
    if not appr:
        return {"error": "not_found"}
    if appr.status == "posted":
        return {"status": "already_posted"}
    conn = session.query(Connection).filter_by(org_id=appr.org_id, provider="qbo").first()
    dest = QboDestination(conn); dest.refresh()
    conn.refresh_token_enc = vault.encrypt(dest.refresh_token); session.commit()

    posted = []
    runs = (session.query(SyncRun)
            .filter_by(org_id=appr.org_id, business_date=appr.business_date, status="drafted").all())
    for run in runs:
        detail = json.loads(run.detail_json or "{}")
        body = detail.get("body")
        if not body:
            continue
        res = dest.post_batch(body, dry_run=False)
        run.status = res["status"]          # posted | skipped
        run.qbo_id = res.get("qbo_id", "")
        detail.pop("body", None)            # clear the stored draft after posting
        run.detail_json = json.dumps(detail)
        posted.append({"batch": run.batch, "status": run.status, "qbo_id": run.qbo_id})
    appr.status = "posted"; session.commit()
    return {"status": "posted", "batches": posted}


def reject(session, token: str) -> dict:
    appr = session.query(Approval).filter_by(token=token).first()
    if not appr:
        return {"error": "not_found"}
    for run in (session.query(SyncRun)
                .filter_by(org_id=appr.org_id, business_date=appr.business_date, status="drafted").all()):
        run.status = "rejected"
    appr.status = "rejected"; session.commit()
    return {"status": "rejected"}
