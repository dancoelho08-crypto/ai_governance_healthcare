"""The read-only agent API and the routes that mint its tokens (#164, R-71, D-89).

Two routers, kept apart on purpose, because they answer to different credentials:

``token_router`` (``/api/agent-tokens``)
    Mint, list and revoke a person's own tokens. These take the SESSION identity,
    the one the front door asserts, exactly like every other route. A bearer token is
    never read here, so a token can never mint, list or revoke a token.

``agent_router`` (``/api/agent/``)
    Three GET routes that answer to a bearer token and to nothing else. The identity
    header is ignored on them, whatever it says, so a client that forges one gains
    nothing. This is the only place a token is accepted.

What an agent is told is built, field by field, from an allowlist: a new model per
response, filled from the stored document by functions that read only the keys named
here and shape-check each value. A stored document is never copied or filtered into a
response, so a field added to the document tomorrow cannot reach an agent by
accident. In particular no name, no email and no free text is ever returned: not a
note, not a rationale, not an evidence title, not the free-text "owner" or "by" a
person typed. People are opaque ids (``agent_tokens.opaque_id``).

What it returns is what the record STORES: statuses, decisions, dates, and one
comparison of a stored due date with today's date (UTC). No phase, no flag, no color,
no score, no verdict: those are the dashboard's computations and the dashboard is where
they are shown.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .access import access_of, readable_rows
from .accessaudit import AccessAction, AccessVia, record_access
from .agent_limits import AgentGuard, FailureVerdict, RowKind
from .agent_tokens import (
    LABEL_MAX_LENGTH,
    AgentCaller,
    Presented,
    Refusal,
    RevokedSource,
    authenticate,
    label_problem,
    mint,
    opaque_id,
    parse_bearer,
    project_ref,
    revoke,
)
from .auth import Identity, check_network_locks, client_address
from .config import AGENT_VALUE_SHAPE, Settings
from .db import Database
from .principals import NOT_PEOPLE
from .retirement import FrameworkRole, record_framework
from .routes import get_db, get_identity, get_settings
from .securitylog import SecurityEvent, emit

log = logging.getLogger("chai.agent")

AGENT_PREFIX = "/api/agent/"

# Result sizes are capped, so one call cannot return the whole database.
DEFAULT_LIMIT = 50
MAX_LIMIT = 100
MAX_OFFSET = 100_000
MAX_ITEMS_PER_PROJECT = 500
MAX_PEOPLE_PER_ROLE = 100
MAX_LISTED_TOKENS = 50


def is_agent_path(path: str) -> bool:
    """Is this a path the bearer routes serve? Exactly the ``/api/agent/`` prefix:
    ``/api/agent-tokens`` is a different route, answered to a session."""
    return path.startswith(AGENT_PREFIX)


class TokenState(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


# --- what an agent is shown --------------------------------------------------


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentMeOut(_Out):
    """``GET /api/agent/me``: who this token speaks for, as an opaque id."""

    user: str = Field(description="The token's owner, as an opaque id (u_ + 32 hex).")
    token_id: str = Field(description="This token's public id. Not the secret.")
    expires_at: datetime = Field(description="When this token stops working (UTC).")
    as_of: date = Field(description="Today's date in UTC, the date overdue uses.")


class AgentItem(_Out):
    """One answered item, as stored. No notes, owner text or evidence."""

    id: str = Field(
        description="The item's id, returned only if its framework's definition has it."
    )
    status: str | None = Field(
        description="The stored status; null when none, or not a known value."
    )
    due: date | None = Field(description="The stored due date; null when none.")
    overdue: bool = Field(
        description=(
            "True only when the stored due date is before today (UTC). A plain date "
            "comparison: the status is not consulted, so a settled item with an old "
            "due date reads true."
        )
    )


class AgentGate(_Out):
    """One checkpoint, as stored. No rationale and no committee name."""

    id: str = Field(
        description="The checkpoint's id, returned only if its definition has it."
    )
    decision: str | None = Field(description="The stored decision; null when none.")
    decided_on: date | None = Field(description="The stored decision date.")
    signed_by: str | None = Field(
        description="Who recorded the decision, as an opaque id, where stored."
    )
    signed_at: datetime | None = Field(
        description="When the server recorded it, where stored."
    )


class AgentSupplement(_Out):
    """A supplementary framework's answers on the same project (OPTICA's, say)."""

    framework: str
    enabled: bool
    items: list[AgentItem]


class AgentPeople(_Out):
    """Who may open the project, as opaque ids, never names or emails."""

    owners: list[str]
    writers: list[str]
    readers: list[str]
    truncated: bool = Field(
        description=f"True when a list was cut at {MAX_PEOPLE_PER_ROLE} ids."
    )


class AgentProject(_Out):
    ref: str = Field(
        description=(
            "An opaque reference to the project (pr_ and 32 hex characters), stable in "
            "a deployment. The project's own id is chosen by whoever made it, so it "
            "is never returned."
        )
    )
    framework: str | None = Field(
        description=(
            "The framework the record follows: its stamp, or 'chai'. Null when it is "
            "not a framework of this build."
        )
    )
    updated_at: datetime
    updated_by: str | None = Field(description="Opaque id of the last editor.")
    people: AgentPeople
    items: list[AgentItem]
    items_truncated: bool = Field(
        description=f"True when more than {MAX_ITEMS_PER_PROJECT} items were stored."
    )
    gates: list[AgentGate]
    supplements: list[AgentSupplement]
    has_overdue: bool = Field(description="True when any item above is overdue.")


class AgentPortfolioOut(_Out):
    as_of: date = Field(description="Today's date in UTC, the date overdue uses.")
    total: int = Field(description="Projects matching the filters, before paging.")
    limit: int
    offset: int
    next_offset: int | None = Field(
        description="The offset of the next page, or null on the last."
    )
    projects: list[AgentProject]


# --- the allowlisted readers: each takes only the keys it names ----------------

_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_OPAQUE = re.compile(r"^u_[0-9a-f]{32}$")
_REF = re.compile(r"^pr_[0-9a-f]{32}$")


class VocabKind(StrEnum):
    """The kinds of word ``agent_vocabulary`` holds (014); the CHECK lists the same."""

    FRAMEWORK = "framework"
    ITEMS = "items"
    GATES = "gates"
    STATUSES = "statuses"
    DECISIONS = "decisions"


class Vocabulary:
    """The words of the deployed build's framework definitions, loaded from
    ``agent_vocabulary``. An item id, checkpoint id, supplement id, status or
    decision is returned to an agent only if it is one of them, for the framework it
    belongs to. Anything else a record stores under those keys is whatever a writer
    typed, and is dropped, not shaped: no pattern can tell a name from an id, a list
    of the ids can (D-89). Empty, so nothing is returned, when no manifest was loaded.
    """

    def __init__(self, rows: list[tuple[str, str, str]] | None = None) -> None:
        self._words: dict[tuple[str, str], set[str]] = {}
        for framework_id, kind, value in rows or []:
            self._words.setdefault((framework_id, kind), set()).add(value)

    @classmethod
    async def load(cls, conn: asyncpg.Connection) -> Vocabulary:
        rows = await conn.fetch(
            "SELECT framework_id, kind, value FROM agent_vocabulary"
        )
        return cls([(r["framework_id"], r["kind"], r["value"]) for r in rows])

    def role(self, framework_id: Any) -> FrameworkRole | None:
        """A framework's role in the build, or None if the build has no such one."""
        if not isinstance(framework_id, str):
            return None
        roles = self._words.get((framework_id, VocabKind.FRAMEWORK.value))
        return FrameworkRole(next(iter(roles))) if roles else None

    def _has(self, framework_id: str | None, kind: VocabKind, word: Any) -> bool:
        return (
            framework_id is not None
            and isinstance(word, str)
            and word in self._words.get((framework_id, kind.value), ())
        )

    def item(self, framework_id: str | None, key: Any) -> bool:
        return self._has(framework_id, VocabKind.ITEMS, key)

    def gate(self, framework_id: str | None, key: Any) -> bool:
        return self._has(framework_id, VocabKind.GATES, key)

    def status(self, framework_id: str | None, value: Any) -> str | None:
        return value if self._has(framework_id, VocabKind.STATUSES, value) else None

    def decision(self, framework_id: str | None, value: Any) -> str | None:
        return value if self._has(framework_id, VocabKind.DECISIONS, value) else None


