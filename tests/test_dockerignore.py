#!/usr/bin/env python3
"""What a `docker build` sends to the daemon, against the real build contexts (#63).

`proxy/Dockerfile` builds with the repository root as its context, and the root
had no `.dockerignore`, so every build uploaded the whole working tree: `.env`
(the database password), `backups/`, `.git/` and the licensed source PDF. The
image never contained them, because the Dockerfile copies two paths. But on a
remote or shared builder the context itself is the exposure, BuildKit caches it,
and one `COPY . .` away from a published secret. `.dockerignore` is the control
that makes that mistake impossible rather than merely absent.

This is an integration test: it builds a throwaway Dockerfile that copies the
WHOLE context and lists it, so what it sees is exactly what the daemon received.
Decoy files stand in for the secrets so the user's real `.env` is never touched.

    pixi run test-dockerignore     (needs Docker; fails under REQUIRE_TESTS without)
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRE_TESTS = bool(os.environ.get("REQUIRE_TESTS"))

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


# Which of these paths exist in the context the daemon received. Asking about
# named paths, rather than listing the whole tree, is deliberate: BuildKit clips
# a long build log, and this repository's tree is thousands of files.
PROBE = (
    "FROM busybox\nCOPY . /ctx\n"
    "RUN for p in $PATHS; do "
    '[ -e "/ctx/$p" ] && echo "SENT $p"; done; true\n'
)

# Things that must never cross to the daemon, per context. Decoys are created
# for the ones that are not always present.
ROOT_FORBIDDEN = [
    ".env.dockerignore-probe",
    "backups/probe.sql.gz.gpg",
    "probe-licensed-source.pdf",
    ".git/",
]
SERVER_FORBIDDEN = [".env.dockerignore-probe", "tests/"]
# The optional MCP service's context (mcp/): the same two things (#164).
MCP_FORBIDDEN = [".env.dockerignore-probe", "tests/"]


def copy_sources(dockerfile: str) -> list[str]:
    """Every path a Dockerfile COPYs from its build context, in order.

    Read from the Dockerfile, not listed here: a list kept by hand is how the proxy
    image stopped building when it began to copy a generated policy file that the
    allowlist in .dockerignore did not admit (#154). A COPY from another stage is not
    from the context.
    """
    sources: list[str] = []
    for line in dockerfile.splitlines():
        parts = line.strip().split()
        if not parts or parts[0].upper() != "COPY":
            continue
        args = [p for p in parts[1:] if not p.startswith("--")]
        if any(p.startswith("--from") for p in parts[1:]) or len(args) < 2:
            continue
        sources += [a for a in args[:-1] if a != "."]
    return sources


ROOT_NEEDED = copy_sources((ROOT / "proxy" / "Dockerfile").read_text(encoding="utf-8"))
SERVER_NEEDED = copy_sources(
    (ROOT / "server" / "Dockerfile").read_text(encoding="utf-8")
)


MCP_NEEDED = copy_sources((ROOT / "mcp" / "Dockerfile").read_text(encoding="utf-8"))


def sent_files(context: Path, workdir: Path, candidates: list[str]) -> list[str]:
    """Which of the candidate paths the daemon received for this context."""
    dockerfile = workdir / "Dockerfile.probe"
    paths = " ".join(c.rstrip("/") for c in candidates)
    dockerfile.write_text(PROBE.replace("$PATHS", paths, 1).replace("$p", "$p"))
    done = subprocess.run(
        [
            "docker",
            "build",
            "--no-cache",
            "--progress=plain",
            "-f",
            str(dockerfile),
            str(context),
        ],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise RuntimeError(done.stderr[-800:])
    return sorted(set(re.findall(r"^#\d+ [\d.]+ SENT (\S+)$", done.stderr, re.M)))


def leaks(files: list[str], forbidden: list[str]) -> list[str]:
    bad = {f.rstrip("/") for f in forbidden}
    return [f for f in files if f in bad]


def missing(files: list[str], needed: list[str]) -> list[str]:
    return [n for n in needed if n.rstrip("/") not in files]


def with_decoys(context: Path, names: list[str]):
    """Create decoy files, returning what to remove afterwards."""
    made: list[Path] = []
    for name in names:
        if name.endswith("/"):
            continue
        path = context / name
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("decoy\n")
        made.append(path)
    return made


def main() -> int:
    if (
        not shutil.which("docker")
        or subprocess.run(["docker", "info"], capture_output=True).returncode
    ):
        print("docker unavailable; skipping dockerignore checks")
        return 1 if REQUIRE_TESTS else 0

    workdir = Path(tempfile.mkdtemp(prefix="chai-dockerignore-"))
    made_dirs: list[Path] = []
    backups_existed = (ROOT / "backups").exists()
    try:
        print("The pure rules")
        check(
            "a forwarded .env is noticed",
            bool(leaks([".env", "a"], [".env"])),
        )
        check("a clean listing passes", not leaks(["proxy/Caddyfile"], [".env"]))
        check("a forbidden directory is noticed", bool(leaks([".git"], [".git/"])))
        check("a missing needed file is noticed", bool(missing([], ["a"])))
        sample = (
            "FROM x AS build\nCOPY a.txt b/ /dest/\nCOPY --chown=1:1 c.caddy /etc/c\n"
            "COPY --from=build /out /srv\nCOPY . /ctx\n  copy d /d\n"
        )
        check(
            "the COPY sources are read from a Dockerfile, skipping other stages",
            copy_sources(sample) == ["a.txt", "b/", "c.caddy", "d"],
            str(copy_sources(sample)),
        )
        check(
            "the proxy image's sources include the generated policy file",
            "proxy/csp.caddy" in ROOT_NEEDED and "docs/app/" in ROOT_NEEDED,
            str(ROOT_NEEDED),
        )

        probe = [*ROOT_FORBIDDEN, ".env", *ROOT_NEEDED]
        server_probe = [*SERVER_FORBIDDEN, ".env", *SERVER_NEEDED]
        print("The proxy image's context (the repository root)")
        decoys = with_decoys(ROOT, ROOT_FORBIDDEN)
        try:
            files = sent_files(ROOT, workdir, probe)
            check(
                "no secret, backup, PDF or .git reaches the daemon",
                not leaks(files, [*ROOT_FORBIDDEN, ".env"]),
                ", ".join(leaks(files, [*ROOT_FORBIDDEN, ".env"])[:8]),
            )
            check(
                "what the Dockerfile COPYs is still sent",
                not missing(files, ROOT_NEEDED),
                ", ".join(missing(files, ROOT_NEEDED)),
            )

            # The mutation: take the ignore file away and the decoys must leak,
            # which proves this test can see the problem it guards against.
            ignore = ROOT / ".dockerignore"
            if ignore.exists():
                aside = workdir / "dockerignore.aside"
                shutil.move(ignore, aside)
                try:
                    exposed = leaks(sent_files(ROOT, workdir, probe), ROOT_FORBIDDEN)
                finally:
                    shutil.move(aside, ignore)
                check(
                    "without .dockerignore the same decoys DO leak (the test can fail)",
                    len(exposed) >= 3,
                    ", ".join(exposed),
                )
        finally:
            for path in decoys:
                path.unlink(missing_ok=True)
            if not backups_existed:
                shutil.rmtree(ROOT / "backups", ignore_errors=True)

        print("The API image's context (server/)")
        server = ROOT / "server"
        decoys = with_decoys(server, SERVER_FORBIDDEN)
        try:
            files = sent_files(server, workdir, server_probe)
            check(
                "no env file or test reaches the daemon",
                not leaks(files, SERVER_FORBIDDEN),
                ", ".join(leaks(files, SERVER_FORBIDDEN)[:8]),
            )
            check(
                "what the Dockerfile COPYs is still sent",
                not missing(files, SERVER_NEEDED),
                ", ".join(missing(files, SERVER_NEEDED)),
            )
        finally:
            for path in decoys:
                path.unlink(missing_ok=True)

        print("The MCP image's context (mcp/)")
        mcp = ROOT / "mcp"
        decoys = with_decoys(mcp, MCP_FORBIDDEN)
        try:
            files = sent_files(mcp, workdir, [*MCP_FORBIDDEN, ".env", *MCP_NEEDED])
            check(
                "no env file or test reaches the daemon (mcp)",
                not leaks(files, MCP_FORBIDDEN),
                ", ".join(leaks(files, MCP_FORBIDDEN)[:8]),
            )
            check(
                "what the MCP Dockerfile COPYs is still sent",
                not missing(files, MCP_NEEDED),
                ", ".join(missing(files, MCP_NEEDED)),
            )
        finally:
            for path in decoys:
                path.unlink(missing_ok=True)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        for d in made_dirs:
            shutil.rmtree(d, ignore_errors=True)

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("dockerignore checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
