#!/usr/bin/env python3
"""The Caddy edge, exercised against a real Caddy: identity, headers, body cap.

This is the one part of the stack no other test touched, and it was broken:
proxy/Caddyfile stripped the upstream providers' headers BEFORE the step that
reads one of them through a placeholder, so every cloud configuration this
repository documents resolved to an empty identity and answered 401 to every
request. The only setting that worked was a literal string -- the single
configuration the rest of the review exists to prevent.

Nothing in Python could have caught that. It needs Caddy parsing the real
Caddyfile and an upstream reporting what arrived.

The security headers and the 2MB request cap are exposed to the same class of
mistake, because in a Caddyfile *where* a directive sits decides which
responses it applies to. `header` at the site level covers /api/* too; the same
block moved inside the static `handle` leaves every JSON response without so
much as nosniff, and looks identical until somebody reads a response. Likewise
an absent `request_body` cap is invisible from Python, because the API enforces
its own limit and answers 413 either way -- the only way to tell the edge cap
apart is to ask the upstream whether it ever saw the request.

    pixi run test-proxy        (needs Docker; skips cleanly without it)
"""

from __future__ import annotations

import contextlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Keep in step with the `header` block in proxy/Caddyfile. A value changed
# there and not here fails loudly, which is the point: these are the response
# headers the dashboard's threat model assumes, not incidental formatting.
#
# Strict-Transport-Security is in this list on purpose even though the rig only
# speaks plain HTTP. Caddy sends it unconditionally, and that is the intent:
# browsers ignore HSTS on a plaintext response, so it costs nothing behind a
# cloud front door that terminates TLS and it is load-bearing the moment
# SITE_ADDRESS is a hostname and Caddy is the public edge. A conditional
# `header` would be the bug -- the header would then be missing exactly where
# it matters.
EXPECTED_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
    "x-frame-options": "DENY",
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    # The Content-Security-Policy is generated from the built dashboard (its script-src
    # is that script's hash), so it is read from the generated file the proxy imports.
    "content-security-policy": re.search(
        r'Content-Security-Policy "([^"]+)"',
        (Path(__file__).resolve().parent.parent / "proxy" / "csp.caddy").read_text(),
    ).group(1),
}

# proxy/Caddyfile caps /api/* bodies with `max_size 2MB`. Caddy parses that
# with SI units, so it is 2,000,000 bytes and NOT 2 MiB -- worth pinning,
# because `2MB` reads like the larger number and the 97KB difference is exactly
# the kind of thing nobody notices until a document sits on the boundary.
EDGE_BODY_CAP = 2_000_000

ROOT = Path(__file__).resolve().parent.parent
CADDYFILE = ROOT / "proxy" / "Caddyfile"
# The MCP service's gate (#164): its own Caddyfile, a second Caddy of the `agent-mcp`
# profile. The mutation test (tests/test_proxy_mcp_mutations.py) points this at a copy.
GATE = ROOT / "proxy" / "Caddyfile.mcp-gate"
# Overridable so two runs on one machine (two worktrees, a developer and CI's
# neighbor) do not collide on the port, the network or the container names.
PORT = int(os.environ.get("PROXY_TEST_PORT", "18099"))
NET = os.environ.get("PROXY_TEST_NET", "chai-proxy-test")
CADDY = os.environ.get("PROXY_TEST_CADDY", "chai-test-caddy")
ECHO_NAME = os.environ.get("PROXY_TEST_ECHO", "chai-test-echo")

# CI sets REQUIRE_TESTS=1. A suite that cannot run then FAILS instead of
# skipping, because a skip exits 0 and reads as a pass: that is how CI once
# reported green while running none of these tests (#32).
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))

# What each front door actually puts on the request, and how .env.example says
# to read it. Keep in step with the identity blocks in .env.example.
FRONT_DOORS = [
    (
        "Google Cloud IAP",
        {
            "IDENTITY_ID_SOURCE": "{http.request.header.X-Goog-Authenticated-User-Id}",
            "IDENTITY_NAME_SOURCE": (
                "{http.request.header.X-Goog-Authenticated-User-Email}"
            ),
            "IDENTITY_EMAIL_SOURCE": (
                "{http.request.header.X-Goog-Authenticated-User-Email}"
            ),
        },
        {
            "X-Goog-Authenticated-User-Id": "accounts.google.com:1234",
            "X-Goog-Authenticated-User-Email": "accounts.google.com:cmo@hospital.org",
        },
        {"X-Auth-Request-User": "accounts.google.com:1234"},
    ),
    (
        "AWS ALB + OIDC",
        {
            "IDENTITY_ID_SOURCE": "{http.request.header.X-Amzn-Oidc-Identity}",
            "IDENTITY_NAME_SOURCE": "{http.request.header.X-Amzn-Oidc-Identity}",
            "IDENTITY_EMAIL_SOURCE": "{http.request.header.X-Amzn-Oidc-Identity}",
        },
        {"X-Amzn-Oidc-Identity": "sub-abc-123"},
        {"X-Auth-Request-User": "sub-abc-123"},
    ),
    (
        "Azure Easy Auth",
        {
            "IDENTITY_ID_SOURCE": "{http.request.header.X-Ms-Client-Principal-Id}",
            "IDENTITY_NAME_SOURCE": "{http.request.header.X-Ms-Client-Principal-Name}",
            "IDENTITY_EMAIL_SOURCE": "{http.request.header.X-Ms-Client-Principal-Name}",
        },
        {
            "X-Ms-Client-Principal-Id": "entra-oid-999",
            "X-Ms-Client-Principal-Name": "cmo@hospital.org",
        },
        {
            "X-Auth-Request-User": "entra-oid-999",
            "X-Auth-Request-Email": "cmo@hospital.org",
        },
    ),
    (
        "oauth2-proxy",
        {
            "IDENTITY_ID_SOURCE": "{http.request.header.X-Forwarded-User}",
            "IDENTITY_NAME_SOURCE": (
                "{http.request.header.X-Forwarded-Preferred-Username}"
            ),
            "IDENTITY_EMAIL_SOURCE": "{http.request.header.X-Forwarded-Email}",
        },
        {
            "X-Forwarded-User": "cmo",
            "X-Forwarded-Preferred-Username": "C. M. Officer",
            "X-Forwarded-Email": "cmo@hospital.org",
        },
        {
            "X-Auth-Request-User": "cmo",
            "X-Auth-Request-Email": "cmo@hospital.org",
        },
    ),
]

