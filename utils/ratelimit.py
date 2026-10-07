"""Per-domain throttling shared by all threads in a process."""
from __future__ import annotations

import threading
import time


class DomainRateLimiter:
    def __init__(self, default_interval: float, overrides: dict[str, float] | None = None):
        self.default_interval = default_interval
        self.overrides = overrides or {}
        self._next_allowed: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, domain: str) -> None:
        interval = self.overrides.get(domain, self.default_interval)
        with self._lock:
            now = time.monotonic()
            slot = max(now, self._next_allowed.get(domain, 0.0))
            self._next_allowed[domain] = slot + interval
        delay = slot - time.monotonic()
        if delay > 0:
            time.sleep(delay)
