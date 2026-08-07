"""Square source adapter — pulls a day's two-batch DailyBatches for a tenant.

PAYOUT-ANCHORED (everbean-two-batch-tender-split-spec.md + Aug-6 reconciliation):
the card batch is defined by the Square PAYOUT that settles the day, not by a
midnight-to-midnight order window. This is the fix for the Aug-6 miss:

  * DEPOSIT is the payout's `amount_money` (authoritative, exact).
  * FEES = every fee the payout deducts: each CHARGE entry's `fee_amount_money`
    PLUS separate fee entries such as `GIFT_CARD_LOAD_FEE` (the $2.50 the old
    code silently dropped because it only summed charge fees).
  * REFUNDS = the payout's REFUND entries (the $27.00 the old code never modeled).
  * The CARD SALES BREAKDOWN is taken from exactly the payments that settled in
    that payout (anchor by `payment_id`), so there is no order-window mismatch —
    the batch ties to the penny by construction (Over/Short -> 0). Any settlement
    the payout deducts that we can't classify falls to Over/Short, which the
    pipeline gate routes to human review rather than silently drafting.

Cash never settles through a payout (no Square fees), so the cash batch is the
day's CASH tenders, self-anchored (deposit = cash collected). Gift-card
redemptions are folded into the card batch with an offsetting gift-card-liability
draw (revenue-neutral to the bank), summed from the SQUARE_GIFT_CARD tenders and
cross-checked against GiftCardActivities.

`aggregate_day` is a pure function (raw API dicts -> DailyBatches) so it can be
unit-tested offline; `SquareSource.pull_day` does the live paginated fetches.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
import datetime
import requests
from .domain import DailyBatches, Batch

C = lambda cents: Decimal(cents) / 100
D = lambda x: Decimal(str(x))
Q2 = lambda x: Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
CARD_TENDERS = {"CARD", "SQUARE_GIFT_CARD"}


# ------------------ authoritative reporting-anchored build ------------------
def build_from_reporting(business_date: str, sales: dict, deposit: Decimal, fees: Decimal,
                         refunds: Decimal, redemptions: Decimal) -> DailyBatches:
    """Build the two-batch day from Square's AUTHORITATIVE Reporting Sales Summary
    (matches the seller's dashboard to the penny) + the payout settlement figures.

    `sales`: the Reporting `Sales.*` measures for the reporting day, in DOLLARS.
    `deposit`/`fees`/`refunds`/`redemptions`: DOLLARS from the payout decomposition +
    GiftCardActivities. The card batch is anchored to the payout deposit; the cash
    batch is split off by its share of collected (net + tax) — a presentation split
    only, since both batches post to the same GL accounts and the two batches' totals
    equal the dashboard exactly. Gift-card-funded sales are already inside the
    authoritative gross/tax, so redemptions post as a gift-card-liability draw and the
    card batch ties to the payout (residual = Square's cash-rounding, absorbed by
    Over/Short)."""
    money = lambda k: D(sales.get(k, 0) or 0)
    G = Q2(money("Sales.top_line_product_sales"))          # gross product sales
    disc = Q2(abs(money("Sales.discounts_amount")))        # magnitude (stored negative)
    tax = Q2(money("Sales.sales_tax_amount"))
    tips = Q2(money("Sales.tips_amount"))                  # non-cash tips (cash tips excluded)
    gc_sold = Q2(money("Sales.gift_card_sales_amount"))
    net = Q2(money("Sales.net_sales"))
    cash_coll = Q2(money("Sales.cash_collected"))

    denom = net + tax
    share = (cash_coll / denom) if denom > 0 else Decimal("0")
    cash_tax = Q2(tax * share)
    cash_disc = Q2(disc * share)
    cash_gross = Q2(cash_coll - cash_tax + cash_disc)      # cash ties to its deposit by construction

    cc = Batch(gross=G - cash_gross, discounts=-(disc - cash_disc), tax=tax - cash_tax,
               tips=tips, gift_cards_sold=gc_sold, gift_card_redemptions=redemptions,
               fees=fees, refunds=refunds, deposit=deposit)
    cc.over_short = Q2(cc.deposit - cc.implied_deposit())

    cash = Batch(gross=cash_gross, discounts=-cash_disc, tax=cash_tax, deposit=cash_coll)
    cash.over_short = Q2(cash.deposit - cash.implied_deposit())
    return DailyBatches(business_date, cc=cc, cash=cash)


# ----------------------------- pure aggregation -----------------------------
def aggregate_day(business_date: str, orders: list, card_payment_ids,
                  payout_deposit_cents: int, payout_fees_cents: int,
                  payout_refunds_cents: int = 0, gc_redemptions_cents: int | None = None,
                  reporting_discount_cents: int | None = None) -> DailyBatches:
    """Build the two-batch day from orders + the authoritative payout figures.

    orders: Square order dicts for the reporting day (with `tenders`).
    card_payment_ids: the set of payment_ids that SETTLED in the day's payout —
        the card batch counts ONLY card tenders whose payment_id is in this set,
        anchoring the card sales to the payout (no order-window drift).
    payout_deposit_cents / payout_fees_cents / payout_refunds_cents: authoritative
        from the payout decomposition (deposit, all fees incl. gift-card load,
        refunds paid back out).
    gc_redemptions_cents: GiftCardActivities REDEEM total (cross-check only; the
        batch uses the SQUARE_GIFT_CARD tender sum so the fold stays internally
        consistent and Over/Short is not disturbed by a labeling difference).
    reporting_discount_cents: authoritative day discount from the reporting Sales
        view; when given, overrides the (unreliable) order-level discount total,
        allocated across the two batches by net-sales share.
    """
    card_ids = set(card_payment_ids or ())
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
            ttype = t.get("type")
            # ---- bucket selection (payout anchor for card) ----
            if ttype == "CARD":
                pid = t.get("payment_id") or t.get("id")
                if card_ids and pid not in card_ids:
                    continue  # settled in a different payout / day — not this batch
                b = cc
            elif ttype == "SQUARE_GIFT_CARD":
                b = cc                                   # redemption, folded into card batch
            elif ttype == "CASH":
                b = cash
            else:
                continue                                 # other tenders not modeled

            tip = (t.get("tip_money") or {}).get("amount", 0)
            w = Decimal(amt) / Decimal(tot)
            tax_a = int((Decimal(tax) * w).quantize(Decimal("1")))
            gc_a = int((Decimal(gc_sold) * w).quantize(Decimal("1")))
            disc_a = int((Decimal(disc) * w).quantize(Decimal("1")))
            net = amt - tip - tax_a - gc_a               # net product sales (post-discount)
            b["net"] += net
            b["tax"] += tax_a
            b["gc_sold"] += gc_a
            b["disc"] += disc_a
            if b is cc and ttype == "CARD":
                b["tips"] += tip                         # card tips only; cash tips excluded
            if ttype == "SQUARE_GIFT_CARD":
                b["tips"] += tip
                redeemed += amt                          # gift-card tender = redemption draw

    # Authoritative discount from reporting overrides the unreliable order-level
    # total, allocated across the two batches by net-sales share (spec §discounts).
    if reporting_discount_cents is not None:
        total_net = cc["net"] + cash["net"]
        if total_net > 0:
            cc["disc"] = int(round(reporting_discount_cents * cc["net"] / total_net))
            cash["disc"] = reporting_discount_cents - cc["disc"]

    def mk(b, deposit_cents, fees_cents, refunds_cents, redemptions_cents):
        gross = b["net"] + b["disc"]                     # gross = net + discount
        batch = Batch(
            gross=C(gross), discounts=C(-b["disc"]), tax=C(b["tax"]), tips=C(b["tips"]),
            gift_cards_sold=C(b["gc_sold"]),
            gift_card_redemptions=C(redemptions_cents),
            fees=C(fees_cents), refunds=C(refunds_cents), deposit=C(deposit_cents))
        # anchor deposit to the authoritative payout figure; residual -> Over/Short
        batch.over_short = batch.deposit - batch.implied_deposit()
        return batch

    cash_deposit = cash["net"] + cash["disc"] + cash["tax"] + cash["gc_sold"]  # cash collected
    return DailyBatches(
        business_date,
        cc=mk(cc, payout_deposit_cents, payout_fees_cents, payout_refunds_cents, redeemed),
        cash=mk(cash, cash_deposit, 0, 0, 0),
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
                b = dict(body or {})
                if cursor: b["cursor"] = cursor
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
                           params={"location_id": location_id, "begin_time": begin_iso,
                                   "end_time": end_iso, "sort_order": "ASC"})

    def payout_entries(self, payout_id):
        return self._paged("GET", f"/v2/payouts/{payout_id}/payout-entries", "payout_entries")

    def gift_redemptions(self, begin_iso, end_iso):
        return self._paged("GET", "/v2/gift-cards/activities", "gift_card_activities",
                           params={"type": "REDEEM", "begin_time": begin_iso, "end_time": end_iso})

    # ---- Reporting API (Cube): authoritative Sales Summary, matches the dashboard ----
    SALES_MEASURES = ["Sales.top_line_product_sales", "Sales.net_sales", "Sales.discounts_amount",
                      "Sales.sales_tax_amount", "Sales.tips_amount", "Sales.gift_card_sales_amount",
                      "Sales.refunds_by_amount_amount", "Sales.total_collected_amount",
                      "Sales.cash_collected", "Sales.order_count"]

    def reporting_load(self, query: dict) -> dict:
        r = requests.post(f"{self.base}/reporting/v1/load", headers=self.h,
                          json={"query": query}, timeout=60)
        if r.status_code == 403:
            raise PermissionError("REPORTING_READ scope missing — reconnect Square to grant Reporting access")
        r.raise_for_status()
        return r.json()

    def sales_summary(self, location_id: str, business_date: str) -> dict:
        """One authoritative Sales-Summary row for the seller's reporting day (uses
        Square's configured reporting-day boundary, e.g. 5:30 AM — the same basis as
        the dashboard), so gross/discounts/tax/tips match the dashboard to the penny."""
        q = {"measures": self.SALES_MEASURES,
             "timeDimensions": [{"dimension": "Sales.reporting_day",
                                 "dateRange": [business_date, business_date]}],
             "filters": [{"member": "Sales.location_id", "operator": "equals", "values": [location_id]}]}
        rows = self.reporting_load(q).get("data", [])
        return rows[0] if rows else {}


def decompose_payouts(payouts: list, entries_by_id: dict) -> dict:
    """Turn selected payouts + their entries into the authoritative settlement
    figures. Returns cents: deposit, fees (all fee deductions), refunds, and the
    set of card payment_ids that settled here (the card-batch anchor).

    Classification is conservative: CHARGE fees and any *FEE* entry (e.g.
    GIFT_CARD_LOAD_FEE) are fees; REFUND entries are refunds; anything else is
    left unclassified so it surfaces as Over/Short for review instead of being
    silently mislabeled as a fee."""
    deposit = fees = refunds = 0
    card_payment_ids = set()
    unclassified = []
    for p in payouts:
        deposit += (p.get("amount_money") or {}).get("amount", 0)
        for e in entries_by_id.get(p["id"], []):
            t = e.get("type", "")
            net = (e.get("net_amount_money") or {}).get("amount", 0)
            fee = (e.get("fee_amount_money") or {}).get("amount", 0)
            if t == "CHARGE":
                fees += fee
                pid = (e.get("type_charge_details") or {}).get("payment_id")
                if pid:
                    card_payment_ids.add(pid)
            elif t == "REFUND":
                refunds += -net                     # net is negative
            elif "FEE" in t:
                fees += -net                         # GIFT_CARD_LOAD_FEE etc. (net negative)
            else:
                unclassified.append({"type": t, "net": net})
    return {"deposit": deposit, "fees": fees, "refunds": refunds,
            "card_payment_ids": card_payment_ids, "unclassified": unclassified}


class SampleSource:
    """Offline fallback (no Square token available, e.g. local dev/demo). Returns
    a validated two-batch sample so the pipeline can run end to end."""
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
    Connection). Selects the payout that settles the day, decomposes it for the
    authoritative deposit / fees / refunds + the card anchor, and returns the
    two-batch DailyBatches. Exposes `last_meta` so the pipeline can surface why a
    day didn't reconcile."""
    def __init__(self, conn, access_token: str):
        self.location = conn.realm_or_location
        self.api = SquareApi(access_token, env=conn.environment)
        self.last_meta: dict = {}

    def _local_dt(self, iso_z: str, tz_offset: str):
        """Parse an RFC3339 (Zulu) timestamp and shift into the location's local
        offset for date bucketing."""
        s = iso_z.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(s)
        sign = 1 if tz_offset[0] == "+" else -1
        oh, om = int(tz_offset[1:3]), int(tz_offset[4:6])
        return dt + datetime.timedelta(hours=sign * oh, minutes=sign * om)

    def _select_payouts(self, business_date, tz_offset):
        """The payout that settles `business_date` is the daily BATCH payout created
        around its close: local(created_at) in [date 12:00, date+1 12:00). This
        deterministically excludes the prior day's early-morning payout and the
        next day's evening payout."""
        y, m, d = map(int, business_date.split("-"))
        day = datetime.date(y, m, d)
        nxt = day + datetime.timedelta(days=1)
        # widen the API window a little around the day to be safe, then filter by created_at
        begin = f"{(day - datetime.timedelta(days=1)).isoformat()}T00:00:00{tz_offset}"
        end = f"{(nxt + datetime.timedelta(days=1)).isoformat()}T00:00:00{tz_offset}"
        lo = datetime.datetime.combine(day, datetime.time(12, 0))
        hi = datetime.datetime.combine(nxt, datetime.time(12, 0))
        selected = []
        for p in self.api.payouts(self.location, begin, end):
            if p.get("type") and p["type"] != "BATCH":
                continue
            created = self._local_dt(p["created_at"], tz_offset).replace(tzinfo=None)
            if lo <= created < hi:
                selected.append(p)
        return selected

    def pull_day(self, business_date: str, tz_offset: str = "-06:00") -> DailyBatches:
        start = f"{business_date}T00:00:00{tz_offset}"
        y, m, d = map(int, business_date.split("-"))
        nxt = (datetime.date(y, m, d) + datetime.timedelta(days=1)).isoformat()
        end = f"{nxt}T00:00:00{tz_offset}"

        # settlement (authoritative deposit / fees / refunds) from the day's payout
        payouts = self._select_payouts(business_date, tz_offset)
        entries_by_id = {p["id"]: self.api.payout_entries(p["id"]) for p in payouts}
        settle = decompose_payouts(payouts, entries_by_id)

        # gift-card redemptions (revenue already inside the authoritative gross)
        redemptions = sum((a.get("redeem_activity_details") or {}).get("amount_money", {}).get("amount", 0)
                          for a in self.api.gift_redemptions(start, end)
                          if (a.get("redeem_activity_details") or {}).get("status") == "COMPLETED")

        # AUTHORITATIVE sales breakdown from Square's Reporting Sales Summary (matches
        # the dashboard); requires the REPORTING_READ scope (raises PermissionError if
        # the tenant hasn't reconnected Square to grant it).
        sales = self.api.sales_summary(self.location, business_date)

        db = build_from_reporting(business_date, sales,
                                  C(settle["deposit"]), C(settle["fees"]),
                                  C(settle["refunds"]), C(redemptions))

        self.last_meta = {
            "payouts": [p["id"] for p in payouts],
            "deposit_cents": settle["deposit"], "fees_cents": settle["fees"],
            "refunds_cents": settle["refunds"], "n_charges": len(settle["card_payment_ids"]),
            "redemptions_cents": redemptions, "unclassified": settle["unclassified"],
            "no_payout": not payouts, "source": "reporting",
            "reporting": {k: sales.get(k) for k in SquareApi.SALES_MEASURES},
        }
        return db
