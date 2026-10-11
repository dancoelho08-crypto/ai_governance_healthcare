"""Which decisions end a project, from the build's own framework definition (R-66).

``retention_due()`` starts a project's retention clock when it is retired (R-56),
and what counts as retired is a property of the framework the dashboard was built
with: a checkpoint option whose class is ``stop`` or ``retire``. The build writes
those pairs into ``docs/app/manifest.json`` (``scripts/build_app.py``) from the same
definitions the page embeds, and the migrate job loads them into ``retirement_rule``
here, as the database owner, under the migration lock (D-76).

The sync never changes disposal silently:

* a manifest governs only the frameworks it lists. Rules of a framework it does not
  list are left as they are, so the records of an earlier primary keep retiring by
  their own rules, and the job reports them;
* any change, a pair added or a pair removed or a new primary, is made only when
  ``RETIREMENT_RULES_ACK`` equals :func:`transition_ack` of that whole change: every
  rule the table holds before and after it, the primary before and after, the
  history row it follows (its id and time) and the database's identity (012).
  Otherwise the job refuses, names every project whose disposal would start or stop
  being due, prints the value to set, and exits non-zero. Because the value binds
  the change it was printed for, the row it follows and the database, it accepts
  that change once and nothing else: not a different change between the same
  primary rule sets, not a stale manifest undoing a newer one, not the same change
  again later, not another database with the same history, and not a database a
  dump of this one was restored into, or restored over (a copy of the database's
  files, such as a snapshot, is to it the database it was copied from). It binds
  the rules, not the records: a project edited between the refusal and the
  acknowledged run is affected without having been listed;
* a sync that changes nothing (the same rows, the same primary) needs no
  acknowledgment, so the default build on a fresh database (whose seed is that
  build's rule set) starts without one;
* a missing or malformed manifest, or a primary with nothing that ends a project,
  fails the job. There is no fallback to CHAI's rules or to the table as it stands.

Every change is a row in the append-only ``retirement_rule_change`` and a security
event.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, NamedTuple

import asyncpg

from .db import MIGRATION_LOCK_ID
from .securitylog import SecurityEvent, emit

MANIFEST_FORMAT = 1
# A record with no meta.framework.id is CHAI's: every record written before records
# were stamped is. 010_retirement_rules.sql's record_framework() says the same.
UNSTAMPED_FRAMEWORK = "chai"
# The definition's id pattern (schema/framework.schema.json), for frameworks and gates.
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_DECISION = 200

log = logging.getLogger("chai.retirement")


class FrameworkRole(StrEnum):
    """A framework's role in a build (schema/framework.schema.json)."""

    PRIMARY = "primary"
    SUPPLEMENT = "supplement"


class ChangeSource(StrEnum):
    """Who wrote a ``retirement_rule_change`` row. The CHECK constraint in 010 lists
    the same values, and ``tests/test_retention.py`` fails if the two drift."""

    SEED = "seed"
    MANIFEST = "manifest"


class SyncOutcome(StrEnum):
    # Nothing to do: the latest manifest sync recorded these rules and this primary.
    UNCHANGED = "unchanged"
    # Nothing changed, but a row was recorded: the first manifest to confirm 010's
    # seed, after which /api/health reports the rules as synced.
    CONFIRMED = "confirmed"
    # Rules were added or removed, or the primary changed, as acknowledged.
    CHANGED = "changed"


class ManifestError(ValueError):
    """The manifest is missing or is not one this server will act on."""


class RulesRefused(RuntimeError):
    """The manifest changes the rules and the transition was not acknowledged."""


class Rule(NamedTuple):
    framework_id: str
    gate_id: str
    decision: str


@dataclass(frozen=True)
class FrameworkEntry:
    id: str
    role: FrameworkRole
    version: str
    sha256: str
    retire: frozenset[tuple[str, str]]
    # What an agent may be shown of a record of this framework (D-89): kind -> words.
    # Empty for a manifest from a build that predates it.
    vocab: tuple[tuple[str, frozenset[str]], ...] = ()


