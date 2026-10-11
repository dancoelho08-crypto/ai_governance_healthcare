#!/usr/bin/env python3
"""`make dispose`: the operator's side of disposal at the end of retention (#57).

The rules are in the database and are tested there (server/tests/test_retention.py).
This tests the script an operator runs: that its report names what is due and never
what a record says, that it changes nothing without --apply, that --apply needs the
name of whoever runs it, and that applying it, against a real PostgreSQL with the real
migrations, disposes of what was reported and records the run. Needs Docker.

    pixi run test-dispose
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
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


ds = load("dispose", ROOT / "scripts" / "dispose.py")
tpl = load("test_purge_ledger", ROOT / "tests" / "test_purge_ledger.py")

failures: list[str] = []
SECRET = "entered by mistake: MRN 00123"
HOSTILE_NAME = "x$by$'; DROP TABLE projects; -- $by"


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def run(*args: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ds.main(list(args))
    return code, out.getvalue() + err.getvalue()


def unit() -> None:
    print("The script, without a database")
    code, out = run("--psql", "false", "--apply")
    check("--apply without --by is refused", code == 2 and "--by" in out, out)
    code, out = run("--psql", "false", "--apply", "--by", "   ")
    check("so is a blank name", code == 2, out)
    hostile = [
        "x$by$; DROP TABLE projects; --",
        "ends in the old tag$by",
        "$by$",
        "$$ ; DROP TABLE projects ; $$",
        'o\'brien \\ "quoted"',
        "",
    ]
    ok = True
    for value in hostile:
        literal = ds.quote(value)
        tag = literal[: literal.index("$", 1) + 1]
        body = literal[len(tag) :]
        # The first thing that closes the literal is its own closing tag, at the end.
        ok = ok and literal.endswith(tag) and body.find(tag) == len(body) - len(tag)
        ok = ok and body[: -len(tag)] == value
    check("a name is quoted so that nothing in it can end the quote", ok)
    report = {
        "policy": {"record_years": 6, "read_trail_years": 6,
                   "changed_at": "2026-01-01T00:00:00", "changed_by": "chai"},
        "projects": [
            {"project_id": "a", "incarnation": "u1", "kind": "retired",
             "clock_start": "2018-01-02T00:00:00", "due": "2024-01-02T00:00:00",
             "held": False},
            {"project_id": "b", "incarnation": "u2", "kind": "deleted",
             "clock_start": "2017-01-02T00:00:00", "due": "2023-01-02T00:00:00",
             "held": True},
        ],
        "read_trail": {"cutoff": "2020-10-08T00:00:00", "events": 4, "held": 1},
        "principals": 2,
    }  # fmt: skip
    text = ds.render(report)
    check(
        "the report separates what is due from what a hold keeps",
        "Due for disposal (1):\n  a  retired since 2018-01-02" in text
        and "Kept: litigation hold (1):\n  b  deleted" in text,
        text,
    )
    check("and counts the read trail", "4 row(s) older than 2020-10-08" in text, text)
    check(
        "and the staff directory", "Staff names and emails: 2 person(s)" in text, text
    )
    check(
        "a report with no rule set says so, not nothing",
        "Retirement rules: NONE recorded" in text,
        text,
    )
    check(
        "it counts the records whose framework has no rules, even when none",
        "Records whose framework has no retirement rules: 0." in text,
        text,
    )
    text = ds.render({**report, "unruled": {"acme": 2, "zeta": 1}})
    check(
        "and names their frameworks when there are some (R-66)",
        "Records whose framework has no retirement rules: 3 (acme: 2, zeta: 1). "
        "They are never retired" in text,
        text,
    )
    rules = {"rule_set_hash": "ab" * 32, "framework": "chai",
             "at": "2026-10-10T00:00:00", "by": "chai"}  # fmt: skip
    text = ds.render({**report, "rules": rules})
    check(
        "and names the retirement rule set that decided what is due (D-76)",
        f"Retirement rules: chai's, rule set {'ab' * 32}, set 2026-10-10 by chai."
        in text,
        text,
    )


SEED = f"""
INSERT INTO projects (id, doc, incarnation, updated_at) VALUES
  ('old', '{{"gates":{{"D":{{"decision":"Retire","date":"2018-03-01"}}}},
            "note":"{SECRET}"}}',
   '11111111-1111-1111-1111-111111111111', now() - interval '8 years'),
  ('live', '{{"gates":{{"D":{{"decision":"Continue"}}}}}}',
   '22222222-2222-2222-2222-222222222222', now() - interval '8 years');
INSERT INTO project_version (project_id, rev, doc, content_md5, incarnation, changed_at)
VALUES
  ('old', 1, '{{"note":"{SECRET}"}}', 'a', '11111111-1111-1111-1111-111111111111',
   now() - interval '8 years'),
  ('live', 1, '{{}}', 'b', '22222222-2222-2222-2222-222222222222',
   now() - interval '8 years');
