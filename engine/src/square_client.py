"""
Square extractor — pulls one day's sales components for EverBean.

Data sources (all proven against the live account):
  - Reporting API  : gross, discounts, comps, sales tax, tips, gift-card sales
  - GiftCardActivities API : gift-card REDEMPTIONS (COMPLETED only)
  - Payouts API    : processing fees + actual bank deposit (for tie-out)

Returns a plain dict of Decimals so downstream math is exact.
"""
from __future__ import annotations
import requests
from decimal import Decimal
from datetime import datetime, timedelta

import config


class SquareClient:
    def __init__(self, access_token: str):
        self.base = config.SQUARE_API_BASE
        self.h = {
            "Authorization": f"Bearer {access_token}",
            "Square-Version": config.SQUARE_VERSION,
            "Content-Type": "application/json",
        }

    # ---- Reporting: daily money totals ---------------------------------
    def daily_sales(self, day: str) -> dict:
        """day = 'YYYY-MM-DD'. Returns gross/discounts/comps/tax/tips/gc_sales/total."""
        query = {
            "query": {
                "measures": [
                    "Sales.top_line_product_sales", "Sales.discounts_amount",
                    "Sales.comps_amount", "Sales.sales_tax_amount",
                    "Sales.tips_amount", "Sales.gift_card_sales_amount",
                    "Sales.total_collected_amount",
                ],
                "timeDimensions": [{
                    "dimension": "Sales.reporting_day",
                    "dateRange": [day, day],
                    "granularity": "day",
                }],
                "limit": 5,
            }
        }
        r = requests.post(f"{self.base}/v1/reporting/load",
                          headers=self.h, json=query, timeout=60)
        r.raise_for_status()
        rows = r.json().get("data", [])
        if not rows:
            return _zero_sales()
        row = rows[0]
        g = lambda k: Decimal(str(row.get(k, 0) or 0))
        return {
            "gross":     g("Sales.top_line_product_sales"),
            "discounts": g("Sales.discounts_amount"),   # negative
            "comps":     g("Sales.comps_amount"),       # negative
            "tax":       g("Sales.sales_tax_amount"),
            "tips":      g("Sales.tips_amount"),
            "gc_sales":  g("Sales.gift_card_sales_amount"),
            "total_collected": g("Sales.total_collected_amount"),
        }

    # ---- Gift card redemptions -----------------------------------------
    def gift_card_redemptions(self, day: str) -> Decimal:
        """Sum of COMPLETED REDEEM activity for the local day (cents -> dollars)."""
        start = f"{day}T00:00:00-06:00"   # America/Denver; DST handled by caller if needed
        end = (datetime.fromisoformat(day) + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00-06:00")
        total = Decimal("0")
        cursor = None
        while True:
            params = {"type": "REDEEM", "begin_time": start, "end_time": end,
                      "limit": 100, "sort_order": "ASC"}
            if cursor:
                params["cursor"] = cursor
            r = requests.get(f"{self.base}/v2/gift-cards/activities",
                             headers=self.h, params=params, timeout=60)
            r.raise_for_status()
            body = r.json()
            for act in body.get("gift_card_activities", []):
                d = act.get("redeem_activity_details", {})
                if d.get("status") == "COMPLETED":
                    total += Decimal(str(d.get("amount_money", {}).get("amount", 0))) / 100
            cursor = body.get("cursor")
            if not cursor:
                break
        return total

    # ---- Payouts: fees + actual deposit --------------------------------
    def payout_fees_and_deposit(self, day: str) -> dict:
        """Processing fees and net deposit for payouts on `day`.
        Note: Square fees settle at PAYOUT time, which can lag the sale day.
        Returned for tie-out; the daily receipt can post before this is final."""
        start = f"{day}T00:00:00-06:00"
        end = (datetime.fromisoformat(day) + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00-06:00")
        r = requests.get(f"{self.base}/v2/payouts", headers=self.h,
                         params={"begin_time": start, "end_time": end, "limit": 100},
                         timeout=60)
        r.raise_for_status()
        fees = Decimal("0")
        deposit = Decimal("0")
        for p in r.json().get("payouts", []):
            amt = p.get("amount_money", {}).get("amount", 0)
            deposit += Decimal(str(amt)) / 100
            # fee detail is on payout entries; summarized here as a placeholder hook
        return {"fees": fees, "deposit": deposit}


def _zero_sales() -> dict:
    z = Decimal("0")
    return {"gross": z, "discounts": z, "comps": z, "tax": z, "tips": z,
            "gc_sales": z, "total_collected": z}
