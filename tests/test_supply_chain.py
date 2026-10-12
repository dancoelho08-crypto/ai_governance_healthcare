#!/usr/bin/env python3
"""What is running, how we learn it is vulnerable, and how fast we say we fix it (#37).

A hospital's third-party risk questionnaire asks three things this repository could not
answer: what is in it (no lock, floating tags), how do you learn about a vulnerability
in it (nothing watched), and how fast do you fix one (no SECURITY.md). A rebuild today
and a rebuild in six months produced different images from identical source, and
`docker compose up -d` does not pull a newer base image, so a deployment could sit on a
vulnerable one indefinitely while appearing current.

These are checks on the repository's own files, each with a mutation test so a rule that
stops noticing is itself noticed, plus (with Docker) a build of the real image.

    pixi run test-supply-chain    (the image build needs Docker)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))
SHA = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


# --- the rules: text in, problems out ---------------------------------------


def unpinned_lock_lines(text: str) -> list[str]:
    """Every requirement in a pip lock must be `==` pinned and carry a hash."""
    problems = []
    for block in re.split(r"\n(?=[A-Za-z0-9_.\-\[\]]+[=<>!~])", text):
        head = block.strip().splitlines()[0] if block.strip() else ""
        if not head or head.startswith("#"):
            continue
        name = re.split(r"[=<>!~ \\]", head)[0]
        if "==" not in head:
            problems.append(f"{name} is not pinned with ==")
        if "--hash=sha256:" not in block:
            problems.append(f"{name} has no hash")
    return problems


def lock_misses(lock: str, dependencies: list[str]) -> list[str]:
    """Top-level dependencies in pyproject that the lock does not pin."""
    pinned = {
        m.group(1).lower().replace("_", "-")
        for m in re.finditer(r"^([A-Za-z0-9_.\-]+)==", lock, re.M)
    }
    wanted = {
        re.split(r"[\[<>=!~ ]", dep)[0].lower().replace("_", "-")
        for dep in dependencies
    }
    return sorted(wanted - pinned)


def floating_from_lines(dockerfile: str) -> list[str]:
    return [
        line.strip()
        for line in dockerfile.splitlines()
        if line.strip().upper().startswith("FROM ")
        and not DIGEST.search(line.strip().split(" AS ")[0].split(" as ")[0])
    ]


def floating_compose_images(compose: dict) -> list[str]:
    """Images compose pulls (not the one it builds) must be pinned by digest."""
    out = []
    for name, svc in compose.get("services", {}).items():
        image = str(svc.get("image", ""))
        if not image or "build" in svc or "${" in image:
            continue
        if not DIGEST.search(image):
            out.append(f"{name}: {image}")
    return out


def unpinned_actions(workflow_text: str) -> list[str]:
    out = []
    for line in workflow_text.splitlines():
        match = re.match(r"^\s*(?:-\s+)?uses:\s*([^\s#]+)", line)
        if not match:
            continue
        ref = match.group(1)
        if ref.startswith("./") or ref.startswith("docker://"):
            continue
        _, _, version = ref.partition("@")
        if not SHA.fullmatch(version):
            out.append(ref)
    return out


def dependabot_problems(config: dict) -> list[str]:
    """Every shipped ecosystem is watched, in a directory that has its files."""
    want = {
        ("pip", "/server", "requirements.txt"),
        ("docker", "/server", "Dockerfile"),
        ("docker", "/proxy", "Dockerfile"),
        ("pip", "/mcp", "requirements.txt"),
        ("docker", "/mcp", "Dockerfile"),
        ("docker-compose", "/", "compose.yaml"),
        ("github-actions", "/", ".github/workflows"),
    }
    have = {
        (u.get("package-ecosystem"), u.get("directory"))
        for u in config.get("updates", [])
    }
    problems = [
        f"{eco} {where} is not watched"
        for eco, where, _ in want
        if (eco, where) not in have
    ]
    # pydantic pins pydantic-core to one exact version, so a bump of the core alone
    # makes the API fail to import (PR #112). It moves only with pydantic itself.
    updates = config.get("updates", [])
    pip = [u for u in updates if u.get("package-ecosystem") == "pip"]
    for update in pip:
        ignored = {i.get("dependency-name") for i in update.get("ignore", [])}
        if "pydantic-core" not in ignored:
            problems.append(
                "pip does not ignore pydantic-core, which moves with pydantic"
            )
    for update in config.get("updates", []):
        if not update.get("schedule", {}).get("interval"):
            problems.append(f"{update.get('package-ecosystem')} has no schedule")
    for _eco, where, manifest in want:
        if not (ROOT / where.lstrip("/") / manifest).exists():
            problems.append(f"{where}/{manifest} does not exist")
    return problems


def security_policy_problems(text: str) -> list[str]:
    needed = {
        "how to report": "report",
        "how remediation is handled": "remediat",
        "severity": "critical",
        "what is in scope": "scope",
    }
    low = text.lower()
    return [
        f"SECURITY.md lacks {what}" for what, word in needed.items() if word not in low
    ]


# The owner commits to no response or fix times (D-58): a one-developer project
# cannot keep them, and a stated target reads as a commitment to whoever relies on it.
TIME_PROMISE = re.compile(
    r"\bwithin\s+\d+|\b\d+\s+(?:business\s+)?(?:hours?|days?|weeks?)\b", re.I
)


def time_promises(text: str) -> list[str]:
    return [m.group(0) for m in TIME_PROMISE.finditer(text)]


def push_to_default_branch(workflow_text: str) -> list[str]:
    """A scheduled job must not `git push` to the branch main protects."""
    return [
        line.strip()
        for line in workflow_text.splitlines()
        if re.match(r"^\s*git push\s*$", line)
        or re.match(r"^\s*git push\s+origin\s+(HEAD:)?(refs/heads/)?main\b", line)
    ]


def image_scan_problems(workflow: dict) -> list[str]:
    text = yaml.safe_dump(workflow)
    problems = []
    if "trivy" not in text:
        problems.append("no trivy scan")
    if "HIGH,CRITICAL" not in text:
        problems.append("does not scan HIGH,CRITICAL")
    if "'schedule'" not in str(
        workflow.get(True, workflow.get("on", {}))
    ) and "schedule" not in str(workflow.get(True) or workflow.get("on")):
        problems.append("no weekly schedule")
    return problems


def main() -> int:
    lock = (ROOT / "server" / "requirements.txt").read_text(encoding="utf-8")
    pyproject = tomllib.loads((ROOT / "server" / "pyproject.toml").read_text())
    deps = pyproject["project"]["dependencies"]
    server_df = (ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
    proxy_df = (ROOT / "proxy" / "Dockerfile").read_text(encoding="utf-8")
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))

    print("The server's dependencies are locked, with hashes")
    check(
        "every locked requirement is pinned and hashed",
        not unpinned_lock_lines(lock),
        str(unpinned_lock_lines(lock)[:3]),
    )
    check("and there are some", lock.count("--hash=sha256:") > 20)
    check(
        "every pyproject dependency is in the lock",
        not lock_misses(lock, deps),
        str(lock_misses(lock, deps)),
    )
    check(
        "an unpinned requirement is noticed",
        bool(unpinned_lock_lines("foo>=1 \\\n    --hash=sha256:" + "a" * 64)),
    )
    check(
        "a requirement with no hash is noticed", bool(unpinned_lock_lines("foo==1.0\n"))
    )
    check(
        "a dependency missing from the lock is noticed",
        lock_misses("foo==1 \\\n", ["foo", "bar>=2"]) == ["bar"],
    )
    check(
        "the server image installs only from the lock, verifying hashes",
        "--require-hashes" in server_df and "requirements.txt" in server_df,
    )
    check(
        "and does not upgrade pip from the network or build the project from PyPI",
        "--upgrade pip" not in server_df
        and not re.search(r"pip install\s+\.", server_df),
        "an unpinned install defeats the lock",
    )
    check(
        "and does not ship pip in the runtime venv",
        re.search(r"pip uninstall[^\n]*\bpip\b", server_df) is not None,
    )

    print("The MCP service's dependencies are locked, with hashes (#164)")
    mcp_lock = (ROOT / "mcp" / "requirements.txt").read_text(encoding="utf-8")
    mcp_deps = tomllib.loads((ROOT / "mcp" / "pyproject.toml").read_text())["project"][
        "dependencies"
    ]
    mcp_df = (ROOT / "mcp" / "Dockerfile").read_text(encoding="utf-8")
    check(
        "every locked MCP requirement is pinned and hashed",
        not unpinned_lock_lines(mcp_lock),
        str(unpinned_lock_lines(mcp_lock)[:3]),
    )
    check(
        "every MCP dependency is in its lock",
        not lock_misses(mcp_lock, mcp_deps),
        str(lock_misses(mcp_lock, mcp_deps)),
    )
    check(
        "the MCP image installs only from the lock, verifying hashes, and ships no pip",
        "--require-hashes" in mcp_df
        and "requirements.txt" in mcp_df
        and re.search(r"pip uninstall[^\n]*\bpip\b", mcp_df) is not None
        and "--upgrade pip" not in mcp_df,
    )

    print("Base images are pinned by digest")
    check(
        "the API image's bases are pinned",
        not floating_from_lines(server_df),
        str(floating_from_lines(server_df)),
    )
    check(
        "the MCP image's bases are pinned",
        not floating_from_lines(mcp_df),
        str(floating_from_lines(mcp_df)),
    )
    check(
        "the proxy image's base is pinned",
        not floating_from_lines(proxy_df),
        str(floating_from_lines(proxy_df)),
    )
    check(
        "the images compose pulls are pinned",
        not floating_compose_images(compose),
        str(floating_compose_images(compose)),
    )
    check(
        "a floating FROM is noticed",
        bool(floating_from_lines("FROM python:3.12-slim AS b")),
    )
    check(
        "a digest-pinned FROM passes",
        not floating_from_lines("FROM python:3.12-slim@sha256:" + "a" * 64 + " AS b"),
    )
    check(
        "a floating compose image is noticed",
        bool(floating_compose_images({"services": {"db": {"image": "postgres:17"}}})),
    )
    check(
        "the image compose builds is not mistaken for a floating pull",
        not floating_compose_images(
            {"services": {"api": {"image": "x:local", "build": {"context": "."}}}}
        ),
    )

    print("GitHub Actions are pinned by commit")
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        check(
            f"{wf.name}: every `uses:` is a commit SHA",
            not unpinned_actions(wf.read_text(encoding="utf-8")),
            str(unpinned_actions(wf.read_text(encoding="utf-8"))),
        )
    check(
        "a tag is noticed",
        bool(unpinned_actions("      - uses: actions/checkout@v4\n")),
    )
    check("a branch is noticed", bool(unpinned_actions("uses: foo/bar@main")))
    check("a SHA passes", not unpinned_actions("- uses: foo/bar@" + "a" * 40 + " # v1"))

    print("Something watches for updates")
    dep = yaml.safe_load(
        (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    )
    check(
        "dependabot covers pip, both Dockerfiles, compose and the actions",
        not dependabot_problems(dep),
        str(dependabot_problems(dep)),
    )
    no_ignore = yaml.safe_load(yaml.safe_dump(dep))
    for u in no_ignore["updates"]:
        u.pop("ignore", None)
    check(
        "dropping the pydantic-core ignore is noticed",
        any("pydantic-core" in p for p in dependabot_problems(no_ignore)),
    )
    check(
        "a missing ecosystem is noticed",
        bool(dependabot_problems({"updates": dep["updates"][1:]})),
    )

    print("A vulnerability scan runs, and the scheduled job cannot write to main")
    scan = yaml.safe_load((ROOT / ".github" / "workflows" / "security.yml").read_text())
    check(
        "security.yml scans HIGH and CRITICAL, on a schedule",
        not image_scan_problems(scan),
        str(image_scan_problems(scan)),
    )
    chai = (ROOT / ".github" / "workflows" / "chai-updates.yml").read_text(
        encoding="utf-8"
    )
    check(
        "chai-updates.yml no longer pushes to the protected branch",
        not push_to_default_branch(chai),
        str(push_to_default_branch(chai)),
    )
    check(
        "a bare `git push` is noticed",
        bool(push_to_default_branch("        git push\n")),
    )
    check(
        "pushing a feature branch is not",
        not push_to_default_branch("  git push origin HEAD:refs/heads/chai-snapshot\n"),
    )

    print("A policy says how to report and how fast it is fixed")
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    check(
        "SECURITY.md has the four things a reviewer asks for",
        not security_policy_problems(policy),
        str(security_policy_problems(policy)),
    )
    check(
        "an empty policy is noticed", len(security_policy_problems("# Security")) == 4
    )
    check(
        "SECURITY.md promises no response or fix times",
        not time_promises(policy),
        ", ".join(time_promises(policy)),
    )
    check(
        "a stated time is noticed (mutation)",
        bool(time_promises("Acknowledge within 5 business days."))
        and bool(time_promises("Critical fixes in 14 days."))
        and not time_promises("Handled in order of severity."),
    )

    print("Updating is documented, because `up -d` alone does not")
    docs = (ROOT / "docs" / "deploy.md").read_text(encoding="utf-8")
    section = docs[docs.index("### Updating") :] if "### Updating" in docs else ""
    check(
        "deploy.md says docker compose up -d does not pick up a new base image",
        "does not" in section and "pull" in section and "--pull" in section,
        section[:200],
    )

    if (
        shutil.which("docker")
        and subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    ):
        print("The real image builds from the lock, and ships no pip")
        tag = "chai-supply-chain-test"
        built = subprocess.run(
            ["docker", "build", "-q", "-t", tag, str(ROOT / "server")],
            capture_output=True,
            text=True,
        )
        check("it builds", built.returncode == 0, built.stderr[-400:])
        if built.returncode == 0:
            imp = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--entrypoint",
                    "/opt/venv/bin/python",
                    tag,
                    "-c",
                    "import fastapi, uvicorn, asyncpg, pydantic; print('ok')",
                ],
                capture_output=True,
                text=True,
            )
            check(
                "the locked dependencies import",
                imp.stdout.strip() == "ok",
                imp.stderr[-300:],
            )
            pip = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--entrypoint",
                    "/opt/venv/bin/python",
                    tag,
                    "-m",
                    "pip",
                    "--version",
                ],
                capture_output=True,
                text=True,
            )
            check("pip is not in the runtime image", pip.returncode != 0, pip.stdout)
            versions = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--entrypoint",
                    "/opt/venv/bin/python",
                    tag,
                    "-c",
                    "import importlib.metadata as m; print(m.version('fastapi'))",
                ],
                capture_output=True,
                text=True,
            )
            locked = re.search(r"^fastapi==([\d.]+)", lock, re.M).group(1)
            check(
                "the installed version is the locked one",
                versions.stdout.strip() == locked,
                f"{versions.stdout.strip()} vs {locked}",
            )
        subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)

        print("The MCP image builds from its lock, ships no pip, and runs unprivileged")
        mcp_tag = "chai-supply-chain-test-mcp"
        built = subprocess.run(
            ["docker", "build", "-q", "-t", mcp_tag, str(ROOT / "mcp")],
            capture_output=True,
            text=True,
        )
        check("the MCP image builds", built.returncode == 0, built.stderr[-400:])
        if built.returncode == 0:

            def in_image(*args: str) -> subprocess.CompletedProcess:
                return subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--entrypoint",
                        "/opt/venv/bin/python",
                        mcp_tag,
                        *args,
                    ],
                    capture_output=True,
                    text=True,
                )

            imp = in_image("-c", "import mcp, httpx, pydantic, uvicorn; print('ok')")
            check(
                "the MCP image's locked dependencies import",
                imp.stdout.strip() == "ok",
                imp.stderr[-300:],
            )
            # The filesystem itself, not an import through the venv: the base image's
            # pip is a binary in /usr/local/bin and a package of its own interpreter,
            # which `python -m pip` through the venv cannot see (review L3).
            probe = (
                "import glob, importlib.util as u\n"
                "found = [p for pat in ("
                "'/usr/local/bin/pip*', '/usr/local/bin/easy_install*', "
                "'/usr/local/lib/python3*/site-packages/pip*', "
                "'/usr/local/lib/python3*/site-packages/setuptools*', "
                "'/usr/local/lib/python3*/site-packages/pkg_resources*', "
                "'/usr/local/lib/python3*/ensurepip', "
                "'/opt/venv/lib/python3*/site-packages/pip*', "
                "'/opt/venv/lib/python3*/site-packages/setuptools*') "
                "for p in glob.glob(pat)]\n"
                "print(found, u.find_spec('pip'), u.find_spec('ensurepip'), "
                "u.find_spec('setuptools'))\n"
            )
            gone = in_image("-c", probe)
            check(
                "no pip, setuptools or ensurepip is anywhere in the MCP runtime image",
                gone.stdout.strip() == "[] None None None",
                gone.stdout + gone.stderr,
            )
            check(
                "and the system interpreter cannot import pip either",
                subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--entrypoint",
                        "/usr/local/bin/python",
                        mcp_tag,
                        "-c",
                        "import pip",
                    ],
                    capture_output=True,
                ).returncode
                != 0,
            )
            locked = re.search(r"^mcp==([\d.]+)", mcp_lock, re.M).group(1)
            got = in_image(
                "-c", "import importlib.metadata as m; print(m.version('mcp'))"
            )
            check(
                "the installed MCP SDK is the locked one",
                got.stdout.strip() == locked,
                f"{got.stdout.strip()} vs {locked}",
            )
            facts = json.loads(
                subprocess.run(
                    ["docker", "inspect", mcp_tag], capture_output=True, text=True
                ).stdout
            )[0]["Config"]
            check(
                "it runs as a numeric non-root user, has a health check, and is "
                "started directly, not through a shell",
                facts["User"] not in ("", "0", "root")
                and facts["User"].split(":")[0].isdigit()
                and facts["Healthcheck"]["Test"][0] == "CMD"
                and facts["Cmd"] == ["python", "-m", "chai_mcp"]
                and not facts.get("Entrypoint"),
                str({k: facts.get(k) for k in ("User", "Cmd", "Entrypoint")}),
            )
            shell = in_image("-c", "import pwd; print(pwd.getpwuid(10002).pw_shell)")
            check(
                "its user has no login shell",
                shell.stdout.strip() == "/usr/sbin/nologin",
                shell.stdout + shell.stderr,
            )
        subprocess.run(["docker", "rmi", "-f", mcp_tag], capture_output=True)
    elif REQUIRE_TESTS:
        check("docker is available to build the image", False, "REQUIRE_TESTS is set")
    else:
        print("  skip  docker unavailable: the image build is not checked")

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("supply chain checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
