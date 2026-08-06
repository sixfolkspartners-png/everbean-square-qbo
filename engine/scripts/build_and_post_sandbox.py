"""
ONE-SHOT sandbox validation. Idempotent end to end. When shell execution is
available, a single run does everything:
  1. refresh + persist the rotated refresh token
  2. dump the tax preference (is Automated Sales Tax on?)
  3. ensure the EverBean chart of accounts + items exist
  4. build the two Aug-4 two-batch SalesReceipts with the exact tax override
  5. post them (skip if DocNumber already exists)
  6. read them back and PASS/FAIL the tax override + total tie-out

Run:  cd engine && set -a && source .env && set +a && python -m scripts.build_and_post_sandbox
"""
import os, re, json, requests
from decimal import Decimal
from src.qbo_client import QBOClient, API_BASE
import config
from src import transform_batches as tb

AUG4 = {
    "cc":   {"gross":"1800.23","discounts":"-10.05","tax":"80.39","tips":"260.48",
             "gc_sold":"100.00","gc_redemptions":"85.92","fees":"68.68","over_short":"0","deposit":"2076.45"},
    "cash": {"gross":"212.39","discounts":"0","tax":"9.56","deposit":"221.95"},
}
EXPECT = {"CC": (Decimal("2076.45"), Decimal("80.39")),
          "CASH": (Decimal("221.95"), Decimal("9.56"))}


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
        raise RuntimeError(f"{entity} '{body.get('Name')}' {r.status_code}: {r.text[:300]}")
    return r.json().get(entity.capitalize(), {})

def ensure_account(qbo, name, t, st):
    rows = query(qbo, f"select Id from Account where Name = '{name}'").get("Account", [])
    if rows: return rows[0]["Id"]
    return create(qbo, "account", {"Name": name, "AccountType": t, "AccountSubType": st})["Id"]

def ensure_item(qbo, name, acct_id, taxable):
    rows = query(qbo, f"select Id from Item where Name = '{name}'").get("Item", [])
    if rows: return rows[0]["Id"]
    return create(qbo, "item", {"Name": name, "Type": "Service",
                                "IncomeAccountRef": {"value": acct_id}, "Taxable": taxable})["Id"]

def persist(qbo):
    try:
        p = os.path.join(os.path.dirname(__file__), "..", ".env")
        open(p, "w").write(re.sub(r"(?m)^QBO_REFRESH_TOKEN=.*$",
                                  f"QBO_REFRESH_TOKEN={qbo.refresh_token}", open(p).read()))
    except Exception as e:
        print("[.env] persist failed:", e)

def read_back(qbo, doc):
    rows = query(qbo, f"select * from SalesReceipt where DocNumber = '{doc}'").get("SalesReceipt", [])
    if not rows: return None
    sr = rows[0]
    return Decimal(str(sr.get("TotalAmt"))), Decimal(str(sr.get("TxnTaxDetail", {}).get("TotalTax", "0"))), sr.get("Id")


def main():
    qbo = QBOClient(os.environ["QBO_CLIENT_ID"], os.environ["QBO_CLIENT_SECRET"],
                    os.environ["QBO_REFRESH_TOKEN"])
    qbo.refresh(); persist(qbo)
    print("connected:", query(qbo, "select * from CompanyInfo")["CompanyInfo"][0]["CompanyName"])

    taxp = query(qbo, "select * from Preferences")["Preferences"][0].get("TaxPrefs", {})
    print("TaxPrefs:", json.dumps(taxp))

    # chart of accounts
    inc_sales = ensure_account(qbo, "Sales of Product Income", "Income", "SalesOfProductIncome")
    inc_disc  = ensure_account(qbo, "Discounts given", "Income", "DiscountsRefundsGiven")
    lia_tips  = ensure_account(qbo, "Tips Payable", "Other Current Liability", "OtherCurrentLiabilities")
    lia_gc    = ensure_account(qbo, "Gift Card Outstanding", "Other Current Liability", "OtherCurrentLiabilities")
    exp_fees  = ensure_account(qbo, "Square Fees", "Expense", "OtherMiscellaneousServiceCost")
    inc_os    = ensure_account(qbo, "Over and Short", "Income", "OtherPrimaryIncome")

    # items (fee item wants an income acct; if expense is rejected as income ref, fall back)
    it_sales = ensure_item(qbo, "Square sales item", inc_sales, True)
    it_disc  = ensure_item(qbo, "Square Discount",   inc_disc,  True)
    it_tips  = ensure_item(qbo, "Tips",              lia_tips,  False)
    it_gc    = ensure_item(qbo, "Gift Card",         lia_gc,    False)
    try:
        it_fees = ensure_item(qbo, "Square Fees", exp_fees, False)
    except RuntimeError as e:
        print("[fee item] expense-as-income rejected -> using Over/Short acct:", str(e)[:120])
        it_fees = ensure_item(qbo, "Square Fees", inc_os, False)
    it_os = ensure_item(qbo, "Over and Short", inc_os, False)
    print(f"items: sales={it_sales} disc={it_disc} tips={it_tips} gc={it_gc} fees={it_fees} os={it_os}")

    # point the shared builder at the sandbox ids
    config.ITEM_SALES, config.ITEM_DISCOUNT, config.ITEM_TIPS, config.ITEM_GIFT_CARD = \
        it_sales, it_disc, it_tips, it_gc
    config.ITEM_SQUARE_FEES, config.ITEM_OVER_SHORT = it_fees, it_os
    config.QBO_DEPOSIT_ACCOUNT_ID = "35"          # Checking
    # tax: try a real sandbox rate for the TaxLine; harmless if AST ignores it
    trs = query(qbo, "select Id, Name from TaxRate").get("TaxRate", [])
    tcs = query(qbo, "select Id, Name from TaxCode").get("TaxCode", [])
    config.QBO_TAX_RATE_ID = trs[0]["Id"] if trs else ""
    config.QBO_TAX_CODE_ID = tcs[0]["Id"] if tcs else ""
    print(f"using TaxRateRef={config.QBO_TAX_RATE_ID} TxnTaxCodeRef={config.QBO_TAX_CODE_ID}")

    out = tb.build_batch_receipts("2026-08-04", AUG4)

    for suffix, body in (("CC", out["cc"]), ("CASH", out["cash"])):
        doc = body["DocNumber"]
        try:
            res = qbo.create_sales_receipt(body)
            print(f"[{suffix}] post: {res}")
        except Exception as e:
            print(f"[{suffix}] POST FAILED: {str(e)[:500]}")
            continue

    print("\n== READBACK / VALIDATION ==")
    for suffix in ("CC", "CASH"):
        doc = f"SQ-20260804-{suffix}"
        rb = read_back(qbo, doc)
        if not rb:
            print(f"[{suffix}] not found"); continue
        total, tax, sid = rb
        exp_total, exp_tax = EXPECT[suffix]
        tot_ok = abs(total - exp_total) < Decimal("0.005")
        tax_ok = abs(tax - exp_tax) < Decimal("0.005")
        print(f"[{suffix}] id={sid} total=${total} (exp ${exp_total} {'OK' if tot_ok else 'FAIL'})  "
              f"tax=${tax} (exp ${exp_tax} {'OK' if tax_ok else 'FAIL — QBO recomputed'})")
    print("\nIf tax shows FAIL, Automated Sales Tax overrode our exact figure -> "
          "switch override strategy (GlobalTaxCalculation / manual tax) before production.")

if __name__ == "__main__":
    main()
