"""
Offline validation of transform + reconcile against the proven Jul 24-30, 2026
sample week. No network — pure logic check so we know the math is right before
a single live call is made.
"""
import sys, os
from decimal import Decimal
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
# Give the optional items ids so the Over/Short and Sales-Tax lines are exercised.
config.ITEM_OVER_SHORT = "OS"
config.ITEM_SALES_TAX = "TAX-LIA"
from src import transform, reconcile

# (gross, discounts, tax, tips, gc_sales, total_collected, redemptions)
SAMPLE = {
 "2026-07-24": (2434.32, -18.80, 107.37, 335.41,   0.00, 2858.33, 122.90),
 "2026-07-25": (3772.87, -58.35, 163.69, 455.53,   0.00, 4329.97, 116.88),
 "2026-07-26": (3086.83, -15.55, 137.17, 394.44,   0.00, 3589.07,  26.19),
 "2026-07-27": (2085.70, -17.77,  92.89, 254.88, 240.00, 2649.40, 141.65),
 "2026-07-28": (2033.97, -38.30,  89.28, 236.93, 100.00, 2421.85,  55.14),
 "2026-07-29": (2070.62, -23.20,  90.78, 279.44, 250.00, 2667.69, 104.23),
 "2026-07-30": (1782.51, -16.70,  79.71, 229.35, 150.00, 2224.88, 122.66),
}


def _s(t):
    return {"gross": Decimal(str(t[0])), "discounts": Decimal(str(t[1])),
            "comps": Decimal("0"), "tax": Decimal(str(t[2])),
            "tips": Decimal(str(t[3])), "gc_sales": Decimal(str(t[4])),
            "total_collected": Decimal(str(t[5]))}


def main():
    all_ok = True
    print(f"{'Day':<12}{'Recon':<8}{'Over/Short':>11}{'ReceiptTot':>12}{'TaxLine':>13}")
    for day, t in SAMPLE.items():
        s = _s(t)
        redemptions = Decimal(str(t[6]))
        rc = reconcile.check_day(s, redemptions)
        receipt = transform.build_sales_receipt(day, s, redemptions)

        # 1) tax is a NON-taxable line (not a TxnTaxDetail override); QBO tax = $0
        assert "TxnTaxDetail" not in receipt, f"must not use QBO tax engine on {day}"
        tax_lines = [ln for ln in receipt["Line"]
                     if ln["SalesItemLineDetail"]["ItemRef"]["value"] == config.ITEM_SALES_TAX]
        assert len(tax_lines) == 1, f"exactly one sales-tax line on {day}"
        tax_amt = tax_lines[0]["Amount"]
        assert abs(tax_amt - float(t[2])) < 0.005, f"tax line != Square tax on {day}"

        # 2) every line is non-taxable (so QBO computes $0 and can't drift)
        codes = [ln["SalesItemLineDetail"]["TaxCodeRef"]["value"] for ln in receipt["Line"]]
        assert all(c == "NON" for c in codes), f"all lines must be non-taxable on {day}"

        # 3) receipt total (sum of lines) == total_collected - redemptions (money to deposit)
        receipt_total = Decimal(str(sum(ln["Amount"] for ln in receipt["Line"])))
        expected = transform.expected_receipt_total(s, redemptions)
        assert abs(receipt_total - expected) < Decimal("0.01"), \
            f"receipt total {receipt_total} != expected {expected} on {day}"

        all_ok &= rc["internal_ok"]
        flag = "OK" if rc["internal_ok"] else "REVIEW"
        print(f"{day:<12}{flag:<8}{float(rc['over_short']):>+11.2f}"
              f"{float(receipt_total):>12.2f}{tax_amt:>13.2f}")
    print("\nALL DAYS internally consistent:", all_ok)
    print("Verified per day: tax booked as a non-taxable liability line (QBO tax $0),")
    print("all lines non-taxable, and receipt total == total_collected - gift-card redemptions.")


if __name__ == "__main__":
    main()