@dataclass(frozen=True)
class Manifest:
    primary: str
    frameworks: tuple[FrameworkEntry, ...]
    rule_set_hash: str

    @property
    def primary_entry(self) -> FrameworkEntry:
        return next(f for f in self.frameworks if f.id == self.primary)

    def rules(self) -> frozenset[Rule]:
        return frozenset(
            Rule(f.id, gate, decision)
            for f in self.frameworks
            for gate, decision in f.retire
        )


@dataclass(frozen=True)
class SyncResult:
    outcome: SyncOutcome
    added: frozenset[Rule]
    removed: frozenset[Rule]
    rule_set_hash: str
    # Rules of frameworks the manifest does not list, left as they were.
    kept: frozenset[Rule] = frozenset()
    unlisted: tuple[str, ...] = ()
    # The primary before the sync, when the sync changed it.
    previous_primary: str | None = None


def canonical_json(value: object) -> bytes:
    """Sorted keys, no spaces, UTF-8: what scripts/build_app.py hashes."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def rule_set_hash(framework_id: str, pairs: frozenset[tuple[str, str]] | set) -> str:
    """SHA-256 of a framework's retirement rules, as scripts/build_manifest.py does."""
    rules = sorted([gate, decision] for gate, decision in pairs)
    return hashlib.sha256(
        canonical_json({"framework": framework_id, "retire": rules})
    ).hexdigest()


def _need(ok: bool, why: str) -> None:
    if not ok:
        raise ManifestError(why)


def _keys(
    obj: dict, required: set[str], where: str, optional: set[str] | None = None
) -> None:
    _need(isinstance(obj, dict), f"{where} is not an object")
    extra = set(obj) - required - (optional or set())
    missing = required - set(obj)
    _need(not missing, f"{where} lacks {sorted(missing)}")
    _need(not extra, f"{where} has unknown keys {sorted(extra)}")


VOCAB_KINDS = ("items", "gates", "statuses", "decisions")
# A word is a display word of a framework definition: an id, a status, an option such
# as "Proceed with conditions". 64 characters is longer than any of them.
MAX_VOCAB_WORD = 64
MAX_WORDS_PER_KIND = 5_000
MAX_WORDS_TOTAL = 50_000


def _unsafe_character(word: str) -> str | None:
    """The first character of ``word`` that no display word has: a control, format
    (zero-width, bidirectional), surrogate, private-use or unassigned character, or a
    line or paragraph separator. Spaces are fine ("Proceed with conditions")."""
    for ch in word:
        category = unicodedata.category(ch)
        if category[0] == "C" or category in {"Zl", "Zp"}:  # enum-ok: Unicode
            return f"U+{ord(ch):04X}"
    return None


def _vocab(raw: Any, where: str) -> tuple[tuple[str, frozenset[str]], ...]:
    """A framework's vocabulary, strictly: four lists of plain display words.

    This is a shape and safety filter, not a judgment of content: the manifest is build
    output and carries the authority of the framework definitions it is built from, so
    a poisoned one could put text in front of agents (D-89).
    """
    if raw is None:
        return ()
    _keys(raw, set(VOCAB_KINDS), where)
    out = []
    for kind in VOCAB_KINDS:
        words = raw[kind]
        _need(isinstance(words, list), f"{where}.{kind} is not a list")
        _need(
            len(words) <= MAX_WORDS_PER_KIND,
            f"{where}.{kind} lists {len(words)} words, more than {MAX_WORDS_PER_KIND}",
        )
        for word in words:
            _need(
                isinstance(word, str)
                and bool(word.strip())
                and word == word.strip()
                and len(word) <= MAX_VOCAB_WORD,
                f"{where}.{kind} holds {str(word)[:40]!r}, which is not a word "
                f"(text of 1 to {MAX_VOCAB_WORD} characters, no surrounding space)",
            )
            bad = _unsafe_character(word)
            _need(
                bad is None,
                f"{where}.{kind} holds {word[:40]!r}, which has the character {bad}, "
                "a control, zero-width, bidirectional or otherwise invisible one",
            )
        _need(len(set(words)) == len(words), f"{where}.{kind} lists a word twice")
        out.append((kind, frozenset(words)))
    return tuple(out)


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        raise ManifestError(f"the manifest repeats the key {dup[0]!r}")
    return dict(pairs)


