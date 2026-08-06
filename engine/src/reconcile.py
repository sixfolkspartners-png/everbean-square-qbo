"""
Reconciliation checks. A day only posts (or is flagged clean) when the numbers
tie out, so a bad pull never quietly lands wrong figures in the books.

Two distinct checks:
  1. Internal consistency  — Square's components vs its own total_collected.
     The residual is the "Over and Short" plug; only a LARGE residual is a
     problem (rounding/refund pennies are normal and get booked to Over/Short).
  2. Deposit tie-out       — receipt total vs the ACTUAL Square payout/deposit
     (once fees/payout data is available). This one is tight.
"""
from __future__ import annotations
from decimal import Decimal
import config


def check_day(s: dict, redemptions: Decimal, deposit: Decimal | None = None,
              fees: Decimal = Decimal("0")) -> dict:
    computed = s["gross"] + s["discounts"] + s["tax"] + s["tips"] + s["gc_sales"]
    over_short = s["total_collected"] - computed          # the plug (small)
    net_to_deposit = s["total_collected"] - redemptions - fees

    internal_ok = over_short.copy_abs() <= Decimal(str(config.OVER_SHORT_LIMIT))

    deposit_ok = None
    deposit_diff = None
    if deposit is not None:
        deposit_diff = net_to_deposit - deposit
        deposit_ok = deposit_diff.copy_abs() <= Decimal(str(config.RECONCILE_TOLERANCE))

    return {
        "ok": internal_ok and (deposit_ok is not False),
        "internal_ok": internal_ok,
        "over_short": over_short,
        "computed_total": computed,
        "square_total": s["total_collected"],
        "redemptions": redemptions,
        "net_to_deposit": net_to_deposit,
        "deposit_ok": deposit_ok,
        "deposit_diff": deposit_diff,
    }


def format_report(day: str, s: dict, rc: dict) -> str:
    lines = [
        f"[{day}] internal {'OK' if rc['internal_ok'] else 'REVIEW'} "
        f"(over/short {rc['over_short']:+.2f})",
        f"  gross={s['gross']}  disc={s['discounts']}  tax={s['tax']}  "
        f"tips={s['tips']}  gc_sales={s['gc_sales']}",
        f"  square_total={rc['square_total']}  redemptions={rc['redemptions']}  "
        f"net_to_deposit={rc['net_to_deposit']}",
    ]
    if rc["deposit_ok"] is not None:
        lines.append(f"  deposit_tie_out={'OK' if rc['deposit_ok'] else 'FAILED'} "
                     f"(diff {rc['deposit_diff']:+.2f})")
    return "\n".join(lines)
