"""Durable transaction gate independent of monthly scheduling state."""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from app.data.storage import write_json_atomic


class PauseControl:
    """Pause new financial work while preserving account observations and due dates."""

    def __init__(self, path: Path):
        self.path = path

    def snapshot(self, now=None):
        data = json.loads(self.path.read_text()) if self.path.exists() else {"paused": False, "until": None}
        if not isinstance(data, dict) or type(data.get("paused")) is not bool:
            raise ValueError("Invalid transaction controls; transactions remain paused.")
        until = data.get("until")
        if until is not None and not isinstance(until, str):
            raise ValueError("Invalid transaction controls; transactions remain paused.")
        parsed = datetime.fromisoformat(until.replace("Z", "+00:00")) if until else None
        if parsed and parsed.tzinfo is None:
            raise ValueError("Invalid transaction controls; transactions remain paused.")
        expires = parsed.timestamp() if parsed else None
        return {
            "paused": data["paused"] and (expires is None or expires > (time.time() if now is None else now)),
            "until": until,
        }

    def set(self, paused, until=None):
        if type(paused) is not bool or until is not None and not isinstance(until, str):
            raise ValueError("Invalid pause request.")
        if until:
            try:
                parsed = datetime.fromisoformat(until.replace("Z", "+00:00"))
                if parsed.tzinfo is None or parsed.timestamp() <= time.time():
                    raise ValueError
                until = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
            except ValueError:
                raise ValueError("Pause end must be a future timestamp with timezone.") from None
        write_json_atomic(self.path, {"paused": paused, "until": until if paused else None})
        return self.snapshot()
