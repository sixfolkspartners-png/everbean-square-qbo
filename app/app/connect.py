"""OAuth connect flow + first-connect onboarding (auto-provision the chart of
accounts a new tenant's QuickBooks needs). Plaid-style: build authorize URL ->
user approves in QBO -> callback exchanges the code -> we encrypt + store the
Connection and resolve/create the account map.
"""
from __future__ import annotations
import base64, secrets, urllib.parse, requests
from .settings import QBO
from . import vault

MINOR = "75"
API = {"production": "https://quickbooks.api.intuit.com",
       "sandbox": "https://sandbox-quickbooks.api.intuit.com"}

# DailyLedger accounts to ensure on connect: key -> (Name, AccountType, AccountSubType)
LEDGER_ACCOUNTS = {
    "sales_income":       ("Sales of Product Income", "Income", "SalesOfProductIncome"),
    "discounts":          ("Discounts given", "Income", "DiscountsRefundsGiven"),
    "sales_tax_payable":  ("Square Sales Tax Payable", "Other Current Liability", "SalesTaxPayable"),
    "tips_payable":       ("Tips Payable", "Other Current Liability", "OtherCurrentLiabilities"),
    "gift_card_liability":("Gift Card Outstanding", "Other Current Liability", "OtherCurrentLiabilities"),
    "square_fees":        ("Square Fees", "Expense", "OtherMiscellaneousServiceCost"),
    "over_short":         ("Over and Short", "Income", "OtherPrimaryIncome"),
}


# ------------- authorize + token exchange -------------
def qbo_authorize_url(state: str | None = None) -> tuple[str, str]:
    state = state or secrets.token_urlsafe(16)
    q = {"client_id": QBO.CLIENT_ID, "scope": QBO.SCOPE, "redirect_uri": QBO.REDIRECT_URI,
         "response_type": "code", "state": state}
    return f"{QBO.AUTHORIZE}?{urllib.parse.urlencode(q)}", state


def qbo_exchange_code(code: str) -> dict:
    basic = base64.b64encode(f"{QBO.CLIENT_ID}:{QBO.CLIENT_SECRET}".encode()).decode()
    r = requests.post(QBO.TOKEN, timeout=60,
                      headers={"Authorization": f"Basic {basic}",
                               "Content-Type": "application/x-www-form-urlencoded",
                               "Accept": "application/json"},
                      data={"grant_type": "authorization_code", "code": code,
                            "redirect_uri": QBO.REDIRECT_URI})
    r.raise_for_status()
    return r.json()  # access_token, refresh_token, ...


# ------------- onboarding: provision the chart of accounts -------------
class _Admin:
    def __init__(self, access_token, realm, env):
        self.at, self.realm, self.base = access_token, realm, API[env]

    def _h(self):
        return {"Authorization": f"Bearer {self.at}", "Accept": "application/json",
                "Content-Type": "application/json"}

    def query(self, sql):
        r = requests.get(f"{self.base}/v3/company/{self.realm}/query"
                         f"?query={requests.utils.quote(sql)}&minorversion={MINOR}",
                         headers=self._h(), timeout=60); r.raise_for_status()
        return r.json().get("QueryResponse", {})

    def create(self, body):
        r = requests.post(f"{self.base}/v3/company/{self.realm}/account?minorversion={MINOR}",
                          headers=self._h(), json=body, timeout=60)
        if r.status_code >= 400:
            raise RuntimeError(f"account create '{body['Name']}' {r.status_code}: {r.text[:200]}")
        return r.json()["Account"]

    def ensure(self, name, t, st):
        rows = self.query(f"select Id from Account where Name = '{name}'").get("Account", [])
        if rows:
            return rows[0]["Id"], False
        return self.create({"Name": name, "AccountType": t, "AccountSubType": st})["Id"], True

    def first_bank(self):
        rows = self.query("select Id, Name from Account where AccountType = 'Bank'").get("Account", [])
        return (rows[0]["Id"], rows[0]["Name"]) if rows else ("", "")


