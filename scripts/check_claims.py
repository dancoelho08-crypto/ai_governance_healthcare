#!/usr/bin/env python3
"""Fail when a security claim is not backed by something that runs.

This repository kept finding the same bug: a sentence in the docs or the UI
asserting a property that no test checked, and that turned out to be false.

    #31  "a checkpoint sign-off means something"   the client chose who signed
    #55  the header says "Shared workspace"        saves said "Saved in this browser"
    #56  "`make check-isolation` asserts this"     step 3 asserted nothing
    #61  PROXY_SHARED_SECRET offered as a control  nothing sent the header

Correcting the sentences does not scale; it is how the repository got here. So
docs/security-claims.md lists every security property it asserts, and this checks
the list. Each claim has:

    Asserted in   a file and the sentence QUOTED from it. The quote must still be
                  there, so when the doc changes the row has to change with it.
    Status        enforced | partial | unenforced | violated
    Enforced by   the tests that enforce it, as `path::name`. Each must exist,
                  AND be something CI runs, because a test nobody runs (#32) is
                  decoration.
    Gap           for anything not fully enforced: why, and the issue (#NN).

The honest statuses matter. A claim the code does not back is allowed to stay in
the inventory, but only as `violated`, with an issue, in plain sight. What is not
allowed is a claim that looks enforced and is not.

Evidence is one of:
    server/tests/x.py::TestK::test_name    a pytest test, found by `def`/`class`
    mcp/tests/x.py::test_name              the same, for the MCP service (#164)
    tests/test_x.py::a check name          a script suite's check("...") text
    tests/test_x.py                        the whole file
    .pre-commit-config.yaml::hook-id       a hook, which CI runs through prek

    pixi run check-claims
"""

from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

try:
    from enum import StrEnum
except ImportError:  # Python 3.10; the repository itself targets 3.11+

    class StrEnum(str, Enum):  # noqa: UP042
        def __str__(self) -> str:
            return str(self.value)


ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "security-claims.md"
TEST_WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"
LINT_WORKFLOW = ROOT / ".github" / "workflows" / "lint.yml"
PRECOMMIT = ROOT / ".pre-commit-config.yaml"
PIXI = ROOT / "pixi.toml"


class Status(StrEnum):
    ENFORCED = "enforced"
    PARTIAL = "partial"
    UNENFORCED = "unenforced"
    VIOLATED = "violated"


class Field_(StrEnum):
    CLAIM = "Claim"
    ASSERTED = "Asserted in"
    STATUS = "Status"
    EVIDENCE = "Enforced by"
    GAP = "Gap"


HEADING = re.compile(r"^### (C-\d+)[ \t]+(.+?)[ \t]*$", re.MULTILINE)
FIELD_START = re.compile(r"^- \*\*([^:*]+):\*\*[ \t]*(.*)$")
ASSERTION = re.compile(r'^`([^`]+)`\s*[—-]\s*"(.*)"$')
ISSUE = re.compile(r"#\d+")
PYTEST_NAME = re.compile(r"(Test\w+|test_\w+)")
PRECOMMIT_REF = ".pre-commit-config.yaml"
SERVER_TESTS = "server/tests/"
# The optional MCP service's own pytest suite (#164), run from mcp/ in the server job.
MCP_TESTS = "mcp/tests/"
SCRIPT_TESTS = "tests/"


@dataclass
class Claim:
    id: str
    title: str
    claim: str = ""
    assertions: list[tuple[str, str]] = field(default_factory=list)
    status: Status | None = None
    evidence: list[str] = field(default_factory=list)
    gap: str = ""
    parse_problems: list[str] = field(default_factory=list)


@dataclass
class Context:
    """Everything a claim is checked against, so tests can supply their own."""

    root: Path
    workflow_text: str
    pixi_tasks: dict[str, str]
    precommit_text: str
    lint_workflow_text: str


def normalize(text: str) -> str:
    """Collapse runs of whitespace, so a quote survives the source's line wrapping."""
    return " ".join(text.split())


