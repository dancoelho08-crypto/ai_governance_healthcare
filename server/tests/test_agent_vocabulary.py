"""The words an agent may be shown travel with the build (#164, D-89).

A record's item ids, checkpoint ids and statuses are whatever a writer typed, so the
agent API returns one only if it is a word of the build's framework definitions. The
server image knows no framework (D-76), so scripts/build_manifest.py writes the words
into manifest.json and the migrate job loads them into agent_vocabulary, the way the
retirement rules go. These tests hold both ends and the table between them.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from app.retirement import ManifestError, parse_manifest, sync_vocabulary

from . import manifests
from .conftest import DB_URL, owner_connection, requires_db

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = json.loads(manifests.DEFAULT_MANIFEST.read_text(encoding="utf-8"))


def mutated(edit) -> str:
    doc = copy.deepcopy(DEFAULT)
    edit(doc)
    return json.dumps(doc)


# --- the manifest: pure ------------------------------------------------------------


def test_the_build_writes_each_frameworks_words_into_the_manifest() -> None:
    defs = manifests.default_build()
    written = manifests.build_manifest.manifest(defs, "chai")
    by_id = {f["id"]: f["vocab"] for f in written["frameworks"]}
    chai = defs["chai"]
    assert by_id["chai"]["gates"] == sorted(g["id"] for g in chai["gates"])
    assert by_id["chai"]["statuses"] == sorted(s["value"] for s in chai["statuses"])
    assert "s1-1" in by_id["chai"]["items"] and "A" in by_id["chai"]["gates"]
    assert "Proceed" in by_id["chai"]["decisions"]
    assert by_id["optica"]["items"] and by_id["optica"]["gates"] == []
    assert "declined" in by_id["optica"]["statuses"]
    assert written == DEFAULT  # and the committed manifest is what the build writes


def test_the_words_are_outside_the_rule_set_hash() -> None:
    """They decide what an agent sees, never disposal, so adding one needs no
    acknowledgment: the hash the retirement rules are acknowledged by is unchanged."""
    defs = manifests.default_build()
    grown = copy.deepcopy(defs)
    grown["chai"]["sections"][0]["items"].append(
        {"id": "s1-99", "category": "U", "text": "x"}
    )
    a = manifests.build_manifest.manifest(defs, "chai")
    b = manifests.build_manifest.manifest(grown, "chai")
    assert a["ruleSetHash"] == b["ruleSetHash"]
    assert "s1-99" in b["frameworks"][0]["vocab"]["items"]
    assert "s1-99" not in a["frameworks"][0]["vocab"]["items"]


def test_the_server_reads_the_words_strictly() -> None:
    manifest = parse_manifest(manifests.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    chai = next(f for f in manifest.frameworks if f.id == "chai")
    assert dict(chai.vocab)["gates"] == frozenset({"A", "B", "C", "D"})
    for why, edit in {
        "an unknown kind": lambda d: d["frameworks"][0]["vocab"].update(notes=["x"]),
        "a missing kind": lambda d: d["frameworks"][0]["vocab"].pop("gates"),
        "not a list": lambda d: d["frameworks"][0]["vocab"].update(items="s1-1"),
        "a word that is not text": lambda d: d["frameworks"][0]["vocab"][
            "items"
        ].append(7),
        "a blank word": lambda d: d["frameworks"][0]["vocab"]["items"].append("  "),
        "a control character": lambda d: d["frameworks"][0]["vocab"]["items"].append(
            "a\nb"
        ),
        "an overlong word": lambda d: d["frameworks"][0]["vocab"]["items"].append(
            "x" * 201
        ),
        "a word twice": lambda d: d["frameworks"][0]["vocab"]["items"].append("s1-1"),
    }.items():
        with pytest.raises(ManifestError):
            parse_manifest(mutated(edit))
        assert why


def test_a_manifest_without_words_is_still_a_manifest() -> None:
    """A build that predates the words loads, and shows an agent none."""
    text = mutated(lambda d: [f.pop("vocab") for f in d["frameworks"]])
    manifest = parse_manifest(text)
    assert all(f.vocab == () for f in manifest.frameworks)


# --- the table: real PostgreSQL -------------------------------------------------------


async def table() -> set[tuple[str, str, str]]:
    async with owner_connection() as conn:
        rows = await conn.fetch(
            "SELECT framework_id, kind, value FROM agent_vocabulary"
        )
    return {(r["framework_id"], r["kind"], r["value"]) for r in rows}


def expected_rows(manifest) -> set[tuple[str, str, str]]:
    return {(f.id, "framework", f.role.value) for f in manifest.frameworks} | {
        (f.id, kind, w) for f in manifest.frameworks for kind, ws in f.vocab for w in ws
    }


@requires_db
@pytest.mark.usefixtures("client")
async def test_loading_replaces_the_table_wholesale() -> None:
    default = parse_manifest(manifests.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    assert await table() == expected_rows(default)
    # A build with other words: the old ones are gone, not kept beside them.
    other = parse_manifest(
        mutated(
            lambda d: d["frameworks"][0]["vocab"].update(
                items=["only-this"], decisions=["Proceed"]
            )
        )
    )
    async with owner_connection() as conn:
        written = await sync_vocabulary(conn, other)
    assert written == len(expected_rows(other))
    rows = await table()
    assert rows == expected_rows(other)
    assert ("chai", "items", "s1-1") not in rows
    # A manifest with no words empties it: an agent is then shown none.
    bare = parse_manifest(mutated(lambda d: [f.pop("vocab") for f in d["frameworks"]]))
    async with owner_connection() as conn:
        await sync_vocabulary(conn, bare)
    assert {k for _, k, _ in await table()} == {"framework"}


@requires_db
@pytest.mark.usefixtures("client")
async def test_the_migrate_job_loads_the_words_from_the_manifest() -> None:
    async with owner_connection() as conn:
        await conn.execute("DELETE FROM agent_vocabulary")
    done = manifests.run_migrate(
        DB_URL, RETIREMENT_MANIFEST=str(manifests.DEFAULT_MANIFEST)
    )
    assert done.returncode == 0, done.stderr
    assert re.search(r"agent vocabulary row\(s\) loaded", done.stdout)
    default = parse_manifest(manifests.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    assert await table() == expected_rows(default)


@requires_db
@pytest.mark.usefixtures("client")
async def test_the_table_refuses_a_kind_it_does_not_know() -> None:
    import asyncpg

    async with owner_connection() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO agent_vocabulary VALUES ('chai', 'notes', 'x')"
            )
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "INSERT INTO agent_vocabulary VALUES ('chai', 'framework', 'owner')"
            )


@requires_db
@pytest.mark.usefixtures("client")
async def test_the_table_and_the_enum_agree() -> None:
    from app.agent import VocabKind

    async with owner_connection() as conn:
        definition = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'agent_vocabulary_kind_known'"
        )
    assert set(re.findall(r"'([a-z]+)'", definition)) == {k.value for k in VocabKind}
