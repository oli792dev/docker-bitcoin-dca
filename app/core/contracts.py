"""Shared payload contracts for account reads and withdrawal projections."""

from decimal import Decimal
from typing import Any, NotRequired, TypedDict


class ForecastPlan(TypedDict):
    """Serializable reference order used by reporting, never an execution instruction."""

    orderAmount: str
    plannedCost: str
    budget: str
    nextDepositAt: str
    baseOrderAmount: NotRequired[str]
    basePlannedCost: NotRequired[str]
    useRemainingBudget: NotRequired[bool]
    intervalSeconds: NotRequired[int]
    marketRules: NotRequired[dict[str, Any]]
    feeRate: NotRequired[str]


class AccountCycleData(TypedDict):
    """Exchange values reused only within one serialized account cycle."""

    market_prices: dict[str, str]
    balance: Decimal
    price: Decimal
    market: dict[str, Any]
    fee_rate: Decimal
    btc_balance: Decimal | None
