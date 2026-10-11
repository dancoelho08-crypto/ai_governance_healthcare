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
from http.server import BaseHTTPRequestHandler, HTTPServer
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
            body = json.dumps(dict(self.headers)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    do_GET = respond
    do_POST = respond
    def log_message(self, *a): pass
HTTPServer(("0.0.0.0", 8000), H).serve_forever()
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
) -> tuple[int, str, dict[str, str]]:
    """Return (status, body, response headers lowercased) for one request.

    Response headers come back because half the checks below are about what
    Caddy puts on the response rather than what it forwards.
    """
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}", headers=headers, method=method, data=body
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
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


if __name__ == "__main__":
    sys.exit(main())
