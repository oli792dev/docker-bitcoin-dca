"""Import booked fiat deposits without changing Bitcoin accounting or CSV exports."""

from datetime import UTC, datetime
from decimal import Decimal

from app.data.activity import append_activity_records


def sync_deposits(api, settings, state, now, balance):
    """Query only after available fiat rises; retain a narrow window for retries."""
    identity = [settings["exchange"], settings["quote"]]
    previous = state.get("fiat_observation", {})
    observation = {"identity": identity, "checkedAt": now.isoformat(), "balance": str(balance)}
    if previous.get("identity") != identity:
        state["fiat_observation"] = observation
        return [], 0
    pending = previous.get("pending")
    if balance - Decimal(previous["balance"]) >= Decimal(".01"):
        pending = pending or {"start": previous["checkedAt"]}
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
    records = []
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
        records.append(
            {
                "id": f"fiat-deposit:{settings['exchange']}:{settings['quote']}:{item['id']}",
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
        )
    # Insert before advancing the checkpoint; retrying the same exchange IDs is harmless.
    inserted = append_activity_records(records) if records else 0
    known = {record["id"] for record in confirmed}
    if any(record["id"] not in known for record in records):
        observation.pop("pending", None)
        observation["confirmed"] = records
    return observation["confirmed"], inserted
