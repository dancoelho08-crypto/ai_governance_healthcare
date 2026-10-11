"""What bounds an unauthenticated flood of agent calls (#164, D-89).

The agent routes answer to a bearer token and sit where a front door cannot ask for a
sign-in, so anyone who can reach the path can send a stream of bad tokens. Three
rules keep that from costing anything that lasts, or from touching a real agent:

1. **A token is checked before anything is limited.** The check is one indexed read
   and writes nothing. A request whose token verifies is never counted against the
   address it came from, so a flooded address does not lock out a working agent.
2. **A failure is counted against its source, and against nothing else.** Not against
   the token it named (anyone who learns a public token id could otherwise spend its
   allowance), and only a bounded number are answered: once a source has used up its
   failures for the window, the rest get a 429 with no database write.
3. **A failure is a read-trail row only when it names a token that exists**, and
   then at most ``REFUSAL_ROWS_PER_WINDOW`` per (token id, source) per window. The
   read trail is append-only, so a flood must not be able to grow it: a bad or
   unknown token is never a row. What a flood leaves is one aggregated line in the
   security log per source per window, with the count.

The source is the socket peer, or the address the proxy reported when the peer is a
proxy inside ``TRUSTED_PROXY_CIDR`` (``auth.client_address``): never a header a
client can choose.

State is in process, so with N replicas every ceiling here is N times as large.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .config import Settings
from .ratelimit import SlidingWindowRateLimiter
from .securitylog import SecurityEvent, emit

# Trail rows a source may cause for one token id in one window.
REFUSAL_ROWS_PER_WINDOW = 5
MAX_SOURCES = 50_000


@dataclass
class _Window:
    start: float
    count: int


class FailureTally:
    """Failed calls per source, in fixed windows, with the count kept past the limit."""

    def __init__(self, window_seconds: int, limit: int) -> None:
        self.window = max(1, window_seconds)
        self.limit = max(1, limit)
        self._by_source: dict[str, _Window] = {}

    def charge(self, source: str, now: float) -> tuple[bool, list[tuple[str, int]]]:
        """Count one failure. Returns whether it may be answered with a 401 (and so
        may write a row), and the windows that closed since: ``(source, count)``."""
        closed: list[tuple[str, int]] = []
        if len(self._by_source) > MAX_SOURCES:
            closed += self.flush()
        for key, w in list(self._by_source.items()):
            if now - w.start >= self.window:
                closed.append((key, w.count))
                del self._by_source[key]
        w = self._by_source.setdefault(source, _Window(now, 0))
        w.count += 1
        return w.count <= self.limit, closed

    def flush(self) -> list[tuple[str, int]]:
        closed = [(k, w.count) for k, w in self._by_source.items()]
        self._by_source.clear()
        return closed


class AgentGuard:
    """The limiters of the agent routes, one set per app."""

    def __init__(self, settings: Settings) -> None:
        window = settings.rate_limit_window_seconds
        self.window = window
        self.per_token = SlidingWindowRateLimiter(
            window, settings.agent_rate_limit_max_requests
        )
        self.rows = SlidingWindowRateLimiter(window, REFUSAL_ROWS_PER_WINDOW)
        self.failures = FailureTally(
            window, settings.agent_failure_rate_limit_max_requests
        )
        self.failure_limit = self.failures.limit
        self._announced: dict[str, float] = {}

    def report(self, closed: list[tuple[str, int]]) -> None:
        """One security-log line per source per window that saw a failure."""
        for source, count in closed:
            emit(
                SecurityEvent.AGENT_FAILURES,
                f"{count} failed agent call(s) from {source} in one window",
                source=source,
                count=count,
                limit=self.failure_limit,
                window_seconds=self.window,
                limited=count > self.failure_limit,
            )

    def charge_failure(self, source: str) -> bool:
        allowed, closed = self.failures.charge(source, time.monotonic())
        self.report(closed)
        return allowed

    def flush(self) -> None:
        self.report(self.failures.flush())

    async def allow_token(self, token_id: str) -> bool:
        """The per-token allowance. Only a request whose token verified spends it."""
        if await self.per_token.allow(token_id):
            return True
        now = time.monotonic()
        if now - self._announced.get(token_id, -1e9) >= self.window:
            if len(self._announced) > 10_000:
                self._announced.clear()
            self._announced[token_id] = now
            emit(
                SecurityEvent.RATELIMIT_TRIPPED,
                f"rate limit tripped for agent:{token_id}",
                key=f"agent:{token_id}",
                limit=self.per_token.max_requests,
                window_seconds=self.window,
            )
        return False

    async def may_write_row(self, token_id: str, source: str) -> bool:
        return await self.rows.allow(f"{token_id}|{source}")
