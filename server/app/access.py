"""Per-project access control, enforced.

This mirrors ``app/js/00-core/15-access.js``. The browser copy decides what to
SHOW; this one decides what the server will ACCEPT, and only the second is a
control. Anyone can open the console and flip a flag in the first. Keep the two
in step: a permission added there and not here is a label, not a rule.

The model, in one line each:

* **owner**  -- delete, archive, purge history, and change who else has access
* **writer** -- fill in the review
* **reader** -- see it, change nothing

Two deliberate holes, both load-bearing:

1. **A project with no owners is unrestricted.** Records created before access
   control existed have no owner list. Treating that as "nobody may touch it"
   would lock a team out of its own governance history, so it reads as "not yet
   claimed". The first person to claim it becomes its owner.

2. **With identity disabled, everything is permitted.** If the deployment is
   not behind an identity-providing proxy there is nobody to check a list
   against, and pretending otherwise would be security theater. The API says so
   at /api/health rather than quietly allowing everything.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import asyncpg
from fastapi import HTTPException, status

from .securitylog import SecurityEvent, emit


class Level(StrEnum):
    """What a request needs on a project. ``require`` checks it; a denial logs it."""

    READ = "read"
    WRITE = "write"
    OWN = "own"


def denied(
    user_id: str | None,
    project_id: str | None,
    need: Level,
    held: str,
    code: int,
) -> None:
    """Record one denial. The caller raises its own exception.

    The single place an authorization refusal is recorded (#53). It used to be
    nowhere, so a compromised account probing other people's records left no
    trace: the only record was Caddy's uncollected access log, which cannot tell
    a denial from a hit. The name `access.denied` is stable so an alert can match
    it without parsing prose. `%r` quotes the actor and project so a crafted id
    cannot forge a second log line.

    It logs who, which project, what was needed, what they held and what the
    caller will be told. Never the document: the project id is necessary and its
    contents are exactly what the denial protected.
    """
    emit(
        SecurityEvent.ACCESS_DENIED,
        f"access.denied actor={user_id!r} project={project_id!r} need={need} "
        f"held={held or 'none'} status={code}",
        actor=user_id,
        project=project_id,
        need=need,
        held=held or "none",
        status=code,
    )


ROLES = ("owner", "writer", "reader")


def _listed(access: dict[str, Any], key: str) -> list[str]:
    value = access.get(key)
    return [str(v) for v in value] if isinstance(value, list) else []


def access_of(doc: dict[str, Any]) -> dict[str, list[str]]:
    raw = doc.get("access") if isinstance(doc, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    return {
        "owners": _listed(raw, "owners"),
        "writers": _listed(raw, "writers"),
        "readers": _listed(raw, "readers"),
    }


def unclaimed(doc: dict[str, Any]) -> bool:
    """No owner recorded: open, and claimable. See hole 1 in the module docs."""
    return not access_of(doc)["owners"]


def role_of(doc: dict[str, Any], user_id: str | None) -> str:
    """The user's role, or "" for none. The strongest role held wins."""
    if not user_id:
        return "owner" if unclaimed(doc) else ""
    access = access_of(doc)
    if user_id in access["owners"]:
        return "owner"
    if user_id in access["writers"]:
        return "writer"
    if user_id in access["readers"]:
        return "reader"
    return ""


def can_read(
    doc: dict[str, Any],
    user_id: str | None,
    *,
    enforced: bool = True,
    emergency: bool = False,
) -> bool:
    if not enforced or unclaimed(doc) or emergency:
        return True
    return bool(role_of(doc, user_id))


def can_write(
    doc: dict[str, Any],
    user_id: str | None,
    *,
    enforced: bool = True,
    emergency: bool = False,
) -> bool:
    if not enforced or unclaimed(doc) or emergency:
        return True
    return role_of(doc, user_id) in ("owner", "writer")


def can_own(
    doc: dict[str, Any],
    user_id: str | None,
    *,
    enforced: bool = True,
    emergency: bool = False,
) -> bool:
    if not enforced or unclaimed(doc) or emergency:
        return True
    return role_of(doc, user_id) == "owner"


async def readable_rows(
    conn: asyncpg.Connection,
    user_id: str | None,
    *,
    enforced: bool,
    emergency: bool = False,
) -> list[asyncpg.Record]:
    """Every project row the user may read, newest change first.

    The one list of what a person's dashboard is given: ``GET /api/projects`` and
    the agent API (#164) both read it here, so what an agent sees cannot drift from
    what the same user's own list shows. An agent passes ``emergency=False``, always.
    """
    rows = await conn.fetch(
        "SELECT id, doc, updated_at, updated_by FROM projects "
        "ORDER BY updated_at DESC, id ASC"
    )
    return [
        row
        for row in rows
        if can_read(row["doc"] or {}, user_id, enforced=enforced, emergency=emergency)
    ]


def require(
    doc: dict[str, Any],
    user_id: str | None,
    level: Level,
    *,
    enforced: bool = True,
    project_id: str | None = None,
    emergency: bool = False,
) -> bool:
    """Raise unless the user holds `level` on this project.

    404 rather than 403 when the user cannot even read it. Returning 403 would
    confirm that a project with that id exists, which is a small leak but a
    free one to close: project ids appear in URLs people paste around.

    Returns True when the request was allowed ONLY because ``emergency`` (a
    configured break-glass identity) lifted a refusal, and False when the
    project's own access list would have allowed it. The caller must record a True
    (``app/emergency.py``): a path around the access lists that is not recorded is
    just a backdoor (#42).
    """
    checks = {Level.READ: can_read, Level.WRITE: can_write, Level.OWN: can_own}

    if not can_read(doc, user_id, enforced=enforced):
        if emergency:
            return True
        denied(
            user_id, project_id, level, role_of(doc, user_id), status.HTTP_404_NOT_FOUND
        )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such project")

    if not checks[level](doc, user_id, enforced=enforced):
        if emergency:
            return True
        held = role_of(doc, user_id) or "no"
        need = "an owner" if level is Level.OWN else "write access"
        denied(
            user_id, project_id, level, role_of(doc, user_id), status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"You have {held} access to this project; this needs {need}.",
        )
    return False


# Fields inside the project document that only an owner may change, even
# though a writer may change everything else in it.
#
# These exist because the browser enforces them -- 15-access.js gates archive
# on canOwn() -- and a rule enforced only in the browser is a label. The server
# saw `{"archived": true}` as an ordinary field in a deep-merge patch and let
# any writer set it.
OWNER_ONLY_FIELDS = ("archived",)


def guard_owner_only_fields(
    before: dict[str, Any],
    patch: dict[str, Any],
    user_id: str | None,
    *,
    enforced: bool = True,
    project_id: str | None = None,
    emergency: bool = False,
) -> None:
    """Refuse a writer's attempt to change an owner-only field.

    Only fires when the patch would actually CHANGE the value. A no-op patch
    -- the browser re-sending `archived: false` alongside an unrelated edit --
    is not an attempt to archive anything, and failing it would turn an
    ordinary save into a 403.
    """
    for field in OWNER_ONLY_FIELDS:
        if field not in patch:
            continue
        if patch[field] == before.get(field):
            continue
        if not can_own(before, user_id, enforced=enforced, emergency=emergency):
            denied(
                user_id,
                project_id,
                Level.OWN,
                role_of(before, user_id),
                status.HTTP_403_FORBIDDEN,
            )
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Only an owner can change {field!r} on this project.",
            )