def _id(value: Any, where: str) -> str:
    _need(
        isinstance(value, str) and bool(_ID.fullmatch(value)), f"{where} is not an id"
    )
    return value


def parse_manifest(text: str) -> Manifest:
    """Read and check a manifest. Strict: an unknown key, a bad id, a pair on a
    supplement, a primary that ends nothing or a hash that does not match its pairs
    is an error, because acting on a manifest misread is changing disposal."""
    try:
        raw = json.loads(text, object_pairs_hook=_no_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"the manifest is not JSON: {exc}") from exc
    _keys(raw, {"manifest", "primary", "frameworks", "ruleSetHash"}, "the manifest")
    _need(
        raw["manifest"] == MANIFEST_FORMAT and type(raw["manifest"]) is int,
        f"the manifest format is {raw['manifest']!r}, not {MANIFEST_FORMAT}",
    )
    primary = _id(raw["primary"], "primary")
    _need(
        isinstance(raw["frameworks"], list) and bool(raw["frameworks"]),
        "frameworks is not a non-empty list",
    )
    entries: list[FrameworkEntry] = []
    for i, f in enumerate(raw["frameworks"]):
        where = f"frameworks[{i}]"
        _keys(f, {"id", "role", "version", "sha256", "retire"}, where, {"vocab"})
        fid = _id(f["id"], f"{where}.id")
        try:
            role = FrameworkRole(f["role"])
        except ValueError as exc:
            raise ManifestError(f"{where}.role is {f['role']!r}") from exc
        _need(
            isinstance(f["version"], str) and bool(f["version"].strip()),
            f"{where}.version is not text",
        )
        _need(
            isinstance(f["sha256"], str) and bool(_SHA256.fullmatch(f["sha256"])),
            f"{where}.sha256 is not a SHA-256",
        )
        _need(isinstance(f["retire"], list), f"{where}.retire is not a list")
        pairs: set[tuple[str, str]] = set()
        for j, pair in enumerate(f["retire"]):
            at = f"{where}.retire[{j}]"
            _keys(pair, {"gate", "decision"}, at)
            gate = _id(pair["gate"], f"{at}.gate")
            decision = pair["decision"]
            _need(
                isinstance(decision, str)
                and bool(decision.strip())
                and len(decision) <= MAX_DECISION
                and not _CONTROL.search(decision),
                f"{at}.decision is not a decision",
            )
            _need((gate, decision) not in pairs, f"{at} is listed twice")
            pairs.add((gate, decision))
        if role is FrameworkRole.SUPPLEMENT:
            _need(not pairs, f"{where} is a supplement and cannot end a project")
        entries.append(
            FrameworkEntry(
                fid,
                role,
                f["version"],
                f["sha256"],
                frozenset(pairs),
                _vocab(f.get("vocab"), f"{where}.vocab"),
            )
        )
    total = sum(len(words) for e in entries for _, words in e.vocab)
    _need(
        total <= MAX_WORDS_TOTAL,
        f"the manifest lists {total} words, more than {MAX_WORDS_TOTAL}",
    )
    ids = [e.id for e in entries]
    _need(len(set(ids)) == len(ids), "a framework is listed twice")
    primaries = [e.id for e in entries if e.role is FrameworkRole.PRIMARY]
    _need(
        primaries == [primary],
        f"primary is {primary!r} but the primaries listed are {primaries}",
    )
    manifest = Manifest(primary, tuple(entries), raw["ruleSetHash"])
    _need(
        bool(manifest.primary_entry.retire),
        f"the primary framework {primary!r} has no decision that ends a project, so "
        "no record of it could ever come due for disposal (R-56)",
    )
    _need(
        raw["ruleSetHash"] == rule_set_hash(primary, manifest.primary_entry.retire),
        "ruleSetHash does not match the primary's retirement pairs",
    )
    return manifest


