"""Agent tokens: minting, verifying and revoking (#164, R-71, D-89).

An agent has no browser session, so it cannot come through the front door's single
sign-on. A signed-in person mints a bearer token in the app instead, and the token
is that person for one purpose: reading, through ``/api/agent/``, what their own
dashboard shows.

The token::

    agt_<id>.<secret>

* ``id`` is 16 hex characters. It is not a secret: it names the row, appears in the
  read trail and in the security log, and is what the rate limiter keys on.
* ``secret`` is 32 random bytes (256 bits), url-safe base64, 43 characters.
* Only SHA-256 of the whole token is stored. The token is shown once, in the
  response to the mint, and is never recoverable afterwards. A fast hash is right
  here: there is nothing short to guess, so a slow one would only slow every call.
* It lives exactly 8 hours (``TOKEN_LIFETIME``), and the database refuses any other
  lifetime (a CHECK in 013). It can be revoked by its owner, through the API, or by
  the operator, with ``scripts/agent_tokens.py``. It is deleted with its principal.

What this module never does: accept a token on any route but the agent routes (the
dependency in ``agent.py`` is the only caller of :func:`authenticate`), let a token
mint, list or revoke tokens (those routes take the session identity only), or put a
secret in a log line, a read-trail row or an error.

The opaque person id is here too, since both the token's owner and the people in a
project are shown to an agent the same way: ``HMAC-SHA256(secret, id)``, truncated.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

import asyncpg

TOKEN_PREFIX = "agt_"
TOKEN_LIFETIME = timedelta(hours=8)
LABEL_MAX_LENGTH = 64

# The id is hex so that it is safe in a log line, a path and a SQL literal alike.
_TOKEN_SHAPE = re.compile(r"^agt_(?P<id>[0-9a-f]{16})\.(?P<secret>[A-Za-z0-9_-]{43})$")
_LABEL_SHAPE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()-]{0,63}$")


class Refusal(StrEnum):
    """Why a token was refused. Recorded for the operator, never shown to the caller."""

    MALFORMED = "malformed"  # not the shape of a token, or no bearer header at all
    UNKNOWN = "unknown"  # a well-formed token that matches no row
    EXPIRED = "expired"
    REVOKED = "revoked"
    NOT_VISIBLE = "not_visible"  # a valid token asked for a project it may not see


class RevokedSource(StrEnum):
    USER = "user"
    OPERATOR = "operator"


@dataclass(frozen=True)
class AgentCaller:
    """Whom a verified token speaks for. Holds no secret and no name."""

    token_id: str
    user_id: str  # the identity id of the person who minted it
    expires_at: datetime


@dataclass(frozen=True)
class Presented:
    """What a request's Authorization header held, once parsed. Not yet verified."""

    token_id: str | None  # only ever a 16-hex string: safe to log and to key on
    token: str | None  # the whole token; kept out of every log


def parse_bearer(header: str | None) -> Presented:
    """Split an ``Authorization`` header. Anything that is not a token is empty."""
    if not header:
        return Presented(None, None)
    scheme, _, rest = header.strip().partition(" ")
    if scheme.lower() != "bearer":  # enum-ok: the HTTP Authorization scheme, RFC 6750
        return Presented(None, None)
    candidate = rest.strip()
    match = _TOKEN_SHAPE.fullmatch(candidate)
    if not match:
        return Presented(None, None)
    return Presented(match["id"], candidate)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def new_token() -> tuple[str, str, str]:
    """A fresh ``(token_id, token, hash)``. The token is returned to the caller once."""
    token_id = secrets.token_hex(8)
    token = f"{TOKEN_PREFIX}{token_id}.{secrets.token_urlsafe(32)}"
    return token_id, token, hash_token(token)


