"""The FastAPI application.

Serves the API only. The dashboard itself is static and is served by the proxy
in front (``proxy/Caddyfile``), which is also what terminates SSO -- see
``docs/deploy.md``.

Two defaults here are deliberate and worth not changing by accident:

**CORS is off.** The browser app is served from the same origin as the API, by
the same proxy, so it never makes a cross-origin request. Turning CORS on would
only widen who can call the API from a page they control. ``CORS_ORIGINS`` can
switch it on for a split deployment, and takes an explicit list -- never ``*``,
which with credentials is both insecure and rejected by browsers anyway.

**Cross-site writes are refused.** Identity comes from a proxy that decides
based on its own session, which a browser attaches to cross-site requests too.
``Sec-Fetch-Site`` is checked on every non-GET; see the middleware below.

**No ``--proxy-headers``.** uvicorn's proxy-header handling rewrites the peer
address from ``X-Forwarded-For``, which the client controls. ``TRUSTED_PROXY_CIDR``
in ``app/auth.py`` checks the *real* TCP peer, and that check is only meaningful
while the real peer is what the app sees.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from .auth import log_auth_posture
from .config import Settings
from .db import Database
from .emergency import EmergencyAudit
from .events import EventBroker
from .principals import PrincipalRecorder
from .retirement import (
    ManifestError,
    RulesRefused,
    describe_sync,
    load_manifest,
    sync_rules,
)
from .roles import DbRole
from .routes import router
from .securitylog import SecurityEvent, configure_logging, emit

log = logging.getLogger("chai")

# Methods that cannot change state, and so need no cross-site check.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})
API_CSP = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
HSTS_VALUE = "max-age=31536000; includeSubDomains"


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


# Kept so an operator's existing import or reference does not break.
FixedWindowRateLimiter = SlidingWindowRateLimiter


def _is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _is_tls(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "")
    if forwarded:
        proto = forwarded.split(",", 1)[0].strip().lower()
        if proto == "https":
            return True
    return request.url.scheme == "https"


def _rate_limit_key(request: Request, settings: Settings) -> str:
    identity = request.headers.get(settings.identity_header, "").strip()
    if (
        identity
        and settings.identity_strip_prefix
        and identity.startswith(settings.identity_strip_prefix)
    ):
        identity = identity[len(settings.identity_strip_prefix) :]
    if identity:
        return f"id:{identity.lower()}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


class BodySizeLimitMiddleware:
    """Reject an oversize request body, as ASGI middleware rather than HTTP.

    This cannot be a ``@app.middleware("http")`` function, and the reason is
    worth recording because the first version was one and looked correct.

    Starlette's ``BaseHTTPMiddleware`` hands the downstream app its own
    receive channel. A dispatch function that reads the body to measure it --
    with ``await request.body()`` or by draining ``request.stream()`` -- has
    consumed it, and assigning ``request._receive`` puts it back only on the
    middleware's OWN ``Request`` object. The route constructs a new one and
    sees nothing. The result was that any request without a Content-Length,
    which is every chunked request, reached the route with an EMPTY body and
    failed validation with a 422 that had nothing to do with what was sent.
    Content-Length requests were unaffected, which is why the browser app and
    the original tests never showed it.

    Wrapping ``receive`` at the ASGI level measures the body without
    consuming it: each chunk is counted and passed straight through. Nothing
    is buffered, so the limit is enforced on the first chunk that crosses it
    rather than after the whole body has been read into memory.
    """

    def __init__(self, app: Any, *, limit: int) -> None:
        self.app = app
        self.limit = max(1, limit)

    async def _reject(self, send: Any) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": f"Request body exceeds the {self.limit}-byte limit."},
        )
        await response({"type": "http"}, lambda: {"type": "http.request"}, send)

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") not in BODY_METHODS
            or not _is_api_path(scope.get("path", ""))
        ):
            await self.app(scope, receive, send)
            return

        # Declared size: reject before a single byte is read.
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = self.limit + 1
                if declared > self.limit:
                    await self._reject(send)
                    return
                break

        received = 0
        rejected = False
        response_started = False

        async def limited_receive() -> Any:
            nonlocal received, rejected
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.limit:
                    rejected = True
                    # Looks like a dropped connection to the app, which
                    # Starlette already knows how to unwind. Our 413 goes out
                    # below instead of whatever it would have replied.
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Any) -> None:
            nonlocal response_started
            if rejected:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except ClientDisconnect:
            if not rejected:
                raise

        if rejected and not response_started:
            await self._reject(send)


async def migrate_and_sync(db: Database, settings: Settings) -> None:
    """``RUN_MIGRATIONS=true`` (the single-role setup): migrate, and load the
    retirement rules the way ``python -m app.migrate`` does (D-76).

    With ``RETIREMENT_MANIFEST`` set, the same sync with the same refusal: a
    missing or malformed manifest, or a change of rules that
    ``RETIREMENT_RULES_ACK`` does not acknowledge, stops the API from starting.
    Without it the API still migrates, retiring by whatever the database holds
    (010's seed is CHAI's rules), logs a warning, and ``/api/health`` reports the
    rules as not synced (``retirement_rules.synced``) for as long as it runs, even
    over rules an earlier sync recorded: this API checked nothing against its build.
    """
    manifest = None
    if settings.retirement_manifest:
        try:
            manifest = load_manifest(settings.retirement_manifest)
        except ManifestError as exc:
            raise RuntimeError(f"retirement rules: {exc}") from exc
    await db.migrate()
    if manifest is None:
        db.rules_unsynced = True
        log.warning(
            "RUN_MIGRATIONS=true and RETIREMENT_MANIFEST is not set: the retirement "
            "rules were not synced from the build's manifest, so the database "
            "retires by what it holds (010's seed, CHAI's rules, unless an earlier "
            "sync recorded others) and /api/health "
            "reports retirement_rules.synced=false. Set RETIREMENT_MANIFEST to the "
            "build's manifest.json, or run `python -m app.migrate` (D-76)."
        )
        return
    async with db.acquire() as conn:
        try:
            synced = await sync_rules(conn, manifest, settings.retirement_rules_ack)
        except RulesRefused as exc:
            raise RuntimeError(f"retirement rules refused: {exc}") from exc
    log.info("%s", describe_sync(synced, manifest))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Open the pool, migrate, start listening; tear all three down in order."""
    settings: Settings = app.state.settings
    configure_logging(settings.log_level, settings.log_format)
    log.info("CHAI governance API %s starting", settings.version)
    log_auth_posture(settings)

    db = Database(
        settings.serving_database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        connect_timeout=settings.db_connect_timeout,
    )
    await db.connect()
    db_role = await db.serving_role()
    if db_role is DbRole.OWNER:
        log.warning(
            "serving as the database OWNER (or a superuser): the append-only "
            "triggers on the audit log and version history constrain this "
            "application's bugs, not the application, and not anything holding its "
            "credential. Set APP_POSTGRES_PASSWORD and run `python -m app.migrate` "
            "so the API serves as a restricted role (#48)."
        )
    else:
        log.info("serving as a restricted database role (cannot disable triggers)")
    if settings.run_migrations:
        try:
            await migrate_and_sync(db, settings)
        except BaseException:
            await db.close()
            raise
    else:
        log.info("RUN_MIGRATIONS=false: assuming the schema is already current")

    broker = EventBroker(
        db,
        channel=settings.events_channel,
        queue_size=settings.sse_queue_size,
        max_streams_per_user=settings.sse_max_streams_per_user,
    )
    await broker.start()

    app.state.db = db
    app.state.emergency = EmergencyAudit()
    if settings.emergency_access_ids:
        log.warning(
            "emergency access is configured for %s: these identities hold owner "
            "rights on EVERY project, and every use is recorded in that project's "
            "audit log and as an access.breakglass security event.",
            ", ".join(sorted(settings.emergency_access_ids)),
        )
    app.state.principals = PrincipalRecorder(db)
    app.state.db_role = db_role
    app.state.broker = broker
    log.info("ready")
    try:
        yield
    finally:
        log.info("shutting down")
        await broker.stop()
        await db.close()


