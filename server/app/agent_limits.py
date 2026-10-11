"""What bounds an unauthenticated flood of agent calls (#164, D-89).

The agent routes answer to a bearer token and sit where a front door cannot ask for a
sign-in, so anyone who can reach the path can send a stream of bad tokens. These rules
keep that from costing anything that lasts, or from touching a real agent:

1. **A token is checked before anything is limited.** The check is one indexed read
   and writes nothing. A request whose token verifies is never counted against the
   address it came from, nor against the failure budgets below, so a flooded address
   does not lock out a working agent.
2. **A failure is counted against its source, and against nothing else.** Not against
   the token it named (anyone who learns a public token id could otherwise spend its
   allowance). Once a source has used up its failures for the window, the rest get a
   429 with no database write. A GLOBAL budget bounds the failures of all sources
   together, so that rotating source keys cannot make the server do unbounded work:
   past it a failure gets a 429 with no per-source accounting at all.
3. **A refusal is a read-trail row only within three small budgets.** The read trail
   is append-only, so a flood must not be able to grow it. A bad or unknown token is
   never a row. A row needs a token that exists, and then: a wrong secret (anybody
   can send one that names a public id) is limited per token id across ALL sources and
   overall; a right secret on a token that stopped working (the person who holds it)
   has its own budget, so a flood of wrong secrets cannot starve it; a project the
   token's owner cannot see has its own. What is not written is counted in one
   security-log line per window.
4. **A person's tokens share one allowance**, so five tokens cannot multiply the work
   a person's calls cost.

The tallies are bounded structures with O(1) work per failure: no scan, no copy. A
background task closes windows every half window and writes the summary, so a burst
is reported when it ends and not when the next failure happens to arrive.

The source is the socket peer, or the address the proxy reported when the peer is a
proxy inside ``TRUSTED_PROXY_CIDR`` (``auth.client_address``): never a header a
client can choose.

State is in process, so with N replicas every ceiling here is N times as large.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import OrderedDict
from collections.abc import Callable
from enum import StrEnum

from .config import Settings
from .ratelimit import SlidingWindowRateLimiter
from .securitylog import SecurityEvent, emit

# Trail rows one token id may cause per window, across every source, by kind.
WRONG_SECRET_ROWS_PER_TOKEN = 10
RIGHT_SECRET_ROWS_PER_TOKEN = 5
NOT_VISIBLE_ROWS_PER_TOKEN = 5
# And all tokens together, by kind.
ROWS_PER_KIND_OVERALL = 100
# Sources and keys a structure will hold; the oldest idle ones go first.
MAX_SOURCES = 10_000
MAX_ROW_KEYS = 10_000
TOP_SOURCES_LOGGED = 10


class FailureVerdict(StrEnum):
    ALLOW = "allow"  # answer 401, and a row may be written within its budget
    SOURCE_LIMITED = "source_limited"  # this source is over its failures: 429
    GLOBAL_LIMITED = "global_limited"  # every source together are over: 429


class RowKind(StrEnum):
    WRONG_SECRET = "wrong_secret"
    RIGHT_SECRET = "right_secret"  # revoked or expired
    NOT_VISIBLE = "not_visible"


_PER_TOKEN = {
    RowKind.WRONG_SECRET: WRONG_SECRET_ROWS_PER_TOKEN,
    RowKind.RIGHT_SECRET: RIGHT_SECRET_ROWS_PER_TOKEN,
    RowKind.NOT_VISIBLE: NOT_VISIBLE_ROWS_PER_TOKEN,
}


class _Counts:
    """A count in a window that started at ``start``."""

    __slots__ = ("count", "start")

    def __init__(self, start: float) -> None:
        self.start = start
        self.count = 0


class FailureTally:
    """Failed calls per source, in fixed windows: bounded, and O(1) per failure."""

    def __init__(
        self,
        window_seconds: int,
        source_limit: int,
        global_limit: int,
        *,
        max_sources: int = MAX_SOURCES,
    ) -> None:
        self.window = max(1, window_seconds)
        self.source_limit = max(1, source_limit)
        self.global_limit = max(1, global_limit)
        self.max_sources = max(1, max_sources)
        # Least recently counted first, so the head is the oldest idle source.
        self._by_source: OrderedDict[str, _Counts] = OrderedDict()
        self._global = _Counts(0.0)
        self._reset_totals()

    def _reset_totals(self) -> None:
        self.failures = 0  # every failure charged since the last summary
        self.limited_sources: set[str] = set()
        self.global_limited = 0
        self.evicted_sources = 0
        self.top: dict[str, int] = {}

    def charge(self, source: str, now: float) -> FailureVerdict:
        if now - self._global.start >= self.window:
            self._global = _Counts(now)
        self._global.count += 1
        self.failures += 1
        if self._global.count > self.global_limit:
            self.global_limited += 1
            return FailureVerdict.GLOBAL_LIMITED
        w = self._by_source.get(source)
        if w is None:
            while len(self._by_source) >= self.max_sources:
                self._by_source.popitem(last=False)  # the oldest idle source
                self.evicted_sources += 1
            w = self._by_source[source] = _Counts(now)
        elif now - w.start >= self.window:
            self._bank(source, w)
            w.start, w.count = now, 0  # its window closed: a new one begins
        w.count += 1
        self._by_source.move_to_end(source)
        if w.count > self.source_limit:
            self.limited_sources.add(source)
            return FailureVerdict.SOURCE_LIMITED
        return FailureVerdict.ALLOW

    def _bank(self, source: str, w: _Counts) -> None:
        """Remember a closed window's count for the summary's top list."""
        if w.count > self.top.get(source, 0):
            self.top[source] = w.count
        if len(self.top) > 4 * TOP_SOURCES_LOGGED:
            keep = sorted(self.top.items(), key=lambda kv: -kv[1])
            self.top = dict(keep[: 2 * TOP_SOURCES_LOGGED])

    def close_expired(self, now: float, *, everything: bool = False) -> None:
        """Drop the sources whose window has closed (all of them at shutdown). Called
        once per half window by the guard's task, never per failure."""
        for source in [
            s
            for s, w in self._by_source.items()
            if everything or now - w.start >= self.window
        ]:
            self._bank(source, self._by_source.pop(source))

    def summary(self) -> dict[str, object] | None:
        """What happened since the last summary, or None if nothing did."""
        if not self.failures and not self.evicted_sources:
            return None
        top = sorted(self.top.items(), key=lambda kv: -kv[1])[:TOP_SOURCES_LOGGED]
        out: dict[str, object] = {
            "failures": self.failures,
            "limited_sources": len(self.limited_sources),
            "global_limited": self.global_limited,
            "evicted_sources": self.evicted_sources,
            "top": [{"source": s, "count": n} for s, n in top],
        }
        self._reset_totals()
        return out

    @property
    def tracked(self) -> int:
        return len(self._by_source)


