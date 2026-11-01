"""Pure, validated order budgeting shared by execution and forecasting."""
from dataclasses import dataclass
from datetime import timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN


def amount(value, name, *, positive=False):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or positive and number <= 0:
            raise ValueError
        return number
    except (ValueError, InvalidOperation):
        raise ValueError(f'{name} must be a finite '+('positive' if positive else 'non-negative')+' amount.') from None


def precision(value):
    if isinstance(value, bool) or not str(value).isdigit() or not 0 <= int(value) <= 18:
        raise ValueError('Exchange precision must be an integer from 0 to 18.')
    return int(value)


def ceil_to_places(value, places):
    return value.quantize(Decimal(1).scaleb(-precision(places)), rounding=ROUND_CEILING)


@dataclass(frozen=True)
class OrderPlan:
    quantity: Decimal
    quote: Decimal
    fee: Decimal
    cost: Decimal
    affordable: int
    base_quantity: Decimal
    base_cost: Decimal
    remaining_budget: bool


def plan_order(market, configured, price, fee_rate, budget):
    price = amount(price, 'BTC price', positive=True)
    rate = amount(fee_rate, 'Trading fee')
    if rate > 1: raise ValueError('Trading fee exceeds 100%.')
    budget = amount(budget, 'Available fiat')
    configured = amount(configured, 'Purchase quantity')
    minimum = amount(market['minOrderInBaseAsset'], 'Minimum BTC')
    minimum_quote = amount(market['minOrderInQuoteAsset'], 'Minimum order value')
    if minimum == minimum_quote == configured == 0:
        raise ValueError('Exchange minimum or configured quantity must be positive.')
    places, quote_places = precision(market['quantityDecimals']), precision(market['notionalDecimals'])
    base = ceil_to_places(max(configured, minimum, minimum_quote / price), places)
    def costs(quantity):
        quote = ceil_to_places(quantity * price, quote_places)
        return quote, quote * rate, quote * (1 + rate)
    quote, fee, base_cost = costs(base)
    affordable = int(budget // base_cost)
    quantity = base
    if affordable == 1:
        # Spend the tail within lot/notional precision while reserving the fee.
        quote_cap = (budget / (1 + rate)).quantize(Decimal(1).scaleb(-quote_places), rounding=ROUND_DOWN)
        candidate = (quote_cap / price).quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)
        if candidate > base:
            quantity = candidate
            quote, fee, cost = costs(quantity)
            if cost > budget: raise ValueError('Final order exceeds available funds.')
    quote, fee, cost = costs(quantity)
    return OrderPlan(quantity, quote, fee, cost, affordable, base, base_cost, quantity > base)


def purchase_interval(anchor, deposit, affordable):
    if anchor.tzinfo is None or deposit.tzinfo is None:
        raise ValueError('Purchase planning requires timezone-aware timestamps.')
    if not isinstance(affordable, int) or affordable < 1:
        raise ValueError('Purchase planning requires at least one affordable order.')
    seconds = max(60, (deposit.astimezone(timezone.utc)-anchor.astimezone(timezone.utc)).total_seconds())
    return max(60, int(seconds / (affordable + 1)))
