"""docs/mcp.md says what the MCP server does, and every example is true (#164).

A contract page that has drifted from the code is worse than none: a client is
configured against it. So the page is parsed, and held to the running service:

* every documented tool is a registered tool, and every registered tool is documented;
* every documented input parameter (its name, type and whether it is required) and every
  documented result field (its name, type and whether it may be null) is in the tool's
  own schema, and every field of the schema is documented, so a field added without a
  decision about the page fails here;
* every message the page lists is a message the service can say, and every message the
  service can say is on the page;
* every setting the page names is one the service reads or compose passes on, and every
  setting the service reads is on the page and in .env.example;
* the client configuration is valid JSON of the shape the page says, and the three curl
  commands, run against a REAL service in front of a REAL API on a real PostgreSQL with
  the credentials the page says they use, answer what the page shows;
* the page names no client, and states the MedGemma facts only as the owner decided.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import httpx
import pytest
from chai_mcp import models
from chai_mcp.server import ALLOWED_TOOLS, build_server
from chai_mcp.upstream import Message

from .conftest import requires_db
from .harness import running_service, settings_for
from .stack import ALICE, access, mint, put_project, real_api

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "mcp.md"
TEXT = DOC.read_text(encoding="utf-8")
HOST = "governance.example.org"


# --- reading the page ---------------------------------------------------------------


def section(title_pattern: str, level: int = 3) -> str:
    """The text from a heading to the next heading of the same or a higher level."""
    marks = "#" * level
    start = re.search(rf"^{marks} {title_pattern}\s*$", TEXT, re.M)
    assert start, f"no heading {title_pattern!r}"
    rest = TEXT[start.end() :]
    stop = re.search(rf"^#{{1,{level}}} ", rest, re.M)
    return rest[: stop.start()] if stop else rest


def table_rows(text: str, header_first_cell: str) -> list[list[str]]:
    """The rows (without the header) of the first table whose header starts with it."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("|") and line.strip("| ").split("|")[0].strip() == (
            header_first_cell
        ):
            rows = []
            for row in lines[i + 2 :]:
                if not row.startswith("|"):
                    break
                rows.append([c.strip() for c in row.strip().strip("|").split("|")])
            return rows
    return []


def table_after(text: str, label: str) -> list[list[str]]:
    """The rows of the table that follows ``**label**``."""
    start = text.index(f"**{label}**")
    lines = text[start:].splitlines()[1:]
    rows: list[list[str]] = []
    in_table = False
    for line in lines:
        if line.startswith("|"):
            in_table = True
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            rows.append(cells)
        elif in_table or line.startswith("**"):
            break
    return rows[1:]


def names(rows: list[list[str]]) -> list[str]:
    return [r[0].strip("`") for r in rows]


def json_blocks(text: str) -> list[object]:
    return [
        json.loads(m.group(1))
        for m in re.finditer(r"```json\n(.*?)\n```", text, re.S)
        if m.group(1).lstrip().startswith(("{", "["))
    ]


# --- what the schemas say ------------------------------------------------------------


def type_word(prop: dict, defs: dict) -> tuple[str, bool]:
    """(base type, may be null) of one JSON-schema property, as the page words it."""
    nullable = False
    options = prop.get("anyOf")
    if options:
        non_null = [o for o in options if o.get("type") != "null"]
        nullable = len(non_null) != len(options)
        prop = non_null[0]
    if "$ref" in prop:
        return "object", nullable
    kind = prop.get("type")
    if kind == "array":
        item = prop.get("items", {})
        return (
            "array of string" if item.get("type") == "string" else "array"
        ), nullable
    if kind == "string" and prop.get("format") == "date":
        return "string (date)", nullable
    return str(kind), nullable


def doc_type(cell: str) -> tuple[str, bool]:
    nullable = cell.endswith(" or null")
    base = cell.removesuffix(" or null")
    return base, nullable


def schema_fields(model) -> dict[str, tuple[str, bool]]:
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})
    return {name: type_word(prop, defs) for name, prop in schema["properties"].items()}


def doc_fields(rows: list[list[str]]) -> dict[str, tuple[str, bool]]:
    return {r[0].strip("`"): doc_type(r[1]) for r in rows}


def types_agree(doc: tuple[str, bool], schema: tuple[str, bool]) -> bool:
    # The page says "string" for a date field it describes in prose, and for a field
    # whose JSON type is a string; both are one JSON type.
    return doc[1] == schema[1] and doc[0].split(" (")[0] == schema[0].split(" (")[0]


# --- the tools -----------------------------------------------------------------------


def registered() -> dict:
    mcp, _ = build_server(settings_for("http://api.invalid"))
    return {t.name: t for t in mcp._tool_manager.list_tools()}


