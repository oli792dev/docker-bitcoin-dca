"""Dashboard status presentation derived from saved account and worker state."""

from dataclasses import dataclass
from typing import Literal

from app.core.purchase_status import PURCHASE_LABELS, PurchaseStatus


@dataclass(frozen=True)
class DashboardStatus:
    """Keep the user-facing status label, color and warning consistent."""

    label: str
    tone: Literal["active", "waiting", "error"]
    warning: bool = False


def exchange_check_status(*, startup_delay: bool) -> str:
    """Describe the pending exchange check without implying account failure."""
    return PURCHASE_LABELS[PurchaseStatus.STARTUP_DELAY if startup_delay else PurchaseStatus.EXCHANGE_CHECK]


def dashboard_status(
    *,
    balance_matches: bool,
    purchase_status: str,
    live: bool,
    exchange_check_pending: bool,
    startup_delay: bool,
    worker_healthy: bool,
    worker_error: bool,
    financial_error: str | None = None,
    purchase_status_code: str = PurchaseStatus.UNKNOWN,
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
    if financial_error:
        return DashboardStatus(financial_error, "error", True)
    try:
        code = PurchaseStatus(purchase_status_code)
    except ValueError:
        code = PurchaseStatus.UNKNOWN
    if code == PurchaseStatus.UNKNOWN:
        return DashboardStatus(PURCHASE_LABELS[PurchaseStatus.UNKNOWN], "waiting")
    if code == PurchaseStatus.REJECTED:
        return DashboardStatus(purchase_status, "error", True)
    if code in {
        PurchaseStatus.STARTUP_DELAY,
        PurchaseStatus.EXCHANGE_CHECK,
        PurchaseStatus.OPEN_TRANSACTIONS,
        PurchaseStatus.VERIFYING_DEPOSIT,
        PurchaseStatus.MARKET_UNAVAILABLE,
        PurchaseStatus.WAITING_DEPOSIT,
        PurchaseStatus.PAUSED,
    }:
        return DashboardStatus(purchase_status, "waiting")
    if not live:
        return DashboardStatus("Simulation", "waiting")
    return DashboardStatus("Bot active", "active")