def load_manifest(path: str | None) -> Manifest:
    """The manifest at ``path``. Unset, missing or unreadable is an error."""
    if not path:
        raise ManifestError(
            "RETIREMENT_MANIFEST is not set. It names the build's manifest.json "
            "(compose mounts ${APP_DIR}/manifest.json), which says which decisions "
            "end a project; without it the server cannot know when disposal is due."
        )
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"cannot read the manifest {path}: {exc}") from exc
    return parse_manifest(text)


def _arrays(rules: frozenset[Rule]) -> tuple[list[str], list[str], list[str]]:
    ordered = sorted(rules)
    return (
        [r.framework_id for r in ordered],
        [r.gate_id for r in ordered],
        [r.decision for r in ordered],
    )


def _as_json(rules: frozenset[Rule]) -> list[list[str]]:
    return [list(r) for r in sorted(rules)]


async def affected_projects(
    conn: asyncpg.Connection, before: frozenset[Rule], after: frozenset[Rule]
) -> list[asyncpg.Record]:
    """Every live project whose retirement changes between the two rule sets, and
    whether disposal is due for it now and after, through the same retired_under()
    that retention_due() uses."""
    return await conn.fetch(
        """
        WITH keep AS (
            SELECT make_interval(years => record_years) AS k FROM retention_policy
        ),
        before AS (SELECT * FROM retired_under($1::text[], $2::text[], $3::text[])),
        after AS (SELECT * FROM retired_under($4::text[], $5::text[], $6::text[]))
        SELECT coalesce(b.project_id, a.project_id) AS project_id,
               coalesce(b.clock_start + keep.k <= now(), false) AS due_before,
               coalesce(a.clock_start + keep.k <= now(), false) AS due_after
          FROM before b
          FULL JOIN after a
            ON a.project_id = b.project_id AND a.incarnation = b.incarnation
         CROSS JOIN keep
         WHERE b.clock_start IS DISTINCT FROM a.clock_start
         ORDER BY 1
        """,
        *_arrays(before),
        *_arrays(after),
    )


class RuleState(NamedTuple):
    """What decides disposal: every rule the table holds, and the primary, whose
    stamp the API accepts."""

    primary: str | None
    rules: frozenset[Rule]


class DatabaseIdentity(NamedTuple):
    """What makes a database itself to an acknowledgment, read by 012's
    ``retirement_ack_database()``: none of it is in a dump, so neither another
    database nor a dump restored anywhere, in place too, shares it."""

    # The cluster's system identifier (pg_control_system()), as text.
    cluster: str
    # This database's OID.
    database: int
    # The OID of retirement_rule_change, which a restore in place recreates.
    history: int


class Follows(NamedTuple):
    """Where in which database's history a change starts: the database's identity,
    and the id and time of the latest ``retirement_rule_change`` row."""

    database: DatabaseIdentity
    # None only before 010's seed, which never happens once migrated.
    change_id: int | None
    at: str | None


