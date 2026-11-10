"""Read-only permission evidence; never submit probe trades or withdrawals."""

import time

import requests


def check_permissions(api, quote):
    """Distinguish successful reads, explicit denial and unverified financial scopes."""
    result = {
        name: {"status": "unknown", "evidence": "Not verified by a read-only check."}
        for name in ("funds", "orders", "history", "trade", "withdraw")
    }
    end = int(time.time() * 1000)
    probes = {
        "funds": lambda: (api.balance(quote), api.balance("BTC")),
        "orders": api.open_orders,
        "history": lambda: (api.fiat_deposits(quote, end - 86400000, end), api.btc_withdrawals(end - 86400000, end)),
    }
    for name, probe in probes.items():
        try:
            probe()
            result[name] = {"status": "proven", "evidence": "Read-only request succeeded."}
        except (ValueError, RuntimeError, requests.RequestException) as exc:
            # Only an explicit permission denial proves missing access. Outages,
            # unsupported endpoints and malformed replies leave permission unknown.
            denied = getattr(exc, "category", None) == "permission_denied"
            result[name] = {
                "status": "denied" if denied else "unknown",
                "evidence": "Exchange denied permission." if denied else "Read-only request could not verify access.",
            }
    if hasattr(api, "permission_scopes"):
        try:
            scopes = api.permission_scopes()
            if isinstance(scopes, dict):
                for name in result:
                    granted = scopes.get(name)
                    if type(granted) is bool and (not granted or name in ("trade", "withdraw")):
                        result[name] = {
                            "status": "proven" if granted else "denied",
                            "evidence": "Reported by exchange API key metadata.",
                        }
                    elif name == "orders" and granted is not True and result[name]["status"] != "denied":
                        result[name] = {"status": "unknown", "evidence": "Closed-order access could not be verified."}
        except (ValueError, RuntimeError, requests.RequestException):
            if result["orders"]["status"] != "denied":
                result["orders"] = {"status": "unknown", "evidence": "Closed-order access could not be verified."}
    return result
