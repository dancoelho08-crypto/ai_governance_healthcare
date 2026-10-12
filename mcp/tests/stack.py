"""The real agent API on a real PostgreSQL, served on a socket, for the MCP tests.

The API is the server's own app (server/app), created the way the server's tests create
it (server/tests/conftest.py, loaded by path so its settings and its database reset
are the same ones). Nothing here fakes the API.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
import httpx

from .harness import Served

SERVER_TESTS = Path(__file__).resolve().parents[2] / "server" / "tests"
SECRET = "agent-id-secret-0123456789-abcdefghijklmnop"
ALICE = "alice@hospital.example"
BOB = "bob@hospital.example"
NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=UTC)


def _load():
    name = "server_tests_conftest"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SERVER_TESTS / "conftest.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


server = _load()
DB_URL = server.DB_URL


def run_sync(coro_fn):
    """Run a coroutine to completion on its own loop, in its own thread, so a test that
    is itself async can call it."""
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = asyncio.run(coro_fn())
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


def reset_database() -> None:
    run_sync(server.reset_database)


@contextmanager
def real_api(**settings: Any):
    """The API on a socket, its clock fixed, and the database emptied."""
    from app.main import create_app

    base: dict[str, Any] = {
        "agent_id_secret": SECRET,
        "rate_limit_max_requests": 100_000,
        "agent_rate_limit_max_requests": 100_000,
        "agent_failure_rate_limit_max_requests": 100_000,
        "agent_global_failure_rate_limit_max_requests": 100_000,
        "agent_user_rate_limit_max_requests": 100_000,
    }
    app = create_app(server.make_settings(**{**base, **settings}))
    app.state.clock = lambda: NOW
    with Served(app) as served:
        reset_database()
        served.app = app  # type: ignore[attr-defined]
        yield served


def session_client(served: Served, email: str) -> httpx.Client:
    """A signed-in person: the identity header the front door would have set."""
    return httpx.Client(
        base_url=served.url,
        headers={"X-Forwarded-Email": email, "X-Forwarded-User": email.split("@")[0]},
    )


def mint(served: Served, email: str = ALICE) -> dict[str, Any]:
    with session_client(served, email) as session:
        response = session.post("/api/agent-tokens", json={"label": "test"})
    assert response.status_code == 201, response.text
    return response.json()


def revoke(served: Served, minted: dict[str, Any], email: str = ALICE) -> None:
    with session_client(served, email) as session:
        response = session.delete(f"/api/agent-tokens/{minted['id']}")
    assert response.status_code in (200, 204), response.text


def sql(statement: str, *args: Any) -> list[dict[str, Any]]:
    async def run() -> list[dict[str, Any]]:
        conn = await asyncpg.connect(DB_URL)
        try:
            return [dict(r) for r in await conn.fetch(statement, *args)]
        finally:
            await conn.close()

    return run_sync(run)


def put_project(pid: str, doc: dict[str, Any], created_by: str = ALICE) -> None:
    sql(
        "INSERT INTO projects (id, doc, created_by, updated_by) "
        "VALUES ($1, $2::jsonb, $3, $3)",
        pid,
        json.dumps({**doc, "archived": False}),
        created_by,
    )


def access(owners=(), writers=(), readers=()) -> dict[str, list[str]]:
    return {"owners": list(owners), "writers": list(writers), "readers": list(readers)}


def project_ref(project_id: str) -> str:
    from app.agent_tokens import project_ref as ref_of

    return ref_of(SECRET, project_id)


def opaque(identity: str) -> str:
    from app.agent_tokens import opaque_id

    return opaque_id(SECRET, identity)
