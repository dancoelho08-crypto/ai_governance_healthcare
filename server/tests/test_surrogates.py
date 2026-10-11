"""A lone surrogate in a request body is a 422, never a 500 (#187).

JSON permits ``"\\ud800"``, a UTF-16 half with no partner, and Python's parser
accepts it, but it is not a character: it cannot be encoded as UTF-8. FastAPI's own
validation-error handler echoed the offending input back, and encoding that echo
raised ``UnicodeEncodeError``: a request that failed validation, and carried a
surrogate, answered 500 instead of 422. A *valid* request carrying one got no better,
because asyncpg cannot encode it either.

The routes under test are read from the FastAPI app, not listed by hand, and a test
fails when a route that takes a body has no case here, so a new route cannot be added
and quietly left out.

Every body is sent as raw bytes: ``json.dumps`` writes a surrogate as the ASCII text
``\\ud800``, and httpx would otherwise fail to encode one on the client's side.
"""

from __future__ import annotations

import json
import re
from typing import NamedTuple

import pytest
from app.routes import router
from httpx import AsyncClient

from .conftest import requires_db

LONE = "\\ud800"  # the six characters of the JSON escape, not a surrogate itself
SURROGATE = re.compile("[\ud800-\udfff]")


class Case(NamedTuple):
    method: str
    path: str
    valid: str  # a body the route accepts
    invalid: list[str]  # bodies it must refuse, each carrying a lone surrogate
    tainted: str  # accepted but for the surrogate; empty when no field holds text


PID = "sg1"
CASES = [
    Case(
        "POST",
        "/api/projects/{id}",
        '{"meta": {"solution": "S"}}',
        [f'["{LONE}"]', f'"{LONE}"', f'[[{{"{LONE}": 1}}]]'],
        f'{{"meta": {{"solution": "{LONE}"}}}}',
    ),
    Case(
        "PATCH",
        "/api/projects/{id}",
        '{"meta": {"scope": "x"}}',
        [f'["{LONE}"]', f'[{{"{LONE}": [1]}}]'],
        f'{{"meta": {{"scope": "{LONE}"}}}}',
    ),
    Case(
        "POST",
        "/api/projects/{id}/hold",
        '{"action": "place", "reason": "r"}',
        [
            f'{{"action": "{LONE}", "reason": "r"}}',
            f'{{"action": "place", "reason": "r", "{LONE}": 1}}',
            f'{{"action": "place", "reason": ["{LONE}"]}}',
            f'{{"{LONE}": {{"a": ["{LONE}"]}}}}',
        ],
        f'{{"action": "place", "reason": "{LONE}"}}',
    ),
    Case(
        "POST",
        "/api/projects/{id}/log",
        '{"text": "hello"}',
        [
            f'{{"x": "{LONE}"}}',
            f'{{"text": "", "x": "{LONE}"}}',
            f'{{"text": 5, "{LONE}": 1}}',
            f'{{"text": ["{LONE}"]}}',
            f'["{LONE}"]',
        ],
        f'{{"text": "a{LONE}b"}}',
    ),
    Case(
        "POST",
        "/api/projects/{id}/exports",
        '{"format": "json"}',
        [
            f'{{"format": "{LONE}"}}',
            f'{{"format": ["{LONE}"]}}',
            f'["{LONE}"]',
        ],
        "",  # no free text: an unknown key is ignored, so nothing to taint
    ),
    Case(
        "POST",
        "/api/exports",
        '{"format": "csv"}',
        [
            f'{{"format": "{LONE}"}}',
            f'{{"format": ["{LONE}"]}}',
            f'["{LONE}"]',
        ],
        "",
    ),
]
HEADERS = {"Content-Type": "application/json"}


def body_routes() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for route in router.routes:
        if route.dependant.body_params:  # type: ignore[attr-defined]
            for method in route.methods:  # type: ignore[attr-defined]
                found.add((method, route.path.replace("{project_id}", "{id}")))  # type: ignore[attr-defined]
    return found


def test_every_route_that_takes_a_body_has_a_case() -> None:
    assert body_routes() == {(c.method, c.path) for c in CASES}


