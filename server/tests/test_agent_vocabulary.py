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


# --- the manifest is trusted build output, read with a shape and safety filter ----------


def _chai(edit):
    return mutated(lambda d: edit(d["frameworks"][0]["vocab"]))


@pytest.mark.parametrize(
    "case, edit",
    [
        ("a lone surrogate", lambda v: v["items"].append("a\ud800b")),
        ("a zero-width space", lambda v: v["items"].append("s1" + chr(0x200B) + "-1")),
        (
            "a right-to-left override",
            lambda v: v["decisions"].append("Stop" + chr(0x202E)),
        ),
        ("a byte-order mark", lambda v: v["statuses"].append(chr(0xFEFF) + "met")),
        ("a private-use character", lambda v: v["gates"].append("A" + chr(0xE000))),
        (
            "a line separator",
            lambda v: v["decisions"].append("Go" + chr(0x2028) + "now"),
        ),
        ("a tab", lambda v: v["decisions"].append("Go\tnow")),
        ("surrounding space", lambda v: v["decisions"].append(" Proceed ")),
        ("a sentence over the length", lambda v: v["decisions"].append("x" * 65)),
        (
            "too many words of one kind",
            lambda v: v["items"].extend(f"extra-{i}" for i in range(5_001)),
        ),
    ],
)
def test_a_word_a_display_word_could_not_be_is_refused(case, edit) -> None:
    with pytest.raises(ManifestError):
        parse_manifest(_chai(edit))
    assert case


def test_a_word_with_spaces_is_a_display_word() -> None:
    parse_manifest(_chai(lambda v: v["decisions"].append("Proceed with conditions, 2")))
    parse_manifest(_chai(lambda v: v["items"].append("x" * 64)))


def test_a_manifest_with_too_many_words_overall_is_refused() -> None:
    def edit(doc) -> None:
        template = next(f for f in doc["frameworks"] if f["role"] == "supplement")
        for n in range(4):
            extra = copy.deepcopy(template)
            extra["id"] = f"supp{n}"
            extra["vocab"] = {
                "items": [f"i{n}-{i}" for i in range(5_000)],
                "gates": [f"g{n}-{i}" for i in range(5_000)],
                "statuses": [f"s{n}-{i}" for i in range(5_000)],
                "decisions": [],
            }
            doc["frameworks"].append(extra)

    with pytest.raises(ManifestError, match="more than 50000"):
        parse_manifest(mutated(edit))


def test_a_repeated_json_key_is_refused_and_not_silently_resolved() -> None:
    text = manifests.DEFAULT_MANIFEST.read_text(encoding="utf-8")
    doubled = text.replace('"gates": [', '"gates": ["A"], "gates": [', 1)
    assert doubled != text
    with pytest.raises(ManifestError, match="repeats the key 'gates'"):
        parse_manifest(doubled)
    with pytest.raises(ManifestError, match="repeats the key"):
        parse_manifest('{"manifest": 1, "manifest": 1}')


@requires_db
@pytest.mark.usefixtures("client")
async def test_a_manifest_that_cannot_be_loaded_stops_the_job_cleanly(tmp_path) -> None:
    """A lone surrogate used to pass the parse and crash the INSERT after the
    retirement sync. It is now refused before the job touches anything."""
    bad = tmp_path / "manifest.json"
    bad.write_text(
        mutated(lambda d: d["frameworks"][0]["vocab"]["items"].append("a\ud800b")),
        encoding="utf-8",
        errors="surrogatepass",
    )
    done = manifests.run_migrate(DB_URL, RETIREMENT_MANIFEST=str(bad))
    assert done.returncode == 1
    assert "Traceback" not in done.stderr and "invisible one" in done.stderr
    default = parse_manifest(manifests.DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    assert await table() == expected_rows(default)  # and nothing was changed


# --- the API role can read the words and nothing else -----------------------------------


@requires_db
@pytest.mark.usefixtures("client")
async def test_the_api_role_may_only_read_the_vocabulary() -> None:
    """Written by hand, not from roles.GRANTS: if a mutation widens GRANTS and the
    grants together, test_roles agrees with itself and this does not."""
    import asyncpg
    from app.roles import provision

    from .test_roles import dsn_as

    role, password = "chai_app_vocab_test", "vocab-test-password-0123456789"
    async with owner_connection() as owner:
        if await owner.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role):
            await owner.execute(f"DROP OWNED BY {role}")
            await owner.execute(f"DROP ROLE {role}")
        await provision(owner, role, password)
        try:
            granted = {
                r["privilege_type"]
                for r in await owner.fetch(
                    "SELECT privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_name = 'agent_vocabulary' AND grantee = $1",
                    role,
                )
            }
            assert granted == {"SELECT"}
            app = await asyncpg.connect(dsn_as(role, password))
            try:
                assert await app.fetchval("SELECT count(*) FROM agent_vocabulary") > 0
                for statement in (
                    "INSERT INTO agent_vocabulary VALUES ('chai', 'items', 'x')",
                    "UPDATE agent_vocabulary SET value = 'x'",
                    "DELETE FROM agent_vocabulary",
                    "TRUNCATE agent_vocabulary",
                ):
                    with pytest.raises(asyncpg.InsufficientPrivilegeError):
                        await app.execute(statement)
            finally:
                await app.close()
        finally:
            await owner.execute(f"DROP OWNED BY {role}")
            await owner.execute(f"DROP ROLE {role}")
