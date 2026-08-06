"""
Dry-run: build the two SalesReceipt payloads for a day and prove they tie out —
no QuickBooks call, no credentials needed. Verifies the poster reproduces the
manually-validated receipts (Aug 4: CC #...444 = $2,076.45, cash #...443 = $221.95).

Run:  cd engine && python -m scripts.dryrun_two_batch
"""
import os
# Placeholder sandbox entity IDs so the full payload (fees, over/short, tax line)
# renders. Replace with real sandbox IDs from scripts/lookup_ids.py before posting.
os.environ.setdefault("QBO_ENV", "sandbox")
os.environ.setdefault("QBO_ITEM_SQUARE_FEES", "SANDBOX_FEES_ITEM")
os.environ.setdefault("QBO_ITEM_OVER_SHORT", "SANDBOX_OVERSHORT_ITEM")
os.environ.setdefault("QBO_DEPOSIT_ACCOUNT_ID", "SANDBOX_CHECKING_ACCT")
os.environ.setdefault("QBO_TAX_CODE_ID", "SANDBOX_TAX_CODE")
os.environ.setdefault("QBO_TAX_RATE_ID", "SANDBOX_TAX_RATE")

import json
from decimal import Decimal
from src.transform_batches import build_batch_receipts

# Aug 4, 2026 — the two-batch figures that produced the validated manual receipts.
AUG4 = {
    "cc": {
        "gross": "1800.23", "discounts": "-10.05", "tax": "80.39",
        "tips": "260.48", "gc_sold": "100.00", "gc_redemptions": "85.92",
        "fees": "68.68", "over_short": "0", "deposit": "2076.45",  # = Square payout
    },
    "cash": {
        "gross": "212.39", "discounts": "0", "tax": "9.56",
        "deposit": "221.95",  # = cash deposit
    },
}


def receipt_total(body: dict) -> Decimal:
    lines = sum(Decimal(str(l["Amount"])) for l in body["Line"])
    tax = Decimal(str(body["TxnTaxDetail"]["TotalTax"]))
    return lines + tax


def main():
    day = "2026-08-04"
    out = build_batch_receipts(day, AUG4)

    for label, key, expected in [("CREDIT-CARD", "cc", out["expected_cc_total"]),
                                 ("CASH", "cash", out["expected_cash_total"])]:
        body = out[key]
        total = receipt_total(body)
        tie = "OK ✓" if abs(total - Decimal(str(expected))) < Decimal("0.005") else "MISMATCH ✗"
        print(f"\n{'='*70}\n{label} batch — DocNumber {body['DocNumber']}\n{'='*70}")
        print(json.dumps(body, indent=2))
        print(f"--> receipt total ${total}  vs  expected deposit ${expected}   [{tie}]")

    print("\nBoth receipts must tie to the actual Square payout / cash deposit to post.")


if __name__ == "__main__":
    main()
