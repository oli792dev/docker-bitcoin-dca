"""Independent public display quotes and saved account price reads."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from threading import Event

import requests

from app.core.logging_utils import clear_transition, log_transition
from app.exchanges.kraken import BASE_URL

LOG = logging.getLogger("bitcoin-dca.prices")


class DisplayPrices:
    """Retain the last good public Kraken quote for each supported currency."""

    def __init__(self) -> None:
        self._quotes: dict[str, tuple[Decimal, float]] = {}

    def latest(self, quote: str) -> tuple[Decimal, float] | None:
        return self._quotes.get(quote)

    def refresh(self, quote: str, display_currency: str = "") -> None:
        other = "USD" if quote == "EUR" else "EUR"
        try:
            response = requests.get(f"{BASE_URL}/public/Ticker", params={"pair": "XBT" + other}, timeout=15)
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise ValueError("Kraken conversion ticker unavailable")
            price = Decimal(str(next(iter(payload["result"].values()))["c"][0]))
            if not price.is_finite() or price <= 0:
                raise ValueError("Invalid conversion price")
            self._quotes[quote] = (price, datetime.now(UTC).timestamp())
            clear_transition(self, "display-price")
        except (
            requests.RequestException,
            ValueError,
            ArithmeticError,
            LookupError,
            StopIteration,
            TypeError,
            AttributeError,
        ):
            needed = display_currency == other
            log_transition(
                LOG,
                self,
                "display-price",
                (other, needed),
                logging.WARNING if needed else logging.DEBUG,
                "BTC/%s display conversion refresh failed.",
                other,
            )
            LOG.debug("Display conversion refresh failed", exc_info=True)

    def run(self, current_currencies: Callable[[], tuple[str, str] | None], stop: Event) -> None:
        while not stop.is_set():
            currencies = current_currencies()
            if currencies is not None:
                self.refresh(*currencies)
            stop.wait(60)


def snapshot_market_price(snapshot, exchange, display_currency, quote_currency, currencies=(), *, alternate=None):
    needed = {display_currency, quote_currency, *currencies}
    if not needed <= {"EUR", "USD"}:
        raise ValueError("Display and historical fiat currencies must be EUR or USD")
    if snapshot.get("exchange") != exchange or snapshot.get("quote") != quote_currency:
        raise RuntimeError("Waiting for account check")
    prices = {c: Decimal(str(v)) for c, v in snapshot.get("marketPrices", {}).items()}
    if quote_currency not in prices:
        raise RuntimeError("Waiting for account price check")
    account_updated = datetime.fromisoformat(snapshot["updatedAt"].replace("Z", "+00:00")).timestamp()
    timestamps = dict.fromkeys(prices, account_updated)
    other = "USD" if quote_currency == "EUR" else "EUR"
    if alternate is not None and alternate[1] >= timestamps.get(other, 0):
        prices[other], timestamps[other] = alternate
    if not needed <= prices.keys():
        raise RuntimeError("Waiting for account price check")
    if any(not prices[c].is_finite() or prices[c] <= 0 for c in needed):
        raise RuntimeError("Account price unavailable")
    updated = min(timestamps[c] for c in needed)
    target = prices[display_currency]
    return {
        "currency": display_currency,
        "quoteCurrency": quote_currency,
        "price": str(target),
        "conversionRate": str(target / prices[quote_currency]),
        "conversionRates": {c: str(target / v) for c, v in prices.items()},
        "conversionRatesUpdatedAt": {
            c: min(timestamps[display_currency], updated_at) for c, updated_at in timestamps.items()
        },
        "source": "Last account check",
        "updatedAt": updated,
        "stale": datetime.now(UTC).timestamp() - updated > 600,
    }
