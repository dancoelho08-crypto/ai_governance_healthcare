"""Reading a governance record must leave a trace (#33).

Every read route returned data and wrote nothing, and the exports never touched the
server at all. So "account X was compromised on the 3rd and closed on the 9th; which
records did it open, and did it export any?" had no answer anywhere in the stack, and
every breach would be scoped to the whole portfolio by default (GDPR Art. 33(3)(a)).
45 CFR 164.312(b), audit controls, is *required*.

`access_event` is that record: append-only like the audit log, with no foreign key so it
outlives the project, and written in the same transaction as the read it describes. The
same fact also goes out as a security event, which is the copy a database administrator
cannot alter.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pytest
from app.accessaudit import AccessAction, AccessVia
from app.main import configure_logging
from httpx import ASGITransport, AsyncClient

from .conftest import TEST_EMAIL, TEST_HEADERS, owner_connection, requires_db
from .test_events import base_url  # noqa: F401  (the uvicorn fixture)

pytestmark = [requires_db, pytest.mark.db]

OTHER = "other@hospital.example"
STRANGER = "stranger@hospital.example"


def as_user(client: AsyncClient, email: str, **extra: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=client.app),
        base_url="http://api.test",
        headers={**TEST_HEADERS, "X-Forwarded-Email": email, **extra},
    )


async def events() -> list[dict]:
    async with owner_connection() as conn:
        rows = await conn.fetch("SELECT * FROM access_event ORDER BY id")
    return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]


@pytest.fixture
async def project(client: AsyncClient) -> str:
    r = await client.post(
        "/api/projects/audited",
        json={
            "meta": {"solution": "Audited"},
            "access": {"owners": [TEST_EMAIL], "writers": [], "readers": [OTHER]},
        },
    )
    assert r.status_code == 201
    async with owner_connection() as conn:
        await conn.execute("TRUNCATE access_event")  # the setup is not under test
    return "audited"


async def test_listing_records_which_projects_it_returned(
    client: AsyncClient, project: str
) -> None:
    await client.post("/api/projects/second", json={"meta": {"solution": "Two"}})
    async with owner_connection() as conn:
        await conn.execute("TRUNCATE access_event")
    assert (await client.get("/api/projects")).status_code == 200
    [event] = await events()
    assert event["action"] == "list" and event["actor"] == TEST_EMAIL
    assert event["project_id"] is None
    assert sorted(event["detail"]["projects"]) == ["audited", "second"]
    assert event["detail"]["count"] == 2


async def test_a_list_names_only_what_the_caller_was_given(
    client: AsyncClient, project: str
) -> None:
    async with as_user(client, STRANGER) as other:
        assert (await other.get("/api/projects")).json() == []
    [event] = await events()
    assert event["actor"] == STRANGER and event["detail"] == {
        "count": 0,
        "projects": [],
    }


async def test_each_read_route_records_what_it_returned(
    client: AsyncClient, project: str
) -> None:
    await client.get(f"/api/projects/{project}/versions")
    await client.get(f"/api/projects/{project}/versions/1")
    await client.get(f"/api/projects/{project}/log")
    rows = await events()
    assert [(e["action"], e["project_id"], e["revision"]) for e in rows] == [
        ("read_versions", project, None),
        ("read_version", project, 1),
        ("read_log", project, None),
    ]
    assert all(e["actor"] == TEST_EMAIL for e in rows)


async def test_a_reader_is_recorded_too(client: AsyncClient, project: str) -> None:
    async with as_user(client, OTHER) as reader:
        await reader.get(f"/api/projects/{project}/log")
    [event] = await events()
    assert event["actor"] == OTHER and event["action"] == "read_log"


async def test_a_refused_read_is_not_recorded_as_a_read(
    client: AsyncClient, project: str
) -> None:
    """Nothing was disclosed. The attempt is an access.denied security event."""
    async with as_user(client, STRANGER) as other:
        assert (await other.get(f"/api/projects/{project}/log")).status_code == 404
        assert (await other.get(f"/api/projects/{project}/versions")).status_code == 404
        assert (await other.get("/api/projects/never/log")).status_code in (200, 404)
    assert [e["action"] for e in await events() if e["project_id"] == project] == []


async def test_attaching_to_the_event_stream_is_recorded(
    base_url: str,  # noqa: F811
) -> None:
    """The stream delivers change notifications, so who attached is part of the trail."""
    async with AsyncClient(base_url=base_url, headers=TEST_HEADERS) as http:
        async with http.stream("GET", "/api/events") as response:
            assert response.status_code == 200
            async for line in response.aiter_lines():
                if line.startswith("event: hello"):
                    break
    [event] = [e for e in await events() if e["action"] == "stream_attach"]
    assert event["actor"] == TEST_EMAIL and event["project_id"] is None


async def test_the_source_is_what_the_proxy_reported(
    client: AsyncClient, project: str
) -> None:
    async with as_user(client, TEST_EMAIL, **{"X-Real-IP": "203.0.113.9"}) as http:
        await http.get(f"/api/projects/{project}/log")
    [event] = await events()
    assert event["source_ip"] == "203.0.113.9"


async def test_the_export_beacon_records_an_export(
    client: AsyncClient, project: str
) -> None:
    r = await client.post(f"/api/projects/{project}/exports", json={"format": "pdf"})
    assert r.status_code == 204
    [event] = await events()
    assert event["action"] == "export" and event["project_id"] == project
    assert event["detail"] == {"format": "pdf"}


async def test_a_reader_may_export_and_it_is_recorded(
    client: AsyncClient, project: str
) -> None:
    async with as_user(client, OTHER) as reader:
        assert (
            await reader.post(f"/api/projects/{project}/exports", json={"format": "md"})
        ).status_code == 204
    assert (await events())[0]["actor"] == OTHER


async def test_a_stranger_cannot_use_the_beacon_to_probe_or_to_forge(
    client: AsyncClient, project: str
) -> None:
    async with as_user(client, STRANGER) as other:
        r = await other.post(f"/api/projects/{project}/exports", json={"format": "md"})
    assert r.status_code == 404, "no access to the project, so no entry about it"
    assert await events() == []


@pytest.mark.parametrize(
    "body", [{}, {"format": "docx"}, {"format": ""}, {"format": 5}]
)
async def test_an_unknown_export_format_is_refused(
    client: AsyncClient, project: str, body: dict
) -> None:
    r = await client.post(f"/api/projects/{project}/exports", json=body)
    assert r.status_code == 422
    assert await events() == []


async def test_the_trail_is_append_only(client: AsyncClient, project: str) -> None:
    import asyncpg

    await client.get(f"/api/projects/{project}/log")
    async with owner_connection() as conn:
        with pytest.raises(asyncpg.PostgresError, match="append-only"):
            await conn.execute("UPDATE access_event SET actor = 'someone-else'")
        with pytest.raises(asyncpg.PostgresError, match="append-only"):
            await conn.execute("DELETE FROM access_event")


async def test_the_trail_outlives_the_project(
    client: AsyncClient, project: str
) -> None:
    await client.get(f"/api/projects/{project}/log")
    assert (await client.delete(f"/api/projects/{project}")).status_code == 204
    kept = [e for e in await events() if e["project_id"] == project]
    assert kept, "deleting a project must not erase who read it"


async def test_a_read_that_fails_leaves_no_row(
    client: AsyncClient, project: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same transaction: no read without a record, no record without a read."""
    import app.routes as routes

    async def explode(*args, **kwargs):
        raise RuntimeError("the audit write failed")

    monkeypatch.setattr(routes, "record_access", explode)
    transport = ASGITransport(app=client.app, raise_app_exceptions=False)
    async with AsyncClient(
        transport=transport, base_url="http://api.test", headers=TEST_HEADERS
    ) as http:
        r = await http.get(f"/api/projects/{project}/log")
    assert r.status_code == 500, "a read that cannot be recorded is not served"
    assert await events() == []