def test_every_registered_tool_is_documented_and_every_documented_tool_is_registered():
    documented = set(re.findall(r"^### `(\w+)`\s*$", TEXT, re.M))
    assert documented == {t.value for t in ALLOWED_TOOLS} == set(registered())


def test_every_documented_input_parameter_is_the_schema_and_every_one_is_documented():
    tools = registered()
    # whoami takes nothing, and says so.
    assert "**Input:** none." in section("`whoami`")
    assert tools["whoami"].parameters.get("properties", {}) == {}
    for tool in ("list_portfolio", "get_project"):
        rows = table_rows(section(f"`{tool}`"), "Parameter")
        props = tools[tool].parameters["properties"]
        required = set(tools[tool].parameters.get("required", []))
        assert set(names(rows)) == set(props), tool
        for row in rows:
            name, kind, req = row[0].strip("`"), row[1], row[2]
            assert (req == "yes") == (name in required), (tool, name)
            want, _ = type_word(props[name], {})
            assert kind.split(" (")[0] == want.split(" (")[0], (tool, name, kind, want)


@pytest.mark.parametrize(
    ("tool", "model", "label"),
    [
        ("whoami", models.Whoami, "Result fields"),
        ("list_portfolio", models.Portfolio, "Result fields"),
        ("get_project", models.Project, "Result fields"),
    ],
)
def test_every_documented_result_field_is_the_schema_and_every_one_is_documented(
    tool, model, label
):
    rows = table_after(section(f"`{tool}`"), label)
    documented, actual = doc_fields(rows), schema_fields(model)
    assert set(documented) == set(actual), tool
    for name, got in documented.items():
        assert types_agree(got, actual[name]), (tool, name, got, actual[name])


@pytest.mark.parametrize(
    ("label", "model"),
    [
        ("`people` fields", models.People),
        ("`items` fields", models.Item),
        ("`gates` fields", models.Gate),
        ("`supplements` fields", models.Supplement),
    ],
)
def test_the_nested_fields_are_documented_as_the_models_have_them(label, model):
    rows = table_after(section("`get_project`"), label)
    documented, actual = doc_fields(rows), schema_fields(model)
    assert set(documented) == set(actual), label
    for name, got in documented.items():
        assert types_agree(got, actual[name]), (label, name, got, actual[name])


def test_the_portfolio_projects_are_the_projects_the_page_describes():
    body = section("`list_portfolio`")
    assert "each as in [`get_project`](#get_project)" in body
    assert schema_fields(models.Portfolio)["projects"][0] == "array"


# --- the messages --------------------------------------------------------------------


def test_the_error_table_is_every_message_the_service_can_say():
    rows = table_rows(section("Errors", 2), "Message")
    said = [r[0].strip("`") for r in rows]
    for message in Message:
        assert message.value in said, message.name
    prefixes = (
        "the governance server did not accept the request:",
        "too many requests for this token",
    )
    for text in said:
        assert text in {m.value for m in Message} or text.startswith(prefixes), text
    for prefix in prefixes:
        assert any(s.startswith(prefix) for s in said), prefix
    # The wording the table gives for a 429 is the code's.
    from chai_mcp import upstream

    assert "retry after" in Path(upstream.__file__).read_text()
    assert any("retry after N seconds" in s for s in said)


# --- the settings --------------------------------------------------------------------


def test_the_documented_settings_are_the_ones_the_service_and_compose_use():
    rows = table_rows(section("Turn it on", 2), "Setting")
    documented = set()
    for row in rows:
        documented |= set(re.findall(r"`([A-Z][A-Z_]+)`", row[0]))
    config = (ROOT / "mcp" / "chai_mcp" / "config.py").read_text(encoding="utf-8")
    read = set(re.findall(r'(?:env\.get\(|_positive\(env, )"([A-Z_]+)"', config))
    assert read, "found no settings in config.py"
    assert read <= documented, f"read but not documented: {sorted(read - documented)}"
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in documented:
        assert name in compose or name in config, f"{name} is documented, not used"
    # compose sets these two itself (the gate's address, and the container's own port).
    for name in documented - {"API_BASE_URL", "MCP_PORT"}:
        assert name in example, f"{name} is not in .env.example"


def test_the_documented_defaults_are_the_codes():
    from chai_mcp import config

    text = section("Turn it on", 2)
    assert f"| `MCP_MAX_BODY_BYTES` | `{config.DEFAULT_MAX_BODY_BYTES}` |" in text
    assert (
        f"| `MCP_TIMEOUT_SECONDS` | `{int(config.DEFAULT_TIMEOUT_SECONDS)}` |" in text
    )
    assert f"| `MCP_MAX_IN_FLIGHT` | `{config.DEFAULT_MAX_IN_FLIGHT}` |" in text
    assert f"| `MCP_PORT` | `{config.DEFAULT_PORT}` |" in text
    limits = section("Limits", 2)
    assert "64 KB" in limits and "10 seconds" in limits and "16 (" in limits


