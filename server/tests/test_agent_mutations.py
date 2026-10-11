"""Every guard on the agent API is shown to fail (#164, R-71).

A guard nobody has seen fail is a claim, not a control (CLAUDE.md). Each case here
breaks one thing in a COPY of the server, on a scratch database, the way a careless
edit or a plausible refactor would, and demands that ``test_agent_api.py`` notices by
failing the test that names that guard. The copy is never the real tree.

The first case breaks nothing: if the harness cannot pass an unbroken copy, a
"failure" below would prove nothing.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest

from .conftest import DB_URL, requires_db

pytestmark = [requires_db, pytest.mark.db]

SERVER = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Mutant:
    name: str
    path: str  # relative to server/
    old: str
    new: str
    # Tests of test_agent_api.py, any one of which must fail because of this break.
    caught_by: tuple[str, ...]
    append: str = ""  # added to the end of the file instead of replacing text
    suite: str = "tests/test_agent_api.py"
    count: int = 0  # how many times `old` must occur (0: at least once)
    extra: tuple[tuple[str, str, str], ...] = field(default=())


MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        "a bearer is accepted on a session route",
        "app/routes.py",
        "    identity = identity_from_request(request, settings)\n    recorder",
        "    if request.headers.get('authorization') and not request.headers.get(\n"
        "        settings.identity_header\n    ):\n"
        "        return Identity(id='agent', name='', email='')\n"
        "    identity = identity_from_request(request, settings)\n    recorder",
        (
            "test_a_bearer_alone_authenticates_nobody_on_any_other_route",
            "test_a_token_cannot_mint_list_or_revoke_tokens",
            "test_the_session_identity_never_reads_a_bearer",
        ),
    ),
    Mutant(
        "the archived filter is skipped",
        "app/agent.py",
        'not (row["doc"] or {}).get("archived")',
        "True",
        (
            "test_an_archived_project_is_never_returned_by_any_route",
            "test_a_token_sees_exactly_the_projects_its_users_dashboard_lists",
        ),
    ),
    Mutant(
        "the access lists are not enforced",
        "app/agent.py",
        "readable_rows(conn, caller.user_id, enforced=True)",
        "readable_rows(conn, caller.user_id, enforced=False)",
        ("test_a_token_sees_exactly_the_projects_its_users_dashboard_lists",),
    ),
    Mutant(
        "a token is given its user's emergency access",
        "app/agent.py",
        "readable_rows(conn, caller.user_id, enforced=True)",
        "readable_rows(\n            conn,\n            caller.user_id,\n            enforced=True,\n"
        "            emergency=caller.user_id in settings.emergency_access_ids,\n        )",
        ("test_an_emergency_user_gets_no_emergency_access_through_a_token",),
    ),
    Mutant(
        "a person is shown by identity, not an opaque id",
        "app/agent.py",
        "opaque_id(secret, value) if isinstance(value, str) and value else None",
        "value if isinstance(value, str) and value else None",
        (
            "test_nothing_hostile_planted_anywhere_reaches_an_agent",
            "test_statuses_decisions_dates_and_people_are_the_stored_ones",
        ),
    ),
    Mutant(
        "a call is not written to the read trail",
        "app/agent.py",
        "await record_access(",
        "await _skip(",
        (
            "test_every_agent_call_is_in_the_read_trail_marked_as_agent_access",
            "test_refused_calls_are_recorded_and_say_why_to_the_operator_only",
            "test_the_portfolio_entry_lists_the_ids_that_were_returned",
        ),
        append="\n\nasync def _skip(*args, **kwargs):\n    return None\n",
    ),
    Mutant(
        "an agent call is recorded as a session read",
        "app/agent.py",
        "via=AccessVia.AGENT",
        "via=AccessVia.SESSION",
        ("test_every_agent_call_is_in_the_read_trail_marked_as_agent_access",),
    ),
    Mutant(
        "expiry is not checked",
        "app/agent_tokens.py",
        'if row["expires_at"] <= now:',
        "if False:",
        (
            "test_a_token_works_until_the_eighth_hour_and_not_after",
            "test_every_bad_token_gets_the_same_401",
        ),
    ),
    Mutant(
        "revocation is not checked",
        "app/agent_tokens.py",
        '    if row["revoked_at"] is not None:\n        return Verified(None, Refusal.REVOKED',
        "    if False:\n        return Verified(None, Refusal.REVOKED",
        (
            "test_you_can_list_and_revoke_only_your_own",
            "test_every_bad_token_gets_the_same_401",
        ),
    ),
    Mutant(
        "the secret is compared with ==",
        "app/agent_tokens.py",
        "hmac.compare_digest(stored, hash_token(presented.token))",
        "stored == hash_token(presented.token)",
        ("test_tokens_are_compared_in_constant_time_and_only_there",),
    ),
    Mutant(
        "the lifetime is not 8 hours",
        "app/agent_tokens.py",
        "TOKEN_LIFETIME = timedelta(hours=8)",
        "TOKEN_LIFETIME = timedelta(hours=9)",
        ("test_a_minted_token_has_the_shape_and_the_fixed_lifetime",),
    ),
    Mutant(
        "the identity header is honored on an agent route",
        "app/agent.py",
        '    presented = parse_bearer(request.headers.get("authorization"))\n'
        "    async with db.acquire() as conn:\n        verified",
        '    presented = parse_bearer(request.headers.get("authorization"))\n'
        "    if presented.token is None and request.headers.get(settings.identity_header):\n"
        "        return AgentCaller(\n            '0' * 16,\n"
        "            request.headers[settings.identity_header],\n"
        "            now_of(request).replace(year=2999),\n        )\n"
        "    async with db.acquire() as conn:\n        verified",
        ("test_the_identity_header_means_nothing_on_an_agent_route",),
    ),
    Mutant(
        "an expired token is told apart from a wrong one",
        "app/agent.py",
        "    raise _unauthorized()\n\n\ndef _as_identity",
        "    if verified.refusal.value == 'expired':\n"
        "        raise HTTPException(401, 'This token has expired.')\n"
        "    raise _unauthorized()\n\n\ndef _as_identity",
        ("test_every_bad_token_gets_the_same_401",),
    ),
    Mutant(
        "overdue includes today",
        "app/agent.py",
        "overdue=due is not None and due < today,",
        "overdue=due is not None and due <= today,",
        ("test_overdue_is_a_date_comparison_and_nothing_else",),
    ),
    Mutant(
        "the page size is not capped",
        "app/agent.py",
        "MAX_LIMIT = 100",
        "MAX_LIMIT = 100_000",
        ("test_pagination_pages_without_gaps_or_repeats_and_is_capped",),
    ),
    Mutant(
        "an agent route takes a write verb",
        "app/agent.py",
        "# --- minting, listing and revoking",
        "@agent_router.post('/me')\nasync def _write(\n"
        "    caller: AgentCaller = Depends(get_agent),\n) -> dict:\n    return {}\n\n\n"
        "# --- minting, listing and revoking",
        ("test_the_agent_routes_are_read_only",),
    ),
    Mutant(
        "the count of live tokens is not enforced",
        "app/agent_tokens.py",
        "if live >= max_active:",
        "if False:",
        (
            "test_a_person_holds_at_most_five_live_tokens",
            "test_the_limit_is_a_setting",
        ),
    ),
    Mutant(
        "a person can revoke another's token",
        "app/agent_tokens.py",
        '"SELECT revoked_at FROM agent_token WHERE token_id = $1 AND principal_id = $2 "',
        '"SELECT revoked_at FROM agent_token WHERE token_id = $1 AND $2::text IS NOT NULL "',
        ("test_you_can_list_and_revoke_only_your_own",),
    ),
    Mutant(
        "a token outlives its principal",
        "migrations/013_agent_tokens.sql",
        "REFERENCES principals (id) ON DELETE CASCADE",
        "REFERENCES principals (id)",
        (
            "test_a_token_is_deleted_with_its_principal_and_stops_working",
            "test_disposing_of_a_principal_takes_their_tokens_with_it",
        ),
    ),
    Mutant(
        "the database accepts any lifetime",
        "migrations/013_agent_tokens.sql",
        "CHECK (expires_at = created_at + interval '8 hours')",
        "CHECK (true)",
        ("test_the_database_refuses_any_other_lifetime",),
    ),
    Mutant(
        "a token's label can be rewritten",
        "migrations/013_agent_tokens.sql",
        "       OR NEW.label IS DISTINCT FROM OLD.label\n",
        "",
        ("test_a_tokens_identity_and_expiry_cannot_be_rewritten",),
    ),
    Mutant(
        "a revoked token can be revived",
        "migrations/013_agent_tokens.sql",
        "    IF OLD.revoked_at IS NOT NULL\n",
        "    IF false AND OLD.revoked_at IS NOT NULL\n",
        ("test_a_tokens_identity_and_expiry_cannot_be_rewritten",),
    ),
    Mutant(
        "a documented response field is renamed",
        "../docs/agent-api.md",
        "| `has_overdue` | boolean | True when any item is overdue. |",
        "| `has_overdue_soon` | boolean | True when any item is overdue. |",
        ("test_the_documented_response_fields_are_the_models_exactly",),
        suite="tests/test_agent_docs.py",
    ),
    Mutant(
        "a model field is added and not documented",
        "app/agent.py",
        '    due: date | None = Field(description="The stored due date; null when none.")\n',
        '    due: date | None = Field(description="The stored due date; null when none.")\n'
        "    note: str | None = None\n",
        ("test_the_documented_response_fields_are_the_models_exactly",),
        suite="tests/test_agent_docs.py",
    ),
    Mutant(
        "a documented status code is one the route cannot return",
        "../docs/agent-api.md",
        "| `409` | You already hold the most live tokens allowed. |",
        "| `409` | You already hold the most live tokens allowed. |\n| `418` | A teapot. |",
        (
            "test_the_documented_status_codes_are_the_routes",
            "test_every_documented_status_is_one_the_route_returns",
        ),
        suite="tests/test_agent_docs.py",
    ),
    Mutant(
        "a documented query parameter does not exist",
        "../docs/agent-api.md",
        "| `limit` | integer | Page size, 1 to 100. Default 50. |",
        "| `limit` | integer | Page size, 1 to 100. Default 50. |\n| `sort` | string | Order. |",
        ("test_the_documented_query_parameters_are_the_routes",),
        suite="tests/test_agent_docs.py",
    ),
    Mutant(
        "a documented curl command no longer works",
        "../docs/agent-api.md",
        "portfolio?status=notmet&overdue=true&limit=20",
        "portfolio?status=notmet&overdue=maybe&limit=20",
        ("test_every_documented_curl_command_works_as_documented",),
        suite="tests/test_agent_docs.py",
    ),
    Mutant(
        "a documented curl command sends an identity header",
        "../docs/agent-api.md",
        'curl -sS "$BASE/api/agent/me" -H "Authorization: Bearer $TOKEN"\n```\n\nAll',
        'curl -sS "$BASE/api/agent/me" -H "Authorization: Bearer $TOKEN" -H "X-Forwarded-Email: a@b.org"\n```\n\nAll',
        ("test_every_documented_curl_command_works_as_documented",),
        suite="tests/test_agent_docs.py",
    ),
    Mutant(
        "an example response has a field the model lacks",
        "../docs/agent-api.md",
        '  "token_id": "7d3f9a1c5b2e4f60",',
        '  "token_id": "7d3f9a1c5b2e4f60",\n  "name": "Dr. A",',
        ("test_the_example_responses_fit_their_models",),
        suite="tests/test_agent_docs.py",
    ),
    Mutant(
        "the page names a client",
        "../docs/agent-api.md",
        "A read-only way for a program",
        "A read-only way for Claude, a program",
        ("test_the_page_names_no_client_and_no_model",),
        suite="tests/test_agent_docs.py",
    ),
    Mutant(
        "the page states another default limit",
        "../docs/agent-api.md",
        "| `AGENT_RATE_LIMIT_MAX_REQUESTS` | `60` |",
        "| `AGENT_RATE_LIMIT_MAX_REQUESTS` | `30` |",
        ("test_the_limits_on_the_page_are_the_codes",),
        suite="tests/test_agent_docs.py",
    ),
    Mutant(
        "the archived filter is skipped on one project",
        "app/agent.py",
        '            if (row["doc"] or {}).get("archived"):\n                continue',
        "            if False:\n                continue",
        ("test_an_archived_project_is_never_returned_by_any_route",),
    ),
    Mutant(
        "an item id is returned whatever it says",
        "app/agent.py",
        "for k in answers if vocab.item(framework_id, k)",
        "for k in answers if isinstance(k, str)",
        (
            "test_a_key_a_writer_chose_never_reaches_an_agent",
            "test_nothing_hostile_planted_anywhere_reaches_an_agent",
        ),
    ),
    Mutant(
        "a checkpoint id is returned whatever it says",
        "app/agent.py",
        "for k in gates if vocab.gate(framework_id, k)",
        "for k in gates if isinstance(k, str)",
        ("test_a_key_a_writer_chose_never_reaches_an_agent",),
    ),
    Mutant(
        "a supplement key is returned whatever it says",
        "app/agent.py",
        "for key in sorted(k for k in doc if vocab.role(k) is FrameworkRole.SUPPLEMENT):",
        "for key in sorted(k for k in doc if isinstance(k, str)):",
        ("test_a_key_a_writer_chose_never_reaches_an_agent",),
    ),
    Mutant(
        "a status is returned whatever it says",
        "app/agent.py",
        "return value if self._has(framework_id, VocabKind.STATUSES, value) else None",
        "return value if isinstance(value, str) else None",
        (
            "test_nothing_hostile_planted_anywhere_reaches_an_agent",
            "test_a_builds_own_words_pass_and_the_published_ones_do_not_cross_over",
        ),
    ),
    Mutant(
        "a decision is returned whatever it says",
        "app/agent.py",
        "return value if self._has(framework_id, VocabKind.DECISIONS, value) else None",
        "return value if isinstance(value, str) else None",
        (
            "test_nothing_hostile_planted_anywhere_reaches_an_agent",
            "test_a_builds_own_words_pass_and_the_published_ones_do_not_cross_over",
        ),
    ),
    Mutant(
        "an item is read against another framework's words",
        "app/agent.py",
        "        return self._has(framework_id, VocabKind.ITEMS, key)",
        "        return any(k == VocabKind.ITEMS.value and key == w for (_, k), ws in self._words.items() for w in ws)",
        ("test_a_builds_own_words_pass_and_the_published_ones_do_not_cross_over",),
    ),
    Mutant(
        "a project is shown by its own id",
        "app/agent.py",
        'ref=project_ref(secret, row["id"]),',
        'ref=row["id"],',
        (
            "test_a_key_a_writer_chose_never_reaches_an_agent",
            "test_a_project_ref_is_stable_keyed_and_resolves_only_what_is_visible",
        ),
    ),
    Mutant(
        "no vocabulary is read, so everything shows",
        "app/agent.py",
        '        rows = await conn.fetch(\n            "SELECT framework_id, kind, value FROM agent_vocabulary"\n        )',
        "        rows = []",
        ("test_a_builds_own_words_pass_and_the_published_ones_do_not_cross_over",),
    ),
    Mutant(
        "the per-token limit is not applied",
        "app/agent.py",
        "if not await guard.allow_token(verified.caller.token_id):",
        "if False:",
        ("test_an_agent_token_has_its_own_lower_limit",),
    ),
    Mutant(
        "the failure bucket is not applied",
        "app/agent.py",
        "if not guard.charge_failure(source):",
        "if not (guard.charge_failure(source) or True):",
        (
            "test_a_flood_of_bad_tokens_writes_nothing_and_never_blocks_a_real_token",
            "test_the_source_is_the_peer_and_not_a_header_a_client_chooses",
        ),
    ),
    Mutant(
        "a failure names a token and spends its allowance",
        "app/agent.py",
        "    source = client_address(request, settings)\n",
        "    source = client_address(request, settings)\n"
        "    if presented.token_id:\n"
        "        await guard.per_token.allow(presented.token_id)\n",
        (
            "test_nobody_can_spend_another_tokens_allowance_by_naming_it",
            "test_the_per_token_limit_counts_only_requests_that_verified",
        ),
    ),
    Mutant(
        "an unknown token is a trail row",
        "app/agent.py",
        "        verified.known_id\n        and presented.token_id\n",
        "        presented.token_id\n",
        (
            "test_a_flood_of_bad_tokens_writes_nothing_and_never_blocks_a_real_token",
            "test_only_a_token_that_exists_leaves_a_trail_row_when_refused",
        ),
    ),
    Mutant(
        "a known token's refusals are unbounded rows",
        "app/agent.py",
        "        and await guard.may_write_row(presented.token_id, source)\n",
        "",
        (
            "test_a_flood_of_bad_tokens_writes_nothing_and_never_blocks_a_real_token",
            "test_nobody_can_spend_another_tokens_allowance_by_naming_it",
        ),
    ),
    Mutant(
        "the source is taken from X-Forwarded-For",
        "app/agent.py",
        "    source = client_address(request, settings)\n",
        "    source = request.headers.get('x-forwarded-for') or client_address(\n"
        "        request, settings\n    )\n",
        ("test_the_source_is_the_peer_and_not_a_header_a_client_chooses",),
    ),
    Mutant(
        "X-Real-IP is believed from any peer",
        "app/auth.py",
        "    if not peer or not settings.trusted_proxy_cidrs:\n        return peer",
        "    if not peer:\n        return peer",
        (
            "test_the_source_is_the_peer_and_not_a_header_a_client_chooses",
            "test_the_proxys_address_is_believed_only_inside_the_trusted_range",
        ),
        extra=(
            (
                "app/auth.py",
                "    if not any(ip in net for net in _networks(settings.trusted_proxy_cidrs)):\n        return peer",
                "    if False:\n        return peer",
            ),
        ),
    ),
    Mutant(
        "X-Real-IP is believed from a peer outside the range",
        "app/auth.py",
        "    if not any(ip in net for net in _networks(settings.trusted_proxy_cidrs)):\n        return peer",
        "    if False:\n        return peer",
        ("test_the_proxys_address_is_believed_only_inside_the_trusted_range",),
    ),
    Mutant(
        "a token is accepted from a query parameter",
        "app/agent.py",
        '    presented = parse_bearer(request.headers.get("authorization"))\n    async with db.acquire() as conn:\n        verified',
        '    presented = parse_bearer(\n        request.headers.get("authorization")\n        or "Bearer " + request.query_params.get("token", "")\n    )\n    async with db.acquire() as conn:\n        verified',
        ("test_the_token_comes_from_the_authorization_header_and_nowhere_else",),
    ),
    Mutant(
        "a use is noted on every token",
        "app/agent.py",
        '"UPDATE agent_token SET last_used_at = $2 WHERE token_id = $1",',
        '"UPDATE agent_token SET last_used_at = $2 WHERE $1::text IS NOT NULL",',
        ("test_using_a_token_notes_that_token_and_no_other",),
    ),
    Mutant(
        "a repeated-pattern secret is accepted",
        "app/config.py",
        "        if value == (value[:period] * len(value))[: len(value)]:",
        "        if False:",
        ("test_a_weak_secret_stops_the_server_starting",),
    ),
    Mutant(
        "a low-variety secret is accepted",
        "app/config.py",
        "    if len(set(value)) < AGENT_ID_SECRET_MIN_DISTINCT:",
        "    if False:",
        ("test_a_weak_secret_stops_the_server_starting",),
    ),
    Mutant(
        "the access log keeps an agent query string",
        "app/securitylog.py",
        "            if mark and path.startswith(self.PREFIX):",
        "            if False:",
        (
            "test_the_access_log_does_not_keep_a_query_on_an_agent_route",
            "test_a_token_sent_in_a_url_is_refused_and_not_logged_by_the_server",
        ),
    ),
    Mutant(
        "loading the words does not replace the old ones",
        "app/retirement.py",
        '        await conn.execute("DELETE FROM agent_vocabulary")',
        '        await conn.execute("SELECT 1")',
        ("test_loading_replaces_the_table_wholesale",),
        suite="tests/test_agent_vocabulary.py",
    ),
    Mutant(
        "the migrate job does not load the words",
        "app/migrate.py",
        "            words = await sync_vocabulary(conn, manifest)",
        "            words = 0",
        ("test_the_migrate_job_loads_the_words_from_the_manifest",),
        suite="tests/test_agent_vocabulary.py",
    ),
    Mutant(
        "the server accepts a word twice",
        "app/retirement.py",
        '        _need(len(set(words)) == len(words), f"{where}.{kind} lists a word twice")',
        "        pass",
        ("test_the_server_reads_the_words_strictly",),
        suite="tests/test_agent_vocabulary.py",
    ),
    Mutant(
        "a mint needs no signed-in person",
        "app/agent.py",
        "    if identity.id in NOT_PEOPLE or not settings.require_identity:",
        "    if False:",
        ("test_minting_needs_a_person_not_an_anonymous_request",),
    ),
)


def _copy_server(into: Path) -> Path:
    for name in (
        "docs/app/manifest.json",
        "scripts/build_manifest.py",
        "scripts/framework_enums.py",
    ):
        (into / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(SERVER.parent / name, into / name)
    for name in ("docs/agent-api.md", "zensical.toml", ".env.example", "compose.yaml"):
        (into / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(SERVER.parent / name, into / name)
    target = into / "server"
    shutil.copytree(
        SERVER,
        target,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
    )
    # The tests read a few things beside server/: the framework definitions.
    shutil.copytree(
        SERVER.parent / "app" / "frameworks",
        into / "app" / "frameworks",
        ignore=shutil.ignore_patterns("*.js"),
    )
    return target


def _scratch_url(name: str) -> str:
    parts = urlsplit(DB_URL)
    return urlunsplit(parts._replace(path=f"/{name}"))


async def _with_scratch_database(run):
    name = "agent_mut_" + uuid.uuid4().hex[:10]
    admin = await asyncpg.connect(DB_URL)
    try:
        await admin.execute(f'CREATE DATABASE "{name}"')
        return await run(_scratch_url(name))
    finally:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.close()


def _pytest(
    tree: Path, url: str, names: tuple[str, ...], suites: tuple[str, ...]
) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in {"TEST_APP_ROLE"}}
    env.update(TEST_DATABASE_URL=url, REQUIRE_TESTS="1", PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-rf",
            "-p",
            "no:cacheprovider",
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


async def test_the_harness_passes_an_unbroken_copy() -> None:
    """The control. Without it a failure below could be the harness failing."""

    async def run(url: str):
        with tempfile.TemporaryDirectory() as tmp:
            tree = _copy_server(Path(tmp))
            return await asyncio.to_thread(_pytest, tree, url, ALL_NAMES, SUITES)

    done = await _with_scratch_database(run)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-1000:]
    assert re.search(r"\b\d+ passed\b", done.stdout) and "failed" not in done.stdout


@pytest.mark.parametrize("mutant", MUTANTS, ids=[m.name for m in MUTANTS])
async def test_each_guard_is_noticed_when_broken(mutant: Mutant) -> None:
    async def run(url: str):
        with tempfile.TemporaryDirectory() as tmp:
            tree = _copy_server(Path(tmp))
            target = tree / mutant.path
            text = target.read_text(encoding="utf-8")
            assert mutant.old in text or mutant.append, f"{mutant.name}: text not found"
            if mutant.old in text:
                occurrences = text.count(mutant.old)
                if mutant.count:
                    assert occurrences == mutant.count
                text = text.replace(mutant.old, mutant.new)
            text += mutant.append
            assert text != target.read_text(encoding="utf-8")
            target.write_text(text, encoding="utf-8")
            for path, old, new in mutant.extra:
                other = tree / path
                body = other.read_text(encoding="utf-8")
                assert old in body, f"{mutant.name}: {path}: text not found"
                other.write_text(body.replace(old, new), encoding="utf-8")
            return await asyncio.to_thread(
                _pytest, tree, url, mutant.caught_by, (mutant.suite,)
            )

    done = await _with_scratch_database(run)
    failed = re.findall(r"^FAILED tests/test_agent_\w+\.py::(\w+)", done.stdout, re.M)
    assert done.returncode == 1, (
        f"breaking {mutant.name!r} was not noticed:\n{done.stdout[-2500:]}"
    )
    assert set(failed) & set(mutant.caught_by), (
        f"breaking {mutant.name!r} failed {failed}, not any of {mutant.caught_by}:\n"
        f"{done.stdout[-2500:]}"
    )
