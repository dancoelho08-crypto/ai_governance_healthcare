#!/usr/bin/env python3
"""Fail when code branches on a bare string instead of an enumerated type.

Why this exists: the server-backed dashboard told every user "Saved in this
browser". `MODE` was assigned "api" in one file and compared with "shared" in
another, and nothing connected the two spellings, so the comparison was quietly
false forever. A typo in a string literal is not an error anywhere; a typo in an
enum member is an AttributeError the first time the line runs, and a rename
follows every use. That is the whole argument, and it is why this repository's
rule is "a closed set of values gets a type" -- see CLAUDE.md.

What it flags, in application code (tests are exempt, because a test may pin a
wire value on purpose):

    Python      x == "owner", x is "owner"        comparison to a literal
                x in ("a", "b"), frozenset({...})  membership in a literal set
                x.startswith("not")               prefix or suffix test
                case "owner":                     match on a literal
                Literal["a", "b"]                 a closed set spelled as a type
                Field(pattern="^(a|b)$")          a closed set spelled as a regex
    JavaScript  MODE === "api"                    comparison to a literal
                ["a", "b"].includes(x)            membership in a literal array
                case "api":                       switch on a literal
                s.startsWith("not")               prefix or suffix test
                MODE = "api"                      a state variable assigned a word

Only identifier-shaped literals count ("owner", "jwt", "http.request",
"in-progress"). Paths, punctuation, empty strings and prose are never domain
values. A file the checker cannot parse is reported, not skipped, because a
skipped file would be a way to hide a violation.

What it cannot see, by design. Catching these would flag every dict lookup and
substring test, and a guardrail that cries wolf gets switched off. A green check
is a tripwire for the common shape, not proof that no string is being branched
on:

    OWNER = "owner"; x == OWNER          a hoisted string constant is still a
                                         string; `x == Role.OWNER` is the fix
    ROLES = ("a", "b"); x in ROLES       the same, hoisted
    HANDLERS = {"csv": f}; HANDLERS[k]   a dispatch dict keyed by strings
    "admin" in user.roles                a literal on the left of `in`
    operator.eq(x, "a")                  and other indirect comparisons
    mode = "api"  (JavaScript)           only SHOUTING_CASE state variables count
    <script> inside an .html file        only .py and app/**/*.js are read
    a violation moved to another line    the baseline counts per file and literal
    a hand-edited baseline               nothing but review stops this

The first four are the ones to watch for in review: they are exactly what a
well-meaning author writes to make this check pass.

It is a ratchet, not a wall. Existing uses live in scripts/enum_baseline.json,
counted per file and per literal. A NEW use fails the check. Fixing one makes
the baseline stale, which also fails, so the baseline can only shrink. Growing
it requires --allow-growth, and is a decision for a human, not a way to make
the check pass.

A genuine exception -- an ASGI scope type, a DOM key name, a value defined by
someone else's protocol -- is marked on its line with a reason:

    if scope["type"] == "http":  # enum-ok: ASGI protocol value

A bare `enum-ok` with no reason does not suppress anything.

    pixi run check-enums                       whole repository
    python scripts/check_enums.py --files F..  just these files
    python scripts/check_enums.py --report     what is in the baseline, by file
    python scripts/check_enums.py --update-baseline    ratchet down only

Also run, with --hook, as a Claude Code PostToolUse hook (.claude/settings.json)
so a violation is reported to the author at the moment it is written.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

try:
    from enum import StrEnum
except ImportError:  # Python 3.10: the system python3 some contributors run this with

    class StrEnum(str, Enum):  # noqa: UP042
        """Minimal stand-in; the repository itself targets 3.11+."""

        def __str__(self) -> str:
            return str(self.value)


ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "enum_baseline.json"


class Lang(StrEnum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"


class Shape(StrEnum):
    COMPARE = "comparison to a string literal"
    MEMBERSHIP = "membership in a literal set of strings"
    MATCH = "match on a string literal"
    LITERAL_TYPE = "Literal[...] used as an enum"
    SWITCH = "switch on a string literal"
    ASSIGN = "state variable assigned a bare string"
    STRING_METHOD = "prefix, suffix or identity test against a string literal"
    PATTERN = "regex enumerating a closed set"
    UNPARSEABLE = "file could not be parsed, so it cannot be checked"


# Where application code lives. Every Python file and every script under app/ is
# checked, EXCEPT tests: a test that pins the wire format ("the API sends role
# 'owner'") should say so in plain text. Only these three trees are exempt, so code
# cannot become unchecked by being put in a directory that merely has "tests" in
# its path.
TEST_PREFIXES = ("tests/", "server/tests/", "mcp/tests/")
SKIP_PARTS = frozenset(
    # .claude holds agents' git worktrees: other checkouts, not this one's code.
    {"__pycache__", ".pixi", ".git", "node_modules", "site", ".cache", ".claude"}
)
JS_ROOT = "app/"
JS_SUFFIXES = (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx")

# Identifier-shaped, optionally dotted or hyphenated ("http.request",
# "in-progress"). Anything else is a path, a sentence, punctuation or a number,
# none of which is an enum member.
_WORD = r"[A-Za-z_][A-Za-z0-9_-]*"
DOMAIN = re.compile(rf"^{_WORD}(?:\.{_WORD})*$")
MIN_LEN = 2

# The exception marker. The reason after the colon is mandatory, and it only
# counts inside a real comment (not inside a string that happens to contain it).
PRAGMA = re.compile(r"enum-ok:\s*\S")

# `typeof x === "undefined"` compares against the language's own type names.
JS_TYPEOF_NAMES = frozenset(
    {"undefined", "string", "object", "function", "number", "boolean", "symbol"}
)

# JavaScript shapes. They run over source with comments blanked out, so `\s*`
# lets a comparison wrap across lines, and a quote class that includes the
# backtick catches template literals.
_Q = "([\"'`])"
_JS_WORD = r"([A-Za-z_][A-Za-z0-9_-]*)"
JS_CMP_RIGHT = re.compile(rf"(?:===|!==|==|!=)\s*{_Q}{_JS_WORD}\1")
JS_CMP_LEFT = re.compile(rf"{_Q}{_JS_WORD}\1\s*(?:===|!==|==|!=)")
JS_CASE = re.compile(rf"\bcase\s*\(?\s*{_Q}{_JS_WORD}\1\s*\)?\s*:")
JS_ASSIGN = re.compile(
    rf"(?<![\w$.])([A-Z][A-Z0-9_]+)\s*(?:\|\|=|\?\?=|=(?!=))\s*{_Q}{_JS_WORD}\2"
)
JS_ARRAY_TEST = re.compile(
    rf"\[\s*((?:{_Q}[^\"'`\]]*\2\s*,?\s*)+)\]\s*\.\s*"
    r"(?:includes|indexOf|lastIndexOf)\s*\("
)
JS_SET_TEST = re.compile(
    rf"new\s+Set\s*\(\s*\[\s*((?:{_Q}[^\"'`\]]*\2\s*,?\s*)+)\]\s*\)\s*\.\s*has\s*\("
)
JS_STR_METHOD = re.compile(rf"\.\s*(?:startsWith|endsWith)\s*\(\s*{_Q}{_JS_WORD}\1")
JS_OBJECT_IS = re.compile(rf"Object\.is\s*\([^()]*?,\s*{_Q}{_JS_WORD}\1\s*\)")
JS_STR_ELEMENT = re.compile(rf"{_Q}{_JS_WORD}\1")
JS_CONST_BEFORE = re.compile(r"\bconst\s+$")

# `Field(pattern="^(owner|writer)$")` spells a closed set as a regex.
PY_PATTERN_KEYWORDS = frozenset({"pattern", "regex"})
PY_ALTERNATION = re.compile(r"^\^\(?(?:\?:)?([\w-]+(?:\|[\w-]+)+)\)?\$$")
PY_STR_METHODS = frozenset({"startswith", "endswith", "removeprefix", "removesuffix"})
PY_COLLECTION_CALLS = frozenset({"frozenset", "set", "tuple", "list"})
PY_TYPING_MODULES = frozenset({"typing", "typing_extensions"})
LITERAL_NAME = "Literal"
UNPARSEABLE = "<unparseable>"


@dataclass(frozen=True)
class Finding:
    lang: Lang
    path: str
    line: int
    literal: str
    shape: Shape

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.lang.value, self.path, self.literal)


# --- Python -----------------------------------------------------------------


def _is_dunder(value: str) -> bool:
    """`__main__` and friends are the language's own names, not domain values."""
    return value.startswith("__") and value.endswith("__")


