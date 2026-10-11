#!/usr/bin/env python3
"""Unit tests for the CI configuration itself.

CI once ran the linters and no tests at all (#32): twenty-four test files, every
regression test for a closed security finding among them, ran only when someone
remembered. That is a failure of configuration, and configuration can be tested.

What is asserted, and why each one earns its place:

* every `pixi run test-*` task is run by .github/workflows/test.yml. A test added
  later cannot be silently left out of CI, which is how the gap opened;
* every tests/test_*.py file is reachable from a pixi task, so a test cannot be
  orphaned either;
* REQUIRE_TESTS is set, so a suite that cannot run fails instead of skipping
  (a skip exits 0 and reads as a pass), in test.yml and in every workflow that
  runs the prek hooks (check-app among them skips `node --check` without node);
* nothing may `continue-on-error`, and every job has a timeout;
* the Postgres in CI is the major version compose.yaml pins;
* one aggregate job depends on all the others, so branch protection can require a
  single name and a new job cannot be forgotten.

Each rule has a mutation test: break a copy of the real workflow and demand the
rule notice. A check that is never shown to fail is a claim, not a control.

    pixi run test-workflows
"""

from __future__ import annotations

import copy
import re
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
TEST_WORKFLOW = WORKFLOWS / "test.yml"
LINT_WORKFLOW = WORKFLOWS / "lint.yml"

TEST_TASK_PREFIX = "test-"
REQUIRE_VAR = "REQUIRE_TESTS"
AGGREGATE_JOB = "tests-passed"
SERVER_JOB = "server"
POSTGRES_SERVICE = "postgres"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


# --- loading ----------------------------------------------------------------


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def triggers(workflow: dict) -> dict:
    """The `on:` block. YAML 1.1 reads the bare key `on` as the boolean True."""
    return workflow.get("on") or workflow.get(True) or {}


def jobs(workflow: dict) -> dict:
    return workflow.get("jobs") or {}


def run_commands(workflow: dict) -> list[str]:
    return [
        step["run"]
        for job in jobs(workflow).values()
        for step in job.get("steps", [])
        if "run" in step
    ]


def pixi_tasks() -> dict[str, str]:
    data = tomllib.loads((ROOT / "pixi.toml").read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for name, value in data.get("tasks", {}).items():
        out[name] = value if isinstance(value, str) else str(value.get("cmd", ""))
    return out


def test_files() -> list[str]:
    return sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))


# --- the rules --------------------------------------------------------------
# Each takes plain data and returns a list of problems, so the mutation tests can
# hand it a deliberately broken copy.


def untested_tasks(workflow: dict, tasks: dict[str, str]) -> list[str]:
    commands = "\n".join(run_commands(workflow))
    wanted = [t for t in tasks if t.startswith(TEST_TASK_PREFIX)]
    return [
        f"pixi task {t!r} is never run by CI"
        for t in wanted
        if not re.search(rf"pixi run {re.escape(t)}\b", commands)
    ]


def orphan_tests(tasks: dict[str, str], files: list[str]) -> list[str]:
    commands = "\n".join(tasks.values())
    return [f"{f} is not run by any pixi task" for f in files if f not in commands]


def no_server_pytest(workflow: dict) -> list[str]:
    server = jobs(workflow).get(SERVER_JOB, {})
    ran = any(
        "pytest" in step.get("run", "") and step.get("working-directory") == "server"
        for step in server.get("steps", [])
    )
    return [] if ran else ["the server job does not run pytest from server/"]


def skips_allowed(workflow: dict) -> list[str]:
    value = str((workflow.get("env") or {}).get(REQUIRE_VAR, ""))
    return (
        []
        if value not in ("", "0", "false")
        else [
            f"{REQUIRE_VAR} is not set at workflow level: a skip would read as a pass"
        ]
    )


