"""``python -m app.migrate``: apply migrations and provision the serving role.

This is the ONE process that holds the database owner's credential. The API does
not: it connects as the restricted serving role (``app.roles``), so a compromised
API cannot disable the append-only triggers the history's value rests on (#48).

Run it as a job before the API starts (compose does: the ``migrate`` service; on a
cloud, a one-off task or job). It is idempotent, so running it on every deploy is
right: it applies any new migration, re-asserts the grants, and re-syncs the role's
password from ``APP_POSTGRES_PASSWORD``.

    python -m app.migrate                  migrate, then provision the role
    python -m app.migrate --print-grants   print the GRANTs and exit (no database)

Environment: the owner's ``DATABASE_URL`` (or ``POSTGRES_*``), and for the role
``APP_POSTGRES_USER`` (default ``chai_app``) and ``APP_POSTGRES_PASSWORD``. With no
``APP_POSTGRES_PASSWORD`` it only migrates, which is the single-role setup this
replaces and is reported as such.

After migrating it loads the build's retirement rules (``app.retirement``, D-76) from
``RETIREMENT_MANIFEST``, the path of the build's ``manifest.json``. That is required:
with no manifest, an unreadable one, or one that changes the rules of a framework it
lists without ``RETIREMENT_RULES_ACK`` set to the acknowledgment of that transition
(which the refusal prints), the job fails and provisions nothing, so the API (which
waits for it) does not start on rules nobody chose.

Exit status: 0 done, 1 an error (including a bad manifest), 2 no owner credential,
3 a change of the rules that was not acknowledged.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from .config import _log_format, build_database_url
from .db import Database
from .retirement import (
    ManifestError,
    RulesRefused,
    describe_sync,
    load_manifest,
    sync_rules,
    sync_vocabulary,
)
from .roles import DEFAULT_APP_ROLE, check_role_name, grant_statements, provision
from .securitylog import configure_logging

log = logging.getLogger("chai.migrate")

EXIT_REFUSED = 3


async def run(env: dict[str, str]) -> int:
    dsn = build_database_url(env)
    if not dsn:
        print(
            "migrate: no owner credential. Set DATABASE_URL, or POSTGRES_PASSWORD "
            "with POSTGRES_USER, POSTGRES_HOST and POSTGRES_DB.",
            file=sys.stderr,
        )
        return 2

    role = check_role_name(env.get("APP_POSTGRES_USER") or DEFAULT_APP_ROLE)
    password = env.get("APP_POSTGRES_PASSWORD") or ""
    # Read before connecting: a missing or malformed manifest fails the job before it
    # changes anything.
    try:
        manifest = load_manifest(env.get("RETIREMENT_MANIFEST"))
    except ManifestError as exc:
        print(f"migrate: retirement rules: {exc}", file=sys.stderr)
        return 1

    db = Database(dsn, min_size=1, max_size=1)
    # A database that is still starting is the normal case in compose, so wait for
    # it; MIGRATE_CONNECT_RETRIES shortens that where waiting is not wanted.
    await db.connect(retries=int(env.get("MIGRATE_CONNECT_RETRIES") or 10))
    try:
        applied = await db.migrate()
        print(
            f"migrate: applied {len(applied)} migration(s)"
            if applied
            else "migrate: schema is up to date"
        )
        async with db.acquire() as conn:
            try:
                synced = await sync_rules(
                    conn, manifest, (env.get("RETIREMENT_RULES_ACK") or "").strip()
                )
            except RulesRefused as exc:
                print(f"migrate: retirement rules refused: {exc}", file=sys.stderr)
                return EXIT_REFUSED
        print(f"migrate: {describe_sync(synced, manifest)}")
        async with db.acquire() as conn:
            words = await sync_vocabulary(conn, manifest)
        print(f"migrate: {words} agent vocabulary row(s) loaded (D-89)")
        if not password:
            print(
                "migrate: APP_POSTGRES_PASSWORD is not set, so no restricted serving "
                "role was provisioned. The API will serve as the table owner, and "
                "the append-only triggers will not constrain it (#48).",
                file=sys.stderr,
            )
            return 0
        async with db.acquire() as conn:
            await provision(conn, role, password)
        print(
            f"migrate: role {role!r} provisioned (login, no superuser, table "
            "privileges only)"
        )
        return 0
    finally:
        await db.close()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    # The same log as the API, so a security event the job emits (a retirement rule
    # changed or refused) is a JSON line tagged "security" a log sink can alert on.
    try:
        configure_logging(os.environ.get("LOG_LEVEL") or "info", _log_format())
    except RuntimeError as exc:
        print(f"migrate: {exc}", file=sys.stderr)
        return 1
    if "--print-grants" in args:
        role = os.environ.get("APP_POSTGRES_USER") or DEFAULT_APP_ROLE
        print("\n".join(s + ";" for s in grant_statements(role)))
        return 0
    try:
        return asyncio.run(run(dict(os.environ)))
    except (RuntimeError, ValueError) as exc:
        print(f"migrate: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