class RowBudget:
    """How many read-trail rows of one kind may be written in a window: per token id
    (across every source) and overall. Bounded by ``max_keys``."""

    def __init__(
        self,
        window_seconds: int,
        per_key: int,
        overall: int,
        *,
        max_keys: int = MAX_ROW_KEYS,
    ) -> None:
        self.window = max(1, window_seconds)
        self.per_key = per_key
        self.overall = overall
        self.max_keys = max_keys
        self._by_key: OrderedDict[str, _Counts] = OrderedDict()
        self._all = _Counts(0.0)
        self.suppressed = 0

    def allow(self, key: str, now: float) -> bool:
        if now - self._all.start >= self.window:
            self._all = _Counts(now)
        w = self._by_key.get(key)
        if w is None:
            while len(self._by_key) >= self.max_keys:
                self._by_key.popitem(last=False)
            w = self._by_key[key] = _Counts(now)
        elif now - w.start >= self.window:
            w.start, w.count = now, 0
        self._by_key.move_to_end(key)
        if w.count >= self.per_key or self._all.count >= self.overall:
            self.suppressed += 1
            return False
        w.count += 1
        self._all.count += 1
        return True

    def close_expired(self, now: float) -> None:
        for key in [k for k, w in self._by_key.items() if now - w.start >= self.window]:
            del self._by_key[key]

    @property
    def tracked(self) -> int:
        return len(self._by_key)


