#!/usr/bin/env python3
"""A subject access request can be answered with a command (#57).

One person's identifier is stored in at least six places. `scripts/subject_access.py`
finds them. This runs the real script against a real PostgreSQL (the real migrations,
real rows) and checks what it finds, what it must not find, that hostile input is only
ever data, and that no column that records who did something has been left out as the
schema grows.

Needs Docker.

    pixi run test-subject-access
"""

from __future__ import annotations

import importlib.util
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "subject_access.py"
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))

spec = importlib.util.spec_from_file_location("subject_access", SCRIPT)
sa = importlib.util.module_from_spec(spec)
sys.modules["subject_access"] = sa
spec.loader.exec_module(sa)

vb_spec = importlib.util.spec_from_file_location(
    "verify_backup", ROOT / "scripts" / "verify_backup.py"
)
vb = importlib.util.module_from_spec(vb_spec)
sys.modules["verify_backup"] = vb
vb_spec.loader.exec_module(vb)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def docker(*args: str, stdin: bytes | None = None):
    return subprocess.run(["docker", *args], input=stdin, capture_output=True)


def psql(container: str, sql: str) -> str:
    done = docker("exec", container, "psql", "-U", "chai", "-d", "chai", "-tAc", sql)
    assert done.returncode == 0, done.stderr.decode()[-300:]
    return done.stdout.decode().strip()


def start() -> str:
    name = f"chai-sa-{secrets.token_hex(3)}"
    done = docker(
        "run", "-d", "--rm", "--name", name,
        "-e", "POSTGRES_USER=chai", "-e", "POSTGRES_DB=chai",
        "-e", f"POSTGRES_PASSWORD={secrets.token_hex(8)}",
        "--network", "none", "--tmpfs", "/var/lib/postgresql/data",
        vb.production_image(),
    )  # fmt: skip
    assert done.returncode == 0, done.stderr.decode()[-300:]
    streak = 0
    for _ in range(120):
        ready = docker("exec", name, "pg_isready", "-U", "chai", "-d", "chai")
        streak = streak + 1 if ready.returncode == 0 else 0
        if streak >= 2:
            break
        time.sleep(0.6)
    for migration in sorted((ROOT / "server" / "migrations").glob("*.sql")):
        done = docker(
            "exec", "-i", name, "psql", "-U", "chai", "-d", "chai",
            "-v", "ON_ERROR_STOP=1", "-q", "-f", "-",
            stdin=migration.read_bytes(),
        )  # fmt: skip
        assert done.returncode == 0, done.stderr.decode()[-400:]
    return name


def seed(name: str) -> None:
    psql(
        name,
        """
        INSERT INTO projects (id, doc, created_by, updated_by) VALUES
          ('p1', '{"access":{"owners":["dr.a@hosp.org"]},
                   "gates":{"g1":{"signedBy":"Dr.A@hosp.org"}}}',
           'dr.a@hosp.org', 'dr.a@hosp.org'),
          ('p2', '{"meta":{"solution":"Two"}}', 'other@hosp.org', 'other@hosp.org');
        INSERT INTO project_log (project_id, by_id, entry) VALUES
          ('p1', 'dr.a@hosp.org', '{"text":"signed by dr.a@hosp.org"}'),
          ('p2', 'other@hosp.org', '{"text":"nothing here"}');
        UPDATE project_log SET purged_by = 'dr.a@hosp.org', purged_at = now(),
               entry = project_log_redacted(entry) WHERE project_id = 'p1';
        INSERT INTO project_log (project_id, by_id, entry) VALUES
          ('p1', 'other@hosp.org', '{"text":"cc dr.a@hosp.org"}');
        INSERT INTO project_version (project_id, rev, doc, content_md5, changed_by,
                                     access, purged_by, incarnation) VALUES
          ('p1', 1, '{"gates":{"g1":{"signedBy":"dr.a@hosp.org"}}}', 'a',
           'dr.a@hosp.org', '{"owners":["dr.a@hosp.org"]}', NULL, gen_random_uuid()),
          ('p2', 1, '{}', 'b', 'other@hosp.org', '{}', NULL, gen_random_uuid());
        INSERT INTO project_deletion (project_id, incarnation, deleted_by)
          VALUES ('p9', gen_random_uuid(), 'dr.a@hosp.org');
        INSERT INTO access_event (actor, action, project_id)
          VALUES ('dr.a@hosp.org', 'list', NULL), ('other@hosp.org', 'list', NULL);
        INSERT INTO principals (id, name, email)
          VALUES ('dr.a@hosp.org', 'Dr. A', 'dr.a@hosp.org');
        INSERT INTO retention_hold (project_id, by_id, action, reason) VALUES
          ('p1', 'dr.a@hosp.org', 'place', 'Records request'),
          ('p2', 'other@hosp.org', 'place', 'Deposition of dr.a@hosp.org');
        INSERT INTO agent_token (token_id, secret_hash, principal_id, label,
                                 created_at, expires_at)
          VALUES ('0123456789abcdef', repeat('a', 64), 'dr.a@hosp.org', 'dr.a laptop',
                  '2026-01-01T00:00:00Z', '2026-01-01T08:00:00Z');
        SELECT dispose_due('dr.a@hosp.org');
        """,
    )


