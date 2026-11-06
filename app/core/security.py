"""Bounded restore parsing and thread-safe password-attempt limits."""

import json
import math
import re
import time
from threading import RLock


class AttemptLimiter:
    def __init__(self, limit: int = 5, window: int = 900, capacity: int = 1024) -> None:
        self.limit, self.window, self.capacity = limit, window, capacity
        self.attempts: dict[str, list[float]] = {}
        self.lock = RLock()

    def consume(self, key: str) -> int:
        """Reserve an attempt before password hashing; return retry delay or zero."""
        now = time.monotonic()
        with self.lock:
            self.attempts = {
                k: [stamp for stamp in stamps if now - stamp < self.window]
                for k, stamps in self.attempts.items()
                if stamps and now - stamps[-1] < self.window
            }
            stamps = self.attempts.get(key, [])
            if len(stamps) >= self.limit:
                return max(1, math.ceil(stamps[0] + self.window - now))
            if key not in self.attempts and len(self.attempts) >= self.capacity:
                return self.window
            self.attempts.setdefault(key, []).append(now)
            return 0

    def clear(self, key: str) -> None:
        with self.lock:
            self.attempts.pop(key, None)


class PasswordConfirmationError(ValueError):
    def __init__(self, message: str, retry_after: int = 0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def string_object(text: str, limits: dict[str, int]) -> dict[str, str]:
    """Decode a flat restore envelope without materializing attacker-supplied containers."""
    decoder = json.JSONDecoder()
    whitespace = re.compile(r"[ \t\r\n]*")

    def skip_space(position: int) -> int:
        match = whitespace.match(text, position)
        if match is None:
            raise ValueError("Invalid backup request.")
        return match.end()

    position = skip_space(0)
    if text[position : position + 1] != "{":
        raise ValueError("Invalid backup request.")
    position += 1
    result: dict[str, str] = {}
    while True:
        position = skip_space(position)
        if len(result) >= len(limits) or text[position : position + 1] != '"':
            raise ValueError("Invalid backup request.")
        # All allowed ASCII field names fit even when every character is escaped.
        key, end = decoder.raw_decode(text[position : position + 128])
        if key not in limits or key in result:
            raise ValueError("Invalid backup request.")
        position = skip_space(position + end)
        if text[position : position + 1] != ":":
            raise ValueError("Invalid backup request.")
        position = skip_space(position + 1)
        if text[position : position + 1] != '"':
            raise ValueError("Invalid backup request.")
        value, position = decoder.raw_decode(text, position)
        if len(value) > limits[key]:
            raise ValueError("Invalid backup request.")
        result[key] = value
        position = skip_space(position)
        token = text[position : position + 1]
        position += 1
        if token == "}":
            if set(result) != set(limits) or skip_space(position) != len(text):
                raise ValueError("Invalid backup request.")
            return result
        if token != ",":
            raise ValueError("Invalid backup request.")