def opaque_id(secret: str, identity_id: str) -> str:
    """The id an agent is shown for a person: stable within a deployment, and not
    reversible without the secret. It is a pseudonym, not encryption: whoever holds
    the secret and a candidate list can test candidates, so the secret is kept like a
    password and is not in the database."""
    digest = hmac.new(
        secret.encode("utf-8"),
        b"chai-agent-person-v1:" + identity_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return "u_" + digest[:32]


def project_ref(secret: str, project_id: str) -> str:
    """The id an agent is shown for a project: ``pr_`` and 128 bits of HMAC-SHA256.

    A project's id is chosen by whoever creates it, so it can hold anything, a name
    included. A ref is stable within a deployment, tells nothing about the project and
    cannot be computed without the secret. The HMAC input carries its own domain
    prefix, so a ref and a person's id are never the same function of the same text.
    """
    digest = hmac.new(
        secret.encode("utf-8"),
        b"chai-agent-project-v1:" + project_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return "pr_" + digest[:32]


def label_problem(label: str) -> str | None:
    if label and not _LABEL_SHAPE.fullmatch(label):
        return (
            f"label may be up to {LABEL_MAX_LENGTH} letters, digits, spaces and "
            "the characters . _ ( ) -, starting with a letter or digit"
        )
    return None


# A constant to compare against when no row matched, so an unknown id and a wrong
# secret both do one hash comparison. Timing is best effort, not a guarantee.
_NO_HASH = hash_token("agt_0000000000000000." + "A" * 43)


@dataclass(frozen=True)
class Verified:
    caller: AgentCaller | None
    refusal: Refusal | None
    # The person the token belongs to, when the secret matched but it was expired or
    # revoked: whoever holds the secret is that person's agent, so the trail can say so.
    user_id: str | None = None
    # The presented id is a token that exists, whatever its secret was. Only then is a
    # refusal about a token somebody holds, and only then may it be a trail row.
    known_id: bool = False


async def authenticate(
    conn: asyncpg.Connection, presented: Presented, now: datetime
) -> Verified:
    """Check a presented token against the table. Never raises for a bad token."""
    if presented.token is None or presented.token_id is None:
        return Verified(None, Refusal.MALFORMED)
    row = await conn.fetchrow(
        "SELECT token_id, secret_hash, principal_id, expires_at, revoked_at "
        "FROM agent_token WHERE token_id = $1",
        presented.token_id,
    )
    stored = row["secret_hash"] if row else _NO_HASH
    matches = hmac.compare_digest(stored, hash_token(presented.token))
    if row is None or not matches:
        return Verified(None, Refusal.UNKNOWN, known_id=row is not None)
    if row["revoked_at"] is not None:
        return Verified(None, Refusal.REVOKED, row["principal_id"], True)
    if row["expires_at"] <= now:
        return Verified(None, Refusal.EXPIRED, row["principal_id"], True)
    return Verified(
        AgentCaller(row["token_id"], row["principal_id"], row["expires_at"]), None
    )


async def mint(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    name: str,
    email: str,
    label: str,
    now: datetime,
    max_active: int,
) -> tuple[str, str, datetime, datetime] | None:
    """Create a token for ``user_id``. Returns ``(token_id, token, created, expires)``,
    or ``None`` when they already hold ``max_active`` live ones."""
    # The principal row is what the token hangs from (and dies with). The recorder
    # writes it as people sign in, throttled and best effort, so it is made sure of
    # here, in the transaction, without changing a name or email already there.
    await conn.execute(
        "INSERT INTO principals (id, name, email) VALUES ($1, $2, $3) "
        "ON CONFLICT (id) DO NOTHING",
        user_id,
        name or "",
        email or "",
    )
    # Serialize one person's mints, so two at once cannot both pass the count.
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"agent:{user_id}")
    live = await conn.fetchval(
        "SELECT count(*) FROM agent_token WHERE principal_id = $1 "
        "AND revoked_at IS NULL AND expires_at > $2",
        user_id,
        now,
    )
    if live >= max_active:
        return None
    token_id, token, digest = new_token()
    created = now.astimezone(UTC)
    expires = created + TOKEN_LIFETIME
    await conn.execute(
        "INSERT INTO agent_token "
        "(token_id, secret_hash, principal_id, label, created_at, expires_at) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        token_id,
        digest,
        user_id,
        label,
        created,
        expires,
    )
    return token_id, token, created, expires


async def revoke(
    conn: asyncpg.Connection,
    *,
    token_id: str,
    user_id: str,
    now: datetime,
) -> bool:
    """Revoke one of ``user_id``'s own tokens. False when they hold no such token.
    Revoking one already revoked is not an error and changes nothing."""
    row = await conn.fetchrow(
        "SELECT revoked_at FROM agent_token WHERE token_id = $1 AND principal_id = $2 "
        "FOR UPDATE",
        token_id,
        user_id,
    )
    if row is None:
        return False
    if row["revoked_at"] is None:
        await conn.execute(
            "UPDATE agent_token SET revoked_at = $2, revoked_source = $3 "
            "WHERE token_id = $1",
            token_id,
            now,
            RevokedSource.USER.value,
        )
    return True
