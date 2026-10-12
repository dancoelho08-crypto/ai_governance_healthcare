"""This service's models are the agent API's response models, field for field (#164).

The service is a thin wrapper: what it returns is what the API returns, checked against
its own copy of the models. If the API grows, renames or drops a field, this fails, and
the wrapper is updated on purpose, not found out by a chatbot.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from chai_mcp import models as mcp

from app import agent as api

PAIRS = [
    (api.AgentMeOut, mcp.Whoami),
    (api.AgentItem, mcp.Item),
    (api.AgentGate, mcp.Gate),
    (api.AgentSupplement, mcp.Supplement),
    (api.AgentPeople, mcp.People),
    (api.AgentProject, mcp.Project),
    (api.AgentPortfolioOut, mcp.Portfolio),
]


@pytest.mark.parametrize(("theirs", "ours"), PAIRS, ids=[p[1].__name__ for p in PAIRS])
def test_the_fields_are_the_apis_fields(theirs, ours) -> None:
    assert list(ours.model_fields) == list(theirs.model_fields)
    for name, field in theirs.model_fields.items():
        assert ours.model_fields[name].is_required() == field.is_required(), name


def test_the_routes_are_the_apis_three_get_routes() -> None:
    from chai_mcp.upstream import Route

    paths = {
        r.path for r in api.agent_router.routes if "GET" in getattr(r, "methods", set())
    }
    assert {r.value.rstrip("/") for r in Route} == {
        p.replace("/{ref}", "") for p in paths
    }
    assert all(r.methods == {"GET"} for r in api.agent_router.routes)


def test_the_portfolio_filters_are_the_apis_filters() -> None:
    import inspect

    from chai_mcp.server import build_server

    from .harness import settings_for

    theirs = {
        (getattr(q.default, "alias", None) or n)
        for n, q in inspect.signature(api.agent_portfolio).parameters.items()
        if n not in {"request", "caller", "settings", "db"}
    }
    mcp_server, _ = build_server(settings_for("http://api.invalid"))
    [tool] = [
        t for t in mcp_server._tool_manager.list_tools() if t.name == "list_portfolio"
    ]
    assert set(tool.parameters["properties"]) == theirs


def test_the_api_and_this_service_agree_on_what_a_vocabulary_word_looks_like() -> None:
    """Every id, status and decision of the shipped build is a word to this service."""
    manifest = json.loads(
        (
            Path(__file__).resolve().parents[2] / "docs" / "app" / "manifest.json"
        ).read_text()
    )
    pattern = re.compile(mcp.WORD)
    for framework in manifest["frameworks"]:
        for kind, words in framework["vocab"].items():
            for word in words:
                assert pattern.fullmatch(word) and len(word) <= mcp.WORD_MAX, (
                    framework["id"],
                    kind,
                    word,
                )
        assert re.fullmatch(mcp.KEY, framework["id"])
