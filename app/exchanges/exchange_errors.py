"""Only positively classified exchange rejections may clear a pending action."""

import requests


class DefinitiveRejection(requests.RequestException):
    pass


class UncertainWithdrawalError(ValueError):
    """A financial submission is unresolved and requires verification."""


class WithdrawalNotReady(ValueError):
    """A withdrawal cannot yet cover its fee; no request was submitted."""