def _day(value: Any) -> date | None:
    if not isinstance(value, str) or not _DAY.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _instant(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _items(
    answers: Any, vocab: Vocabulary, framework_id: str | None, today: date
) -> tuple[list[AgentItem], bool]:
    if not isinstance(answers, dict):
        return [], False
    found: list[AgentItem] = []
    for key in sorted(k for k in answers if vocab.item(framework_id, k)):
        answer = answers[key]
        if not isinstance(answer, dict):
            continue
        status = vocab.status(framework_id, answer.get("status"))
        due = _day(answer.get("due"))
        if status is None and due is None:
            continue
        found.append(
            AgentItem(
                id=key,
                status=status,
                due=due,
                overdue=due is not None and due < today,
            )
        )
    return found[:MAX_ITEMS_PER_PROJECT], len(found) > MAX_ITEMS_PER_PROJECT


def _gates(
    gates: Any,
    vocab: Vocabulary,
    framework_id: str | None,
    person: Callable[[Any], str | None],
) -> list[AgentGate]:
    if not isinstance(gates, dict):
        return []
    found: list[AgentGate] = []
    for key in sorted(k for k in gates if vocab.gate(framework_id, k)):
        gate = gates[key]
        if not isinstance(gate, dict):
            continue
        decision = vocab.decision(framework_id, gate.get("decision"))
        decided_on = _day(gate.get("date"))
        signed_by = person(gate.get("signedBy"))
        signed_at = _instant(gate.get("signedAt"))
        if decision is None and decided_on is None and signed_by is None:
            continue
        found.append(
            AgentGate(
                id=key,
                decision=decision,
                decided_on=decided_on,
                signed_by=signed_by,
                signed_at=signed_at,
            )
        )
    return found


def build_project(
    row: asyncpg.Record,
    *,
    secret: str,
    vocab: Vocabulary,
    today: date,
) -> AgentProject:
    """One project as an agent sees it, from an allowlist of stored keys."""
    doc = row["doc"] if isinstance(row["doc"], dict) else {}

    def person(value: Any) -> str | None:
        return opaque_id(secret, value) if isinstance(value, str) and value else None

    access = access_of(doc)

    def opaque_list(ids: list[str]) -> list[str]:
        return [opaque_id(secret, i) for i in ids[:MAX_PEOPLE_PER_ROLE] if i]

    people = AgentPeople(
        owners=opaque_list(access["owners"]),
        writers=opaque_list(access["writers"]),
        readers=opaque_list(access["readers"]),
        truncated=any(len(v) > MAX_PEOPLE_PER_ROLE for v in access.values()),
    )
    primary = record_framework(doc)
    framework = primary if vocab.role(primary) is FrameworkRole.PRIMARY else None
    items, truncated = _items(doc.get("items"), vocab, framework, today)
    supplements: list[AgentSupplement] = []
    for key in sorted(k for k in doc if vocab.role(k) is FrameworkRole.SUPPLEMENT):
        value = doc[key]
        if not isinstance(value, dict) or not isinstance(value.get("answers"), dict):
            continue
        extra, _ = _items(value["answers"], vocab, key, today)
        supplements.append(
            AgentSupplement(
                framework=key, enabled=value.get("enabled") is True, items=extra
            )
        )
    return AgentProject(
        ref=project_ref(secret, row["id"]),
        framework=framework,
        updated_at=row["updated_at"],
        updated_by=person(row["updated_by"]),
        people=people,
        items=items,
        items_truncated=truncated,
        gates=_gates(doc.get("gates"), vocab, framework, person),
        supplements=supplements,
        has_overdue=any(i.overdue for i in items)
        or any(i.overdue for s in supplements for i in s.items),
    )


# --- who is calling ------------------------------------------------------------


def _unauthorized() -> HTTPException:
    """The one answer to every bad token. Expired, revoked, unknown, malformed and
    absent are the same status, the same body and the same header, so the response
    tells a guesser nothing about which it was."""
    return HTTPException(
        status_code=401,
        detail="Invalid or expired token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def now_of(request: Request) -> datetime:
    """The clock the agent API uses. A test replaces ``app.state.clock``."""
    return request.app.state.clock()


def _route_of(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", AGENT_PREFIX)[:120]


async def _record_refusal(
    db: Database,
    request: Request,
    presented: Presented,
    reason: Refusal,
    user_id: str | None,
    detail_extra: dict[str, Any] | None = None,
) -> None:
    """Write a refused call to the read trail and the security log. Never raises: a
    trail that cannot be written must not turn a 401 into a 500 that says more.

    Called only for a token that exists (and so is attributable), after the guard has
    allowed a row: see ``agent_limits``."""
    detail: dict[str, Any] = {
        "route": _route_of(request),
        "reason": reason.value,
        # A proxy that works strips this on the agent route; one that does not shows.
        "identity_header_ignored": _carries_identity_header(request),
        **(detail_extra or {}),
    }
    try:
        async with db.acquire() as conn:
            await record_access(
                conn,
                Identity(id=user_id or "unknown", name="", email=""),
                AccessAction.AGENT_REFUSED,
                request,
                detail=detail,
                via=AccessVia.AGENT,
                token_id=presented.token_id,
            )
    except Exception as exc:
        log.warning("could not record a refused agent call: %s", type(exc).__name__)


def _carries_identity_header(request: Request) -> bool:
    settings: Settings = request.app.state.settings
    return bool((request.headers.get(settings.identity_header) or "").strip())


def _too_many(window: int) -> HTTPException:
    return HTTPException(
        429,
        "Too many requests; please retry shortly.",
        headers={"Retry-After": str(window)},
    )


async def get_agent(
    request: Request,
    settings: Settings = Depends(get_settings),
    db: Database = Depends(get_db),
) -> AgentCaller:
    """The caller a bearer token speaks for, or a uniform 401.

    The identity header is not read here and is never consulted: a request carrying
    both is a bearer request, and the header is ignored. Nothing about the session
    is trusted on this route. The token is read from the Authorization header and
    from nowhere else (not a query parameter, not a cookie).

    The token is checked FIRST, and only then is anything limited
    (``agent_limits``): a verified token spends its own allowance and nobody's
    source address; a failure spends its source's, and writes a trail row only for a
    token that exists, within a bound.
    """
    if not settings.agent_api_enabled:
        raise HTTPException(404, "Not Found")
    check_network_locks(request, settings)
    guard: AgentGuard = request.app.state.agent_guard
    presented = parse_bearer(request.headers.get("authorization"))
    async with db.acquire() as conn:
        verified = await authenticate(conn, presented, now_of(request))
    if verified.caller is not None:
        if not await guard.allow_token(verified.caller.token_id):
            raise _too_many(guard.window)
        if not await guard.allow_user(verified.caller.user_id):
            raise _too_many(guard.window)
        request.state.agent_presented = presented
        return verified.caller
    assert verified.refusal is not None
    source = client_address(request, settings)
    if guard.charge_failure(source) is not FailureVerdict.ALLOW:
        raise _too_many(guard.window)
    # A wrong secret can be sent by anybody who has seen a public id; a right secret
    # on a token that stopped working is its holder. Separate budgets, so a flood of
    # the first cannot starve the second.
    kind = (
        RowKind.RIGHT_SECRET
        if verified.refusal in (Refusal.REVOKED, Refusal.EXPIRED)
        else RowKind.WRONG_SECRET
    )
    if (
        verified.known_id
        and presented.token_id
        and guard.may_write_row(kind, presented.token_id)
    ):
        await _record_refusal(
            db, request, presented, verified.refusal, verified.user_id
        )
    raise _unauthorized()


def _as_identity(caller: AgentCaller) -> Identity:
    """The caller as the read trail's actor. Never emergency: an agent has no
    break-glass, whoever minted the token (R-71)."""
    return Identity(id=caller.user_id, name="", email="", emergency=False)


async def _used(conn: asyncpg.Connection, caller: AgentCaller, now: datetime) -> None:
    await conn.execute(
        "UPDATE agent_token SET last_used_at = $2 WHERE token_id = $1",
        caller.token_id,
        now,
    )


agent_router = APIRouter(prefix="/api/agent", tags=["agent (read-only)"])

RefPath = Path(
    ...,
    pattern=_REF.pattern,
    description="A project reference (pr_ and 32 hex characters), from the portfolio.",
)

_UNAUTHORIZED = {
    401: {"description": "No token, or one that is wrong, expired or revoked."},
    403: {"description": "The request did not come through the authenticating proxy."},
    404: {"description": "The agent API is not enabled on this server."},
    429: {"description": "Too many requests for this token."},
}

# What every session route (the token routes) can say before its own answers.
_SESSION = {
    401: {"description": "No identity: the request did not come through the proxy."},
    403: {
        "description": "Refused: not a signed-in person, cross-site, or not proxied."
    },
    429: {"description": "Too many requests."},
}


@agent_router.get(
    "/me", response_model=AgentMeOut, responses=_UNAUTHORIZED, summary="Whose token"
)
async def agent_me(
    request: Request,
    caller: AgentCaller = Depends(get_agent),
    settings: Settings = Depends(get_settings),
    db: Database = Depends(get_db),
) -> AgentMeOut:
    now = now_of(request)
    async with db.acquire() as conn, conn.transaction():
        await record_access(
            conn,
            _as_identity(caller),
            AccessAction.AGENT_ME,
            request,
            detail={"route": _route_of(request)},
            via=AccessVia.AGENT,
            token_id=caller.token_id,
        )
        await _used(conn, caller, now)
    return AgentMeOut(
        user=opaque_id(settings.agent_id_secret, caller.user_id),
        token_id=caller.token_id,
        expires_at=caller.expires_at,
        as_of=now.astimezone(UTC).date(),
    )


_WORD = {"pattern": AGENT_VALUE_SHAPE.pattern, "max_length": 64}


@agent_router.get(
    "/portfolio",
    response_model=AgentPortfolioOut,
    responses={**_UNAUTHORIZED, 422: {"description": "A parameter is not valid."}},
    summary="The projects this user's dashboard shows",
)
async def agent_portfolio(
    request: Request,
    caller: AgentCaller = Depends(get_agent),
    settings: Settings = Depends(get_settings),
    db: Database = Depends(get_db),
    item_status: str | None = Query(
        None,
        alias="status",
        description="Only projects with an item (or supplement item) in this status.",
        **_WORD,
    ),
    decision: str | None = Query(
        None,
        description="Only projects with a checkpoint holding this decision.",
        **_WORD,
    ),
    overdue: bool | None = Query(
        None, description="true: has an overdue item. false: has none."
    ),
    overdue_since: date | None = Query(
        None,
        description=(
            "Only projects with an overdue item whose due date is on or after this "
            "date (YYYY-MM-DD)."
        ),
    ),
    overdue_before: date | None = Query(
        None,
        description=(
            "Only projects with an overdue item whose due date is before this date "
            "(YYYY-MM-DD)."
        ),
    ),
    owner: str | None = Query(
        None,
        description="Only projects this person owns, by opaque id (from this API).",
        pattern=_OPAQUE.pattern,
    ),
    framework: str | None = Query(
        None,
        description="Only projects whose record follows this framework id.",
        pattern=_KEY.pattern,
    ),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
) -> AgentPortfolioOut:
    now = now_of(request)
    today = now.astimezone(UTC).date()
    async with db.acquire() as conn, conn.transaction():
        vocab = await Vocabulary.load(conn)
        rows = await readable_rows(conn, caller.user_id, enforced=True)
        built = [
            (
                row,
                build_project(
                    row, secret=settings.agent_id_secret, vocab=vocab, today=today
                ),
            )
            for row in rows
            if not (row["doc"] or {}).get("archived")
        ]
        matching = [
            (row, p)
            for row, p in built
            if _matches(
                p,
                item_status=item_status,
                decision=decision,
                overdue=overdue,
                overdue_since=overdue_since,
                overdue_before=overdue_before,
                owner=owner,
                framework=framework,
            )
        ]
        page_rows = [row for row, _ in matching[offset : offset + limit]]
        page = [p for _, p in matching[offset : offset + limit]]
        filters = {
            k: (v.isoformat() if isinstance(v, date) else v)
            for k, v in {
                "status": item_status,
                "decision": decision,
                "overdue": overdue,
                "overdue_since": overdue_since,
                "overdue_before": overdue_before,
                "owner": owner,
                "framework": framework,
            }.items()
            if v is not None
        }
        await record_access(
            conn,
            _as_identity(caller),
            AccessAction.AGENT_PORTFOLIO,
            request,
            detail={
                "route": _route_of(request),
                "count": len(page),
                "total": len(matching),
                "offset": offset,
                "projects": [r["id"] for r in page_rows],
                "filters": filters,
            },
            via=AccessVia.AGENT,
            token_id=caller.token_id,
        )
        await _used(conn, caller, now)
    more = offset + limit < len(matching)
    return AgentPortfolioOut(
        as_of=today,
        total=len(matching),
        limit=limit,
        offset=offset,
        next_offset=offset + limit if more else None,
        projects=page,
    )


def _matches(
    p: AgentProject,
    *,
    item_status: str | None,
    decision: str | None,
    overdue: bool | None,
    overdue_since: date | None,
    overdue_before: date | None,
    owner: str | None,
    framework: str | None,
) -> bool:
    every = [*p.items, *(i for s in p.supplements for i in s.items)]
    if item_status is not None and not any(i.status == item_status for i in every):
        return False
    if decision is not None and not any(g.decision == decision for g in p.gates):
        return False
    if overdue is not None and p.has_overdue is not overdue:
        return False
    late = [i.due for i in every if i.overdue and i.due is not None]
    if overdue_since is not None and not any(d >= overdue_since for d in late):
        return False
    if overdue_before is not None and not any(d < overdue_before for d in late):
        return False
    if owner is not None and owner not in p.people.owners:
        return False
    return framework is None or p.framework == framework


@agent_router.get(
    "/projects/{ref}",
    response_model=AgentProject,
    responses={
        **_UNAUTHORIZED,
        404: {
            "description": (
                "No such project, or not one this user's dashboard shows; or the "
                "agent API is not enabled."
            )
        },
        422: {"description": "The reference is not a reference."},
    },
    summary="One project, by the reference the portfolio gave",
)
async def agent_project(
    request: Request,
    ref: str = RefPath,
    caller: AgentCaller = Depends(get_agent),
    settings: Settings = Depends(get_settings),
    db: Database = Depends(get_db),
) -> AgentProject:
    now = now_of(request)
    today = now.astimezone(UTC).date()
    found: AgentProject | None = None
    project_id: str | None = None
    async with db.acquire() as conn, conn.transaction():
        vocab = await Vocabulary.load(conn)
        # A ref is resolved by looking at what this person's dashboard shows, and
        # nothing else: no lookup by project id, so a ref for a project the person
        # cannot open, one that is archived and one that does not exist are alike.
        for row in await readable_rows(conn, caller.user_id, enforced=True):
            if (row["doc"] or {}).get("archived"):
                continue
            if project_ref(settings.agent_id_secret, row["id"]) == ref:
                project_id = row["id"]
                found = build_project(
                    row, secret=settings.agent_id_secret, vocab=vocab, today=today
                )
                break
        if found is not None:
            await record_access(
                conn,
                _as_identity(caller),
                AccessAction.AGENT_PROJECT,
                request,
                project_id=project_id,
                detail={"route": _route_of(request)},
                via=AccessVia.AGENT,
                token_id=caller.token_id,
            )
            await _used(conn, caller, now)
    if found is None:
        # Nothing was disclosed. A call by a token that verified, so it is
        # attributable and limited by that token's own allowance.
        guard: AgentGuard = request.app.state.agent_guard
        if guard.may_write_row(RowKind.NOT_VISIBLE, caller.token_id):
            await _record_refusal(
                db,
                request,
                request.state.agent_presented,
                Refusal.NOT_VISIBLE,
                caller.user_id,
                {"ref": ref},
            )
        raise HTTPException(404, "No such project")
    return found


# --- minting, listing and revoking: the session's, never a token's ------------


token_router = APIRouter(prefix="/api/agent-tokens", tags=["agent tokens (session)"])


class TokenMintIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(
        default="",
        max_length=LABEL_MAX_LENGTH,
        description="A name for your own list, e.g. 'Claude on my laptop'.",
    )


class TokenMintOut(BaseModel):
    id: str = Field(description="The token's public id.")
    token: str = Field(description="The token. Shown this once and never again.")
    label: str
    created_at: datetime
    expires_at: datetime = Field(description="Exactly 8 hours after created_at.")


class TokenOut(BaseModel):
    id: str
    label: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    state: TokenState


TokenIdPath = Path(..., pattern=r"^[0-9a-f]{16}$", description="A token's public id.")


def _need_agent_api(settings: Settings) -> None:
    if not settings.agent_api_enabled:
        raise HTTPException(
            404, "The agent API is not enabled on this server (AGENT_ID_SECRET)."
        )


def _need_a_person(identity: Identity, settings: Settings) -> None:
    if identity.id in NOT_PEOPLE or not settings.require_identity:
        raise HTTPException(
            403,
            "Tokens are minted for a signed-in person, and this server is not "
            "identifying one.",
        )


@token_router.post(
    "",
    response_model=TokenMintOut,
    status_code=201,
    responses={
        **_SESSION,
        409: {"description": "You already hold the most tokens allowed."},
        404: {"description": "The agent API is not enabled."},
        422: {"description": "The label is not valid."},
    },
    summary="Mint a token for yourself",
)
async def mint_token(
    body: TokenMintIn,
    response: Response,
    request: Request,
    identity: Identity = Depends(get_identity),
    settings: Settings = Depends(get_settings),
    db: Database = Depends(get_db),
) -> TokenMintOut:
    """A token for the signed-in person, valid for 8 hours. It is in this response
    only: the server keeps a hash. It reads what your own dashboard shows, and it
    cannot write, and cannot mint, list or revoke tokens."""
    _need_agent_api(settings)
    _need_a_person(identity, settings)
    problem = label_problem(body.label.strip())
    if problem:
        raise HTTPException(422, problem)
    async with db.acquire() as conn, conn.transaction():
        minted = await mint(
            conn,
            user_id=identity.id,
            name=identity.name,
            email=identity.email,
            label=body.label.strip(),
            now=now_of(request),
            max_active=settings.agent_max_active_tokens,
        )
    if minted is None:
        raise HTTPException(
            409,
            f"You already hold {settings.agent_max_active_tokens} active tokens. "
            "Revoke one, or wait for one to expire.",
        )
    token_id, token, created, expires = minted
    emit(
        SecurityEvent.AGENT_TOKEN_MINTED,
        f"agent token {token_id} minted by {identity.id}",
        level=logging.INFO,
        actor=identity.id,
        token_id=token_id,
        expires_at=expires.isoformat(),
    )
    response.headers["Cache-Control"] = "no-store"
    return TokenMintOut(
        id=token_id,
        token=token,
        label=body.label.strip(),
        created_at=created,
        expires_at=expires,
    )


@token_router.get(
    "",
    response_model=list[TokenOut],
    summary="Your own tokens",
    responses={**_SESSION, 404: {"description": "The agent API is not enabled."}},
)
async def list_tokens(
    request: Request,
    identity: Identity = Depends(get_identity),
    settings: Settings = Depends(get_settings),
    db: Database = Depends(get_db),
) -> list[TokenOut]:
    """Your tokens, newest first: ids, labels and dates. Never a secret."""
    _need_agent_api(settings)
    now = now_of(request)
    async with db.acquire() as conn:
        rows = await conn.fetch(
            "SELECT token_id, label, created_at, expires_at, revoked_at, "
            "last_used_at FROM agent_token WHERE principal_id = $1 "
            "ORDER BY created_at DESC LIMIT $2",
            identity.id,
            MAX_LISTED_TOKENS,
        )
    return [
        TokenOut(
            id=r["token_id"],
            label=r["label"],
            created_at=r["created_at"],
            expires_at=r["expires_at"],
            revoked_at=r["revoked_at"],
            last_used_at=r["last_used_at"],
            state=(
                TokenState.REVOKED
                if r["revoked_at"] is not None
                else TokenState.EXPIRED
                if r["expires_at"] <= now
                else TokenState.ACTIVE
            ),
        )
        for r in rows
    ]


@token_router.delete(
    "/{token_id}",
    status_code=204,
    summary="Revoke one of your own tokens",
    responses={
        **_SESSION,
        404: {
            "description": "You hold no such token, or the agent API is not enabled."
        },
        422: {"description": "The token id is not valid."},
    },
)
async def revoke_token(
    request: Request,
    token_id: str = TokenIdPath,
    identity: Identity = Depends(get_identity),
    settings: Settings = Depends(get_settings),
    db: Database = Depends(get_db),
) -> Response:
    _need_agent_api(settings)
    async with db.acquire() as conn, conn.transaction():
        done = await revoke(
            conn, token_id=token_id, user_id=identity.id, now=now_of(request)
        )
    if not done:
        raise HTTPException(404, "No such token")
    emit(
        SecurityEvent.AGENT_TOKEN_REVOKED,
        f"agent token {token_id} revoked by {identity.id}",
        level=logging.INFO,
        actor=identity.id,
        token_id=token_id,
        by=RevokedSource.USER.value,
    )
    return Response(status_code=204)