# --- parsing -----------------------------------------------------------------


def _fields(block: str) -> list[tuple[str, str]]:
    """The `- **Label:** value` bullets of one claim, continuation lines joined."""
    out: list[tuple[str, str]] = []
    current: list[str] | None = None
    for line in block.splitlines():
        start = FIELD_START.match(line)
        if start:
            current = [start.group(1), start.group(2)]
            out.append((current[0], current[1]))
            continue
        if current is not None and line.startswith("  ") and line.strip():
            label, value = out[-1]
            out[-1] = (label, f"{value} {line.strip()}")
        elif not line.strip():
            current = None
    return out


def parse_claims(text: str) -> list[Claim]:
    matches = list(HEADING.finditer(text))
    claims: list[Claim] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        claim = Claim(id=match.group(1), title=match.group(2))
        known = {f.value for f in Field_}
        for label, raw in _fields(text[match.end() : end]):
            value = normalize(raw)
            if label not in known:
                claim.parse_problems.append(f"{claim.id}: unknown field '{label}'")
            elif label == Field_.CLAIM:
                claim.claim = value
            elif label == Field_.ASSERTED:
                found = ASSERTION.match(value)
                if found:
                    claim.assertions.append((found.group(1), found.group(2)))
                else:
                    claim.parse_problems.append(
                        f'{claim.id}: Asserted in must be `path` — "quote" '
                        f"(got: {value[:60]})"
                    )
            elif label == Field_.STATUS:
                try:
                    claim.status = Status(value.lower())
                except ValueError:
                    allowed = ", ".join(s.value for s in Status)
                    claim.parse_problems.append(
                        f"{claim.id}: status '{value}' is not one of: {allowed}"
                    )
            elif label == Field_.EVIDENCE:
                claim.evidence += re.findall(r"`([^`]+)`", value)
            elif label == Field_.GAP:
                claim.gap = value
        claims.append(claim)
    return claims


# --- validation --------------------------------------------------------------


def _read(ctx: Context, relative: str) -> str | None:
    path = ctx.root / relative
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _ci_problem(path: str, ctx: Context) -> str | None:
    """Why CI would NOT run this evidence, or None if it does."""
    if path == PRECOMMIT_REF:
        return (
            None
            if "prek" in ctx.lint_workflow_text
            else ("CI does not run the pre-commit hooks (lint.yml has no prek)")
        )
    if path.startswith(SERVER_TESTS):
        ran = (
            "pytest" in ctx.workflow_text
            and "working-directory: server" in ctx.workflow_text
        )
        return None if ran else "CI does not run pytest from server/"
    if path.startswith(MCP_TESTS):
        ran = (
            "pytest" in ctx.workflow_text
            and "working-directory: mcp" in ctx.workflow_text
        )
        return None if ran else "CI does not run pytest from mcp/"
    if path.startswith(SCRIPT_TESTS) and path.endswith(".py"):
        tasks = [t for t, cmd in ctx.pixi_tasks.items() if path in cmd]
        if not tasks:
            return f"no pixi task runs {path}, so CI cannot"
        if any(f"pixi run {t}" in ctx.workflow_text for t in tasks):
            return None
        return f"CI never runs {', '.join(tasks)}"
    return (
        f"{path} is not something CI runs (evidence is server/tests, mcp/tests, "
        "a tests/ suite with a pixi task CI runs, or a pre-commit hook)"
    )