def bootstrap_qbo_accounts(access_token: str, realm: str, env: str,
                           deposit_account_id: str | None = None) -> dict:
    """Ensure the DailyLedger accounts exist; return {account_map, created, deposit}."""
    a = _Admin(access_token, realm, env)
    amap, created = {}, []
    for key, (name, t, st) in LEDGER_ACCOUNTS.items():
        aid, was_created = a.ensure(name, t, st)
        amap[key] = aid
        if was_created:
            created.append(name)
    # deposit ("checking"): tenant-selected, else the company's first Bank account
    if deposit_account_id:
        amap["checking"] = deposit_account_id
        dep_name = None
    else:
        amap["checking"], dep_name = a.first_bank()
    return {"account_map": amap, "created": created, "deposit_account_name": dep_name}


# ------------- persist a Connection from a completed connect -------------
def save_qbo_connection(session, org_id: int, realm: str, token_json: dict, account_map: dict):
    from .models import Connection
    conn = session.query(Connection).filter_by(org_id=org_id, provider="qbo").first()
    if not conn:
        conn = Connection(org_id=org_id, provider="qbo"); session.add(conn)
    conn.environment = QBO.ENV
    conn.realm_or_location = realm
    conn.client_id = QBO.CLIENT_ID
    conn.client_secret = vault.encrypt(QBO.CLIENT_SECRET)
    conn.refresh_token_enc = vault.encrypt(token_json["refresh_token"])
    conn.account_map = account_map
    conn.status = "connected"
    session.commit()
    return conn


# ------------- Square OAuth: token exchange + connection -------------
SQUARE_API = {"production": "https://connect.squareup.com",
              "sandbox": "https://connect.squareupsandbox.com"}
SQUARE_VERSION = "2024-07-17"


def square_exchange_code(code: str) -> dict:
    """Exchange the OAuth authorization code for a Square access token."""
    from .settings import SQUARE
    base = SQUARE_API.get(SQUARE.ENV, SQUARE_API["production"])
    r = requests.post(f"{base}/oauth2/token", timeout=60,
                      headers={"Content-Type": "application/json", "Square-Version": SQUARE_VERSION},
                      json={"client_id": SQUARE.CLIENT_ID, "client_secret": SQUARE.CLIENT_SECRET,
                            "code": code, "grant_type": "authorization_code",
                            "redirect_uri": SQUARE.REDIRECT_URI})
    r.raise_for_status()
    return r.json()  # access_token, refresh_token, merchant_id, expires_at, ...


def square_first_location(access_token: str) -> str:
    """Pick the seller's main active location id (the pipeline pulls per location)."""
    from .settings import SQUARE
    base = SQUARE_API.get(SQUARE.ENV, SQUARE_API["production"])
    r = requests.get(f"{base}/v2/locations", timeout=60,
                     headers={"Authorization": f"Bearer {access_token}", "Square-Version": SQUARE_VERSION})
    r.raise_for_status()
    locs = r.json().get("locations", [])
    active = [l for l in locs if l.get("status") == "ACTIVE"] or locs
    return active[0]["id"] if active else ""


def save_square_connection(session, org_id: int, token_json: dict, location_id: str):
    from .models import Connection
    from .settings import SQUARE
    conn = session.query(Connection).filter_by(org_id=org_id, provider="square").first()
    if not conn:
        conn = Connection(org_id=org_id, provider="square"); session.add(conn)
    conn.environment = SQUARE.ENV
    conn.realm_or_location = location_id
    conn.client_id = SQUARE.CLIENT_ID
    conn.client_secret = vault.encrypt(SQUARE.CLIENT_SECRET)
    # the pipeline reads refresh_token_enc as the Square Bearer token
    conn.refresh_token_enc = vault.encrypt(token_json["access_token"])
    conn.status = "connected"
    session.commit()
    return conn
