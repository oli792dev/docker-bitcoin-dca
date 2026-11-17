"""Reconcile submitted withdrawals conservatively against exchange history."""

import logging
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.core.logging_utils import log_transition
from app.data.activity import update_activity_record, withdrawal_records

LOG = logging.getLogger("bitcoin-dca.withdrawals")
# Limit matching to the connection and first-response timeout budget.
KRAKEN_WITHDRAWAL_WINDOW_MS = 40_000


def withdrawal_status(value: str) -> str:
    status = value.lower()
    if status in ("success", "completed"):
        return "completed"
    if status in ("failure", "failed", "canceled", "cancelled"):
        return "failed"
    return "submitted"


def match_kraken_withdrawal(api, pending: dict, context: dict) -> dict | None:
    """Read the saved attempt window and identify one independently verified Kraken withdrawal."""
    submitted = context.get("timestamp_ms")
    key = pending.get("key")
    if type(submitted) is not int or submitted <= 0 or not isinstance(key, str) or not key:
        return None
    # Kraken reports creation times at whole-second precision. Legacy state saved only the start.
    start = submitted // 1000 * 1000
    end = context.get("kraken_recovery_until_ms", submitted + KRAKEN_WITHDRAWAL_WINDOW_MS)
    if type(end) is not int or not submitted <= end <= submitted + KRAKEN_WITHDRAWAL_WINDOW_MS:
        return None
    try:
        amount = Decimal(str(pending.get("amount")))
        fee = Decimal(str(pending.get("fee")))
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount <= 0 or not fee.is_finite() or fee < 0:
        return None
    rows = api.btc_withdrawals(start, end)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        return None
    matches = []
    for row in rows:
        timestamp = row.get("timestamp")
        if type(timestamp) is int and timestamp > 0 and not start <= timestamp <= end:
            continue
        if row.get("symbol") not in (None, "", "BTC") or row.get("key") not in (None, "", key):
            continue
        try:
            row_amount = Decimal(str(row.get("amount")))
            row_fee = Decimal(str(row.get("fee")))
        except InvalidOperation:
            return None
        if not row_amount.is_finite() or not row_fee.is_finite():
            return None
        if row_amount != amount or row_fee != fee:
            continue
        if (
            type(timestamp) is not int
            or not start <= timestamp <= end
            or row.get("symbol") != "BTC"
            or row.get("key") != key
            or not isinstance(row.get("id"), str)
            or not row["id"].strip()
            or not isinstance(row.get("status"), str)
            or not row["status"].strip()
        ):
            return None
        matches.append(row)
    if len(matches) != 1:
        return None
    match = matches[0]
    return match if sum(row.get("id") == match["id"] for row in rows) == 1 else None


def reconcile_withdrawals(api, settings, force=False, submitted_only=False):
    now = time.monotonic()
    previous = getattr(api, "_withdrawal_check_at", None)
    if isinstance(previous, (int, float)) and not force and now - previous < 30:
        return
    api._withdrawal_check_at = now
    waiting = withdrawal_records(unresolved=True)
    if submitted_only:
        waiting = [record for record in waiting if record.get("withdrawalStatus") == "submitted"]
    waiting.sort(key=lambda r: r.get("withdrawalStatus") != "submitted")
    checked = 0
    for record in waiting:
        if record.get("nextVerificationAt", 0) > time.time() and not force:
            continue
        if checked >= 4 and not force:
            break
        if record.get("exchange") not in ("", None, settings["exchange"]):
            continue
        row = record["row"]
        stamp = int(datetime.fromisoformat(row["datetime"].replace("Z", "+00:00")).timestamp() * 1000)
        first_submission = int(record.get("firstSubmittedAt", stamp))
        last_submission = int(record.get("lastSubmittedAt", stamp))
        window_start = max(0, min(stamp, first_submission) - 300000)
        window_end = max(stamp, last_submission) + 300000
        checked += 1
        candidates = api.btc_withdrawals(window_start, window_end)
        identifier = record.get("withdrawalId") or record["id"].removeprefix("withdrawal:")
        matches = []
        for candidate in candidates:
            identity = candidate.get("id") or candidate.get("refid")
            if identity and str(identity) == str(identifier):
                matches.append(candidate)
                continue
            if record.get("txId") and candidate.get("txId") == record["txId"]:
                matches.append(candidate)
                continue
            if settings["exchange"] != "BITVAVO" or not record.get("withdrawalAddress"):
                continue
            fee = Decimal(str(candidate.get("fee", "0")))
            gross = Decimal(str(candidate.get("amount", "0"))) + fee
            if (
                candidate.get("address") == record["withdrawalAddress"]
                and window_start <= int(candidate.get("timestamp", 0)) <= window_end
                and gross == Decimal(str(record.get("grossWithdrawalAmountBtc", "-1")))
            ):
                matches.append(candidate)
        if len(matches) != 1:
            overdue = time.time() - stamp / 1000 >= 3600
            level = logging.ERROR if overdue else logging.WARNING
            log_transition(
                LOG,
                api,
                "withdrawal-verification:" + record["id"],
                "overdue" if overdue else "ambiguous",
                level,
                "BTC withdrawal %s has no unique exchange-history match; verification deferred%s.",
                identifier,
                "; unresolved for at least one hour, check exchange status" if overdue else "",
            )
            record["nextVerificationAt"] = time.time() + 300
            record["verificationNote"] = "No unique exchange-history match; not exportable."
            update_activity_record(record)
            continue  # Never guess between indistinguishable withdrawals.
        found = matches[0]
        if found.get("timestamp") and int(found["timestamp"]) > 0:
            row["datetime"] = datetime.fromtimestamp(int(found["timestamp"]) / 1000, UTC).isoformat()
        status = withdrawal_status(str(found.get("status", "")))
        record.pop("nextVerificationAt", None)
        record.pop("verificationNote", None)
        record["exchange"] = settings["exchange"]
        previous_status = record.get("withdrawalStatus")
        record["withdrawalStatus"] = status
        record["exchangeStatus"] = str(found.get("status", ""))
        record["txId"] = found.get("txId", "")
        record["lastVerifiedAt"] = datetime.now(UTC).isoformat()
        fee_value = found.get("fee")
        fee = Decimal(str(fee_value if fee_value is not None else record.get("networkFeeBtc", "0")))
        amount_value = found.get("amount")
        net = Decimal(str(amount_value if amount_value is not None else row["shares"]))
        record["networkFeeBtc"] = str(fee)
        record["grossWithdrawalAmountBtc"] = str(net + fee)
        record["netWithdrawalAmount"] = True
        row["shares"] = str(net)
        row["amount"] = str(net * Decimal(row["price"]))
        row["fee"] = str(fee * Decimal(row["price"]))
        update_activity_record(record)
        if previous_status != status:
            LOG.log(
                logging.WARNING if status == "failed" else logging.INFO,
                "BTC withdrawal %s status changed: %s -> %s (exchange status=%s)",
                identifier,
                previous_status,
                status,
                record["exchangeStatus"],
            )