def transition_ack(follows: Follows, before: RuleState, after: RuleState) -> str:
    """The value ``RETIREMENT_RULES_ACK`` must hold to make one change: SHA-256 of
    the canonical JSON (sorted keys, no spaces, UTF-8) ::

        {"database": {"cluster": <system identifier, text>,
                      "database": <the database's OID>,
                      "history": <the OID of retirement_rule_change>},
         "follows": <id of the latest retirement_rule_change row>,
         "at": <that row's time, UTC, "YYYY-MM-DDTHH:MM:SS.ffffffZ">,
         "before": {"primary": ..., "rules": [[framework, gate, decision], ...]},
         "after":  {"primary": ..., "rules": [...]}}

    with each rule list sorted. It binds the whole change the operator was shown:
    every row of ``retirement_rule`` before and after, of every framework, listed by
    the manifest or not, and the primary before and after. A different change
    between the same primary rule sets (a build that also drops an unlisted
    framework's rules) or a new primary over the same rows needs its own value. And
    because it names the history row it follows, which the change itself moves on,
    it is spent once used: a value left set never accepts a later change, even one
    identical to it. The database's identity (012) makes it one database's: another
    database refuses it, with the same history or restored from a dump of this one,
    and so does this database after a dump that creates the tables again is
    restored over it. A copy of the database's files (a base backup, a snapshot, a
    promoted replica) keeps the identity, and accepts a value printed against the
    state it was copied in, as does its original a value printed on the copy. So
    does a restore of the data alone into the existing tables (``--data-only``, or
    TRUNCATE and reload), which keeps the history table's OID.

    It binds the rules and the primary, not the records: the projects a refusal
    lists are those at the moment it was printed, and one edited before the
    acknowledged run is affected without having been listed.
    """
    return hashlib.sha256(
        canonical_json(
            {
                "database": follows.database._asdict(),
                "follows": follows.change_id,
                "at": follows.at,
                "before": {"primary": before.primary, "rules": _as_json(before.rules)},
                "after": {"primary": after.primary, "rules": _as_json(after.rules)},
            }
        )
    ).hexdigest()


async def database_identity(conn: asyncpg.Connection) -> DatabaseIdentity:
    """This database's identity, from 012's ``retirement_ack_database()``. If it
    cannot be read (a platform that withholds ``pg_control_system()``), no change
    can be acknowledged, so the change is refused and says why."""
    try:
        row = await conn.fetchrow("SELECT * FROM retirement_ack_database()")
    except asyncpg.PostgresError as exc:
        raise RulesRefused(
            "the manifest changes the retirement rules, and this database's identity "
            f"cannot be read ({exc}), so no acknowledgment can be bound to it. "
            "retirement_ack_database() needs pg_control_system(), which PostgreSQL "
            "grants to every role by default. Nothing was changed."
        ) from exc
    if row is None or None in tuple(row):
        raise RulesRefused(
            "the manifest changes the retirement rules, and this database's identity "
            "came back incomplete, so no acknowledgment can be bound to it. Nothing "
            "was changed."
        )
    return DatabaseIdentity(
        str(row["cluster"]), int(row["database"]), int(row["history"])
    )


def _refusal(
    added: frozenset[Rule],
    removed: frozenset[Rule],
    primaries: tuple[str | None, str],
    needed: str,
    affected: list,
) -> str:
    due_changes = [r for r in affected if r["due_before"] != r["due_after"]]
    old_primary, new_primary = primaries
    lines = [
        "the manifest changes the retirement rules the database holds:",
        *(
            f"  {r.framework_id}: checkpoint {r.gate_id} decided {r.decision!r} "
            f"({word})"
            for rules, word in ((added, "added"), (removed, "removed"))
            for r in sorted(rules)
        ),
        *(
            [
                f"  the primary changes: {old_primary} -> {new_primary} (the only "
                "framework a new record may be stamped with)"
            ]
            if old_primary != new_primary
            else []
        ),
        f"{len(affected)} live project(s) would change when they retire; "
        f"{len(due_changes)} would change whether disposal is due now:",
        *(
            f"  {r['project_id']}: "
            f"{'becomes due' if r['due_after'] else 'stops being due'} "
            f"(due now {r['due_before']} -> {r['due_after']})"
            for r in due_changes
        ),
        "Nothing was changed. If this build is meant to make exactly this change, run "
        "the migrate job again with "
        f"RETIREMENT_RULES_ACK={needed}",
        "It acknowledges this change from the rules as they stand now, once; clear it "
        "afterwards.",
    ]
    return "\n".join(lines)


