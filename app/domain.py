"""Canonical, source-agnostic domain model for a day's sales.

A day is TWO batches (card + cash), each with the same breakdown, split by the
actual tender (docs/11-two-batch-tender-split-spec.md). The destination adapter
turns this into whatever the accounting system needs (QBO Journal Entries).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from decimal import Decimal

D = lambda x: Decimal(str(x))


@dataclass
class Batch:
    gross: Decimal = Decimal("0")          # gross product sales (income)
    discounts: Decimal = Decimal("0")      # negative (contra-income)
    tax: Decimal = Decimal("0")            # Square's EXACT collected tax (liability)
    tips: Decimal = Decimal("0")           # liability (card only; cash tips excluded)
    gift_cards_sold: Decimal = Decimal("0")        # liability +
    gift_card_redemptions: Decimal = Decimal("0")  # liability - (positive number)
    fees: Decimal = Decimal("0")           # Square fees (expense), positive number
    over_short: Decimal = Decimal("0")     # plug
    deposit: Decimal = Decimal("0")        # what hits the bank (payout / cash deposit)

    def collected(self) -> Decimal:
        # discounts are stored NEGATIVE (codebase convention), so add them
        return self.gross + self.discounts + self.tax + self.tips + self.gift_cards_sold

    def net_after_redemptions(self) -> Decimal:
        return self.collected() - self.gift_card_redemptions

    def implied_deposit(self) -> Decimal:
        return self.net_after_redemptions() - self.fees + self.over_short


@dataclass
class DailyBatches:
    business_date: str          # "YYYY-MM-DD"
    cc: Batch = field(default_factory=Batch)
    cash: Batch = field(default_factory=Batch)

    @classmethod
    def from_dict(cls, business_date: str, d: dict) -> "DailyBatches":
        def mk(x): return Batch(**{k: D(v) for k, v in x.items()})
        return cls(business_date, mk(d.get("cc", {})), mk(d.get("cash", {})))
