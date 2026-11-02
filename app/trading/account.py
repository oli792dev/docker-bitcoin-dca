"""One account lock, independent of the engine and HTTP implementation."""

from functools import wraps
from threading import RLock

ACCOUNT_LOCK = RLock()


def serialized(function):
    @wraps(function)
    def locked(*args, **kwargs):
        with ACCOUNT_LOCK:
            return function(*args, **kwargs)

    return locked
