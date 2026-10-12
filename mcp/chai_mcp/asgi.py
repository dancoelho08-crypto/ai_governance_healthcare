"""The HTTP front of the service: one path, one method, a token, and no query string.

Everything here runs before the MCP SDK sees a request, and none of it reads the token's
value: a request either carries a bearer header or it does not. Whether the token is
right is the agent API's answer, given to the tool that asked.

* ``/healthz`` answers the container's health check, and nothing else is served but
  ``/mcp``. Anything else is a 404.
* Host and Origin are validated (DNS rebinding, per the MCP transport guidance), before
  the token is looked at. No CORS header is ever sent and OPTIONS is not served, so a
  page in a browser cannot call this service.
* Only POST is served: stateless JSON responses need nothing else. GET and DELETE are
  405.
* A query string is refused. A token has no business in a URL, and a refused request
  is not logged with its query.
* The log has one line per request: the method, the path and the status. Never a
  header, a query or a body.
"""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any

from mcp.server.transport_security import TransportSecurityMiddleware
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from .bearer import bearer_token
from .config import Settings
from .server import build_server, transport_security
from .upstream import Message as Words
from .upstream import Upstream

log = logging.getLogger("chai.mcp.access")

MCP_PATH = "/mcp"
HEALTH_PATH = "/healthz"


class Guard:
    """Pure ASGI, so it sees a request before any framework does."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self._security = TransportSecurityMiddleware(transport_security(settings))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # enum-ok: ASGI protocol value
            await self.app(scope, receive, send)
            return
        status = 500

        async def watching(message: MutableMapping[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":  # enum-ok: ASGI protocol value
                status = message["status"]
            await send(message)  # type: ignore[arg-type]

        try:
            refusal = await self._refusal(scope)
            if refusal is not None:
                await refusal(scope, receive, watching)
            else:
                await self.app(scope, receive, watching)
        finally:
            # Path only, never the query: a token a client put there is not logged.
            log.info("%s %s %s", scope["method"], scope["path"], status)

    async def _refusal(self, scope: Scope) -> Response | None:
        path, method = scope["path"], scope["method"]
        if path == HEALTH_PATH and method == "GET":  # enum-ok: HTTP method
            return JSONResponse({"status": "ok"})
        if path != MCP_PATH:
            return PlainTextResponse("Not found.", status_code=404)
        request = Request(scope)
        # Host and Origin first: a rebinding page never gets as far as being told
        # whether it sent a token.
        bad = await self._security.validate_request(
            request,
            is_post=method == "POST",  # enum-ok: HTTP method
        )
        if bad is not None:
            return bad
        if method != "POST":  # enum-ok: HTTP method
            return PlainTextResponse(
                "Method not allowed.", status_code=405, headers={"Allow": "POST"}
            )
        if scope.get("query_string"):
            return PlainTextResponse("No query string is accepted.", status_code=400)
        if bearer_token(request.headers.get("authorization")) is None:
            return PlainTextResponse(
                Words.NO_TOKEN.value,
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None


def create_app(settings: Settings, *, upstream: Upstream | None = None) -> Starlette:
    mcp, upstream = build_server(settings, upstream)
    app = mcp.streamable_http_app()
    # Held so a test can look for what must not be here: a token kept after its call.
    app.state.mcp, app.state.upstream = mcp, upstream
    app.add_middleware(Guard, settings=settings)  # type: ignore[arg-type]
    return app