def run(name: str, subject: str) -> dict:
    return sa.query(
        ["docker", "exec", "-i", name, "psql", "-U", "chai", "-d", "chai"], subject
    )


def locations(report: dict) -> dict[str, int]:
    return {loc["location"]: loc["rows"] for loc in report["locations"]}


def covered_columns(name: str, sql: str) -> list[str]:
    """Columns that record who did something, which the report does not mention."""
    rows = psql(
        name,
        "SELECT table_name || '.' || column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND (column_name LIKE '%\\_by' "
        "OR column_name IN ('by_id', 'actor')) ORDER BY 1",
    ).split()
    return [r for r in rows if r not in sql]


def main() -> int:
    if not shutil.which("docker"):
        if REQUIRE_TESTS:
            check("docker is available", False, "REQUIRE_TESTS is set")
            return 1
        print("  skip  docker unavailable: subject access is not checked")
        return 0
    name = start()
    try:
        seed(name)
        before = psql(
            name,
            "SELECT (SELECT count(*) FROM projects) || '/' || "
            "(SELECT count(*) FROM project_log) || '/' || "
            "(SELECT count(*) FROM project_version)",
        )

        found = locations(run(name, "dr.a@hosp.org"))
        for loc in (
            "projects.created_by", "projects.updated_by", "projects.doc",
            "project_log.by_id", "project_log.entry", "project_log.purged_by",
            "project_version.changed_by",
            "project_version.doc", "project_version.access",
            "project_deletion.deleted_by", "access_event.actor", "principals",
            "retention_hold.by_id", "retention_hold.reason", "disposal_run.run_by",
            "agent_token.principal_id",
        ):  # fmt: skip
            check(f"found in {loc}", found.get(loc, 0) >= 1, str(found))
        check(
            "and not in what belongs to someone else",
            found.get("projects.created_by") == 1
            and found.get("access_event.actor") == 1,
            str(found),
        )
        check(
            "it names the projects, so the privacy office knows where to look",
            next(
                loc for loc in run(name, "dr.a@hosp.org")["locations"]
                if loc["location"] == "projects.doc"
            )["projects"] == ["p1"],
        )  # fmt: skip
        check(
            "the principal row comes back",
            run(name, "dr.a@hosp.org")["principal"]["name"] == "Dr. A",
        )
        check(
            "case does not hide a match",
            locations(run(name, "DR.A@HOSP.ORG")) == found,
        )
        check(
            "someone who is nowhere comes back empty",
            run(name, "nobody@hosp.org")["locations"] == [],
        )
        check(
            "a wildcard is data, not a pattern",
            run(name, "%")["locations"] == [] and run(name, "_")["locations"] == [],
        )
        hostile = run(name, "x'; DROP TABLE projects; --")
        check(
            "a quote and a statement in the identifier are only data",
            hostile["locations"] == []
            and psql(name, "SELECT count(*) FROM projects") == "2",
        )
        after = psql(
            name,
            "SELECT (SELECT count(*) FROM projects) || '/' || "
            "(SELECT count(*) FROM project_log) || '/' || "
            "(SELECT count(*) FROM project_version)",
        )
        check("it changed nothing", before == after, f"{before} -> {after}")

        # Restoring a dump taken before a purge brings the purged content back.
        dump = docker("exec", name, "pg_dump", "-U", "chai", "-d", "chai",
                      "--clean", "--if-exists").stdout  # fmt: skip
        psql(
            name,
            "UPDATE project_version SET doc = '{}'::jsonb, purged_at = now(), "
            "purged_by = 'dpo@hosp.org' WHERE project_id = 'p1'",
        )
        purged = psql(
            name,
            "SELECT count(*) FROM project_version "
            "WHERE project_id = 'p1' AND purged_at IS NOT NULL",
        )
        docker("exec", "-i", name, "psql", "-U", "chai", "-d", "chai",
               "-v", "ON_ERROR_STOP=1", "-q", "-f", "-", stdin=dump)  # fmt: skip
        back = psql(
            name,
            "SELECT count(*) FROM project_version "
            "WHERE project_id = 'p1' AND purged_at IS NULL AND doc <> '{}'",
        )
        check(
            "a restore of a dump from before a purge brings the purged content back",
            purged == "1" and back == "1",
            f"purged={purged} restored={back}",
        )

        sql = sa.SQL.read_text(encoding="utf-8")
        check(
            "every column that records who did something is searched",
            not covered_columns(name, sql),
            ", ".join(covered_columns(name, sql)),
        )
        check(
            "and the drift check notices a table left out (mutation)",
            bool(covered_columns(name, sql.replace("access_event", "x"))),
        )

        report = run(name, "dr.a@hosp.org")
        text = sa.render(report)
        check("the report names the identifier", "dr.a@hosp.org" in text)
        check("and says a jsonb match is only a place to look", "place to look" in text)
        check("and points to the position", "docs/privacy.md" in text)
        check(
            "a usage error is not a crash",
            sa.main([]) == 2 and sa.main(["a", "b"]) == 2,
        )
    finally:
        docker("rm", "-f", name)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("subject access checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
