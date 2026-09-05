"""Rate limiting for AI-triggering endpoints (A14).

API_CONTRACTS requires AI endpoints to be rate-limited but names no numbers, so
the limits are configuration (`AI_RATE_LIMIT_PER_HOUR`, `AI_RATE_LIMIT_PER_MINUTE`)
with the defaults recorded in the plan: 10/hour and 3/minute.

Why not slowapi, which the plan named
--------------------------------------
slowapi resolves its key function inside a decorator that runs *before* FastAPI's
dependency graph, so keying per user would mean reading the `sub` claim out of a
token that has not been verified yet. Rate limiting on attacker-controlled input
is a poor trade: a forged `sub` lets a caller choose which bucket to spend, and
spending a victim's bucket is a denial-of-service primitive. This limiter runs as
a dependency, after authentication, so the key is always a verified user id.

Counting is non-destructive
---------------------------
Two rules with different windows share one event log per key. An earlier version
pruned the log while counting, which meant checking the 60-second rule deleted
events the 3600-second rule still needed — layered limits silently leaked, and
spacing requests 70 seconds apart defeated the hourly limit entirely. Reads now
count without mutating; pruning happens only on write, bounded by the longest
window the caller actually uses.

Scope
-----
State is per process. That is correct for the MVP's single API container and
becomes wrong the moment there are two: N replicas allow N times the limit. The
storage interface is deliberately narrow so a shared backend can replace it
without touching call sites.
"""

from __future__ import annotations

import threading
import time
from bisect import bisect_right
from collections import defaultdict, deque
from collections.abc import Callable

from app.common.errors import RateLimitedError

# Keys idle for longer than this are dropped, so a long-running process does not
# accumulate one deque per user who ever made a request.
_IDLE_EVICTION_SECONDS = 3600
_SWEEP_EVERY_SECONDS = 300


class InMemorySlidingWindow:
    """A sliding-window event log held in this process's memory.

    Events per key are appended in monotonically increasing time order, so a
    binary search can count a window without walking or mutating the log.
    """

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._last_sweep = 0.0

    def hits(self, key: str, window_seconds: float, now: float) -> int:
        """Count events inside the window. Never mutates - see the module docstring."""
        with self._lock:
            events = self._events.get(key)
            if not events:
                return 0
            cutoff = now - window_seconds
            return len(events) - bisect_right(events, cutoff)

    def oldest_in_window(self, key: str, window_seconds: float, now: float) -> float | None:
        with self._lock:
            events = self._events.get(key)
            if not events:
                return None
            cutoff = now - window_seconds
            index = bisect_right(events, cutoff)
            return events[index] if index < len(events) else None

    def record(self, key: str, now: float, retain_seconds: float) -> None:
        """Append an event and discard anything older than the longest live window."""
        with self._lock:
            events = self._events[key]
            events.append(now)

            cutoff = now - retain_seconds
            while events and events[0] <= cutoff:
                events.popleft()

            self._maybe_sweep(now)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._last_sweep = 0.0

    def _maybe_sweep(self, now: float) -> None:
        if now - self._last_sweep < _SWEEP_EVERY_SECONDS:
            return
        self._last_sweep = now
        stale = [
            key
            for key, events in self._events.items()
            if not events or events[-1] <= now - _IDLE_EVICTION_SECONDS
        ]
        for key in stale:
            del self._events[key]


class RateLimiter:
    """Applies one or more (limit, window) rules to a key.

    The clock is injectable so tests can assert window behaviour without sleeping:
    a limiter tested with `time.sleep` is slow and only ever samples one point on
    the curve.
    """

    def __init__(
        self,
        storage: InMemorySlidingWindow | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.storage = storage or InMemorySlidingWindow()
        self._clock = clock

    def check(self, key: str, rules: list[tuple[int, int]]) -> None:
        """Raise :class:`RateLimitedError` if any rule is already satisfied.

        `rules` is a list of ``(limit, window_seconds)``. Every rule is checked
        before anything is recorded, so a request refused by the minute limit does
        not quietly consume an hourly slot - otherwise a client retrying in a tight
        loop would hold its own window open and never recover.
        """
        if not rules:
            return

        now = self._clock()

        for limit, window in rules:
            if limit <= 0:
                raise RateLimitedError("This operation is currently disabled.")
            if self.storage.hits(key, window, now) >= limit:
                oldest = self.storage.oldest_in_window(key, window, now)
                retry_after = max(1, int(window - (now - oldest))) if oldest else window
                raise RateLimitedError(
                    "Too many requests. Please try again shortly.",
                    details={"retry_after_seconds": retry_after},
                )

        self.storage.record(key, now, retain_seconds=max(window for _, window in rules))

    def reset(self) -> None:
        self.storage.reset()


# One limiter per process. Module-level so the limit survives across requests;
# swap the storage for a shared backend when there is more than one replica.
ai_limiter = RateLimiter()
