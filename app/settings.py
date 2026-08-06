"""App/provider settings. In production these are real env vars / secrets; for
local dev we fall back to the sandbox app creds already in engine/.env so the
connect flow can be exercised without extra setup.
"""
from __future__ import annotations
import os, re

def _engine_env(key, default=""):
    try:
        p = os.path.join(os.path.dirname(__file__), "..", "engine", ".env")
        for line in open(p):
            m = re.match(rf"^{key}=(.*)$", line.strip())
            if m:
                return m.group(1)
    except Exception:
        pass
    return default


class QBO:
    ENV = os.environ.get("QBO_APP_ENV", _engine_env("QBO_ENV", "sandbox"))
    CLIENT_ID = os.environ.get("QBO_APP_CLIENT_ID", _engine_env("QBO_CLIENT_ID"))
    CLIENT_SECRET = os.environ.get("QBO_APP_CLIENT_SECRET", _engine_env("QBO_CLIENT_SECRET"))
    REDIRECT_URI = os.environ.get("QBO_APP_REDIRECT_URI", "http://localhost:8000/callback/qbo")
    SCOPE = "com.intuit.quickbooks.accounting"
    AUTHORIZE = "https://appcenter.intuit.com/connect/oauth2"
    TOKEN = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"


class SQUARE:
    ENV = os.environ.get("SQUARE_APP_ENV", "production")
    CLIENT_ID = os.environ.get("SQUARE_APP_CLIENT_ID", "")
    CLIENT_SECRET = os.environ.get("SQUARE_APP_CLIENT_SECRET", "")
    REDIRECT_URI = os.environ.get("SQUARE_APP_REDIRECT_URI", "http://localhost:8000/callback/square")
    SCOPE = "ORDERS_READ PAYMENTS_READ GIFTCARDS_READ MERCHANT_PROFILE_READ SETTLEMENTS_READ"
    AUTHORIZE = ("https://connect.squareup.com/oauth2/authorize" if ENV == "production"
                 else "https://connect.squareupsandbox.com/oauth2/authorize")
