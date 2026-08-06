"""
End-to-end proof that the CANONICAL engine builder (src/transform_batches.py,
now tax-as-liability) posts correct receipts to the live sandbox. Resolves the
sandbox item ids by name, builds via build_batch_receipts, deletes any prior
Aug-4 receipts, posts, reads back, and validates total + QBO tax == $0.

Run: cd engine && set -a && source .env && set +a && python -m scripts.validate_canonical
"""
import os, re, requests
from decimal import Decimal
from src.qbo_client import QBOClient, API_BASE
from src import transform_batches as tb
import config

AUG4 = {
    "cc":   {"gross":"1800.23","discounts":"-10.05","tax":"80.39","tips":"260.48",
             "gc_sold":"100.00","gc_redemptions":"85.92","fees":"68.68","over_short":"0","deposit":"2076.45"},
    "cash": {"gross":"212.39","discounts":"0","tax":"9.56","deposit":"221.95"},
}
EXPECT = {"CC": Decimal("2076.45"), "CASH": Decimal("221.95")}

def _u(p): return f"{API_BASE}/v3/company/{config.QBO_REALM_ID}/{p}?minorversion={config.QBO_MINOR_VERSION}"
def query(qbo, sql):
    r = requests.get(f"{API_BASE}/v3/company/{config.QBO_REALM_ID}/query"
                     f"?query={requests.utils.quote(sql)}&minorversion={config.QBO_MINOR_VERSION}",
                     headers=qbo._headers(), timeout=60); r.raise_for_status()
    return r.json().get("QueryResponse", {})
def item_id(qbo, name):
    return query(qbo, f"select Id from Item where Name = '{name}'")["Item"][0]["Id"]
def delete_receipt(qbo, doc):
    for sr in query(qbo, f"select Id, SyncToken from SalesReceipt where DocNumber = '{doc}'").get("SalesReceipt", []):
        requests.post(_u("salesreceipt") + "&operation=delete", headers=qbo._headers(),
                      json={"Id": sr["Id"], "SyncToken": sr["SyncToken"]}, timeout=60)

def main():
    qbo = QBOClient(os.environ["QBO_CLIENT_ID"], os.environ["QBO_CLIENT_SECRET"], os.environ["QBO_REFRESH_TOKEN"])
    qbo.refresh()
    try:
        p = os.path.join(os.path.dirname(__file__), "..", ".env")
        txt = open(p).read()
        with open(p, "w") as f: f.write(re.sub(r"(?m)^QBO_REFRESH_TOKEN=.*$", f"QBO_REFRESH_TOKEN={qbo.refresh_token}", txt))
    except Exception as e: print("persist:", e)

    # point config at the sandbox ids (resolved by name)
    config.ITEM_SALES     = item_id(qbo, "Square sales item")
    config.ITEM_DISCOUNT  = item_id(qbo, "Square Discount")
    config.ITEM_TIPS      = item_id(qbo, "Tips")
    config.ITEM_GIFT_CARD = item_id(qbo, "Gift Card")
    config.ITEM_SQUARE_FEES = item_id(qbo, "Square Fees")
    config.ITEM_OVER_SHORT  = item_id(qbo, "Over and Short")
    config.ITEM_SALES_TAX   = item_id(qbo, "Square Sales Tax")
    config.QBO_DEPOSIT_ACCOUNT_ID = "35"  # Checking
    print("resolved sandbox item ids:",
          f"sales={config.ITEM_SALES} disc={config.ITEM_DISCOUNT} tips={config.ITEM_TIPS} "
          f"gc={config.ITEM_GIFT_CARD} fees={config.ITEM_SQUARE_FEES} os={config.ITEM_OVER_SHORT} "
          f"tax={config.ITEM_SALES_TAX}")

    out = tb.build_batch_receipts("2026-08-04", AUG4)

    delete_receipt(qbo, "SQ-20260804-CC"); delete_receipt(qbo, "SQ-20260804-CASH")

    print("\n== posting via canonical build_batch_receipts ==")
    for suffix, body in (("CC", out["cc"]), ("CASH", out["cash"])):
        r = requests.post(_u("salesreceipt"), headers=qbo._headers(), json=body, timeout=90)
        if r.status_code >= 400:
            print(f"[{suffix}] POST FAILED {r.status_code}: {r.text[:400]}"); continue
        sr = r.json()["SalesReceipt"]
        total = Decimal(str(sr["TotalAmt"])); tax = Decimal(str(sr.get("TxnTaxDetail", {}).get("TotalTax", "0")))
        exp = EXPECT[suffix]
        print(f"[{suffix}] id={sr['Id']} total=${total} (exp ${exp} {'OK' if abs(total-exp)<Decimal('0.005') else 'FAIL'})  "
              f"QBO_tax=${tax} ({'OK $0' if tax==0 else 'FAIL'})  hasTxnTaxDetail={'TxnTaxDetail' in body}")

if __name__ == "__main__":
    main()
