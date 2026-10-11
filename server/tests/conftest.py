"""Shared fixtures.

Two kinds of test live here. The pure ones -- deep-merge semantics, identity
header parsing -- need nothing but Python and always run. The rest need a real
PostgreSQL, because what they are testing *is* the database's behavior: a row
lock serializing two concurrent PATCHes, a unique constraint producing one 409,
a trigger refusing an UPDATE. A fake would test the fake.

Run everything with::

    docker run -d --name chai-test-db -p 55432:5432 \
      -e POSTGRES_PASSWORD=test -e POSTGRES_DB=chai_test postgres:16-alpine
    TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/chai_test \
      pytest

Without ``TEST_DATABASE_URL`` the database tests skip and say why.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import asyncpg
import pytest
from app.config import Settings
from app.db import Database
from app.main import create_app
from app.roles import provision
from httpx import ASGITransport, AsyncClient

DB_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or ""

# TEST_APP_ROLE=1 runs the WHOLE suite with the API connected as the restricted
# serving role (app/roles.py), the way a real deployment does (#48). The owner
# only prepares the schema and the role, and resets the data between tests. CI
# runs the suite both ways: as the owner (what a single-role setup does) and as
# the restricted role, because "the role can do its job" is only shown by doing it.
APP_ROLE_MODE = bool(os.getenv("TEST_APP_ROLE"))
SUITE_ROLE = "chai_app_suite"
SUITE_PASSWORD = "suite-role-password-0123456789"


def _url_as(role: str, password: str) -> str:
    parts = urlsplit(DB_URL)
    host = parts.netloc.rsplit("@", 1)[-1]
    netloc = f"{quote(role, safe='')}:{quote(password, safe='')}@{host}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


APP_ROLE_URL = _url_as(SUITE_ROLE, SUITE_PASSWORD) if DB_URL else ""

# CI sets REQUIRE_TESTS=1. A test that cannot run then FAILS instead of skipping,
# because a skip reports as a pass: that is how CI once ran none of these (#32).
REQUIRE_TESTS = bool(os.getenv("REQUIRE_TESTS"))

requires_db = pytest.mark.skipif(
    not DB_URL and not REQUIRE_TESTS,
    reason="set TEST_DATABASE_URL to a PostgreSQL this test may TRUNCATE",
)

TEST_EMAIL = "tester@hospital.example"
TEST_HEADERS = {"X-Forwarded-Email": TEST_EMAIL, "X-Forwarded-User": "Test Er"}


def make_settings(**overrides: object) -> Settings:
    """Settings for a test, with the environment deliberately ignored.

    Reading the real environment here would make a developer's local
    ``IDENTITY_MODE`` change what the tests assert.
    """
    base: dict[str, object] = {
        "database_url": DB_URL,
        "db_pool_min": 2,
        "db_pool_max": 12,
        "identity_mode": "proxy",
        "identity_header": "X-Forwarded-Email",
        "identity_name_header": "X-Forwarded-User",
        "run_migrations": True,
        "sse_keepalive_seconds": 1.0,
        "version": "test",
    }
    if APP_ROLE_MODE:
        # As deployed: the API holds only the restricted role and never migrates.
        base.update(
            database_url="", app_database_url=APP_ROLE_URL, run_migrations=False
        )
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


async def _prepare_owner_side() -> None:
    """What the migrate job does: the schema, and the restricted role."""
    owner = Database(DB_URL, min_size=1, max_size=1)
    await owner.connect()
    try:
        await owner.migrate()
        async with owner.acquire() as conn:
            await provision(conn, SUITE_ROLE, SUITE_PASSWORD)
    finally:
        await owner.close()


@pytest.fixture(scope="session", autouse=True)
def app_role_prepared() -> None:
    # Always, not only in app-role mode: the schema and the role are cheap and
    # idempotent, and tests that start a restricted app of their own need both.
    if DB_URL:
        asyncio.run(_prepare_owner_side())


@contextlib.asynccontextmanager
async def owner_connection() -> AsyncIterator[asyncpg.Connection]:
    """A connection as the table OWNER, whichever role the API under test uses.

    For tests of the triggers themselves (what the database refuses even the
    owner). The restricted role is refused those statements earlier, by a
    privilege check, which tests/test_roles.py covers; these tests need to reach
    the trigger.
    """
    conn = await asyncpg.connect(DB_URL)
    try:
        yield conn
    finally:
        await conn.close()


# The migration that creates and seeds the retirement rules (CHAI's four). It is
# idempotent, so running it again over emptied tables puts back exactly the seeded
# state, with no second copy of the seed here to drift from it.
RETIREMENT_MIGRATION = (
    Path(__file__).resolve().parent.parent / "migrations" / "010_retirement_rules.sql"
)


async def reset_retirement_rules(conn: asyncpg.Connection) -> None:
    """Put the retirement rules and their history back to what 010 seeds."""
    await conn.execute(
        "TRUNCATE retirement_rule, retirement_rule_change RESTART IDENTITY"
    )
    await conn.execute(RETIREMENT_MIGRATION.read_text(encoding="utf-8"))


DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[2] / "docs" / "app" / "manifest.json"
)


async def reset_vocabulary(conn: asyncpg.Connection) -> None:
    """Load the default build's vocabulary, as the migrate job does (D-89)."""
    from app.retirement import parse_manifest, sync_vocabulary

    manifest = parse_manifest(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    await sync_vocabulary(conn, manifest)


async def reset_database() -> None:
    """Empty every table, as the OWNER, whichever role the API under test uses."""
    conn = await asyncpg.connect(DB_URL)
    try:
        # project_version is listed explicitly: it has no foreign key to
        # projects, on purpose (002_versions.sql), so CASCADE does not reach it and
        # its rows survived between tests. A snapshot left behind by an earlier
        # test collides with the new rev 1 of a project reusing the same id, and
        # the ON CONFLICT swallows it, so the leak showed up as a test that
        # passed or failed depending on what ran before it.
        #
        # TRUNCATE rather than DELETE so the bigserial in project_log restarts
        # and assertions about order are unaffected by earlier tests. It also
        # does not fire the row-level triggers that (correctly) refuse DELETE on
        # project_version.
        await conn.execute(
            "TRUNCATE access_event, project_deletion, project_version, project_log, "
            "projects, retention_hold, disposal_run, principals, agent_token "
            "RESTART IDENTITY CASCADE"
        )
        await conn.execute(
            "UPDATE retention_policy SET record_years = 6, read_trail_years = 6"
        )
        await reset_retirement_rules(conn)
        await reset_vocabulary(conn)
    finally:
        await conn.close()


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """An HTTP client wired straight to the ASGI app, with lifespan run.

    ``httpx.ASGITransport`` does not run startup or shutdown on its own, so the
    lifespan context is entered by hand. Without it there is no pool, no
    migration and no event broker.
    """
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        # Every test starts from an empty database.
        await reset_database()
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://api.test", headers=TEST_HEADERS
        ) as http:
            http.app = app  # type: ignore[attr-defined]
            yield http


@pytest.fixture
async def project(client: AsyncClient) -> str:
    """One project with a small nested document, ready to patch."""
    pid = "ptest001"
    response = await client.post(
        f"/api/projects/{pid}",
        json={
            "meta": {"solution": "Sepsis alert", "org": "St Elsewhere"},
            "items": {
                "s4-1": {"status": "met", "evidence": "validation report"},
                "s4-2": {"status": "partial", "owner": "A. Reviewer"},
            },
            "metrics": [
                {"cat": "Fairness & equity", "name": "TPR gap", "value": "0.04"}
            ],
            "archived": False,
        },
    )
    assert response.status_code == 201
    return pid
