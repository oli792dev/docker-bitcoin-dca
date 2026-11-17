"""Transactional activity ledger with indexed queries."""

import json
import logging
import os
import re
import sqlite3
import time
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from secrets import token_hex
from threading import RLock
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.data.storage import write_json_atomic

ACTIVITY_PATH = Path("/webui-data/activity.sqlite3")
SNAPSHOT_PATH = Path("/webui-data/dashboard.json")
_ACTIVITY_LOCK = RLock()
_REPORT_LOCK = RLock()
_activity_revision = token_hex(16)


SCHEMA_VERSION = 1
SCHEMA_TABLES = {
    "activity": (
        ("id", "TEXT PRIMARY KEY"),
        ("timestamp", "INTEGER NOT NULL"),
        ("kind", "TEXT"),
        ("asset", "TEXT"),
        ("simulated", "INTEGER"),
        ("exchange", "TEXT"),
        ("currency", "TEXT"),
        ("shares", "TEXT"),
        ("amount", "TEXT"),
        ("fee", "TEXT"),
        ("gross", "TEXT"),
        ("status", "TEXT"),
        ("payload", "TEXT NOT NULL"),
    ),
    "metadata": (("key", "TEXT PRIMARY KEY"), ("value", "TEXT NOT NULL")),
    "cache": (("key", "TEXT PRIMARY KEY"), ("value", "TEXT"), ("updated", "REAL")),
}
SCHEMA_INDEXES = {
    "activity_period": ("activity", "asset,timestamp DESC,id"),
    "activity_type": ("activity", "kind,status,timestamp"),
}


