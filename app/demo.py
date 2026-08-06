"""Seed EverBean as a real tenant row (encrypted tokens + account map resolved
live from QBO), then drive Aug 4 through the MULTI-TENANT pipeline to prove the
architecture end to end (Connection -> source -> reconcile gate -> JE post -> SyncRun).

Run: cd /home/claude/dailyledger && python -m app.demo
"""
import os, re, requests
from decimal import Decimal
from .models import make_session, Org, Connection, SyncRun
from . import vault
from .qbo import QboDestination, REQUIRED_ACCOUNTS
from .pipeline import run_day

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", "engine", ".env")
ACCOUNT_NAMES = {
    "checking": "Checking", "sales_income": "Sales of Product Income",
    "discounts": "Discounts given", "sales_tax_payable": "Square Sales Tax Payable",
    "tips_payable": "Tips Payable", "gift_card_liability": "Gift Card Outstanding",
    "square_fees": "Square Fees", "over_short": "Over and Short",
}

def load_env():
    d = {}
    for line in open(ENV_PATH):
        m = re.match(r"^([A-Z_]+)=(.*)$", line.strip())
        if m: d[m.group(1)] = m.group(2)
    return d

def resolve_accounts(dest: QboDestination) -> dict:
    m = {}
    for key, name in ACCOUNT_NAMES.items():
        rows = dest._query(f"select Id from Account where Name = '{name}'").get("Account", [])
        if not rows: raise RuntimeError(f"account '{name}' not found in QBO {dest.realm}")
        m[key] = rows[0]["Id"]
    return m

def main():
    env = load_env()
    Session = make_session()
    s = Session()

    org = s.query(Org).filter_by(name="EverBean Coffee Co").first()
    if not org:
        org = Org(name="EverBean Coffee Co", timezone="America/Denver",
                  posting_format="journal_entry", rollout_mode="auto_post")
        s.add(org); s.commit()

    qbo = s.query(Connection).filter_by(org_id=org.id, provider="qbo").first()
    if not qbo:
        qbo = Connection(org_id=org.id, provider="qbo")
        s.add(qbo)
    qbo.environment = env.get("QBO_ENV", "sandbox")
    qbo.realm_or_location = env["QBO_REALM_ID"]
    qbo.client_id = env["QBO_CLIENT_ID"]
    qbo.client_secret = vault.encrypt(env["QBO_CLIENT_SECRET"])
    qbo.refresh_token_enc = vault.encrypt(env["QBO_REFRESH_TOKEN"])
    s.commit()

    # square connection placeholder (source stub doesn't need creds yet)
    if not s.query(Connection).filter_by(org_id=org.id, provider="square").first():
        s.add(Connection(org_id=org.id, provider="square",
                         realm_or_location="L5VY1TDS95SCC", environment="production")); s.commit()

    # resolve + store the account map
    dest = QboDestination(qbo); dest.refresh()
    qbo.refresh_token_enc = vault.encrypt(dest.refresh_token)
    qbo.account_map = resolve_accounts(dest)
    s.commit()
    print("seeded org:", org.name, "| qbo realm", qbo.realm_or_location,
          "| accounts", list(qbo.account_map.keys()))
    print("using dev fernet key:", vault.using_dev_key())

    # clean prior Aug-4 JEs so we post fresh THROUGH the pipeline
    for doc in ("SQ-20260804-CC", "SQ-20260804-CASH"):
        for je in dest._query(f"select Id, SyncToken from JournalEntry where DocNumber='{doc}'").get("JournalEntry", []):
            requests.post(dest._url("journalentry") + "&operation=delete", headers=dest._h(),
                          json={"Id": je["Id"], "SyncToken": je["SyncToken"]}, timeout=60)

    print("\n== run_day via multi-tenant pipeline ==")
    result = run_day(s, org.id, "2026-08-04")
    import json; print(json.dumps(result, indent=2))

    print("\n== SyncRun rows recorded ==")
    for r in s.query(SyncRun).filter_by(org_id=org.id, business_date="2026-08-04").all():
        print(f"   {r.business_date} {r.batch:<4} status={r.status:<8} doc={r.doc_number} qbo_id={r.qbo_id} deposit=${r.deposit}")

if __name__ == "__main__":
    main()
