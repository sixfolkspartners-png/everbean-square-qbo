"""Draft-and-approve + review-window: render proposed JEs for review, let the user
resolve a genuine variance (book the residual / add a memo) right in the portal,
and post to QuickBooks only on approval. Idempotent (post_batch queries DocNumber
first)."""
from __future__ import annotations
import json
from decimal import Decimal
from . import vault
from .models import Org, Connection, SyncRun, Approval
from .qbo import QboDestination, _c

OVER_SHORT_DESC = "Over and short"


def _lines_of(body):
    lines = []
    for ln in body.get("Line", []):
        jd = ln["JournalEntryLineDetail"]
        lines.append({"type": jd["PostingType"], "amount": Decimal(str(ln["Amount"])),
                      "desc": ln.get("Description", ""), "acct": jd["AccountRef"]["value"]})
    return lines


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
        lines = _lines_of(body) if body else []
        d = sum(l["amount"] for l in lines if l["type"] == "Debit")
        c = sum(l["amount"] for l in lines if l["type"] == "Credit")
        var = detail.get("variance") or {}
        try:
            over_short = Decimal(var.get("over_short", "0"))
        except Exception:
            over_short = Decimal("0")
        drafts.append({"batch": r.batch, "status": r.status, "doc": r.doc_number,
                       "qbo_id": r.qbo_id, "deposit": r.deposit, "lines": lines,
                       "debit": d, "credit": c, "balanced": d == c,
                       "reason": detail.get("reason", ""), "variance": var,
                       "over_short": over_short, "meta": detail.get("meta") or {}})
    return appr, org, drafts


def adjust(session, token: str, batch: str, account_key: str, memo: str = "") -> dict:
    """Resolve a flagged (review) batch from the portal: re-book the residual
    (Over/Short) to the account the user chose, with an optional memo, and stage the
    batch as 'drafted' so it can be approved. The residual AMOUNT is not editable —
    it comes straight from the authoritative payout — only where it lands and the
    note. This keeps the entry balanced and avoids guessing at the numbers."""
    appr = session.query(Approval).filter_by(token=token).first()
    if not appr:
        return {"error": "not_found"}
    run = (session.query(SyncRun)
           .filter_by(org_id=appr.org_id, business_date=appr.business_date, batch=batch).first())
    if not run:
        return {"error": "batch_not_found"}
    detail = json.loads(run.detail_json or "{}")
    body = detail.get("body")
    if not body:
        return {"error": "no_body"}

    conn = session.query(Connection).filter_by(org_id=appr.org_id, provider="qbo").first()
    accts = conn.account_map if conn else {}
    acct_id = accts.get(account_key)
    if not acct_id:
        return {"error": "unmapped_account", "account_key": account_key}

    # strip the existing balancing (Over/Short) line, recompute the residual from the
    # rest, and re-add one balancing line to the chosen account so debits == credits.
    kept = [ln for ln in body["Line"] if ln.get("Description") != OVER_SHORT_DESC]
    d = sum(Decimal(str(l["Amount"])) for l in kept if l["JournalEntryLineDetail"]["PostingType"] == "Debit")
    c = sum(Decimal(str(l["Amount"])) for l in kept if l["JournalEntryLineDetail"]["PostingType"] == "Credit")
    residual = c - d                       # >0 -> need a debit; <0 -> need a credit
    desc = (memo.strip() or "Over and short (reviewed)")
    if residual != 0:
        posting = "Debit" if residual > 0 else "Credit"
        kept.append({"DetailType": "JournalEntryLineDetail", "Amount": _c(abs(residual)),
                     "Description": desc,
                     "JournalEntryLineDetail": {"PostingType": posting, "AccountRef": {"value": acct_id}}})
    body["Line"] = kept
    detail["body"] = body
    detail["adjusted"] = {"account_key": account_key, "memo": desc, "residual": str(residual)}
    run.status = "drafted"
    run.detail_json = json.dumps(detail)
    session.commit()
    return {"status": "staged", "batch": batch, "residual": str(residual), "account_key": account_key}


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

    # only close the approval if nothing is still flagged for review; otherwise keep
    # it open so the remaining variance can be resolved in the portal.
    still_review = (session.query(SyncRun)
                    .filter_by(org_id=appr.org_id, business_date=appr.business_date, status="review").count())
    appr.status = "pending" if still_review else "posted"
    session.commit()
    return {"status": "posted", "batches": posted, "remaining_review": still_review}


def reject(session, token: str) -> dict:
    appr = session.query(Approval).filter_by(token=token).first()
    if not appr:
        return {"error": "not_found"}
    for run in (session.query(SyncRun)
                .filter_by(org_id=appr.org_id, business_date=appr.business_date)
                .filter(SyncRun.status.in_(["drafted", "review"])).all()):
        run.status = "rejected"
    appr.status = "rejected"; session.commit()
    return {"status": "rejected"}