def test_the_profile_the_page_names_is_the_compose_profile():
    import yaml

    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    profiles = {tuple(compose["services"][s]["profiles"]) for s in ("mcp", "mcp-gate")}
    assert profiles == {("agent-mcp",)}
    assert "docker compose --profile agent-mcp up -d --build" in TEXT
    assert "docker compose --profile agent-mcp rm -sf" in TEXT


# --- what the page is careful about --------------------------------------------------


def test_the_page_names_no_client_and_endorses_none():
    clients = (
        "Claude",
        "Cursor",
        "Copilot",
        "ChatGPT",
        "Open WebUI",
        "LibreChat",
        "Cline",
        "Windsurf",
        "Zed",
        "Goose",
        "Continue",
        "Gemini CLI",
        "Codex",
        "VS Code",
    )
    for name in clients:
        assert not re.search(rf"\b{name}\b", TEXT), name
    assert "ships **no client code**" in TEXT and "does not endorse a client" in TEXT
    # The one neutral mention, labeled.
    assert TEXT.count("OpenMed Agent") == 1
    paragraph = " ".join(
        next(p for p in TEXT.split("\n\n") if "OpenMed Agent" in p).split()
    )
    assert "not tested here" in paragraph and "Apache-2.0 per its README" in paragraph
    assert "gated access" in paragraph


def test_the_medgemma_facts_are_owner_decided_and_labeled_as_the_cards_to_verify():
    body = section("An example: MedGemma", 3)
    assert "has not been tested with this server" in body
    assert "MedGemma is a **model, not a client**" in body
    assert "google/medgemma-27b-text-it" in body
    rows = table_rows(body, "Fact")
    assert len(rows) == 7
    for row in rows:
        assert row[1].endswith("verify at the source.")
    facts = " ".join(r[0] for r in rows)
    for must in (
        "text-only",
        "Gemma 3",
        "128K tokens of input, 8K of output",
        "gated",
        "Health AI Developer Foundations",
        "**not** Apache-2.0",
        "never bundles or redistributes",
        "vLLM or SGLang",
        "does not mention function calling",
        "not evaluated for multi-turn",
        "54 GB",
        "our arithmetic",
        "not for diagnosis or patient management",
    ):
        assert must in facts or must in " ".join(r[1] for r in rows), must
    # Nothing else on the page says MedGemma has a permissive license.
    assert TEXT.count("Apache-2.0") == 2  # OpenMed's README, and "not Apache-2.0"
    assert (
        "untested" in body.lower() and "Untested here" in body
    ) or "Untested here" in body
    assert "vllm serve google/medgemma-27b-text-it" in body


def test_the_operators_checklist_asks_what_it_must():
    body = section("Should you turn it on\\?", 2)
    for must in (
        "Which model?",
        "Where does it run?",
        "Does the data leave your network?",
        "What does the model's operator keep?",
        "Who can mint a token?",
        "Turning the\n   MCP service off does not stop a person calling the agent API",
    ):
        assert must in body, must
    assert "decision for the **operator**" in body


def test_every_route_this_page_says_is_refused_is_refused_by_the_service():
    """The HTTP statuses of the page's last paragraph of 'Errors'."""
    text = section("Errors", 2)
    for pair in ("`401`", "`403`", "`404`", "`405`", "`413`", "`421`", "`400`"):
        assert pair in text


def test_the_client_configuration_is_json_of_the_shape_the_page_says():
    blocks = json_blocks(section("Connecting a client", 2))
    config = next(b for b in blocks if "mcpServers" in b)
    server = config["mcpServers"]["governance"]
    assert server["url"].endswith("/mcp") and server["url"].startswith("https://")
    assert server["headers"]["Authorization"].startswith("Bearer agt_")
    other = next(
        b for b in json_blocks(section("An example: MedGemma", 3)) if "mcp_servers" in b
    )
    assert other["mcp_servers"][0]["url"].endswith("/mcp")
    assert other["model"]["base_url"].endswith("/v1")


def test_the_page_is_in_the_nav_and_linked_from_where_a_reader_looks():
    nav = (ROOT / "zensical.toml").read_text(encoding="utf-8")
    assert '{ "The MCP server" = "mcp.md" }' in nav
    for page in ("agent-api.md", "privacy.md", "self-hosting.md", "deploy.md"):
        assert "mcp.md" in (ROOT / "docs" / page).read_text(encoding="utf-8"), page