def _encodable(value: Any) -> Any:
    """``value`` with every lone surrogate in a string or key written out as text."""
    if isinstance(value, str):
        return value.encode("utf-8", "backslashreplace").decode("utf-8")
    if isinstance(value, dict):
        return {_encodable(k): _encodable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_encodable(v) for v in value]
    return value


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Taking settings as an argument is what makes it testable."""
    settings = settings or Settings.from_env()

    app = FastAPI(
        title="CHAI governance review API",
        version=settings.version,
        summary=(
            "Shared storage for the CHAI governance dashboard: projects, an "
            "append-only audit log, and a change stream."
        ),
        description=__doc__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    rate_limiter = SlidingWindowRateLimiter(
        settings.rate_limit_window_seconds,
        settings.rate_limit_max_requests,
    )
    announced: dict[str, float] = {}  # when each client's trip was last reported

    if settings.cors_origins:
        log.warning(
            "CORS enabled for %s. The app does not need this when it is served "
            "from the same origin as the API.",
            ", ".join(settings.cors_origins),
        )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type"],
        )

    @app.middleware("http")
    async def api_hardening(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        # /api/health is exempt: every platform in docs/deploy.md probes it
        # from inside the load balancer. That exemption is why the database
        # check behind it is cached -- see Database.ping_cached.
        if _is_api_path(path) and request.method != "OPTIONS" and path != "/api/health":
            key = _rate_limit_key(request, settings)
            if not await rate_limiter.allow(key):
                # Once per client per window: a flood of refused requests must not
                # become a flood of log lines, which is the denial of service again.
                now = time.monotonic()
                if now - announced.get(key, -1e9) >= settings.rate_limit_window_seconds:
                    announced[key] = now
                    if len(announced) > 10_000:
                        announced.clear()
                    emit(
                        SecurityEvent.RATELIMIT_TRIPPED,
                        f"rate limit tripped for {key}",
                        key=key,
                        limit=settings.rate_limit_max_requests,
                        window_seconds=settings.rate_limit_window_seconds,
                    )
                return JSONResponse(
                    status_code=429,
                    headers={"Retry-After": str(settings.rate_limit_window_seconds)},
                    content={"detail": "Too many requests; please retry shortly."},
                )

        response = await call_next(request)

        if _is_api_path(path):
            response.headers.setdefault("Content-Security-Policy", API_CSP)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "no-referrer")
            if _is_tls(request):
                response.headers.setdefault("Strict-Transport-Security", HSTS_VALUE)
        return response

    @app.middleware("http")
    async def reject_cross_site_writes(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Refuse a state-changing request that a different site initiated.

        Every write here is authenticated by a header the proxy adds, and the
        proxy adds it based on ITS session -- an oauth2-proxy cookie, an Easy
        Auth cookie, an IAP or ALB session. The browser attaches that session
        to a cross-site request just as readily as to a same-site one, so a
        page a signed-in user visits could issue

            fetch('https://governance.hospital.org/api/projects/x',
                  {method: 'DELETE', credentials: 'include'})

        and the API would accept it as them. CORS does not help: it governs
        whether the response can be READ, and a delete does not need to be
        read to have happened.

        ``Sec-Fetch-Site`` is the check. It is set by the browser, cannot be
        altered by script, and says where the request came from. Requests
        without it are allowed through: every browser that has shipped it
        since 2023 sends it on every request, so an absent header means a
        non-browser client -- curl, a health probe, an integration -- which is
        not what a cross-site attack looks like. Blocking those would break
        real callers to defend against nothing.

        ``CSRF_TRUSTED_SITES=cross-site`` relaxes this for a deployment that
        genuinely serves the app from a different origin than the API. That is
        the same deployment that needs ``CORS_ORIGINS``, and both should be
        rare.
        """
        if request.method not in SAFE_METHODS:
            site = request.headers.get("sec-fetch-site")
            if site is not None and site not in settings.csrf_trusted_sites:
                emit(
                    SecurityEvent.CSRF_REJECTED,
                    f"rejected cross-site {request.method} {request.url.path} "
                    f"(Sec-Fetch-Site: {site})",
                    method=request.method,
                    path=request.url.path,
                    site=site,
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": (
                            "Cross-site write rejected. This API only accepts "
                            "state-changing requests from its own origin."
                        )
                    },
                )
        return await call_next(request)

    @app.middleware("http")
    async def mark_auth_mode(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Stamp the auth posture on every response.

        In dev mode this is the header that makes a screenshot of the network
        tab enough to tell that the identity is fake.
        """
        response = await call_next(request)
        response.headers["X-Chai-Auth-Mode"] = settings.auth_mode
        return response

    @app.exception_handler(asyncpg.exceptions.DataError)
    async def unstorable(request: Request, exc: Exception) -> JSONResponse:
        """The database refused data a writer sent (SQLSTATE class 22), most often the
        NUL character (U+0000), which PostgreSQL text and jsonb cannot hold. That is the
        writer's input, so it is a 422, not a server error that any writer could
        provoke at will. The text is not logged: it is the thing that was refused."""
        log.warning(
            "refused data the database cannot store on %s %s (%s)",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=422,
            content={
                "detail": "The request contains data that cannot be stored, "
                "such as the NUL character (U+0000)."
            },
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """FastAPI's own 422, with the echoed input made encodable (#187).

        Its handler returns each error's ``input``, the value that failed, and JSON
        text holding a lone surrogate (which the parser accepts) cannot be written as
        UTF-8, so a request that failed validation and carried one answered 500. The
        surrogate is escaped to its text (backslashreplace, as the fingerprint does),
        here, once, for every route.
        """
        errors = jsonable_encoder(exc.errors())
        return JSONResponse(status_code=422, content={"detail": _encodable(errors)})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Log the traceback; return a body that does not contain it.

        A stack trace in an API response tells an attacker the file layout, the
        library versions and often the SQL.
        """
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500, content={"detail": "Internal server error."}
        )

    # Added last, so it runs FIRST: an oversize body is refused before the
    # rate limiter, the cross-site check or any route reads a byte of it.
    app.add_middleware(BodySizeLimitMiddleware, limit=settings.request_body_limit_bytes)

    app.include_router(router)
    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run(
        "app.main:app",
        # Settings.bind_host reads the same HOST variable. Going through
        # settings rather than os.getenv here keeps the value that the
        # startup check in config.py reasons about and the value actually
        # bound from drifting apart.
        host=settings.bind_host,
        port=settings.port,
        log_level=settings.log_level,
        # Intentionally no proxy_headers=True: see the module docstring.
        proxy_headers=False,
    )
