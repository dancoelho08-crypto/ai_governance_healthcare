"""Servers for the tests: real sockets, real ASGI apps, no mocks of the thing tested.

``Served`` runs any ASGI app under uvicorn in a thread. ``FakeAPI`` is a stand-in for
the agent API for the tests of the MCP service itself (what it forwards, what it
refuses, how it maps a failure): it records every request it receives, headers
included, and answers as told. The tests that need the real API and a real PostgreSQL
are in test_mcp_integration.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import threading
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
import uvicorn
from chai_mcp.asgi import create_app
from chai_mcp.config import Settings
from mcp.client.streamable_http import streamable_http_client
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mcp import ClientSession

PERSON = "u_" + "a" * 32
REF = "pr_" + "b" * 32


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Served:
    """An ASGI app under uvicorn, in a thread of this process."""

    def __init__(self, app: Any) -> None:
        self.port = free_port()
        self.server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=self.port,
                log_level="warning",
                access_log=False,
                lifespan="on",
            )
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> Served:
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            if time.monotonic() > deadline or not self.thread.is_alive():
                raise RuntimeError("the test server did not start")
            time.sleep(0.02)
        return self

    def __exit__(self, *_: object) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def me_body(**over: Any) -> dict[str, Any]:
    return {
        "user": PERSON,
        "token_id": "0123456789abcdef",
        "expires_at": "2026-10-11T20:00:00Z",
        "as_of": "2026-10-11",
        **over,
    }


def project_body(**over: Any) -> dict[str, Any]:
    return {
        "ref": REF,
        "framework": "chai",
        "updated_at": "2026-10-10T09:00:00Z",
        "updated_by": PERSON,
        "people": {
            "owners": [PERSON],
            "writers": [],
            "readers": [],
            "truncated": False,
        },
        "items": [
            {"id": "s1-3", "status": "notmet", "due": "2026-09-01", "overdue": True},
            {"id": "s1-4", "status": "met", "due": None, "overdue": False},
        ],
        "items_truncated": False,
        "gates": [
            {
                "id": "A",
                "decision": "Proceed",
                "decided_on": "2026-08-01",
                "signed_by": PERSON,
                "signed_at": "2026-08-02T00:00:00Z",
            }
        ],
        "supplements": [
            {
                "framework": "optica",
                "enabled": True,
                "items": [
                    {"id": "1-1", "status": "partial", "due": None, "overdue": False}
                ],
            }
        ],
        "has_overdue": True,
        **over,
    }


def portfolio_body(**over: Any) -> dict[str, Any]:
    return {
        "as_of": "2026-10-11",
        "total": 1,
        "limit": 50,
        "offset": 0,
        "next_offset": None,
        "projects": [project_body()],
        **over,
    }


@dataclass
class Seen:
    method: str
    path: str
    query: str
    headers: dict[str, str]


@dataclass
class FakeAPI:
    """Answers as told and records what it was asked."""

    status: int = 200
    body: Any = None
    raw: bytes | None = None
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0
    seen: list[Seen] = field(default_factory=list)
    # A function of the request, when a fixed answer is not enough.
    respond: Callable[[Request], Awaitable[Response]] | None = None
    served: Served | None = None

    async def handle(self, request: Request) -> Response:
        self.seen.append(
            Seen(
                request.method,
                request.url.path,
                request.url.query,
                {k.lower(): v for k, v in request.headers.items()},
            )
        )
        if self.respond is not None:
            return await self.respond(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raw is not None:
            return Response(self.raw, status_code=self.status, headers=self.headers)
        body = self.body
        if body is None:
            name = request.url.path
            if name.endswith("/me"):
                body = me_body()
            elif name.endswith("/portfolio"):
                body = portfolio_body()
            else:
                body = project_body()
        return JSONResponse(body, status_code=self.status, headers=self.headers)

    def app(self) -> Starlette:
        return Starlette(
            routes=[
                Route("/{path:path}", self.handle, methods=["GET", "POST", "DELETE"])
            ]
        )

    @property
    def paths(self) -> list[str]:
        return [s.path for s in self.seen]


def settings_for(api_url: str, **over: Any) -> Settings:
    base: dict[str, Any] = {
        "api_base_url": api_url,
        "allowed_hosts": ("mcp.example.test",),
        "allowed_origins": ("https://chat.example.test",),
        "max_body_bytes": 16 * 1024,
        "timeout_seconds": 5.0,
        "max_in_flight": 16,
    }
    base.update(over)
    return Settings(**base)


@contextlib.contextmanager
def running_service(api_url: str, **over: Any) -> Iterator[Served]:
    with Served(create_app(settings_for(api_url, **over))) as served:
        yield served


@asynccontextmanager
async def session(
    served: Served, token: str | None = "agt_0123456789abcdef.TOKEN", **headers: str
):
    """The SDK's own client, over Streamable HTTP, as a chatbot's would be."""
    sent = {"Host": "mcp.example.test", **headers}
    if token is not None:
        sent["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(headers=sent, timeout=30) as http:
        async with streamable_http_client(f"{served.url}/mcp", http_client=http) as (
            r,
            w,
            _,
        ):
            async with ClientSession(r, w) as client:
                await client.initialize()
                yield client


def post(served: Served, body: Any, **headers: str) -> httpx.Response:
    sent = {
        "Host": "mcp.example.test",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": "Bearer agt_0123456789abcdef.TOKEN",
        **headers,
    }
    sent = {k: v for k, v in sent.items() if v is not None}
    return httpx.post(f"{served.url}/mcp", json=body, headers=sent, timeout=10)


INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}


def call(name: str, arguments: dict[str, Any] | None = None, id_: int = 2) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": id_,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }


class LogSweep(logging.Handler):
    """Every log record written during a test, whole, as text."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.lines.append(self.format(record))
            self.lines.append(repr(record.__dict__))
        except Exception:  # pragma: no cover
            self.lines.append(record.getMessage())

    def text(self) -> str:
        return "\n".join(self.lines)

    def __enter__(self) -> LogSweep:
        from chai_mcp.logs import QUIET, quiet_libraries

        logging.getLogger().addHandler(self)
        self._level = logging.getLogger().level
        logging.getLogger().setLevel(logging.DEBUG)
        # The service silences these in its own process (chai_mcp.logs). In this one
        # they also carry the test's own client, which sends the token on purpose.
        self._levels = {n: logging.getLogger(n).level for n in QUIET}
        quiet_libraries()
        return self

    def __exit__(self, *_: object) -> None:
        logging.getLogger().removeHandler(self)
        logging.getLogger().setLevel(self._level)
        for name, level in self._levels.items():
            logging.getLogger(name).setLevel(level)
