#!/usr/bin/env python3
"""The MCP route's guards in proxy/Caddyfile and proxy/Caddyfile.mcp-gate, each shown
to fail (#164, R-73, D-91).

tests/test_proxy_identity.py checks both files against a real Caddy: only the
transport's methods on the single path, every identity header stripped and none set,
the bearer passed on untouched, the secret kept from the service, nothing else
forwarded, and a 502 when nothing is behind the route. A check nobody has seen fail is
a claim, so this breaks a COPY of each file in each way that matters, runs the same
checks against a real Caddy, and demands that they notice. Needs Docker.

    pixi run test-proxy-mcp
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tp = load("proxy_identity", ROOT / "tests" / "test_proxy_identity.py")

MAIN_START = "\t@mcpfront {"
MAIN_END = "\t# " + "-" * 73 + "\n\t# The dashboard: one pre-built"


def strip(name: str) -> str:
    return f"\t\t\trequest_header -{name}\n"


AGENT_ONLY_LOG = (
    r"(?i)^(?:([^?]*(?:agent|%|//|/\.{1,2}(?:/|$))[^?]*)\?.*|([^?]*)\?.*agent.*)$"
)
MCP_LOG = (
    r"(?i)^(?:([^?]*(?:agent|mcp|%|//|/\.{1,2}(?:/|$))[^?]*)\?.*"
    r"|([^?]*)\?.*(?:agent|mcp).*)$"
)

# (name, old, new, nth occurrence in its scope)
MAIN: list[tuple[str, str, str, int]] = [
    ("PUT is forwarded", "method POST GET DELETE", "method POST GET DELETE PUT", 1),
    ("PATCH is forwarded", "method POST GET DELETE", "method POST GET DELETE PATCH", 1),
    (
        "any path under the prefix is forwarded",
        "\t\tpath /mcp\n",
        "\t\tpath /mcp*\n",
        1,
    ),
    (
        "the canonical email header is not stripped",
        strip("X-Auth-Request-Email"),
        "",
        1,
    ),
    ("the canonical user header is not stripped", strip("X-Auth-Request-User"), "", 1),
    ("an IAP header is not stripped", strip("X-Goog-Authenticated-User-Email"), "", 1),
    (
        "the oauth2-proxy email header is not stripped",
        strip("X-Forwarded-Email"),
        "",
        1,
    ),
    ("an ALB header is not stripped", strip("X-Amzn-Oidc-Data"), "", 1),
    ("an Easy Auth header is not stripped", strip("X-Ms-Client-Principal-Name"), "", 1),
    ("a client's X-Client-Address is not stripped", strip("X-Client-Address"), "", 1),
    ("a client's X-Proxy-Secret is not stripped", strip("X-Proxy-Secret"), "", 1),
    (
        "the proxy sets an identity on the mcp route",
        '\t\t\theader Cache-Control "no-store"\n',
        '\t\t\trequest_header X-Auth-Request-Email "{$IDENTITY_EMAIL_SOURCE}"\n'
        '\t\t\theader Cache-Control "no-store"\n',
        1,
    ),
    (
        "the proxy gives the service its shared secret",
        "\t\t\t\tflush_interval -1\n",
        "\t\t\t\tflush_interval -1\n"
        '\t\t\t\theader_up X-Proxy-Secret "{$PROXY_SHARED_SECRET}"\n',
        1,
    ),
    ("the answer is cacheable", '\t\t\theader Cache-Control "no-store"\n', "", 1),
    (
        "the body is not capped",
        "\t\trequest_body {\n\t\t\tmax_size 64KB\n\t\t}\n\n",
        "",
        1,
    ),
    (
        "the fallback no longer refuses the rest of the prefix",
        '\thandle /mcp* {\n\t\trespond "Not found." 404\n\t}\n',
        "",
        1,
    ),
    (
        "the default upstream is the main API",
        "{$MCP_UPSTREAM:mcp-gate:8082}",
        "{$MCP_UPSTREAM:api:8000}",
        1,
    ),
]
# Applied to the whole file: the log's redaction is above the route.
MAIN_FILE: list[tuple[str, str, str, int]] = [
    ("the log keeps the query of /mcp", MCP_LOG, AGENT_ONLY_LOG, 1),
]

GATE: list[tuple[str, str, str, int]] = [
    # --- :8081, the service to the API
    (
        "8081 forwards a write verb",
        "\t\tmethod GET\n",
        "\t\tmethod GET POST DELETE\n",
        1,
    ),
    (
        "8081 forwards any agent path",
        "\t\tpath /api/agent/me /api/agent/portfolio /api/agent/projects/*\n",
        "\t\tpath /api/agent/*\n",
        1,
    ),
    (
        "8081 forwards every API path",
        "\t\tpath /api/agent/me /api/agent/portfolio /api/agent/projects/*\n",
        "\t\tpath /api/*\n",
        1,
    ),
    ("8081 does not strip the canonical email", strip("X-Auth-Request-Email"), "", 1),
    (
        "8081 does not strip an IAP header",
        strip("X-Goog-Authenticated-User-Email"),
        "",
        1,
    ),
    (
        "8081 does not send the caller's address",
        '\t\t\t\theader_up X-Real-IP "{http.request.header.X-Client-Address}"\n',
        "",
        1,
    ),
    (
        "8081 lets the sender choose the shared secret",
        '\t\t\t\theader_up X-Proxy-Secret "{$PROXY_SHARED_SECRET}"\n',
        "",
        1,
    ),
    (
        "8081 no longer refuses the rest",
        '\thandle {\n\t\trespond "Not found." 404\n\t}\n',
        "",
        1,
    ),
    ("8081 answer is cacheable", '\t\t\theader Cache-Control "no-store"\n', "", 1),
    # --- :8082, the proxy to the service
    (
        "8082 forwards PUT",
        "\t\tmethod POST GET DELETE\n",
        "\t\tmethod POST GET DELETE PUT\n",
        1,
    ),
    ("8082 forwards any path", "\t\tpath /mcp\n", "\t\tpath /mcp*\n", 1),
    ("8082 does not strip the canonical email", strip("X-Auth-Request-Email"), "", 2),
    ("8082 does not strip an ALB header", strip("X-Amzn-Oidc-Data"), "", 2),
    ("8082 passes a client's shared secret", strip("X-Proxy-Secret"), "", 1),
    (
        "8082 lets the client choose its address",
        '\t\t\t\theader_up X-Client-Address "{client_ip}"\n',
        "",
        1,
    ),
    (
        "8082 no longer refuses the rest",
        '\thandle {\n\t\trespond "Not found." 404\n\t}\n',
        "",
        2,
    ),
    (
        "8082 does not cap the body",
        "\t\trequest_body {\n\t\t\tmax_size 64KB\n\t\t}\n\n",
        "",
        1,
    ),
    ("8082 answer is cacheable", '\t\t\theader Cache-Control "no-store"\n', "", 2),
    # --- the log
    (
        "the gate's log keeps the query",
        'regexp "^([^?]*)\\?.*$" "$1?[redacted]"',
        'regexp "^nothing$" "$1?[redacted]"',
        1,
    ),
]


def replace_nth(text: str, old: str, new: str, nth: int) -> str | None:
    at = -1
    for _ in range(nth):
        at = text.find(old, at + 1)
        if at < 0:
            return None
    return text[:at] + new + text[at + len(old) :]


def main() -> int:
    if not tp.docker_usable():
        print("docker unavailable; skipping the MCP route's mutation checks")
        return 1 if REQUIRE_TESTS else 0

    main_text = (ROOT / "proxy" / "Caddyfile").read_text(encoding="utf-8")
    gate_text = (ROOT / "proxy" / "Caddyfile.mcp-gate").read_text(encoding="utf-8")
    start, end = main_text.index(MAIN_START), main_text.index(MAIN_END)
    failures = 0

    with tp.rig() as workdir:

        def run(main_copy: str, gate_copy: str, which: str) -> list[str]:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "Caddyfile"
                path.write_text(main_copy, encoding="utf-8")
                shutil.copy(ROOT / "proxy" / "csp.caddy", Path(tmp) / "csp.caddy")
                gate = Path(tmp) / "Caddyfile.mcp-gate"
                gate.write_text(gate_copy, encoding="utf-8")
                tp.CADDYFILE, tp.GATE = path, gate
                tp.failures.clear()
                with contextlib.redirect_stdout(io.StringIO()):
                    if which == "main":
                        tp.check_mcp_route(workdir)
                    else:
                        tp.check_mcp_gate(workdir)
                return list(tp.failures)

        print("The unbroken files")
        for which in ("main", "gate"):
            clean = run(main_text, gate_text, which)
            ok = not clean
            print(f"  {'PASS' if ok else 'FAIL'}  the {which} checks pass a real copy")
            if not ok:
                print("        " + "; ".join(clean[:5]))
                failures += 1

        print("Each guard of the route in proxy/Caddyfile, broken")
        for name, old, new, nth in MAIN:
            region = replace_nth(main_text[start:end], old, new, nth)
            if region is None:
                print(f"  FAIL  {name}  <- the text to break is not in the route")
                failures += 1
                continue
            mutated = main_text[:start] + region + main_text[end:]
            assert mutated != main_text
            noticed = run(mutated, gate_text, "main")
            ok = bool(noticed)
            print(
                f"  {'PASS' if ok else 'FAIL'}  {name} is noticed"
                + (f"  ({len(noticed)} check(s))" if ok else "")
            )
            failures += 0 if ok else 1
        for name, old, new, nth in MAIN_FILE:
            mutated = replace_nth(main_text, old, new, nth)
            if mutated is None:
                print(f"  FAIL  {name}  <- the text to break is not in the file")
                failures += 1
                continue
            noticed = run(mutated, gate_text, "main")
            ok = bool(noticed)
            print(f"  {'PASS' if ok else 'FAIL'}  {name} is noticed")
            failures += 0 if ok else 1

        # Order is not a property to break here, unlike the agent route's: Caddy sorts
        # `handle` blocks by how specific their matcher is, and the dashboard's
        # catch-all has none, so it can never take /mcp whatever order the file is
        # written in. What would break is the route reaching the sign-on handle, and
        # that is what the checks above (no identity set, nothing reaching /api/) are
        # for.

        print("Each guard of the gate, broken")
        for name, old, new, nth in GATE:
            mutated = replace_nth(gate_text, old, new, nth)
            if mutated is None:
                print(f"  FAIL  {name}  <- the text to break is not in the gate")
                failures += 1
                continue
            noticed = run(main_text, mutated, "gate")
            ok = bool(noticed)
            print(
                f"  {'PASS' if ok else 'FAIL'}  {name} is noticed"
                + (f"  ({len(noticed)} check(s))" if ok else "")
            )
            failures += 0 if ok else 1

        tp.CADDYFILE = ROOT / "proxy" / "Caddyfile"
        tp.GATE = ROOT / "proxy" / "Caddyfile.mcp-gate"

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("proxy MCP mutation checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
