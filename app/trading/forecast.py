"""Pure monthly withdrawal projection, independent of an executable buy schedule."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal, DecimalException
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.contracts import ForecastPlan
from app.core.deposit_calendar import deposit_at
from app.core.planning import plan_order

LOG = logging.getLogger("bitcoin-dca")
_LAST_INVALID = None


def _invalid_input(exc: Exception) -> None:
    global _LAST_INVALID
    signature = (type(exc).__name__, str(exc))
    if signature != _LAST_INVALID:
        LOG.warning("Withdrawal forecast unavailable: invalid account or order data (%s).", type(exc).__name__)
        _LAST_INVALID = signature


DESCRIPTION = "Estimate at the current BTC price, deposit and purchase interval"


class MissingForecastData(Exception):
    """The account snapshot does not yet contain a forecast reference."""


def _snapshot_field(snapshot: Mapping[str, Any], key: str) -> Any:
    """Only absent snapshot fields represent an account refresh still in progress."""
    try:
        return snapshot[key]
    except KeyError as exc:
        raise MissingForecastData from exc


def _account_inputs(
    settings: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    monthly_deposit: str | Decimal,
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Validate the current balance independently of any future order reference."""
    if not isinstance(snapshot, Mapping):
        raise ValueError("Invalid snapshot")
    monthly = Decimal(str(monthly_deposit))
    balance, price = (
        Decimal(str(_snapshot_field(snapshot, "btcBalance"))),
        Decimal(str(_snapshot_field(snapshot, "price"))),
    )
    threshold = Decimal(str(settings["withdraw_threshold"]))
    if any(not v.is_finite() or v < 0 for v in (monthly, balance, price, threshold)) or price <= 0 or threshold <= 0:
        raise ValueError("Invalid forecast input")
    return monthly, balance, price, threshold


@dataclass(frozen=True)
class ForecastInputs:
    """Validated reference values and initial state for the monthly projection."""

    monthly_deposit: Decimal
    remaining_btc: Decimal
    price: Decimal
    plan: ForecastPlan
    quantity: Decimal
    cost: Decimal
    base_quantity: Decimal
    base_cost: Decimal
    budget: Decimal
    zone: ZoneInfo
    overdue: bool
    funding: datetime
    due: datetime
    interval: int


def _forecast_inputs(
    settings: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    monthly_deposit: str | Decimal,
    now: datetime,
) -> ForecastInputs:
    """Parse external values before running projection arithmetic."""
    monthly, balance, price, threshold = _account_inputs(settings, snapshot, monthly_deposit)
    plan: ForecastPlan = _snapshot_field(snapshot, "withdrawalForecastPlan")
    if plan is None:
        raise MissingForecastData
    if not isinstance(plan, Mapping):
        raise ValueError("Invalid forecast reference")
    quantity, cost = (
        Decimal(str(_snapshot_field(plan, "orderAmount"))),
        Decimal(str(_snapshot_field(plan, "plannedCost"))),
    )
    base_quantity = Decimal(str(plan.get("baseOrderAmount", _snapshot_field(plan, "orderAmount"))))
    base_cost = Decimal(str(plan.get("basePlannedCost", _snapshot_field(plan, "plannedCost"))))
    budget = Decimal(str(_snapshot_field(plan, "budget")))
    if (
        any(not v.is_finite() or v <= 0 for v in (quantity, cost, base_quantity, base_cost))
        or not budget.is_finite()
        or budget < 0
    ):
        raise ValueError("Invalid forecast reference")
    zone_name = settings.get("timezone", "UTC")
    if not isinstance(zone_name, str):
        raise ValueError("Invalid forecast timezone")
    zone = ZoneInfo(zone_name)
    now = now.astimezone(UTC)
    if not isinstance(_snapshot_field(plan, "nextDepositAt"), str):
        raise ValueError("Invalid next deposit time")
    expected = datetime.fromisoformat(_snapshot_field(plan, "nextDepositAt")).astimezone(zone)
    overdue = expected.astimezone(UTC) < now
    funding = max(expected.astimezone(UTC), now)
    raw_due = snapshot.get("nextPurchaseAt")
    if raw_due is not None and not isinstance(raw_due, str):
        raise ValueError("Invalid purchase time")
    parsed_due = datetime.fromisoformat(raw_due.replace("Z", "+00:00")) if raw_due else now
    if parsed_due.tzinfo is None:
        raise ValueError("Purchase time must include its timezone")
    due = max(now, parsed_due)
    if not isinstance(plan.get("intervalSeconds", 300), (str, int, float, Decimal)):
        raise ValueError("Invalid purchase interval")
    interval = max(60, int(plan.get("intervalSeconds", 300)))
    if plan.get("marketRules"):
        if not isinstance(plan["marketRules"], Mapping):
            raise ValueError("Invalid market rules")
        for key in ("minOrderInBaseAsset", "minOrderInQuoteAsset", "quantityDecimals", "notionalDecimals"):
            _snapshot_field(plan["marketRules"], key)
        _snapshot_field(plan, "feeRate")
        plan_order(plan["marketRules"], base_quantity, price, plan["feeRate"], budget)
    # Validate calendar inputs here; projection errors must remain visible.
    deposit_at(now.year, now.month, settings["deposit_day"], settings.get("deposit_time", "00:00"), zone)
    return ForecastInputs(
        monthly_deposit=monthly,
        remaining_btc=threshold / price - balance,
        price=price,
        plan=plan,
        quantity=quantity,
        cost=cost,
        base_quantity=base_quantity,
        base_cost=base_cost,
        budget=budget,
        zone=zone,
        overdue=overdue,
        funding=funding,
        due=due,
        interval=interval,
    )


