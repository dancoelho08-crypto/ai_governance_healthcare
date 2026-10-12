#!/usr/bin/env python3
"""End-to-end checks against a running Docker Compose stack.

Verifies the properties that only exist once the real stack is up: the browser
selects ApiStore, identity comes from the proxy and cannot be forged, writes
reach PostgreSQL, and a change made elsewhere arrives over SSE.

Start the stack first, then:

    docker compose up -d --build
    pixi run test-stack

Skips cleanly (exit 0) when nothing is listening, so it is safe in CI without
Docker.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# STACK_URL lets two stacks on one machine (two worktrees) use different ports.
BASE = os.environ.get("STACK_URL", "http://localhost:8080")

# CI sets REQUIRE_TESTS=1. A suite that cannot run then FAILS instead of
# skipping, because a skip exits 0 and reads as a pass: that is how CI once
# reported green while running none of these tests (#32).
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))


def http(path: str, method: str = "GET", body: dict | None = None) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def stack_up() -> bool:
    try:
        return http("/api/health")[0] == 200
    except Exception:
        return False


def wait_until(page, expression: str, timeout: float = 20.0) -> None:
    """Poll until a page expression is truthy, or raise.

    NOT page.wait_for_function: that evaluates its argument with the page's own
    `eval`, which the Content-Security-Policy this stack serves
    (`script-src` is a hash of the page's script, deliberately no `unsafe-eval`)
    forbids. This
    suite broke the day that policy shipped and nobody noticed, because CI did not
    run it (#32). `page.evaluate` goes through the debugging protocol instead, so
    the app is still tested under the policy it actually ships with.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate(expression):
            return
        page.wait_for_timeout(200)
    raise TimeoutError(f"still false after {timeout}s: {expression}")


def compose_exec(service: str, *command: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", service, *command],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout if result.returncode == 0 else ""


def container_facts() -> dict[str, dict]:
    """What the running containers were actually started with, by service.

    Read with `docker inspect`, so it is what the daemon applied, not what the
    compose file said it wanted.
    """
    out = subprocess.run(
        ["docker", "compose", "ps", "-a", "-q"], capture_output=True, text=True
    ).stdout.split()
    facts: dict[str, dict] = {}
    for cid in out:
        raw = subprocess.run(
            ["docker", "inspect", cid], capture_output=True, text=True
        ).stdout
        info = json.loads(raw)[0]
        host = info["HostConfig"]
        service = info["Config"]["Labels"].get("com.docker.compose.service", cid)
        facts[service] = {
            "user": info["Config"].get("User"),
            "cap_drop": host.get("CapDrop"),
            "cap_add": host.get("CapAdd"),
            "read_only": host.get("ReadonlyRootfs"),
            "security_opt": host.get("SecurityOpt"),
            "memory": host.get("Memory"),
            "exit": info["State"].get("ExitCode"),
        }
    return facts


def compose_exec_all(service: str, *command: str) -> str:
    """Like compose_exec, but returns stdout AND stderr whatever the exit code."""
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", service, *command],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout + result.stderr


def proxy_log() -> str:
    done = subprocess.run(
        ["docker", "compose", "logs", "--no-color", "proxy"],
        capture_output=True,
        text=True,
    )
    return (done.stdout + done.stderr).lower()


def direct_api_status(headers: dict[str, str]) -> int:
    """GET /api/me straight at the API, from inside the proxy's network namespace.

    The API publishes no port, so the only way to reach it without Caddy is from
    a container on its network. Sharing the proxy's namespace gives the request
    the proxy's address, which TRUSTED_PROXY_CIDR accepts, so a 403 can only be
    the shared-secret check.
    """

    def out(*argv: str) -> str:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        return done.stdout.strip()

    proxy = out("docker", "compose", "ps", "-q", "proxy")
    image = out(
        "docker",
        "inspect",
        "-f",
        "{{.Config.Image}}",
        out("docker", "compose", "ps", "-q", "api"),
    )
    script = (
        "import json, sys, urllib.error, urllib.request\n"
        "req = urllib.request.Request('http://api:8000/api/me',"
        " headers=json.loads(sys.argv[1]))\n"
        "try:\n"
        "    print(urllib.request.urlopen(req, timeout=10).status)\n"
        "except urllib.error.HTTPError as e:\n"
        "    print(e.code)\n"
    )
    code = out(
        "docker", "run", "--rm", "--network", f"container:{proxy}",
        "--entrypoint", "python", image, "-c", script, json.dumps(headers),
    )  # fmt: skip
    return int(code) if code.isdigit() else -1


def main() -> int:
    if not stack_up():
        print("stack not running at " + BASE + " - skipping")
        print("  start it with: docker compose up -d --build")
        return 1 if REQUIRE_TESTS else 0

    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
        if not ok:
            failures.append(name)

    print("API")
    status, body = http("/api/health")
    check("health reports ok", json.loads(body).get("status") == "ok", body)
    # The migrate service loaded the retirement rules from the manifest beside the
    # page the proxy serves (compose's APP_DIR, D-76), and the API reports that rule
    # set: the database retires by the build's own definition.
    manifest = json.loads(
        (Path(__file__).resolve().parent.parent / "docs" / "app" / "manifest.json")
        .read_text(encoding="utf-8")
    )  # fmt: skip
    # What this proves is the default build: its rule set is 010's seed (same hash),
    # so the hash alone would match even if no sync ran. `synced` shows the migrate
    # job read the manifest and confirmed it. That a different rule set is loaded,
    # refused or acknowledged is server/tests' evidence (C-88).
    check(
        "the database retires by the served build's rule set, synced from it",
        json.loads(body).get("retirement_rules")
        == {
            "hash": manifest["ruleSetHash"],
            "primary": manifest["primary"],
            "synced": True,
        },
        body,
    )
    _, served = http("/manifest.json")
    check(
        "and it is the manifest the proxy serves beside the page",
        json.loads(served or "{}").get("ruleSetHash") == manifest["ruleSetHash"],
        served[:200],
    )

    # Identity must come from the proxy, never from the client.
    _, me = http("/api/me")
    baseline = json.loads(me)
    req = urllib.request.Request(
        BASE + "/api/me",
        headers={
            "X-Auth-Request-Email": "ceo@hospital.org",
            "X-Goog-Authenticated-User-Email": "attacker@evil.com",
            "X-Amzn-Oidc-Identity": "attacker@evil.com",
            "X-Ms-Client-Principal-Name": "attacker@evil.com",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        forged = json.loads(r.read().decode())
    check(
        "forged identity headers are stripped",
        forged == baseline,
        f"{forged} != {baseline}",
    )

    # Deep merge must preserve siblings at every level, and replace arrays.
    pid = "t-" + uuid.uuid4().hex[:8]
    status, _ = http(
        f"/api/projects/{pid}",
        "POST",
        {
            "meta": {"solution": "merge test"},
            "items": {"a": {"status": "met"}, "b": {"status": "partial"}},
            "metrics": [{"name": "old"}],
        },
    )
    check("create returns 201", status == 201, str(status))
    check(
        "duplicate create returns 409",
        http(f"/api/projects/{pid}", "POST", {})[0] == 409,
    )

    http(
        f"/api/projects/{pid}",
        "PATCH",
        {"items": {"a": {"owner": "Alice"}}, "metrics": [{"name": "new"}]},
    )
    _, body = http("/api/projects")
    doc = next(p for p in json.loads(body) if p["id"] == pid)
    check(
        "nested sibling key preserved",
        doc["items"]["a"] == {"status": "met", "owner": "Alice"},
        str(doc["items"]["a"]),
    )
    check("sibling object untouched", doc["items"]["b"] == {"status": "partial"})
    check(
        "arrays replace, not merge",
        doc["metrics"] == [{"name": "new"}],
        str(doc["metrics"]),
    )

    # Who signed a checkpoint is the server's to say, not the client's (#31). Sent
    # through the real proxy to the real API: the identity comes from Caddy, so
    # this is the only place the two halves are tested together.
    forged = "cmo@hospital.example"
    forged_at = "2026-01-15T09:00:00.000Z"
    sid = "t-" + uuid.uuid4().hex[:8]
    http(f"/api/projects/{sid}", "POST", {"meta": {"solution": "sign-off test"}})
    status, _ = http(
        f"/api/projects/{sid}",
        "PATCH",
        {
            "gates": {
                "A": {
                    "decision": "Proceed",
                    "signedBy": forged,
                    "signedAt": forged_at,
                }
            }
        },
    )
    check("a forged sign-off is accepted as a patch", status == 200, str(status))
    _, listing = http("/api/projects")
    gate = next(p for p in json.loads(listing) if p["id"] == sid)["gates"]["A"]
    check(
        "the sign-off is attributed to the proxy identity, not the claim",
        gate["signedBy"] == baseline["id"] and gate["signedBy"] != forged,
        f"signedBy={gate['signedBy']!r}, expected {baseline['id']!r}",
    )
    check(
        "the sign-off time is the server's, not the claim",
        gate["signedAt"] != forged_at,
        gate["signedAt"],
    )

    # Disposal (#36), through the real proxy: a purge destroys the content and says
    # so, a delete leaves the history, and neither is the same as the other.
    secret = "MRN-" + uuid.uuid4().hex[:8]
    did = "t-" + uuid.uuid4().hex[:8]
    http(
        f"/api/projects/{did}",
        "POST",
        {"meta": {"solution": "disposal test"}, "items": {"a": {"evidence": secret}}},
    )
    http(
        f"/api/projects/{did}/log",
        "POST",
        {"text": f"Changed evidence: {secret}", "change": {"path": "a", "to": secret}},
    )
    check(
        "a purge is accepted", http(f"/api/projects/{did}/versions", "DELETE")[0] == 204
    )
    _, rev = http(f"/api/projects/{did}/versions/1")
    check(
        "the revision's content is gone",
        secret not in rev and json.loads(rev)["doc"] == {},
    )
    _, entries = http(f"/api/projects/{did}/log")
    check(
        "the audit log no longer holds the value", secret not in entries, entries[:200]
    )
    check("and says it was purged", "[content purged]" in entries)
    check("a delete is accepted", http(f"/api/projects/{did}", "DELETE")[0] == 204)
    check(
        "deleting did not erase what was already purged, or restore it",
        http(f"/api/projects/{did}/versions/1")[0] == 200,
    )

    print("Isolation (#56)")
    # The same script `make check-isolation` runs, against this real stack: no
    # published port on api or db, no direct way in, and a forged identity header
    # that does not become the identity. Its exit code is the assertion.
    isolation = subprocess.run(
        [sys.executable, "scripts/check_isolation.py"],
        capture_output=True,
        text=True,
        env={**os.environ, "HTTP_PORT": BASE.rsplit(":", 1)[1]},
        timeout=60,
    )
    check(
        "check_isolation.py finds the isolation model intact",
        isolation.returncode == 0,
        isolation.stdout[-400:],
    )

    print("A user id becomes a person (#39)")
    _, rows = http("/api/principals?ids=" + baseline["id"])
    found = json.loads(rows)
    check(
        "the proxy's asserted name is recorded and resolvable",
        len(found) == 1
        and found[0]["id"] == baseline["id"]
        and found[0]["name"] == baseline["name"],
        rows,
    )
    check(
        "an id nobody signed in as resolves to nothing, not an error",
        json.loads(http("/api/principals?ids=nobody-ever-signed-in")[1]) == [],
    )

    print("Two database roles (#48)")
    api_env = compose_exec("api", "env").splitlines()
    owner_vars = [
        line.split("=", 1)[0]
        for line in api_env
        if line.split("=", 1)[0]
        in ("POSTGRES_PASSWORD", "POSTGRES_USER", "DATABASE_URL")
    ]
    check(
        "the API container holds no owner credential",
        not owner_vars,
        f"the API's environment has {owner_vars}",
    )
    _, health_text = http("/api/health")
    check(
        "the API reports it serves as a restricted role",
        json.loads(health_text).get("db_role") == "restricted",
        health_text,
    )
    refused = compose_exec_all(
        "api",
        "python",
        "-c",
        "import asyncio, asyncpg, os\n"
        "from app.config import build_app_database_url\n"
        "async def main():\n"
        "    c = await asyncpg.connect(build_app_database_url(os.environ))\n"
        "    out = []\n"
        "    for sql in ('ALTER TABLE project_log DISABLE TRIGGER ALL',\n"
        "                'TRUNCATE project_version',\n"
        "                'DROP TRIGGER project_log_no_update ON project_log'):\n"
        "        try:\n"
        "            await c.execute(sql)\n"
        "            out.append('ALLOWED ' + sql)\n"
        "        except asyncpg.InsufficientPrivilegeError:\n"
        "            out.append('refused')\n"
        "    print(','.join(out))\n"
        "asyncio.run(main())\n",
    )
    check(
        "using the credential the API holds, the triggers cannot be disabled",
        refused.strip() == "refused,refused,refused",
        refused[-300:],
    )
    facts_roles = container_facts()
    check(
        "the migrate job ran, and exited cleanly",
        (facts_roles.get("migrate") or {}).get("exit") == 0,
        str(facts_roles.get("migrate")),
    )

    print("Container hardening (#50)")
    facts = container_facts()

    def fact(service: str, key: str):
        return (facts.get(service) or {}).get(key)

    check(
        "the proxy runs as an unprivileged user",
        str(fact("proxy", "user")).split(":")[0] not in ("", "0", "root", "None"),
        str(fact("proxy", "user")),
    )
    check(
        "the proxy and the api have no capability but the proxy's one",
        fact("api", "cap_drop") == ["ALL"]
        and fact("proxy", "cap_drop") == ["ALL"]
        and fact("proxy", "cap_add") == ["CAP_NET_BIND_SERVICE"]
        and not fact("api", "cap_add"),
        f"{facts}",
    )
    check(
        "the proxy and the api have a read-only root filesystem",
        fact("proxy", "read_only") is True and fact("api", "read_only") is True,
    )
    check(
        "every service has no-new-privileges and a memory limit",
        all(
            "no-new-privileges:true" in (fact(s, "security_opt") or [])
            and (fact(s, "memory") or 0) > 0
            for s in ("db", "api", "proxy", "migrate")
        ),
        f"{facts}",
    )
    check(
        "the proxy's volumes were handed to it, and it did not fail to write them",
        fact("proxy-perms", "exit") == 0 and "permission denied" not in proxy_log(),
        f"exit={fact('proxy-perms', 'exit')}",
    )

    print("PROXY_SHARED_SECRET (#61)")
    # Everything above went through the proxy, so with the secret on it already
    # proves the proxy sends it: the API would have answered 403 to all of it.
    # What it cannot show is that the API enforces it. For that, ask the API
    # from the proxy's own network address (so TRUSTED_PROXY_CIDR is satisfied)
    # without going through Caddy, once without the header and once with it.
    secret = compose_exec("api", "printenv", "PROXY_SHARED_SECRET").strip()
    if not secret:
        check(
            "the stack was started with PROXY_SHARED_SECRET set",
            False,
            "set it in .env; CI does, and this check is the only e2e of the control",
        )
    else:
        identity = {"X-Auth-Request-User": "u@x", "X-Auth-Request-Email": "u@x"}
        check(
            "the API refuses a request that skipped the proxy's secret",
            direct_api_status(identity) == 403,
            str(direct_api_status(identity)),
        )
        check(
            "and accepts the same request carrying it",
            direct_api_status({**identity, "X-Proxy-Secret": secret}) == 200,
            str(direct_api_status({**identity, "X-Proxy-Secret": secret})),
        )

    print("The read trail (#33)")
    probe = "trail-" + uuid.uuid4().hex[:8]
    http(f"/api/projects/{probe}", "POST", {"meta": {"solution": "Trail"}})
    http("/api/projects")
    http(f"/api/projects/{probe}/versions")
    http(f"/api/projects/{probe}/versions/1")
    http(f"/api/projects/{probe}/log")
    status_code, _ = http(f"/api/projects/{probe}/exports", "POST", {"format": "md"})
    check(
        "the export beacon is accepted through the proxy",
        status_code == 204,
        str(status_code),
    )
    rows = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "db",
            "psql",
            "-U",
            "chai",
            "-d",
            "chai",
            "-tAF",
            "|",
            "-c",
            "SELECT action, count(*) FROM access_event "
            f"WHERE project_id = '{probe}' OR (action = 'list') GROUP BY action",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    counts = dict(line.split("|") for line in rows.split() if "|" in line)
    check(
        "each read was recorded in the real database",
        all(
            int(counts.get(a, 0)) >= 1
            for a in ("list", "read_versions", "read_version", "read_log", "export")
        ),
        rows,
    )

    print("Agent API (#164)")
    status, body = http("/api/agent-tokens", "POST", {"label": "stack test"})
    if status == 404 and not REQUIRE_TESTS:
        print("  skip  AGENT_ID_SECRET is not set in this stack: the agent API is off")
    else:
        check("a signed-in user mints a token through the proxy", status == 201, body)
        minted = json.loads(body) if status == 201 else {"token": "", "id": ""}

        def as_agent(
            path: str, token: str | None, method: str = "GET"
        ) -> tuple[int, str]:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            req = urllib.request.Request(
                BASE + path, method=method, headers=headers, data=None
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return r.status, r.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode()

        status, body = as_agent("/api/agent/me", minted["token"])
        me = json.loads(body) if status == 200 else {}
        check(
            "the token reaches the agent route through the proxy, and names its user "
            "only as an opaque id",
            status == 200
            and me.get("token_id") == minted["id"]
            and me.get("user", "").startswith("u_")
            and baseline["email"] not in body
            and baseline["id"] not in body,
            f"{status} {body}",
        )
        status, body = as_agent("/api/agent/portfolio?limit=5", minted["token"])
        check(
            "the portfolio answers, with stored fields",
            status == 200 and "projects" in json.loads(body),
            f"{status} {body[:200]}",
        )
        bad_status, bad_body = as_agent(
            "/api/agent/me", "agt_" + "0" * 16 + "." + "A" * 43
        )
        check(
            "a token that is wrong is the uniform 401",
            bad_status == 401 and "Invalid or expired token." in bad_body,
            f"{bad_status} {bad_body}",
        )
        check(
            "a write verb on the agent route is refused by the proxy",
            as_agent("/api/agent/me", minted["token"], "DELETE")[0] == 404,
        )
        rows = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "chai",
                "-d",
                "chai",
                "-tAF",
                "|",
                "-c",
                "SELECT action, via, count(*) FROM access_event "
                f"WHERE token_id = '{minted['id']}' GROUP BY 1, 2",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
        counts = {
            line.split("|")[0]: (line.split("|")[1], int(line.split("|")[2]))
            for line in rows.split()
            if line.count("|") == 2
        }
        check(
            "each call is in the real read trail, marked as agent access",
            counts.get("agent_me") == ("agent", 1)
            and counts.get("agent_portfolio") == ("agent", 1),
            rows,
        )
        secret = minted["token"].split(".", 1)[-1]
        logs = subprocess.run(
            ["docker", "compose", "logs", "--no-color", "--no-log-prefix", "api"],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
        check(
            "the token's secret is in no log line",
            bool(secret) and secret not in logs,
        )
        check(
            "the owner can revoke it, and it stops working",
            http(f"/api/agent-tokens/{minted['id']}", "DELETE")[0] == 204
            and as_agent("/api/agent/me", minted["token"])[0] == 401,
        )

        status, body = http("/api/agent-tokens", "POST", {"label": "stack flood"})
        survivor = json.loads(body)["token"] if status == 201 else ""
        # A flood of well-formed wrong tokens through the real proxy, each claiming a
        # different X-Real-IP: the proxy replaces that header, so they are one source.
        # They are answered 401 and then 429, write no read-trail row, and a working
        # token from the same address is still served (#164 review).
        statuses = []
        for i in range(300):
            req = urllib.request.Request(
                BASE + "/api/agent/me",
                headers={
                    "Authorization": f"Bearer agt_{i:016x}." + "A" * 43,
                    "X-Real-IP": f"203.0.113.{i % 250}",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    statuses.append(r.status)
            except urllib.error.HTTPError as e:
                statuses.append(e.code)
        check(
            "a flood of wrong tokens gets 401 then 429, whatever X-Real-IP says",
            statuses.count(401) <= 31 and statuses.count(429) >= 250,
            f"401x{statuses.count(401)} 429x{statuses.count(429)}",
        )
        check(
            "and a working token from the same source is still served",
            as_agent("/api/agent/me", survivor)[0] == 200,
        )
        written = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                "chai",
                "-d",
                "chai",
                "-tA",
                "-c",
                "SELECT count(*) FROM access_event WHERE action = 'agent_refused' "
                f"AND token_id <> '{minted['id']}'",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout.strip()
        check(
            "and the flood wrote no row to the read trail",
            written == "0",
            written,
        )

    print("Security events (#38)")
    # The earlier checks created, purged and deleted projects through the real proxy.
    # What the API container wrote about that is what a log sink would receive.
    raw = subprocess.run(
        ["docker", "compose", "logs", "--no-color", "--no-log-prefix", "api"],
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    records = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("{"):
            with contextlib.suppress(ValueError):
                records.append(json.loads(line))
    check(
        "the API's log is JSON, one object per line",
        len(records) > 5 and all("stream" in r and "ts" in r for r in records),
        f"{len(records)} JSON lines of {len(raw.splitlines())}",
    )
    security = [r for r in records if r.get("stream") == "security"]
    seen = {r.get("event") for r in security}
    check(
        "creates, deletes and purges are named security events",
        {"project.created", "project.deleted", "versions.purged"} <= seen,
        str(sorted(e for e in seen if e)),
    )
    check(
        "they carry who and which project",
        all(
            r.get("actor") and r.get("project")
            for r in security
            if r.get("event") in ("project.created", "project.deleted")
        ),
    )
    check(
        "application chatter is not in the security stream",
        not any(
            r.get("event") is None for r in records if r.get("stream") == "security"
        ),
    )

    print("Browser")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  playwright not installed - skipping browser checks")
        return 1 if failures or REQUIRE_TESTS else 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/")
        wait_until(page, "typeof LOADED !== 'undefined' && LOADED", timeout=20)
        page.wait_for_timeout(1500)

        check(
            "app selects ApiStore",
            page.evaluate("STORE.constructor.name") == "ApiStore",
        )
        check("identity taken from the proxy", page.evaluate("ME.id") == baseline["id"])
        check("mode badge says shared", "Shared" in page.inner_text("#mode"))
        # The served page and the stack's rules are one build, so the page says
        # nothing about them (D-83). tests/test_rules_banner.py shows it would.
        check(
            "the page shows no retirement-rules banner: its rules are the server's",
            page.evaluate(
                "BUILD.ruleSetHash === "
                + json.dumps(manifest["ruleSetHash"])
                + " && RULES_PROBLEMS.length === 0"
                " && !document.getElementById('rulesBanner')"
            ),
        )

        # A change made OUTSIDE the browser must arrive over SSE. This is the
        # one that silently regressed once: the server sends named events, and
        # EventSource.onmessage never fires for those.
        before = page.evaluate("PROJECTS.size")
        other = "t-" + uuid.uuid4().hex[:8]
        subprocess.run(
            [
                "curl",
                "-s",
                "-o",
                "/dev/null",
                "-X",
                "POST",
                "-H",
                "Content-Type: application/json",
                "-d",
                '{"meta":{"solution":"pushed externally"}}',
                f"{BASE}/api/projects/{other}",
            ],
            capture_output=True,
            timeout=20,
        )
        arrived = False
        for _ in range(24):
            time.sleep(0.5)
            if page.evaluate("PROJECTS.size") > before:
                arrived = True
                break
        check("external change arrives over SSE", arrived)
        check("no page errors", not errors, "; ".join(errors[:2]))
        browser.close()
        http(f"/api/projects/{other}", "DELETE")

    http(f"/api/projects/{pid}", "DELETE")

    print()
    if failures:
        print(
            f"{len(failures)} check(s) failed: {', '.join(failures)}", file=sys.stderr
        )
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
