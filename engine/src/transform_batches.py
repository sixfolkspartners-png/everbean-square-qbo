"""
Two-batch SalesReceipt builder (docs/11-two-batch-tender-split-spec.md).

A day posts TWO SalesReceipts — a Credit-card batch and a Cash batch — each with
the same line breakdown, split by the actual tender. Card + gift-card orders go
in the CC receipt (gift-card redemptions come off as a reduction line); cash
orders go in the Cash receipt (no tips, no fees).

TAX (validated live in the QBO sandbox, Aug 2026): QuickBooks' Automated Sales
Tax IGNORES a TxnTaxDetail.TotalTax override and recomputes from its own rate.
So we bypass QBO's tax engine entirely — every line is non-taxable (QBO tax = $0)
and Square's exact tax is its own line to ITEM_SALES_TAX (Square Sales Tax
Payable, a liability). Each batch total then ties to the payout / cash deposit
to the penny, immune to AST.
"""
from __future__ import annotations
from decimal import Decimal
import config
from src.transform import _line, _cents


def _receipt(day: str, suffix: str, lines: list, deposit_account: str, note: str) -> dict:
    r = {
        "CustomerRef": {"value": config.QBO_SQUARE_CUSTOMER_ID},
        "TxnDate": day,
        "DocNumber": f"{config.DOCNUMBER_PREFIX}{day.replace('-', '')}-{suffix}",
        "Line": lines,               # no TxnTaxDetail: all lines NON -> QBO tax $0
        "PrivateNote": note,
    }
    acct = deposit_account or config.QBO_DEPOSIT_ACCOUNT_ID
    if acct:
        r["DepositToAccountRef"] = {"value": acct}
    return r


def build_cc_receipt(day: str, cc: dict) -> dict:
    """cc keys (Decimals): gross, discounts(neg), tax, tips, gc_sold,
    gc_redemptions(pos), fees(pos), over_short(signed, optional)."""
    D = lambda k: Decimal(str(cc.get(k, 0)))
    gross, disc, tax = D("gross"), D("discounts"), D("tax")
    tips, gc_sold, gc_red, fees = D("tips"), D("gc_sold"), D("gc_redemptions"), D("fees")
    over_short = D("over_short")

    lines = [
        _line(config.ITEM_SALES,     f"Gross product sales — Square {day} (card)", gross),
        _line(config.ITEM_DISCOUNT,  "Discounts",                    disc),
    ]
    if config.ITEM_SALES_TAX:
        lines.append(_line(config.ITEM_SALES_TAX, "Sales tax (Square exact)", tax))
    lines += [
        _line(config.ITEM_TIPS,      "Tips collected",               tips),
        _line(config.ITEM_GIFT_CARD, "Gift cards sold",              gc_sold),
        _line(config.ITEM_GIFT_CARD, "Gift card redemptions",        -gc_red),
    ]
    if config.ITEM_SQUARE_FEES:
        lines.append(_line(config.ITEM_SQUARE_FEES, "Square fees (processing + gift-card load)", -fees))
    if config.ITEM_OVER_SHORT and over_short != 0:
        lines.append(_line(config.ITEM_OVER_SHORT, "Over and short", over_short))

    return _receipt(day, "CC", lines,
                    config.QBO_DEPOSIT_ACCOUNT_CC or config.QBO_DEPOSIT_ACCOUNT_ID,
                    f"Auto-posted from Square daily sales (CARD batch) for {day}.")


def build_cash_receipt(day: str, cash: dict) -> dict:
    """cash keys (Decimals): gross, discounts(neg), tax, over_short(optional). No tips/fees."""
    D = lambda k: Decimal(str(cash.get(k, 0)))
    gross, disc, tax, over_short = D("gross"), D("discounts"), D("tax"), D("over_short")

    lines = [_line(config.ITEM_SALES, f"Gross product sales — Square {day} (cash)", gross)]
    if disc != 0:
        lines.append(_line(config.ITEM_DISCOUNT, "Discounts", disc))
    if config.ITEM_SALES_TAX:
        lines.append(_line(config.ITEM_SALES_TAX, "Sales tax (Square exact)", tax))
    if config.ITEM_OVER_SHORT and over_short != 0:
        lines.append(_line(config.ITEM_OVER_SHORT, "Over and short", over_short))

    return _receipt(day, "CASH", lines,
                    config.QBO_DEPOSIT_ACCOUNT_CASH or config.QBO_DEPOSIT_ACCOUNT_ID,
                    f"Auto-posted from Square daily sales (CASH batch) for {day}.")


def build_batch_receipts(day: str, db: dict) -> dict:
    """db = {"cc": {...}, "cash": {...}}. Returns both bodies + the expected
    totals to tie out against the actual Square payout / cash deposit."""
    cc_body = build_cc_receipt(day, db["cc"])
    cash_body = build_cash_receipt(day, db["cash"])
    return {
        "cc": cc_body,
        "cash": cash_body,
        "expected_cc_total": _cents(Decimal(str(db["cc"].get("deposit", 0)))),
        "expected_cash_total": _cents(Decimal(str(db["cash"].get("deposit", 0)))),
    }