def hooks_may_skip(workflows: dict[str, dict]) -> list[str]:
    """Every workflow that runs the prek hooks sets REQUIRE_TESTS: a hook that
    cannot do part of its work (check-app without node) then fails, not skips."""
    return [
        f"{name} runs prek but {problem}"
        for name, wf in workflows.items()
        if any("prek run" in cmd for cmd in run_commands(wf))
        for problem in skips_allowed(wf)
    ]


def swallowed_failures(workflow: dict) -> list[str]:
    problems = []
    for name, job in jobs(workflow).items():
        if job.get("continue-on-error"):
            problems.append(f"job {name!r} has continue-on-error")
        for step in job.get("steps", []):
            if step.get("continue-on-error"):
                problems.append(f"a step in {name!r} has continue-on-error")
    return problems


def missing_timeouts(workflow: dict) -> list[str]:
    return [
        f"job {name!r} has no timeout-minutes"
        for name, job in jobs(workflow).items()
        if "timeout-minutes" not in job
    ]


def postgres_drift(workflow: dict, compose: dict) -> list[str]:
    ci = (
        jobs(workflow)
        .get(SERVER_JOB, {})
        .get("services", {})
        .get(POSTGRES_SERVICE, {})
        .get("image")
    )
    pinned = compose.get("services", {}).get("db", {}).get("image")
    if ci == pinned and ci:
        return []
    return [f"CI tests against {ci!r} but compose.yaml pins {pinned!r}"]


def aggregate_problems(workflow: dict) -> list[str]:
    job = jobs(workflow).get(AGGREGATE_JOB)
    if job is None:
        return [f"there is no {AGGREGATE_JOB!r} aggregate job"]
    problems = []
    others = set(jobs(workflow)) - {AGGREGATE_JOB}
    needs = set(job.get("needs", []))
    if others - needs:
        problems.append(f"{AGGREGATE_JOB} does not depend on {sorted(others - needs)}")
    if "always()" not in str(job.get("if", "")):
        problems.append(
            f"{AGGREGATE_JOB} would be skipped, not failed, when a job fails"
        )
    conditions = " ".join(str(s.get("if", "")) for s in job.get("steps", []))
    if "skipped" not in conditions:
        problems.append(f"{AGGREGATE_JOB} treats a skipped job as a pass")
    return problems


def trigger_problems(workflow: dict) -> list[str]:
    on = triggers(workflow)
    problems = []
    if "pull_request" not in on:
        problems.append("tests do not run on pull_request")
    if "main" not in (on.get("push") or {}).get("branches", []):
        problems.append("tests do not run on push to main")
    return problems


def permission_problems(workflow: dict) -> list[str]:
    permissions = workflow.get("permissions")
    if permissions is None:
        return ["no top-level permissions block (the default is broad)"]
    writes = [k for k, v in permissions.items() if v != "read"]
    return [f"test workflow requests {k}: {permissions[k]}" for k in writes]


def actionlint_missing(workflow: dict) -> list[str]:
    return (
        []
        if "actionlint" in "\n".join(run_commands(workflow))
        else ["the workflows are not statically analyzed (actionlint)"]
    )


ENGINES_JOB = "engines"
ENGINE_SUITES = (
    "pixi run test-csp",
    "pixi run test-injection",
    "pixi run test-markdown-render",
)
OTHER_ENGINES = {"firefox", "webkit"}


