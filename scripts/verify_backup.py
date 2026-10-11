#!/usr/bin/env python3
"""Restore a backup into a throwaway PostgreSQL and check that it is a backup (#52).

`make backup` writes an encrypted dump and nothing ever read one back, so the restore
path was an assumption. 45 CFR 164.308(a)(7): a data backup plan is *required*, and
testing it is addressable. The dump holds the evidence that a clinical AI deployment was
reviewed, and it cannot be reconstructed by re-entry. A backup that has never been
restored is a hypothesis; this makes it a check.

    python3 scripts/verify_backup.py                 # the newest dump in backups/
    python3 scripts/verify_backup.py FILE            # a specific one
    make verify-backup [FILE=...]

It starts a throwaway PostgreSQL of the SAME MAJOR VERSION as production (read from
compose.yaml, so the test cannot drift from what runs), with no network and its data
on tmpfs, streams the dump into it (decrypting with BACKUP_PASSPHRASE for a `.gpg`),
and checks what the dump is FOR: the tables exist, the rows came back, and **the
append-only triggers are present and enabled**, because a dump that restores into a
database without them, or with them switched off, has quietly lost the guarantee the
history's value rests on. From migration 010 it also checks that the retirement rules
are exactly the ones their history last recorded (D-76). The container is always
removed.

What it cannot tell you: that the dump is recent, that it contains everything (it
can only compare counts to what the dump says), or that your off-host copy is the
same file. It exits 0 only if the restore ran cleanly and nothing it checks is
missing.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CRYPTO = ROOT / "scripts" / "backup_crypto.sh"

# Tables a restored database must have, and that carry the guarantees. Others are
# reported but may legitimately be absent from a dump taken before their migration.
REQUIRED_TABLES = ("projects", "project_log", "project_version", "schema_migrations")
# Tables whose append-only guarantee is a trigger.
TRIGGERED_TABLES = ("project_log", "project_version")
REPORTED_TABLES = (
    *REQUIRED_TABLES,
    "project_deletion",
    "principals",
    "access_event",
    "agent_token",
    "retirement_rule",
    "retirement_rule_change",
)
# From this migration on, which decisions retire a project, and so when disposal is
# due, is a table (D-76). A restore without its rows would treat no project as
# retired, so it is required, and its rows are reported.
RULES_MIGRATION = "010_retirement_rules.sql"
RULES_TABLE = "retirement_rule"
# Their history, append-only by trigger from the same migration: "by which rule, set
# when and by whom" must not be rewritable in a restored copy either.
RULES_HISTORY = "retirement_rule_change"
# pg_trigger.tgenabled states in which a trigger fires for the API and the owner:
# O (origin, the default) and A (always). D is disabled; R fires only when
# session_replication_role is "replica", which neither sets, so it counts as off.
FIRING = ("O", "A")
# The latest change of the rules: the row with the highest id, whose new_rules the
# table must hold. A module constant so the test can show the order matters.
LATEST_CHANGE = (
    "SELECT coalesce((SELECT json_build_array(id, new_rules)"
    f" FROM {RULES_HISTORY} ORDER BY id DESC LIMIT 1), 'null')"
)


@dataclass
class Report:
    """What a restored database holds."""

    counts: dict[str, int] = field(default_factory=dict)
    # Enabled user triggers per table: ones that fire in a normal session.
    triggers: dict[str, int] = field(default_factory=dict)
    migrations: list[str] = field(default_factory=list)
    rules: list[tuple[str, str, str]] = field(default_factory=list)
    # The rules the latest retirement_rule_change row says were set (its new_rules)
    # and that row's id; None when there is no row to read.
    latest_rules: list[tuple[str, str, str]] | None = None
    latest_change: int | None = None
    # User triggers present but not firing (disabled, or replica-only), per table.
    disabled_triggers: dict[str, int] = field(default_factory=dict)
    # Live records whose framework has no retirement rules, by framework: they never
    # come due. Reported, not a failure: it may be what the deployment intends.
    unruled: dict[str, int] = field(default_factory=dict)


def _trigger_problem(report: Report, table: str, what: str) -> str | None:
    """Why ``table``'s append-only trigger does not hold in the restore, if it does
    not: absent, or present and switched off."""
    if report.triggers.get(table, 0) >= 1:
        return None
    if report.disabled_triggers.get(table, 0) >= 1:
        return (
            f"{table} was restored with its append-only trigger DISABLED: it is "
            f"there but does not fire, so {what}"
        )
    return f"{table} was restored WITHOUT its append-only trigger: {what}"


def problems_for(report: Report) -> list[str]:
    """What is wrong with a restored database. Empty means it is a backup."""
    problems = [
        f"table {table!r} is missing from the restored database"
        for table in REQUIRED_TABLES
        if table not in report.counts
    ]
    for table in TRIGGERED_TABLES:
        if table in report.counts:
            problem = _trigger_problem(
                report,
                table,
                "this dump has lost the guarantee that the history cannot be rewritten",
            )
            if problem:
                problems.append(problem)
    if RULES_MIGRATION in report.migrations:
        if RULES_TABLE not in report.counts:
            problems.append(
                f"{RULES_TABLE} is missing although {RULES_MIGRATION} was applied: "
                "the restored database cannot tell which projects are retired"
            )
        elif report.counts[RULES_TABLE] < 1:
            problems.append(
                f"{RULES_TABLE} is empty: the restored database would treat no "
                "project as retired, so nothing would ever come due for disposal"
            )
        if RULES_HISTORY not in report.counts:
            problems.append(
                f"{RULES_HISTORY} is missing although {RULES_MIGRATION} was applied: "
                "the history of the retirement rules did not come back"
            )
            return problems
        problem = _trigger_problem(
            report,
            RULES_HISTORY,
            "the history of which decisions retire a project could be rewritten",
        )
        if problem:
            problems.append(problem)
        if report.counts[RULES_HISTORY] < 1:
            problems.append(
                f"{RULES_HISTORY} is empty: the history of the retirement rules did "
                f"not come back ({RULES_MIGRATION} records its seed there)"
            )
        else:
            problems.extend(_rules_drift(report))
    return problems


def _rules_drift(report: Report) -> list[str]:
    """The restored rules against the ones their history last recorded. A rule in
    only one of them means the table was changed outside the sync (D-76), or the
    dump lost rows of one and not the other: either way the restore would retire by
    rules nobody recorded choosing."""
    if report.latest_rules is None:
        return [
            f"the latest {RULES_HISTORY} row could not be read, so it cannot be "
            f"shown that {RULES_TABLE} holds the rules last recorded"
        ]
    table, recorded = set(report.rules), set(report.latest_rules)
    if table == recorded:
        return []
    lines = [
        f"  {f}: checkpoint {g} decided {d!r} ({why})"
        for rules, why in (
            (table - recorded, "not in the history"),
            (recorded - table, "recorded, not in the table"),
        )
        for f, g, d in sorted(rules)
    ]
    return [
        f"{RULES_TABLE} does not hold the rules its history last recorded "
        f"({RULES_HISTORY} #{report.latest_change}):\n" + "\n".join(lines)
    ]


def production_image() -> str:
    """The PostgreSQL image compose.yaml runs, so the restore tests the same major."""
    text = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    found = re.search(
        r"^\s+image:\s*(postgres:\d+(?:@sha256:[0-9a-f]{64})?)\s*$", text, re.M
    )
    if not found:
        raise RuntimeError("cannot find the pinned postgres image in compose.yaml")
    return found.group(1)


def newest_dump(directory: Path) -> Path | None:
    """The newest dump by name: the timestamps are ISO, so name order is time order."""
    candidates = sorted(
        p
        for p in directory.glob("*.sql.gz*")
        if p.name.endswith((".sql.gz", ".sql.gz.gpg"))
    )
    return candidates[-1] if candidates else None


def docker(*args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], input=stdin, capture_output=True)


def stream_restore(dump: Path, container: str) -> list[str]:
    """dump -> (decrypt) -> gunzip -> psql, and the exit status of EVERY stage.

    A pipeline's status is its last command's, which is how a failed decrypt used to
    look like a successful restore. Each stage is checked here.
    """
    problems: list[str] = []
    stages: list[tuple[str, subprocess.Popen]] = []
    if dump.name.endswith(".gpg"):
        if not os.environ.get("BACKUP_PASSPHRASE"):
            return ["BACKUP_PASSPHRASE is not set, so the dump cannot be decrypted"]
        first = subprocess.Popen(
            [str(CRYPTO), "decrypt", str(dump)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stages.append(("decrypt", first))
        source = first.stdout
    else:
        source = None
    gunzip = subprocess.Popen(
        ["gunzip", "-c"] + ([] if source else [str(dump)]),
        stdin=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stages.append(("gunzip", gunzip))
    if source:
        source.close()
    psql = subprocess.Popen(
        [
            "docker",
            "exec",
            "-i",
            container,
            "psql",
            "-U",
            "chai",
            "-d",
            "chai",
            "-v",
            "ON_ERROR_STOP=1",
            "-q",
            "-f",
            "-",
        ],
        stdin=gunzip.stdout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stages.append(("restore", psql))
    gunzip.stdout.close()
    outputs = {name: proc.communicate() for name, proc in reversed(stages)}
    for name, proc in stages:
        if proc.returncode != 0:
            tail = outputs[name][1].decode("utf-8", "replace").strip().splitlines()
            problems.append(
                f"the {name} step failed (exit {proc.returncode})"
                + (f": {tail[-1][:200]}" if tail else "")
            )
    return problems


def psql_value(container: str, sql: str) -> str:
    done = docker("exec", container, "psql", "-U", "chai", "-d", "chai", "-tAc", sql)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.decode("utf-8", "replace").strip()[-300:])
    return done.stdout.decode().strip()


def inspect(container: str) -> Report:
    report = Report()
    present = set(
        psql_value(
            container,
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'",
        ).split()
    )
    for table in REPORTED_TABLES:
        if table in present:
            report.counts[table] = int(
                psql_value(container, f"SELECT count(*) FROM {table}")
            )
    # tgenabled: O fires in a normal session, A always; D (disabled) and R (replica
    # only) do not fire for the API or the owner, so they do not count as present.
    firing = ", ".join(f"'{state}'" for state in FIRING)
    triggers = psql_value(
        container,
        f"SELECT c.relname || ' ' || count(*) FILTER (WHERE t.tgenabled IN ({firing}))"
        f" || ' ' || count(*) FILTER (WHERE t.tgenabled NOT IN ({firing}))"
        " FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid"
        " WHERE NOT t.tgisinternal GROUP BY c.relname",
    )
    for line in triggers.splitlines():
        name, enabled, disabled = line.rsplit(" ", 2)
        if int(enabled):
            report.triggers[name] = int(enabled)
        if int(disabled):
            report.disabled_triggers[name] = int(disabled)
    if "schema_migrations" in present:
        report.migrations = psql_value(
            container, "SELECT version FROM schema_migrations ORDER BY version"
        ).split()
    if RULES_TABLE in present:
        report.rules = [
            tuple(r)
            for r in json.loads(
                psql_value(
                    container,
                    "SELECT coalesce(json_agg(json_build_array(framework_id, gate_id,"
                    " decision) ORDER BY framework_id, gate_id, decision), '[]')"
                    f" FROM {RULES_TABLE}",
                )
            )
        ]
    if RULES_HISTORY in present:
        latest = json.loads(psql_value(container, LATEST_CHANGE))
        if latest is not None:
            report.latest_change = int(latest[0])
            report.latest_rules = [tuple(r) for r in latest[1]]
    if RULES_MIGRATION in report.migrations and RULES_TABLE in present:
        report.unruled = json.loads(
            psql_value(
                container,
                "SELECT coalesce(json_object_agg(f, n), '{}') FROM ("
                " SELECT record_framework(p.doc) AS f, count(*) AS n FROM projects p"
                f" WHERE NOT EXISTS (SELECT 1 FROM {RULES_TABLE} r"
                "  WHERE r.framework_id = record_framework(p.doc)) GROUP BY 1) u",
            )
        )
    return report


def container_name() -> str:
    """``chai-verify-``, then ``VERIFY_BACKUP_RUN`` when it is set, then a random
    suffix. The test names its run, so it finds only the containers it started."""
    run = os.environ.get("VERIFY_BACKUP_RUN", "").strip()
    return f"chai-verify-{run + '-' if run else ''}{secrets.token_hex(4)}"


def start_container() -> str:
    name = container_name()
    done = docker(
        "run", "-d", "--rm", "--name", name,
        "-e", "POSTGRES_USER=chai", "-e", "POSTGRES_DB=chai",
        "-e", f"POSTGRES_PASSWORD={secrets.token_hex(16)}",
        "--network", "none", "--tmpfs", "/var/lib/postgresql/data",
        "--memory", "512m",
        production_image(),
    )  # fmt: skip
    if done.returncode != 0:
        raise RuntimeError(done.stderr.decode("utf-8", "replace").strip()[-300:])
    return name


def wait_ready(container: str, timeout: float = 90.0) -> None:
    """Ready twice in a row: initdb restarts the server once before it settles."""
    deadline = time.monotonic() + timeout
    streak = 0
    while time.monotonic() < deadline:
        ready = docker("exec", container, "pg_isready", "-U", "chai", "-d", "chai")
        streak = streak + 1 if ready.returncode == 0 else 0
        if streak >= 2:
            return
        time.sleep(0.6)
    raise RuntimeError("the throwaway PostgreSQL did not become ready")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    directory = Path(os.environ.get("BACKUP_DIR") or "backups")
    if "--dir" in args:
        directory = Path(args[args.index("--dir") + 1])
        args = [
            a for i, a in enumerate(args) if a != "--dir" and args[i - 1] != "--dir"
        ]
    positional = [a for a in args if not a.startswith("-")]

    dump = Path(positional[0]) if positional else newest_dump(directory)
    if dump is None:
        print(
            f"verify-backup: no dump found in {directory}/. Run `make backup` first.",
            file=sys.stderr,
        )
        return 1
    if not dump.is_file():
        print(f"verify-backup: {dump} does not exist", file=sys.stderr)
        return 1
    if not shutil.which("docker"):
        print("verify-backup: docker is required", file=sys.stderr)
        return 1

    print(f"verify-backup: {dump} ({dump.stat().st_size:,} bytes)")
    container = None
    try:
        container = start_container()
        wait_ready(container)
        problems = stream_restore(dump, container)
        report = Report()
        if not problems:
            report = inspect(container)
            problems = problems_for(report)
    except (RuntimeError, OSError) as exc:
        problems = [str(exc)]
        report = Report()
    finally:
        if container:
            docker("rm", "-f", container)

    for table, count in report.counts.items():
        print(f"  {table:<18} {count:>8} row(s)")
    if report.migrations:
        print(f"  schema at          {report.migrations[-1]}")
    for framework, gate, decision in report.rules:
        print(
            f"  retires on         {framework}: checkpoint {gate} decided {decision!r}"
        )
    if report.latest_change is not None and set(report.rules) == set(
        report.latest_rules or []
    ):
        print(f"  as last recorded   {RULES_HISTORY} #{report.latest_change}")
    if RULES_MIGRATION in report.migrations:
        unruled = sum(report.unruled.values())
        named = ", ".join(f"{f}: {n}" for f, n in sorted(report.unruled.items()))
        print(
            f"  no rules for       {unruled:>8} record(s)"
            + (f" ({named}): never retired, so never due" if unruled else "")
        )
    if report.counts and not report.counts.get("projects"):
        print(
            "  note: the restored portfolio is empty. If that is not expected, this "
            "dump is not what you think it is."
        )
    if problems:
        print()
        for problem in problems:
            print(f"  FAIL  {problem}")
        print("\nverify-backup: this backup did NOT verify.")
        return 1
    print(
        "\nverify-backup: restored cleanly, with its tables and its "
        "append-only triggers, enabled."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
