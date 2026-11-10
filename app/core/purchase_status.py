"""Stable purchase state codes and their default display labels."""

from enum import StrEnum


class PurchaseStatus(StrEnum):
    UNKNOWN = "unknown"
    STARTUP_DELAY = "startup_delay"
    EXCHANGE_CHECK = "exchange_check"
    OPEN_TRANSACTIONS = "open_transactions"
    VERIFYING_DEPOSIT = "verifying_deposit"
    MARKET_UNAVAILABLE = "market_unavailable"
    WAITING_DEPOSIT = "waiting_deposit"
    SCHEDULED = "scheduled"
    DUE = "due"
    PAUSED = "paused"
    SUBMITTING = "submitting"
    VERIFYING_ORDER = "verifying_order"
    REJECTED = "purchase_rejected"


PURCHASE_LABELS = {
    PurchaseStatus.UNKNOWN: "Schedule pending",
    PurchaseStatus.STARTUP_DELAY: "Waiting for startup delay",
    PurchaseStatus.EXCHANGE_CHECK: "Waiting for exchange check",
    PurchaseStatus.OPEN_TRANSACTIONS: "Waiting for open exchange orders or withdrawals",
    PurchaseStatus.VERIFYING_DEPOSIT: "Verifying deposit",
    PurchaseStatus.MARKET_UNAVAILABLE: "Waiting for market status: {detail}",
    PurchaseStatus.WAITING_DEPOSIT: "Waiting for deposit",
    PurchaseStatus.SCHEDULED: "Scheduled",
    PurchaseStatus.DUE: "Due now",
    PurchaseStatus.PAUSED: "Transactions paused",
    PurchaseStatus.SUBMITTING: "Submitting the order and waiting for its status check",
    PurchaseStatus.VERIFYING_ORDER: "Waiting for confirmation that the previous order has ended",
    PurchaseStatus.REJECTED: "Purchase rejected; check exchange permissions, balance and order limits.",
}