def engine_problems(workflow: dict) -> list[str]:
    """The page policy and the injection suite run in Firefox and WebKit (#160)."""
    job = jobs(workflow).get(ENGINES_JOB)
    if job is None:
        return [f"there is no {ENGINES_JOB!r} job, so only Chromium is tested"]
    problems = []
    matrix = set(job.get("strategy", {}).get("matrix", {}).get("engine", []))
    if matrix != OTHER_ENGINES:
        problems.append(
            f"{ENGINES_JOB} runs {sorted(matrix)}, not {sorted(OTHER_ENGINES)}"
        )
    if "matrix.engine" not in str(job.get("env", {}).get("TEST_BROWSER", "")):
        problems.append(f"{ENGINES_JOB} does not pass the engine as TEST_BROWSER")
    runs = " ".join(str(s.get("run", "")) for s in job.get("steps", []))
    problems += [
        f"{ENGINES_JOB} does not run `{suite}`"
        for suite in ENGINE_SUITES
        if suite not in runs
    ]
    if "playwright install" not in runs or "matrix.engine" not in runs:
        problems.append(f"{ENGINES_JOB} does not install the engine it tests")
    return problems


def every_rule(
    workflow: dict, tasks: dict, files: list[str], compose: dict
) -> list[str]:
    return [
        *untested_tasks(workflow, tasks),
        *orphan_tests(tasks, files),
        *no_server_pytest(workflow),
        *skips_allowed(workflow),
        *swallowed_failures(workflow),
        *missing_timeouts(workflow),
        *postgres_drift(workflow, compose),
        *aggregate_problems(workflow),
        *engine_problems(workflow),
        *trigger_problems(workflow),
        *permission_problems(workflow),
        *actionlint_missing(workflow),
    ]


# --- tests ------------------------------------------------------------------


