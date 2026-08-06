"""
Determine empirically whether QBO (this AST sandbox) will accept an EXACT sales
tax in the tax field via the API. Posts throwaway cash-style receipts with
different tax strategies, reads back the stored TotalTax, then deletes them.

Cash example: one taxable $212.39 line; Square's exact tax = $9.56.
If QBO honors an override, TotalTax comes back 9.56; if AST recomputes, ~16.99 (8%).

Run: cd engine && set -a && source .env && set +a && python -m scripts.tax_experiment
"""
import os, requests
from decimal import Decimal
from src.qbo_client import QBOClient, API_BASE
import config

def _u(p): return f"{API_BASE}/v3/company/{config.QBO_REALM_ID}/{p}?minorversion={config.QBO_MINOR_VERSION}"
def query(qbo, sql):
    r = requests.get(f"{API_BASE}/v3/company/{config.QBO_REALM_ID}/query"
                     f"?query={requests.utils.quote(sql)}&minorversion={config.QBO_MINOR_VERSION}",
                     headers=qbo._headers(), timeout=60); r.raise_for_status()
    return r.json().get("QueryResponse", {})
def item_id(qbo, name): return query(qbo, f"select Id from Item where Name='{name}'")["Item"][0]["Id"]
def delete(qbo, doc):
    for sr in query(qbo, f"select Id, SyncToken from SalesReceipt where DocNumber='{doc}'").get("SalesReceipt", []):
        requests.post(_u("salesreceipt")+"&operation=delete", headers=qbo._headers(),
                      json={"Id": sr["Id"], "SyncToken": sr["SyncToken"]}, timeout=60)

def taxline(sales_item, rate_id):
    return [{"DetailType":"SalesItemLineDetail","Amount":212.39,"Description":"Gross (taxable)",
             "SalesItemLineDetail":{"ItemRef":{"value":sales_item},"TaxCodeRef":{"value":"TAX"},"Qty":1}}]

def post(qbo, doc, body):
    body.update({"CustomerRef":{"value":config.QBO_SQUARE_CUSTOMER_ID},"TxnDate":"2026-08-04",
                 "DocNumber":doc,"DepositToAccountRef":{"value":"35"}})
    r = requests.post(_u("salesreceipt"), headers=qbo._headers(), json=body, timeout=90)
    if r.status_code>=400: return f"POST FAIL {r.status_code}: {r.text[:200]}"
    sr=r.json()["SalesReceipt"]
    return f"total=${sr['TotalAmt']}  TotalTax=${sr.get('TxnTaxDetail',{}).get('TotalTax','0')}"

def main():
    qbo=QBOClient(os.environ["QBO_CLIENT_ID"],os.environ["QBO_CLIENT_SECRET"],os.environ["QBO_REFRESH_TOKEN"]); qbo.refresh()
    sales=item_id(qbo,"Square sales item")
    rates=query(qbo,"select Id, Name, RateValue from TaxRate").get("TaxRate",[])
    codes=query(qbo,"select Id, Name from TaxCode").get("TaxCode",[])
    print("rates:", [(t['Id'],t.get('Name'),t.get('RateValue')) for t in rates])
    print("codes:", [(t['Id'],t.get('Name')) for t in codes])
    rid = rates[0]['Id'] if rates else ""

    strategies = {
      "A_taxable_no_detail":      {"Line":taxline(sales,rid)},  # pure AST compute (baseline)
      "B_TotalTax_only":          {"Line":taxline(sales,rid),"TxnTaxDetail":{"TotalTax":9.56}},
      "C_TotalTax_taxline_fixed": {"Line":taxline(sales,rid),"TxnTaxDetail":{"TotalTax":9.56,
                                     "TaxLine":[{"DetailType":"TaxLineDetail","Amount":9.56,
                                       "TaxLineDetail":{"TaxRateRef":{"value":rid},"PercentBased":False,"NetAmountTaxable":212.39}}]}},
      "D_globalcalc_notapplic":   {"Line":taxline(sales,rid),"GlobalTaxCalculation":"NotApplicable","TxnTaxDetail":{"TotalTax":9.56}},
    }
    for name, body in strategies.items():
        doc=f"SQ-TAXTEST-{name[:1]}"
        delete(qbo, doc)
        print(f"\n[{name}] -> {post(qbo, doc, body)}")
        delete(qbo, doc)
    print("\n(want: TotalTax=$9.56 in the tax field. If all show ~$16.99, AST ignores API overrides.)")

if __name__=="__main__":
    main()
