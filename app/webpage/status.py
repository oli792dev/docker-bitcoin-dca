"""Dashboard status presentation derived from saved account and worker state."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DashboardStatus:
    """Keep the user-facing status label, color and warning consistent."""

    label: str
    tone: Literal["active", "waiting", "error"]
    warning: bool = False


def exchange_check_status(*, startup_delay: bool) -> str:
    """Describe the pending exchange check without implying account failure."""
    return "Waiting for startup delay" if startup_delay else "Waiting for exchange check"


def dashboard_status(
    *,
    balance_matches: bool,
    purchase_status: str,
    live: bool,
    exchange_check_pending: bool,
    startup_delay: bool,
    worker_healthy: bool,
    worker_error: bool,
) -> DashboardStatus:
    """Select a status in priority order without changing trading state."""
    if not worker_healthy:
        return DashboardStatus("Worker unavailable", "error", True)
    if worker_error:
        return DashboardStatus("Account check failed; retrying", "error", True)
    if exchange_check_pending:
        return DashboardStatus(exchange_check_status(startup_delay=startup_delay), "waiting")
    if not balance_matches:
        return DashboardStatus("Account data unavailable", "error", True)
    if purchase_status.startswith(("Waiting", "Checking", "Verifying")) and purchase_status != (
        "Waiting for confirmation that the previous order has ended"
    ):
        label = (
            "Waiting for deposit" if purchase_status == "Waiting until the balance covers an order" else purchase_status
        )
        return DashboardStatus(label, "waiting")
    if not live:
        return DashboardStatus("Simulation", "waiting")
    return DashboardStatus("Bot active", "active")
