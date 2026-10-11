"""Security events: named, structured, and separable from the application log (#38).

The only record of a delete, a purge, a rejected cross-site write, an out-of-range peer
or a 401 used to be a line of English on container stdout. `auth.py` says of a 401 that
it is "worth alerting on", and nothing could be: the signal was a substring of a
formatted sentence in an uncollected stream.

An event here has a **stable name** (``SecurityEvent``) and **fields**, and is
written as one JSON object per line tagged ``"stream": "security"``. That makes an
alert a field match, and lets a log sink keep the security stream for longer than
the application's chatter (45 CFR 164.308(a)(1)(ii)(D), 164.308(a)(6)(ii)).

Rules for what goes in an event:

* the names are an API. They are listed in docs/deploy.md and a test fails if the list
  and this enum drift apart, because an alert is written against them;
* actor and project ids, never a document, a token or a secret;
* every value is JSON-encoded, so an identity containing a quote or a newline stays
  inside its own string and cannot forge a second record.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from enum import StrEnum
from typing import IO, Any

SECURITY_LOGGER = "chai.security"
_HANDLER_MARK = "_chai_handler"

# Keys the formatter owns. A field that collides is kept under a prefixed name, so an
# event can never overwrite its own timestamp, level or name.
_RESERVED = {
    "ts",
    "level",
    "severity",
    "logger",
    "stream",
    "message",
    "event",
    "exc",
}


class LogFormat(StrEnum):
    JSON = "json"  # one object per line; security events named and tagged
    TEXT = "text"  # the human-readable line, for a terminal


class SecurityEvent(StrEnum):
    AUTH_NO_IDENTITY = "auth.no_identity"
    AUTH_PEER_REJECTED = "auth.peer_rejected"
    AUTH_SECRET_REJECTED = "auth.secret_rejected"
    AUTH_TOKEN_UNREADABLE = "auth.token_unreadable"
    AUTH_AUDIENCE_REJECTED = "auth.audience_rejected"
    CSRF_REJECTED = "csrf.rejected"
    ACCESS_DENIED = "access.denied"
    ACCESS_BREAKGLASS = "access.breakglass"
    PROJECT_CREATED = "project.created"
    PROJECT_DELETED = "project.deleted"
    VERSIONS_PURGED = "versions.purged"
    HOLD_PLACED = "hold.placed"
    HOLD_LIFTED = "hold.lifted"
    RETIREMENT_RULES_CHANGED = "retirement.rules_changed"
    RETIREMENT_RULES_REFUSED = "retirement.rules_refused"
    RATELIMIT_TRIPPED = "ratelimit.tripped"
    STREAM_REFUSED = "stream.refused"
    STREAM_ATTACHED = "stream.attached"
    RECORD_READ = "record.read"
    RECORD_EXPORTED = "record.exported"
    AGENT_TOKEN_MINTED = "agent_token.minted"
    AGENT_TOKEN_REVOKED = "agent_token.revoked"
    AGENT_REFUSED = "agent.refused"


_log = logging.getLogger(SECURITY_LOGGER)


def emit(
    event: SecurityEvent,
    message: str | None = None,
    *,
    level: int = logging.WARNING,
    **fields: Any,
) -> None:
    """Record one security event.

    ``message`` is the human-readable form (it is what ``LOG_FORMAT=text`` prints). When
    it is omitted one is built from the fields.
    """
    if message is None:
        message = " ".join([event.value] + [f"{k}={v!r}" for k, v in fields.items()])
    _log.log(
        level, message, extra={"security_event": event.value, "security_fields": fields}
    )


class JsonFormatter(logging.Formatter):
    """One JSON object per record, with the stream it belongs to."""

    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "security_event", None)
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )[:-3]
            + "Z",
            "level": record.levelname,
            # Cloud Logging reads `severity` to classify an entry; harmless elsewhere.
            "severity": record.levelname,
            "logger": record.name,
            "stream": "security" if event else "app",
            "message": record.getMessage(),
        }
        if event:
            out["event"] = event
            for key, value in (getattr(record, "security_fields", None) or {}).items():
                out[f"field_{key}" if key in _RESERVED else key] = value
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False, default=str)


def configure_logging(
    level: str = "info",
    fmt: LogFormat = LogFormat.JSON,
    stream: IO[str] | None = None,
) -> None:
    """Install the process's log handler. Idempotent: it replaces its own handler.

    The security logger is held at INFO whatever ``level`` says. A deployment that
    turns the application log down to WARNING must not thereby stop recording that a
    project was deleted.
    """
    fmt = LogFormat(fmt)  # a str is accepted; an unknown value raises
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stdout)
    setattr(handler, _HANDLER_MARK, True)
    handler.setFormatter(
        JsonFormatter()
        if fmt is LogFormat.JSON
        else logging.Formatter("%(asctime)s %(levelname)-8s %(name)s  %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    logging.getLogger(SECURITY_LOGGER).setLevel(logging.INFO)
