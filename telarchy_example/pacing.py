"""Interruptible sleeps for responsive shutdown (Ctrl+C / SIGTERM)."""

from __future__ import annotations

import time
from collections.abc import Callable


def sleep_interruptible(
    seconds: float,
    should_stop: Callable[[], bool] | None,
    *,
    chunk_s: float = 0.25,
) -> bool:
    """Sleep up to ``seconds``. Returns True if ``should_stop`` became true first."""
    if seconds <= 0:
        return False
    if should_stop is None:
        time.sleep(seconds)
        return False
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if should_stop():
            return True
        time.sleep(min(chunk_s, deadline - time.monotonic()))
    return False
