#!/usr/bin/env python3
"""The agent route's guards in proxy/Caddyfile, each shown to fail (#164).

tests/test_proxy_identity.py checks the real Caddyfile, against a real Caddy, for the
agent API's route: only the three GET routes get through, every identity header a
client sends is stripped, the proxy sets none, and every other route is as it was. A
check nobody has seen fail is a claim, so this breaks a COPY of the Caddyfile in each
way that matters, runs the same checks against a real Caddy, and demands that they
notice. Needs Docker.

    pixi run test-proxy-agent
"""

from __future__ import annotations

import importlib.util
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

AGENT_BLOCK_START = "	handle @agentread {"
STRIP = "			request_header -{name}\n"

# (name, old text, new text). Each is applied inside the agent block, or to the
# whole file where it says so; the harness refuses a mutation that changes nothing.
HANDOFF_LINE = '\t\t\t\theader_up X-Proxy-Secret "{$PROXY_SHARED_SECRET}"\n'
AFTER_HANDOFF = (
    "\t\t\t\ttransport http {\n\t\t\t\t\tdial_timeout 5s\n\t\t\t\t}\n"
    "\t\t\t}\n\t\t}\n\t}\n\n\thandle /api/agent/* {"
)
MUTATIONS: list[tuple[str, str, str]] = [
    (
        "the log keeps a query string on the agent routes",
        "(?i)^(/api/agent/[^?]*)",
        "(?i)^(/api/nothing/[^?]*)",
    ),
    (
        "a write verb is forwarded",
        "		method GET\n		path /api/agent/me",
        "		method GET POST DELETE\n		path /api/agent/me",
    ),
    (
        "any path under the prefix is forwarded",
        "		path /api/agent/me /api/agent/portfolio /api/agent/projects/*",
        "		path /api/agent/*",
    ),
    (
        "the canonical email header is not stripped",
        STRIP.format(name="X-Auth-Request-Email"),
        "",
    ),
    (
        "the canonical user header is not stripped",
        STRIP.format(name="X-Auth-Request-User"),
        "",
    ),
    (
        "the front door's email header is not stripped",
        STRIP.format(name="X-Forwarded-Email"),
        "",
    ),
    (
        "an IAP header is not stripped",
        STRIP.format(name="X-Goog-Authenticated-User-Email"),
        "",
    ),
    (
        "an Easy Auth header is not stripped",
        STRIP.format(name="X-Ms-Client-Principal-Name"),
        "",
    ),
    (
        "an ALB header is not stripped",
        STRIP.format(name="X-Amzn-Oidc-Data"),
        "",
    ),
    (
        "the proxy sets an identity on the agent route",
        '			header Cache-Control "no-store"\n',
        '			request_header X-Auth-Request-Email "{$IDENTITY_EMAIL_SOURCE}"\n'
        '			header Cache-Control "no-store"\n',
    ),
    (
        "the answer is cacheable",
        '			header Cache-Control "no-store"\n',
        "",
    ),
    (
        "the fallback no longer refuses the rest of the prefix",
        '	handle /api/agent/* {\n		respond "Not found." 404\n	}\n',
        "",
    ),
    (
        "the shared secret is not sent on the agent route",
        HANDOFF_LINE + AFTER_HANDOFF,
        AFTER_HANDOFF,
    ),
]


def main() -> int:
    if not tp.docker_usable():
        print("docker unavailable; skipping the agent route's mutation checks")
        return 1 if REQUIRE_TESTS else 0

    original = (ROOT / "proxy" / "Caddyfile").read_text(encoding="utf-8")
    agent_start = original.index(AGENT_BLOCK_START)
    agent_end = original.index("	handle /api/* {")
    failures = 0

    with tp.rig() as workdir:

        def run_against(caddyfile_text: str) -> list[str]:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "Caddyfile"
                path.write_text(caddyfile_text, encoding="utf-8")
                shutil.copy(ROOT / "proxy" / "csp.caddy", Path(tmp) / "csp.caddy")
                tp.CADDYFILE = path
                tp.failures.clear()
                import contextlib
                import io

                with contextlib.redirect_stdout(io.StringIO()):
                    tp.check_agent_route(workdir)
                return list(tp.failures)

        print("The unbroken Caddyfile")
        clean = run_against(original)
        ok = not clean
        print(
            f"  {'PASS' if ok else 'FAIL'}  the agent route's checks pass a copy "
            "of the real file"
        )
        if not ok:
            print("        " + "; ".join(clean[:5]))
            failures += 1

        print("Each guard, broken")
        for name, old, new in MUTATIONS:
            block = original[agent_start:agent_end]
            if old in block:
                mutated = (
                    original[:agent_start]
                    + block.replace(old, new, 1)
                    + original[agent_end:]
                )
            elif old in original:
                mutated = original.replace(old, new, 1)
            else:
                print(f"  FAIL  {name}  <- the text to break is not in the Caddyfile")
                failures += 1
                continue
            assert mutated != original
            noticed = run_against(mutated)
            ok = bool(noticed)
            print(
                f"  {'PASS' if ok else 'FAIL'}  {name} is noticed"
                + (f"  ({len(noticed)} check(s))" if ok else "")
            )
            failures += 0 if ok else 1

        # The order of the handles is the property: the agent route must come before
        # the single sign-on route, which would otherwise take it and ask for a session.
        region = original[agent_start:agent_end]
        dashboard = original.index(
            "\t# " + "-" * 73 + "\n	# The dashboard: one pre-built"
        )
        moved = (
            original[:agent_start]
            + original[agent_end:dashboard]
            + region
            + original[dashboard:]
        )
        assert moved != original and moved.count("handle @agentread") == 1
        noticed = run_against(moved)
        print(
            f"  {'PASS' if noticed else 'FAIL'}  the agent route below the single "
            "sign-on route is noticed"
        )
        failures += 0 if noticed else 1

        # Reading the real file again: the harness must not have changed it.
        tp.CADDYFILE = ROOT / "proxy" / "Caddyfile"

    print()
    if failures:
        print(f"{failures} check(s) failed")
        return 1
    print("proxy agent mutation checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