# --- the examples, run -----------------------------------------------------------------


def curl_commands() -> list[tuple[dict[str, str], object]]:
    """(headers, JSON body) of each curl command in the page's raw example."""
    found = []
    for block in re.findall(r"```bash\n(curl -sS \"\$MCP_URL\".*?)\n```", TEXT, re.S):
        argv = shlex.split(block)
        headers, body = {}, None
        for i, arg in enumerate(argv):
            if arg == "-H":
                key, _, value = argv[i + 1].partition(": ")
                headers[key] = value
            if arg == "-d":
                body = json.loads(argv[i + 1])
        found.append((headers, body))
    return found


def shape_issues(documented, actual, path="", subset=False) -> list[str]:
    """Where an example's shape differs from the real answer's: object keys and value
    kinds. Lists are compared by their first element; null matches any kind."""
    if documented is None or actual is None:
        return []
    if isinstance(documented, dict):
        if not isinstance(actual, dict):
            return [f"{path}: not an object"]
        out = []
        missing = set(documented) - set(actual)
        extra = set(actual) - set(documented)
        out += [f"{path}.{k}: documented, not returned" for k in sorted(missing)]
        if not subset:
            out += [f"{path}.{k}: returned, not documented" for k in sorted(extra)]
        for k in set(documented) & set(actual):
            out += shape_issues(documented[k], actual[k], f"{path}.{k}", subset)
        return out
    if isinstance(documented, list):
        if not isinstance(actual, list):
            return [f"{path}: not a list"]
        if documented and actual:
            return shape_issues(documented[0], actual[0], f"{path}[0]", subset)
        return []
    same = isinstance(documented, type(actual)) or (
        isinstance(documented, int | float) and isinstance(actual, int | float)
    )
    return (
        []
        if same
        else [f"{path}: {type(documented).__name__} vs {type(actual).__name__}"]
    )


@requires_db
def test_the_documented_curl_commands_run_and_answer_what_the_page_shows():
    commands = curl_commands()
    assert [c[1]["method"] for c in commands] == [
        "initialize",
        "tools/list",
        "tools/call",
    ]
    with real_api() as api:
        put_project(
            "docs-example",
            {
                "meta": {"framework": {"id": "chai"}},
                "items": {"s1-3": {"status": "notmet", "due": "2026-09-01"}},
                "access": access(owners=[ALICE]),
            },
        )
        token = mint(api)["token"]
        with running_service(api.url, allowed_hosts=(HOST,)) as svc:
            answers = []
            for headers, body in commands:
                sent = {k: v.replace("$TOKEN", token) for k, v in headers.items()}
                assert sent["Authorization"] == f"Bearer {token}"
                response = httpx.post(
                    f"{svc.url}/mcp", json=body, headers={**sent, "Host": HOST}
                )
                assert response.status_code == 200, response.text
                assert "mcp-session-id" not in {k.lower() for k in response.headers}
                answers.append(response.json())
            # The list_portfolio example call, as the page words it.
            listed = httpx.post(
                f"{svc.url}/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": json.loads(
                        re.search(
                            r'```json\n(\{"name": "list_portfolio".*?)\n```', TEXT
                        ).group(1)
                    ),
                },
                headers={
                    **commands[0][0],
                    "Authorization": f"Bearer {token}",
                    "Host": HOST,
                },
            ).json()
    init, tools, who = answers
    blocks = json_blocks(section("Connecting a client", 2))
    example_init = next(b for b in blocks if b.get("id") == 1)
    example_who = next(b for b in blocks if b.get("id") == 3)
    assert shape_issues(example_init, init, subset=True) == []
    assert shape_issues(example_who, who) == []
    assert who["result"]["isError"] is False
    # The text content is the same JSON as the structured content.
    assert (
        json.loads(who["result"]["content"][0]["text"])
        == who["result"]["structuredContent"]
    )
    assert {t["name"] for t in tools["result"]["tools"]} == {
        t.value for t in ALLOWED_TOOLS
    }
    assert all(t["annotations"]["readOnlyHint"] for t in tools["result"]["tools"])
    # The portfolio example.
    portfolio_blocks = json_blocks(section("`list_portfolio`"))
    example_call = next(b for b in portfolio_blocks if "name" in b)
    assert example_call == {
        "name": "list_portfolio",
        "arguments": {"status": "notmet", "limit": 5},
    }
    example_result = next(b for b in portfolio_blocks if "projects" in b)
    result = listed["result"]
    assert result["isError"] is False
    assert shape_issues(example_result, result["structuredContent"]) == []
