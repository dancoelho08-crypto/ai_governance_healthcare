#!/usr/bin/env python3
"""The enum guardrail, tested as a guardrail.

A check that is never shown to fail is a claim, not a control. These cases pin
both directions: what it must catch (a comparison to a bare string in Python or
JavaScript, a Literal used as an enum, a state variable assigned a word), what
it must leave alone (paths, prose, dunders, typeof, a single named constant, a
reasoned `enum-ok`), and how the ratchet behaves (growth fails, a stale
baseline fails, the baseline will not grow without being told to).

    pixi run test-enums
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_enums.py"
spec = importlib.util.spec_from_file_location("check_enums", SCRIPT)
ce = importlib.util.module_from_spec(spec)
sys.modules["check_enums"] = ce
spec.loader.exec_module(ce)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def py(source: str) -> list[str]:
    return [f.literal for f in ce.scan_python(source, "server/app/x.py")]


def js(source: str) -> list[str]:
    return [f.literal for f in ce.scan_javascript(source, "app/js/x.js")]


def new_shapes() -> None:
    """The evasions an adversarial review found, each now closed."""
    print("Python: shapes the first version missed")
    check("is a word", py('x is "owner"') == ["owner"])
    check("is not a word", py('x is not "owner"') == ["owner"])
    check(
        "in frozenset(...)", sorted(py('x in frozenset({"a1", "b1"})')) == ["a1", "b1"]
    )
    check("in set(...)", sorted(py('x in set(("a1", "b1"))')) == ["a1", "b1"])
    check("in a dict literal", sorted(py('x in {"a1": 1, "b1": 2}')) == ["a1", "b1"])
    check("a kebab-case value", py('s == "in-progress"') == ["in-progress"])
    check(
        "kebab-case in a set",
        sorted(py('s in ("not-met", "met")')) == ["met", "not-met"],
    )
    check(
        "Literal imported under an alias",
        sorted(py('from typing import Literal as L\nx: L["a1", "b1"]')) == ["a1", "b1"],
    )
    check(
        "Literal from typing_extensions",
        sorted(py('from typing_extensions import Literal\nx: Literal["a1", "b1"]'))
        == ["a1", "b1"],
    )
    check(
        "a regex that enumerates the set",
        sorted(py('Field(pattern="^(owner|writer|reader)$")'))
        == ["owner", "reader", "writer"],
    )
    check("startswith a word", py('s.startswith("not")') == ["not"])
    check(
        "endswith a tuple", sorted(py('s.endswith(("_ok", "_err"))')) == ["_err", "_ok"]
    )
    check("removeprefix a word", py('s.removeprefix("pre")') == ["pre"])

    print("Python: and what it still leaves alone")
    check("startswith a path", py('s.startswith("/api")') == [])
    check("startswith a variable", py("s.startswith(prefix)") == [])
    check("a non-enumerating regex", py('Field(pattern="^[a-z]+$")') == [])
    check("a single-word pattern", py('Field(pattern="^owner$")') == [])
    check("not-literal is not Literal", py('x: Other["a1", "b1"]') == [])

    print("Python: the exception marker lives in comments only")
    check(
        "a pragma inside a string does not excuse",
        py('x == "http"; log("# enum-ok: because")') == ["http"],
    )
    check(
        "a pragma in a real comment does",
        py('x == "http"  # enum-ok: ASGI value') == [],
    )

    print("JavaScript: shapes the first version missed")
    check(
        "includes on an array literal",
        sorted(js('["a1","b1"].includes(r)')) == ["a1", "b1"],
    )
    check("indexOf on an array literal", js('["a1"].indexOf(r)') == ["a1"])
    check(
        "new Set([...]).has", sorted(js('new Set(["a1","b1"]).has(r)')) == ["a1", "b1"]
    )
    check("a backtick literal", js("if (m === `api`) {}") == ["api"])
    check("a comparison wrapped after the operator", js('m ===\n  "api"') == ["api"])
    check("a comparison wrapped before the operator", js('m\n  === "api"') == ["api"])
    check("a literal on the left, wrapped", js('"api"\n  === m') == ["api"])
    check('compact case("x"):', js('switch(m){case("api"):break;}') == ["api"])
    check("case with no space", js('switch(m){case"api":break;}') == ["api"])
    check(
        "code after a block comment on the line",
        js('/* c */ if (MODE === "api") {}') == ["api"],
    )
    check("a kebab-case value", js('a === "dl-csv"') == ["dl-csv"])
    check("startsWith a word", js('s.startsWith("not")') == ["not"])
    check("Object.is against a word", js('Object.is(m, "api")') == ["api"])
    check("an uppercase value", js('MODE = "READY";') == ["READY"])
    check("||= a word", js('MODE ||= "api";') == ["api"])
    check("a two-letter state name", js('RO = "yes";') == ["yes"])
    check(
        "a URL string does not start a comment",
        js('u = "http://x"; MODE === "api"') == ["api"],
    )

    print("JavaScript: and what it still leaves alone")
    check(
        "a pragma inside a string does not excuse",
        js('m === "api"; log("// enum-ok: x")') == ["api"],
    )
    check(
        "a pragma in a real comment does", js('m === "api" // enum-ok: DOM value') == []
    )
    check(
        "a pragma in a block comment does",
        js('m === "api" /* enum-ok: DOM value */') == [],
    )
    check("code inside a block comment", js('/* MODE === "api" */') == [])
    check("a multi-line block comment", js('/*\nMODE === "api"\n*/') == [])
    check("an array of non-words", js('["/a","b c"].includes(r)') == [])
    check("includes on a variable", js("ROLES.includes(r)") == [])
    check("a template with substitution", js("m === `a${x}`") == [])

    print("Scope: every Python file and every script under app/, minus tests")
    check(
        "server code outside app/",
        ce.language_of("server/worker/x.py") is ce.Lang.PYTHON,
    )
    check("a new top-level directory", ce.language_of("tools/x.py") is ce.Lang.PYTHON)
    check("a service worker", ce.language_of("app/sw.js") is ce.Lang.JAVASCRIPT)
    check("an ES module", ce.language_of("app/x.mjs") is ce.Lang.JAVASCRIPT)
    check("TypeScript", ce.language_of("app/x.ts") is ce.Lang.JAVASCRIPT)
    check("server tests exempt", ce.language_of("server/tests/x.py") is None)
    check("mcp tests exempt", ce.language_of("mcp/tests/x.py") is None)
    check(
        "mcp application code is checked",
        ce.language_of("mcp/chai_mcp/x.py") is not None,
    )
    check(
        "a tests directory elsewhere in mcp is not exempt",
        ce.language_of("mcp/chai_mcp/tests/x.py") is not None,
    )
    check("top-level tests exempt", ce.language_of("tests/x.py") is None)
    check(
        "a directory merely named tests is NOT exempt",
        ce.language_of("server/app/tests/x.py") is ce.Lang.PYTHON,
    )
    check("the pixi environment is skipped", ce.language_of(".pixi/envs/x.py") is None)


def main() -> int:
    print("Python: what it must catch")
    check("== a word", py('x == "owner"') == ["owner"])
    check("!= a word", py('x != "owner"') == ["owner"])
    check("literal on the left", py('"owner" == x') == ["owner"])
    check("chained comparison", py('a == "x1" != b') == ["x1"])
    check("in a tuple", sorted(py('x in ("a1", "b1")')) == ["a1", "b1"])
    check("not in a set", sorted(py('x not in {"a1", "b1"}')) == ["a1", "b1"])
    check("in a list", sorted(py('x in ["a1", "b1"]')) == ["a1", "b1"])
    check(
        "match on a string",
        py('match x:\n    case "alpha":\n        pass\n    case "beta":\n        pass')
        == ["alpha", "beta"],
    )
    check(
        "Literal as an enum",
        sorted(py('from typing import Literal\nx: Literal["a1", "b1"]'))
        == ["a1", "b1"],
    )
    check(
        "typing.Literal as an enum",
        sorted(py('import typing\nx: typing.Literal["a1", "b1"]')) == ["a1", "b1"],
    )
    check("dotted protocol value", py('t == "http.request"') == ["http.request"])
    check("inside an expression", py('f(x == "owner") and y') == ["owner"])
    check("in a comprehension", py('[a for a in xs if a.k == "owner"]') == ["owner"])

    print("Python: what it must leave alone")
    check("empty string", py('x == ""') == [])
    check("a path", py('p == "/api/health"') == [])
    check("prose with a space", py('m == "not ready"') == [])
    check("punctuation", py('c == ":"') == [])
    check("one character", py('c == "a"') == [])
    check("the __main__ idiom", py('if __name__ == "__main__":\n    pass') == [])
    check("a number", py("x == 5") == [])
    check("an enum member", py("x == Role.OWNER") == [])
    check("a named constant", py("x == OWNER") == [])
    check("a dict key test", py('"owner" in d') == [])
    check("membership in a variable", py("x in ALLOWED") == [])
    check("a one-member Literal", py('x: Literal["a1"]') == [])
    check("assignment is not comparison", py('x = "owner"') == [])
    check("a docstring", py('"""x == "owner" is bad"""') == [])
    check(
        "a syntax error is reported, not silently skipped",
        py("def (:") == [ce.UNPARSEABLE],
    )

    print("Python: the exception marker")
    check("a reasoned enum-ok", py('x == "http"  # enum-ok: ASGI value') == [])
    check("a bare enum-ok does not excuse", py('x == "http"  # enum-ok') == ["http"])
    check(
        "an empty reason does not excuse",
        py('x == "http"  # enum-ok:   ') == ["http"],
    )
    check(
        "the marker excuses a multi-line comparison",
        py('ok = (\n    x\n    == "http"  # enum-ok: ASGI value\n)') == [],
    )

    print("JavaScript: what it must catch")
    check("=== a word", js('if (MODE === "api") {}') == ["api"])
    check("!== a word", js('if (MODE !== "api") {}') == ["api"])
    check("== a word", js('if (a == "api") {}') == ["api"])
    check("literal on the left", js('if ("api" === MODE) {}') == ["api"])
    check("single quotes", js("if (m === 'api') {}") == ["api"])
    check("switch case", js('switch (m) { case "api": break; }') == ["api"])
    check("property comparison", js('v.kind === "stage"') == ["stage"])
    check("state variable assigned", js('let MODE="connecting";') == ["connecting"])
    check(
        "assignment among several declarators",
        js('let STORE=null, MODE="connecting", RO=false;') == ["connecting"],
    )
    check("two on one line", sorted(js('a === "x1" || a === "y1"')) == ["x1", "y1"])

    print("JavaScript: what it must leave alone")
    check("typeof undefined", js('typeof x === "undefined"') == [])
    check("typeof string", js('typeof x !== "string"') == [])
    check("a single named const", js('const API_KEY = "abc";') == [])
    check("a comparison to an enum member", js("MODE === Mode.API") == [])
    check("a // comment line", js('// MODE === "api" is wrong') == [])
    check("a block comment", js('/*\n * if (MODE === "api")\n */') == [])
    check("a path", js('u === "/api"') == [])
    check("an empty string", js('x === ""') == [])
    check("a reasoned enum-ok", js('k === "Enter" // enum-ok: DOM key name') == [])
    check("a bare enum-ok does not excuse", js('k === "Enter" // enum-ok') == ["Enter"])
    check("=== is not read as an assignment", js('MODE === "api"') == ["api"])

    print("Language and path rules")
    check("tests are exempt", ce.language_of("server/tests/test_x.py") is None)
    check("top-level tests are exempt", ce.language_of("tests/test_x.py") is None)
    check("server code is checked", ce.language_of("server/app/x.py") is ce.Lang.PYTHON)
    check("scripts are checked", ce.language_of("scripts/x.py") is ce.Lang.PYTHON)
    check(
        "app JS is checked", ce.language_of("app/js/20-app/x.js") is ce.Lang.JAVASCRIPT
    )
    check("the built bundle is not", ce.language_of("docs/app/index.html") is None)
    check("migrations are not", ce.language_of("server/migrations/001.sql") is None)

    new_shapes()

    print("The ratchet")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir()
        (root / "server" / "app").mkdir(parents=True)
        (root / "app" / "js").mkdir(parents=True)
        ce.ROOT = root
        ce.BASELINE = root / "scripts" / "enum_baseline.json"
        target = root / "server" / "app" / "x.py"

        def run(files=None) -> int:
            sink = io.StringIO()
            real = sys.stderr, sys.stdout
            sys.stderr = sys.stdout = sink
            try:
                return ce.run_check(files)
            finally:
                sys.stderr, sys.stdout = real

        target.write_text('x == "owner"\n')
        check("a new violation fails with no baseline", run() == 1)

        real_err = sys.stderr
        sys.stderr = io.StringIO()
        try:
            status = ce.run_update(allow_growth=False)
        finally:
            sys.stderr = real_err
        check("the baseline refuses to grow by itself", status == 1)
        check("and wrote nothing", not ce.BASELINE.exists())

        sink = io.StringIO()
        real = sys.stdout
        sys.stdout = sink
        try:
            status = ce.run_update(allow_growth=True)
        finally:
            sys.stdout = real
        check("--allow-growth seeds it", status == 0 and ce.BASELINE.exists())
        check("an existing use then passes", run() == 0)

        target.write_text('x == "owner"\ny == "owner"\n')
        check("a second use of the same word fails", run() == 1)
        target.write_text('x == "owner"\ny == "writer"\n')
        check("a different word fails", run() == 1)

        target.write_text("x is Role.OWNER\n")
        check("fixing one makes the baseline stale, which fails", run() == 1)
        check(
            "--files mode does not complain about staleness",
            run(["server/app/x.py"]) == 0,
        )

        sink = io.StringIO()
        real = sys.stdout
        sys.stdout = sink
        try:
            ce.run_update(allow_growth=False)
        finally:
            sys.stdout = real
        check("ratcheting down is allowed and then passes", run() == 0)
        data = json.loads(ce.BASELINE.read_text())
        check("the baseline is now empty", data == {}, str(data))

        print("The Claude Code hook")

        def hook(payload: dict) -> tuple[int, str]:
            sink = io.StringIO()
            real_in, real_err = sys.stdin, sys.stderr
            sys.stdin, sys.stderr = io.StringIO(json.dumps(payload)), sink
            try:
                return ce.run_hook(), sink.getvalue()
            finally:
                sys.stdin, sys.stderr = real_in, real_err

        target.write_text('x == "owner"\n')
        code, err = hook({"tool_input": {"file_path": str(target)}})
        check("a violating edit exits 2", code == 2, str(code))
        check(
            "and names the file and the fix",
            "server/app/x.py" in err and "StrEnum" in err,
        )

        target.write_text("x is Role.OWNER\n")
        code, _ = hook({"tool_input": {"file_path": str(target)}})
        check("a clean edit exits 0", code == 0, str(code))

        test_file = root / "server" / "tests" / "test_x.py"
        test_file.parent.mkdir(parents=True)
        test_file.write_text('x == "owner"\n')
        code, _ = hook({"tool_input": {"file_path": str(test_file)}})
        check("an edit to a test file exits 0", code == 0, str(code))

        code, _ = hook({"tool_input": {"file_path": "/etc/hosts"}})
        check("a file outside the repository exits 0", code == 0, str(code))
        code, _ = hook({"tool_input": {}})
        check(
            "--files with a deleted path is skipped, not a crash",
            run(["server/app/does_not_exist.py"]) == 0,
        )
        check("a payload with no file exits 0", code == 0, str(code))

        print("The hook after a Bash edit (no file named in the payload)")
        import os
        import subprocess

        # Run from a git hook (prek), GIT_INDEX_FILE and friends point at the REAL
        # repository, so `git add -A` here would stage into it. This temporary
        # repository must be the only one git can see.
        for name in [n for n in os.environ if n.startswith("GIT_")]:
            del os.environ[name]
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
        target.write_text("x is Role.OWNER\n")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)

        bash = {"tool_name": "Bash", "tool_input": {"command": "sed -i s/a/b/ f"}}
        code, _ = hook(bash)
        check("a Bash call with nothing changed exits 0", code == 0, str(code))

        target.write_text('x == "owner"\n')  # what `sed -i` or a heredoc would do
        code, err = hook(bash)
        check("a Bash edit that adds a violation exits 2", code == 2, str(code))
        check("and names the file it found", "server/app/x.py" in err, err[:80])

        fresh = root / "server" / "app" / "new_file.py"
        fresh.write_text('y == "writer"\n')  # created by a heredoc: untracked
        code, err = hook(bash)
        check(
            "an untracked file made by Bash is checked", "new_file.py" in err, err[:80]
        )
        fresh.unlink()
        target.write_text("x is Role.OWNER\n")
        code, _ = hook(bash)
        check("and fixing it makes the next Bash call quiet", code == 0, str(code))

        sys.stdin = io.StringIO("not json")
        check("garbage on stdin exits 0, not a crash", ce.run_hook() == 0)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("enum guardrail checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
