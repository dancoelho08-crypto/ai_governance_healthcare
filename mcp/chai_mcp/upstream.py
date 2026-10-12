"""The one hop: this request's token, to the agent API's three GET routes.

What this module guarantees, because nothing else in the service can:

* The token is passed in, used for one request and dropped. It is never a setting, a
  field, a default, a cache key or a log argument. A client is built for the call and
  closed after it, so no connection, cookie or header outlives the request or is
  shared with another caller.
* Only a fixed list of paths can be asked for (``Route``). A tool cannot name another
  route, a URL or a path; the only caller-chosen parts are a validated project
  reference and filters that are validated words, dates and numbers.
* A redirect is never followed, so a token is never sent anywhere but the configured
  address.
* A failure is turned into one of a few fixed messages. Neither the token nor a byte
  of the upstream body is in any of them, except the 422's own safe message, which is
  re-cut to a plain character set.
"""

from __future__ import annotations

import asyncio
import logging
import re
from enum import StrEnum
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import Settings
from .models import PROJECT

log = logging.getLogger("chai.mcp")

T = TypeVar("T", bound=BaseModel)


class Route(StrEnum):
    """The only upstream routes. One tool each. All GET."""

    ME = "/api/agent/me"
    PORTFOLIO = "/api/agent/portfolio"
    PROJECT = "/api/agent/projects/"


class ToolFailure(Exception):
    """A failure with a fixed, safe message. ``str()`` is what a model is told."""


class Message(StrEnum):
    REJECTED = "token rejected or expired"
    UNAVAILABLE = "the governance server is unavailable"
    NOT_ENABLED = "the agent API is not enabled on this governance server"
    NO_PROJECT = (
        "no such project, or not one this token's owner can see "
        "(a reference comes from list_portfolio)"
    )
    UNEXPECTED = "the governance server returned an answer this service does not accept"
    BUSY = "this service is busy; try again shortly"
    INTERNAL = "this service could not complete the request"
    NO_TOKEN = "no token: send the token as an Authorization: Bearer header"


# Printable characters a validation message may keep, and a bound on its length.
_SAFE = re.compile(r"[^A-Za-z0-9 ,.'_-]")
_MAX_SAFE = 160
_RETRY_MAX = 3600
_PROJECT_REF = re.compile(PROJECT)


def _retry_after(response: httpx.Response) -> int | None:
    raw = response.headers.get("retry-after", "").strip()
    if raw.isdigit() and 0 < int(raw) <= _RETRY_MAX:
        return int(raw)
    return None


def _safe_422(response: httpx.Response) -> str:
    """The API's own message for a parameter it did not accept, cut to plain text."""
    try:
        detail = response.json().get("detail")
        first = detail[0] if isinstance(detail, list) and detail else {}
        msg = first.get("msg", "") if isinstance(first, dict) else ""
        loc = first.get("loc", []) if isinstance(first, dict) else []
        where = loc[-1] if loc and isinstance(loc[-1], str) else ""
    except (ValueError, AttributeError, KeyError, IndexError, TypeError):
        return "a parameter was not accepted"
    said = _SAFE.sub("", str(msg)).strip()
    name = _SAFE.sub("", where).strip()
    text = f"{name}: {said}" if name and said else (said or name)
    return text[:_MAX_SAFE].strip() or "a parameter was not accepted"


def error_for(response: httpx.Response, route: Route) -> ToolFailure:
    """The fixed message for a non-200 answer. Never reads the body, bar the 422."""
    code = response.status_code
    if code == httpx.codes.UNAUTHORIZED:
        return ToolFailure(Message.REJECTED.value)
    if code == httpx.codes.NOT_FOUND:
        return ToolFailure(
            (
                Message.NO_PROJECT if route is Route.PROJECT else Message.NOT_ENABLED
            ).value
        )
    if code == httpx.codes.UNPROCESSABLE_ENTITY:
        return ToolFailure(
            f"the governance server did not accept the request: {_safe_422(response)}"
        )
    if code == httpx.codes.TOO_MANY_REQUESTS:
        wait = _retry_after(response)
        suffix = f"; retry after {wait} seconds" if wait else "; retry later"
        return ToolFailure(f"too many requests for this token{suffix}")
    return ToolFailure(Message.UNAVAILABLE.value)


class Upstream:
    """Calls the agent API for one request, with that request's token."""

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ):
        self._base = settings.api_base_url
        self._timeout = settings.timeout_seconds
        self._transport = transport

    async def get(
        self,
        route: Route,
        model: type[T],
        *,
        authorization: str,
        suffix: str = "",
        params: dict[str, Any] | None = None,
        client_address: str | None = None,
    ) -> T:
        if route is Route.PROJECT and not _PROJECT_REF.fullmatch(suffix):
            # Belt and braces: the tool's own type already says so.
            raise ToolFailure(Message.NO_PROJECT.value)
        if route is not Route.PROJECT and suffix:
            raise ToolFailure(Message.INTERNAL.value)
        headers = {"Authorization": authorization, "Accept": "application/json"}
        if client_address:
            headers["X-Client-Address"] = client_address
        try:
            # A total bound, on top of httpx's bound on each phase.
            async with (
                asyncio.timeout(self._timeout),
                httpx.AsyncClient(
                    base_url=self._base,
                    timeout=self._timeout,
                    follow_redirects=False,
                    transport=self._transport,
                    trust_env=False,
                ) as client,
            ):
                response = await client.get(
                    route.value + suffix, params=params or None, headers=headers
                )
        except (httpx.HTTPError, TimeoutError) as exc:
            # The class names what failed; the message could carry the URL.
            log.warning("upstream call failed: %s", type(exc).__name__)
            raise ToolFailure(Message.UNAVAILABLE.value) from None
        if response.status_code != httpx.codes.OK:
            log.info("upstream answered %s for %s", response.status_code, route.name)
            raise error_for(response, route) from None
        try:
            return model.model_validate(response.json())
        except (ValueError, ValidationError):
            # Which field failed is logged by name only (never a value).
            log.warning("upstream answer refused for %s", route.name)
            raise ToolFailure(Message.UNEXPECTED.value) from None
