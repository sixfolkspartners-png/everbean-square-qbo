"""
EverBean Coffee Co — Square → QuickBooks daily sales sync
Central configuration: QuickBooks item/account mappings and runtime settings.

All QuickBooks IDs below are the RAW QBO entity IDs (as used by the Intuit REST
API), confirmed live against SixFolks Partners LLC dba EverBean Coffee Co.

Anything marked TODO must be filled in once the QuickBooks tax code and the
Square Fees / Over-and-Short item IDs are looked up (one-time, see docs).
"""
import os

# --- QuickBooks company ---
QBO_REALM_ID = os.environ.get("QBO_REALM_ID", "9130357334018486")
QBO_ENV = os.environ.get("QBO_ENV", "production")  # "production" | "sandbox"
QBO_MINOR_VERSION = "75"

# --- QuickBooks entity references (raw QBO IDs) ---
# All env-overridable so the SAME code runs against sandbox and production
# (defaults are EverBean production ids; sandbox ids come from .env).
QBO_SQUARE_CUSTOMER_ID = os.environ.get("QBO_SQUARE_CUSTOMER_ID", "2")   # "Square customer"

# Item IDs for SalesReceipt line items (item -> account link does the routing)
ITEM_SALES        = os.environ.get("QBO_ITEM_SALES",     "23")   # "Square sales item"    -> Sales of Product Income
ITEM_DISCOUNT     = os.environ.get("QBO_ITEM_DISCOUNT",  "20")   # "Square Discount"      -> Discounts given (contra income)
ITEM_TIPS         = os.environ.get("QBO_ITEM_TIPS",      "10")   # "Tips"                 -> Tips Payable (liability)
ITEM_GIFT_CARD    = os.environ.get("QBO_ITEM_GIFT_CARD",  "7")   # "Gift Card"            -> Gift Card Outstanding (liability)
ITEM_SALES_TAX    = os.environ.get("QBO_ITEM_SALES_TAX",  "")    # "Square Sales Tax"     -> Square Sales Tax Payable (liability)
ITEM_SQUARE_FEES  = os.environ.get("QBO_ITEM_SQUARE_FEES", "")   # "Square Fees"          -> Square Fees (expense)
ITEM_OVER_SHORT   = os.environ.get("QBO_ITEM_OVER_SHORT",  "")   # "Over and Short"       -> Over/Short

# Deposit target for the SalesReceipt (cash sale -> money lands here, no A/R).
QBO_DEPOSIT_ACCOUNT_ID   = os.environ.get("QBO_DEPOSIT_ACCOUNT_ID", "")
QBO_DEPOSIT_ACCOUNT_CC   = os.environ.get("QBO_DEPOSIT_ACCOUNT_CC", "")    # optional: card batch deposit acct
QBO_DEPOSIT_ACCOUNT_CASH = os.environ.get("QBO_DEPOSIT_ACCOUNT_CASH", "")  # optional: cash batch deposit acct

# Sales tax: we do NOT use QuickBooks' tax engine. Validated in sandbox that
# QuickBooks' Automated Sales Tax IGNORES a TxnTaxDetail.TotalTax override and
# recomputes from its own rate. So every line is non-taxable (QBO tax = $0) and
# Square's exact tax rides as its own line to ITEM_SALES_TAX (Square Sales Tax
# Payable liability). The total then ties to the penny regardless of AST.
# (These refs are retained only for the legacy override path; unused now.)
QBO_TAX_CODE_ID = os.environ.get("QBO_TAX_CODE_ID", "")
QBO_TAX_RATE_ID = os.environ.get("QBO_TAX_RATE_ID", "")
QBO_TAX_PERCENT = float(os.environ.get("QBO_TAX_PERCENT", "4.5"))

# --- Square ---
SQUARE_ENV = os.environ.get("SQUARE_ENV", "production")
SQUARE_API_BASE = (
    "https://connect.squareup.com" if SQUARE_ENV == "production"
    else "https://connect.squareupsandbox.com"
)
SQUARE_VERSION = "2025-05-21"  # Square-Version header

# --- Behavior ---
# DocNumber pattern makes each day idempotent: we query before posting.
DOCNUMBER_PREFIX = "SQ-"       # -> SQ-20260727
TIMEZONE = "America/Denver"    # EverBean local reporting timezone
# Tie-out tolerance (dollars) when checking the receipt total against the
# ACTUAL Square payout/deposit. This should be tight.
RECONCILE_TOLERANCE = 0.05
# The daily "Over and Short" residual (Square total_collected vs the sum of its
# components) is normally a few dollars from rounding/refund timing and is
# booked to the Over and Short item. Flag a day for review only if it exceeds
# this — a large residual means something is genuinely off, not just rounding.
OVER_SHORT_LIMIT = 25.00

# Alerting (optional): set a Slack webhook or leave blank to log only.
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