def clean(response) -> None:  # type: ignore[no-untyped-def]
    """The body is UTF-8 JSON, and no surrogate was echoed into it."""
    text = response.content.decode("utf-8")  # raises if the response is not UTF-8
    walk = [json.loads(text)]
    while walk:
        item = walk.pop()
        if isinstance(item, dict):
            walk.extend(item.keys())
            walk.extend(item.values())
        elif isinstance(item, list):
            walk.extend(item)
        elif isinstance(item, str):
            assert not SURROGATE.search(item)


async def send(client: AsyncClient, case: Case, body: str):  # type: ignore[no-untyped-def]
    return await client.request(
        case.method,
        case.path.replace("{id}", PID),
        content=body.encode("ascii"),
        headers=HEADERS,
    )


async def with_project(client: AsyncClient, case: Case | None = None) -> None:
    if case is not None and (case.method, case.path) == ("POST", "/api/projects/{id}"):
        return  # this is the route that creates it; the control does that
    assert (
        await client.post(f"/api/projects/{PID}", json={"meta": {"solution": "S"}})
    ).status_code == 201


def ids(cases: list[Case]) -> list[str]:
    return [f"{c.method} {c.path}" for c in cases]


@requires_db
@pytest.mark.parametrize("case", CASES, ids=ids(CASES))
async def test_an_invalid_body_with_a_surrogate_is_a_422(
    client: AsyncClient, case: Case
) -> None:
    await with_project(client)
    for body in case.invalid:
        response = await send(client, case, body)
        assert response.status_code == 422, (body, response.status_code)
        clean(response)


TAINTABLE = [c for c in CASES if c.tainted]


@requires_db
@pytest.mark.parametrize("case", TAINTABLE, ids=ids(TAINTABLE))
async def test_a_valid_body_with_a_surrogate_is_refused_not_a_500(
    client: AsyncClient, case: Case
) -> None:
    await with_project(client, case)
    # The control: the same body without the surrogate is accepted, so the 422
    # below is the surrogate and not something else wrong with the request.
    ok = await send(client, case, case.valid)
    assert ok.status_code in (200, 201, 204), (ok.status_code, ok.text[:200])
    response = await send(client, case, case.tainted)
    assert response.status_code == 422, (response.status_code, response.text[:200])
    clean(response)


@requires_db
async def test_a_refused_surrogate_leaves_no_trace_in_the_record(
    client: AsyncClient,
) -> None:
    from .conftest import owner_connection

    await with_project(client)
    await client.post(
        f"/api/projects/{PID}/log",
        content=f'{{"text": "{LONE}"}}'.encode(),
        headers=HEADERS,
    )
    await client.patch(
        f"/api/projects/{PID}",
        content=f'{{"meta": {{"scope": "{LONE}"}}}}'.encode(),
        headers=HEADERS,
    )
    async with owner_connection() as conn:
        assert await conn.fetchval("SELECT count(*) FROM project_log") >= 0
        doc = await conn.fetchval("SELECT doc::text FROM projects WHERE id = $1", PID)
    assert "scope" not in json.loads(doc)["meta"]
    assert "ud800" not in doc


@requires_db
async def test_a_surrogate_in_the_path_or_query_is_not_a_500(
    client: AsyncClient,
) -> None:
    await with_project(client)
    bad = "%ED%A0%80"  # the UTF-8 bytes of U+D800: not valid UTF-8 at all
    for method, url in (
        ("GET", f"/api/projects/{bad}/log"),
        ("GET", f"/api/projects/{PID}/log?limit={bad}"),
        ("GET", f"/api/projects/{PID}/log?before={bad}"),
        ("GET", f"/api/projects/{PID}/versions/{bad}"),
        ("DELETE", f"/api/projects/{bad}"),
        ("POST", f"/api/projects/{bad}"),
    ):
        response = await client.request(
            method, url, content=b'{"meta": {}}', headers=HEADERS
        )
        assert response.status_code < 500, (method, url, response.status_code)
        clean(response)
