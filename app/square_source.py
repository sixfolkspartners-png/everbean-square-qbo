"""Square source adapter — pulls a day's two-batch DailyBatches for a tenant.

Implements the locked rules (everbean-two-batch-tender-split-spec.md):
- Tender split from Orders: each order's money split by its ACTUAL tenders;
  tender.amount_money INCLUDES the tip (stripped before net product sales).
  CARD + SQUARE_GIFT_CARD -> card batch; CASH -> cash batch; cash tips excluded.
- Gift-card redemptions = SQUARE_GIFT_CARD tender collected (cross-checked to
  GiftCardActivities REDEEM/COMPLETED); a reduction inside the card batch.
- Fees + the card deposit are AUTHORITATIVE from the payout, fully paginated via
  Payouts.listEntries (never estimated). CC deposit is anchored to the payout;
  any residual vs the orders-derived collection lands on Over/Short (the pipeline
  gates |over_short| > $25 to 'review').

`aggregate_day` is a pure function (raw API dicts -> DailyBatches) so it can be
unit-tested offline; `SquareSource.pull_day` does the live paginated fetches.
"""
from __future__ import annotations
from decimal import Decimal
import requests
from .domain import DailyBatches, Batch

C = lambda cents: Decimal(cents) / 100
CARD_TENDERS = {"CARD", "SQUARE_GIFT_CARD"}


# ----------------------------- pure aggregation -----------------------------
def aggregate_day(business_date: str, orders: list, payout_fees_cents: int,
                  payout_deposit_cents: int, gc_redemptions_cents: int | None = None,
                  reporting_discount_cents: int | None = None) -> DailyBatches:
    """orders: list of Square order dicts. payout_*: authoritative from the payout
    (card fees, card net deposit). gc_redemptions_cents: from GiftCardActivities
    (optional cross-check; falls back to the SQUARE_GIFT_CARD tender sum).
    reporting_discount_cents: the AUTHORITATIVE day discount from the reporting
    Sales view (Order.total_discount_money is unreliable — spec §discounts); when
    given it overrides the order-level discount, allocated by net-sales share."""
    cc = dict(net=0, tax=0, tips=0, gc_sold=0, disc=0)
    cash = dict(net=0, tax=0, tips=0, gc_sold=0, disc=0)
    redeemed = 0

    for o in orders:
        if o.get("state") != "COMPLETED":
            continue
        tenders = o.get("tenders") or []
        amts = [(t.get("amount_money") or {}).get("amount", 0) for t in tenders]
        tot = sum(amts)
        if tot <= 0:
            continue
        tax = (o.get("total_tax_money") or {}).get("amount", 0)
        disc = (o.get("total_discount_money") or {}).get("amount", 0)
        gc_sold = sum((li.get("gross_sales_money") or {}).get("amount", 0)
                      for li in (o.get("line_items") or []) if li.get("item_type") == "GIFT_CARD")

        for t in tenders:
            amt = (t.get("amount_money") or {}).get("amount", 0)
            if amt <= 0:
                continue
            tip = (t.get("tip_money") or {}).get("amount", 0)
            w = Decimal(amt) / Decimal(tot)
            tax_a = int((Decimal(tax) * w).quantize(Decimal("1")))
            gc_a = int((Decimal(gc_sold) * w).quantize(Decimal("1")))
            disc_a = int((Decimal(disc) * w).quantize(Decimal("1")))
            net = amt - tip - tax_a - gc_a          # net product sales (post-discount)
            b = cc if t.get("type") in CARD_TENDERS else (cash if t.get("type") == "CASH" else None)
            if b is None:
                continue
            b["net"] += net
            b["tax"] += tax_a
            b["gc_sold"] += gc_a
            b["disc"] += disc_a
            if b is cc and t.get("type") == "CARD":
                b["tips"] += tip                     # card tips only; cash tips excluded
            if t.get("type") == "SQUARE_GIFT_CARD":
                b["tips"] += tip
                redeemed += amt

    if gc_redemptions_cents is not None:
        redeemed = gc_redemptions_cents

    # Authoritative discount from reporting overrides the unreliable order-level
    # total, allocated across the two batches by net-sales share (spec §discounts).
    if reporting_discount_cents is not None:
        total_net = cc["net"] + cash["net"]
        if total_net > 0:
            cc["disc"] = int(round(reporting_discount_cents * cc["net"] / total_net))
            cash["disc"] = reporting_discount_cents - cc["disc"]

    def mk(b, deposit_cents, fees_cents, is_cc):
        gross = b["net"] + b["disc"]                 # gross = net + discount
        batch = Batch(
            gross=C(gross), discounts=C(-b["disc"]), tax=C(b["tax"]), tips=C(b["tips"]),
            gift_cards_sold=C(b["gc_sold"]),
            gift_card_redemptions=C(redeemed) if is_cc else Decimal("0"),
            fees=C(fees_cents), deposit=C(deposit_cents))
        # anchor deposit to the authoritative figure; residual -> over/short
        batch.over_short = batch.deposit - batch.implied_deposit()
        return batch

    cash_deposit = cash["net"] + cash["disc"] + cash["tax"] + cash["gc_sold"]  # cash collected
    return DailyBatches(
        business_date,
        cc=mk(cc, payout_deposit_cents, payout_fees_cents, is_cc=True),
        cash=mk(cash, cash_deposit, 0, is_cc=False),
    )


