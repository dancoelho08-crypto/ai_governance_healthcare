"""The database role the API serves traffic as, and exactly what it may do.

The append-only guarantees in ``001_init.sql``, ``003_version_access.sql`` and
``005_disposal.sql`` (a log that refuses UPDATE, a version history that refuses
DELETE, a tombstone that refuses everything) are triggers. A table's OWNER can
``ALTER TABLE ... DISABLE TRIGGER``, ``DROP TRIGGER`` or ``TRUNCATE`` in one
statement, and the API used to run migrations and serve traffic as the same role,
which owned every table (and, in the compose stack, was a superuser). So the
triggers constrained the application's bugs, not the application, and not anything
holding its credential (#48).

So there are two roles:

* the **owner** (``POSTGRES_USER`` / ``DATABASE_URL``) creates the schema. Only
  ``python -m app.migrate`` holds it, as a one-shot job;
* the **serving role** (``APP_POSTGRES_USER``, default ``chai_app``) is what the API
  connects as. It is a plain login role with the table privileges below and
  nothing else: it cannot disable or drop a trigger, truncate, alter a table or
  create one.

``GRANTS`` is the whole list, and a test fails if a table exists that is not in it,
so adding a table without deciding what the API may do to it is not possible.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum

import asyncpg

DEFAULT_APP_ROLE = "chai_app"


class DbRole(StrEnum):
    """What the API's own database role can do to the append-only guarantees."""

    RESTRICTED = "restricted"  # cannot disable a trigger, truncate or alter a table
    OWNER = "owner"  # owns the tables or is a superuser: it can, so they bind bugs only


# What the API may do to each table. Nothing is granted by default, on purpose:
# a new table needs a line here, decided, not inherited.
#
# project_log gets UPDATE because a purge redacts entries in place (the trigger
# permits exactly that transition and nothing else). It gets no DELETE: a project's
# log is removed by ON DELETE CASCADE, which runs with the table owner's rights.
# project_version gets UPDATE for the purge and no DELETE, ever. project_deletion
# is INSERT and SELECT only, and its trigger refuses the rest regardless.
GRANTS: Mapping[str, tuple[str, ...]] = {
    "projects": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "project_log": ("SELECT", "INSERT", "UPDATE"),
    "project_version": ("SELECT", "INSERT", "UPDATE"),
    "project_deletion": ("SELECT", "INSERT"),
    # The read trail (#33): append-only, and the API may only add to it and read it.
    "access_event": ("SELECT", "INSERT"),
    # Updated in place as a person's name or email changes; never deleted by the API.
    "principals": ("SELECT", "INSERT", "UPDATE"),
    # Retention (#57, 008_retention.sql). The API may read the periods, and place or
    # lift a litigation hold (append-only). It may not dispose of anything: that is
    # dispose_due(), run by an operator as the owner, and the read trail above has
    # no DELETE.
    "retention_policy": ("SELECT",),
    "retention_hold": ("SELECT", "INSERT"),
    "disposal_run": ("SELECT",),
    # Which decisions end a project, and their history (D-76, 010). The API reads the
    # active rule set for /api/health; only the migrate job, as the owner, changes
    # them, so a compromised API cannot make a record come due for disposal early.
    "retirement_rule": ("SELECT",),
    "retirement_rule_change": ("SELECT",),
    # Agent tokens (#164, 013). The API mints one (INSERT), authenticates by one
    # (SELECT), and records its use and its revocation (UPDATE). A trigger lets only
    # those two columns move, and no DELETE is granted: a token leaves by expiring, or
    # with its principal (ON DELETE CASCADE, which runs with the owner's rights).
    "agent_token": ("SELECT", "INSERT", "UPDATE"),
    # The words an agent may be shown, loaded from the build's manifest by the migrate
    # job (014, D-89). The API only reads it: a compromised API cannot widen what an
    # agent is shown.
    "agent_vocabulary": ("SELECT",),
}

# Tables the API must never touch at all: the owner's migration bookkeeping.
NO_ACCESS = ("schema_migrations",)

# project_log.seq is a bigserial; inserting needs the sequence.
SEQUENCE_GRANTS: Mapping[str, tuple[str, ...]] = {
    "project_log_seq_seq": ("USAGE", "SELECT"),
    "access_event_id_seq": ("USAGE", "SELECT"),
    "retention_hold_id_seq": ("USAGE", "SELECT"),
}

_ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def check_role_name(name: str) -> str:
    """A role name this module is willing to put in SQL. Anything else is refused."""
    if not _ROLE_NAME.fullmatch(name):
        raise ValueError(
            f"{name!r} is not a usable database role name: use lowercase letters, "
            "digits and underscores, starting with a letter or underscore."
        )
    return name


def grant_statements(role: str) -> list[str]:
    """The GRANTs, as SQL, for ``python -m app.migrate --print-grants`` and docs.

    ``role`` is interpolated, so it is validated first; the password never is.
    """
    role = check_role_name(role)
    out = [
        f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}",
        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {role}",
        "GRANT USAGE ON SCHEMA public TO " + role,
    ]
    for table, privileges in GRANTS.items():
        out.append(f"GRANT {', '.join(privileges)} ON {table} TO {role}")
    for sequence, privileges in SEQUENCE_GRANTS.items():
        out.append(f"GRANT {', '.join(privileges)} ON SEQUENCE {sequence} TO {role}")
    return out


async def provision(conn: asyncpg.Connection, role: str, password: str) -> None:
    """Create or update the serving role. Idempotent; run as the owner, every boot.

    Running it every time is deliberate: it re-syncs the password, so rotating
    ``APP_POSTGRES_PASSWORD`` is a restart and not a manual ALTER ROLE, and it
    re-asserts the grants, so a hand-edited privilege does not survive a deploy.
    """
    role = check_role_name(role)
    if not password:
        raise ValueError("a serving role needs a password")
    # The password goes through format(%L) on the server, never into a string
    # here, so a quote in it cannot break out of the statement.
    exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
    verb = "ALTER" if exists else "CREATE"
    statement = await conn.fetchval(
        f"SELECT format('{verb} ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER "
        "NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT', "
        "$1::text, $2::text)",
        role,
        password,
    )
    async with conn.transaction():
        await conn.execute(statement)
        database = await conn.fetchval("SELECT current_database()")
        await conn.execute(
            await conn.fetchval(
                "SELECT format('GRANT CONNECT ON DATABASE %I TO %I', "
                "$1::text, $2::text)",
                database,
                role,
            )
        )
        for sql in grant_statements(role):
            await conn.execute(sql)
