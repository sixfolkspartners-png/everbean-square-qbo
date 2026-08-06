"""
Prototype: post the Aug-4 two-batch day as daily-summary JOURNAL ENTRIES instead
of SalesReceipts. JEs are NOT processed by Automated Sales Tax, so every number
(incl. the exact $89.95 tax to Square Sales Tax Payable) is fully controlled.

CC batch JE (debits = credits = 2241.10):
  DR Checking 2076.45 | DR Square Fees 68.68 | DR Discounts given 10.05 | DR Gift Card Outstanding 85.92 (redeemed)
  CR Sales of Product Income 1800.23 | CR Square Sales Tax Payable 80.39 | CR Tips Payable 260.48 | CR Gift Card Outstanding 100.00 (sold)
Cash batch JE (221.95):
  DR Checking 221.95 | CR Sales of Product Income 212.39 | CR Square Sales Tax Payable 9.56

Run: cd engine && set -a && source .env && set +a && python -m scripts.prototype_journal_entry
"""
import os, re, requests
from decimal import Decimal
from src.qbo_client import QBOClient, API_BASE
import config

def _u(p): return f"{API_BASE}/v3/company/{config.QBO_REALM_ID}/{p}?minorversion={config.QBO_MINOR_VERSION}"
def query(qbo, sql):
    r = requests.get(f"{API_BASE}/v3/company/{config.QBO_REALM_ID}/query"
                     f"?query={requests.utils.quote(sql)}&minorversion={config.QBO_MINOR_VERSION}",
                     headers=qbo._headers(), timeout=60); r.raise_for_status()
    return r.json().get("QueryResponse", {})
def acct(qbo, name):
    return query(qbo, f"select Id from Account where Name = '{name}'")["Account"][0]["Id"]
def delete_je(qbo, doc):
    for je in query(qbo, f"select Id, SyncToken from JournalEntry where DocNumber = '{doc}'").get("JournalEntry", []):
        requests.post(_u("journalentry") + "&operation=delete", headers=qbo._headers(),
                      json={"Id": je["Id"], "SyncToken": je["SyncToken"]}, timeout=60)

def dr(a, amt, desc): return {"DetailType":"JournalEntryLineDetail","Amount":float(amt),"Description":desc,
                              "JournalEntryLineDetail":{"PostingType":"Debit","AccountRef":{"value":a}}}
def cr(a, amt, desc): return {"DetailType":"JournalEntryLineDetail","Amount":float(amt),"Description":desc,
                              "JournalEntryLineDetail":{"PostingType":"Credit","AccountRef":{"value":a}}}

def post_je(qbo, doc, lines, note):
    delete_je(qbo, doc)
    body = {"DocNumber": doc, "TxnDate": "2026-08-04", "PrivateNote": note, "Line": lines}
    r = requests.post(_u("journalentry"), headers=qbo._headers(), json=body, timeout=90)
    if r.status_code >= 400:
        print(f"[{doc}] POST FAILED {r.status_code}: {r.text[:400]}"); return
    je = r.json()["JournalEntry"]
    d = sum(Decimal(str(l["Amount"])) for l in je["Line"] if l["JournalEntryLineDetail"]["PostingType"]=="Debit")
    c = sum(Decimal(str(l["Amount"])) for l in je["Line"] if l["JournalEntryLineDetail"]["PostingType"]=="Credit")
    print(f"[{doc}] id={je['Id']}  debits=${d}  credits=${c}  balanced={d==c}")
    for l in je["Line"]:
        jd = l["JournalEntryLineDetail"]
        print(f"     {jd['PostingType']:<6} ${str(l['Amount']).rjust(8)}  {l.get('Description','')}")

def main():
    qbo = QBOClient(os.environ["QBO_CLIENT_ID"], os.environ["QBO_CLIENT_SECRET"], os.environ["QBO_REFRESH_TOKEN"])
    qbo.refresh()
    try:
        p = os.path.join(os.path.dirname(__file__), "..", ".env")
        txt = open(p).read()
        with open(p, "w") as f: f.write(re.sub(r"(?m)^QBO_REFRESH_TOKEN=.*$", f"QBO_REFRESH_TOKEN={qbo.refresh_token}", txt))
    except Exception as e: print("persist:", e)

    A = {n: acct(qbo, n) for n in ("Checking","Sales of Product Income","Discounts given",
                                   "Square Sales Tax Payable","Tips Payable","Gift Card Outstanding","Square Fees")}
    print("account ids:", A, "\n")

    cc_lines = [
        dr(A["Checking"], "2076.45", "CC deposit — Square payout"),
        dr(A["Square Fees"], "68.68", "Square fees (processing + gift-card load)"),
        dr(A["Discounts given"], "10.05", "Discounts"),
        dr(A["Gift Card Outstanding"], "85.92", "Gift card redemptions (draw down liability)"),
        cr(A["Sales of Product Income"], "1800.23", "Gross product sales (card)"),
        cr(A["Square Sales Tax Payable"], "80.39", "Sales tax collected (Square exact)"),
        cr(A["Tips Payable"], "260.48", "Tips collected"),
        cr(A["Gift Card Outstanding"], "100.00", "Gift cards sold (add to liability)"),
    ]
    cash_lines = [
        dr(A["Checking"], "221.95", "Cash deposit"),
        cr(A["Sales of Product Income"], "212.39", "Gross product sales (cash)"),
        cr(A["Square Sales Tax Payable"], "9.56", "Sales tax collected (Square exact)"),
    ]

    post_je(qbo, "JE-20260804-CC",   cc_lines,   "CARD batch 2026-08-04 (daily-summary JE; exact tax, no AST)")
    print()
    post_je(qbo, "JE-20260804-CASH", cash_lines, "CASH batch 2026-08-04")

if __name__ == "__main__":
    main()
