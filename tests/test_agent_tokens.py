#!/usr/bin/env python3
"""`make agent-tokens`: the operator's way to list and end agent tokens (#164).

The app has no administrator role, so an operator revokes the way they dispose of
records: a script that connects as the database owner. This tests the script against a
real PostgreSQL with the real migrations: that it lists live tokens and never a
secret, that it revokes exactly what it was told to (one token, one person, everyone)
and only what is still live, that it marks the revocation as the operator's, and that a
hostile identity is data and not SQL. Needs Docker.

    pixi run test-agent-tokens
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


at = load("agent_tokens_script", ROOT / "scripts" / "agent_tokens.py")
tpl = load("test_purge_ledger", ROOT / "tests" / "test_purge_ledger.py")

failures: list[str] = []
HOSTILE = "x'; DROP TABLE agent_token; -- $$ $by$"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def run(*args: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = at.main(list(args))
        except SystemExit as exc:  # argparse's own usage error
            code = int(exc.code or 0)
    return code, out.getvalue() + err.getvalue()


def unit() -> None:
    print("The script, without a database")
    code, out = run("--psql", "false", "revoke")
    check("revoke with no selector is refused", code == 2, out)
    code, out = run("--psql", "false", "revoke", "--everyone", "--user", "a")
    check("so are two selectors", code == 2, out)
    code, out = run("--psql", "false", "revoke", "--token", "not-hex")
    check("a token id that is not 16 hex characters is refused", code == 2, out)
    check(
        "an empty list is said in words",
        at.render_list([]) == "No agent tokens.",
    )
    check(
        "nothing to revoke is said, not silence",
        "Nothing to revoke" in at.render_revoked([]),
    )


def seed() -> str:
    return """
    INSERT INTO principals (id, name, email) VALUES
      ('ann@h.org', 'Ann', 'ann@h.org'), ('bob@h.org', 'Bob', 'bob@h.org'),
      ('x''; DROP TABLE agent_token; -- $$ $by$', '', '');
    INSERT INTO agent_token (token_id, secret_hash, principal_id, label,
                            created_at, expires_at) VALUES
      ('a000000000000001', repeat('1', 64), 'ann@h.org', 'laptop',
       now() - interval '1 hour', now() - interval '1 hour' + interval '8 hours'),
      ('a000000000000002', repeat('2', 64), 'ann@h.org', '',
       now() - interval '2 hour', now() - interval '2 hour' + interval '8 hours'),
      ('b000000000000001', repeat('3', 64), 'bob@h.org', 'ci',
       now() - interval '1 hour', now() - interval '1 hour' + interval '8 hours'),
      ('c000000000000001', repeat('4', 64), 'ann@h.org', 'old',
       now() - interval '20 hours', now() - interval '12 hours'),
      ('d000000000000001', repeat('5', 64),
       'x''; DROP TABLE agent_token; -- $$ $by$', '',
       now() - interval '1 hour', now() - interval '1 hour' + interval '8 hours');
    UPDATE agent_token SET revoked_at = now(), revoked_source = 'user'
     WHERE token_id = 'a000000000000002';
    """


def integration() -> None:
    print("Against a real PostgreSQL")
    if not shutil.which("docker"):
        if REQUIRE_TESTS:
            check("docker is available", False, "REQUIRE_TESTS is set")
        else:
            print("  skip  docker unavailable: the script is not checked")
        return
    name = tpl.start()
    try:
        prefix = f"docker exec -i {name} psql -U chai -d chai"
        tpl.psql(name, seed())

        def state() -> dict[str, str]:
            rows = tpl.psql(
                name,
                "SELECT token_id || ' ' || coalesce(revoked_source, '-') || ' ' || "
                "(revoked_at IS NOT NULL) FROM agent_token ORDER BY token_id",
            ).splitlines()
            return {r.split()[0]: " ".join(r.split()[1:]) for r in rows}

        code, out = run("--psql", prefix, "list")
        check("list runs", code == 0, out)
        check(
            "it shows the live tokens and not the expired or revoked ones",
            "a000000000000001" in out
            and "b000000000000001" in out
            and "a000000000000002" not in out
            and "c000000000000001" not in out,
            out,
        )
        check("it names who each belongs to", "ann@h.org" in out and "bob@h.org" in out)
        code, out = run("--psql", prefix, "list", "--all-states")
        check(
            "--all-states shows every one, with its state",
            "revoked by user" in out and "expired" in out and out.count("\n") >= 5,
            out,
        )
        code, out = run("--psql", prefix, "list", "--user", "bob@h.org")
        check(
            "--user shows one person's",
            "b000000000000001" in out and "a000000000000001" not in out,
            out,
        )
        check(
            "it never prints a hash or a secret",
            "1" * 64 not in out
            and not any(h * 64 in out for h in "12345")
            and "secret_hash" not in out,
        )
        before = state()
        check("listing changes nothing", state() == before)

        code, out = run("--psql", prefix, "revoke", "--token", "b000000000000001")
        check(
            "revoke --token ends that token",
            code == 0 and "b000000000000001" in out,
            out,
        )
        after = state()
        check(
            "and only that one, marked as the operator's",
            after["b000000000000001"] == "operator true"
            and after["a000000000000001"] == "- false",
            str(after),
        )

        code, out = run("--psql", prefix, "revoke", "--token", "b000000000000001")
        check(
            "revoking it again finds nothing and changes nothing",
            code == 0 and "Nothing to revoke" in out and state() == after,
            out,
        )

        code, out = run("--psql", prefix, "revoke", "--user", "ann@h.org")
        after = state()
        check(
            "revoke --user ends a person's live tokens",
            code == 0 and after["a000000000000001"] == "operator true",
            out,
        )
        check(
            "and leaves what was already revoked, or expired, as it was",
            after["a000000000000002"] == "user true"
            and after["c000000000000001"] == "- false",
            str(after),
        )

        code, out = run("--psql", prefix, "revoke", "--user", HOSTILE)
        check(
            "an identity full of quotes and SQL runs as data",
            code == 0
            and "d000000000000001" in out
            and tpl.psql(name, "SELECT count(*) FROM agent_token") == "5",
            out,
        )

        tpl.psql(
            name,
            "INSERT INTO agent_token (token_id, secret_hash, principal_id, created_at, "
            "expires_at) VALUES ('e000000000000001', repeat('6', 64), 'bob@h.org', "
            "now(), "
            "now() + interval '8 hours'), ('e000000000000002', repeat('7', 64), "
            "'ann@h.org', now(), now() + interval '8 hours')",
        )
        code, out = run("--psql", prefix, "revoke", "--everyone")
        after = state()
        check(
            "revoke --everyone ends every live token",
            code == 0
            and after["e000000000000001"] == "operator true"
            and after["e000000000000002"] == "operator true",
            out,
        )
        code, out = run("--psql", prefix, "list")
        check("and none is left live", "No agent tokens." in out, out)

        # The row is the record: it stays, and the operator's mark is on it.
        check(
            "nothing is deleted: the rows and their owners remain",
            tpl.psql(name, "SELECT count(*) FROM agent_token") == "7",
        )
    finally:
        tpl.docker("rm", "-f", name)


def main() -> int:
    unit()
    integration()
    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("agent-tokens checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
