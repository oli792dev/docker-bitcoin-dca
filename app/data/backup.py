"""Authenticated bounded backups and recoverable volume restores.

All callers hold the account lock; SQLite operations additionally hold the ledger
lock. The durable journal survives interruption and is rolled back before startup.
"""

import hashlib
import io
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.data import activity
from app.data.storage import write_json_atomic

MAX_BYTES = 32 * 1024 * 1024
MAGIC = b"DCA-BACKUP-1\0"
FILES = frozenset(
    {"config.json", "state.json", "controls.json", "installation.json", "report-preferences.json", "activity.sqlite3"}
)
SCOPES = {
    "full": FILES,
    "activity": frozenset({"activity.sqlite3"}),
    "config": frozenset({"config.json", "report-preferences.json", "controls.json"}),
}
JOURNAL = ".restore-journal"
COMPLETED = ".restore-completed"
LOG = logging.getLogger("bitcoin-dca.backup")


def _key(password, salt):
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError("Backup password must contain 12–1024 characters.")
    return hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, maxmem=128 * 1024 * 1024, dklen=32)


def encrypt(payload, password):
    """Encrypt a bounded archive using scrypt and AES-256-GCM."""
    if len(payload) > MAX_BYTES:
        raise ValueError("Backup exceeds the 32 MiB limit.")
    salt, nonce = os.urandom(16), os.urandom(12)
    header = MAGIC + salt + nonce
    return header + AESGCM(_key(password, salt)).encrypt(nonce, payload, header)


def decrypt(payload, password):
    """Authenticate the versioned envelope before parsing any archive content."""
    size = len(MAGIC)
    if (
        not isinstance(payload, bytes)
        or not size + 44 <= len(payload) <= MAX_BYTES + size + 44
        or not payload.startswith(MAGIC)
    ):
        raise ValueError("Invalid backup envelope or backup size.")
    salt, nonce = payload[size : size + 16], payload[size + 16 : size + 28]
    try:
        return AESGCM(_key(password, salt)).decrypt(nonce, payload[size + 28 :], payload[: size + 28])
    except InvalidTag:
        raise ValueError("Backup password is incorrect or the backup was modified.") from None


def unpack(payload):
    """Read only exact allowed members; never extract paths or accept zip bombs."""
    if len(payload) > MAX_BYTES:
        raise ValueError("Backup exceeds the 32 MiB limit.")
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            members = archive.infolist()
            names = [item.filename for item in members]
            if (
                len(names) != len(set(names))
                or not set(names) <= FILES | {"manifest.json"}
                or "manifest.json" not in names
            ):
                raise ValueError("Invalid backup members.")
            if (
                any(
                    item.compress_type != zipfile.ZIP_STORED or item.flag_bits & 1 or item.file_size > MAX_BYTES
                    for item in members
                )
                or sum(item.file_size for item in members) > MAX_BYTES
            ):
                raise ValueError("Invalid backup compression or size.")
            data = {item.filename: archive.read(item) for item in members}
            manifest = json.loads(data.pop("manifest.json"))
            if (
                not isinstance(manifest, dict)
                or set(manifest) != {"version", "scope", "createdAt", "files"}
                or manifest["version"] != 1
                or manifest["scope"] not in SCOPES
            ):
                raise ValueError("Unsupported backup manifest.")
            created = datetime.fromisoformat(manifest["createdAt"])
            if created.tzinfo is None:
                raise ValueError("Invalid backup timestamp.")
            expected = SCOPES[manifest["scope"]]
            if set(data) != expected or manifest["files"] != {
                name: hashlib.sha256(value).hexdigest() for name, value in data.items()
            }:
                raise ValueError("Backup contents do not match the manifest.")
            return manifest, data
    except (zipfile.BadZipFile, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError, RuntimeError) as exc:
        raise ValueError("Invalid backup archive.") from exc


def sqlite_snapshot(source, destination):
    """Use SQLite's backup API to include committed WAL content consistently."""
    with (
        closing(sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True)) as reader,
        closing(sqlite3.connect(destination)) as writer,
    ):
        reader.backup(writer)
    os.chmod(destination, 0o600)


