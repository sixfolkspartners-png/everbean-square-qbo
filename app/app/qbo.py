"""QuickBooks destination adapter (multi-tenant). Posts a DailyBatches day as two
daily-summary Journal Entries (card + cash). JEs bypass Automated Sales Tax, so
Square's exact tax posts to Sales Tax Payable with full control. Idempotent by
DocNumber. Driven entirely by a Connection row (creds + realm + account map) —
no global config.
"""
from __future__ import annotations
import base64, requests
from decimal import Decimal, ROUND_HALF_UP
from . import vault
from .domain import DailyBatches, Batch

TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
API = {"production": "https://quickbooks.api.intuit.com",
       "sandbox": "https://sandbox-quickbooks.api.intuit.com"}
MINOR = "75"

# account_map keys the destination expects
REQUIRED_ACCOUNTS = ["checking", "sales_income", "discounts", "sales_tax_payable",
                     "tips_payable", "gift_card_liability", "square_fees", "over_short"]


def _c(x: Decimal) -> float:
    return float(Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class QboDestination:
    def __init__(self, conn):
        self.conn = conn
        self.env = conn.environment
        self.base = API[self.env]
        self.realm = conn.realm_or_location
        self.accts = conn.account_map
        self.client_id = conn.client_id
        self.client_secret = vault.decrypt(conn.client_secret) if conn.client_secret else ""
        self.refresh_token = vault.decrypt(conn.refresh_token_enc) if conn.refresh_token_enc else ""
        self.access_token = None

    # ---- auth ----
    def refresh(self) -> str:
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        r = requests.post(TOKEN_URL, timeout=60,
                          headers={"Authorization": f"Basic {basic}",
                                   "Content-Type": "application/x-www-form-urlencoded",
                                   "Accept": "application/json"},
                          data={"grant_type": "refresh_token", "refresh_token": self.refresh_token})
        r.raise_for_status()
        tok = r.json()
        self.access_token = tok["access_token"]
        self.refresh_token = tok.get("refresh_token", self.refresh_token)
        return self.refresh_token  # caller re-encrypts + persists (rotation)

    def _h(self):
        return {"Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json", "Content-Type": "application/json"}

    def _url(self, path):
        return f"{self.base}/v3/company/{self.realm}/{path}?minorversion={MINOR}"

    def _query(self, sql):
        r = requests.get(f"{self.base}/v3/company/{self.realm}/query"
                         f"?query={requests.utils.quote(sql)}&minorversion={MINOR}",
                         headers=self._h(), timeout=60)
        r.raise_for_status()
        return r.json().get("QueryResponse", {})

    # ---- JE line helpers ----
    def _dr(self, key, amt, desc):
        return {"DetailType": "JournalEntryLineDetail", "Amount": _c(amt), "Description": desc,
                "JournalEntryLineDetail": {"PostingType": "Debit", "AccountRef": {"value": self.accts[key]}}}

    def _cr(self, key, amt, desc):
        return {"DetailType": "JournalEntryLineDetail", "Amount": _c(amt), "Description": desc,
                "JournalEntryLineDetail": {"PostingType": "Credit", "AccountRef": {"value": self.accts[key]}}}

    def build_cc_je(self, day: str, b: Batch) -> dict:
        lines = [
            self._dr("checking", b.deposit, "CC deposit — Square payout"),
            self._dr("square_fees", b.fees, "Square fees (processing + gift-card load)"),
            self._cr("sales_income", b.gross, "Gross product sales (card)"),
            self._cr("sales_tax_payable", b.tax, "Sales tax collected (Square exact)"),
            self._cr("tips_payable", b.tips, "Tips collected"),
        ]
        if b.discounts:
            lines.append(self._dr("discounts", -b.discounts, "Discounts"))  # discounts stored negative
        if b.gift_cards_sold:
            lines.append(self._cr("gift_card_liability", b.gift_cards_sold, "Gift cards sold"))
        if b.gift_card_redemptions:
            lines.append(self._dr("gift_card_liability", b.gift_card_redemptions, "Gift card redemptions"))
        if b.over_short:
            lines.append((self._cr if b.over_short > 0 else self._dr)("over_short", abs(b.over_short), "Over and short"))
        return {"DocNumber": f"SQ-{day.replace('-','')}-CC", "TxnDate": day,
                "PrivateNote": f"DailyLedger CARD batch {day}", "Line": lines}

    def build_cash_je(self, day: str, b: Batch) -> dict:
        lines = [self._dr("checking", b.deposit, "Cash deposit"),
                 self._cr("sales_income", b.gross, "Gross product sales (cash)")]
        if b.tax:
            lines.append(self._cr("sales_tax_payable", b.tax, "Sales tax collected (Square exact)"))
        if b.discounts:
            lines.append(self._dr("discounts", -b.discounts, "Discounts"))
        if b.over_short:
            lines.append((self._cr if b.over_short > 0 else self._dr)("over_short", abs(b.over_short), "Over and short"))
        return {"DocNumber": f"SQ-{day.replace('-','')}-CASH", "TxnDate": day,
                "PrivateNote": f"DailyLedger CASH batch {day}", "Line": lines}

    # ---- posting (idempotent) ----
    def _existing(self, doc):
        rows = self._query(f"select Id, TxnDate from JournalEntry where DocNumber = '{doc}'").get("JournalEntry", [])
        return rows[0] if rows else None

    def post_batch(self, body: dict, dry_run: bool = False) -> dict:
        doc = body["DocNumber"]
        existing = self._existing(doc)
        if existing:
            return {"status": "skipped", "reason": "already_exists", "qbo_id": existing["Id"], "doc_number": doc, "body": body}
        if dry_run:
            return {"status": "drafted", "doc_number": doc, "body": body}
        r = requests.post(self._url("journalentry"), headers=self._h(), json=body, timeout=90)
        if r.status_code >= 400:
            raise RuntimeError(f"JE post {doc} {r.status_code}: {r.text[:400]}")
        je = r.json()["JournalEntry"]
        d = sum(Decimal(str(l["Amount"])) for l in je["Line"] if l["JournalEntryLineDetail"]["PostingType"] == "Debit")
        return {"status": "posted", "doc_number": doc, "qbo_id": je["Id"], "balanced_total": str(d), "body": body}

    def post_day(self, db: DailyBatches, dry_run: bool = False) -> dict:
        return {"cc": self.post_batch(self.build_cc_je(db.business_date, db.cc), dry_run),
                "cash": self.post_batch(self.build_cash_je(db.business_date, db.cash), dry_run)}
