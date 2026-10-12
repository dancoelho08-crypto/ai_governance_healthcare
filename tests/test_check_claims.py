#!/usr/bin/env python3
"""The security-claims checker, tested by trying to make it accept a lie.

docs/security-claims.md lists every security property this project asserts, where
it asserts it (with the sentence quoted), and the test that enforces it. The
checker is what stops that page being decoration, so it has to be shown to fail:

* a quote that is no longer in the file it cites (the doc changed under the row);
* evidence that points at a file or a test that does not exist;
* evidence that exists but that CI never runs, which is how #32 happened;
* a claim marked enforced with nothing enforcing it;
* a claim that is not enforced and does not say so, or says so without an issue.

The "known violation" statuses are the honest part: a claim the code does not back
is allowed to stay in the inventory, but only as `violated`, with an issue, in
plain sight. What is not allowed is a claim that looks enforced and is not.

    pixi run test-claims
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_claims.py"
spec = importlib.util.spec_from_file_location("check_claims", SCRIPT)
cc = importlib.util.module_from_spec(spec)
sys.modules["check_claims"] = cc
spec.loader.exec_module(cc)

failures: list[str] = []

SERVER_ONLY = (
    "jobs:\n  s:\n    steps:\n      - run: pytest\n        working-directory: server\n"
)
SECOND_ASSERTION = '- **Asserted in:** `docs/doc.md` — "and sets its own"'


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def page(
    *,
    status: str = "enforced",
    quote: str = "proxy strips it",
    path: str = "docs/doc.md",
    evidence: str = "`tests/test_a.py::test_strips_it`",
    gap: str = "",
    title: str = "C-01 A claim",
) -> str:
    lines = [
        f"### {title}",
        "",
        "- **Claim:** The proxy strips the header.",
        f'- **Asserted in:** `{path}` — "{quote}"',
        f"- **Status:** {status}",
    ]
    if evidence:
        lines.append(f"- **Enforced by:** {evidence}")
    if gap:
        lines.append(f"- **Gap:** {gap}")
    return "\n".join(lines) + "\n"


def world(root: Path, **overrides) -> cc.Context:
    (root / "docs").mkdir(exist_ok=True)
    (root / "tests").mkdir(exist_ok=True)
    (root / "server" / "tests").mkdir(parents=True, exist_ok=True)
    (root / "mcp" / "tests").mkdir(parents=True, exist_ok=True)
    (root / "mcp" / "tests" / "test_m.py").write_text(
        "async def test_m():\n    pass\n", encoding="utf-8"
    )
    (root / "docs" / "doc.md").write_text(
        "Intro.\n\nThe proxy strips it,\nand sets its own.\n", encoding="utf-8"
    )
    (root / "tests" / "test_a.py").write_text(
        "def check(n, ok): pass\n\ndef test_strips_it():\n    pass\n\n"
        "class TestK:\n    def test_inside(self):\n        pass\n\n"
        'check("a forged header is refused", True)\n',
        encoding="utf-8",
    )
    (root / "server" / "tests" / "test_s.py").write_text(
        "class TestZ:\n    async def test_z(self):\n        pass\n", encoding="utf-8"
    )
    (root / "Makefile").write_text("check-isolation:\n\t@true\n", encoding="utf-8")
    return cc.Context(
        root=root,
        workflow_text=overrides.get(
            "workflow_text",
            "jobs:\n  server:\n    steps:\n      - run: pytest\n"
            "        working-directory: server\n      - run: pytest\n"
            "        working-directory: mcp\n  w:\n    steps:\n"
            "      - run: pixi run test-a\n",
        ),
        pixi_tasks=overrides.get("pixi_tasks", {"test-a": "python tests/test_a.py"}),
        precommit_text=overrides.get(
            "precommit_text", "      - id: build-app\n      - id: check-claims\n"
        ),
        lint_workflow_text=overrides.get(
            "lint_workflow_text", "- run: pixi run prek run\n"
        ),
    )


def problems_for(text: str, **overrides) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        ctx = world(Path(tmp), **overrides)
        return cc.validate(cc.parse_claims(text), ctx)


def main() -> int:
    print("A well-formed, honest claim passes")
    check("enforced with real evidence and a real quote", problems_for(page()) == [])
    check(
        "the quote may wrap across lines in the source",
        problems_for(page(quote="The proxy strips it, and sets its own.")) == [],
    )

    print("Parsing")
    parsed = cc.parse_claims(page() + "\n" + page(title="C-02 Another"))
    check("two claims are parsed", [c.id for c in parsed] == ["C-01", "C-02"])
    check("the status is an enumerated value", parsed[0].status is cc.Status.ENFORCED)
    check(
        "a claim can be asserted in several places",
        len(
            cc.parse_claims(
                page().replace(
                    "- **Status:",
                    SECOND_ASSERTION + "\n- **Status:",
                )
            )[0].assertions
        )
        == 2,
    )
    check(
        "a wrapped field value is joined",
        cc.parse_claims(
            page().replace(
                "The proxy strips the header.", "The proxy strips\n  the header."
            )
        )[0].claim
        == "The proxy strips the header.",
    )
    check(
        "an unknown status is refused",
        any("status" in p.lower() for p in problems_for(page(status="mostly"))),
    )
    check(
        "an unknown field label is refused",
        any(
            "unknown" in p.lower()
            for p in problems_for(page().replace("**Claim:**", "**Idea:**"))
        ),
    )
    check(
        "a claim with no Asserted in is refused",
        any(
            "Asserted in" in p
            for p in problems_for(page().replace("- **Asserted in:**", "- **Note:**"))
        ),
    )
    check(
        "a malformed Asserted in is refused",
        any("Asserted in" in p for p in problems_for(page().replace(" — ", " "))),
    )
    check(
        "a duplicate id is refused",
        any("duplicate" in p.lower() for p in problems_for(page() + page())),
    )
    check(
        "an empty inventory is refused",
        any("no claims" in p.lower() for p in problems_for("# Title\n")),
    )

    print("The quote must still be in the file that is cited")
    check(
        "a quote that is not there is noticed",
        any(
            "quote" in p.lower()
            for p in problems_for(page(quote="the proxy lets it through"))
        ),
    )
    check(
        "a file that does not exist is noticed",
        any("does not exist" in p for p in problems_for(page(path="docs/gone.md"))),
    )
    check(
        "the doc changing under the row is noticed",
        any(
            "quote" in p.lower()
            for p in problems_for(page(quote="strips it, and then sets its own"))
        ),
    )

    print("Evidence must exist")
    check(
        "a test file that does not exist is noticed",
        any(
            "does not exist" in p
            for p in problems_for(page(evidence="`tests/test_missing.py::test_x`"))
        ),
    )
    check(
        "a test that is not in the file is noticed",
        any(
            "test_nope" in p
            for p in problems_for(page(evidence="`tests/test_a.py::test_nope`"))
        ),
    )
    check(
        "a test in a class resolves",
        problems_for(page(evidence="`tests/test_a.py::TestK::test_inside`")) == [],
    )
    check(
        "a class that is not there is noticed",
        any(
            "TestNope" in p
            for p in problems_for(
                page(evidence="`tests/test_a.py::TestNope::test_inside`")
            )
        ),
    )
    check(
        "a script-style check name resolves by its text",
        problems_for(page(evidence="`tests/test_a.py::a forged header is refused`"))
        == [],
    )
    check(
        "a script-style name that is not there is noticed",
        any(
            "is allowed" in p
            for p in problems_for(
                page(evidence="`tests/test_a.py::a forged header is allowed`")
            )
        ),
    )
    check(
        "a whole-file reference resolves",
        problems_for(page(evidence="`tests/test_a.py`")) == [],
    )
    check(
        "a pre-commit hook id resolves",
        problems_for(page(evidence="`.pre-commit-config.yaml::build-app`")) == [],
    )
    check(
        "a pre-commit hook that does not exist is noticed",
        any(
            "nope" in p
            for p in problems_for(page(evidence="`.pre-commit-config.yaml::nope`"))
        ),
    )

    print("Evidence must be something CI actually runs")
    check(
        "a server pytest test is run by CI",
        problems_for(page(evidence="`server/tests/test_s.py::TestZ::test_z`")) == [],
    )
    check(
        "a server test is NOT counted if CI does not run pytest in server/",
        any(
            "CI" in p
            for p in problems_for(
                page(evidence="`server/tests/test_s.py::TestZ::test_z`"),
                workflow_text="jobs: {}",
            )
        ),
    )
    check(
        "an MCP pytest test is run by CI",
        problems_for(page(evidence="`mcp/tests/test_m.py::test_m`")) == [],
    )
    check(
        "an MCP test is NOT counted if CI does not run pytest in mcp/",
        any(
            "mcp/" in p
            for p in problems_for(
                page(evidence="`mcp/tests/test_m.py::test_m`"),
                workflow_text=SERVER_ONLY,
            )
        ),
    )
    check(
        "a script suite with a pixi task CI runs is counted", problems_for(page()) == []
    )
    check(
        "a script suite whose pixi task CI never runs is noticed",
        any(
            "CI" in p
            for p in problems_for(
                page(),
                workflow_text=SERVER_ONLY,
            )
        ),
    )
    check(
        "a script suite with no pixi task at all is noticed",
        any("CI" in p for p in problems_for(page(), pixi_tasks={})),
    )
    check(
        "a Makefile target is not evidence CI runs",
        any(
            "CI" in p
            for p in problems_for(page(evidence="`Makefile::check-isolation`"))
        ),
    )
    check(
        "a hook is not counted if CI does not run prek",
        any(
            "CI" in p
            for p in problems_for(
                page(evidence="`.pre-commit-config.yaml::build-app`"),
                lint_workflow_text="",
            )
        ),
    )

    print("Status must be honest")
    check(
        "enforced with no evidence is noticed",
        any("evidence" in p.lower() for p in problems_for(page(evidence=""))),
    )
    check(
        "partial needs evidence AND a gap with an issue",
        any("issue" in p.lower() for p in problems_for(page(status="partial"))),
    )
    check(
        "partial with evidence and an issue passes",
        problems_for(page(status="partial", gap="Only the happy path. #12")) == [],
    )
    check(
        "violated needs an issue",
        any(
            "issue" in p.lower()
            for p in problems_for(
                page(status="violated", evidence="", gap="It is false.")
            )
        ),
    )
    check(
        "violated with an issue passes",
        problems_for(page(status="violated", evidence="", gap="It is false. See #56."))
        == [],
    )
    check(
        "unenforced needs a stated reason",
        any(
            "gap" in p.lower()
            for p in problems_for(page(status="unenforced", evidence=""))
        ),
    )
    check(
        "unenforced with a reason passes",
        problems_for(
            page(
                status="unenforced",
                evidence="",
                gap="Rests on the cloud's own configuration; not testable here.",
            )
        )
        == [],
    )
    check("enforced does not need a gap", problems_for(page(gap="")) == [])

    print("The summary counts every status")
    many = (
        page()
        + page(title="C-02 B", status="violated", evidence="", gap="False. #5")
        + page(title="C-03 C", status="unenforced", evidence="", gap="External.")
    )
    counts = cc.summarize(cc.parse_claims(many))
    check(
        "each status is counted",
        counts
        == {
            cc.Status.ENFORCED: 1,
            cc.Status.PARTIAL: 0,
            cc.Status.UNENFORCED: 1,
            cc.Status.VIOLATED: 1,
        },
        str(counts),
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("claims checker tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
