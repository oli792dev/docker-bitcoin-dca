"""Durable fiat observation and normalized history boundaries."""

from typing import Literal, NotRequired, Protocol, TypedDict


class DepositSettings(TypedDict):
    exchange: str
    quote: str
    account_identity: NotRequired[str]


class FiatDeposit(TypedDict):
    id: str
    timestamp: int
    symbol: str
    amount: str
    status: str
    fee: NotRequired[str]


class DepositActivity(TypedDict):
    id: str
    exchange: str
    accountIdentity: NotRequired[str]
    depositStatus: Literal["confirmed"]
    row: dict[str, str]


class PendingDeposit(TypedDict):
    start: str
    balanceBaseline: NotRequired[str]
    bookedBaseline: NotRequired[str]


class FiatObservation(TypedDict):
    identity: list[str]
    checkedAt: str
    balance: str
    booked: NotRequired[str]
    historyStartAt: str
    confirmed: NotRequired[list[DepositActivity]]
    pending: NotRequired[PendingDeposit]


class FundingState(TypedDict):
    fiat_observation: NotRequired[FiatObservation]


class DepositHistoryExchange(Protocol):
    def fiat_deposits(self, currency: str, start_ms: int = 0, end_ms: int | None = None) -> list[FiatDeposit]: ...
