"""
Stand up the EverBean chart of accounts + items in the QBO sandbox, idempotently
(query by name; create only if missing). Prints a CONFIG block with the resulting
sandbox IDs to paste into .env, and dumps the tax preference so we know whether
Automated Sales Tax is on (which decides the tax-override strategy).

Run:  cd engine && set -a && source .env && set +a && python -m scripts.setup_sandbox_coa
"""
import os, json, requests
from src.qbo_client import QBOClient, API_BASE
import config

H = None
def query(qbo, sql):
    r = requests.get(f"{API_BASE}/v3/company/{config.QBO_REALM_ID}/query"
                     f"?query={requests.utils.quote(sql)}&minorversion={config.QBO_MINOR_VERSION}",
                     headers=qbo._headers(), timeout=60)
    r.raise_for_status()
    return r.json().get("QueryResponse", {})

def create(qbo, entity, body):
    r = requests.post(f"{API_BASE}/v3/company/{config.QBO_REALM_ID}/{entity}"
                      f"?minorversion={config.QBO_MINOR_VERSION}",
                      headers=qbo._headers(), json=body, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"create {entity} '{body.get('Name')}' -> {r.status_code}: {r.text}")
    key = entity.capitalize()
    return r.json().get(key, r.json())

def ensure_account(qbo, name, acct_type, sub_type):
    rows = query(qbo, f"select Id, Name from Account where Name = '{name}'").get("Account", [])
    if rows:
        print(f"   [=] account '{name}' exists id={rows[0]['Id']}")
        return rows[0]["Id"]
    body = {"Name": name, "AccountType": acct_type, "AccountSubType": sub_type}
    acc = create(qbo, "account", body)
    print(f"   [+] account '{name}' created id={acc['Id']} ({acct_type}/{sub_type})")
    return acc["Id"]

def ensure_item(qbo, name, income_acct_id, taxable):
    rows = query(qbo, f"select Id, Name from Item where Name = '{name}'").get("Item", [])
    if rows:
        print(f"   [=] item '{name}' exists id={rows[0]['Id']}")
        return rows[0]["Id"]
    body = {"Name": name, "Type": "Service",
            "IncomeAccountRef": {"value": income_acct_id}, "Taxable": taxable}
    it = create(qbo, "item", body)
    print(f"   [+] item '{name}' created id={it['Id']} -> acct {income_acct_id} taxable={taxable}")
    return it["Id"]

def main():
    qbo = QBOClient(os.environ["QBO_CLIENT_ID"], os.environ["QBO_CLIENT_SECRET"],
                    os.environ["QBO_REFRESH_TOKEN"])
    qbo.refresh()
    # persist rotated token
    try:
        p = os.path.join(os.path.dirname(__file__), "..", ".env")
        import re
        t = open(p).read()
        open(p, "w").write(re.sub(r"(?m)^QBO_REFRESH_TOKEN=.*$",
                                  f"QBO_REFRESH_TOKEN={qbo.refresh_token}", t))
    except Exception as e:
        print("[.env] persist failed:", e)

    # ---- tax mode ----
    prefs = query(qbo, "select * from Preferences").get("Preferences", [{}])[0]
    taxp = prefs.get("TaxPrefs", {})
    print("== Tax preference ==")
    print("   ", json.dumps(taxp))
    print()

    # ---- accounts ----
    print("== Accounts ==")
    inc_sales = ensure_account(qbo, "Sales of Product Income", "Income", "SalesOfProductIncome")
    inc_disc  = ensure_account(qbo, "Discounts given", "Income", "DiscountsRefundsGiven")
    lia_tips  = ensure_account(qbo, "Tips Payable", "Other Current Liability", "OtherCurrentLiabilities")
    lia_gc    = ensure_account(qbo, "Gift Card Outstanding", "Other Current Liability", "OtherCurrentLiabilities")
    exp_fees  = ensure_account(qbo, "Square Fees", "Expense", "OtherMiscellaneousServiceCost")
    inc_os    = ensure_account(qbo, "Over and Short", "Income", "OtherPrimaryIncome")

    # ---- items ----
    print("\n== Items ==")
    it_sales = ensure_item(qbo, "Square sales item", inc_sales, taxable=True)
    it_disc  = ensure_item(qbo, "Square Discount",   inc_disc,  taxable=True)
    it_tips  = ensure_item(qbo, "Tips",              lia_tips,  taxable=False)
    it_gc    = ensure_item(qbo, "Gift Card",         lia_gc,    taxable=False)
    try:
        it_fees = ensure_item(qbo, "Square Fees", exp_fees, taxable=False)
    except RuntimeError as e:
        print("   [!] fee item to expense acct failed, retrying against income acct:", str(e)[:180])
        it_fees = ensure_item(qbo, "Square Fees", inc_os, taxable=False)
    it_os = ensure_item(qbo, "Over and Short", inc_os, taxable=False)

    print("\n== CONFIG (sandbox) ==")
    print(f"ITEM_SALES={it_sales}  ITEM_DISCOUNT={it_disc}  ITEM_TIPS={it_tips}  ITEM_GIFT_CARD={it_gc}")
    print(f"QBO_ITEM_SQUARE_FEES={it_fees}")
    print(f"QBO_ITEM_OVER_SHORT={it_os}")
    print(f"QBO_DEPOSIT_ACCOUNT_ID=35   # Checking")
    print("tax rates:")
    for t in query(qbo, "select Id, Name, RateValue from TaxRate").get("TaxRate", []):
        print(f"   id={t['Id']} rate={t.get('RateValue')} {t.get('Name')}")
    for t in query(qbo, "select Id, Name from TaxCode").get("TaxCode", []):
        print(f"   taxcode id={t['Id']} {t.get('Name')}")

if __name__ == "__main__":
    main()
