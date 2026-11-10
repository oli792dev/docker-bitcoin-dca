"""Only positively classified exchange rejections may clear a pending action."""

from typing import Literal

import requests


class ExchangeError(requests.HTTPError):
    def __init__(
        self,
        message: str,
        *,
        code: int | str | None = None,
        category: Literal["permission_denied", "rejected", "uncertain"] = "uncertain",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.category = category


class DefinitiveRejection(ExchangeError):
    def __init__(
        self,
        message: str,
        *,
        code: int | str | None = None,
        category: Literal["permission_denied", "rejected"] = "rejected",
    ) -> None:
        super().__init__(message, code=code, category=category)


class UncertainWithdrawalError(ValueError):
    """A financial submission is unresolved and requires verification."""


class WithdrawalNotReady(ValueError):
    """A withdrawal cannot yet cover its fee; no request was submitted."""