async def test_the_same_facts_go_out_as_security_events(
    client: AsyncClient, project: str
) -> None:
    buffer = io.StringIO()
    configure_logging("info", "json", stream=buffer)
    try:
        await client.get(f"/api/projects/{project}/versions/1")
        await client.post(f"/api/projects/{project}/exports", json={"format": "html"})
    finally:
        configure_logging("info", "json", stream=io.StringIO())
    lines = [json.loads(x) for x in buffer.getvalue().splitlines() if x.startswith("{")]
    read = [r for r in lines if r.get("event") == "record.read"]
    exported = [r for r in lines if r.get("event") == "record.exported"]
    assert read and read[0]["action"] == "read_version" and read[0]["revision"] == 1
    assert read[0]["actor"] == TEST_EMAIL and read[0]["project"] == project
    assert exported and exported[0]["format"] == "html"
    assert all(r["stream"] == "security" for r in read + exported)


async def test_the_check_constraint_and_the_enum_agree(client: AsyncClient) -> None:
    """A column holding an enum keeps a CHECK listing the same values."""
    async with owner_connection() as conn:
        definition = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'access_event'::regclass AND contype = 'c' "
            "AND conname = 'access_event_action_known'"
        )
        via = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'access_event'::regclass AND contype = 'c' "
            "AND conname = 'access_event_via_known'"
        )
    in_db = set(re.findall(r"'([a-z_]+)'", definition))
    assert in_db == {a.value for a in AccessAction}
    assert set(re.findall(r"'([a-z_]+)'", via)) == {v.value for v in AccessVia}


DOC = Path(__file__).resolve().parents[2] / "docs" / "deploy.md"


async def test_the_investigators_query_in_the_docs_answers_the_question(
    client: AsyncClient, project: str
) -> None:
    """'Which records did this account open, and did it export any?' (#33)."""
    text = DOC.read_text(encoding="utf-8")
    section = text[text.index("### The read trail") :]
    block = re.search(r"```sql\n(.*?)```", section, re.S).group(1)
    first = re.split(r"\n\n(?=--)", block)[0].strip().rstrip(";")

    async with as_user(client, OTHER) as reader:
        await reader.get(f"/api/projects/{project}/log")
        await reader.post(f"/api/projects/{project}/exports", json={"format": "pdf"})
    async with owner_connection() as conn:
        rows = await conn.fetch(
            first.replace("person@hospital.org", OTHER)
            .replace("2026-01-01", "2000-01-01")
            .replace("2026-02-01", "2100-01-01")
        )
    seen = {(r["action"], r["project_id"]) for r in rows}
    assert ("read_log", project) in seen and ("export", project) in seen
