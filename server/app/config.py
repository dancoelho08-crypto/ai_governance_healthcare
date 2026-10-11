"""Runtime configuration, read once from the environment at startup.

Every knob is an environment variable, because the three clouds this is meant
to run on -- Google Cloud, AWS and Azure -- all inject configuration that way,
and all three send a *different* identity header.

Two ways to say the same thing:

``IDENTITY_MODE``
    A preset: ``iap``, ``alb``, ``easyauth``, or ``proxy`` (the default). Picks
    the header name, the value format and any prefix to strip. This is what
    ``docs/deploy.md`` sets.

``IDENTITY_HEADER`` and friends
    Explicit overrides, for a proxy none of the presets covers -- nginx with
    oauth2-proxy, Cloudflare Access, a hospital's own gateway. Anything set
    explicitly wins over the preset.

``IDENTITY_HEADER`` defaults to ``X-Forwarded-Email``, the de-facto name used
by oauth2-proxy and most nginx auth_request setups.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit

from .securitylog import LogFormat

DEFAULT_IDENTITY_HEADER = "X-Forwarded-Email"


@dataclass(frozen=True)
class IdentityPreset:
    """Which headers one front door sets, and how to read them."""

    header: str
    fmt: str = "plain"  # "plain" | "jwt"
    name_header: str = ""
    id_header: str = ""
    strip_prefix: str = ""
    description: str = ""


IDENTITY_PRESETS: dict[str, IdentityPreset] = {
    # Generic reverse proxy: oauth2-proxy, nginx auth_request, Cloudflare
    # Access with a transform rule, a hospital gateway.
    "proxy": IdentityPreset(
        header=DEFAULT_IDENTITY_HEADER,
        name_header="X-Forwarded-User",
        description="generic reverse proxy",
    ),
    # Google Cloud Identity-Aware Proxy. The value is prefixed with the
    # issuer: "accounts.google.com:person@example.org". Code that forgets to
    # strip that prefix stores a user id nobody can match to a directory.
    "iap": IdentityPreset(
        header="X-Goog-Authenticated-User-Email",
        id_header="X-Goog-Authenticated-User-Id",
        strip_prefix="accounts.google.com:",
        description="Google Cloud Identity-Aware Proxy",
    ),
    # AWS Application Load Balancer with an authenticate-oidc listener rule.
    # x-amzn-oidc-identity carries only the opaque `sub`, so read the claims
    # out of x-amzn-oidc-data instead -- that is where the email lives.
    "alb": IdentityPreset(
        header="x-amzn-oidc-data",
        fmt="jwt",
        description="AWS ALB authenticate-oidc",
    ),
    # Azure App Service / Container Apps built-in authentication ("Easy Auth").
    # Easy Auth strips any client-supplied copy of these headers before it
    # forwards, which is one fewer thing to get wrong.
    "easyauth": IdentityPreset(
        header="X-MS-CLIENT-PRINCIPAL-NAME",
        id_header="X-MS-CLIENT-PRINCIPAL-ID",
        description="Azure Easy Auth",
    ),
}


def _str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None else value.strip()


def _alias(primary: str, alias: str, default: str = "") -> str:
    """First of two spellings that is set.

    The repository's Docker Compose stack puts Caddy in front and normalizes
    every cloud's header into ``X-Auth-Request-*``, so it configures the API
    with ``AUTH_HEADER_EMAIL`` and friends. Accepting both spellings means the
    same image runs under compose and under a raw cloud front door without a
    wrapper script translating variables.
    """
    value = os.getenv(primary)
    if value is not None and value.strip():
        return value.strip()
    value = os.getenv(alias)
    if value is not None and value.strip():
        return value.strip()
    return default


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:  # pragma: no cover - startup failure
        raise RuntimeError(f"{name} must be an integer, got {value!r}") from exc


# What a sign-out URL may be. It becomes a link in the page, so it is an
# allowlist, not a blocklist of bad schemes: an https URL, or a path on this origin
# ("/.auth/logout"). Not "//host" (a protocol-relative URL leaves the origin), not
# plain http, not javascript: or data:, and nothing with whitespace or control
# characters in it.
_SIGN_OUT_OK = re.compile(r"^(https://[^\s/]+[^\s]*|/(?!/)[^\s]*)$")


def _sign_out_url() -> str:
    raw = os.environ.get("SIGN_OUT_URL", "")
    if not raw:
        return ""
    if not _SIGN_OUT_OK.fullmatch(raw) or any(ord(ch) < 32 for ch in raw):
        raise RuntimeError(
            "SIGN_OUT_URL must be an https URL or a path starting with a single '/' "
            "(for example /.auth/logout), with no spaces or control characters. It "
            "becomes a link in the page, so javascript:, data:, http: and "
            "protocol-relative URLs are refused."
        )
    return raw


def _log_format() -> LogFormat:
    value = os.environ.get("LOG_FORMAT", "").strip().lower() or LogFormat.JSON
    try:
        return LogFormat(value)
    except ValueError:
        raise RuntimeError(
            f"LOG_FORMAT must be 'json' or 'text', got {value!r}"
        ) from None


def _idle_lock_minutes() -> int:
    raw = os.environ.get("IDLE_LOCK_MINUTES", "").strip()
    if not raw:
        return 0
    if not raw.isdigit() or not 0 <= int(raw) <= 1440:
        raise RuntimeError(
            "IDLE_LOCK_MINUTES must be a whole number of minutes from 0 (off) to 1440."
        )
    return int(raw)


# The secret that makes the agent API's person ids opaque (#164). It is a key, not a
# password a person types, so a short one is refused rather than accepted.
AGENT_ID_SECRET_MIN_LENGTH = 32

# A status or decision value a deployment adds for a build of its own framework
# (AGENT_EXTRA_VALUES). It is shown to an agent as the stored value, so it must look
# like a vocabulary word and not like a name or an address.
AGENT_VALUE_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,&/+._-]{0,63}$")


def _agent_id_secret() -> str:
    value = os.environ.get("AGENT_ID_SECRET", "").strip()
    if value and len(value) < AGENT_ID_SECRET_MIN_LENGTH:
        raise RuntimeError(
            f"AGENT_ID_SECRET is set but shorter than {AGENT_ID_SECRET_MIN_LENGTH} "
            "characters. It keys the pseudonym of every person the agent API names, "
            "so it must be long and random: openssl rand -base64 48. Unset it to "
            "leave the agent API off."
        )
    return value


def _agent_extra_values() -> frozenset[str]:
    values = _csv("AGENT_EXTRA_VALUES")
    for value in values:
        if not AGENT_VALUE_SHAPE.fullmatch(value):
            raise RuntimeError(
                f"AGENT_EXTRA_VALUES holds {value!r}, which is not a status or "
                "decision value: letters, digits, spaces and , & / + . _ - only, "
                "up to 64 characters, starting with a letter or digit."
            )
    return frozenset(values)


def _csv(name: str) -> list[str]:
    return [part.strip() for part in _str(name).split(",") if part.strip()]


# --- the database URL ------------------------------------------------------
#
# Nothing builds this URL by string interpolation. Compose used to write
# `postgresql://user:${POSTGRES_PASSWORD}@db/...`, which cannot percent-encode,
# so a `/` in the password ended the URL's authority section and the first chunk
# of the password was read as a port number:
#
#     ValueError: invalid literal for int() with base 10: 'pwYZ1MXvvrx+eItO'
#
# `openssl rand -base64 32` is the generator preflight.py and .env.example tell
# people to use, and it emits a `/` often enough that about half of all passwords
# broke the stack. So compose passes the pieces and this assembles them, with the
# password encoded, which makes the choice of password irrelevant.


def _bad_url_reason(url: str) -> str | None:
    """Why `url` cannot be parsed, WITHOUT quoting any of it.

    urllib's own message embeds the offending text, which for this failure is the
    start of the password. An error that echoes a credential ends up in a log
    aggregator, so this says what is wrong and nothing about what it was given.
    """
    try:
        urlsplit(url).port  # noqa: B018  (the access is the check)
    except ValueError:
        return (
            "DATABASE_URL is not a valid URL: what follows the first ':' in its "
            "authority is not a port number. This almost always means the "
            "password contains one of / @ : ? # and was not percent-encoded. "
            "Either percent-encode it, or set POSTGRES_USER, POSTGRES_PASSWORD, "
            "POSTGRES_HOST and POSTGRES_DB instead and let the API do it."
        )
    return None


def build_database_url(env: Mapping[str, str]) -> str:
    """The connection URL, from DATABASE_URL or from its pieces. "" if neither.

    An explicit DATABASE_URL wins and is used as written, because a managed
    instance's URL carries query parameters (``sslmode``, a Cloud SQL socket) the
    pieces cannot express. It is checked, so a broken one fails at startup with a
    message that says why.

    Otherwise the URL is assembled from POSTGRES_USER, POSTGRES_PASSWORD,
    POSTGRES_HOST, POSTGRES_PORT and POSTGRES_DB, with every part percent-encoded.
    No password means no URL, not a guess.
    """
    explicit = (env.get("DATABASE_URL") or "").strip()
    if explicit:
        problem = _bad_url_reason(explicit)
        if problem:
            raise RuntimeError(problem)
        return explicit

    password = env.get("POSTGRES_PASSWORD") or ""
    if not password:
        return ""
    return _assemble_url(env, env.get("POSTGRES_USER") or "chai", password)


def _assemble_url(env: Mapping[str, str], user: str, password: str) -> str:
    """A URL from its pieces, every part percent-encoded."""
    quoted_user = quote(user, safe="")
    database = quote(env.get("POSTGRES_DB") or "chai", safe="")
    host = env.get("POSTGRES_HOST") or "localhost"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"  # an IPv6 literal
    port = env.get("POSTGRES_PORT") or "5432"
    return (
        f"postgresql://{quoted_user}:{quote(password, safe='')}"
        f"@{host}:{port}/{database}"
    )


def build_app_database_url(env: Mapping[str, str]) -> str:
    """The URL the API SERVES as, when it is not the table owner. "" if unset.

    The owner (``DATABASE_URL`` / ``POSTGRES_*``) creates the schema and can
    disable the append-only triggers; the API should hold a restricted role
    instead (``app/roles.py``, #48). An explicit ``APP_DATABASE_URL`` wins, for a
    managed instance; otherwise ``APP_POSTGRES_USER`` (default ``chai_app``) and
    ``APP_POSTGRES_PASSWORD`` are combined with the same host, port and database.
    """
    explicit = (env.get("APP_DATABASE_URL") or "").strip()
    if explicit:
        problem = _bad_url_reason(explicit)
        if problem:
            raise RuntimeError(problem.replace("DATABASE_URL", "APP_DATABASE_URL"))
        return explicit
    password = env.get("APP_POSTGRES_PASSWORD") or ""
    if not password:
        return ""
    return _assemble_url(env, env.get("APP_POSTGRES_USER") or "chai_app", password)


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the environment."""

    # --- database ---------------------------------------------------------
    database_url: str = ""
    # What the API serves as, when that is a restricted role rather than the owner.
    app_database_url: str = ""
    db_pool_min: int = 1
    db_pool_max: int = 10
    db_connect_timeout: float = 10.0
    run_migrations: bool = True
    # Only when run_migrations: the build's manifest.json and the acknowledgment of
    # a change of retirement rules, as the migrate job reads them (D-76). With no
    # manifest the API migrates without syncing the rules, says so in its log, and
    # /api/health reports them as not synced.
    retirement_manifest: str = ""
    retirement_rules_ack: str = ""

    # --- identity ---------------------------------------------------------
    identity_mode: str = "proxy"
    identity_header: str = DEFAULT_IDENTITY_HEADER
    identity_name_header: str = "X-Forwarded-User"
    identity_id_header: str = ""
    identity_strip_prefix: str = ""
    identity_header_format: str = "plain"
    identity_audience: str = ""
    identity_jwt_email_claim: str = "email"
    identity_jwt_name_claim: str = "name"
    identity_jwt_id_claim: str = "sub"

    # --- dev-only escape hatch -------------------------------------------
    dev_insecure_auth: bool = False
    dev_identity_email: str = "dev@localhost"
    dev_identity_name: str = "Local Dev (INSECURE)"

    require_identity: bool = True

    # Identities (as the proxy asserts them, after any prefix is stripped) that hold
    # owner rights on every project, with every use recorded in that project's own
    # audit log (#42). Empty by default: nobody is special unless the deployment
    # says so, and a blank value is not a wildcard.
    emergency_access_ids: frozenset[str] = frozenset()

    # A second, differently-named variable that must ALSO be set before either
    # kill switch above is honored off loopback. One typo'd variable in a task
    # definition should not be the whole of the authentication system.
    insecure_auth_acknowledged: bool = False

    # The address uvicorn is told to bind. Read here only so the startup check
    # can tell "a laptop" from "something with a route to it".
    bind_host: str = "0.0.0.0"

    # --- transport --------------------------------------------------------
    cors_origins: list[str] = field(default_factory=list)

    # Sec-Fetch-Site values accepted on a state-changing request. "same-origin"
    # covers the app talking to its own API. "none" is a user typing the URL or
    # a bookmark, which cannot carry an attacker's body. "same-site" is NOT
    # included by default: a sibling subdomain is a different trust boundary,
    # and a hospital intranet has many of them.
    csrf_trusted_sites: frozenset[str] = frozenset({"same-origin", "none"})
    proxy_shared_secret: str = ""
    proxy_secret_header: str = "X-Proxy-Secret"
    trusted_proxy_cidrs: list[str] = field(default_factory=list)
    request_body_limit_bytes: int = 1_048_576
    rate_limit_window_seconds: int = 60
    rate_limit_max_requests: int = 240
    log_level: str = "info"
    # "json": one object per line, security events tagged and named (#38). "text":
    # the old human-readable line, for a terminal.
    log_format: LogFormat = LogFormat.JSON
    port: int = 8000

    # --- events -----------------------------------------------------------
    events_channel: str = "chai_events"
    sse_keepalive_seconds: float = 15.0
    sse_queue_size: int = 256
    sse_max_streams_per_user: int = 8
    # How long one event stream may live before the SERVER ends it. The stream
    # authenticates once, when it attaches, so without a bound it keeps delivering
    # after the account behind it is disabled (#49). Ending it makes the browser
    # reconnect, which goes back through the front door and is authenticated again.
    # 0 means unlimited, for a deployment whose front door already bounds it.
    sse_max_lifetime_seconds: float = 900.0

    # --- session controls the browser reads from /api/health --------------
    # Minutes of inactivity before the dashboard locks itself. 0 is off. The
    # front door's own session lifetime is the real control; this is defense in
    # depth for a shared workstation (#49).
    idle_lock_minutes: int = 0
    # Where the front door ends a session. Rendered as a "Sign out" link, so it
    # is validated (see SIGN_OUT_RULES): https, or a path on this origin.
    sign_out_url: str = ""

    # --- agent API (#164, D-89) -------------------------------------------
    # The key that turns an identity id into the opaque id an agent is shown. Empty
    # leaves the agent API off: no token can be minted and every /api/agent/ route
    # answers 404. It is never logged and never returned.
    agent_id_secret: str = ""
    # Requests per token per rate-limit window. Lower than rate_limit_max_requests,
    # which a person at a dashboard needs and an agent loop does not.
    agent_rate_limit_max_requests: int = 60
    # Tokens a person may hold at once (not revoked, not expired).
    agent_max_active_tokens: int = 5
    # Status and decision values beyond the published and example frameworks', for a
    # build of another framework (D-79). Anything else is shown to an agent as null.
    agent_extra_values: frozenset[str] = frozenset()

    # --- misc -------------------------------------------------------------
    version: str = "0.1.0"
    log_page_size: int = 60

    @property
    def agent_api_enabled(self) -> bool:
        """The agent API is on only when it has a secret to make ids opaque with."""
        return bool(self.agent_id_secret)

    @property
    def serving_database_url(self) -> str:
        """The connection the API's traffic uses: the restricted role if given."""
        return self.app_database_url or self.database_url

    @property
    def auth_mode(self) -> str:
        """One short string for ``/api/health`` and the startup log."""
        if self.dev_insecure_auth:
            return "DEV-INSECURE"
        if not self.require_identity:
            return f"proxy-header:{self.identity_mode}:anonymous-allowed"
        return f"proxy-header:{self.identity_mode}"

    def _reject_silent_misconfiguration(self) -> None:
        """Refuse to start on settings that would be ignored without a word.

        IDENTITY_AUDIENCE is only ever read while decoding a JWT. Set it
        alongside a `plain` header format -- which is what IDENTITY_MODE=iap
        and IDENTITY_MODE=easyauth select -- and it does nothing at all, while
        looking in the deployment config exactly like an audience check is in
        force. An operator who believes their deployment is pinned to one
        service, and is not, is worse off than one who knows it is not pinned.
        So this is fatal rather than a warning: a misconfiguration that only
        weakens security is precisely the kind that survives in production.
        """
        self._reject_unguarded_insecure_auth()

        # A restricted serving role cannot create tables, so a process that serves
        # as one and is also told to migrate fails at the first migration, with a
        # permission error that points nowhere useful. Say what to do instead.
        if self.app_database_url and self.run_migrations:
            raise RuntimeError(
                "APP_POSTGRES_PASSWORD / APP_DATABASE_URL is set, so this process "
                "serves as the restricted database role, which cannot migrate. Set "
                "RUN_MIGRATIONS=false here and run `python -m app.migrate` as the "
                "database owner (compose's `migrate` service does) before starting "
                "the API. See docs/self-hosting.md."
            )

        if self.identity_audience and self.identity_header_format != "jwt":
            raise RuntimeError(
                "IDENTITY_AUDIENCE is set but IDENTITY_HEADER_FORMAT is "
                f"{self.identity_header_format!r}, so the audience is never "
                "checked. Either set IDENTITY_HEADER_FORMAT=jwt with a header "
                "that carries a signed assertion (x-goog-iap-jwt-assertion, "
                "x-amzn-oidc-data, X-MS-TOKEN-AAD-ID-TOKEN), or unset "
                "IDENTITY_AUDIENCE. See docs/deploy.md."
            )

        # An ALB signs x-amzn-oidc-data with its LOAD BALANCER's ARN in the
        # token header's `signer`. A listener's ARN looks almost the same and
        # can never match, so every request would be a 401 that reads as an SSO
        # fault, and the operator's likeliest next move is to unset the
        # audience, which turns off the check that catches a token minted for
        # another service (#51).
        if re.search(r":listener(-rule)?/", self.identity_audience):
            raise RuntimeError(
                f"IDENTITY_AUDIENCE={self.identity_audience!r} is a listener ARN. "
                "An ALB signs with its load balancer ARN "
                "(arn:aws:elasticloadbalancing:REGION:ACCOUNT:loadbalancer/app/"
                "NAME/ID), so this value can never match and every request "
                "would be a 401. Use the load balancer's ARN: aws elbv2 "
                "describe-load-balancers --query "
                "'LoadBalancers[].LoadBalancerArn'. See docs/deploy.md."
            )

    @property
    def _binds_loopback_only(self) -> bool:
        """Is this process reachable only from its own machine?

        Treated as the one place the kill switches below are tolerable. Note
        that a container binding 127.0.0.1 inside its own namespace is not
        reachable from the host either, so this is conservative in the right
        direction: it says "safe" less often than it could.
        """
        return self.bind_host in {"127.0.0.1", "::1", "localhost"}

    def _reject_unguarded_insecure_auth(self) -> None:
        """Refuse to start with authentication off and a route to the world.

        ``DEV_INSECURE_AUTH`` authenticates every request as one fixed user.
        ``REQUIRE_IDENTITY=false`` turns off per-project access control for
        everyone. Each was previously guarded by a log line, and a log line is
        not a guard: a single stale variable in a task definition, a Helm
        values file or a copied .env is a full compromise, and nobody reads
        container logs at 3am.

        So: either bind to loopback -- a laptop, which is what the flags are
        for -- or say so twice, with a variable whose name cannot be set by
        accident. The banner still prints; this is what makes it enforceable.
        """
        if self._binds_loopback_only or self.insecure_auth_acknowledged:
            return

        reasons = []
        if self.dev_insecure_auth:
            reasons.append(
                "DEV_INSECURE_AUTH is on, so EVERY request is authenticated as "
                f"{self.dev_identity_email!r} and the identity header is ignored"
            )
        if not self.require_identity:
            reasons.append(
                "REQUIRE_IDENTITY is false, so requests with no identity are "
                "served as 'anonymous' and per-project access control is not "
                "enforced for anyone"
            )
        if not reasons:
            return

        raise RuntimeError(
            "Refusing to start.\n\n  "
            + "\n  ".join(f"- {r}." for r in reasons)
            + f"\n\n  This process binds {self.bind_host}, which is not loopback, "
            "so anyone who\n  can reach the port is affected.\n\n"
            "  If this is a laptop, bind loopback: HOST=127.0.0.1\n"
            "  If you genuinely intend this, set I_UNDERSTAND_THIS_IS_INSECURE=1 "
            "as well.\n"
            "  Otherwise unset the variable above -- which is almost certainly "
            "what you want."
        )

    @classmethod
    def from_env(cls) -> Settings:
        mode = _str("IDENTITY_MODE", "proxy").lower()
        if mode not in IDENTITY_PRESETS:
            known = ", ".join(sorted(IDENTITY_PRESETS))
            raise RuntimeError(f"IDENTITY_MODE must be one of: {known} (got {mode!r})")
        preset = IDENTITY_PRESETS[mode]

        fmt = _str("IDENTITY_HEADER_FORMAT", preset.fmt).lower()
        if fmt not in {"plain", "jwt"}:
            raise RuntimeError(
                f"IDENTITY_HEADER_FORMAT must be 'plain' or 'jwt', got {fmt!r}"
            )

        settings = cls(
            database_url=build_database_url(os.environ),
            app_database_url=build_app_database_url(os.environ),
            db_pool_min=_int("DB_POOL_MIN", 1),
            db_pool_max=_int("DB_POOL_MAX", 10),
            db_connect_timeout=float(_int("DB_CONNECT_TIMEOUT", 10)),
            run_migrations=_bool("RUN_MIGRATIONS", True),
            retirement_manifest=_str("RETIREMENT_MANIFEST"),
            retirement_rules_ack=_str("RETIREMENT_RULES_ACK"),
            identity_mode=mode,
            identity_header=_alias(
                "IDENTITY_HEADER", "AUTH_HEADER_EMAIL", preset.header
            ),
            identity_name_header=_alias(
                "IDENTITY_NAME_HEADER", "AUTH_HEADER_NAME", preset.name_header
            ),
            identity_id_header=_alias(
                "IDENTITY_ID_HEADER", "AUTH_HEADER_ID", preset.id_header
            ),
            identity_strip_prefix=_str("IDENTITY_STRIP_PREFIX", preset.strip_prefix),
            identity_header_format=fmt,
            identity_audience=_str("IDENTITY_AUDIENCE"),
            identity_jwt_email_claim=_str("IDENTITY_JWT_EMAIL_CLAIM", "email"),
            identity_jwt_name_claim=_str("IDENTITY_JWT_NAME_CLAIM", "name"),
            identity_jwt_id_claim=_str("IDENTITY_JWT_ID_CLAIM", "sub"),
            emergency_access_ids=frozenset(
                _csv("EMERGENCY_ACCESS_IDS") or _csv("EMERGENCY_ACCESS_ID")
            ),
            dev_insecure_auth=_bool("DEV_INSECURE_AUTH", False),
            insecure_auth_acknowledged=_bool("I_UNDERSTAND_THIS_IS_INSECURE", False),
            bind_host=_str("HOST", "0.0.0.0"),
            dev_identity_email=_alias(
                "DEV_IDENTITY_EMAIL", "DEV_IDENTITY_ID", "dev@localhost"
            ),
            dev_identity_name=_str("DEV_IDENTITY_NAME", "Local Dev (INSECURE)"),
            require_identity=_bool("REQUIRE_IDENTITY", True),
            cors_origins=_csv("CORS_ORIGINS"),
            csrf_trusted_sites=frozenset(
                _csv("CSRF_TRUSTED_SITES") or ["same-origin", "none"]
            ),
            proxy_shared_secret=_str("PROXY_SHARED_SECRET"),
            proxy_secret_header=_str("PROXY_SECRET_HEADER", "X-Proxy-Secret"),
            trusted_proxy_cidrs=_csv("TRUSTED_PROXY_CIDR"),
            request_body_limit_bytes=_int("REQUEST_BODY_LIMIT_BYTES", 1_048_576),
            rate_limit_window_seconds=_int("RATE_LIMIT_WINDOW_SECONDS", 60),
            rate_limit_max_requests=_int("RATE_LIMIT_MAX_REQUESTS", 240),
            log_level=_str("LOG_LEVEL", "info").lower(),
            log_format=_log_format(),
            port=_int("PORT", _int("API_PORT", 8000)),
            events_channel=_str("EVENTS_CHANNEL", "chai_events"),
            sse_keepalive_seconds=float(_int("SSE_KEEPALIVE_SECONDS", 15)),
            sse_queue_size=_int("SSE_QUEUE_SIZE", 256),
            sse_max_streams_per_user=_int("SSE_MAX_STREAMS_PER_USER", 8),
            sse_max_lifetime_seconds=float(_int("SSE_MAX_LIFETIME_SECONDS", 900)),
            idle_lock_minutes=_idle_lock_minutes(),
            sign_out_url=_sign_out_url(),
            agent_id_secret=_agent_id_secret(),
            agent_rate_limit_max_requests=_int("AGENT_RATE_LIMIT_MAX_REQUESTS", 60),
            agent_max_active_tokens=_int("AGENT_MAX_ACTIVE_TOKENS", 5),
            agent_extra_values=_agent_extra_values(),
            version=_str("APP_VERSION", "0.1.0"),
            log_page_size=_int("LOG_PAGE_SIZE", 60),
        )
        settings._reject_silent_misconfiguration()
        return settings
