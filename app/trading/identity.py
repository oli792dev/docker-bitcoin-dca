"""Nonsecret credential boundary for account state and activity."""

import hashlib
import json
from typing import Literal, NotRequired, TypedDict


class AccountCredentials(TypedDict):
    exchange: Literal["KRAKEN", "BITVAVO"]
    quote: str
    kraken_api_key: NotRequired[str]
    bitvavo_api_key: NotRequired[str]


def account_identity(settings: AccountCredentials) -> str:
    """Treat a new active API key as a new account; secrets may rotate in place."""
    exchange = settings["exchange"]
    key = settings.get("kraken_api_key", "") if exchange == "KRAKEN" else settings.get("bitvavo_api_key", "")
    payload = json.dumps([exchange, settings["quote"], key], separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