# The upstream. It echoes the headers it was handed -- which is how the
# identity checks see what Caddy actually forwarded -- and records how many
# body bytes it managed to read for each request, which is what the body-cap
# check needs. /_seen returns that log and is not itself recorded.
ECHO = """
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time
import json
SEEN = []
class H(BaseHTTPRequestHandler):
    def respond(self):
        if self.path.endswith("/_seen"):
            body = json.dumps(SEEN).encode()
        else:
            declared = int(self.headers.get("Content-Length") or 0)
            read = 0
            truncated = False
            try:
                while read < declared:
                    chunk = self.rfile.read(min(65536, declared - read))
                    if not chunk:
                        truncated = True
                        break
                    read += len(chunk)
            except Exception:
                truncated = True
            SEEN.append({"method": self.command, "path": self.path,
                         "declared": declared, "read": read,
                         "truncated": truncated})
            if truncated:
                return
            time.sleep(float(self.headers.get("X-Echo-Delay") or 0))
            body = json.dumps(dict(self.headers)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    do_GET = respond
    do_POST = respond
    do_DELETE = respond
    do_PUT = respond
    do_PATCH = respond
    do_OPTIONS = respond
    def log_message(self, *a): pass
ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
"""

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}{(' -- ' + detail) if detail else ''}")
        failures.append(name)


def docker(*args: str, check_rc: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check_rc
    )


