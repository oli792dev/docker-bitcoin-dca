"""Keep an unfunded monthly boundary open until usable fiat arrives."""

from datetime import UTC, datetime
from decimal import Decimal

from app.core.deposit_calendar import deposit_at


def observe_deposit(state, settings, now, cycle_start, next_deposit, balance, deposits=()):
    if not settings["live"]:
        return next_deposit, False, False
    identity = [
        settings.get("exchange"),
        settings["quote"],
        settings["deposit_day"],
        settings.get("deposit_time", "00:00"),
        settings["timezone"],
    ]
    previous = state.get("deposit_tracking", {})
    last_at = state.get("last_order_at")
    history = settings.get("startup_last_buy_at")
    last = datetime.fromisoformat(last_at) if last_at else history
    if last is not None:
        last = last.replace(tzinfo=last.tzinfo or UTC).astimezone(UTC)
    if previous.get("identity") == identity:
        due = datetime.fromisoformat(previous["dueAt"])
        waiting = bool(previous.get("waiting"))
        unverified = bool(previous.get("unverifiedBoundary"))
        first_due = bool(previous.get("firstPurchaseDue")) and last_at == previous.get("lastOrderAt")
    else:
        due = cycle_start if last is not None and last < cycle_start.astimezone(UTC) else next_deposit
        waiting = first_due = False
        unverified = now.astimezone(UTC) >= due.astimezone(UTC)
    expired = now.astimezone(UTC) >= due.astimezone(UTC)
    # A booked deposit from this local due date or later funds this cycle, even
    # when it arrived before the configured clock or while the bot was offline.
    received = any(
        Decimal(record["row"]["amount"]) > Decimal(record["row"].get("fee", "0"))
        and due.date() <= datetime.fromisoformat(record["row"]["datetime"]).astimezone(now.tzinfo).date() <= now.date()
        for record in deposits
    )
    if received:
        if next_deposit.date() <= now.date():
            year, month = (
                (next_deposit.year + 1, 1) if next_deposit.month == 12 else (next_deposit.year, next_deposit.month + 1)
            )
            due = deposit_at(year, month, settings["deposit_day"], settings.get("deposit_time", "00:00"), now.tzinfo)
        else:
            due = next_deposit
        expired = False
        first_due = True
        unverified = False
    state["deposit_tracking"] = {
        "identity": identity,
        "dueAt": due.isoformat(),
        "balance": str(balance),
        "lastOrderAt": last_at,
        "waiting": waiting,
        "firstPurchaseDue": first_due,
        "unverifiedBoundary": unverified,
    }
    return due, expired, received