def _evidence_problems(ref: str, ctx: Context) -> list[str]:
    path, *names = ref.split("::")
    # The hook list comes from the context, not a file read: the context is what
    # the checker was told the repository looks like.
    text = ctx.precommit_text if path == PRECOMMIT_REF else _read(ctx, path)
    if text is None:
        return [f"evidence {ref}: {path} does not exist"]
    problems: list[str] = []
    if path == PRECOMMIT_REF:
        for name in names:
            if f"id: {name}" not in ctx.precommit_text:
                problems.append(
                    f"evidence {ref}: hook '{name}' is not defined in {path}"
                )
    else:
        for name in names:
            if PYTEST_NAME.fullmatch(name):
                if not re.search(rf"\b(class|def)\s+{re.escape(name)}\b", text):
                    problems.append(f"evidence {ref}: {name} is not defined in {path}")
            elif name not in text:
                problems.append(f"evidence {ref}: '{name}' does not appear in {path}")
    ci = _ci_problem(path, ctx)
    if ci:
        problems.append(f"evidence {ref}: {ci}")
    return problems


def validate_claim(claim: Claim, ctx: Context) -> list[str]:
    problems = list(claim.parse_problems)
    if not claim.assertions and not any("Asserted in" in p for p in problems):
        problems.append(f"{claim.id}: has no Asserted in")
    for path, quote in claim.assertions:
        text = _read(ctx, path)
        if text is None:
            problems.append(f"{claim.id}: {path} does not exist")
        elif normalize(quote) not in normalize(text):
            problems.append(
                f'{claim.id}: the quote is no longer in {path}: "{quote[:70]}". '
                "The doc changed under this row; update the row, or the doc."
            )
    for ref in claim.evidence:
        problems += [f"{claim.id}: {p}" for p in _evidence_problems(ref, ctx)]

    status = claim.status
    has_issue = bool(ISSUE.search(claim.gap))
    if status is Status.ENFORCED and not claim.evidence:
        problems.append(
            f"{claim.id}: enforced, but it names no evidence in 'Enforced by'"
        )
    if status is Status.PARTIAL and not (claim.evidence and has_issue):
        problems.append(
            f"{claim.id}: partial needs evidence AND a Gap naming an issue (#NN)"
        )
    if status is Status.UNENFORCED and not claim.gap:
        problems.append(f"{claim.id}: unenforced needs a Gap stating why")
    if status is Status.VIOLATED and not has_issue:
        problems.append(f"{claim.id}: violated needs a Gap naming its issue (#NN)")
    return problems


def validate(claims: list[Claim], ctx: Context) -> list[str]:
    if not claims:
        return ["there are no claims in the inventory"]
    problems: list[str] = []
    seen: set[str] = set()
    for claim in claims:
        if claim.id in seen:
            problems.append(f"{claim.id}: duplicate id")
        seen.add(claim.id)
        problems += validate_claim(claim, ctx)
    return problems


def summarize(claims: list[Claim]) -> dict[Status, int]:
    counts = {status: 0 for status in Status}
    for claim in claims:
        if claim.status is not None:
            counts[claim.status] += 1
    return counts


# --- command line ------------------------------------------------------------


def repo_context() -> Context:
    data = tomllib.loads(PIXI.read_text(encoding="utf-8"))
    tasks = {
        name: value if isinstance(value, str) else str(value.get("cmd", ""))
        for name, value in data.get("tasks", {}).items()
    }
    return Context(
        root=ROOT,
        workflow_text=TEST_WORKFLOW.read_text(encoding="utf-8"),
        pixi_tasks=tasks,
        precommit_text=PRECOMMIT.read_text(encoding="utf-8"),
        lint_workflow_text=LINT_WORKFLOW.read_text(encoding="utf-8"),
    )


def main() -> int:
    claims = parse_claims(PAGE.read_text(encoding="utf-8"))
    problems = validate(claims, repo_context())
    if problems:
        print(
            f"\n  {len(problems)} problem(s) in {PAGE.relative_to(ROOT)}:\n",
            file=sys.stderr,
        )
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\n  A claim must be quoted from where it is made, and backed by a test CI "
            "runs,\n  or be listed honestly as partial, unenforced or violated.\n",
            file=sys.stderr,
        )
        return 1
    counts = summarize(claims)
    breakdown = ", ".join(f"{n} {s.value}" for s, n in counts.items())
    print(f"check-claims: ok ({len(claims)} claims: {breakdown})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