class ActiveRules(NamedTuple):
    """The latest ``retirement_rule_change``: what the database retires by."""

    rule_set_hash: str
    primary: str
    source: ChangeSource
    change_id: int
    # Its time, UTC, as the acknowledgment states it (transition_ack).
    at: str


async def active_rules(conn: asyncpg.Connection) -> ActiveRules | None:
    """The latest change, or ``None`` before 010's seed (never, once migrated)."""
    row = await conn.fetchrow(
        "SELECT rule_set_hash, framework_id, source, id,"
        " to_char(at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')"
        " FROM retirement_rule_change ORDER BY id DESC LIMIT 1"
    )
    if row is None:
        return None
    return ActiveRules(row[0], row[1], ChangeSource(row[2]), row[3], row[4])


async def active_rule_set_hash(conn: asyncpg.Connection) -> str | None:
    """The rule-set hash of the latest change."""
    active = await active_rules(conn)
    return active.rule_set_hash if active else None


async def active_primary(conn: asyncpg.Connection) -> str:
    """The primary framework the latest sync recorded (010's seed: CHAI). The only
    framework a record may be stamped with through the API (R-66)."""
    active = await active_rules(conn)
    return active.primary if active else UNSTAMPED_FRAMEWORK


async def hold_off_rule_changes(conn: asyncpg.Connection) -> None:
    """Take the migration lock SHARED for the rest of the caller's transaction.

    :func:`sync_rules` takes it exclusively before it reads, so it waits for every
    write holding it to commit or roll back, and a write that asks for it while a
    sync (or a migration) holds it waits and then reads what that left. Writes do
    not block one another. A write takes it before any row or table lock, so a
    migration holding the lock never waits on a write that is waiting for it."""
    await conn.execute("SELECT pg_advisory_xact_lock_shared($1)", MIGRATION_LOCK_ID)


async def write_primary(conn: asyncpg.Connection) -> str:
    """The active primary, for a create, whose stamp check depends on it (R-66),
    read under :func:`hold_off_rule_changes`. Without it, under READ COMMITTED, a
    create that read the old primary could commit, after an acknowledged switch, a
    record the new primary forbids, which the acknowledgment never listed. A patch
    does not read the primary: it may not change the record's framework at all."""
    await hold_off_rule_changes(conn)
    return await active_primary(conn)


# --- the record's stamp (meta.framework) -----------------------------------------
# Whose rules a record follows is its stamp, so the stamp decides when it can be
# disposed of. A writer who could stamp any id could stamp one with no rules and keep
# a record forever, so the API accepts only the active primary's (R-66).

META_KEY = "meta"
STAMP_KEY = "framework"
STAMP_ID_KEY = "id"


def record_framework(doc: Any) -> str:
    """The framework whose rules a stored document follows, as 010's
    ``record_framework()`` reads it: ``meta.framework.id`` as text, or CHAI's when
    it is absent, null or empty."""
    meta = doc.get(META_KEY) if isinstance(doc, dict) else None
    stamp = meta.get(STAMP_KEY) if isinstance(meta, dict) else None
    value = stamp.get(STAMP_ID_KEY) if isinstance(stamp, dict) else None
    if value is None:
        return UNSTAMPED_FRAMEWORK
    text = value if isinstance(value, str) else json.dumps(value)
    return text or UNSTAMPED_FRAMEWORK