class AgentGuard:
    """The limiters of the agent routes, one set per app."""

    def __init__(
        self,
        settings: Settings,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        window = settings.rate_limit_window_seconds
        self.window = window
        self._clock = clock
        self.per_token = SlidingWindowRateLimiter(
            window, settings.agent_rate_limit_max_requests
        )
        self.per_user = SlidingWindowRateLimiter(
            window, settings.agent_user_rate_limit_max_requests
        )
        self.failures = FailureTally(
            window,
            settings.agent_failure_rate_limit_max_requests,
            settings.agent_global_failure_rate_limit_max_requests,
        )
        self.rows = {
            kind: RowBudget(window, per_token, ROWS_PER_KIND_OVERALL)
            for kind, per_token in _PER_TOKEN.items()
        }
        self._announced: dict[str, float] = {}
        self._last_summary = clock()
        self._task: asyncio.Task[None] | None = None

    # -- the three decisions get_agent makes ------------------------------------

    def charge_failure(self, source: str) -> FailureVerdict:
        return self.failures.charge(source, self._clock())

    def may_write_row(self, kind: RowKind, token_id: str) -> bool:
        return self.rows[kind].allow(token_id, self._clock())

    async def allow_token(self, token_id: str) -> bool:
        """The per-token allowance. Only a request whose token verified spends it."""
        if await self.per_token.allow(token_id):
            return True
        self._announce(f"agent:{token_id}", self.per_token.max_requests)
        return False

    async def allow_user(self, user_id: str) -> bool:
        """The allowance a person's tokens share (only verified calls spend it)."""
        if await self.per_user.allow(user_id):
            return True
        self._announce(f"agent-user:{user_id}", self.per_user.max_requests)
        return False

    def _announce(self, key: str, limit: int) -> None:
        """One ratelimit.tripped line per key per window."""
        now = self._clock()
        if now - self._announced.get(key, -1e9) < self.window:
            return
        if len(self._announced) > MAX_ROW_KEYS:
            self._announced.clear()
        self._announced[key] = now
        emit(
            SecurityEvent.RATELIMIT_TRIPPED,
            f"rate limit tripped for {key}",
            key=key,
            limit=limit,
            window_seconds=self.window,
        )

    # -- the summary line -------------------------------------------------------------

    def flush(self, *, everything: bool = False) -> None:
        """Close the windows that are over and, once a window, write the summary line
        if anything happened. Called every half window by the task, and at shutdown."""
        now = self._clock()
        self.failures.close_expired(now, everything=everything)
        for budget in self.rows.values():
            budget.close_expired(now)
        if not everything and now - self._last_summary < self.window:
            return  # one summary per window
        self._last_summary = now
        summary = self.failures.summary()
        suppressed = {k.value: b.suppressed for k, b in self.rows.items()}
        if summary is None and not any(suppressed.values()):
            return
        for budget in self.rows.values():
            budget.suppressed = 0
        summary = summary or {"failures": 0}
        emit(
            SecurityEvent.AGENT_FAILURES,
            f"{summary['failures']} failed agent call(s) in a window"
            + (
                f"; {sum(suppressed.values())} trail row(s) not written"
                if any(suppressed.values())
                else ""
            ),
            window_seconds=self.window,
            source_limit=self.failures.source_limit,
            global_limit=self.failures.global_limit,
            rows_not_written=suppressed,
            **summary,
        )

    def start(self) -> None:
        """Start the task that writes the summary at the window's close."""
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        interval = max(0.5, self.window / 2)
        while True:
            await asyncio.sleep(interval)
            self.flush()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.flush(everything=True)
