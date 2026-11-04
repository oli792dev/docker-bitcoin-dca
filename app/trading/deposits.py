"""Import booked fiat deposits without changing Bitcoin accounting or CSV exports."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from app.data.activity import append_activity_records
from app.trading.deposit_types import (
    DepositActivity,
    DepositHistoryExchange,
    DepositSettings,
    FiatObservation,
    FundingState,
)

_persist_deposits: Callable[[list[DepositActivity]], int] = append_activity_records


def sync_deposits(
    api: DepositHistoryExchange,
    settings: DepositSettings,
    state: FundingState,
    now: datetime,
    balance: Decimal,
) -> tuple[list[DepositActivity], int]:
    """Verify booked increases, excluding order holds; keep unexplained funding paused."""
    identity = [settings["exchange"], settings["quote"]]
    if settings.get("account_identity"):
        identity.append(settings["account_identity"])
    previous = state.get("fiat_observation")
    observation: FiatObservation = {"identity": identity, "checkedAt": now.isoformat(), "balance": str(balance)}
    # Adapter methods read the same scoped snapshot as the available balance.
    # Unknown adapters retain the conservative available-balance behavior.
    booked_reader = getattr(type(api), "booked_balance", None)
    booked = booked_reader(api, settings["quote"]) if callable(booked_reader) else None
    if booked is not None:
        if not isinstance(booked, Decimal) or not booked.is_finite():
            raise ValueError("Booked fiat balance could not be verified")
        observation["booked"] = str(booked)
    if previous is None or previous.get("identity") != identity:
        state["fiat_observation"] = observation
        return [], 0
    pending = previous.get("pending")
    rise = balance - Decimal(previous["balance"])
    if booked is not None and "booked" in previous:
        rise = booked - Decimal(previous["booked"])
    if rise >= Decimal(".01"):
        pending = pending or {"start": previous["checkedAt"], "balanceBaseline": previous["balance"]}
        if booked is not None and "booked" in previous and "bookedBaseline" not in pending:
            pending["bookedBaseline"] = previous["booked"]
    confirmed = previous.get("confirmed", [])
    observation["confirmed"] = confirmed
    if not pending:
        state["fiat_observation"] = observation
        return confirmed, 0
    observation["pending"] = pending
    state["fiat_observation"] = observation
    # The adapter may round request timestamps; filter returned rows to this exact window.
    start = max(0, int(datetime.fromisoformat(pending["start"]).timestamp() * 1000))
    rows = api.fiat_deposits(settings["quote"], start, int(now.timestamp() * 1000))
    if not isinstance(rows, list):
        raise ValueError("Fiat deposit history could not be verified")
    records: list[DepositActivity] = []
    account_scope = f"{settings['account_identity']}:" if settings.get("account_identity") else ""
    for item in rows:
        if item.get("status") != "completed" or item.get("symbol") != settings["quote"]:
            continue
        amount = Decimal(item["amount"])
        fee = Decimal(item.get("fee", "0"))
        if not amount.is_finite() or not fee.is_finite() or amount <= 0 or fee < 0 or fee > amount:
            raise ValueError("Invalid fiat deposit amount or fee")
        timestamp = int(item["timestamp"])
        if not item.get("id") or timestamp < 0:
            raise ValueError("Invalid fiat deposit reference or timestamp")
        if not start <= timestamp <= int(now.timestamp() * 1000):
            continue
        legacy_id = f"fiat-deposit:{settings['exchange']}:{settings['quote']}:{item['id']}"
        record_id = f"fiat-deposit:{settings['exchange']}:{settings['quote']}:{account_scope}{item['id']}"
        if any(record["id"] == legacy_id for record in confirmed):
            record_id = legacy_id
        record: DepositActivity = {
            "id": record_id,
            "exchange": settings["exchange"],
            "depositStatus": "confirmed",
            "row": {
                "datetime": datetime.fromtimestamp(timestamp / 1000, UTC).isoformat(),
                "type": "Deposit",
                "identifier": settings["quote"],
                "assetType": "Cash",
                "currency": settings["quote"],
                "amount": str(amount),
                "fee": str(fee),
                "shares": "0",
                "price": "0",
                "tax": "0",
            },
        }
        if settings.get("account_identity"):
            record["accountIdentity"] = settings["account_identity"]
        records.append(record)
    # Insert before advancing the checkpoint; retrying the same exchange IDs is harmless.
    inserted = _persist_deposits(records) if records else 0
    deposit_total = sum(
        (Decimal(record["row"]["amount"]) - Decimal(record["row"]["fee"]) for record in records), Decimal(0)
    )
    verified = False
    if booked is not None and (
        "bookedBaseline" in pending or getattr(type(api), "supports_unanchored_funding_verification", False) is True
    ):
        classifier = getattr(type(api), "non_deposit_balance_change", None)
        if (
            callable(classifier)
            and classifier(
                api,
                settings["quote"],
                start,
                int(now.timestamp() * 1000),
                Decimal(pending["bookedBaseline"]) if "bookedBaseline" in pending else None,
                booked,
                deposit_total,
            )
            is True
        ):
            verified = True
    elif booked is None and records and "balanceBaseline" in pending:
        verified = Decimal(pending["balanceBaseline"]) + deposit_total == balance
    if verified:
        observation.pop("pending", None)
        if records:
            observation["confirmed"] = records
    return observation["confirmed"], inserted
