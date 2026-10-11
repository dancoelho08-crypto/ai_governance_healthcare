"""The in-process sliding-window rate limiter, shared by the API's middleware and the
agent API's guard (#164)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque

log = logging.getLogger("chai")


class SlidingWindowRateLimiter:
    """Per-key request accounting over a moving window.

    Named for what it does: entries are discarded once they fall outside
    ``window_seconds`` of *now*, so the window slides. A true fixed window
    resets on a wall-clock boundary and lets a caller spend two full
    allowances across it.

    **In-process, and so per-replica.** With N replicas behind a load
    balancer the effective ceiling is N x ``max_requests``, because nothing is
    shared between them. That is a deliberate trade: a shared counter means
    Redis, or a round trip to PostgreSQL on every request, and this limiter
    exists to blunt a runaway client rather than to meter an API. Size the
    limit for one replica and treat the total as approximate. The hard
    protections are elsewhere -- the body cap below, the SSE stream cap, and
    the network isolation that keeps unauthenticated traffic out entirely.

    **Bounded memory.** Keys are swept once per window. Without that the
    dictionary grew by one entry for every distinct identity or source
    address ever seen and never shrank, which for IP-keyed traffic is an
    attacker-controlled leak: 200k addresses meant 200k permanently retained
    keys.
    """

    def __init__(
        self,
        window_seconds: int,
        max_requests: int,
        *,
        max_keys: int = 50_000,
    ) -> None:
        self.window_seconds = max(1, window_seconds)
        self.max_requests = max(1, max_requests)
        self.max_keys = max(1, max_keys)
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()
        self._last_sweep = time.monotonic()

    def _sweep(self, now: float) -> None:
        """Drop keys with nothing left inside the window. Caller holds the lock."""
        cutoff = now - self.window_seconds
        stale = [
            key
            for key, bucket in self._events.items()
            if not bucket or bucket[-1] <= cutoff
        ]
        for key in stale:
            del self._events[key]
        self._last_sweep = now
        if len(self._events) > self.max_keys:
            # Everything here is live traffic inside one window, so this is a
            # flood from many sources rather than accumulated residue. Say so
            # once per sweep; the limiter keeps working.
            log.warning(
                "rate limiter is tracking %d active keys (above max_keys=%d); "
                "this looks like distributed traffic rather than one client",
                len(self._events),
                self.max_keys,
            )

    async def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self._lock:
            if now - self._last_sweep >= self.window_seconds:
                self._sweep(now)
            bucket = self._events[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(now)
            return True

    @property
    def tracked_keys(self) -> int:
        return len(self._events)