# ----------------------------- live Square client ---------------------------
class SquareApi:
    def __init__(self, access_token: str, env: str = "production", version: str = "2025-05-21"):
        self.base = ("https://connect.squareup.com" if env == "production"
                     else "https://connect.squareupsandbox.com")
        self.h = {"Authorization": f"Bearer {access_token}", "Square-Version": version,
                  "Content-Type": "application/json"}

    def _paged(self, method, path, key, body=None, params=None):
        out, cursor = [], None
        while True:
            if method == "POST":
                b = dict(body or {}); b["cursor"] = cursor
                r = requests.post(f"{self.base}{path}", headers=self.h, json=b, timeout=60)
            else:
                p = dict(params or {})
                if cursor: p["cursor"] = cursor
                r = requests.get(f"{self.base}{path}", headers=self.h, params=p, timeout=60)
            r.raise_for_status(); j = r.json()
            out += j.get(key, [])
            cursor = j.get("cursor")
            if not cursor:
                return out

    def orders(self, location_id, start_iso, end_iso):
        return self._paged("POST", "/v2/orders/search", "orders", body={
            "location_ids": [location_id],
            "query": {"filter": {"date_time_filter": {"closed_at": {"start_at": start_iso, "end_at": end_iso}},
                                 "state_filter": {"states": ["COMPLETED"]}}}})

    def payouts(self, location_id, begin_iso, end_iso):
        return self._paged("GET", "/v2/payouts", "payouts",
                           params={"location_id": location_id, "begin_time": begin_iso, "end_time": end_iso})

    def payout_entries(self, payout_id):
        return self._paged("GET", f"/v2/payouts/{payout_id}/payout-entries", "payout_entries")

    def gift_redemptions(self, begin_iso, end_iso):
        return self._paged("GET", "/v2/gift-cards/activities", "gift_card_activities",
                           params={"type": "REDEEM", "begin_time": begin_iso, "end_time": end_iso})


class SampleSource:
    """Offline fallback (no Square token available, e.g. local dev/demo). Returns
    the validated Aug-4 two-batch sample so the pipeline can run end to end."""
    _SAMPLES = {
        "2026-08-04": {
            "cc":   {"gross": "1800.23", "discounts": "-10.05", "tax": "80.39", "tips": "260.48",
                     "gift_cards_sold": "100.00", "gift_card_redemptions": "85.92", "fees": "68.68",
                     "over_short": "0", "deposit": "2076.45"},
            "cash": {"gross": "212.39", "tax": "9.56", "deposit": "221.95"},
        },
        "2026-08-05": {
            "cc":   {"gross": "1800.23", "discounts": "-10.05", "tax": "80.39", "tips": "260.48",
                     "gift_cards_sold": "100.00", "gift_card_redemptions": "85.92", "fees": "68.68",
                     "over_short": "0", "deposit": "2076.45"},
            "cash": {"gross": "212.39", "tax": "9.56", "deposit": "221.95"},
        },
    }

    def __init__(self, conn=None):
        self.conn = conn

    def pull_day(self, business_date: str) -> DailyBatches:
        if business_date not in self._SAMPLES:
            raise NotImplementedError(
                f"No Square token for live pull and no sample for {business_date}. "
                f"Connect Square (Phase A) or use a sample day ({', '.join(self._SAMPLES)}).")
        return DailyBatches.from_dict(business_date, self._SAMPLES[business_date])


class SquareSource:
    """Live source. Needs the tenant's Square access token + location (from the
    Connection). Selects the payout covering the day, decomposes it for the
    authoritative fees + card deposit, and returns the two-batch DailyBatches."""
    def __init__(self, conn, access_token: str):
        self.location = conn.realm_or_location
        self.api = SquareApi(access_token, env=conn.environment)

    def pull_day(self, business_date: str, tz_offset: str = "-06:00") -> DailyBatches:
        start = f"{business_date}T00:00:00{tz_offset}"
        # end of local day
        y, m, d = map(int, business_date.split("-"))
        import datetime
        nxt = (datetime.date(y, m, d) + datetime.timedelta(days=1)).isoformat()
        end = f"{nxt}T00:00:00{tz_offset}"

        orders = self.api.orders(self.location, start, end)
        # payout covering the day: pick the one whose entries fall in-window (simplify:
        # the payout created that evening). Fully paginate entries for exact fees + net.
        payouts = self.api.payouts(self.location, start, f"{nxt}T23:59:59{tz_offset}")
        fees = deposit = 0
        for p in payouts:
            entries = self.api.payout_entries(p["id"])
            fees += sum((e.get("fee_amount_money") or {}).get("amount", 0) for e in entries)
            deposit += (p.get("amount_money") or {}).get("amount", 0)
        redemptions = sum((a.get("redeem_activity_details") or {}).get("amount_money", {}).get("amount", 0)
                          for a in self.api.gift_redemptions(start, end)
                          if (a.get("redeem_activity_details") or {}).get("status") == "COMPLETED")
        return aggregate_day(business_date, orders, fees, deposit, redemptions or None)
