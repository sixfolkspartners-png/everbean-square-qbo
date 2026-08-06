"""
Entry point for the daily Square -> QuickBooks sales-receipt sync.

Usage:
  python -m src.main                      # sync yesterday (the default cron run)
  python -m src.main --date 2026-07-27    # sync one specific day
  python -m src.main --backfill 2026-07-01 2026-07-30   # inclusive range
  python -m src.main --dry-run --date 2026-07-27        # build + print, no post

Env (provided by GitHub Actions secrets):
  SQUARE_ACCESS_TOKEN
  QBO_CLIENT_ID, QBO_CLIENT_SECRET, QBO_REFRESH_TOKEN
  (optional) GH_TOKEN, GH_REPO, SLACK_WEBHOOK_URL
"""
from __future__ import annotations
import os
import sys
import json
import argparse
from datetime import datetime, timedelta, timezone

import config
from src.square_client import SquareClient
from src.qbo_client import QBOClient
from src.token_store import persist_refresh_token
from src import transform, reconcile


def _yesterday() -> str:
    # America/Denver is UTC-6/-7; using UTC-6 as a simple, safe "prior day" anchor.
    now = datetime.now(timezone.utc) - timedelta(hours=6)
    return (now.date() - timedelta(days=1)).isoformat()


def _daterange(a: str, b: str):
    d0 = datetime.fromisoformat(a).date()
    d1 = datetime.fromisoformat(b).date()
    while d0 <= d1:
        yield d0.isoformat()
        d0 += timedelta(days=1)


def alert(msg: str):
    print(msg)
    if config.SLACK_WEBHOOK_URL:
        try:
            import requests
            requests.post(config.SLACK_WEBHOOK_URL, json={"text": msg}, timeout=15)
        except Exception as e:
            print("[alert] slack post failed:", e)


def sync_day(sq: SquareClient, qbo: QBOClient | None, day: str, dry_run: bool) -> dict:
    s = sq.daily_sales(day)
    redemptions = sq.gift_card_redemptions(day)
    payout = sq.payout_fees_and_deposit(day)
    fees = payout["fees"]
    deposit = payout["deposit"] if payout["deposit"] else None

    rc = reconcile.check_day(s, redemptions, deposit=deposit, fees=fees)
    print(reconcile.format_report(day, s, rc))

    if not rc["internal_ok"]:
        alert(f":warning: EverBean sync {day}: over/short {rc['over_short']:+.2f} "
              f"exceeds limit — NOT posting, needs review.")
        return {"day": day, "posted": False, "reason": "over_short_review"}

    body = transform.build_sales_receipt(day, s, redemptions, fees=fees)
    if dry_run or qbo is None:
        print(json.dumps(body, indent=2))
        return {"day": day, "posted": False, "reason": "dry_run", "body": body}

    result = qbo.create_sales_receipt(body)
    if result.get("skipped"):
        print(f"[{day}] already posted (DocNumber {result['doc_number']}), skipping.")
    else:
        print(f"[{day}] posted SalesReceipt id={result['id']} total={result['total']}")
    return {"day": day, "posted": not result.get("skipped"), **result}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--backfill", nargs=2, metavar=("START", "END"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sq = SquareClient(os.environ["SQUARE_ACCESS_TOKEN"])

    qbo = None
    if not args.dry_run:
        qbo = QBOClient(os.environ["QBO_CLIENT_ID"],
                        os.environ["QBO_CLIENT_SECRET"],
                        os.environ["QBO_REFRESH_TOKEN"])
        qbo.refresh()
        # persist the (possibly rotated) refresh token so tomorrow's run works
        persist_refresh_token(qbo.refresh_token)

    if args.backfill:
        days = list(_daterange(*args.backfill))
    elif args.date:
        days = [args.date]
    else:
        days = [_yesterday()]

    results = []
    for day in days:
        try:
            results.append(sync_day(sq, qbo, day, args.dry_run))
        except Exception as e:
            alert(f":rotating_light: EverBean sync {day} FAILED: {e}")
            results.append({"day": day, "posted": False, "error": str(e)})

    posted = sum(1 for r in results if r.get("posted"))
    print(f"\nDone. {posted}/{len(results)} day(s) posted.")
    # non-zero exit if any hard error, so the Action surfaces it
    if any("error" in r for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
