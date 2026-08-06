"""
Transform one day's Square figures into a QuickBooks SalesReceipt payload.

TAX HANDLING (validated against live QuickBooks sandbox, Aug 2026):
QuickBooks' Automated Sales Tax IGNORES a `TxnTaxDetail.TotalTax` override and
recomputes tax from its own rate. So we do NOT use QBO's tax engine at all —
every line is NON-taxable (QBO computes $0 tax) and Square's EXACT collected tax
rides as its own line item to "Square Sales Tax Payable" (a liability). The
receipt total then equals Square's money-to-deposit to the penny, immune to AST.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
import config


def _cents(x: Decimal) -> float:
    return float(Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _line(item_id: str, desc: str, amount: Decimal) -> dict:
    """A SalesReceipt line. ALWAYS non-taxable — QBO's tax engine is bypassed
    (see module docstring); tax is carried as its own ITEM_SALES_TAX line."""
    return {
        "DetailType": "SalesItemLineDetail",
        "Amount": _cents(amount),
        "Description": desc,
        "SalesItemLineDetail": {
            "ItemRef": {"value": item_id},
            "TaxCodeRef": {"value": "NON"},
            "Qty": 1,
        },
    }


def build_sales_receipt(day: str, s: dict, redemptions: Decimal,
                        fees: Decimal = Decimal("0")) -> dict:
    """
    s: dict from SquareClient.daily_sales()
    redemptions: Decimal from SquareClient.gift_card_redemptions()
    fees: Decimal processing fees (optional; include to tie out to deposit)

    Returns a SalesReceipt JSON body for POST /v3/company/{realm}/salesreceipt.
    No TxnTaxDetail — all lines non-taxable so QBO computes $0; the exact tax is a line.
    """
    gross      = s["gross"]
    discounts  = s["discounts"]        # negative already
    tax        = s["tax"]              # Square's EXACT collected tax (booked as a line)
    tips       = s["tips"]
    gc_sales   = s["gc_sales"]

    lines = [
        _line(config.ITEM_SALES,     f"Gross product sales — Square {day}", gross),
        _line(config.ITEM_DISCOUNT,  "Discounts",                           discounts),
    ]
    if config.ITEM_SALES_TAX:
        lines.append(_line(config.ITEM_SALES_TAX, "Sales tax (Square exact)", tax))
    lines += [
        _line(config.ITEM_TIPS,      "Tips collected",                      tips),
        _line(config.ITEM_GIFT_CARD, "Gift card purchases (sold)",          gc_sales),
        _line(config.ITEM_GIFT_CARD, "Gift card redemptions (spent)",       -redemptions),
    ]
    if fees and config.ITEM_SQUARE_FEES:
        lines.append(_line(config.ITEM_SQUARE_FEES, "Square processing fees", -fees))

    # Over/Short residual: makes the receipt's pre-redemption subtotal equal
    # Square's own total_collected, absorbing rounding/refund-timing pennies.
    #   over_short = total_collected - (gross + discounts + tax + tips + gc_sales)
    over_short = (s["total_collected"]
                  - (gross + discounts + tax + tips + gc_sales))
    if config.ITEM_OVER_SHORT and over_short != 0:
        lines.append(_line(config.ITEM_OVER_SHORT, "Over and short (rounding)", over_short))

    receipt = {
        "CustomerRef": {"value": config.QBO_SQUARE_CUSTOMER_ID},
        "TxnDate": day,
        "DocNumber": f"{config.DOCNUMBER_PREFIX}{day.replace('-', '')}",
        "Line": lines,
        "PrivateNote": f"Auto-posted from Square daily sales for {day}.",
    }
    if config.QBO_DEPOSIT_ACCOUNT_ID:
        receipt["DepositToAccountRef"] = {"value": config.QBO_DEPOSIT_ACCOUNT_ID}

    return receipt


def expected_receipt_total(s: dict, redemptions: Decimal, fees: Decimal = Decimal("0")) -> Decimal:
    """
    What the SalesReceipt TotalAmt should be = the actual money to deposit.
    With the Over/Short line, the pre-redemption subtotal equals Square's
    total_collected, so:  total_collected - redemptions - fees.
    """
    return s["total_collected"] - redemptions - fees
