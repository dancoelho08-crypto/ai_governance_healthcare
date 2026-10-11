#!/usr/bin/env python3
"""List and revoke agent tokens, as the operator (#164, R-71, D-89).

    agent_tokens.py list [--user ID] [--all-states]
    agent_tokens.py revoke --token ID
    agent_tokens.py revoke --user ID
    agent_tokens.py revoke --everyone

A person mints their own token in the app and can revoke it there. This is the
operator's way to end one without the person: an account was compromised, a laptop was
lost, a person left, or a backup was restored. The app has no administrator role, so
this is an operator action like `make dispose`: it connects as the database owner and
changes the `agent_token` table directly.

`revoke` sets `revoked_at` and `revoked_source = 'operator'` on every token it matches
that is still live. A revoked token stops working on its next call. Nothing is deleted:
the row stays, with its owner and its use, until the person's principal is disposed of
(`make dispose`), which takes their tokens with it.

Revoking is never needed for the 8-hour lifetime, which ends every token by itself.
It is for the next hours. After a `make restore` run `revoke --everyone`: a backup can
hold a token that was revoked after the dump was taken.

It prints identity ids and token ids, never a secret (the server keeps none). It runs
on the host's Python, so it keeps to what 3.10 has.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from enum import Enum
from pathlib import Path
from typing import Any

try:
    from enum import StrEnum
except ImportError:  # Python 3.10, which the host's python3 may be

    class StrEnum(str, Enum):  # noqa: UP042
        def __str__(self) -> str:
            return str(self.value)


sys.path.insert(0, str(Path(__file__).resolve().parent))

from dispose import quote
from purge_ledger import default_psql, run_psql


class Command(StrEnum):
    LIST = "list"
    REVOKE = "revoke"


TOKEN_ID = re.compile(r"^[0-9a-f]{16}$")

LIST_SQL = """
SELECT coalesce(json_agg(t ORDER BY t.created_at DESC), '[]'::json)::text FROM (
  SELECT token_id, principal_id AS "user", label, created_at, expires_at,
         last_used_at, revoked_at, revoked_source,
         CASE WHEN revoked_at IS NOT NULL THEN 'revoked'
              WHEN expires_at <= now() THEN 'expired'
              ELSE 'active' END AS state
    FROM agent_token
   WHERE {where}
) t;
"""

REVOKE_SQL = """
WITH ended AS (
  UPDATE agent_token
     SET revoked_at = now(), revoked_source = 'operator'
   WHERE revoked_at IS NULL AND expires_at > now() AND {where}
  RETURNING token_id, principal_id
)
SELECT coalesce(json_agg(ended ORDER BY token_id), '[]'::json)::text FROM ended;
"""


def where_of(args: argparse.Namespace) -> str:
    """The WHERE clause for what the command named. A selector that was given is
    always applied, even an empty one is refused rather than read as "no selector":
    `revoke --user ''` must never mean everyone."""
    clauses = ["true"]
    for name, column in (("user", "principal_id"), ("token", "token_id")):
        value = getattr(args, name, None)
        if value is None:
            continue
        if not value.strip():
            raise ValueError(f"--{name} is empty: name a {name}, or use --everyone")
        clauses.append(f"{column} = {quote(value.strip())}")
    return " AND ".join(clauses)


def render_list(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No agent tokens."
    lines = [f"{len(rows)} agent token(s), newest first:"]
    for r in rows:
        used = (r["last_used_at"] or "never")[:19]
        ended = f", revoked by {r['revoked_source']}" if r["revoked_at"] else ""
        lines.append(
            f"  {r['token_id']}  {r['state']:<8} {r['user']}  "
            f"made {r['created_at'][:19]}, expires {r['expires_at'][:19]}, "
            f"last used {used}{ended}" + (f"  [{r['label']}]" if r["label"] else "")
        )
    return "\n".join(lines)


def render_revoked(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "Nothing to revoke: no live token matches."
    lines = [f"Revoked {len(rows)} token(s). They stop working on their next call:"]
    lines += [f"  {r['token_id']}  {r['principal_id']}" for r in rows]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    top = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    top.add_argument(
        "--psql",
        type=shlex.split,
        default=None,
        help="the psql command to run (default: docker compose exec -T db psql ...)",
    )
    sub = top.add_subparsers(dest="command", required=True)
    lister = sub.add_parser(Command.LIST.value, help="show tokens")
    lister.add_argument("--user", help="only this person's (their identity id)")
    lister.add_argument(
        "--all-states",
        action="store_true",
        help="include expired and revoked tokens (default: live ones)",
    )
    revoker = sub.add_parser(Command.REVOKE.value, help="end tokens now")
    which = revoker.add_mutually_exclusive_group(required=True)
    which.add_argument("--token", help="one token, by its public id")
    which.add_argument("--user", help="every live token of one person")
    which.add_argument(
        "--everyone", action="store_true", help="every live token of everyone"
    )
    args = top.parse_args(argv)
    if getattr(args, "token", None) is not None and not TOKEN_ID.fullmatch(args.token):
        print("agent_tokens: a token id is 16 hex characters", file=sys.stderr)
        return 2
    try:
        where_of(args)  # refuses an empty selector before anything is run
    except ValueError as exc:
        print(f"agent_tokens: {exc}", file=sys.stderr)
        return 2
    psql = args.psql or default_psql()
    try:
        if Command(args.command) is Command.LIST:
            where = where_of(args)
            if not args.all_states:
                where += " AND revoked_at IS NULL AND expires_at > now()"
            print(render_list(json.loads(run_psql(psql, LIST_SQL.format(where=where)))))
        else:
            where = where_of(args)
            print(
                render_revoked(
                    json.loads(run_psql(psql, REVOKE_SQL.format(where=where)))
                )
            )
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"agent_tokens: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
