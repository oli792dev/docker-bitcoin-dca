"""Coordinate process signals without interrupting persisted financial operations."""

import logging
import signal
from contextlib import contextmanager
from threading import Event

LOG = logging.getLogger("bitcoin-dca.lifecycle")


@contextmanager
def shutdown_signals(worker):
    stop = Event()
    previous = {}

    def request_stop(signum, frame):
        if not stop.is_set():
            LOG.info("Container stop requested; finishing active account operation")
            worker.stop.set()
            stop.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, request_stop)
    try:
        yield stop
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
