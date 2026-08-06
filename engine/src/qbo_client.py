"""
QuickBooks Online client — OAuth2 token refresh + SalesReceipt create with
idempotency (query by DocNumber before posting so a re-run never duplicates).

Uses the raw Intuit Accounting API, which — unlike the MCP connector — supports
the TxnTaxDetail.TotalTax override we need.
"""
from __future__ import annotations
import base64
import requests
import config

TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
API_BASE = {
    "production": "https://quickbooks.api.intuit.com",
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
}[config.QBO_ENV]


class QBOClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.access_token = None

    # ---- OAuth2 ---------------------------------------------------------
    def refresh(self) -> dict:
        """Exchange the refresh token for a new access token. Intuit may rotate
        the refresh token; the (possibly new) one is returned so the caller can
        persist it (see token_store)."""
        basic = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()).decode()
        r = requests.post(
            TOKEN_URL,
            headers={"Authorization": f"Basic {basic}",
                     "Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "application/json"},
            data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
            timeout=60,
        )
        r.raise_for_status()
        tok = r.json()
        self.access_token = tok["access_token"]
        self.refresh_token = tok.get("refresh_token", self.refresh_token)
        return tok

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}",
                "Accept": "application/json", "Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        return (f"{API_BASE}/v3/company/{config.QBO_REALM_ID}/{path}"
                f"?minorversion={config.QBO_MINOR_VERSION}")

    # ---- Idempotency: has this day already posted? ----------------------
    def find_sales_receipt(self, doc_number: str) -> dict | None:
        q = (f"select Id, DocNumber, TotalAmt from SalesReceipt "
             f"where DocNumber = '{doc_number}'")
        r = requests.get(
            f"{API_BASE}/v3/company/{config.QBO_REALM_ID}/query"
            f"?query={requests.utils.quote(q)}&minorversion={config.QBO_MINOR_VERSION}",
            headers=self._headers(), timeout=60)
        r.raise_for_status()
        rows = r.json().get("QueryResponse", {}).get("SalesReceipt", [])
        return rows[0] if rows else None

    # ---- Create --------------------------------------------------------
    def create_sales_receipt(self, body: dict, skip_if_exists: bool = True) -> dict:
        doc = body.get("DocNumber")
        if skip_if_exists and doc:
            existing = self.find_sales_receipt(doc)
            if existing:
                return {"skipped": True, "reason": "already_exists",
                        "id": existing["Id"], "doc_number": doc}
        r = requests.post(self._url("salesreceipt"),
                          headers=self._headers(), json=body, timeout=90)
        if r.status_code >= 400:
            raise RuntimeError(f"QBO SalesReceipt create failed {r.status_code}: {r.text}")
        sr = r.json().get("SalesReceipt", {})
        return {"skipped": False, "id": sr.get("Id"),
                "doc_number": sr.get("DocNumber"), "total": sr.get("TotalAmt")}
