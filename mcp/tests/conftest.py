"""Fixtures for the MCP service's tests.

A suite that cannot run FAILS when REQUIRE_TESTS=1 (CI sets it), and never skips: a
skip exits 0 and reads as a pass (#32).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from .harness import FakeAPI, LogSweep, Served

REQUIRE_TESTS = bool(os.getenv("REQUIRE_TESTS"))
DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or ""

requires_db = pytest.mark.skipif(
    not DB_URL and not REQUIRE_TESTS,
    reason="set TEST_DATABASE_URL to a PostgreSQL this test may TRUNCATE",
)


@pytest.fixture
def api() -> Iterator[FakeAPI]:
    fake = FakeAPI()
    with Served(fake.app()) as served:
        fake.served = served
        yield fake


@pytest.fixture
def sweep() -> Iterator[LogSweep]:
    with LogSweep() as handler:
        yield handler
