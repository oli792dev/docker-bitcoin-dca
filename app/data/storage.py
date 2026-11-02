"""Volume-only runtime paths and atomic initialization of new storage."""

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

type JSONValue = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]
type StoragePath = str | os.PathLike[str]

LOG = logging.getLogger("bitcoin-dca.storage")
DATA_DIR = Path("/webui-data")
STATE_PATH = DATA_DIR / "state.json"
HEALTH_PATH = DATA_DIR / "worker-health.json"


def _read(path: Path) -> dict[str, JSONValue]:
    data: object = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError("Invalid persistent file: " + path.name)
    return cast(dict[str, JSONValue], data)


def write_json_atomic(path: StoragePath, data: object) -> None:
    """Replace a JSON file durably without exposing partial or public data."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".storage-", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def installation_started_at(data_dir: StoragePath | None = None) -> str:
    """Immutable first-start timestamp, independent of scheduling resets."""
    directory = Path(data_dir) if data_dir is not None else DATA_DIR
    path = directory / "installation.json"
    if not path.exists():
        write_json_atomic(path, {"firstStartedAt": datetime.now(UTC).isoformat(timespec="seconds")})
    value = _read(path)["firstStartedAt"]
    if not isinstance(value, str):
        raise ValueError("Invalid installation start timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Invalid installation start timestamp")
    return value


def prepare_storage(data_dir: StoragePath | None = None) -> None:
    """Validate existing volume state or initialize an empty first-run volume."""
    destination = Path(data_dir) if data_dir is not None else DATA_DIR
    destination.mkdir(parents=True, exist_ok=True)
    installation_started_at(destination)
    state = destination / "state.json"
    if state.exists():
        _read(state)
        os.chmod(state, 0o600)
        return
    configuration = destination / "config.json"
    saved = _read(configuration) if configuration.exists() else {}
    has_history = (destination / "activity.sqlite3").exists() or (destination / "activity.json").exists()
    if saved.get("complete") or has_history:
        write_json_atomic(state, {})
        LOG.warning(
            "Scheduling state is missing; initialized empty state. Automatic exchange checks must pass before new transactions."
        )
        return
    write_json_atomic(state, {})
    LOG.info("Persistent storage initialized in the named web UI volume")
