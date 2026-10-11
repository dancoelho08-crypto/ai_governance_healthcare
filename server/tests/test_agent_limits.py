"""The structures that bound an unauthenticated flood of agent calls (#164, D-89).

A flood of bad tokens must cost the server O(1) work per request and a bounded amount
of memory and log, whatever it varies: the source address, the token id, the pace.
These test the structures themselves, with a clock they control; test_agent_api.py
tests what the routes do with them.
"""

from __future__ import annotations

import asyncio
import io
import json
import time

from app.agent_limits import (
    MAX_SOURCES,
    AgentGuard,
    FailureTally,
    FailureVerdict,
    RowBudget,
)
from app.main import configure_logging
from app.ratelimit import SlidingWindowRateLimiter

from .conftest import make_settings


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def captured(run) -> list[dict]:
    buffer = io.StringIO()
    configure_logging("info", "json", stream=buffer)
    try:
        run()
    finally:
        configure_logging("info", "json", stream=io.StringIO())
    return [json.loads(x) for x in buffer.getvalue().splitlines() if x.startswith("{")]


def guard(clock: Clock, **overrides) -> AgentGuard:
    base = {"agent_id_secret": "k" * 40}
    return AgentGuard(make_settings(**{**base, **overrides}), clock=clock)


# --- cost: O(1) per failure, bounded memory ---------------------------------------------


def test_a_hundred_thousand_sources_cost_a_bounded_time_and_memory() -> None:
    tally = FailureTally(60, 30, 10**9)
    worst = 0.0
    started = time.perf_counter()
    for i in range(100_000):
        t0 = time.perf_counter()
        tally.charge(f"10.{i >> 16}.{(i >> 8) & 255}.{i & 255}", 1000.0)
        worst = max(worst, time.perf_counter() - t0)
        assert tally.tracked <= MAX_SOURCES
    total = time.perf_counter() - started
    # Generous bounds, for a slow CI runner: the old per-failure scan took seconds in
    # total and milliseconds a call at this size, and grew with the table.
    assert total < 5.0, total
    assert worst < 0.05, worst
    assert tally.tracked == MAX_SOURCES
    assert tally.evicted_sources == 100_000 - MAX_SOURCES


def test_the_table_never_exceeds_its_cap_and_evicts_the_oldest_idle() -> None:
    tally = FailureTally(60, 30, 10**9, max_sources=20)
    for i in range(100):
        tally.charge(f"s{i}", 1000.0)
        assert tally.tracked <= 20
    assert set(tally._by_source) == {f"s{i}" for i in range(80, 100)}
    assert tally.evicted_sources == 80


def test_an_active_attackers_bucket_survives_the_evictions_it_causes() -> None:
    tally = FailureTally(60, 5, 10**9, max_sources=20)
    verdicts = []
    for i in range(500):
        verdicts.append(tally.charge("attacker", 1000.0))  # keeps being the freshest
        tally.charge(f"noise{i}", 1000.0)  # and churns the table around it
    assert verdicts[:5] == [FailureVerdict.ALLOW] * 5
    assert set(verdicts[5:]) == {FailureVerdict.SOURCE_LIMITED}  # never reset to zero
    assert tally.tracked <= 20 and "attacker" in tally._by_source


def test_a_window_that_closes_starts_again() -> None:
    tally = FailureTally(60, 3, 10**9)
    assert [tally.charge("a", 1000.0) for _ in range(5)][3:] == [
        FailureVerdict.SOURCE_LIMITED
    ] * 2
    assert tally.charge("a", 1000.0 + 59) is FailureVerdict.SOURCE_LIMITED
    assert tally.charge("a", 1000.0 + 61) is FailureVerdict.ALLOW


def test_past_the_global_budget_nothing_is_accounted_per_source() -> None:
    tally = FailureTally(60, 5, 50)
    verdicts = [tally.charge(f"src{i}", 1000.0) for i in range(1000)]
    assert verdicts.count(FailureVerdict.ALLOW) == 50
    assert verdicts.count(FailureVerdict.GLOBAL_LIMITED) == 950
    assert tally.tracked == 50  # the rest never entered the table
    # The budget is per window: it comes back.
    assert tally.charge("late", 1000.0 + 61) is FailureVerdict.ALLOW


# --- the summary: one line, at window close, with a clock -------------------------------


