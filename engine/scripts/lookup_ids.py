"""
One-time helper: once QuickBooks OAuth works, this prints the entity IDs you
need to finish config (Square Fees item, Over and Short item, deposit account,
tax code + rate). Paste the results into your GitHub secrets / .env.

Run:  python -m scripts.lookup_ids
"""
import os
from src.qbo_client import QBOClient, API_BASE
import config, requests


def q(qbo, query):
    r = requests.get(
        f"{API_BASE}/v3/company/{config.QBO_REALM_ID}/query"
        f"?query={requests.utils.quote(query)}&minorversion={config.QBO_MINOR_VERSION}",
        headers=qbo._headers(), timeout=60)
    r.raise_for_status()
    return r.json().get("QueryResponse", {})


def main():
    qbo = QBOClient(os.environ["QBO_CLIENT_ID"], os.environ["QBO_CLIENT_SECRET"],
                    os.environ["QBO_REFRESH_TOKEN"])
    qbo.refresh()

    print("== Items ==")
    for it in q(qbo, "select Id, Name from Item").get("Item", []):
        if it["Name"] in ("Square Fees", "Over and Short", "Square sales item",
                            "Square discount item", "Tips", "Gift Card"):
            print(f"  {it['Name']:<22} id={it['Id']}")

    print("\n== Bank / Other Current Asset accounts (deposit target) ==")
    for a in q(qbo, "select Id, Name, AccountType from Account "
                    "where AccountType in ('Bank','Other Current Asset')").get("Account", []):
        print(f"  {a['Name']:<32} id={a['Id']}  ({a['AccountType']})")

    print("\n== Tax codes ==")
    for t in q(qbo, "select Id, Name from TaxCode").get("TaxCode", []):
        print(f"  {t['Name']:<28} id={t['Id']}")

    print("\n== Tax rates ==")
    for t in q(qbo, "select Id, Name, RateValue from TaxRate").get("TaxRate", []):
        print(f"  {t.get('Name','?'):<28} id={t['Id']}  rate={t.get('RateValue')}")


if __name__ == "__main__":
    main()