def _records(path):
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA integrity_check").fetchone() != ("ok",) or db.execute(
            "PRAGMA user_version"
        ).fetchone() != (1,):
            raise ValueError("Invalid Activity database.")
        objects = db.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
        allowed = {
            ("table", "activity"),
            ("table", "metadata"),
            ("table", "cache"),
            ("index", "activity_period"),
            ("index", "activity_type"),
        }
        if set(objects) != allowed:
            raise ValueError("Unsupported Activity schema.")
        columns = [r[1] for r in db.execute("PRAGMA table_info(activity)")]
        if columns != [
            "id",
            "timestamp",
            "kind",
            "asset",
            "simulated",
            "exchange",
            "currency",
            "shares",
            "amount",
            "fee",
            "gross",
            "status",
            "payload",
        ]:
            raise ValueError("Unsupported Activity columns.")
        records = {}
        for values in db.execute("SELECT * FROM activity"):
            if len(values[-1]) > 262144:
                raise ValueError("Activity record is too large.")
            record = json.loads(values[-1])
            row = record["row"]
            if "simulated" in record and type(record["simulated"]) is not bool:
                raise ValueError("Invalid Activity record.")
            for name in ("networkFeeBtc", "grossWithdrawalAmountBtc"):
                if name in record:
                    number = Decimal(str(record[name]))
                    if not number.is_finite() or number < 0:
                        raise ValueError("Invalid Activity amount.")
            if (
                not isinstance(record.get("id"), str)
                or not 1 <= len(record["id"]) <= 512
                or row.get("type") not in ("Buy", "TransferOut", "Deposit")
            ):
                raise ValueError("Invalid Activity record.")
            for name in ("shares", "amount", "fee", "price"):
                number = Decimal(str(row.get(name, "0")))
                if not number.is_finite() or number < 0:
                    raise ValueError("Invalid Activity amount.")
            if tuple(activity._values(record)) != values:
                raise ValueError("Activity index and payload disagree.")
            records[record["id"]] = record
        return records


def _unresolved(records):
    return any(
        row["row"]["type"] == "TransferOut"
        and not row.get("simulated")
        and row.get("withdrawalStatus") not in ("completed", "failed", "canceled", "cancelled")
        for row in records.values()
    )


def _sync_directory(directory):
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _finish_restore(directory):
    # Retire the complete journal atomically before any rollback copies are deleted.
    os.replace(directory / JOURNAL, directory / COMPLETED)
    _sync_directory(directory)
    recover_restore(directory)


def recover_restore(directory):
    """Rollback interrupted multi-file restore before settings can be loaded."""
    directory = Path(directory)
    completed = directory / COMPLETED
    if completed.exists():
        try:
            shutil.rmtree(completed)
            _sync_directory(directory)
        except OSError:
            LOG.warning("Completed restore cleanup deferred until restart")
    journal = directory / JOURNAL
    marker = journal / "manifest.json"
    if not journal.exists():
        return
    if not marker.exists():
        # Preparation never touched destination files. A half-prepared journal
        # can be removed safely; restoration starts only after durable manifest.
        shutil.rmtree(journal)
        return
    manifest = json.loads(marker.read_text())
    if (
        not isinstance(manifest, dict)
        or set(manifest) != FILES
        or any(type(value) is not bool for value in manifest.values())
    ):
        raise ValueError("Invalid restore recovery journal; transactions remain blocked.")
    with activity._ACTIVITY_LOCK:
        for name, existed in manifest.items():
            target = directory / name
            if existed:
                source = journal / name
                if name.endswith("sqlite3"):
                    sqlite_snapshot(source, target)
                else:
                    write_json_atomic(target, json.loads(source.read_text()))
            elif name == "activity.sqlite3":
                for suffix in ("", "-wal", "-shm"):
                    (directory / (name + suffix)).unlink(missing_ok=True)
            else:
                target.unlink(missing_ok=True)
        write_json_atomic(directory / "controls.json", {"paused": True, "until": None})
        _finish_restore(directory)


