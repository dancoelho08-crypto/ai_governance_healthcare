"""Every guard on the MCP service is shown to fail (#164, R-73, D-91).

A guard nobody has seen fail is a claim, not a control (CLAUDE.md). Each case breaks one
thing in a COPY of the service, the way a careless edit or a plausible refactor would,
and demands that the suite names the guard by failing the test written for it. The copy
is never the real tree.

The first case breaks nothing: if the harness cannot pass an unbroken copy, a "failure"
below would prove nothing.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

MCP = Path(__file__).resolve().parents[1]
SUITE = "tests/test_mcp_service.py"
PROCESS = "tests/test_mcp_process.py"


@dataclass(frozen=True)
class Mutant:
    name: str
    path: str  # relative to mcp/
    old: str
    new: str
    caught_by: tuple[str, ...]  # any one of these must fail
    suite: str = SUITE
    append: str = ""
    # More edits, in other files or the same, that together make the one break.
    also: tuple[tuple[str, str, str], ...] = ()


EXTRA_TOOL = """
    @mcp.tool(name="update_project", description="write")
    async def update_project(ref: str) -> str:
        return "no"

    return mcp, upstream
"""

MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        "an extra tool is registered",
        "chai_mcp/server.py",
        "    return mcp, upstream\n",
        EXTRA_TOOL,
        (
            "test_only_the_three_allowlisted_tools_are_registered",
            "test_the_protocol_lists_exactly_the_allowlist",
        ),
    ),
    Mutant(
        "a resource is registered",
        "chai_mcp/server.py",
        "    return mcp, upstream\n",
        '    @mcp.resource("data://x")\n    def x() -> str:\n        return "x"\n\n'
        "    return mcp, upstream\n",
        ("test_no_resource_template_or_prompt_is_registered",),
    ),
    Mutant(
        "a prompt is registered",
        "chai_mcp/server.py",
        "    return mcp, upstream\n",
        '    @mcp.prompt()\n    def p() -> str:\n        return "x"\n\n'
        "    return mcp, upstream\n",
        ("test_no_resource_template_or_prompt_is_registered",),
    ),
    Mutant(
        "a write verb is sent upstream",
        "chai_mcp/upstream.py",
        "await client.get(\n                    route.value + suffix, params=params or None, headers=headers\n                )",
        'await client.request(\n                    "POST", route.value + suffix, params=params or None, headers=headers\n                )',
        (
            "test_each_tool_returns_its_documented_result_and_forwards_the_callers_token",
        ),
    ),
    Mutant(
        "a fourth upstream route exists",
        "chai_mcp/upstream.py",
        '    PROJECT = "/api/agent/projects/"\n',
        '    PROJECT = "/api/agent/projects/"\n    PROJECTS = "/api/projects"\n',
        ("test_the_upstream_routes_are_the_three_get_routes_and_no_others",),
    ),
    Mutant(
        "the token is logged",
        "chai_mcp/upstream.py",
        '        headers = {"Authorization": authorization, "Accept": "application/json"}\n',
        '        headers = {"Authorization": authorization, "Accept": "application/json"}\n'
        '        log.info("calling upstream with %s", authorization)\n',
        ("test_the_token_is_in_no_log_line_on_any_path",),
    ),
    Mutant(
        "the token is kept on the upstream object",
        "chai_mcp/upstream.py",
        '        headers = {"Authorization": authorization, "Accept": "application/json"}\n',
        "        self.last = authorization\n"
        '        headers = {"Authorization": authorization, "Accept": "application/json"}\n',
        ("test_a_token_is_not_kept_after_its_request",),
    ),
    Mutant(
        "the token is kept in a module global",
        "chai_mcp/server.py",
        '    return f"Bearer {token}"\n',
        '    LAST.append(token)\n    return f"Bearer {token}"\n',
        ("test_a_token_is_not_kept_after_its_request",),
        append="\n\nLAST: list[str] = []\n",
    ),
    Mutant(
        "the token is in an error",
        "chai_mcp/upstream.py",
        "            raise error_for(response, route) from None",
        '            raise ToolFailure(f"{error_for(response, route)} {authorization}") from None',
        ("test_a_token_the_api_rejects_is_one_message_and_is_never_echoed",),
    ),
    Mutant(
        "the upstream body is in an error",
        "chai_mcp/upstream.py",
        "    return ToolFailure(Message.UNAVAILABLE.value)\n\n\nclass Upstream",
        "    return ToolFailure(response.text)\n\n\nclass Upstream",
        ("test_a_failure_is_a_fixed_message_and_never_the_upstream_body",),
    ),
    Mutant(
        "a 422's message is passed on whole",
        "chai_mcp/upstream.py",
        '    said = _SAFE.sub("", str(msg)).strip()',
        "    said = str(msg)",
        ("test_a_422_carries_the_apis_message_cut_to_plain_text",),
    ),
    Mutant(
        "the bearer is not forwarded; an identity header is sent instead",
        "chai_mcp/upstream.py",
        '        headers = {"Authorization": authorization, "Accept": "application/json"}\n',
        '        headers = {"X-Auth-Request-Email": authorization, "Accept": "application/json"}\n',
        (
            "test_each_tool_returns_its_documented_result_and_forwards_the_callers_token",
            "test_only_the_bearer_is_forwarded_no_identity_and_no_other_credential",
        ),
    ),
    Mutant(
        "the caller's cookie and identity headers are forwarded too",
        "chai_mcp/upstream.py",
        "        if client_address:\n",
        '        headers["Cookie"] = "session=x"\n        if client_address:\n',
        ("test_only_the_bearer_is_forwarded_no_identity_and_no_other_credential",),
    ),
    Mutant(
        "the Origin check is off",
        "chai_mcp/server.py",
        "enable_dns_rebinding_protection=True",
        "enable_dns_rebinding_protection=False",
        (
            "test_a_browser_origin_that_is_not_listed_is_refused_even_with_a_token",
            "test_a_request_for_another_host_is_refused",
        ),
    ),
    Mutant(
        "every origin is allowed once any is configured",
        "chai_mcp/server.py",
        "        allowed_origins=list(settings.allowed_origins),",
        '        allowed_origins=[*settings.allowed_origins, "https://evil.example"],',
        ("test_a_browser_origin_that_is_not_listed_is_refused_even_with_a_token",),
    ),
    Mutant(
        "the bearer requirement is gone",
        "chai_mcp/asgi.py",
        '        if bearer_token(request.headers.get("authorization")) is None:',
        "        if False:",
        ("test_a_request_without_a_bearer_token_is_refused_before_anything_else",),
    ),
    Mutant(
        "a bearer with nothing after it is accepted",
        "chai_mcp/bearer.py",
        "or not credentials:",
        "or False:",
        ("test_a_request_without_a_bearer_token_is_refused_before_anything_else",),
    ),
    Mutant(
        "a different scheme is taken for a bearer",
        "chai_mcp/bearer.py",
        'if scheme.lower() != "bearer"',
        "if False",
        ("test_a_request_without_a_bearer_token_is_refused_before_anything_else",),
    ),
    Mutant(
        "a query string is accepted",
        "chai_mcp/asgi.py",
        '        if scope.get("query_string"):',
        "        if False:",
        ("test_only_post_to_the_one_path_with_no_query_is_served",),
    ),
    Mutant(
        "GET is served",
        "chai_mcp/asgi.py",
        '        if method != "POST":  # enum-ok: HTTP method',
        "        if False:",
        ("test_only_post_to_the_one_path_with_no_query_is_served",),
    ),
    Mutant(
        "any path is served",
        "chai_mcp/asgi.py",
        "        if path != MCP_PATH:",
        "        if False:",
        ("test_only_post_to_the_one_path_with_no_query_is_served",),
    ),
    Mutant(
        "CORS is on",
        "chai_mcp/asgi.py",
        "    app.add_middleware(Guard, settings=settings)  # type: ignore[arg-type]\n",
        "    app.add_middleware(Guard, settings=settings)  # type: ignore[arg-type]\n"
        "    from starlette.middleware.cors import CORSMiddleware\n\n"
        '    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"])\n',
        ("test_no_cors_headers_are_ever_sent_and_a_preflight_is_not_served",),
    ),
    Mutant(
        "the request size limit is off",
        "chai_mcp/server.py",
        "        max_request_body_size=settings.max_body_bytes,",
        "        max_request_body_size=10**9,",
        ("test_a_body_over_the_limit_is_refused",),
    ),
    Mutant(
        "there is no timeout",
        "chai_mcp/upstream.py",
        "asyncio.timeout(self._timeout),",
        "asyncio.timeout(None),",
        ("test_a_slow_governance_server_times_out",),
        also=(("chai_mcp/upstream.py", "timeout=self._timeout,", "timeout=None,"),),
    ),
    Mutant(
        "concurrency is not bounded",
        "chai_mcp/server.py",
        "        if self._active >= self._limit:",
        "        if False:",
        ("test_concurrency_is_bounded_and_the_overflow_is_refused",),
    ),
    Mutant(
        "a redirect is followed with the token",
        "chai_mcp/upstream.py",
        "follow_redirects=False,",
        "follow_redirects=True,",
        ("test_a_redirect_is_not_followed_so_the_token_goes_nowhere_else",),
    ),
    Mutant(
        "the service keeps sessions",
        "chai_mcp/server.py",
        "        stateless_http=True,",
        "        stateless_http=False,",
        ("test_the_service_keeps_no_session",),
    ),
    Mutant(
        "an answer is not checked against the model",
        "chai_mcp/models.py",
        'model_config = ConfigDict(extra="forbid")',
        'model_config = ConfigDict(extra="allow")',
        ("test_a_value_that_is_not_a_vocabulary_word_never_reaches_a_model",),
    ),
    Mutant(
        "a vocabulary word may be anything",
        "chai_mcp/models.py",
        'WORD = r"^[A-Za-z0-9][A-Za-z0-9,&/+._-]*( [A-Za-z0-9,&/+._-]+){0,3}$"',
        'WORD = r"^.*$"',
        ("test_a_value_that_is_not_a_vocabulary_word_never_reaches_a_model",),
    ),
    Mutant(
        "an unexpected failure shows its message",
        "chai_mcp/server.py",
        "            raise ToolError(Message.INTERNAL.value) from None",
        "            raise ToolError(str(exc)) from None",
        ("test_an_unexpected_failure_inside_the_service_is_one_plain_message",),
    ),
    Mutant(
        "a 401 is not one message",
        "chai_mcp/upstream.py",
        "    if code == httpx.codes.UNAUTHORIZED:\n        return ToolFailure(Message.REJECTED.value)",
        "    if code == httpx.codes.UNAUTHORIZED:\n        return ToolFailure(response.text or Message.REJECTED.value)",
        ("test_a_token_the_api_rejects_is_one_message_and_is_never_echoed",),
    ),
    Mutant(
        "a project reference is not checked",
        "chai_mcp/server.py",
        "                pattern=PROJECT,\n",
        "",
        ("test_a_call_asks_for_a_reference_it_can_name_and_nothing_else",),
        # The service checks twice (the tool's type, and again before the request is
        # built), so a break has to take out both.
        also=(
            (
                "chai_mcp/upstream.py",
                "if route is Route.PROJECT and not _PROJECT_REF.fullmatch(suffix):",
                "if False:",
            ),
        ),
    ),
    Mutant(
        "it starts without an allowed host",
        "chai_mcp/config.py",
        "        if not hosts:",
        "        if False:",
        ("test_it_refuses_to_start_with_no_allowed_host",),
        suite=PROCESS,
    ),
    Mutant(
        "the access log writes the query string",
        "chai_mcp/__main__.py",
        "access_log=False",
        "access_log=True",
        ("test_what_the_process_writes_holds_no_token",),
        suite=PROCESS,
    ),
    Mutant(
        "the process logs the token",
        "chai_mcp/asgi.py",
        '            log.info("%s %s %s", scope["method"], scope["path"], status)',
        '            log.info("%s %s %s %s", scope["method"], scope["path"], status,'
        ' dict(scope["headers"]))',
        ("test_what_the_process_writes_holds_no_token",),
        suite=PROCESS,
    ),
)


def _copy(into: Path) -> Path:
    target = into / "mcp"
    shutil.copytree(
        MCP,
        target,
        ignore=shutil.ignore_patterns(
            "__pycache__", ".pytest_cache", "*.pyc", "*.egg-info"
        ),
    )
    # tests/stack.py and the contract test read the server and the manifest by path.
    (into / "server").symlink_to(MCP.parent / "server")
    (into / "docs").mkdir()
    (into / "docs" / "app").symlink_to(MCP.parent / "docs" / "app")
    return target


def _pytest(tree: Path, names: tuple[str, ...], suites: tuple[str, ...]):
    env = {k: v for k, v in os.environ.items() if k != "TEST_APP_ROLE"}
    env.update(REQUIRE_TESTS="1", PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(tree))
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-rf",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:logging",
            *suites,
            "-k",
            " or ".join(names),
        ],
        cwd=tree,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


ALL_NAMES = tuple(dict.fromkeys(n for m in MUTANTS for n in m.caught_by))
SUITES = tuple(dict.fromkeys(m.suite for m in MUTANTS))


def test_the_harness_passes_an_unbroken_copy() -> None:
    """The control. Without it a failure below could be the harness failing."""
    with tempfile.TemporaryDirectory() as tmp:
        tree = _copy(Path(tmp))
        done = _pytest(tree, ALL_NAMES, SUITES)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-1000:]
    assert re.search(r"\b\d+ passed\b", done.stdout) and "failed" not in done.stdout


@pytest.mark.parametrize("mutant", MUTANTS, ids=[m.name for m in MUTANTS])
def test_each_guard_is_noticed_when_broken(mutant: Mutant) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tree = _copy(Path(tmp))
        target = tree / mutant.path
        text = target.read_text(encoding="utf-8")
        assert mutant.old in text, f"{mutant.name}: the text to break is not there"
        mutated = text.replace(mutant.old, mutant.new, 1) + mutant.append
        assert mutated != text
        target.write_text(mutated, encoding="utf-8")
        for path, old, new in mutant.also:
            other = tree / path
            body = other.read_text(encoding="utf-8")
            assert old in body, f"{mutant.name}: {path}: the text to break is not there"
            other.write_text(body.replace(old, new, 1), encoding="utf-8")
        done = _pytest(tree, mutant.caught_by, (mutant.suite,))
    failed = re.findall(r"^FAILED tests/test_mcp_\w+\.py::(\w+)", done.stdout, re.M)
    assert done.returncode == 1, (
        f"breaking {mutant.name!r} was not noticed:\n{done.stdout[-2500:]}"
    )
    assert set(failed) & set(mutant.caught_by), (
        f"breaking {mutant.name!r} failed {failed}, not any of {mutant.caught_by}:\n"
        f"{done.stdout[-2500:]}"
    )