def test_a_flood_of_sources_is_one_log_line_not_one_per_source() -> None:
    clock = Clock()
    g = guard(clock, agent_global_failure_rate_limit_max_requests=10**9)

    def run() -> None:
        for i in range(MAX_SOURCES + 5_000):
            g.charge_failure(f"10.{i >> 16}.{(i >> 8) & 255}.{i & 255}")
        clock.now += 61
        g.flush()

    lines = [x for x in captured(run) if x.get("event") == "agent.failures"]
    assert len(lines) == 1
    assert lines[0]["failures"] == MAX_SOURCES + 5_000
    assert lines[0]["evicted_sources"] == 5_000
    assert len(lines[0]["top"]) <= 10


def test_the_summary_is_written_when_the_window_closes_and_not_before() -> None:
    clock = Clock()
    g = guard(clock, agent_failure_rate_limit_max_requests=3)
    seen: list[int] = []

    def run() -> None:
        for _ in range(8):
            g.charge_failure("203.0.113.9")
        clock.now += 30
        g.flush()  # half a window: nothing yet
        seen.append(len(buffer.getvalue()))
        clock.now += 31
        g.flush()  # the window has closed
        g.flush()  # and nothing is written twice

    buffer = io.StringIO()
    configure_logging("info", "json", stream=buffer)
    try:
        run()
    finally:
        configure_logging("info", "json", stream=io.StringIO())
    lines = [json.loads(x) for x in buffer.getvalue().splitlines() if x.startswith("{")]
    summary = [x for x in lines if x.get("event") == "agent.failures"]
    assert seen == [0]
    assert len(summary) == 1
    assert summary[0]["failures"] == 8 and summary[0]["limited_sources"] == 1
    assert summary[0]["top"] == [{"source": "203.0.113.9", "count": 8}]


async def test_the_task_writes_the_summary_at_the_window_close_by_itself() -> None:
    """No further failure arrives, and nothing shuts down: the line still appears."""
    g = AgentGuard(make_settings(agent_id_secret="k" * 40, rate_limit_window_seconds=1))
    buffer = io.StringIO()
    configure_logging("info", "json", stream=buffer)
    try:
        g.start()
        for _ in range(5):
            g.charge_failure("203.0.113.7")
        await asyncio.sleep(2.2)
        text = buffer.getvalue()
    finally:
        await g.stop()
        configure_logging("info", "json", stream=io.StringIO())
    assert text.count('"event": "agent.failures"') == 1, text
    assert '"failures": 5' in text


async def test_stopping_writes_what_is_still_open() -> None:
    g = AgentGuard(make_settings(agent_id_secret="k" * 40))  # a 60 second window
    buffer = io.StringIO()
    configure_logging("info", "json", stream=buffer)
    try:
        g.start()
        g.charge_failure("203.0.113.8")
        assert '"agent.failures"' not in buffer.getvalue()
        await g.stop()
        text = buffer.getvalue()
    finally:
        configure_logging("info", "json", stream=io.StringIO())
    assert text.count('"event": "agent.failures"') == 1 and '"failures": 1' in text


# --- the row budgets ---------------------------------------------------------------------


def test_a_row_budget_is_per_key_and_overall_and_comes_back() -> None:
    budget = RowBudget(60, per_key=3, overall=10)
    assert [budget.allow("t1", 1000.0) for _ in range(5)] == [True] * 3 + [False] * 2
    assert [budget.allow(f"k{i}", 1000.0) for i in range(20)].count(True) == 7
    assert budget.suppressed == 2 + 13
    assert budget.allow("t1", 1000.0 + 61) is True


def test_a_row_budget_holds_a_bounded_number_of_keys() -> None:
    budget = RowBudget(60, per_key=1, overall=10**9, max_keys=50)
    for i in range(1000):
        budget.allow(f"k{i}", 1000.0)
        assert budget.tracked <= 50


# --- the sliding-window limiter's own memory bound --------------------------------------


async def test_the_limiter_sweeps_the_keys_a_window_leaves_behind() -> None:
    limiter = SlidingWindowRateLimiter(1, 5)
    for i in range(1000):
        await limiter.allow(f"key{i}")
    assert limiter.tracked_keys == 1000
    await asyncio.sleep(1.2)
    await limiter.allow("fresh")
    assert limiter.tracked_keys <= 2
