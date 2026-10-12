"""Settings, read from the environment once at startup. No secret is among them.

A token is a request's, never a setting: nothing here can hold one.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

DEFAULT_PORT = 8000
# Every request body is a JSON-RPC message of a few hundred bytes.
DEFAULT_MAX_BODY_BYTES = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_IN_FLIGHT = 16
# The host names a request may carry whatever is configured: this machine, which is
# what the container's own health check and a local test use.
LOOPBACK_HOSTS = ("127.0.0.1:*", "localhost:*", "[::1]:*")


class ConfigError(ValueError):
    """The service refuses to start: a setting is missing or unsafe."""


def _split(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _positive(env: Mapping[str, str], name: str, default: float) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if value <= 0:
        raise ConfigError(f"{name} must be greater than zero")
    return value


def _is_http(scheme: str) -> bool:
    return scheme in {"http", "https"}  # enum-ok: URL scheme names (RFC 3986)


def _base_url(raw: str) -> str:
    """The agent API's address. A plain http(s) URL with no credentials, no query and
    no fragment: the token is sent only to this one place."""
    parts = urlsplit(raw)
    if not _is_http(parts.scheme) or not parts.hostname:
        raise ConfigError("API_BASE_URL must be an http or https URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ConfigError(
            "API_BASE_URL must not carry credentials, a query or a fragment"
        )
    return raw.rstrip("/")


def _origin(raw: str) -> str:
    parts = urlsplit(raw)
    if not _is_http(parts.scheme) or not parts.netloc or parts.path:
        raise ConfigError(
            f"MCP_ALLOWED_ORIGINS holds origins (scheme and host, no path), not {raw!r}"
        )
    return raw


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    allowed_hosts: tuple[str, ...]
    allowed_origins: tuple[str, ...] = ()
    port: int = DEFAULT_PORT
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_in_flight: int = DEFAULT_MAX_IN_FLIGHT
    hosts_with_loopback: tuple[str, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "hosts_with_loopback", (*self.allowed_hosts, *LOOPBACK_HOSTS)
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env
        base = (env.get("API_BASE_URL") or "").strip()
        if not base:
            raise ConfigError("set API_BASE_URL (the agent API's internal address)")
        hosts = _split(env.get("MCP_ALLOWED_HOSTS") or "")
        if not hosts:
            raise ConfigError(
                "set MCP_ALLOWED_HOSTS to the host name people reach this service by "
                "(for example governance.example.org). A request for any other host "
                "is refused: that is the protection against DNS rebinding."
            )
        port_raw = (env.get("MCP_PORT") or str(DEFAULT_PORT)).strip()
        if not port_raw.isdigit() or not 0 < int(port_raw) < 65536:
            raise ConfigError("MCP_PORT must be a port number")
        return cls(
            api_base_url=_base_url(base),
            allowed_hosts=tuple(hosts),
            allowed_origins=tuple(
                _origin(o) for o in _split(env.get("MCP_ALLOWED_ORIGINS") or "")
            ),
            port=int(port_raw),
            max_body_bytes=int(
                _positive(env, "MCP_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)
            ),
            timeout_seconds=_positive(
                env, "MCP_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS
            ),
            max_in_flight=int(
                _positive(env, "MCP_MAX_IN_FLIGHT", DEFAULT_MAX_IN_FLIGHT)
            ),
        )
