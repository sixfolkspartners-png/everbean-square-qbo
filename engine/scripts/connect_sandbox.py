"""
Validate the sandbox QBO connection end-to-end and discover entity IDs.
- Refreshes the access token (and writes the rotated refresh token back to .env
  so repeated local runs keep working).
- Queries CompanyInfo to prove auth works.
- Lists Items, Accounts (Bank / Other Current Asset), TaxCodes, TaxRates so we
  can fill config for the two-batch poster.

Run:  cd engine && set -a && source .env && set +a && python -m scripts.connect_sandbox
"""
import os, re, requests
from src.qbo_client import QBOClient, API_BASE
import config

ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")


def _persist_refresh(token: str):
    try:
        with open(ENV_PATH) as f:
            txt = f.read()
        txt = re.sub(r"(?m)^QBO_REFRESH_TOKEN=.*$", f"QBO_REFRESH_TOKEN={token}", txt)
        with open(ENV_PATH, "w") as f:
            f.write(txt)
        print(f"[.env] refresh token rotated and saved ({token[:10]}…)")
    except Exception as e:
        print("[.env] could not persist refresh token:", e)


def q(qbo, query):
    r = requests.get(
        f"{API_BASE}/v3/company/{config.QBO_REALM_ID}/query"
        f"?query={requests.utils.quote(query)}&minorversion={config.QBO_MINOR_VERSION}",
        headers=qbo._headers(), timeout=60)
    r.raise_for_status()
    return r.json().get("QueryResponse", {})


def main():
    print(f"env={config.QBO_ENV}  api={API_BASE}  realm={config.QBO_REALM_ID}")
    qbo = QBOClient(os.environ["QBO_CLIENT_ID"], os.environ["QBO_CLIENT_SECRET"],
                    os.environ["QBO_REFRESH_TOKEN"])
    tok = qbo.refresh()
    print("token refresh OK; access token len", len(qbo.access_token))
    _persist_refresh(qbo.refresh_token)

    ci = q(qbo, "select * from CompanyInfo").get("CompanyInfo", [{}])[0]
    print("\n== Connected company ==")
    print("  ", ci.get("CompanyName"), "| country", ci.get("Country"),
          "| realm", config.QBO_REALM_ID)

    print("\n== Items ==")
    for it in q(qbo, "select Id, Name, Type from Item").get("Item", []):
        print(f"   id={it['Id']:<4} {it.get('Type',''):<14} {it['Name']}")

    print("\n== Accounts (Bank / Other Current Asset) ==")
    for a in q(qbo, "select Id, Name, AccountType from Account "
                    "where AccountType in ('Bank','Other Current Asset')").get("Account", []):
        print(f"   id={a['Id']:<4} {a['AccountType']:<20} {a['Name']}")

    print("\n== Tax codes ==")
    for t in q(qbo, "select Id, Name from TaxCode").get("TaxCode", []):
        print(f"   id={t['Id']:<4} {t.get('Name')}")

    print("\n== Tax rates ==")
    for t in q(qbo, "select Id, Name, RateValue from TaxRate").get("TaxRate", []):
        print(f"   id={t['Id']:<4} rate={t.get('RateValue')}  {t.get('Name')}")


if __name__ == "__main__":
    main()
