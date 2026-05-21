"""Pricing strategy (architektura 5.2).

A ``typing.Protocol`` — structural, no ABC, no DI framework. The default
``FlatRatePricing`` applies a constant per-kWh rate; a future peak/off-peak
tariff is just another class satisfying the same protocol.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol


class PricingStrategy(Protocol):
    """Computes the raw cost for a given energy amount.

    Returns an unrounded ``Decimal`` — rounding policy belongs to ``SessionService``
    so future tariffs do not each re-implement it.
    """

    def cost_for_kwh(self, total_kwh: Decimal) -> Decimal: ...


class FlatRatePricing:
    """Constant rate per kWh (``PRICE_PER_KWH`` from ENV)."""

    def __init__(self, price_per_kwh: Decimal) -> None:
        self._price_per_kwh = price_per_kwh

    def cost_for_kwh(self, total_kwh: Decimal) -> Decimal:
        return total_kwh * self._price_per_kwh
