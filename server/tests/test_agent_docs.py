"""docs/agent-api.md says what the API does, and every example is true (#164).

A contract page that has drifted from the code is worse than none: an agent is
written against it. So the page is parsed, and held to the running app:

* every documented method and path exists in the app's OpenAPI schema, and every
  agent route in the schema is documented;
* every documented query parameter, request field and response field is in the
  models, and every model field is documented (so a field added without a decision
  about the page fails here, which is also what stops one reaching an agent unseen);
* every documented status code is one the route declares, and each is produced;
* each example response validates against its model;
* each documented curl command, run against the real app, with the credentials the
  page says it uses and no others, answers what the page says;
* the documented settings and limits are the code's, and the page names no client
  or model.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import pytest
from app.agent import (
    DEFAULT_LIMIT,
    MAX_ITEMS_PER_PROJECT,
    MAX_LIMIT,
    MAX_LISTED_TOKENS,
    MAX_OFFSET,
    MAX_PEOPLE_PER_ROLE,
    AgentMeOut,
    AgentPortfolioOut,
    AgentProject,
)
from app.agent_tokens import LABEL_MAX_LENGTH, TOKEN_LIFETIME
from app.config import Settings
from httpx import ASGITransport, AsyncClient

from .conftest import make_settings, requires_db
from .test_agent_api import (
    ALICE,
    SECRET,
    R,
    access,
    as_agent,
    as_user,
    mint,
    put_project,
    running,
    set_clock,
)

pytestmark = [requires_db, pytest.mark.db]

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "agent-api.md"
TEXT = DOC.read_text(encoding="utf-8")

HEADING = re.compile(r"^### `(GET|POST|DELETE) (/api/\S+)`\s*$", re.M)
OPERATIONS = [
    ("GET", "/api/agent/me"),
    ("GET", "/api/agent/portfolio"),
    ("GET", "/api/agent/projects/{ref}"),
    ("POST", "/api/agent-tokens"),
    ("GET", "/api/agent-tokens"),
    ("DELETE", "/api/agent-tokens/{token_id}"),
]


def sections() -> dict[tuple[str, str], str]:
    found: dict[tuple[str, str], str] = {}
    marks = list(HEADING.finditer(TEXT))
    for mark in marks:
        end = len(TEXT)
        for nxt in re.finditer(r"^#{1,3} ", TEXT[mark.end() :], re.M):
            end = mark.end() + nxt.start()
            break
        found[(mark.group(1), mark.group(2))] = TEXT[mark.end() : end]
    return found


def table_after(body: str, label: str) -> list[list[str]]:
    """The first column of every row of the table that follows ``**label**``."""
    start = body.find(f"**{label}**")
    if start < 0:
        return []
    rows: list[list[str]] = []
    in_table = False
    for line in body[start:].splitlines()[1:]:
        if line.startswith("|"):
            in_table = True
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            rows.append(cells)
        elif in_table or line.startswith("**"):
            break
    return rows[1:]  # without the header row


def first_column(rows: list[list[str]]) -> list[str]:
    return [r[0].strip("`") for r in rows]


def schema_paths(openapi: dict, schema: dict, prefix: str = "") -> set[str]:
    """Every field path of a response schema: ``projects[].items[].id``."""
    schemas = openapi["components"]["schemas"]

    def resolve(node: dict) -> dict | None:
        if "$ref" in node:
            return schemas[node["$ref"].rsplit("/", 1)[1]]
        for option in node.get("anyOf", []):
            if "$ref" in option or option.get("type") == "array":
                return resolve(option)
        return node if node.get("type") in {"object", "array"} else None

    paths: set[str] = set()
    node = resolve(schema)
    if node is None:
        return paths
    if node.get("type") == "array":
        items = node["items"]
        return schema_paths(openapi, items, prefix)
    for name, prop in node.get("properties", {}).items():
        path = f"{prefix}{name}"
        paths.add(path)
        inner = resolve(prop)
        if inner is None:
            continue
        if inner.get("type") == "array":
            item = inner["items"]
            if resolve(item) is not None and "properties" in (resolve(item) or {}):
                paths |= schema_paths(openapi, item, f"{path}[].")
        elif "properties" in inner:
            paths |= schema_paths(openapi, prop, f"{path}.")
    return paths


@pytest.fixture
def openapi(settings) -> dict:
    from app.main import create_app

    return create_app(settings).openapi()


@pytest.fixture
def settings():
    return make_settings(
        agent_id_secret=SECRET,
        rate_limit_max_requests=100_000,
        agent_rate_limit_max_requests=100_000,
        agent_failure_rate_limit_max_requests=100_000,
        agent_global_failure_rate_limit_max_requests=100_000,
        agent_user_rate_limit_max_requests=100_000,
    )


def test_every_operation_is_documented_and_every_documented_one_exists(openapi) -> None:
    documented = set(sections())
    assert documented == set(OPERATIONS)
    in_schema = {
        (method.upper(), path)
        for path, methods in openapi["paths"].items()
        if path.startswith(("/api/agent/", "/api/agent-tokens"))
        for method in methods
    }
    assert in_schema == documented


def test_the_documented_query_parameters_are_the_routes(openapi) -> None:
    for (method, path), body in sections().items():
        declared = {
            p["name"]
            for p in openapi["paths"][path][method.lower()].get("parameters", [])
            if p["in"] == "query"
        }
        assert set(first_column(table_after(body, "Query parameters"))) == declared, (
            path
        )


def test_the_documented_request_fields_are_the_models(openapi) -> None:
    operation = openapi["paths"]["/api/agent-tokens"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    body = sections()[("POST", "/api/agent-tokens")]
    assert set(first_column(table_after(body, "Request body"))) == schema_paths(
        openapi, schema
    )


def test_the_documented_response_fields_are_the_models_exactly(openapi) -> None:
    """Both ways: a documented field the model lacks is a lie, and a model field the
    page lacks is a field an agent was never told about."""
    for (method, path), body in sections().items():
        operation = openapi["paths"][path][method.lower()]
        ok = next(c for c in operation["responses"] if c.startswith("2"))
        content = operation["responses"][ok].get("content")
        documented = set(first_column(table_after(body, "Response fields")))
        if content is None:  # 204
            assert not documented, path
            continue
        schema = content["application/json"]["schema"]
        assert documented == schema_paths(openapi, schema), path


def test_the_documented_status_codes_are_the_routes(openapi) -> None:
    for (method, path), body in sections().items():
        documented = set(first_column(table_after(body, "Status codes")))
        declared = set(openapi["paths"][path][method.lower()]["responses"])
        assert documented == declared, (method, path)


# --- every documented status is produced ----------------------------------------------


async def test_every_documented_status_is_one_the_route_returns(client) -> None:
    """Each (route, code) in the tables, produced against the real app."""
    set_clock(
        client,
        __import__("datetime").datetime(
            2026, 10, 10, 12, tzinfo=__import__("datetime").UTC
        ),
    )
    minted = await mint(client)
    await put_project("p", {"access": access(owners=[ALICE])})
    produced: dict[tuple[str, str], set[int]] = {op: set() for op in OPERATIONS}

    def got(method: str, path: str, response) -> None:
        produced[(method, path)].add(response.status_code)

    me, pf, pj = (
        "/api/agent/me",
        "/api/agent/portfolio",
        "/api/agent/projects/{ref}",
    )
    async with as_agent(client, minted["token"]) as agent:
        got("GET", me, await agent.get("/api/agent/me"))
        got("GET", pf, await agent.get("/api/agent/portfolio"))
        got("GET", pf, await agent.get("/api/agent/portfolio?limit=0"))
        got("GET", pj, await agent.get(f"/api/agent/projects/{R('p')}"))
        got("GET", pj, await agent.get(f"/api/agent/projects/{R('nope')}"))
        got("GET", pj, await agent.get("/api/agent/projects/a%20b"))
    async with as_agent(client, None) as nobody:
        for method, path, url in (
            ("GET", me, "/api/agent/me"),
            ("GET", pf, "/api/agent/portfolio"),
            ("GET", pj, f"/api/agent/projects/{R('p')}"),
        ):
            got(method, path, await nobody.get(url))
    async with as_user(client, ALICE) as session:
        got(
            "POST",
            "/api/agent-tokens",
            await session.post("/api/agent-tokens", json={"label": "x"}),
        )
        got(
            "POST",
            "/api/agent-tokens",
            await session.post("/api/agent-tokens", json={"label": "-"}),
        )
        got("GET", "/api/agent-tokens", await session.get("/api/agent-tokens"))
        got(
            "DELETE",
            "/api/agent-tokens/{token_id}",
            await session.delete(f"/api/agent-tokens/{minted['id']}"),
        )
        got(
            "DELETE",
            "/api/agent-tokens/{token_id}",
            await session.delete(f"/api/agent-tokens/{'0' * 16}"),
        )
        got(
            "DELETE",
            "/api/agent-tokens/{token_id}",
            await session.delete("/api/agent-tokens/zz"),
        )
        for _ in range(5):
            await session.post("/api/agent-tokens", json={})
        got(
            "POST",
            "/api/agent-tokens",
            await session.post("/api/agent-tokens", json={}),
        )
    async with as_user(client, ALICE, **{"Sec-Fetch-Site": "cross-site"}) as site:
        got("POST", "/api/agent-tokens", await site.post("/api/agent-tokens", json={}))
        got(
            "DELETE",
            "/api/agent-tokens/{token_id}",
            await site.delete(f"/api/agent-tokens/{'0' * 16}"),
        )
    async with AsyncClient(
        transport=ASGITransport(app=client.app), base_url="http://api.test"
    ) as anonymous:
        got(
            "POST",
            "/api/agent-tokens",
            await anonymous.post("/api/agent-tokens", json={}),
        )
        got("GET", "/api/agent-tokens", await anonymous.get("/api/agent-tokens"))
        got(
            "DELETE",
            "/api/agent-tokens/{token_id}",
            await anonymous.delete(f"/api/agent-tokens/{'0' * 16}"),
        )

    # 403 from the proxy locks, 404 for an app with the API off, 429 from the limiter.
    async with running(trusted_proxy_cidrs=["10.0.0.0/8"]) as locked:
        for method, path, url in (
            ("GET", me, "/api/agent/me"),
            ("GET", pf, "/api/agent/portfolio"),
            ("GET", pj, f"/api/agent/projects/{R('p')}"),
        ):
            async with as_agent(locked, "agt_" + "0" * 16 + "." + "A" * 43) as a:
                got(method, path, await a.get(url))
        async with as_user(locked, ALICE) as s:
            got("GET", "/api/agent-tokens", await s.get("/api/agent-tokens"))
    async with running(agent_id_secret="") as off:
        async with as_agent(off, "agt_" + "0" * 16 + "." + "A" * 43) as a:
            for method, path, url in (
                ("GET", me, "/api/agent/me"),
                ("GET", pf, "/api/agent/portfolio"),
                ("GET", pj, f"/api/agent/projects/{R('p')}"),
            ):
                got(method, path, await a.get(url))
        async with as_user(off, ALICE) as s:
            got("POST", "/api/agent-tokens", await s.post("/api/agent-tokens", json={}))
            got("GET", "/api/agent-tokens", await s.get("/api/agent-tokens"))
            got(
                "DELETE",
                "/api/agent-tokens/{token_id}",
                await s.delete(f"/api/agent-tokens/{'0' * 16}"),
            )
    async with running(
        rate_limit_max_requests=1,
        agent_rate_limit_max_requests=1,
        agent_failure_rate_limit_max_requests=1,
    ) as tight:
        for method, path, url in (
            ("GET", me, "/api/agent/me"),
            ("GET", pf, "/api/agent/portfolio"),
            ("GET", pj, f"/api/agent/projects/{R('p')}"),
        ):
            async with as_agent(tight, "agt_" + "1" * 16 + "." + "A" * 43) as a:
                await a.get(url)
                got(method, path, await a.get(url))
        async with as_user(tight, ALICE) as s:
            await s.get("/api/agent-tokens")
            got("GET", "/api/agent-tokens", await s.get("/api/agent-tokens"))
            await s.post("/api/agent-tokens", json={})
            got("POST", "/api/agent-tokens", await s.post("/api/agent-tokens", json={}))
            got(
                "DELETE",
                "/api/agent-tokens/{token_id}",
                await s.delete(f"/api/agent-tokens/{'0' * 16}"),
            )

    documented = {
        op: {int(c) for c in first_column(table_after(body, "Status codes"))}
        for op, body in sections().items()
    }
    for op in OPERATIONS:
        assert produced[op] == documented[op], (op, produced[op], documented[op])


# --- the examples -------------------------------------------------------------------------


def test_the_example_responses_fit_their_models() -> None:
    blocks = re.findall(r"Example response:\n\n```json\n(.*?)```", TEXT, re.S)
    assert len(blocks) == 2
    AgentMeOut.model_validate(json.loads(blocks[0]))
    portfolio = AgentPortfolioOut.model_validate(json.loads(blocks[1]))
    assert portfolio.projects and AgentProject.model_validate(
        portfolio.projects[0].model_dump()
    )
    # The example shows each key the model has, so none is left undocumented by it.
    example = json.loads(blocks[1])["projects"][0]
    assert set(example) == set(AgentProject.model_fields)


def curl_commands() -> list[str]:
    commands = []
    for block in re.findall(r"```bash\n(.*?)```", TEXT, re.S):
        for line in block.splitlines():
            if line.startswith("curl"):
                commands.append(line)
    return commands


def parse_curl(command: str) -> tuple[str, str, dict[str, str], str | None]:
    parts = shlex.split(command)
    method, headers, data, url = "GET", {}, None, ""
    it = iter(parts[1:])
    for arg in it:
        if arg in ("-X", "--request"):
            method = next(it)
        elif arg in ("-H", "--header"):
            name, _, value = next(it).partition(":")
            headers[name.strip()] = value.strip()
        elif arg in ("-d", "--data"):
            data = next(it)
            method = "POST" if method == "GET" else method
        elif arg.startswith("-"):
            continue
        else:
            url = arg
    return method, url, headers, data


async def test_every_documented_curl_command_works_as_documented(client) -> None:
    """The commands on the page, run against the real app with only what they carry:
    the session for the token routes, the bearer and NO identity header for the agent
    routes."""
    set_clock(
        client,
        __import__("datetime").datetime(
            2026, 10, 10, 12, tzinfo=__import__("datetime").UTC
        ),
    )
    await put_project(
        "p1",
        {
            "meta": {"solution": "x"},
            "access": access(owners=[ALICE]),
            "items": {"s1-1": {"status": "notmet", "due": "2026-09-30"}},
            "gates": {"A": {"decision": "Proceed", "date": "2026-08-01"}},
        },
    )
    commands = curl_commands()
    assert len(commands) >= 10
    async with as_user(client, ALICE) as session:
        spare = (await session.post("/api/agent-tokens", json={})).json()
    state: dict[str, str] = {}
    ran: list[str] = []
    async with as_agent(client, None) as bare:
        for command in commands:
            method, url, headers, data = parse_curl(command)
            assert url.startswith("$BASE/"), command
            path = url[len("$BASE") :].replace("$TOKEN_ID", spare["id"])
            for var, value in sorted(state.items(), key=lambda kv: -len(kv[0])):
                path = path.replace(f"${var}", value)
                headers = {k: v.replace(f"${var}", value) for k, v in headers.items()}
            path = path.replace("$PROJECT_REF", R("p1"))
            if "$" in path or any("$" in v for v in headers.values()):
                owner = (
                    await bare.get(
                        "/api/agent/me",
                        headers={"Authorization": f"Bearer {state['TOKEN']}"},
                    )
                ).json()["user"]
                state["OWNER_ID"] = owner
                path = path.replace("$OWNER_ID", owner)
            assert "$" not in path, command
            if path.startswith("/api/agent-tokens"):
                async with as_user(client, ALICE) as session:
                    response = await session.request(
                        method, path, headers=headers, content=data
                    )
            else:
                assert set(headers) == {"Authorization"}, command  # no identity header
                response = await bare.request(method, path, headers=headers)
            expected = {"POST": 201, "DELETE": 204}.get(method, 200)
            assert response.status_code == expected, (
                command,
                response.status_code,
                response.text,
            )
            if method == "POST":
                state["TOKEN"] = response.json()["token"]
            elif path.startswith("/api/agent/me"):
                AgentMeOut.model_validate(response.json())
            elif path.startswith("/api/agent/portfolio"):
                AgentPortfolioOut.model_validate(response.json())
            elif path.startswith("/api/agent/projects/"):
                AgentProject.model_validate(response.json())
            if path.startswith("/api/agent/"):
                assert response.headers["cache-control"] == "no-store", command
            ran.append(f"{method} {path.split('?')[0]}")
    assert (
        "POST /api/agent-tokens" in ran
        and "DELETE /api/agent-tokens/" + spare["id"] in ran
    )
    assert {
        "GET /api/agent/me",
        "GET /api/agent/portfolio",
        f"GET /api/agent/projects/{R('p1')}",
    } <= set(ran)
    # The filters in the examples reached the data: the overdue one matched.
    assert ran.count("GET /api/agent/portfolio") == 5


async def test_agent_answers_are_never_cacheable(client) -> None:
    minted = await mint(client)
    async with as_agent(client, minted["token"]) as agent:
        good = await agent.get("/api/agent/me")
    async with as_agent(client, "agt_" + "0" * 16 + "." + "A" * 43) as bad:
        refused = await bad.get("/api/agent/me")
    assert (
        good.headers["cache-control"] == refused.headers["cache-control"] == "no-store"
    )
    async with as_user(client, ALICE) as session:
        again = await session.post("/api/agent-tokens", json={})
    assert again.headers["cache-control"] == "no-store"


# --- the numbers and names on the page are the code's ------------------------------------


def test_the_limits_on_the_page_are_the_codes() -> None:
    text = " ".join(TEXT.split())
    assert f"Default {DEFAULT_LIMIT}" in text and f"1 to {MAX_LIMIT}" in text
    assert f"0 to {MAX_OFFSET}" in text
    assert f"cut at {MAX_PEOPLE_PER_ROLE} ids" in text
    assert f"more than {MAX_ITEMS_PER_PROJECT} items" in text
    assert f"(at most {MAX_LISTED_TOKENS})" in text
    assert f"up to {LABEL_MAX_LENGTH} letters" in text
    assert TOKEN_LIFETIME.total_seconds() == 8 * 3600 and "Exactly 8 hours" in text
    defaults = Settings()
    assert (
        f"| `AGENT_RATE_LIMIT_MAX_REQUESTS` | `{defaults.agent_rate_limit_max_requests}` |"
        in text
    )
    assert (
        f"| `AGENT_MAX_ACTIVE_TOKENS` | `{defaults.agent_max_active_tokens}` |" in text
    )
    assert (
        f"A working token** may make {defaults.agent_rate_limit_max_requests} calls per {defaults.rate_limit_window_seconds} seconds"
        in text
    )
    assert f"({defaults.rate_limit_max_requests})" in text
    failures = defaults.agent_failure_rate_limit_max_requests
    assert f"up to {failures} per window" in text
    assert f"| `AGENT_FAILURE_RATE_LIMIT_MAX_REQUESTS` | `{failures}` |" in text
    from app.agent_limits import (
        NOT_VISIBLE_ROWS_PER_TOKEN,
        RIGHT_SECRET_ROWS_PER_TOKEN,
        ROWS_PER_KIND_OVERALL,
        WRONG_SECRET_ROWS_PER_TOKEN,
    )

    assert f"at most {WRONG_SECRET_ROWS_PER_TOKEN} per token id a window" in text
    assert f"at most {RIGHT_SECRET_ROWS_PER_TOKEN} per token id a window" in text
    assert f"at most {NOT_VISIBLE_ROWS_PER_TOKEN} per token a window" in text
    assert f"{ROWS_PER_KIND_OVERALL} overall" in text
    assert (
        f"| `AGENT_GLOBAL_FAILURE_RATE_LIMIT_MAX_REQUESTS` | `{defaults.agent_global_failure_rate_limit_max_requests}` |"
        in text
    )
    assert (
        f"| `AGENT_USER_RATE_LIMIT_MAX_REQUESTS` | `{defaults.agent_user_rate_limit_max_requests}` |"
        in text
    )
    assert defaults.agent_id_secret == "" and not defaults.agent_api_enabled


def test_every_documented_setting_is_read_listed_and_passed_on() -> None:
    names = sorted(set(re.findall(r"`(AGENT_[A-Z_]+)`", TEXT)))
    assert names == [
        "AGENT_FAILURE_RATE_LIMIT_MAX_REQUESTS",
        "AGENT_GLOBAL_FAILURE_RATE_LIMIT_MAX_REQUESTS",
        "AGENT_ID_SECRET",
        "AGENT_MAX_ACTIVE_TOKENS",
        "AGENT_RATE_LIMIT_MAX_REQUESTS",
        "AGENT_USER_RATE_LIMIT_MAX_REQUESTS",
    ]
    config = (ROOT / "server" / "app" / "config.py").read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    for name in names:
        assert f'"{name}"' in config, name
        assert name in example, name
        assert f"{name}: ${{{name}" in compose, name


def test_the_page_names_no_client_and_no_model() -> None:
    lowered = TEXT.lower()
    for word in (
        "claude", "anthropic", "openai", "chatgpt", "gpt-", "gemini", "copilot",
        "llama", "mistral", "medgemma", "openmed", "mcp", "cursor",
    ):  # fmt: skip
        assert word not in lowered, word


def test_the_page_is_in_the_navigation() -> None:
    nav = (ROOT / "zensical.toml").read_text(encoding="utf-8")
    assert "agent-api.md" in nav