def guard_access_change(
    before: dict[str, Any],
    patch: dict[str, Any],
    user_id: str | None,
    *,
    enforced: bool = True,
    project_id: str | None = None,
    emergency: bool = False,
) -> None:
    """Police changes to the access list itself.

    Two rules. Only an owner may change who has access -- otherwise a writer
    could promote themselves, and the roles would be decoration. And a project
    may not be left with no owners, because an empty owner list reads as
    "unclaimed", which would turn a locked-down record back into an open one.
    Privilege escalation disguised as a tidy-up.
    """
    if "access" not in patch:
        return

    if not can_own(before, user_id, enforced=enforced, emergency=emergency):
        denied(
            user_id,
            project_id,
            Level.OWN,
            role_of(before, user_id),
            status.HTTP_403_FORBIDDEN,
        )
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only an owner can change who has access to this project.",
        )

    if not enforced:
        return

    proposed = patch.get("access")
    if not isinstance(proposed, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "access must be an object")

    # The patch deep-merges, but access lists REPLACE (arrays always do), so the
    # proposed owners are the owners -- unless the key is absent, in which case
    # the existing ones survive.
    owners = (
        _listed(proposed, "owners")
        if "owners" in proposed
        else access_of(before)["owners"]
    )
    if not owners and not unclaimed(before):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A project must keep at least one owner. Removing the last one "
            "would make it unrestricted.",
        )