def main() -> int:
    workflow = load(TEST_WORKFLOW)
    tasks = pixi_tasks()
    files = test_files()
    compose = load(ROOT / "compose.yaml")

    print("The real configuration")
    problems = every_rule(workflow, tasks, files, compose)
    check(
        "every rule passes on .github/workflows/test.yml",
        not problems,
        "; ".join(problems),
    )
    check(
        "there are pixi test tasks to cover",
        sum(t.startswith(TEST_TASK_PREFIX) for t in tasks) >= 10,
    )
    check("there are test files to cover", len(files) >= 10)

    every = {path.name: load(path) for path in sorted(WORKFLOWS.glob("*.yml"))}
    check(
        "every workflow running the prek hooks sets REQUIRE_TESTS",
        not hooks_may_skip(every),
        "; ".join(hooks_may_skip(every)),
    )
    check(
        "lint.yml runs the prek hooks (so the rule above covers it)",
        any("prek run" in cmd for cmd in run_commands(load(LINT_WORKFLOW))),
    )

    print("Every workflow file")
    for path in sorted(WORKFLOWS.glob("*.yml")):
        wf = load(path)
        check(f"{path.name}: parses and has jobs", bool(jobs(wf)))
        check(
            f"{path.name}: has a permissions block", wf.get("permissions") is not None
        )
        check(
            f"{path.name}: does not use pull_request_target",
            "pull_request_target" not in triggers(wf),
        )

    print("Mutation tests: each rule must notice when it is broken")

    broken = copy.deepcopy(workflow)
    for job in jobs(broken).values():
        job["steps"] = [s for s in job["steps"] if "test-pdf" not in s.get("run", "")]
    check(
        "a suite dropped from CI is noticed",
        any("test-pdf" in p for p in untested_tasks(broken, tasks)),
    )

    check(
        "a new pixi test task nobody wired into CI is noticed",
        any(
            "test-brand-new" in p
            for p in untested_tasks(
                workflow, {**tasks, "test-brand-new": "python x.py"}
            )
        ),
    )
    check(
        "a test file no task runs is noticed",
        any(
            "test_orphan.py" in p
            for p in orphan_tests(tasks, [*files, "test_orphan.py"])
        ),
    )

    broken = copy.deepcopy(workflow)
    del broken["env"][REQUIRE_VAR]
    check("REQUIRE_TESTS removed is noticed", bool(skips_allowed(broken)))
    broken["env"][REQUIRE_VAR] = "0"
    check("REQUIRE_TESTS set to 0 is noticed", bool(skips_allowed(broken)))

    broken = copy.deepcopy(every)
    del broken[LINT_WORKFLOW.name]["env"][REQUIRE_VAR]
    check(
        "REQUIRE_TESTS removed from lint.yml, which runs prek, is noticed",
        any(LINT_WORKFLOW.name in p for p in hooks_may_skip(broken)),
    )

    broken = copy.deepcopy(workflow)
    jobs(broken)["browser"]["steps"][-1]["continue-on-error"] = True
    check("continue-on-error on a step is noticed", bool(swallowed_failures(broken)))
    broken = copy.deepcopy(workflow)
    jobs(broken)["stack"]["continue-on-error"] = True
    check("continue-on-error on a job is noticed", bool(swallowed_failures(broken)))

    broken = copy.deepcopy(workflow)
    del jobs(broken)["server"]["timeout-minutes"]
    check("a job with no timeout is noticed", bool(missing_timeouts(broken)))

    broken = copy.deepcopy(workflow)
    jobs(broken)[SERVER_JOB]["services"][POSTGRES_SERVICE]["image"] = "postgres:16"
    check(
        "Postgres drifting from compose.yaml is noticed",
        bool(postgres_drift(broken, compose)),
    )

    broken = copy.deepcopy(workflow)
    for step in jobs(broken)[SERVER_JOB]["steps"]:
        step.pop("working-directory", None)
    check("pytest not run from server/ is noticed", bool(no_server_pytest(broken)))

    broken = copy.deepcopy(workflow)
    jobs(broken)[AGGREGATE_JOB]["needs"].remove("stack")
    check(
        "an aggregate that forgets a job is noticed", bool(aggregate_problems(broken))
    )
    broken = copy.deepcopy(workflow)
    jobs(broken)[AGGREGATE_JOB]["if"] = "${{ success() }}"
    check(
        "an aggregate that is skipped, not failed, is noticed",
        bool(aggregate_problems(broken)),
    )
    broken = copy.deepcopy(workflow)
    del jobs(broken)[ENGINES_JOB]
    check("no engines job is noticed", bool(engine_problems(broken)))
    broken = copy.deepcopy(workflow)
    jobs(broken)[ENGINES_JOB]["strategy"]["matrix"]["engine"] = ["firefox"]
    check("a missing WebKit is noticed", bool(engine_problems(broken)))
    broken = copy.deepcopy(workflow)
    del jobs(broken)[ENGINES_JOB]["env"]["TEST_BROWSER"]
    check(
        "an engine never passed to the tests is noticed", bool(engine_problems(broken))
    )
    broken = copy.deepcopy(workflow)
    del jobs(broken)[ENGINES_JOB]["steps"][-1]
    check("a dropped suite is noticed", bool(engine_problems(broken)))
    broken = copy.deepcopy(workflow)
    del jobs(broken)[AGGREGATE_JOB]
    check("no aggregate job is noticed", bool(aggregate_problems(broken)))
    broken = copy.deepcopy(workflow)
    jobs(broken)["brand_new"] = {
        "runs-on": "ubuntu-latest",
        "timeout-minutes": 5,
        "steps": [],
    }
    check(
        "a new job the aggregate ignores is noticed", bool(aggregate_problems(broken))
    )

    broken = copy.deepcopy(workflow)
    del broken[True]["pull_request"]
    check(
        "tests not running on pull_request is noticed", bool(trigger_problems(broken))
    )

    broken = copy.deepcopy(workflow)
    broken["permissions"] = {"contents": "write"}
    check(
        "write permissions on the test workflow are noticed",
        bool(permission_problems(broken)),
    )
    del broken["permissions"]
    check("a missing permissions block is noticed", bool(permission_problems(broken)))

    broken = copy.deepcopy(workflow)
    for job in jobs(broken).values():
        job["steps"] = [s for s in job["steps"] if "actionlint" not in s.get("run", "")]
    check("dropping actionlint is noticed", bool(actionlint_missing(broken)))

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("workflow checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