def _is_domain(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) >= MIN_LEN
        and bool(DOMAIN.match(value))
        and not _is_dunder(value)
    )


def _comment_pragma_lines(source: str) -> set[int]:
    """Lines whose real COMMENT token carries a reasoned `enum-ok`.

    Reading tokens, not text, is what stops a string such as
    `log("x == 'a'  # enum-ok: because")` from excusing the line it sits on.
    """
    lines: set[int] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT and PRAGMA.search(token.string):
                lines.add(token.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass  # the parse failure is reported by scan_python
    return lines


def _literal_aliases(tree: ast.AST) -> frozenset[str]:
    """Every name `Literal` is imported as: `from typing import Literal as L`."""
    names = {LITERAL_NAME}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in PY_TYPING_MODULES:
            for alias in node.names:
                if alias.name == LITERAL_NAME:
                    names.add(alias.asname or alias.name)
    return frozenset(names)


class _PyVisitor(ast.NodeVisitor):
    def __init__(self, path: str, excused: set[int], literal_names: frozenset[str]):
        self.path = path
        self.excused = excused
        self.literal_names = literal_names
        self.found: list[Finding] = []

    def _excused(self, node: ast.AST) -> bool:
        first = getattr(node, "lineno", 0)
        last = getattr(node, "end_lineno", first) or first
        return any(line in self.excused for line in range(first, last + 1))

    def _flag(self, node: ast.AST, literal: ast.expr, shape: Shape) -> None:
        if (
            isinstance(literal, ast.Constant)
            and _is_domain(literal.value)
            and not self._excused(node)
        ):
            self.found.append(
                Finding(Lang.PYTHON, self.path, literal.lineno, literal.value, shape)
            )

    def _flag_members(self, node: ast.AST, collection: ast.expr, shape: Shape) -> None:
        """The strings in a literal collection, however it is spelled."""
        if isinstance(collection, ast.Call) and (
            isinstance(collection.func, ast.Name)
            and collection.func.id in PY_COLLECTION_CALLS
            and len(collection.args) == 1
        ):
            collection = collection.args[0]
        if isinstance(collection, (ast.Tuple, ast.List, ast.Set)):
            for element in collection.elts:
                self._flag(node, element, shape)
        elif isinstance(collection, ast.Dict):
            for key in collection.keys:
                if key is not None:
                    self._flag(node, key, shape)

    def visit_Compare(self, node: ast.Compare) -> None:
        operands = [node.left, *node.comparators]
        seen: set[int] = set()  # the middle of `a == "x" != b` sits in two pairs
        for op, left, right in zip(node.ops, operands, operands[1:], strict=False):
            if isinstance(op, (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)):
                for side in (left, right):
                    if id(side) not in seen:
                        seen.add(id(side))
                        self._flag(node, side, Shape.COMPARE)
            elif isinstance(op, (ast.In, ast.NotIn)):
                self._flag_members(node, right, Shape.MEMBERSHIP)
        self.generic_visit(node)

    def visit_MatchValue(self, node: ast.MatchValue) -> None:
        self._flag(node, node.value, Shape.MATCH)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in PY_STR_METHODS:
            for argument in node.args[:1]:
                if isinstance(argument, ast.Tuple):
                    for element in argument.elts:
                        self._flag(node, element, Shape.STRING_METHOD)
                else:
                    self._flag(node, argument, Shape.STRING_METHOD)
        for keyword in node.keywords:
            if keyword.arg in PY_PATTERN_KEYWORDS and isinstance(
                keyword.value, ast.Constant
            ):
                match = PY_ALTERNATION.match(str(keyword.value.value))
                if match and not self._excused(node):
                    for word in match.group(1).split("|"):
                        if _is_domain(word):
                            self.found.append(
                                Finding(
                                    Lang.PYTHON,
                                    self.path,
                                    keyword.value.lineno,
                                    word,
                                    Shape.PATTERN,
                                )
                            )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        target = node.value
        name = (
            target.id if isinstance(target, ast.Name) else getattr(target, "attr", "")
        )
        if name in self.literal_names:
            members = (
                node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
            )
            strings = [
                m
                for m in members
                if isinstance(m, ast.Constant) and _is_domain(m.value)
            ]
            if len(strings) >= 2:
                for member in strings:
                    self._flag(node, member, Shape.LITERAL_TYPE)
        self.generic_visit(node)


def scan_python(source: str, path: str) -> list[Finding]:
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        # Not silently skipped: a file the checker cannot read is a file it
        # cannot vouch for, and a skipped one would be a way to hide a violation.
        line = error.lineno or 1
        return [Finding(Lang.PYTHON, path, line, UNPARSEABLE, Shape.UNPARSEABLE)]
    visitor = _PyVisitor(path, _comment_pragma_lines(source), _literal_aliases(tree))
    visitor.visit(tree)
    return visitor.found


# --- JavaScript -------------------------------------------------------------


def split_javascript(source: str) -> tuple[str, set[int]]:
    """Blank out comments, keep strings, and collect the `enum-ok` lines.

    Returns (code, pragma_lines). `code` has the same length and line numbers as
    the source, with every comment replaced by spaces, so a regex can run across
    line breaks without being fooled by `/* ... */` before the code on a line,
    and a pragma only counts when it is in a real comment. Regex literals are not
    parsed, so a quote inside one can confuse a single line; that is a known
    limit, and it ends at the next newline.
    """
    code: list[str] = []
    pragmas: set[int] = set()
    i, n, line = 0, len(source), 1
    quote = ""
    while i < n:
        ch = source[i]
        following = source[i + 1] if i + 1 < n else ""
        if quote:
            code.append(ch)
            if ch == "\\" and following:
                code.append(following)
                line += following == "\n"
                i += 2
                continue
            if ch == quote:
                quote = ""
            elif ch == "\n":
                line += 1
                if quote != "`":  # an unterminated ' or " ends with the line
                    quote = ""
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
        elif ch == "/" and following in "/*":
            if following == "/":
                end = source.find("\n", i)
                end = n if end < 0 else end
            else:
                end = source.find("*/", i + 2)
                end = n if end < 0 else end + 2
            text = source[i:end]
            for offset, segment in enumerate(text.split("\n")):
                if PRAGMA.search(segment):
                    pragmas.add(line + offset)
            code.append("".join("\n" if c == "\n" else " " for c in text))
            line += text.count("\n")
            i = end
            continue
        elif ch == "\n":
            line += 1
        code.append(ch)
        i += 1
    return "".join(code), pragmas


def scan_javascript(source: str, path: str) -> list[Finding]:
    code, pragmas = split_javascript(source)
    found: list[Finding] = []

    def line_of(offset: int) -> int:
        return code.count("\n", 0, offset) + 1

    def record(match: re.Match[str], group: int, shape: Shape) -> None:
        literal = match.group(group)
        if literal in JS_TYPEOF_NAMES or len(literal) < MIN_LEN:
            return
        first, last = line_of(match.start()), line_of(match.end())
        if any(n in pragmas for n in range(first, last + 1)):
            return
        found.append(
            Finding(Lang.JAVASCRIPT, path, line_of(match.start(group)), literal, shape)
        )

    for pattern, group, shape in (
        (JS_CMP_RIGHT, 2, Shape.COMPARE),
        (JS_CMP_LEFT, 2, Shape.COMPARE),
        (JS_CASE, 2, Shape.SWITCH),
        (JS_STR_METHOD, 2, Shape.STRING_METHOD),
        (JS_OBJECT_IS, 2, Shape.STRING_METHOD),
    ):
        for match in pattern.finditer(code):
            record(match, group, shape)

    for match in JS_ASSIGN.finditer(code):
        # `const NAME = "x"` is a single named constant, which is the fix, not the
        # problem. A reassignable `MODE = "api"` is the problem.
        if not JS_CONST_BEFORE.search(code[: match.start(1)][-12:]):
            record(match, 3, Shape.ASSIGN)

    for pattern in (JS_ARRAY_TEST, JS_SET_TEST):
        for match in pattern.finditer(code):
            first, last = line_of(match.start()), line_of(match.end())
            if any(n in pragmas for n in range(first, last + 1)):
                continue
            for element in JS_STR_ELEMENT.finditer(match.group(1)):
                literal = element.group(2)
                if literal not in JS_TYPEOF_NAMES and len(literal) >= MIN_LEN:
                    found.append(
                        Finding(
                            Lang.JAVASCRIPT,
                            path,
                            line_of(match.start(1)),
                            literal,
                            Shape.MEMBERSHIP,
                        )
                    )
    return sorted(found, key=lambda f: (f.line, f.literal))


# --- Discovery and baseline -------------------------------------------------


def relative(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return None


def language_of(rel: str) -> Lang | None:
    if rel.startswith(TEST_PREFIXES) or set(Path(rel).parts) & SKIP_PARTS:
        return None
    if rel.endswith(".py"):
        return Lang.PYTHON
    if rel.startswith(JS_ROOT) and rel.endswith(JS_SUFFIXES):
        return Lang.JAVASCRIPT
    return None


def scannable_files() -> list[str]:
    out: list[str] = []
    for directory, subdirs, names in os.walk(ROOT):
        subdirs[:] = sorted(d for d in subdirs if d not in SKIP_PARTS)
        for name in sorted(names):
            rel = relative(Path(directory) / name)
            if rel and language_of(rel):
                out.append(rel)
    return out


def scan_file(rel: str) -> list[Finding]:
    lang = language_of(rel)
    if lang is None:
        return []
    source = (ROOT / rel).read_text(encoding="utf-8")
    scanner = scan_python if lang is Lang.PYTHON else scan_javascript
    return scanner(source, rel)


def load_baseline() -> Counter[tuple[str, str, str]]:
    counts: Counter[tuple[str, str, str]] = Counter()
    if not BASELINE.exists():
        return counts
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    for lang, files in data.items():
        for path, literals in files.items():
            for literal, n in literals.items():
                counts[(lang, path, literal)] = n
    return counts


def write_baseline(counts: Counter[tuple[str, str, str]]) -> None:
    tree: dict[str, dict[str, dict[str, int]]] = {}
    for (lang, path, literal), n in sorted(counts.items()):
        if n > 0:
            tree.setdefault(lang, {}).setdefault(path, {})[literal] = n
    BASELINE.write_text(json.dumps(tree, indent=2) + "\n", encoding="utf-8")


GUIDANCE = {
    Lang.PYTHON: (
        "Define a StrEnum and compare to its members. StrEnum members equal their\n"
        "    string value, so JSON, pydantic and asyncpg are unchanged:\n"
        "        class Role(StrEnum):\n"
        '            OWNER = "owner"\n'
        "        if role is Role.OWNER: ...\n"
        "    Parse once at the boundary (Role(raw) raises on an unknown value) and\n"
        "    pass members everywhere inside."
    ),
    Lang.JAVASCRIPT: (
        "Define a frozen constant object and compare to its members:\n"
        '        const Mode = Object.freeze({ LOCAL: "local", API: "api" });\n'
        "        if (MODE === Mode.API) ...\n"
        "    One definition means a typo is `Mode.APi` -> undefined -> a failing\n"
        "    test, not a comparison that is quietly false forever."
    ),
}


def evaluate(
    findings: list[Finding], baseline: Counter[tuple[str, str, str]], *, partial: bool
) -> tuple[list[tuple[tuple[str, str, str], int, int, list[Finding]]], list]:
    """Return (growth, stale). `partial` skips staleness: only some files were read."""
    actual: Counter[tuple[str, str, str]] = Counter(f.key for f in findings)
    by_key: dict[tuple[str, str, str], list[Finding]] = {}
    for f in findings:
        by_key.setdefault(f.key, []).append(f)
    growth = [
        (key, n, baseline.get(key, 0), by_key[key])
        for key, n in sorted(actual.items())
        if n > baseline.get(key, 0)
    ]
    stale = []
    if not partial:
        stale = [
            (key, baseline[key], actual.get(key, 0))
            for key in sorted(baseline)
            if actual.get(key, 0) < baseline[key]
        ]
    return growth, stale


def render_growth(growth: list) -> str:
    out = ["", "  A closed set of values is being compared as a bare string:", ""]
    langs: set[Lang] = set()
    for (lang, path, literal), n, allowed, items in growth:
        langs.add(Lang(lang))
        out.append(f'  {path}  "{literal}"  x{n} (baseline allows {allowed})')
        for f in items:
            out.append(f"      line {f.line}: {f.shape}")
    out.append("")
    for lang in sorted(langs):
        out.append(f"  {lang.value.capitalize()}: {GUIDANCE[lang]}")
        out.append("")
    out.append(
        "  A value defined by someone else's protocol is the one exception: mark\n"
        "  the line `enum-ok: <reason>`. Do not edit the baseline to pass this\n"
        "  check; it is a ratchet and only moves toward fewer strings."
    )
    return "\n".join(out)


def run_check(files: list[str] | None) -> int:
    partial = files is not None
    # A path that no longer exists (deleted since the edit) has nothing to check.
    targets = [
        r
        for r in (files or scannable_files())
        if language_of(r) and (ROOT / r).is_file()
    ]
    findings = [f for rel in targets for f in scan_file(rel)]
    growth, stale = evaluate(findings, load_baseline(), partial=partial)
    if growth:
        print(render_growth(growth), file=sys.stderr)
        return 1
    if stale:
        print(
            "\n  The baseline is stale: these strings were removed, which is the\n"
            "  point. Ratchet the baseline down so they cannot creep back:\n"
            "      python scripts/check_enums.py --update-baseline\n",
            file=sys.stderr,
        )
        for (_lang, path, literal), was, now in stale:
            print(f'      {path}  "{literal}"  {was} -> {now}', file=sys.stderr)
        return 1
    if not partial:
        print(f"check-enums: ok ({len(findings)} baselined string comparisons)")
    return 0


def run_update(*, allow_growth: bool) -> int:
    findings = [f for rel in scannable_files() for f in scan_file(rel)]
    actual: Counter[tuple[str, str, str]] = Counter(f.key for f in findings)
    old = load_baseline()
    grown = {k: (old.get(k, 0), n) for k, n in actual.items() if n > old.get(k, 0)}
    if grown and not allow_growth:
        print(
            "\n  Refusing to grow the baseline. These are NEW string comparisons;\n"
            "  fix them with an enum instead (see the failure from `check-enums`).\n"
            "  --allow-growth exists for a human who has decided otherwise.\n",
            file=sys.stderr,
        )
        for (_lang, path, literal), (was, now) in sorted(grown.items()):
            print(f'      {path}  "{literal}"  {was} -> {now}', file=sys.stderr)
        return 1
    write_baseline(actual)
    print(f"baseline written: {sum(actual.values())} string comparisons remain")
    return 0


def run_report() -> int:
    baseline = load_baseline()
    per_file: Counter[str] = Counter()
    for (_, path, _), n in baseline.items():
        per_file[path] += n
    width = max((len(p) for p in per_file), default=0)
    for path, n in per_file.most_common():
        print(f"  {n:4d}  {path:<{width}}")
    print(f"  {sum(per_file.values()):4d}  total in {len(per_file)} files")
    return 0


def changed_files() -> list[str]:
    """Files git considers modified, added or untracked, relative to the repo.

    A Bash command (`sed -i`, a heredoc, a script that writes a file) changes
    files without any tool payload naming them. The Write and Edit tools say which
    file they touched; Bash does not, so after a Bash call the question is "what
    changed", and git is the one place that knows.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "-z", "--untracked-files=all"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    entries = result.stdout.split("\0")
    out: list[str] = []
    skip_next = False
    for entry in entries:
        if skip_next:  # the original name of a rename or copy
            skip_next = False
            continue
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        skip_next = status[0] in "RC" or status[1] in "RC"
        if "D" not in status and (ROOT / path).is_file():
            out.append(path)
    return out


def run_hook() -> int:
    """PostToolUse hook: read the tool payload on stdin, check what it wrote.

    Write, Edit and MultiEdit name their file. Bash does not, so a Bash call is
    checked against everything git says changed. Exit 2 puts stderr in front of
    the model, which is the point: the author learns about the violation in the
    same turn that wrote it.
    """
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    tool_input = payload.get("tool_input") or {}
    response = payload.get("tool_response") or {}
    raw = tool_input.get("file_path") or (
        response.get("filePath") if isinstance(response, dict) else None
    )
    if raw:
        rel = relative(Path(raw))
        targets = [rel] if rel and (ROOT / rel).exists() else []
    else:
        targets = changed_files()
    targets = [t for t in targets if language_of(t)]
    if not targets:
        return 0
    return 2 if run_check(targets) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--files", nargs="+", metavar="FILE")
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--allow-growth", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--hook", action="store_true")
    args = parser.parse_args(argv)

    if args.hook:
        return run_hook()
    if args.report:
        return run_report()
    if args.update_baseline:
        return run_update(allow_growth=args.allow_growth)
    files = None
    if args.files:
        files = [r for r in (relative(Path(f)) for f in args.files) if r]
    return run_check(files)


if __name__ == "__main__":
    sys.exit(main())
