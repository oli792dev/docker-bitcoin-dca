"""Pending order reconciliation; never submits a replacement order."""

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from app.core.logging_utils import log_transition
from app.core.purchase_status import PurchaseStatus

LOG = logging.getLogger("bitcoin-dca")


class OrderReader(Protocol):
    def get_order(self, symbol: str, client_order_id: str, exchange_order_id: str | None = None) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ReconciliationIO:
    """Explicit effects keep recovery independently testable without importing the engine."""

    save: Callable[[Path, dict[str, Any]], None]
    update_schedule: Callable[[None, PurchaseStatus], None]
    persist_buy: Callable[[OrderReader, dict[str, Any], Mapping[str, Any], str, int], tuple[list[dict[str, Any]], int]]
    transport_error: type[Exception]


def defer_order_check(state: dict[str, Any], state_path: Path, settings: dict[str, Any], io: ReconciliationIO) -> int:
    delay = int(settings["order_status_check_seconds"])
    state["pending_order"]["nextStatusCheckAt"] = int(time.time() * 1000) + delay * 1000
    io.save(state_path, state)
    return delay


def reconcile_pending_order(
    api: OrderReader,
    state: dict[str, Any],
    state_path: Path,
    settings: dict[str, Any],
    check_interval: int,
    io: ReconciliationIO,
) -> int | None:
    pending = state["pending_order"]
    symbol = f"BTC-{settings['quote']}"
    delay = int(settings["order_status_check_seconds"])
    io.update_schedule(None, PurchaseStatus.VERIFYING_ORDER)
    if pending.get("exchange", settings["exchange"]) != settings["exchange"] or pending.get("symbol") != symbol:
        LOG.error("Pending order belongs to a different exchange or market; refusing another purchase.")
        return delay
    due_ms = int(pending.get("nextStatusCheckAt", int(pending.get("submittedAt", 0)) + delay * 1000))
    remaining_ms = due_ms - int(time.time() * 1000)
    if remaining_ms > 0:
        return max(1, (remaining_ms + 999) // 1000)

    try:
        order = api.get_order(symbol, pending["clientOrderId"], pending.get("exchangeOrderId"))
    except io.transport_error as exc:
        LOG.warning(
            "%s order %s could not be confirmed: %s. No new order will be sent; checking again in %ss.",
            settings["exchange"],
            pending.get("exchangeOrderId") or pending["clientOrderId"],
            exc,
            delay,
        )
        return defer_order_check(state, state_path, settings, io)

    status = str(order.get("status", "")).lower()
    if status not in ("closed", "filled", "canceled", "cancelled", "expired", "rejected"):
        log_transition(
            LOG,
            api,
            "order-wait",
            (pending["clientOrderId"], status),
            logging.INFO,
            "%s order %s exists but has not ended (status=%s); no new purchase; checking again in %ss.",
            settings["exchange"],
            pending.get("exchangeOrderId") or pending["clientOrderId"],
            status or "unknown",
            delay,
        )
        return defer_order_check(state, state_path, settings, io)

    records, added = io.persist_buy(api, order, settings, pending["clientOrderId"], int(pending.get("submittedAt", 0)))
    if not records:
        filled_raw = order.get("vol_exec", order.get("filledAmount"))
        filled = Decimal(str(filled_raw)) if filled_raw is not None else None
        if filled is None or filled > 0 or status == "filled":
            LOG.warning(
                "Order %s ended but its fill details are incomplete; keeping it pending.", pending["clientOrderId"]
            )
            return defer_order_check(state, state_path, settings, io)
        state.pop("pending_order", None)
        io.save(state_path, state)
        LOG.warning(
            "Order %s ended without a fill (status=%s); no purchase recorded.", pending["clientOrderId"], status
        )
        return check_interval

    order_cost = sum(
        (Decimal(record["row"]["amount"]) + Decimal(record["row"].get("fee", "0")) for record in records),
        Decimal(0),
    )
    state["spent"] = str(Decimal(state.get("spent", "0")) + order_cost)
    state["last_order_at"] = max(
        datetime.fromisoformat(record["row"]["datetime"].replace("Z", "+00:00")) for record in records
    ).isoformat()
    state["last_order_quote"] = str(order_cost)
    state.pop("pending_order", None)
    io.save(state_path, state)
    settings["startup_last_buy_at"] = None
    LOG.info(
        "Confirmed %s order %s ended (status=%s); saved %s activity record(s). Recalculating the purchase schedule.",
        settings["exchange"],
        pending.get("exchangeOrderId") or pending["clientOrderId"],
        status,
        added,
    )
    return None