def withdrawal_forecast(
    settings: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    monthly_deposit: str | Decimal,
    now: datetime,
) -> tuple[str | None, str]:
    """Estimate threshold arrival using validated account and order inputs."""
    global _LAST_INVALID
    if not settings.get("withdrawals_enabled"):
        return None, "Automatic withdrawals disabled"
    if not settings.get("live"):
        return None, "Unavailable in simulation mode"
    try:
        _, balance, price, threshold = _account_inputs(settings, snapshot, monthly_deposit)
        if balance * price >= threshold:
            _LAST_INVALID = None
            return now.isoformat(), "Threshold reached; awaiting automatic withdrawal check"
        inputs = _forecast_inputs(settings, snapshot, monthly_deposit, now)
    except MissingForecastData:
        return None, "Waiting for account price and order minimums"
    except (ValueError, DecimalException, OverflowError, ZoneInfoNotFoundError) as exc:
        _invalid_input(exc)
        return None, "Forecast unavailable: invalid account or order data"
    _LAST_INVALID = None
    target, description, _ = _project_forecast(settings, inputs)
    return target, description


def _project_forecast(settings: Mapping[str, Any], inputs: ForecastInputs) -> tuple[str | None, str, int | None]:
    """Advance monthly funding and purchases without catching programming failures."""
    quantity, cost, budget = inputs.quantity, inputs.cost, inputs.budget
    funding, due, interval = inputs.funding, inputs.due, inputs.interval
    remaining = inputs.remaining_btc
    purchases = 0
    description = DESCRIPTION + (" · assumes overdue deposit arrives now" if inputs.overdue else "")
    for _ in range(1200):
        slots = max(0, int((funding - due).total_seconds() // interval) + 1)
        count = min(int(budget // cost), slots)
        if count:
            tail_quantity, tail_cost = quantity, cost
            if count == int(budget // cost) and inputs.plan.get("marketRules"):
                tail = plan_order(
                    inputs.plan["marketRules"],
                    inputs.base_quantity,
                    inputs.price,
                    inputs.plan["feeRate"],
                    budget - cost * (count - 1),
                )
                tail_quantity, tail_cost = tail.quantity, tail.cost
            regular = min(count - 1, int((remaining / quantity).to_integral_value(rounding=ROUND_CEILING)))
            if remaining <= quantity * regular:
                return (due + timedelta(seconds=(regular - 1) * interval)).isoformat(), description, purchases + regular
            if remaining <= quantity * (count - 1) + tail_quantity:
                return (due + timedelta(seconds=(count - 1) * interval)).isoformat(), description, purchases + count
            purchases += count
            remaining -= quantity * (count - 1) + tail_quantity
            budget -= cost * (count - 1) + tail_cost
        if inputs.monthly_deposit == 0:
            return None, "Enter an expected monthly deposit to project further purchases", None
        budget += inputs.monthly_deposit
        start = funding.astimezone(inputs.zone)
        year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
        funding = deposit_at(
            year, month, settings["deposit_day"], settings.get("deposit_time", "00:00"), inputs.zone
        ).astimezone(UTC)
        quantity, cost = inputs.base_quantity, inputs.base_cost
        count = int(budget // cost)
        # A deposit releases the first purchase immediately; remaining buys
        # share the rest of the calendar period and finish before its boundary.
        due = start.astimezone(UTC)
        interval = max(60, int((funding - due).total_seconds() / max(1, count)))
    return None, "Estimate exceeds the 100-year forecast horizon", None


def forecast_details(
    settings: Mapping[str, Any], snapshot: Mapping[str, Any], now: datetime | None = None
) -> dict[str, Any] | None:
    """Reporting-only explanation; never creates or advances a purchase schedule."""
    try:
        price = Decimal(str(snapshot["price"]))
        balance = Decimal(str(snapshot["btcBalance"]))
        threshold = Decimal(str(settings["withdraw_threshold"]))
        plan = snapshot["withdrawalForecastPlan"]
        if plan is None:
            return None
        if not isinstance(plan, Mapping):
            raise ValueError("Invalid forecast reference")
        quantity = Decimal(str(plan.get("baseOrderAmount", plan["orderAmount"])))
        if not all(x.is_finite() for x in (price, balance, threshold, quantity)) or price <= 0 or quantity <= 0:
            return None
        remaining = max(Decimal(0), threshold / price - balance)
        purchases = 0
        if remaining:
            inputs = _forecast_inputs(
                settings, snapshot, settings.get("expected_monthly_deposit") or "0", now or datetime.now(UTC)
            )
            _, _, projected_purchases = _project_forecast(settings, inputs)
            if projected_purchases is None:
                return None
            purchases = projected_purchases
        return {
            "remainingBtc": str(remaining),
            "remainingPurchases": purchases,
            "price": str(price),
            "threshold": str(threshold),
            "quote": settings["quote"],
            "monthlyDeposit": settings.get("expected_monthly_deposit", ""),
            "depositDay": settings["deposit_day"],
            "depositTime": settings.get("deposit_time", "00:00"),
            "timezone": settings["timezone"],
            "quantity": str(quantity),
        }
    except (KeyError, MissingForecastData):
        return None
    except (ValueError, DecimalException) as exc:
        _invalid_input(exc)
        return None