async def stored_frameworks(
    conn: asyncpg.Connection, *docs: dict[str, Any]
) -> list[str]:
    """The framework each document follows, read by 010's ``record_framework()``:
    the function ``retention_due()`` reads it with, so a write and retention never
    disagree about whose rules a record follows. ``conn`` encodes ``jsonb`` from a
    dict (``db._init_connection``)."""
    return list(
        await conn.fetchval(
            "SELECT array_agg(record_framework(d) ORDER BY n)"
            " FROM unnest($1::jsonb[]) WITH ORDINALITY AS u(d, n)",
            list(docs),
        )
    )


def sets_stamp(body: Any) -> bool:
    """Does a create or patch body set ``meta.framework`` (to anything, null too)?"""
    meta = body.get(META_KEY) if isinstance(body, dict) else None
    return isinstance(meta, dict) and STAMP_KEY in meta


def stamp_problem(document: Any, primary: str) -> str | None:
    """Why a document's stamp is not acceptable, or ``None`` when it is exactly
    ``{"id": <primary>}``."""
    stamp = document[META_KEY][STAMP_KEY]
    if isinstance(stamp, dict) and stamp == {STAMP_ID_KEY: primary}:
        return None
    return (
        f'meta.framework, when set, must be exactly {{"id": "{primary}"}}: the '
        "primary framework of the build this server retires by (R-66). It decides "
        "which decisions retire the record, and so when it can be disposed of. "
        + (
            "Leave it out and the record is CHAI's."
            if primary == UNSTAMPED_FRAMEWORK
            else "Under this primary a new record must carry it."
        )
    )


def describe_sync(synced: SyncResult, manifest: Manifest) -> str:
    """One line for the job's output (and the API's fallback log): what the sync did,
    and whose rules it left alone."""
    text = f"retirement rules {synced.outcome}"
    if synced.outcome is SyncOutcome.CHANGED:
        text += f" (+{len(synced.added)} -{len(synced.removed)}"
        if synced.previous_primary is not None:
            text += f", primary {synced.previous_primary} -> {manifest.primary}"
        text += ", acknowledged)"
    text += f"; rule set {synced.rule_set_hash} ({manifest.primary})"
    if synced.unlisted:
        counts = ", ".join(
            f"{fid} ({sum(r.framework_id == fid for r in synced.kept)} rule(s))"
            for fid in synced.unlisted
        )
        text += (
            "; rules of frameworks not listed by this manifest, left as they are: "
            f"{counts}. Their records keep retiring by them."
        )
    return text


async def sync_vocabulary(conn: asyncpg.Connection, manifest: Manifest) -> int:
    """Make ``agent_vocabulary`` the manifest's, wholesale; return the rows written.

    It decides only what an agent may be shown and nothing about disposal, so unlike
    the retirement rules it needs no acknowledgment and keeps no history: a build
    that lists fewer words simply shows agents fewer. A manifest with no vocabulary
    empties it, and an agent is then shown no item, checkpoint or status (D-89).
    """
    rows = [(f.id, "framework", f.role.value) for f in manifest.frameworks] + [
        (f.id, kind, word)
        for f in manifest.frameworks
        for kind, words in f.vocab
        for word in sorted(words)
    ]
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", MIGRATION_LOCK_ID)
        await conn.execute("DELETE FROM agent_vocabulary")
        await conn.executemany(
            "INSERT INTO agent_vocabulary (framework_id, kind, value) "
            "VALUES ($1, $2, $3)",
            rows,
        )
    return len(rows)


