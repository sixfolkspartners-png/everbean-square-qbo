"""
Fix for the Automated-Sales-Tax finding: QBO (UsingSalesTax=true) ignores the
TxnTaxDetail.TotalTax override and recomputes tax. So we DON'T use QBO's tax
engine — every line is non-taxable (QBO tax = $0) and Square's exact tax is a
liability LINE ITEM (Square Sales Tax Payable). Total ties to the penny.

This deletes the bad Aug-4 receipts and re-posts the corrected ones, then reads
back and validates: total matches AND QBO-computed tax == $0.

Run: cd engine && set -a && source .env && set +a && python -m scripts.repost_tax_as_liability
"""
import os, re, json, requests
from decimal import Decimal
from src.qbo_client import QBOClient, API_BASE
import config

REALM = None
def _u(path): return f"{API_BASE}/v3/company/{config.QBO_REALM_ID}/{path}?minorversion={config.QBO_MINOR_VERSION}"
def query(qbo, sql):
    r = requests.get(f"{API_BASE}/v3/company/{config.QBO_REALM_ID}/query"
                     f"?query={requests.utils.quote(sql)}&minorversion={config.QBO_MINOR_VERSION}",
                     headers=qbo._headers(), timeout=60); r.raise_for_status()
    return r.json().get("QueryResponse", {})
def create(qbo, entity, body):
    r = requests.post(_u(entity), headers=qbo._headers(), json=body, timeout=60)
    if r.status_code >= 400: raise RuntimeError(f"{entity} {r.status_code}: {r.text[:300]}")
    return r.json().get(entity.capitalize(), {})
def ensure_account(qbo, name, t, st):
    rows = query(qbo, f"select Id from Account where Name = '{name}'").get("Account", [])
    return rows[0]["Id"] if rows else create(qbo, "account", {"Name": name, "AccountType": t, "AccountSubType": st})["Id"]
def ensure_item(qbo, name, acct_id, taxable=False):
    rows = query(qbo, f"select Id from Item where Name = '{name}'").get("Item", [])
    return rows[0]["Id"] if rows else create(qbo, "item",
        {"Name": name, "Type": "Service", "IncomeAccountRef": {"value": acct_id}, "Taxable": taxable})["Id"]
def delete_receipt(qbo, doc):
    rows = query(qbo, f"select Id, SyncToken from SalesReceipt where DocNumber = '{doc}'").get("SalesReceipt", [])
    for sr in rows:
        r = requests.post(_u("salesreceipt") + "&operation=delete", headers=qbo._headers(),
                          json={"Id": sr["Id"], "SyncToken": sr["SyncToken"]}, timeout=60)
        print(f"   deleted {doc} id={sr['Id']} -> {r.status_code}")

def line(item_id, desc, amt):
    return {"DetailType": "SalesItemLineDetail", "Amount": float(Decimal(str(amt))),
            "Description": desc, "SalesItemLineDetail": {"ItemRef": {"value": item_id},
            "TaxCodeRef": {"value": "NON"}, "Qty": 1}}

def receipt(day, suffix, lines, deposit_acct, note):
    return {"CustomerRef": {"value": config.QBO_SQUARE_CUSTOMER_ID}, "TxnDate": day,
            "DocNumber": f"SQ-{day.replace('-','')}-{suffix}", "Line": lines,
            "DepositToAccountRef": {"value": deposit_acct}, "PrivateNote": note}

def main():
    qbo = QBOClient(os.environ["QBO_CLIENT_ID"], os.environ["QBO_CLIENT_SECRET"], os.environ["QBO_REFRESH_TOKEN"])
    qbo.refresh()
    try:
        p = os.path.join(os.path.dirname(__file__), "..", ".env")
        txt = open(p).read()                       # read FIRST (open(w) truncates)
        txt = re.sub(r"(?m)^QBO_REFRESH_TOKEN=.*$", f"QBO_REFRESH_TOKEN={qbo.refresh_token}", txt)
        with open(p, "w") as f: f.write(txt)
    except Exception as e: print("persist:", e)

    it = {n: query(qbo, f"select Id from Item where Name = '{n}'")["Item"][0]["Id"]
          for n in ("Square sales item","Square Discount","Tips","Gift Card","Square Fees")}
    lia_tax = ensure_account(qbo, "Square Sales Tax Payable", "Other Current Liability", "SalesTaxPayable")
    it_tax = ensure_item(qbo, "Square Sales Tax", lia_tax)
    dep = "35"  # Checking

    delete_receipt(qbo, "SQ-20260804-CC"); delete_receipt(qbo, "SQ-20260804-CASH")

    cc = receipt("2026-08-04", "CC", [
        line(it["Square sales item"], "Gross product sales (card)", "1800.23"),
        line(it["Square Discount"],   "Discounts",                  "-10.05"),
        line(it_tax,                  "Sales tax (Square exact)",   "80.39"),
        line(it["Tips"],              "Tips",                       "260.48"),
        line(it["Gift Card"],         "Gift cards sold",            "100.00"),
        line(it["Gift Card"],         "Gift card redemptions",      "-85.92"),
        line(it["Square Fees"],       "Square fees",                "-68.68"),
    ], dep, "CARD batch 2026-08-04 (tax as liability line; QBO tax must be $0)")

    cash = receipt("2026-08-04", "CASH", [
        line(it["Square sales item"], "Gross product sales (cash)", "212.39"),
        line(it_tax,                  "Sales tax (Square exact)",   "9.56"),
    ], dep, "CASH batch 2026-08-04")

    for suffix, body, exp in (("CC", cc, Decimal("2076.45")), ("CASH", cash, Decimal("221.95"))):
        r = requests.post(_u("salesreceipt"), headers=qbo._headers(), json=body, timeout=90)
        if r.status_code >= 400:
            print(f"[{suffix}] POST FAILED {r.status_code}: {r.text[:400]}"); continue
        sr = r.json()["SalesReceipt"]
        total = Decimal(str(sr["TotalAmt"])); tax = Decimal(str(sr.get("TxnTaxDetail", {}).get("TotalTax", "0")))
        print(f"[{suffix}] id={sr['Id']} total=${total} (exp ${exp} {'OK' if abs(total-exp)<Decimal('0.005') else 'FAIL'})  "
              f"QBO_tax=${tax} ({'OK $0' if tax==0 else 'FAIL not zero'})")

if __name__ == "__main__":
    main()
