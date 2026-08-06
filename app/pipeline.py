"""Per-tenant daily pipeline: pull (source) -> reconcile gate -> post (destination),
respecting the org's rollout mode, and recording a SyncRun per batch.

The reconcile gate enforces the hard rule: each batch must tie to its deposit to
the penny, else it is flagged 'review' and NOT posted.
"""
from __future__ import annotations
import json, secrets
from decimal import Decimal
from . import vault
from .models import Org, Connection, SyncRun, Approval
from .square_source import SquareSource, SampleSource
from .qbo import QboDestination

TOL = Decimal("0.005")


def _conn(session, org_id, provider):
    return session.query(Connection).filter_by(org_id=org_id, provider=provider).first()


def run_day(session, org_id: int, business_date: str) -> dict:
    org = session.get(Org, org_id)
    dest_conn = _conn(session, org_id, "qbo")
    src_conn = _conn(session, org_id, "square")
    if not (org and dest_conn):
        raise ValueError("org or QBO connection missing")

    # live Square pull when the tenant has a Square token; else offline sample
    sq_token = vault.decrypt(src_conn.refresh_token_enc) if (src_conn and src_conn.refresh_token_enc) else None
    src = SquareSource(src_conn, sq_token) if sq_token else SampleSource(src_conn)
    db = src.pull_day(business_date)

    dest = QboDestination(dest_conn)
    new_refresh = dest.refresh()
    # persist rotated refresh token (encrypted)
    dest_conn.refresh_token_enc = vault.encrypt(new_refresh)
    session.commit()

    dry = org.rollout_mode == "draft_approve"   # draft-approve => build but don't post
    results = {}
    for batch_name, batch in (("cc", db.cc), ("cash", db.cash)):
        # reconcile gate: computed deposit must tie to the source deposit
        implied = batch.implied_deposit()
        tie_ok = abs(implied - batch.deposit) <= TOL
        run = (session.query(SyncRun)
               .filter_by(org_id=org_id, business_date=business_date, batch=batch_name).first())
        if not run:
            run = SyncRun(org_id=org_id, business_date=business_date, batch=batch_name)
            session.add(run)
        run.deposit = str(batch.deposit)

        if not tie_ok:
            run.status = "review"
            run.detail_json = json.dumps({"reason": "did_not_reconcile",
                                          "implied": str(implied), "deposit": str(batch.deposit)})
            results[batch_name] = {"status": "review", "implied": str(implied), "deposit": str(batch.deposit)}
            continue

        body = dest.build_cc_je(business_date, batch) if batch_name == "cc" else dest.build_cash_je(business_date, batch)
        res = dest.post_batch(body, dry_run=dry)
        run.status = res["status"]           # drafted | posted | skipped
        run.doc_number = res.get("doc_number", "")
        run.qbo_id = res.get("qbo_id", "")
        detail = {"lines": len(body["Line"])}
        if res["status"] == "drafted":
            detail["body"] = body            # keep the draft to post on approval
        run.detail_json = json.dumps(detail)
        results[batch_name] = {k: v for k, v in res.items() if k != "body"}

    # draft-and-approve: if anything was drafted, ensure a one-click approval token
    review = None
    if any(b.get("status") == "drafted" for b in results.values()):
        appr = session.query(Approval).filter_by(org_id=org_id, business_date=business_date).first()
        if not appr:
            appr = Approval(org_id=org_id, business_date=business_date, token=secrets.token_urlsafe(24))
            session.add(appr)
        elif appr.status != "pending":
            appr.status = "pending"          # re-drafted; reopen
        review = {"token": appr.token, "review_path": f"/review/{appr.token}"}

    session.commit()
    return {"org": org.name, "date": business_date, "rollout": org.rollout_mode,
            "review": review, "batches": results}