async def sync_rules(
    conn: asyncpg.Connection, manifest: Manifest, ack: str = ""
) -> SyncResult:
    """Make the rules of the frameworks the manifest lists say what it says.

    Runs as the owner in one transaction under the migration lock, so two migrate
    jobs cannot interleave and a refused sync changes nothing. A manifest governs
    only the frameworks it lists: rows of any other framework are left as they are
    (records of an earlier primary keep retiring by their own rules) and reported in
    ``SyncResult.unlisted``. Any change, an added pair, a removed one or a new
    primary, is refused unless ``ack`` is :func:`transition_ack` of exactly that
    change, read under the lock. Only a sync that changes nothing needs none.
    """
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", MIGRATION_LOCK_ID)
        current = frozenset(
            Rule(*r)
            for r in await conn.fetch(
                "SELECT framework_id, gate_id, decision FROM retirement_rule"
            )
        )
        listed = {f.id for f in manifest.frameworks}
        governed = frozenset(r for r in current if r.framework_id in listed)
        kept = current - governed
        desired = manifest.rules()
        added, removed = desired - governed, governed - desired
        after = kept | desired
        active = await active_rules(conn)
        old_hash = active.rule_set_hash if active else None
        old_primary = active.primary if active else None
        primary_changes = old_primary != manifest.primary
        changes = bool(added or removed) or primary_changes
        needed = ""
        if changes:
            database = await database_identity(conn)
            needed = transition_ack(
                Follows(database, active.change_id, active.at)
                if active
                else Follows(database, None, None),
                RuleState(old_primary, current),
                RuleState(manifest.primary, after),
            )
        if changes and ack != needed:
            affected = await affected_projects(conn, current, after)
            emit(
                SecurityEvent.RETIREMENT_RULES_REFUSED,
                f"retirement rules not changed: {len(added)} addition(s), "
                f"{len(removed)} removal(s) and primary {old_primary} -> "
                f"{manifest.primary} not acknowledged",
                framework=manifest.primary,
                active_primary=old_primary,
                added=_as_json(added),
                removed=_as_json(removed),
                projects=len(affected),
                rule_set_hash=manifest.rule_set_hash,
                active_rule_set_hash=old_hash,
            )
            raise RulesRefused(
                _refusal(
                    added, removed, (old_primary, manifest.primary), needed, affected
                )
            )
        unlisted = tuple(sorted({r.framework_id for r in kept}))
        same_active = (
            active is not None and active.rule_set_hash == manifest.rule_set_hash
        )
        if not changes and same_active and active.source is ChangeSource.MANIFEST:
            return SyncResult(
                SyncOutcome.UNCHANGED, added, removed, old_hash or "", kept, unlisted
            )
        # Otherwise there is something to record: a change (acknowledged above), or
        # the first manifest to confirm the seed, after which /api/health says the
        # rules are synced.
        for r in removed:
            await conn.execute(
                "DELETE FROM retirement_rule"
                " WHERE framework_id = $1 AND gate_id = $2 AND decision = $3",
                *r,
            )
        for r in added:
            await conn.execute(
                "INSERT INTO retirement_rule (framework_id, gate_id, decision)"
                " VALUES ($1, $2, $3)",
                *r,
            )
        await conn.execute(
            "INSERT INTO retirement_rule_change (source, framework_id, old_rules,"
            " new_rules, rule_set_hash, definition_hash, acknowledged)"
            " VALUES ($1, $2, $3::text::jsonb, $4::text::jsonb, $5, $6, $7)",
            ChangeSource.MANIFEST.value,
            manifest.primary,
            json.dumps(_as_json(current)),
            json.dumps(_as_json(after)),
            manifest.rule_set_hash,
            manifest.primary_entry.sha256,
            changes,
        )
    outcome = SyncOutcome.CHANGED if changes else SyncOutcome.CONFIRMED
    emit(
        SecurityEvent.RETIREMENT_RULES_CHANGED,
        f"retirement rules {outcome}: {len(added)} added, {len(removed)} removed",
        framework=manifest.primary,
        active_primary=old_primary,
        added=_as_json(added),
        removed=_as_json(removed),
        unlisted=list(unlisted),
        acknowledged=changes,
        rule_set_hash=manifest.rule_set_hash,
        active_rule_set_hash=old_hash,
    )
    return SyncResult(
        outcome,
        added,
        removed,
        manifest.rule_set_hash,
        kept,
        unlisted,
        old_primary if primary_changes else None,
    )