INSERT INTO access_event (at, actor, action, project_id) VALUES
  (now() - interval '7 years', 'r', 'read_log', 'old'),
  (now() - interval '1 year', 'r', 'read_log', 'old');
INSERT INTO principals (id, name, email, last_seen) VALUES
  ('left@h.org', 'Left Long Ago', 'left@h.org', now() - interval '8 years'),
  ('here@h.org', 'Still Here', 'here@h.org', now());
INSERT INTO agent_token (token_id, secret_hash, principal_id, created_at, expires_at)
VALUES
  ('aaaaaaaaaaaaaaaa', repeat('a', 64), 'left@h.org',
   now() - interval '8 years', now() - interval '8 years' + interval '8 hours'),
  ('bbbbbbbbbbbbbbbb', repeat('b', 64), 'here@h.org', now(),
   now() + interval '8 hours');
"""


def integration() -> None:
    print("Against a real PostgreSQL")
    if not shutil.which("docker"):
        if REQUIRE_TESTS:
            check("docker is available", False, "REQUIRE_TESTS is set")
        else:
            print("  skip  docker unavailable: disposal is not checked")
        return
    name = tpl.start()
    try:
        prefix = " ".join(["docker", "exec", "-i", name, "psql", "-U", "chai", "-d",
                           "chai"])  # fmt: skip
        tpl.psql(name, SEED)
        code, out = run("--psql", prefix)
        check("the report runs", code == 0, out)
        check(
            "it names the retired project and not the one in use",
            "  old  retired since" in out and "  live " not in out,
            out,
        )
        check("it never prints what a record says", SECRET not in out, out)
        manifest = json.loads(
            (ROOT / "docs" / "app" / "manifest.json").read_text(encoding="utf-8")
        )
        check(
            "it names the rule set the database retires by, the build's own",
            f"rule set {manifest['ruleSetHash']}" in out,
            out,
        )
        check(
            "every record's framework has rules",
            "Records whose framework has no retirement rules: 0." in out,
            out,
        )
        check(
            "and changes nothing",
            tpl.psql(name, "SELECT count(*) FROM projects") == "2"
            and tpl.psql(name, "SELECT count(*) FROM disposal_run") == "0",
        )

        code, out = run("--psql", prefix, "--apply", "--by", "ops@hospital.example")
        check("--apply runs", code == 0, out)
        check(
            "and says what it did",
            "Disposed of 1 project(s) (1 revision(s)), 1 read-trail row(s) and 1 person"
            in out,
            out,
        )
        left = tpl.psql(name, "SELECT string_agg(id, ',') FROM projects")
        content = tpl.psql(
            name, "SELECT count(*) FROM project_version WHERE doc::text LIKE '%MRN%'"
        )
        check("the retired record and its content are gone", (left, content) == (
            "live", "0"), f"{left} {content}")  # fmt: skip
        run_row = json.loads(
            tpl.psql(name, "SELECT row_to_json(r) FROM disposal_run r")
        )
        check(
            "the run is recorded with who ran it",
            run_row["run_by"] == "ops@hospital.example" and run_row["projects"] == 1,
            str(run_row),
        )
        code, out = run("--psql", prefix, "--apply", "--by", HOSTILE_NAME)
        check("a name full of quotes and SQL runs as data", code == 0, out)
        recorded = tpl.psql(
            name, "SELECT run_by FROM disposal_run ORDER BY id DESC LIMIT 1"
        )
        check(
            "it is recorded exactly as typed, and the tables are intact",
            recorded == HOSTILE_NAME
            and tpl.psql(name, "SELECT count(*) FROM projects") == "1",
            recorded,
        )
        people = tpl.psql(name, "SELECT string_agg(id, ',') FROM principals")
        check("someone still signing in is kept", people == "here@h.org", people)
        tokens = tpl.psql(name, "SELECT string_agg(token_id, ',') FROM agent_token")
        check(
            "a disposed person's agent tokens go with them, and a kept person's stay",
            tokens == "bbbbbbbbbbbbbbbb",
            tokens,
        )
        code, out = run("--psql", prefix)
        check(
            "a second report finds nothing due",
            "No project is past its retention period." in out
            and "Read trail: 0 row(s)" in out,
            out,
        )
        # A record of a framework the database has no rules for: it never comes
        # due, and the report says how many there are, by framework.
        tpl.psql(
            name,
            "INSERT INTO projects (id, doc, updated_at) VALUES ('stray', "
            '\'{"meta":{"framework":{"id":"acme"}},'
            '"gates":{"D":{"decision":"Retire","date":"2015-01-01"}}}\', '
            "now() - interval '9 years')",
        )
        code, out = run("--psql", prefix)
        check(
            "a record whose framework has no rules is counted, and is not due",
            "Records whose framework has no retirement rules: 1 (acme: 1)" in out
            and "  stray " not in out,
            out,
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
    print("dispose checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