class Backups:
    """Consistent archive creation and validated restore while the worker is locked."""

    def __init__(self, directory):
        self.directory = Path(directory)

    def create(self, scope, password):
        if not isinstance(scope, str) or scope not in SCOPES:
            raise ValueError("Invalid backup scope.")
        with activity._ACTIVITY_LOCK, tempfile.TemporaryDirectory(dir=self.directory, prefix=".backup-") as tmp:
            data = {}
            if "activity.sqlite3" in SCOPES[scope]:
                with activity._db():
                    pass
                database = Path(tmp) / "activity.sqlite3"
                sqlite_snapshot(self.directory / "activity.sqlite3", database)
                data["activity.sqlite3"] = database.read_bytes()
            if scope != "activity":
                for name in SCOPES[scope] - {"activity.sqlite3"}:
                    path = self.directory / name
                    data[name] = (
                        path.read_bytes()
                        if path.exists()
                        else json.dumps(
                            {"paused": False, "until": None}
                            if name == "controls.json"
                            else {
                                "from": json.loads((self.directory / "installation.json").read_text())["firstStartedAt"]
                            }
                            if name == "report-preferences.json"
                            else {}
                        ).encode()
                    )
            manifest = {
                "version": 1,
                "scope": scope,
                "createdAt": datetime.now(UTC).isoformat(),
                "files": {name: hashlib.sha256(value).hexdigest() for name, value in data.items()},
            }
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                for name, value in data.items():
                    archive.writestr(name, value)
            encrypted = encrypt(output.getvalue(), password)
            suffix = "activities" if scope == "activity" else scope
            filename = "bitcoin-dca-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + suffix + ".dcabackup"
            return filename, encrypted

    def restore(self, encrypted, password, scope, unresolved=False):
        if (scope is not None and (not isinstance(scope, str) or scope not in SCOPES)) or unresolved:
            raise ValueError("Resolve pending financial work before restoring a backup.")
        manifest, data = unpack(decrypt(encrypted, password))
        if scope is None:
            scope = manifest["scope"]
            if scope not in ("full", "config"):
                raise ValueError("Initial setup requires a Full or Config backup with login credentials.")
        required = SCOPES[scope]
        if not required <= data.keys():
            raise ValueError("Backup does not contain the selected restore scope.")
        restore_files = SCOPES[scope] & data.keys()
        with activity._ACTIVITY_LOCK, tempfile.TemporaryDirectory(dir=self.directory, prefix=".restore-") as tmp:
            recover_restore(self.directory)
            if (self.directory / COMPLETED).exists():
                raise ValueError("Previous restore cleanup could not finish; check persistent storage.")
            records = {}
            if scope != "config":
                incoming = Path(tmp) / "activity.sqlite3"
                incoming.write_bytes(data["activity.sqlite3"])
                os.chmod(incoming, 0o600)
                records = _records(incoming)
            if _unresolved(records):
                raise ValueError("Backup contains unresolved withdrawals; restore is blocked.")
            with activity._db():
                pass
            current_path = self.directory / "activity.sqlite3"
            current = _records(current_path)
            if _unresolved(current):
                raise ValueError("Resolve pending withdrawals before restoring a backup.")
            if any(key in records and records[key] != value for key, value in current.items()):
                raise ValueError("Backup conflicts with existing Activity; no records were changed.")
            if scope != "activity":
                from app.core.configuration import ConfigStore

                for name in restore_files - {"activity.sqlite3"}:
                    value = json.loads(data[name])
                    if not isinstance(value, dict):
                        raise ValueError("Invalid backup JSON file.")
                    (Path(tmp) / name).write_bytes(data[name])
                for name, key in (("installation.json", "firstStartedAt"), ("report-preferences.json", "from")):
                    if name not in SCOPES[scope]:
                        continue
                    value = json.loads(data[name])
                    if (
                        set(value) != {key}
                        or not isinstance(value[key], str)
                        or datetime.fromisoformat(value[key]).tzinfo is None
                    ):
                        raise ValueError("Invalid backup reporting preferences.")
                config = ConfigStore._read(Path(tmp) / "config.json")
                if config.get("version") != 1 or not isinstance(config.get("account"), dict):
                    raise ValueError("Invalid backup configuration.")
            if scope == "full":
                state = json.loads(data["state.json"])
                if (
                    state.get("pending_order")
                    or state.get("pending_withdrawal")
                    or state.get("pending_withdrawal_context")
                    or state.get("fiat_observation", {}).get("pending")
                ):
                    raise ValueError("Backup contains pending financial requests; full restore is blocked.")
                if not current.keys() <= records.keys():
                    raise ValueError("Full restore would remove Activity. Use Activity-only restore to merge history.")
                old_state = json.loads((self.directory / "state.json").read_text())
                if old_state.get("last_order_at") and (
                    not state.get("last_order_at")
                    or datetime.fromisoformat(state["last_order_at"])
                    < datetime.fromisoformat(old_state["last_order_at"])
                ):
                    raise ValueError("Full restore would rewind financial state. Use Activity-only restore.")
            from app.trading.controls import PauseControl

            controls = PauseControl(
                Path(tmp) / "controls.json" if "controls.json" in restore_files else self.directory / "controls.json"
            ).snapshot()
            journal = self.directory / JOURNAL
            journal.mkdir(mode=0o700)
            existed = {name: (self.directory / name).exists() for name in FILES}
            for name, present in existed.items():
                if present:
                    if name.endswith("sqlite3"):
                        sqlite_snapshot(self.directory / name, journal / name)
                    else:
                        write_json_atomic(journal / name, json.loads((self.directory / name).read_text()))
            write_json_atomic(journal / "manifest.json", existed)
            _sync_directory(self.directory)
            try:
                if scope != "activity":
                    for name in restore_files - {"activity.sqlite3"}:
                        write_json_atomic(self.directory / name, json.loads(data[name]))
                # Import validated records into the application's own schema;
                # archived SQL, caches and indexes are never installed.
                if scope != "config":
                    with activity._db() as db:
                        db.executemany(activity._INSERT, [activity._values(row) for row in records.values()])
                (self.directory / "dashboard.json").unlink(missing_ok=True)
            except BaseException:
                recover_restore(self.directory)
                raise
            _finish_restore(self.directory)
        return {"restored": True, "paused": controls["paused"], "scope": scope}
