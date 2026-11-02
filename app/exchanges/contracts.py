"""Structural read-only adapter contracts shared by account planning."""

from decimal import Decimal
from typing import Any, Protocol


class AccountReadExchange(Protocol):
    """An adapter's account reads; no order or withdrawal submission is exposed."""

    def balance(self, currency: str) -> Decimal:
        """Return currently available funds for the requested currency."""
        ...

    def price(self, symbol: str) -> Decimal:
        """Return the exchange's BTC price in the pair's quote currency."""
        ...

    def market(self, symbol: str, refresh: bool = False) -> dict[str, Any]:
        """Return validated lot/notional rules and exchange market state."""
        ...

    def estimate_taker_fee(self, symbol: str, quote_amount: Decimal) -> Decimal:
        """Return a fractional trading fee, such as Decimal('0.004')."""
        ...

    def fiat_deposits(self, currency: str, start_ms: int = 0, end_ms: int | None = None) -> list[dict[str, Any]]:
        """Read deposit history within the inclusive millisecond window."""
        ...