def request(
    path: str,
    headers: dict[str, str],
    *,
    method: str = "GET",
    body: bytes | None = None,
    port: int | None = None,
    timeout: float = 30,
) -> tuple[int, str, dict[str, str]]:
    """Return (status, body, response headers lowercased) for one request.

    Response headers come back because half the checks below are about what
    Caddy puts on the response rather than what it forwards.
    """
    req = urllib.request.Request(
        f"http://127.0.0.1:{port or PORT}{path}",
        headers=headers,
        method=method,
        data=body,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            got = response.read().decode()
            status, raw = response.status, response.headers
    except urllib.error.HTTPError as exc:
        got, status, raw = exc.read().decode(), exc.code, exc.headers
    return status, got, {k.lower(): v for k, v in raw.items()}


def get(path: str, headers: dict[str, str]) -> tuple[int, str]:
    status, body, _ = request(path, headers)
    return status, body


def start_caddy(workdir: Path, env: dict[str, str]) -> None:
    docker("rm", "-f", CADDY)
    args = [
        "run",
        "-d",
        "--name",
        CADDY,
        "--network",
        NET,
        "-p",
        f"{PORT}:80",
        "-v",
        f"{CADDYFILE}:/etc/caddy/Caddyfile:ro",
        "-v",
        f"{CADDYFILE.parent / 'csp.caddy'}:/etc/caddy/csp.caddy:ro",
        "-v",
        f"{workdir}/srv:/srv/app:ro",
        "-e",
        "SITE_ADDRESS=http://:80",
    ]
    for key, value in env.items():
        args += ["-e", f"{key}={value}"]
    args.append("caddy:2")
    docker(*args)
    for _ in range(40):
        try:
            get("/", {})
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("Caddy did not come up")


def check_security_headers(label: str, path: str, headers: dict[str, str]) -> None:
    """Every response Caddy serves must carry the whole `header` block.

    Run against /api/* as well as the dashboard: the block lives at the site
    level precisely so the JSON responses get it, and a future edit that moves
    it back inside the static `handle` would still pass a dashboard-only check.
    """
    status, _, got = request(path, headers)
    check(f"{label}: responds", status in (200, 401), f"HTTP {status}")
    for name, want in EXPECTED_HEADERS.items():
        check(
            f"{label}: {name}",
            got.get(name) == want,
            f"got {got.get(name)!r}",
        )
    # `-Server` in the Caddyfile. Caddy announces itself otherwise, and the
    # version it announces is a free hint about which bugs apply.
    check(f"{label}: no Server header", "server" not in got, got.get("server", ""))


def seen_by_upstream(headers: dict[str, str]) -> list[dict]:
    """The requests the echo upstream has served, newest last."""
    _, body = get("/api/_seen", headers)
    return json.loads(body)


def check_edge_body_cap(headers: dict[str, str]) -> None:
    """The 2MB cap must be enforced BY CADDY, not merely by the API.

    The API enforces its own limit and answers 413 too, so a status code alone
    proves nothing about the edge. What distinguishes them is what the upstream
    was able to read.

    Note what Caddy's `request_body max_size` does and does not do. It does NOT
    reject on Content-Length before dialing: the upstream still sees the
    request line and headers, and `reverse_proxy` streams the body into it.
    What the directive installs is a reader that stops dead at the cap -- so
    the upstream reads at most 2,000,000 bytes, never the complete document,
    the connection is torn down under it, and the client gets 413. The
    guarantee is therefore "no handler ever receives a whole over-size body",
    which is the one that matters: the oversized write cannot happen, and the
    append-only copy of it in project_version cannot happen either.

    Asserting "the upstream never saw the request at all" would be a stricter
    claim than Caddy makes, and would start failing the day someone looks.
    """
    under = b"a" * 4096
    status, _, _ = request(
        "/api/projects/small",
        {**headers, "Content-Type": "application/json"},
        method="POST",
        body=under,
    )
    check("a body under the cap is forwarded", status == 200, f"HTTP {status}")
    small = [r for r in seen_by_upstream(headers) if r["path"] == "/api/projects/small"]
    check(
        "the under-cap body arrives whole",
        bool(small) and small[-1]["read"] == len(under) and not small[-1]["truncated"],
        f"upstream saw {small[-1:]}",
    )

    over = b"a" * (EDGE_BODY_CAP + 512 * 1024)
    status, _, _ = request(
        "/api/projects/big",
        {**headers, "Content-Type": "application/json"},
        method="POST",
        body=over,
    )
    check(
        f"a body over {EDGE_BODY_CAP} bytes is refused",
        status == 413,
        f"HTTP {status}",
    )

    big = [r for r in seen_by_upstream(headers) if r["path"] == "/api/projects/big"]
    check(
        "Caddy cut the over-size body off at the cap",
        bool(big) and big[-1]["read"] <= EDGE_BODY_CAP,
        f"upstream read {big[-1]['read'] if big else None} of {len(over)}",
    )
    check(
        "the API never receives a complete over-size body",
        bool(big) and big[-1]["truncated"],
        f"upstream saw {big[-1:]}",
    )


def check_proxy_shared_secret(workdir: Path) -> None:
    """The proxy must send the secret, and a client must not be able to choose it.

    With the secret set, what the upstream receives is the proxy's value even
    when the client sends its own, so a caller cannot satisfy the API's check by
    guessing or by replaying a value it saw. With it unset, nothing the client
    sends in that header reaches the API as a usable secret either.
    """
    door = FRONT_DOORS[3]
    secret = "s3cret/with+base64=chars"
    start_caddy(workdir, {**door[1], "PROXY_SHARED_SECRET": secret})

    status, body = get("/api/me", door[2])
    got = {k.lower(): v for k, v in json.loads(body).items()}
    check("with a secret set the request is forwarded", status == 200, f"HTTP {status}")
    check(
        "the proxy sends X-Proxy-Secret to the API",
        got.get("x-proxy-secret") == secret,
        f"got {got.get('x-proxy-secret')!r}",
    )

    _, body = get("/api/me", {**door[2], "X-Proxy-Secret": "chosen-by-the-client"})
    got = {k.lower(): v for k, v in json.loads(body).items()}
    check(
        "a client-supplied X-Proxy-Secret is replaced, not forwarded",
        got.get("x-proxy-secret") == secret,
        f"got {got.get('x-proxy-secret')!r}",
    )

    start_caddy(workdir, door[1])
    _, body = get("/api/me", {**door[2], "X-Proxy-Secret": "chosen-by-the-client"})
    got = {k.lower(): v for k, v in json.loads(body).items()}
    check(
        "with no secret configured a client value is not forwarded as a secret",
        got.get("x-proxy-secret", "") == "",
        f"got {got.get('x-proxy-secret')!r}",
    )


# Every header a front door, or a client pretending to be one, could use to say who
# a request is from. None may reach the API on the agent route.
IDENTITY_HEADERS = [
    "X-Auth-Request-User", "X-Auth-Request-Name", "X-Auth-Request-Email",
    "X-Goog-Authenticated-User-Email", "X-Goog-Authenticated-User-Id",
    "X-Goog-Iap-Jwt-Assertion", "X-Amzn-Oidc-Identity", "X-Amzn-Oidc-Data",
    "X-Amzn-Oidc-Accesstoken", "X-Ms-Client-Principal", "X-Ms-Client-Principal-Id",
    "X-Ms-Client-Principal-Name", "X-Ms-Client-Principal-Idp", "X-Forwarded-Email",
    "X-Forwarded-User", "X-Forwarded-Preferred-Username",
]  # fmt: skip

BEARER = {"Authorization": "Bearer agt_0123456789abcdef." + "A" * 43}


def raw_request(target: str, headers: dict[str, str]) -> bytes:
    """One HTTP/1.1 request with ``target`` exactly as written (no client cleans or
    encodes it), over a plain socket. Returns what the server answered."""
    import socket

    head = f"GET {target} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n"
    head += "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
    with socket.create_connection(("127.0.0.1", PORT), timeout=10) as conn:
        conn.sendall(head.encode("ascii"))
        chunks = []
        while True:
            try:
                data = conn.recv(65536)
            except OSError:
                break
            if not data:
                break
            chunks.append(data)
    return b"".join(chunks)


def check_agent_route(workdir: Path) -> None:
    """The agent API's route (#164): reachable with no single sign-on, read-only,
    and never an identity.

    Four things, each a way this could quietly become a hole:

    1. only the three agent GET routes are forwarded, and nothing else under
       /api/agent/ (a write verb, an unknown path) reaches the API at all;
    2. every identity header a client sends on the route is stripped, whichever
       front door's name it uses, and the bearer is passed through untouched;
    3. the proxy never sets an identity on the route, so a request that gets
       through to a route that needs one gets a 401 from the API;
    4. every other route behaves as before: an anonymous /api/agent-tokens or
       /api/projects is still refused by the proxy, whatever it carries.
    """
    oauth2 = FRONT_DOORS[3]
    start_caddy(workdir, oauth2[1])
    signed_in = oauth2[2]

    def seen() -> list[dict]:
        return seen_by_upstream(signed_in)

    forged = {name: "evil@x.example" for name in IDENTITY_HEADERS}
    for path in (
        "/api/agent/me",
        "/api/agent/portfolio?status=met&limit=5",
        "/api/agent/projects/p1",
    ):
        status, body, headers = request(path, {**forged, **BEARER})
        label = path.split("?")[0]
        check(
            f"agent route {label}: forwarded with no sign-on",
            status == 200,
            f"HTTP {status}",
        )
        got = (
            {k.lower(): v for k, v in json.loads(body).items()} if status == 200 else {}
        )
        check(
            f"agent route {label}: the bearer reaches the API unchanged",
            got.get("authorization") == BEARER["Authorization"],
            f"got {got.get('authorization')!r}",
        )
        leaked = [h for h in IDENTITY_HEADERS if h.lower() in got]
        check(
            f"agent route {label}: no client-supplied identity header reaches the API",
            not leaked,
            ", ".join(leaked),
        )
        check(
            f"agent route {label}: the answer is not cacheable",
            headers.get("cache-control") == "no-store",
            f"got {headers.get('cache-control')!r}",
        )
        for name, want in EXPECTED_HEADERS.items():
            check(f"agent route {label}: {name}", headers.get(name) == want)

    # Nothing is set either: with no identity of its own, the proxy forwards none.
    status, body, _ = request("/api/agent/me", BEARER)
    got = {k.lower() for k in json.loads(body)} if status == 200 else set()
    check(
        "the proxy sets no identity on the agent route",
        status == 200 and not [h for h in IDENTITY_HEADERS if h.lower() in got],
        f"HTTP {status}",
    )

    # 1. Only the three GET routes. A write verb, an unknown path and a path that
    #    only looks like one are answered by the proxy and go no further.
    before = len(seen())
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        status, _, _ = request(
            "/api/agent/me",
            BEARER,
            method=method,
            body=b"{}" if method != "DELETE" else None,
        )
        check(
            f"agent route: {method} is refused by the proxy",
            status == 404,
            f"HTTP {status}",
        )
    for path in (
        "/api/agent/",
        "/api/agent/projects",
        "/api/agent/anything",
        "/api/agent/mine",
        "/api/agent/portfolio/x",
    ):
        status, _, _ = request(path, {**forged, **BEARER})
        check(f"agent route: {path} is not forwarded", status == 404, f"HTTP {status}")
    check(
        "agent route: none of those reached the API",
        seen()[before:] == [],
        f"upstream saw {seen()[before:]}",
    )

    # A path that tries to leave the prefix, in the spellings a client can send. The
    # proxy may refuse it, or route it by the path it makes of it (as the single
    # sign-on route, which is then a session like any other). What must hold is that
    # a request the API would read as an agent route arrives with no identity.
    for path in (
        "/api/agent/me/../../projects",
        "/api/agent/%2e%2e/projects",
        "/api/agent/projects/..%2f..%2fme",
        "/API/AGENT/ME",
        "/api/Agent/me",
        "//api/agent/me",
        "/api/agent/me/",
    ):
        before = len(seen())
        status, body, _ = request(path, {**forged, **BEARER})
        reached = seen()[before:]
        got = {k.lower() for k in json.loads(body)} if status == 200 else set()
        for hit in reached:
            api_path = posixpath.normpath(urllib.parse.unquote(hit["path"])).lower()
            if api_path.startswith("/api/agent/"):
                check(
                    f"agent route: {path} reaches the API as an agent path "
                    "with no identity",
                    not [h for h in IDENTITY_HEADERS if h.lower() in got],
                    f"HTTP {status}, upstream path {hit['path']!r}",
                )
        check(
            f"agent route: {path} is refused, or forwarded as a plain session request",
            status in (200, 401, 404) and (status != 200 or bool(reached)),
            f"HTTP {status}",
        )

    # 4. Every other route is as it was: no identity, no entry, whatever else it
    #    carries. (The oauth2-proxy rig reads X-Forwarded-Email as the front door's
    #    own header, so the forgery here is the canonical set, which the proxy
    #    strips.)
    canonical = {
        h: "evil@x.example"
        for h in ("X-Auth-Request-User", "X-Auth-Request-Name", "X-Auth-Request-Email")
    }
    for path in ("/api/agent-tokens", "/api/projects", "/api/me", "/api/agentx"):
        status, _, _ = request(path, BEARER)
        check(
            f"{path}: a bearer alone is refused by the proxy",
            status == 401,
            f"HTTP {status}",
        )
        status, _, _ = request(path, {**canonical, **BEARER})
        check(
            f"{path}: a forged identity beside a bearer is refused",
            status == 401,
            f"HTTP {status}",
        )
    status, body, _ = request("/api/agent-tokens", {**signed_in, **BEARER})
    got = {k.lower(): v for k, v in json.loads(body).items()} if status == 200 else {}
    check(
        "/api/agent-tokens: a signed-in session still gets its identity set",
        status == 200 and got.get("x-auth-request-email") == "cmo@hospital.org",
        f"HTTP {status}",
    )
    # A token put in a URL is refused by the API; the proxy's log must not keep it
    # either, and must not change what it keeps of an ordinary route. Caddy routes on
    # the decoded, cleaned path and logs the RAW request target, so the spellings that
    # make the two differ are each tried, with the raw bytes a client can send.
    leaks = {
        "an agent path": "/api/agent/me?token=LEAKME111",
        "a different case": "/api/Agent/ME?access_token=LEAKME222&x=1",
        "a project": "/api/agent/projects/pr_x?api_key=LEAKME333",
        "a percent-encoded letter": "/api/%61gent/me?token=LEAKME444",
        "an absolute-form target": "http://localhost/api/agent/me?token=LEAKME555",
        "an absolute-form target in capitals": "HTTP://x/api/agent/me?token=LEAKME666",
        "a doubled slash": "//api/agent/me?token=LEAKME777",
        "the prefix alone": "/api/agent?token=LEAKME888",
        "a dot segment": "/api/./agent/me?token=LEAKME999",
        "a dot-dot segment": "/api/x/../agent/me?token=LEAKMEAAA",
        "the word in the query": "/api/me?token=LEAKMEBBB&who=agent",
        # Over-redaction on purpose: these can reach the agent route after Caddy
        # cleans them, so the query goes even where the raw path says nothing of it.
        "a doubled slash without the word": "//api/me?token=LEAKMEC01",
        "a dot segment without the word": "/api/./me?token=LEAKMEC02",
        "an absolute-form target without the word": "http://localhost/api/me?token=LEAKMEC03",
    }
    for target in leaks.values():
        raw_request(target, {})
    raw_request("/api/agent/me", {"X-Api-Key": "LEAKMEHDR1", "Api-Key": "LEAKMEHDR2"})
    raw_request(
        "/api/agent/me",
        {
            "X-Auth-Token": "LEAKMEHDR3",
            "X-Authorization": "LEAKMEHDR4",
            "X-Access-Token": "LEAKMEHDR5",
        },
    )
    request("/api/me?visible=KEEPME444", signed_in)
    time.sleep(1)
    logs = docker("logs", CADDY)
    text = logs.stdout + logs.stderr
    for what, target in leaks.items():
        secret = target.split("=")[1].split("&")[0]
        check(f"the proxy's log keeps no query of {what}", secret not in text, secret)
    check(
        "the proxy's log keeps no token-like request header",
        "LEAKMEHDR" not in text,
        "a header value was logged",
    )
    check(
        "and says the query was left out",
        text.count("?[redacted]") >= len(leaks),
        f"{text.count('?[redacted]')} mark(s)",
    )
    check("every other route's log line is as it was", "visible=KEEPME444" in text)
    # And the shared secret is still sent on the agent route, as on every route.
    start_caddy(workdir, {**oauth2[1], "PROXY_SHARED_SECRET": "agent/route+secret="})
    status, body, _ = request(
        "/api/agent/me", {**BEARER, "X-Proxy-Secret": "chosen-by-the-client"}
    )
    got = {k.lower(): v for k, v in json.loads(body).items()} if status == 200 else {}
    check(
        "agent route: X-Proxy-Secret is the proxy's, not the client's",
        got.get("x-proxy-secret") == "agent/route+secret=",
        f"got {got.get('x-proxy-secret')!r}",
    )


# --- the MCP route (#164, R-73, D-91) -------------------------------------------------

MCP_BODY_CAP = 64_000  # `max_size 64KB` in proxy/Caddyfile, SI units like the API's cap
MCP_HEADERS = {
    **BEARER,
    "Content-Type": "application/json",
    "Host": "mcp.example.test",
    "Origin": "https://chat.example.test",
}
FORGED_IDENTITY = {h: "forged@evil.example" for h in IDENTITY_HEADERS}


def echo_seen() -> list[dict]:
    """Every request the echo upstream has served, read from inside its container, so it
    works whichever listener the request came in on. It may still be starting."""
    for _ in range(40):
        done = docker(
            "exec",
            ECHO_NAME,
            "python",
            "-c",
            "import urllib.request;"
            "print(urllib.request.urlopen('http://127.0.0.1:8000/_seen').read().decode())",
        )
        if done.returncode == 0 and done.stdout.strip():
            return json.loads(done.stdout)
        time.sleep(0.5)
    raise RuntimeError("the echo upstream did not answer")


def check_mcp_route(workdir: Path) -> None:
    """The optional MCP service's route in proxy/Caddyfile (#164).

    It is the second place a request gets past single sign-on, so the same four ways
    it could quietly become a hole are checked, each against a real Caddy:

    1. only POST, GET and DELETE on exactly /mcp are forwarded; any other method, and
       any other path under the prefix, is answered here with a 404 and goes no further;
    2. every header that could be read as "who is this" is stripped, so is the secret
       the API checks, and the proxy sets none, even with a front door configured;
    3. what is forwarded is what the service needs, unchanged: the bearer, the Host
       (the service validates it), the Origin (the service validates it);
    4. with the profile off (nothing at the upstream) the answer is a 502 and nothing
       else on the proxy changes.
    """
    door = FRONT_DOORS[3]
    signed_in = door[2]
    start_caddy(
        workdir,
        {
            **door[1],
            "PROXY_SHARED_SECRET": "mcp-must-never-see-this",
            # The echo upstream stands in for the gate: the one thing that answers.
            "MCP_UPSTREAM": "api:8000",
        },
    )
    body = b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
    # The address THIS proxy observes, as the agent route gives it to the API.
    _, ref_body, _ = request("/api/agent/me", BEARER)
    # The echo has served every earlier check too: count only what this one adds.
    earlier = len(echo_seen())
    peer = {k.lower(): v for k, v in json.loads(ref_body).items()}.get("x-real-ip")
    sent = {
        **MCP_HEADERS,
        **FORGED_IDENTITY,
        "X-Client-Address": "6.6.6.6",
        "X-Proxy-Secret": "chosen-by-the-client",
        "X-Forwarded-For": "203.0.113.250",
        "X-Real-IP": "203.0.113.251",
        "Forwarded": "for=203.0.113.252",
    }
    status, got_body, resp = request("/mcp", sent, method="POST", body=body)
    check("mcp route: forwarded with no sign-on", status == 200, f"HTTP {status}")
    got = (
        {k.lower(): v for k, v in json.loads(got_body).items()} if status == 200 else {}
    )
    check(
        "mcp route: the bearer reaches the service unchanged",
        got.get("authorization") == BEARER["Authorization"],
    )
    check(
        "mcp route: the Host is the one the client used",
        got.get("host") == "mcp.example.test",
    )
    check(
        "mcp route: the Origin is passed on for the service to judge",
        got.get("origin") == "https://chat.example.test",
    )
    for name in (*IDENTITY_HEADERS, "X-Proxy-Secret"):
        check(
            f"mcp route: a client's {name} is stripped",
            name.lower() not in got,
            f"{name}={got.get(name.lower())!r}",
        )
    # The address the API will rate-limit and audit is what this edge observed, never a
    # claim (review H1): every header a client could use to claim one is deleted, and
    # X-Client-Address is set from the peer, the same value the agent route uses.
    check(
        "mcp route: X-Client-Address is the peer this proxy observed",
        bool(peer) and got.get("x-client-address") == peer,
        f"got {got.get('x-client-address')!r}, the peer is {peer!r}",
    )
    claims = ("203.0.113.250", "203.0.113.251", "203.0.113.252", "6.6.6.6")
    check(
        "mcp route: no forwarding claim a client made reaches the service",
        not [c for c in claims if c in json.dumps(got)],
        str([c for c in claims if c in json.dumps(got)]),
    )
    check(
        "mcp route: a client's X-Real-IP and Forwarded are deleted",
        "x-real-ip" not in got and "forwarded" not in got,
    )
    for rotating in ("203.0.113.10", "203.0.113.11", "203.0.113.12"):
        _, again, _ = request(
            "/mcp",
            {**MCP_HEADERS, "X-Forwarded-For": rotating, "X-Client-Address": rotating},
            method="POST",
            body=body,
        )
        check(
            f"mcp route: rotating the claimed address ({rotating}) changes nothing",
            {k.lower(): v for k, v in json.loads(again).items()}.get("x-client-address")
            == peer,
        )
    for method in ("GET", "DELETE"):
        status, _, _ = request("/mcp", MCP_HEADERS, method=method)
        check(
            f"mcp route: {method} is forwarded (the service answers it)", status == 200
        )
    for method in ("PUT", "PATCH", "OPTIONS"):
        status, text, _ = request("/mcp", MCP_HEADERS, method=method, body=b"{}")
        check(
            f"mcp route: {method} is refused by the proxy",
            status == 404 and text == "Not found.",
            f"HTTP {status} {text[:30]!r}",
        )
    for path in ("/mcp/", "/mcp/x", "/mcpx", "/MCP/x", "/mcp/sse", "/mcp.json"):
        status, text, _ = request(path, MCP_HEADERS, method="POST", body=body)
        check(
            f"mcp route: {path} is not forwarded",
            status == 404 and text == "Not found.",
            f"HTTP {status} {text[:30]!r}",
        )
    for path in ("/mcp/../api/me", "/mcp/%2e%2e/api/me", "/mcp%2f..%2fapi/me"):
        status, _, _ = request(path, MCP_HEADERS, method="POST", body=body)
        check(
            f"mcp route: {path} gets no further than the sign-on handle",
            status in (401, 404),
            f"HTTP {status}",
        )
    forwarded = [
        (r["method"], r["path"])
        for r in echo_seen()[earlier:]
        if r["path"].startswith("/mcp")
    ]
    check(
        "mcp route: the service saw exactly the three allowed requests",
        forwarded == [("POST", "/mcp")] * 4 + [("GET", "/mcp"), ("DELETE", "/mcp")],
        str(forwarded),
    )
    check(
        "mcp route: nothing reached the main API through it",
        not [r for r in echo_seen()[earlier:] if r["path"].startswith("/api/")],
    )

    # X-Client-Address is no client's on ANY route: it is removed for every request.
    for path, headers in (
        ("/api/agent/me", BEARER),
        ("/api/me", signed_in),
        ("/api/projects", signed_in),
    ):
        _, other, _ = request(path, {**headers, "X-Client-Address": "6.6.6.6"})
        check(
            f"X-Client-Address is stripped on {path}",
            "x-client-address" not in {k.lower() for k in json.loads(other)},
        )
    check(
        "the proxy sets no identity on the mcp route, with a front door configured",
        not [k for k in got if k.startswith("x-auth-request")],
        str([k for k in got if k.startswith("x-auth-request")]),
    )
    check(
        "mcp route: the answer is not cacheable",
        resp.get("cache-control") == "no-store",
        f"got {resp.get('cache-control')!r}",
    )
    check(
        "mcp route: the proxy's secret is not given to the service",
        "mcp-must-never-see-this" not in got_body,
    )
    # The security headers are the site's, and this route gets them too.
    for name, want in EXPECTED_HEADERS.items():
        check(f"mcp route: {name}", resp.get(name) == want, f"got {resp.get(name)!r}")

    # The body is capped at the edge, as the API's is.
    under = request("/mcp", MCP_HEADERS, method="POST", body=b"a" * 4096)[0]
    over = request(
        "/mcp", MCP_HEADERS, method="POST", body=b"a" * (MCP_BODY_CAP + 4096)
    )[0]
    check("mcp route: a body under the cap is forwarded", under == 200, f"HTTP {under}")
    check("mcp route: a body over the cap is refused", over == 413, f"HTTP {over}")

    # Everything else on the proxy is as it was.
    status, _ = get("/api/me", {})
    check("an anonymous /api/me is still refused", status == 401, f"HTTP {status}")
    status, text = get("/", {})
    check("the dashboard is still served", status == 200 and text == "app")
    status, _, _ = request("/api/agent-tokens", {}, method="POST", body=b"{}")
    check("an anonymous token mint is still refused", status == 401, f"HTTP {status}")

    # A token in a URL is refused by the service; the proxy must not log it either,
    # and Caddy already redacts the Authorization header.
    request("/mcp?token=LEAKMCP111&x=1", MCP_HEADERS, method="POST", body=body)
    request("/mcp?access_token=LEAKMCP222", MCP_HEADERS, method="POST", body=body)
    request("/MCP?api_key=LEAKMCP333", MCP_HEADERS, method="POST", body=body)
    request("/api/me?visible=KEEPSAFE444", signed_in)
    time.sleep(1)
    logs = docker("logs", CADDY)
    text = logs.stdout + logs.stderr
    for secret in ("LEAKMCP111", "LEAKMCP222", "LEAKMCP333"):
        check(f"the proxy's log keeps no query of /mcp ({secret})", secret not in text)
    check(
        "the proxy's log keeps no bearer token",
        BEARER["Authorization"].split(" ")[1] not in text,
    )
    check("every other route's log line is as it was", "visible=KEEPSAFE444" in text)

    # Profile off: nothing answers where the gate would be. The route exists and says
    # so (502); the rest of the proxy is untouched, and nothing leaks to the API.
    for label, env in (
        ("the default upstream", {}),
        ("an upstream that is down", {"MCP_UPSTREAM": "nowhere.invalid:1"}),
    ):
        start_caddy(workdir, {**door[1], **env})
        earlier = len(echo_seen())
        status, _, _ = request("/mcp", MCP_HEADERS, method="POST", body=body)
        check(
            f"mcp route: with {label}, POST /mcp is a 502",
            status == 502,
            f"HTTP {status}",
        )
        status, _, _ = request("/mcp", MCP_HEADERS, method="GET")
        check(
            f"mcp route: with {label}, GET /mcp is a 502",
            status == 502,
            f"HTTP {status}",
        )
        check(
            f"mcp route: with {label}, nothing reached the main API",
            len(echo_seen()) == earlier,
        )
        status, text = get("/api/me", signed_in)
        check(f"with {label}, the rest of the proxy is as it was", status == 200)


def raw_exchange_bytes(port: int, data: bytes, *, wait: float) -> bytes:
    """Send bytes and read until the peer answers or closes, or ``wait`` passes."""
    import socket

    with socket.create_connection(("127.0.0.1", port), timeout=wait) as conn:
        conn.sendall(data)
        conn.settimeout(wait)
        try:
            return conn.recv(65536)
        except OSError:
            return b""


def check_mcp_timeouts(workdir: Path) -> None:
    """A slow service is answered with an error after the response-header timeout
    (30 seconds) on the route and on the gate's listener, not held for ever."""
    door = FRONT_DOORS[3]
    start_caddy(workdir, {**door[1], "MCP_UPSTREAM": "api:8000"})
    began = time.monotonic()
    status, _, _ = request(
        "/mcp",
        {**MCP_HEADERS, "X-Echo-Delay": "38"},
        method="POST",
        body=b"{}",
        timeout=60,
    )
    took = time.monotonic() - began
    check(
        "mcp route: a service that does not answer in 30 seconds is an error",
        status in (502, 504) and took < 36,
        f"HTTP {status} after {took:.0f}s",
    )
    # Headers that never finish arriving are dropped (read_header, 10 seconds).
    import socket

    def header_trickle(port: int) -> float:
        began = time.monotonic()
        with socket.create_connection(("127.0.0.1", port), timeout=30) as conn:
            conn.sendall(b"POST /mcp HTTP/1.1\r\nHost: x\r\nX-Slow: ")
            conn.settimeout(20)
            with contextlib.suppress(OSError):
                conn.recv(4096)
        return time.monotonic() - began

    took = header_trickle(PORT)
    check(
        "mcp route: headers that never finish arriving are dropped",
        took < 16,
        f"still open after {took:.0f}s",
    )
    start_gate(workdir, {"PROXY_SHARED_SECRET": "x", "MCP_UPSTREAM": "api:8000"})
    for label, port in (("the service's", PORT + 1), ("the API's", PORT)):
        took = header_trickle(port)
        check(
            f"gate: headers that never finish arriving are dropped on {label} listener",
            took < 16,
            f"still open after {took:.0f}s",
        )
    began = time.monotonic()
    status, _, _ = request(
        "/mcp",
        {**MCP_HEADERS, "X-Echo-Delay": "38"},
        method="POST",
        body=b"{}",
        port=PORT + 1,
        timeout=60,
    )
    took = time.monotonic() - began
    check(
        "gate: a service that does not answer in 30 seconds is an error",
        status in (502, 504) and took < 36,
        f"HTTP {status} after {took:.0f}s",
    )


def start_gate(workdir: Path, env: dict[str, str]) -> None:
    """The MCP gate (proxy/Caddyfile.mcp-gate): :8081 on PORT and :8082 on PORT+1."""
    docker("rm", "-f", CADDY)
    args = [
        "run",
        "-d",
        "--name",
        CADDY,
        "--network",
        NET,
        "-p",
        f"{PORT}:8081",
        "-p",
        f"{PORT + 1}:8082",
        "-v",
        f"{GATE}:/etc/caddy/Caddyfile:ro",
    ]
    for key, value in env.items():
        args += ["-e", f"{key}={value}"]
    args.append("caddy:2")
    docker(*args)
    for _ in range(40):
        try:
            request("/", {}, port=PORT)
            request("/", {}, port=PORT + 1)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("the MCP gate did not come up")


def check_mcp_gate(workdir: Path) -> None:
    """The MCP gate (#164): the service's only two doors, each as narrow as it looks.

    :8081 (service to API) forwards the three GET routes and nothing else, with the
    caller's token untouched, the caller's address as the API's source, and the shared
    secret the service never holds. :8082 (proxy to service) forwards the transport's
    three methods on /mcp and nothing else, and sets the caller's address itself.
    """
    secret = "gate/secret+value="
    earlier = len(echo_seen())
    start_gate(
        workdir,
        {
            "PROXY_SHARED_SECRET": secret,
            # The echo upstream stands in for the service, and also for the API.
            "MCP_UPSTREAM": "api:8000",
        },
    )
    out, inn = PORT, PORT + 1

    def seen(_port: int) -> list[dict]:
        return echo_seen()

    # --- :8081, the service's way to the agent API ---------------------------------
    sent = {
        **BEARER,
        **FORGED_IDENTITY,
        "X-Client-Address": "203.0.113.9",
        "X-Proxy-Secret": "chosen-by-the-service",
        "Cookie": "session=abc",
    }
    for path in (
        "/api/agent/me",
        "/api/agent/portfolio?status=notmet&limit=5",
        "/api/agent/projects/pr_" + "a" * 32,
    ):
        status, text, resp = request(path, sent, port=out)
        got = (
            {k.lower(): v for k, v in json.loads(text).items()} if status == 200 else {}
        )
        label = path.split("?")[0]
        check(f"gate: GET {label} is forwarded", status == 200, f"HTTP {status}")
        check(
            f"gate: {label}: the caller's bearer reaches the API unchanged",
            got.get("authorization") == BEARER["Authorization"],
        )
        check(
            f"gate: {label}: no identity header reaches the API",
            not [h for h in IDENTITY_HEADERS if h.lower() in got],
        )
        check(
            f"gate: {label}: the secret is the gate's, not the sender's",
            got.get("x-proxy-secret") == secret,
            f"got {got.get('x-proxy-secret')!r}",
        )
        check(
            f"gate: {label}: the caller's address becomes the API's source",
            got.get("x-real-ip") == "203.0.113.9",
            f"got {got.get('x-real-ip')!r}",
        )
        check(
            f"gate: {label}: the answer is not cacheable",
            resp.get("cache-control") == "no-store",
        )
    status, text, _ = request("/api/agent/me", BEARER, port=out)
    got = {k.lower(): v for k, v in json.loads(text).items()}
    check(
        "gate: with no address reported the API's source header is empty, not invented",
        got.get("x-real-ip", "") == "",
        f"got {got.get('x-real-ip')!r}",
    )
    before = len(seen(out))
    for method in ("POST", "DELETE", "PUT", "PATCH"):
        status, text, _ = request(
            "/api/agent/me", BEARER, method=method, port=out, body=b"{}"
        )
        check(
            f"gate: {method} on an agent route is refused",
            status == 404 and text == "Not found.",
            f"HTTP {status}",
        )
    for path in (
        "/api/projects",
        "/api/projects/x",
        "/api/me",
        "/api/agent-tokens",
        "/api/agent/",
        "/api/agent/anything",
        "/api/agent/projects",
        "/api/events",
        "/api/health",
        "/",
        "/mcp",
    ):
        status, text, _ = request(path, BEARER, port=out)
        check(
            f"gate: GET {path} is not forwarded to the API",
            status == 404 and text == "Not found.",
            f"HTTP {status} {text[:30]!r}",
        )
    check(
        "gate: none of those reached the API",
        len(seen(out)) == before,
        f"{len(seen(out)) - before} extra request(s)",
    )

    # The container's own health check, and a body cap on the agent routes' listener.
    status, text, _ = request("/gate-health", {}, port=out)
    check("gate: its health route answers", status == 200 and text == "ok", f"{status}")
    status, _, _ = request(
        "/api/agent/me",
        {**BEARER, "Content-Type": "text/plain"},
        port=out,
        body=b"a" * 20_000,
    )
    check(
        "gate: a body over the agent listener's cap is refused",
        status == 413,
        f"{status}",
    )

    # --- :8082, the proxy's way to the service -------------------------------------
    sent = {
        **MCP_HEADERS,
        **FORGED_IDENTITY,
        "X-Client-Address": "6.6.6.6",
        "X-Proxy-Secret": "chosen-by-the-client",
        "X-Forwarded-For": "198.51.100.7",
        "X-Real-IP": "198.51.100.8",
        "Forwarded": "for=198.51.100.9",
    }
    status, text, resp = request("/mcp", sent, method="POST", body=b"{}", port=inn)
    got = {k.lower(): v for k, v in json.loads(text).items()} if status == 200 else {}
    check(
        "gate: POST /mcp is forwarded to the service", status == 200, f"HTTP {status}"
    )
    check(
        "gate: the bearer reaches the service unchanged",
        got.get("authorization") == BEARER["Authorization"],
    )
    check(
        "gate: no identity header and no secret reaches the service",
        not [h for h in (*IDENTITY_HEADERS, "X-Proxy-Secret") if h.lower() in got],
        str([h for h in (*IDENTITY_HEADERS, "X-Proxy-Secret") if h.lower() in got]),
    )
    # The gate takes the address from the proxy as it is, and never from a forwarding
    # header (review H1): a forged X-Forwarded-For changes nothing.
    check(
        "gate: X-Client-Address is passed on as the proxy set it",
        got.get("x-client-address") == "6.6.6.6",
        f"got {got.get('x-client-address')!r}",
    )
    check(
        "gate: a forwarded-for claim never becomes the address",
        not [
            c
            for c in ("198.51.100.7", "198.51.100.8", "198.51.100.9")
            if c in json.dumps(got)
        ]
        and "x-real-ip" not in got
        and "forwarded" not in got,
        json.dumps(got)[:200],
    )
    check("gate: the answer is not cacheable", resp.get("cache-control") == "no-store")
    for method in ("GET", "DELETE"):
        status, _, _ = request("/mcp", MCP_HEADERS, method=method, port=inn)
        check(f"gate: {method} /mcp is forwarded", status == 200, f"HTTP {status}")
    for method in ("PUT", "PATCH", "OPTIONS"):
        status, text, _ = request(
            "/mcp", MCP_HEADERS, method=method, port=inn, body=b"{}"
        )
        check(
            f"gate: {method} /mcp is refused",
            status == 404 and text == "Not found.",
            f"HTTP {status}",
        )
    for path in ("/mcp/", "/mcp/x", "/api/agent/me", "/api/projects", "/api/me", "/"):
        status, text, _ = request(
            path, MCP_HEADERS, method="POST", port=inn, body=b"{}"
        )
        check(
            f"gate: {path} is not forwarded to the service",
            status == 404 and text == "Not found.",
            f"HTTP {status}",
        )
    paths = [
        (r["method"], r["path"])
        for r in seen(out)[earlier:]
        if r["path"].startswith("/mcp")
    ]
    check(
        "gate: the service saw only the allowed requests on /mcp",
        paths == [("POST", "/mcp"), ("GET", "/mcp"), ("DELETE", "/mcp")],
        str(paths),
    )

    over = request(
        "/mcp", MCP_HEADERS, method="POST", port=inn, body=b"a" * (MCP_BODY_CAP + 4096)
    )[0]
    check("gate: a body over the cap is refused", over == 413, f"HTTP {over}")
    # A body that is started and never finished is cut off by the gate (review M3). The
    # echo upstream waits for the rest of it, so what shows the gate gave up is the
    # upstream's connection being torn down (a truncated body) once the gate's
    # `read_body` (10 seconds) passes, and not 30 seconds later.
    import socket

    for label, port, path in (
        ("the service's listener", inn, "/mcp"),
        ("the API's listener", out, "/api/agent/me"),
    ):
        method = "POST" if port == inn else "GET"
        before = len(echo_seen())
        with socket.create_connection(("127.0.0.1", port), timeout=30) as conn:
            conn.sendall(
                f"{method} {path} HTTP/1.1\r\nHost: x\r\nContent-Length: 98\r\n"
                f"Authorization: {BEARER['Authorization']}\r\n\r\n{{".encode()
            )
            time.sleep(16)
            cut = [r for r in echo_seen()[before:] if r["path"] == path]
        check(
            f"gate: a body trickled forever is cut off on {label}",
            bool(cut) and cut[-1]["truncated"],
            f"upstream saw {cut}",
        )

    # The log keeps no query string and no token.
    request("/api/agent/me?token=LEAKGATE1", BEARER, port=out)
    request("/mcp?token=LEAKGATE2", MCP_HEADERS, method="POST", port=inn, body=b"{}")
    time.sleep(1)
    logs = docker("logs", CADDY)
    text = logs.stdout + logs.stderr
    for leaked in ("LEAKGATE1", "LEAKGATE2", BEARER["Authorization"].split(" ")[1]):
        check(f"gate: its log keeps no {leaked[:10]}...", leaked not in text)


def docker_usable() -> bool:
    return bool(shutil.which("docker")) and docker("info").returncode == 0


@contextlib.contextmanager
def rig():
    """A scratch directory, a network and an echo upstream named `api`, then gone.

    The mutation test (tests/test_proxy_agent_mutations.py) builds the same rig and
    points start_caddy at a broken copy of the Caddyfile.
    """
    workdir = Path(tempfile.mkdtemp(prefix="chai-proxy-test-"))
    (workdir / "srv").mkdir()
    (workdir / "srv" / "index.html").write_text("app")
    (workdir / "echo.py").write_text(ECHO)

    docker("network", "create", NET)
    docker("rm", "-f", ECHO_NAME)
    docker(
        "run",
        "-d",
        "--name",
        ECHO_NAME,
        "--network",
        NET,
        "--network-alias",
        "api",
        "-v",
        f"{workdir}/echo.py:/echo.py:ro",
        "python:3.12-slim",
        "python",
        "/echo.py",
    )
    try:
        yield workdir
    finally:
        docker("rm", "-f", CADDY)
        docker("rm", "-f", ECHO_NAME)
        docker("network", "rm", NET)
        shutil.rmtree(workdir, ignore_errors=True)


def main() -> int:
    if not docker_usable():
        print("docker unavailable; skipping proxy identity checks")
        return 1 if REQUIRE_TESTS else 0

    with rig() as workdir:
        run_checks(workdir)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("proxy identity checks passed")
    return 0


def run_checks(workdir: Path) -> None:
    for name, env, sent, expected in FRONT_DOORS:
        start_caddy(workdir, env)
        status, body = get("/api/me", sent)
        if status != 200:
            check(f"{name}: request is forwarded", False, f"HTTP {status}")
            continue
        check(f"{name}: request is forwarded", True)
        got = {k.lower(): v for k, v in json.loads(body).items()}
        for header, want in expected.items():
            check(
                f"{name}: {header} = {want!r}",
                got.get(header.lower()) == want,
                f"got {got.get(header.lower())!r}",
            )
        leaked = [
            k
            for k in got
            if k.startswith(("x-goog", "x-amzn", "x-ms-client", "x-forwarded-user"))
            or k in ("x-forwarded-email", "x-forwarded-preferred-username")
        ]
        check(
            f"{name}: no provider header reaches the API",
            not leaked,
            ", ".join(leaked),
        )

    # The canonical headers must never be accepted from the client.
    start_caddy(workdir, FRONT_DOORS[0][1])
    status, _ = get(
        "/api/me",
        {"X-Auth-Request-User": "evil@x", "X-Auth-Request-Email": "evil@x"},
    )
    check("a forged X-Auth-Request-* is refused", status == 401, f"HTTP {status}")

    status, _ = get("/api/me", {})
    check("a request with no identity is refused", status == 401, f"HTTP {status}")

    # An unset source must fail closed, not fall back to something usable.
    start_caddy(
        workdir,
        {
            "IDENTITY_ID_SOURCE": "",
            "IDENTITY_NAME_SOURCE": "",
            "IDENTITY_EMAIL_SOURCE": "",
        },
    )
    status, _ = get("/api/me", {"X-Forwarded-Email": "cmo@hospital.org"})
    check("an unset identity source fails closed", status == 401, f"HTTP {status}")

    # ---------------------------------------------------------------
    # PROXY_SHARED_SECRET (#61). The API rejects a request that lacks the
    # secret, so the control only works if the proxy sends it. It was
    # documented for months while nothing did: switching it on made every
    # request answer 403.
    # ---------------------------------------------------------------
    check_proxy_shared_secret(workdir)

    # ---------------------------------------------------------------
    # The response headers and the edge body cap. #20 added both and
    # nothing asserted either; see the module docstring for why a Python
    # test of the API cannot stand in for this.
    # ---------------------------------------------------------------
    oauth2 = FRONT_DOORS[3]
    start_caddy(workdir, oauth2[1])
    signed_in = oauth2[2]

    check_security_headers("an authenticated /api response", "/api/me", signed_in)
    check_security_headers("an anonymous /api 401", "/api/me", {})
    check_security_headers("the dashboard", "/", {})

    # Cache-Control belongs to the static handler alone: the dashboard is
    # rebuilt at a URL that never changes, so a cached copy is a stale app.
    _, _, dash = request("/", {})
    check(
        "the dashboard is served no-cache",
        dash.get("cache-control") == "no-cache",
        f"got {dash.get('cache-control')!r}",
    )

    check_edge_body_cap(signed_in)

    # The agent API's route: no single sign-on, read-only, never an identity (#164).
    check_agent_route(workdir)

    # The optional MCP service's route and its gate (#164, R-73, D-91).
    check_mcp_route(workdir)
    check_mcp_gate(workdir)
    check_mcp_timeouts(workdir)


if __name__ == "__main__":
    sys.exit(main())