def validate_schema(db):
    if db.execute("PRAGMA user_version").fetchone() != (SCHEMA_VERSION,):
        raise ValueError("Invalid Activity database version.")
    objects = set(db.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"))
    allowed = {("table", name) for name in SCHEMA_TABLES} | {("index", name) for name in SCHEMA_INDEXES}
    if objects != allowed:
        raise ValueError("Unsupported Activity schema.")
    for table, columns in SCHEMA_TABLES.items():
        if [row[1] for row in db.execute(f"PRAGMA table_info({table})")] != [name for name, _ in columns]:
            raise ValueError("Unsupported Activity columns.")


def _timestamp(row):
    value = datetime.fromisoformat(row["datetime"].replace("Z", "+00:00"))
    return int(value.replace(tzinfo=value.tzinfo or UTC).timestamp() * 1000)


def bitcoin_activity_records(records):
    return [r for r in records if str(r.get("row", {}).get("identifier", "")).upper() == "BTC"]


def withdrawal_gross(record):
    if record.get("withdrawalStatus") in ("failed", "canceled", "cancelled"):
        return Decimal(0)
    if record.get("grossWithdrawalAmountBtc") is not None:
        return Decimal(str(record["grossWithdrawalAmountBtc"]))
    row = record["row"]
    amount = Decimal(str(row.get("shares", "0")))
    amount += Decimal(str(record.get("networkFeeBtc", "0")))
    return amount


class _DecimalSum:
    def __init__(self):
        self.value = Decimal(0)

    def step(self, value):
        self.value += Decimal(str(value or "0"))

    def finalize(self):
        return format(self.value, "f")


def _values(record):
    row = record["row"]
    return (
        record["id"],
        _timestamp(row),
        row.get("type", ""),
        row.get("identifier", "").upper(),
        int(bool(record.get("simulated"))),
        record.get("exchange", ""),
        row.get("currency", ""),
        row.get("shares", "0"),
        row.get("amount", "0"),
        row.get("fee", "0"),
        str(withdrawal_gross(record)) if row.get("type") == "TransferOut" else "0",
        record.get("withdrawalStatus", "unverified") if row.get("type") == "TransferOut" else "",
        json.dumps(record, ensure_ascii=False),
    )


_INSERT = "INSERT OR IGNORE INTO activity VALUES(" + ",".join("?" for _ in SCHEMA_TABLES["activity"]) + ")"


def activity_revision():
    return _activity_revision


def _touch_activity():
    global _activity_revision
    _activity_revision = token_hex(16)


@contextmanager
def _db(*, activity_write=False):
    path = ACTIVITY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with _ACTIVITY_LOCK:
        connection = sqlite3.connect(path, timeout=30)
        connection.create_aggregate("decimal_sum", 1, _DecimalSum)
        try:
            os.chmod(path, 0o600)
            connection.execute("PRAGMA synchronous=FULL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise ValueError("Activity database version is newer than this application supports.")
            if version == 0:
                connection.execute("PRAGMA journal_mode=WAL")
                for table, columns in SCHEMA_TABLES.items():
                    definition = ",".join(name + " " + declaration for name, declaration in columns)
                    connection.execute(f"CREATE TABLE IF NOT EXISTS {table}({definition})")
                for name, (table, columns) in SCHEMA_INDEXES.items():
                    connection.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table}({columns})")
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                connection.commit()
            yield connection
            connection.commit()
            if activity_write and connection.total_changes:
                _touch_activity()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def append_activity_records(records):
    with _db(activity_write=True) as db:
        db.executemany(_INSERT, [_values(r) for r in records])
        return db.total_changes


def update_activity_record(record):
    values = _values(record)
    with _db(activity_write=True) as db:
        db.execute(
            "UPDATE activity SET timestamp=?,kind=?,asset=?,simulated=?,exchange=?,currency=?,shares=?,amount=?,fee=?,gross=?,status=?,payload=? WHERE id=?",
            (*values[1:], values[0]),
        )


def has_activity_records():
    with _db() as db:
        return db.execute("SELECT 1 FROM activity LIMIT 1").fetchone() is not None


def read_activity_records():
    with _db() as db:
        return [json.loads(r[0]) for r in db.execute("SELECT payload FROM activity ORDER BY timestamp,id")]


def parqet_interval_records(start, end):
    """Return the complete cycle ending at the last selected confirmed withdrawal."""
    with _report_db() as db:
        completed = "asset='BTC' AND kind='TransferOut' AND simulated=0 AND status='completed'"
        ending = db.execute(
            "SELECT timestamp,exchange,json_extract(payload,'$.accountIdentity') FROM activity WHERE "
            + completed
            + " AND timestamp>? AND timestamp<=? ORDER BY timestamp DESC,id DESC LIMIT 1",
            (start, end),
        ).fetchone()
        if ending is None:
            return []
        latest, exchange, identity = ending
        account_filter = ""
        account_args = ()
        if identity:
            account_filter = " AND json_extract(payload,'$.accountIdentity')=?"
            account_args = (identity,)
        previous = db.execute(
            "SELECT max(timestamp) FROM activity WHERE "
            + completed
            + " AND exchange=? AND timestamp<?"
            + account_filter,
            (exchange, latest, *account_args),
        ).fetchone()[0]
        lower = previous if previous is not None else -1
        return [
            json.loads(r[0])
            for r in db.execute(
                "SELECT payload FROM activity WHERE asset='BTC' AND exchange=? AND timestamp>? AND timestamp<=?"
                + account_filter
                + " ORDER BY timestamp,id",
                (exchange, lower, latest, *account_args),
            )
        ]


def _totals(db, start, end):
    rows = db.execute(
        "SELECT currency,kind,simulated,status,count(*),decimal_sum(shares),decimal_sum(amount),decimal_sum(fee),decimal_sum(gross) FROM activity WHERE asset='BTC' AND timestamp>? AND timestamp<=? GROUP BY currency,kind,simulated,status",
        (start, end),
    ).fetchall()
    rows += db.execute(
        "SELECT currency,'Deposit',0,'confirmed',count(*),'0',decimal_sum(amount),decimal_sum(fee),'0' FROM activity WHERE kind='Deposit' AND json_extract(payload,'$.depositStatus')='confirmed' AND timestamp>? AND timestamp<=? GROUP BY currency",
        (start, end),
    ).fetchall()
    return [
        dict(
            zip(
                ("currency", "kind", "simulated", "status", "count", "shares", "amount", "fee", "gross"), r, strict=True
            )
        )
        for r in rows
    ]


def activity_totals(start=0, end=2**63 - 1):
    with _db() as db:
        return _totals(db, start, end)


def _balance(db):
    rows = db.execute(
        "SELECT kind,decimal_sum(CASE kind WHEN 'Buy' THEN shares ELSE gross END) "
        "FROM activity WHERE asset='BTC' AND simulated=0 AND timestamp>0 AND kind IN ('Buy','TransferOut') "
        "GROUP BY currency,kind,status"
    )
    return sum((Decimal(value) if kind == "Buy" else -Decimal(value) for kind, value in rows), Decimal(0))


def ledger_balance():
    with _db() as db:
        return _balance(db)


_DECIMAL_SEARCH = re.compile(
    r"[€$]?-?(?:[0-9]+[.,][0-9]+|[0-9]{1,3}(?:,[0-9]{3})+\.[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+,[0-9]+)(?:[€$]|/btc)?"
)
_DECIMAL_SEPARATORS = str.maketrans(".,", ",.")


def _matches_search(payload, query, zone=UTC):
    record = json.loads(payload)

    def values(value):
        if isinstance(value, dict):
            return " ".join(values(item) for item in value.values())
        if isinstance(value, list):
            return " ".join(values(item) for item in value)
        return str(value).casefold()

    text = values(record)
    row = record.get("row", {})
    stamp = row.get("datetime")
    if stamp:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        parsed = parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(zone)
        text += " " + parsed.strftime("%d/%m/%Y %H:%M:%S %d.%m.%Y")
    aliases = {"Buy": "buy kauf", "TransferOut": "withdrawal auszahlung", "Deposit": "deposit einzahlung"}
    text += " " + aliases.get(row.get("type"), "")
    if record.get("simulated"):
        text += " simulation simuliert"
    elif (
        row.get("type") == "Buy"
        and record.get("purchaseStatus", "confirmed") == "confirmed"
        or record.get("depositStatus") == "confirmed"
        or record.get("withdrawalStatus") == "completed"
    ):
        text += " confirmed bestätigt completed abgeschlossen"
    status = str(record.get("withdrawalStatus", record.get("purchaseStatus", ""))).lower()
    text += " " + {
        "submitted": "pending ausstehend eingereicht",
        "failed": "fehlgeschlagen",
        "canceled": "cancelled storniert abgebrochen",
        "cancelled": "canceled storniert abgebrochen",
        "unverified": "unverified unbestätigt ungeprüft",
    }.get(status, "")
    symbol = {"EUR": "€", "USD": "$"}.get(row.get("currency"), "")
    visible_numbers = set()
    fields = {"amount": 2}
    if row.get("type") != "Deposit":
        fields.update(price=2, fee=2, shares=8)
    elif record.get("depositStatus"):
        fields["fee"] = 2
    for field, places in fields.items():
        try:
            # Intl formats the browser's Number and rounds midpoint ties away from zero.
            number = Decimal(str(float(row.get(field))))
        except (ValueError, TypeError, OverflowError):
            continue
        if not number.is_finite() or number.adjusted() >= 20:
            continue
        rounded = number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        for grouping in ("", ","):
            formatted = format(rounded, f"{grouping}.{places}f")
            if field == "shares":
                formatted = formatted.rstrip("0").rstrip(".")
            for value in (formatted, formatted.translate(_DECIMAL_SEPARATORS)):
                visible_numbers.add(value)
                if field != "shares" and symbol:
                    visible_numbers.update((symbol + value, value + symbol))
                if field == "price":
                    visible_numbers.update((value + "/btc", symbol + value + "/btc"))
    text += " " + " ".join(visible_numbers)
    text += " " + text.replace(".", ",")
    return all(
        term in visible_numbers if _DECIMAL_SEARCH.fullmatch(term) else term in text
        for term in query.casefold().split()
    )


@contextmanager
def _report_db():
    # Restore can replace the database and its WAL files. Normal ledger writes can
    # proceed while a report reads its own consistent SQLite snapshot.
    with _REPORT_LOCK:
        with _db():
            pass
        with closing(sqlite3.connect(ACTIVITY_PATH.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)) as db:
            db.create_aggregate("decimal_sum", 1, _DecimalSum)
            db.execute("BEGIN")
            yield db


def read_report(start, end, page=1, limit=20, kind="", status="", search="", search_timezone="UTC"):
    """Rows, totals and global balance from one consistent SQLite read transaction."""
    if kind not in ("", "Buy", "TransferOut", "Deposit") or status not in (
        "",
        "real",
        "simulation",
        "confirmed",
        "submitted",
        "completed",
        "failed",
        "canceled",
        "cancelled",
        "unverified",
    ):
        raise ValueError("Invalid Activity filter.")
    if not isinstance(search, str) or len(search) > 256:
        raise ValueError("Activity search must contain at most 256 characters.")
    try:
        if not isinstance(search_timezone, str) or len(search_timezone) > 128:
            raise ValueError
        zone = ZoneInfo(search_timezone)
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("Invalid Activity search timezone.") from None
    limit = max(1, min(1000, int(limit)))
    with _report_db() as db:
        where = "(asset='BTC' OR kind='Deposit') AND timestamp>? AND timestamp<=?"
        args = [start, end]
        if kind:
            where += " AND kind=?"
            args.append(kind)
        if status in ("real", "simulation"):
            where += " AND simulated=?"
            args.append(int(status == "simulation"))
        elif status == "confirmed":
            where += " AND ((kind='Buy' AND simulated=0 AND coalesce(json_extract(payload,'$.purchaseStatus'),'confirmed')='confirmed') OR (kind='Deposit' AND json_extract(payload,'$.depositStatus')='confirmed') OR (kind='TransferOut' AND simulated=0 AND status='completed'))"
        elif status:
            status = "canceled" if status == "cancelled" else status
            where += " AND CASE WHEN kind='Deposit' THEN json_extract(payload,'$.depositStatus') WHEN kind='Buy' AND simulated=0 THEN coalesce(json_extract(payload,'$.purchaseStatus'),'confirmed') WHEN status='cancelled' THEN 'canceled' ELSE status END=?"
            args.append(status)
        requested_page = max(1, min(int(page), 2**63 - 1))
        search = search.strip()
        if search:
            db.create_function(
                "activity_matches", 2, lambda payload, query: _matches_search(payload, query, zone), deterministic=True
            )
            results = db.execute(
                "WITH matches AS MATERIALIZED ("
                "SELECT id,timestamp FROM activity WHERE " + where + " AND activity_matches(payload,?)"
                "), tally AS (SELECT count(*) AS total FROM matches) "
                "SELECT activity.payload,tally.total FROM matches JOIN activity USING(id) CROSS JOIN tally "
                "ORDER BY matches.timestamp DESC,matches.id DESC LIMIT ? "
                "OFFSET (SELECT (max(1,min(?,(total+?-1)/?))-1)*? FROM tally)",
                (*args, search, limit, requested_page, limit, limit, limit),
            ).fetchall()
            total = results[0][1] if results else 0
            rows = results
        else:
            total = db.execute("SELECT count(*) FROM activity WHERE " + where, args).fetchone()[0]
            page = max(1, min(requested_page, max(1, (total + limit - 1) // limit)))
            rows = db.execute(
                "SELECT payload FROM activity WHERE " + where + " ORDER BY timestamp DESC,id DESC LIMIT ? OFFSET ?",
                (*args, limit, (page - 1) * limit),
            ).fetchall()
        page = max(1, min(requested_page, max(1, (total + limit - 1) // limit)))
        return (
            [json.loads(r[0]) for r in rows],
            total,
            page,
            _totals(db, start, end),
            _balance(db),
        )


def withdrawal_records(unresolved=False):
    query = "SELECT payload FROM activity WHERE asset='BTC' AND kind='TransferOut' AND simulated=0"
    if unresolved:
        query += " AND status NOT IN ('completed','failed','canceled','cancelled')"
    query += " ORDER BY timestamp,id"
    with _db() as db:
        return [json.loads(r[0]) for r in db.execute(query)]


def withdrawal_cycle_bounds():
    """Read matching purchase and withdrawal bounds in the same report snapshot."""
    intervals = []
    previous = {}
    with _report_db() as db:
        withdrawals = db.execute(
            "SELECT timestamp,id,exchange,coalesce(json_extract(payload,'$.accountIdentity'),'')"
            " FROM activity WHERE asset='BTC' AND kind='TransferOut' AND simulated=0 AND status='completed'"
            " ORDER BY timestamp,id"
        )
        for timestamp, tx_id, exchange, identity in withdrawals:
            scope = (exchange, identity)
            start = previous.get(scope, 0)
            analysis_start = start
            if not start:
                analysis_start = db.execute(
                    "SELECT min(timestamp) FROM activity WHERE asset='BTC' AND kind='Buy' AND simulated=0"
                    " AND exchange=? AND coalesce(json_extract(payload,'$.accountIdentity'),'')=?"
                    " AND coalesce(json_extract(payload,'$.purchaseStatus'),'confirmed')='confirmed'"
                    " AND timestamp<=?",
                    (*scope, timestamp),
                ).fetchone()[0]
            intervals.append(
                {
                    "timestamp": timestamp,
                    "startTimestamp": start,
                    "analysisStartTimestamp": analysis_start,
                    "txId": tx_id,
                    "exchange": exchange,
                }
            )
            previous[scope] = timestamp
    return intervals


def read_dashboard_snapshot():
    with _ACTIVITY_LOCK:
        source = SNAPSHOT_PATH if SNAPSHOT_PATH.exists() else None
        if not source:
            return {}
        try:
            value = json.loads(source.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            logging.getLogger("bitcoin-dca.activity").warning(
                "Derived dashboard snapshot could not be read; rebuilding from the ledger."
            )
            return {}
        return value if isinstance(value, dict) else {}


def write_dashboard_snapshot(snapshot):
    with _ACTIVITY_LOCK:
        write_json_atomic(SNAPSHOT_PATH, snapshot)


def cache_get_many(keys):
    if not keys:
        return {}
    with _db() as db:
        return {
            key: (json.loads(value), updated)
            for key, value, updated in db.execute(
                "SELECT key,value,updated FROM cache WHERE key IN (" + ",".join("?" for _ in keys) + ")", tuple(keys)
            )
        }


def cache_put_many(values):
    with _db() as db:
        db.executemany(
            "INSERT OR REPLACE INTO cache VALUES(?,?,?)",
            [(key, json.dumps(value), time.time()) for key, value in values.items()],
        )


def get_activity_record(activity_id):
    with _db() as db:
        row = db.execute("SELECT payload FROM activity WHERE id=?", (activity_id,)).fetchone()
        return json.loads(row[0]) if row else None


def activity_records_by_id(activity_ids: list[str]):
    if not activity_ids:
        return {}
    with _db() as db:
        rows = db.execute(
            "SELECT id,payload FROM activity WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(activity_ids),),
        )
        return {activity_id: json.loads(payload) for activity_id, payload in rows}


def latest_real_buy(exchange=None, account_identity=None):
    with _db() as db:
        where = "asset='BTC' AND kind='Buy' AND simulated=0"
        args = []
        if exchange:
            where += " AND exchange=?"
            args.append(exchange)
        if account_identity:
            where += " AND json_extract(payload,'$.accountIdentity')=?"
            args.append(account_identity)
        row = db.execute(
            "SELECT timestamp FROM activity WHERE " + where + " ORDER BY timestamp DESC LIMIT 1", args
        ).fetchone()
        return datetime.fromtimestamp(row[0] / 1000, UTC) if row else None
