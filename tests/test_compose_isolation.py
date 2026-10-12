#!/usr/bin/env python3
"""The network isolation the whole security model rests on, as a test.

The API trusts an identity header, so it is only safe if nothing can reach it
except the proxy that sets that header. docs/self-hosting.md calls this "not
hardening, it is the security model", and says compose.yaml enforces it "with
networking rather than with a convention". Until now the only check was
`make check-isolation`, a manual target against a running stack that nothing in
CI ran, and one step of which asserts nothing (#56).

This reads the real compose.yaml and fails if the property is edited away:

* the API publishes no host port, and neither does the database;
* the database is only on a network that is `internal: true` (no route off the host);
* the only service on the internet-facing network besides the API is the proxy;
* the proxy publishes on loopback by default, because the stack speaks plain HTTP;
* the dev override (which DOES publish the API) is a named file, never
  compose.override.yaml, which a bare `docker compose up` would pick up silently;
* the database lives on a named volume (so `down` keeps the data) and its image is
  pinned to a major version (Postgres does not migrate its on-disk format);
* the page the proxy serves and the manifest the migrate job loads the retirement
  rules from are one build directory, APP_DIR (D-76), read-only, with today's paths
  as the defaults;
* the optional MCP service (#164, R-73, D-91) is off unless its profile is asked for,
  is alone on an internal network with one Caddy gate, holds no credential, and its
  image is non-root with no shell, locked and digest-pinned.

Each rule has a mutation test: break a copy of the real file and demand it notice.

    pixi run test-compose
"""

from __future__ import annotations

import copy
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "compose.yaml"
DEV = ROOT / "compose.dev.yaml"

API, DB, PROXY = "api", "db", "proxy"
EDGE, DATA = "edge", "data"
MCP, MCP_GATE, AGENT = "mcp", "mcp-gate", "agent"
MCP_PROFILE = "agent-mcp"
# What `docker compose up` starts: everything without a profile. Adding a service here
# is a decision, and this list is where it is made.
DEFAULT_SERVICES = {"db", "api", "migrate", "proxy", "proxy-perms"}
VOLUME = "pgdata"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def load() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def service(compose: dict, name: str) -> dict:
    return compose.get("services", {}).get(name, {})


# --- the rules: parsed compose in, problems out ------------------------------


def published_ports(compose: dict, name: str) -> list[str]:
    return [str(p) for p in service(compose, name).get("ports", [])]


def api_ports(compose: dict) -> list[str]:
    return [f"api publishes {p}" for p in published_ports(compose, API)]


def db_ports(compose: dict) -> list[str]:
    return [f"db publishes {p}" for p in published_ports(compose, DB)]


def db_network(compose: dict) -> list[str]:
    nets = service(compose, DB).get("networks", [])
    nets = list(nets.keys()) if isinstance(nets, dict) else list(nets)
    problems = []
    if nets != [DATA]:
        problems.append(f"db must be on [{DATA}] only, found {nets}")
    if not (compose.get("networks", {}).get(DATA) or {}).get("internal"):
        problems.append(
            f"network '{DATA}' is not internal: true, so the db can route off the host"
        )
    return problems


def edge_members(compose: dict) -> list[str]:
    """Who shares the internet-facing network with the API. Only the proxy may."""
    members = []
    for name, svc in compose.get("services", {}).items():
        nets = svc.get("networks", [])
        nets = list(nets.keys()) if isinstance(nets, dict) else list(nets)
        if EDGE in nets:
            members.append(name)
    allowed = {API, PROXY, MCP_GATE}
    return [
        f"{m} is on '{EDGE}', which would let it reach the API and forge identity"
        for m in members
        if m not in allowed
    ]


def proxy_binds_loopback(compose: dict) -> list[str]:
    ports = published_ports(compose, PROXY)
    if not ports:
        return ["the proxy publishes no port"]
    bad = [p for p in ports if not p.startswith("${HTTP_BIND:-127.0.0.1}:")]
    return [f"the proxy publishes {p}, which does not default to loopback" for p in bad]


def database_persists(compose: dict) -> list[str]:
    mounts = service(compose, DB).get("volumes", [])
    problems = []
    if not any(str(m).startswith(f"{VOLUME}:") for m in mounts):
        problems.append(f"db does not mount the named volume '{VOLUME}'")
    if VOLUME not in (compose.get("volumes") or {}):
        problems.append(f"'{VOLUME}' is not declared as a named volume")
    return problems


def database_image_pinned(compose: dict) -> list[str]:
    image = str(service(compose, DB).get("image", ""))
    return (
        []
        if re.fullmatch(r"postgres:\d+(@sha256:[0-9a-f]{64})?", image)
        else [
            f"db image is '{image}'; pin a major version (postgres:NN), because "
            "Postgres "
            "does not migrate its on-disk format"
        ]
    )


def override_file_is_named() -> list[str]:
    stray = [
        n
        for n in (
            "compose.override.yaml",
            "compose.override.yml",
            "docker-compose.override.yml",
        )
        if (ROOT / n).exists()
    ]
    return [
        f"{n} exists, and a bare `docker compose up` would pick it up silently"
        for n in stray
    ]


def shared_secret_reaches_both_ends(compose: dict) -> list[str]:
    """The API checks PROXY_SHARED_SECRET and only the proxy can send it (#61).

    It was documented while no shipped config sent it, so setting it on the API
    made every request 403. Both services must be handed the same variable, or
    the control either never turns on or breaks the stack.
    """
    want = "${PROXY_SHARED_SECRET:-}"
    return [
        f"{name} does not receive PROXY_SHARED_SECRET as {want}"
        for name in (API, PROXY)
        if service(compose, name).get("environment", {}).get("PROXY_SHARED_SECRET")
        != want
    ]


MIGRATE = "migrate"
OWNER_SECRETS = ("POSTGRES_PASSWORD", "POSTGRES_USER", "DATABASE_URL")
PROXY_INIT = "proxy-perms"
NON_ROOT = {"0", "root", ""}


def _security_opts(svc: dict) -> list[str]:
    return [str(o) for o in svc.get("security_opt", [])]


def container_hardening(compose: dict) -> list[str]:
    """The baseline a hospital's container standard asks for (#50).

    The proxy is the only service reachable from outside and it ran as root with
    every default capability; the API's image already drops to uid 10001. No
    service had a memory limit, so any one could take the host's memory. The
    rate limiter's own docstring says the hard protections are elsewhere, and a
    memory limit is one of the elsewheres.
    """
    problems = []
    for name, svc in compose.get("services", {}).items():
        if svc.get("privileged"):
            problems.append(f"{name} is privileged")
        if "no-new-privileges:true" not in _security_opts(svc):
            problems.append(f"{name} lacks security_opt no-new-privileges:true")
        if not svc.get("mem_limit"):
            problems.append(f"{name} has no mem_limit")
        if not svc.get("pids_limit"):
            problems.append(f"{name} has no pids_limit")
        if not svc.get("cpus"):
            problems.append(f"{name} has no cpus limit")

    for name in (API, PROXY, MIGRATE):
        svc = service(compose, name)
        if "ALL" not in [str(c).upper() for c in svc.get("cap_drop", [])]:
            problems.append(f"{name} does not cap_drop ALL")
        if svc.get("read_only") is not True:
            problems.append(f"{name} does not have a read-only root filesystem")
    adds = {str(c).upper() for c in service(compose, API).get("cap_add", [])}
    if adds:
        problems.append(f"api adds back capabilities it does not need: {sorted(adds)}")
    adds = {str(c).upper() for c in service(compose, PROXY).get("cap_add", [])}
    if adds - {"NET_BIND_SERVICE"}:
        problems.append(f"proxy adds back more than NET_BIND_SERVICE: {sorted(adds)}")

    user = str(service(compose, PROXY).get("user", "")).split(":")[0]
    if user in NON_ROOT:
        problems.append("proxy runs as root: set a numeric non-root user")

    # A non-root proxy cannot write the named volumes, which are root-owned, so a
    # one-shot root service fixes their ownership. It must stay off every network
    # and drop everything but CHOWN, or it is a new way in.
    init = service(compose, PROXY_INIT)
    if not init:
        problems.append(f"{PROXY_INIT} is missing, so the non-root proxy cannot write")
    else:
        if init.get("network_mode") != "none":
            problems.append(f"{PROXY_INIT} has network access")
        if init.get("networks"):
            problems.append(f"{PROXY_INIT} is on a network")
        if "ALL" not in [str(c).upper() for c in init.get("cap_drop", [])]:
            problems.append(f"{PROXY_INIT} does not cap_drop ALL")
        if {str(c).upper() for c in init.get("cap_add", [])} - {
            "CHOWN",
            "DAC_READ_SEARCH",
        }:
            problems.append(f"{PROXY_INIT} adds back more than it needs")
        gate = (service(compose, PROXY).get("depends_on") or {}).get(PROXY_INIT, {})
        if gate.get("condition") != "service_completed_successfully":
            problems.append(f"proxy does not wait for {PROXY_INIT} to finish")
    return problems


def cloud_proxy_image_is_unprivileged(dockerfile: str) -> list[str]:
    """proxy/Dockerfile is what Cloud Run, ECS and Container Apps actually run, so it
    must not diverge from the compose service on the one service reachable from
    outside (#50)."""
    problems = []
    user = re.search(r"^USER\s+65532(:65532)?\s*$", dockerfile, re.M)
    if not user:
        problems.append("proxy/Dockerfile does not switch to the non-root user 65532")
    chown = re.search(r"^RUN\s+chown\s+-R\s+65532:65532\s+(.*)$", dockerfile, re.M)
    if not chown or "/data" not in chown.group(1) or "/config" not in chown.group(1):
        problems.append("proxy/Dockerfile does not hand /data and /config to that user")
    elif user and chown.start() > user.start():
        problems.append("the chown must come before USER, or it runs unprivileged")
    return problems


def owner_credential_stays_in_migrate(compose: dict) -> list[str]:
    """The API serves as a restricted role; only `migrate` holds the owner's (#48).

    The owner can disable the append-only triggers the audit log and version
    history depend on. If the API container held that credential, a compromised API
    could do it in one statement, which is the finding. So the API gets the
    restricted role's credential and no trace of the owner's, does not migrate, and
    waits for the job that creates its schema and role.
    """
    problems = []
    api = service(compose, API)
    env = api.get("environment", {})
    leaked = [k for k in OWNER_SECRETS if k in env]
    if leaked:
        problems.append(f"api is given the owner's credential: {leaked}")
    if "APP_POSTGRES_PASSWORD" not in env and "APP_DATABASE_URL" not in env:
        problems.append("api is given no restricted-role credential")
    if str(env.get("RUN_MIGRATIONS")).lower() != "false":
        problems.append("api would try to migrate, which a restricted role cannot do")
    gate = (api.get("depends_on") or {}).get(MIGRATE, {})
    if gate.get("condition") != "service_completed_successfully":
        problems.append("api does not wait for migrate to finish")

    migrate = service(compose, MIGRATE)
    if not migrate:
        problems.append("there is no migrate service, so nothing creates the role")
    else:
        nets = migrate.get("networks", [])
        nets = list(nets.keys()) if isinstance(nets, dict) else list(nets)
        if nets != [DATA]:
            problems.append(f"migrate must be on [{DATA}] only, found {nets}")
        if migrate.get("ports"):
            problems.append("migrate publishes a port")
        if "POSTGRES_PASSWORD" not in migrate.get("environment", {}):
            problems.append("migrate has no owner credential to migrate with")
        if migrate.get("restart") not in ("no", False, None):
            problems.append("migrate must run once, not restart")
        if "app.migrate" not in " ".join(map(str, migrate.get("command", []))):
            problems.append("migrate does not run app.migrate")
    return problems


SESSION_SETTINGS = {
    "SSE_MAX_LIFETIME_SECONDS": "${SSE_MAX_LIFETIME_SECONDS:-900}",
    "IDLE_LOCK_MINUTES": "${IDLE_LOCK_MINUTES:-0}",
    "SIGN_OUT_URL": "${SIGN_OUT_URL:-}",
}


def session_settings_reach_the_api(compose: dict) -> list[str]:
    """The documented session settings must be delivered, or they do nothing."""
    env = service(compose, API).get("environment", {})
    return [
        f"api does not receive {name} as {want}"
        for name, want in SESSION_SETTINGS.items()
        if env.get(name) != want
    ]


def logs_are_capped(compose: dict) -> list[str]:
    """Every service's log has a size cap (#38).

    Docker's default keeps a container's log without bound, so a chatty service fills
    the host's disk, and the audit trail's own database with it. The cap is also what
    makes local retention finite and honest: it is not a retention policy, which is
    why docs/deploy.md says where to send the security stream.
    """
    problems = []
    for name, svc in compose.get("services", {}).items():
        logging_cfg = svc.get("logging") or {}
        opts = logging_cfg.get("options") or {}
        if logging_cfg.get("driver") != "json-file":
            problems.append(f"{name} does not use the json-file log driver")
        if not opts.get("max-size") or not opts.get("max-file"):
            problems.append(f"{name} has no log size cap (max-size and max-file)")
    return problems


def emergency_setting_reaches_the_api(compose: dict) -> list[str]:
    """EMERGENCY_ACCESS_IDS is documented as a .env setting, so compose must pass it.

    A setting the docs tell people to use and the stack never delivers is the
    PROXY_SHARED_SECRET failure (#61): the operator sets it, nothing happens, and
    for an emergency path the first time anyone finds out is the emergency.
    """
    env = service(compose, API).get("environment", {})
    want = "${EMERGENCY_ACCESS_IDS:-}"
    if env.get("EMERGENCY_ACCESS_IDS") != want:
        return [f"api does not receive EMERGENCY_ACCESS_IDS as {want}"]
    return []


APP_DIR_DEFAULT = "${APP_DIR:-./docs/app}"
CSP_FILE_DEFAULT = "${CSP_FILE:-./proxy/csp.caddy}"
MANIFEST_TARGET = "/etc/chai/manifest.json"


def _bind(mount: object) -> tuple[str, str, bool, dict]:
    """(source, target, read-only, the long syntax's `bind` options) of a mount."""
    if isinstance(mount, dict):
        return (
            str(mount.get("source", "")),
            str(mount.get("target", "")),
            bool(mount.get("read_only")),
            mount.get("bind") or {},
        )
    # From the right: a source may hold a colon of its own (${APP_DIR:-...}).
    text = str(mount)
    mode = ""
    if text.endswith((":ro", ":rw")):
        text, mode = text[:-3], text[-2:]
    source, _, target = text.rpartition(":")
    return source, target, mode == "ro", {}


def one_build_for_page_and_rules(compose: dict) -> list[str]:
    """The proxy serves the page, and the migrate job loads the retirement rules,
    from ONE build directory (D-76). Were they two, a custom page could be served
    while disposal followed CHAI's rules, or the other way round. Defaults are
    today's paths, so a stack with no APP_DIR or CSP_FILE runs as it did."""
    problems = []
    proxy = {t: (s, ro) for s, t, ro, _ in map(_bind, service(compose, PROXY).get(
        "volumes", []))}  # fmt: skip
    if proxy.get("/srv/app") != (APP_DIR_DEFAULT, True):
        problems.append(
            f"the proxy does not serve the page read-only from {APP_DIR_DEFAULT}"
        )
    if proxy.get("/etc/caddy/csp.caddy") != (CSP_FILE_DEFAULT, True):
        problems.append(
            f"the proxy does not read its policy read-only from {CSP_FILE_DEFAULT}"
        )
    migrate = service(compose, MIGRATE)
    env = migrate.get("environment", {})
    mounts = [_bind(m) for m in migrate.get("volumes", [])]
    manifest = [m for m in mounts if m[1] == MANIFEST_TARGET]
    if env.get("RETIREMENT_MANIFEST") != MANIFEST_TARGET:
        problems.append(f"migrate is not told the manifest is at {MANIFEST_TARGET}")
    if not manifest:
        problems.append("migrate does not mount the build's manifest")
    else:
        source, _, read_only, bind = manifest[0]
        if source != f"{APP_DIR_DEFAULT}/manifest.json":
            problems.append(
                f"migrate's manifest ({source}) is not the one beside the served page"
            )
        if not read_only:
            problems.append("migrate's manifest is mounted writable")
        if bind.get("create_host_path") is not False:
            problems.append(
                "a missing manifest would be mounted as an empty directory "
                "(set bind.create_host_path: false)"
            )
    if env.get("RETIREMENT_RULES_ACK") != "${RETIREMENT_RULES_ACK:-}":
        problems.append("migrate does not receive RETIREMENT_RULES_ACK from .env")
    if any(t != MANIFEST_TARGET for _, t, _, _ in mounts):
        problems.append("migrate mounts more than the manifest")
    return problems


def _nets(svc: dict) -> list[str]:
    nets = svc.get("networks", [])
    return list(nets.keys()) if isinstance(nets, dict) else list(nets)


def mcp_is_off_unless_asked(compose: dict) -> list[str]:
    """The MCP service must not start with a bare `docker compose up` (#164)."""
    problems = []
    services = compose.get("services", {})
    for name in (MCP, MCP_GATE):
        if (services.get(name) or {}).get("profiles") != [MCP_PROFILE]:
            problems.append(f"{name} is not in the {MCP_PROFILE} profile alone")
    default = {n for n, svc in services.items() if not svc.get("profiles")}
    if default != DEFAULT_SERVICES:
        problems.append(
            f"a bare `up` would start {sorted(default)}, not {sorted(DEFAULT_SERVICES)}"
        )
    return problems


def mcp_has_a_network_of_its_own(compose: dict) -> list[str]:
    """`mcp` is on the internal `agent` network and nothing else, so it reaches only
    the gate: not the API, the database, or the proxy's single sign-on listener."""
    problems = []
    members = {
        n for n, svc in compose.get("services", {}).items() if AGENT in _nets(svc)
    }
    if members != {MCP, MCP_GATE}:
        problems.append(f"'{AGENT}' holds {sorted(members)}, not just mcp and mcp-gate")
    if _nets(service(compose, MCP)) != [AGENT]:
        problems.append(
            f"mcp must be on [{AGENT}] only, found {_nets(service(compose, MCP))}"
        )
    if sorted(_nets(service(compose, MCP_GATE))) != sorted([EDGE, AGENT]):
        problems.append("mcp-gate must be on edge (to reach the API) and agent only")
    if not (compose.get("networks", {}).get(AGENT) or {}).get("internal"):
        problems.append(f"network '{AGENT}' is not internal: true")
    for name in (API, PROXY, DB, "migrate"):
        if AGENT in _nets(service(compose, name)):
            problems.append(f"{name} is on '{AGENT}'")
    for name in (MCP, MCP_GATE):
        for port in published_ports(compose, name):
            problems.append(f"{name} publishes {port}")
    return problems


def mcp_holds_no_credential(compose: dict) -> list[str]:
    """No secret, token, password or key in its environment, no way to the database, no
    dependency on the API, and it talks to the gate, not to the API."""
    problems = []
    svc = service(compose, MCP)
    env = svc.get("environment") or {}
    for name in env:
        if re.search(
            r"TOKEN|SECRET|PASSWORD|KEY|DATABASE|POSTGRES|CREDENTIAL", name, re.I
        ):
            problems.append(f"mcp is given {name}")
    if env.get("API_BASE_URL") != "http://mcp-gate:8081":
        problems.append(
            f"mcp's API_BASE_URL is {env.get('API_BASE_URL')!r}, not the gate"
        )
    if "api" in (svc.get("depends_on") or {}):
        problems.append("mcp depends on the api")
    if svc.get("volumes"):
        problems.append("mcp mounts a volume")
    if svc.get("env_file"):
        problems.append("mcp reads an env_file, which could hold anything")
    # The API's second lock is the gate's to hold, never the service's.
    if "PROXY_SHARED_SECRET" not in (
        service(compose, MCP_GATE).get("environment") or {}
    ):
        problems.append("the gate does not hold PROXY_SHARED_SECRET")
    return problems


def mcp_is_hardened(compose: dict) -> list[str]:
    problems = []
    for name in (MCP, MCP_GATE):
        svc = service(compose, name)
        if svc.get("read_only") is not True:
            problems.append(f"{name} does not have a read-only root filesystem")
        if "ALL" not in [str(c).upper() for c in svc.get("cap_drop", [])]:
            problems.append(f"{name} does not cap_drop ALL")
    adds = {str(c).upper() for c in service(compose, MCP).get("cap_add", [])}
    if adds:
        problems.append(f"mcp adds back capabilities: {sorted(adds)}")
    adds = {str(c).upper() for c in service(compose, MCP_GATE).get("cap_add", [])}
    if adds - {"NET_BIND_SERVICE"}:
        problems.append(
            f"mcp-gate adds back more than NET_BIND_SERVICE: {sorted(adds)}"
        )
    user = str(service(compose, MCP_GATE).get("user", "")).split(":")[0]
    if user in NON_ROOT:
        problems.append("mcp-gate runs as root: set a numeric non-root user")
    image = str(service(compose, MCP_GATE).get("image", ""))
    if not re.fullmatch(r"caddy:\d+@sha256:[0-9a-f]{64}", image):
        problems.append(f"mcp-gate's image is {image!r}, not pinned by digest")
    return problems


def mcp_image_is_unprivileged(dockerfile: str) -> list[str]:
    """mcp/Dockerfile: built like the API's. Non-root, no shell, no pip, locked."""
    problems = []
    froms = re.findall(r"^FROM (\S+)", dockerfile, re.M)
    if not froms or not all(re.search(r"@sha256:[0-9a-f]{64}$", f) for f in froms):
        problems.append(f"a base image is not pinned by digest: {froms}")
    if not re.search(r"^USER [1-9]\d*(:[1-9]\d*)?$", dockerfile, re.M):
        problems.append("no numeric non-root USER")
    if "--shell /usr/sbin/nologin" not in dockerfile:
        problems.append("its user has a login shell")
    if "--require-hashes" not in dockerfile:
        problems.append("the lock is not verified by hash")
    if "pip uninstall" not in dockerfile:
        problems.append("pip stays in the runtime image")
    if not re.search(r"^HEALTHCHECK ", dockerfile, re.M):
        problems.append("no HEALTHCHECK")
    cmd = re.findall(r"^CMD (.*)$", dockerfile, re.M)
    if not cmd or not cmd[-1].startswith('["'):
        problems.append("CMD is not in exec form (a shell would run it)")
    if re.search(r"^CMD .*\bsh\b", dockerfile, re.M):
        problems.append("CMD runs a shell")
    return problems


def mcp_default_set_is_off(compose_cli) -> list[str]:
    """What compose itself says `up` would start, with and without the profile."""
    plain, with_profile = compose_cli(), compose_cli("--profile", MCP_PROFILE)
    problems = []
    if plain is None:
        return ["docker compose is not available to ask"]
    if {MCP, MCP_GATE} & set(plain):
        problems.append(f"a bare `up` starts {sorted({MCP, MCP_GATE} & set(plain))}")
    if not {MCP, MCP_GATE} <= set(with_profile or []):
        problems.append("the profile does not start mcp and mcp-gate")
    return problems


def compose_services(*flags: str) -> list[str] | None:
    """`docker compose config --services`, as compose resolves it."""
    import os
    import shutil
    import subprocess

    if not shutil.which("docker"):
        return None
    env = {
        **os.environ,
        "POSTGRES_PASSWORD": "x",
        "IDENTITY_ID_SOURCE": "x",
    }
    done = subprocess.run(
        ["docker", "compose", *flags, "-f", str(COMPOSE), "config", "--services"],
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
    )
    return done.stdout.split() if done.returncode == 0 else None


def every_rule(compose: dict) -> list[str]:
    return [
        *api_ports(compose),
        *db_ports(compose),
        *db_network(compose),
        *edge_members(compose),
        *proxy_binds_loopback(compose),
        *database_persists(compose),
        *database_image_pinned(compose),
        *override_file_is_named(),
        *shared_secret_reaches_both_ends(compose),
        *container_hardening(compose),
        *owner_credential_stays_in_migrate(compose),
        *emergency_setting_reaches_the_api(compose),
        *session_settings_reach_the_api(compose),
        *logs_are_capped(compose),
        *one_build_for_page_and_rules(compose),
        *cloud_proxy_image_is_unprivileged(
            (ROOT / "proxy" / "Dockerfile").read_text(encoding="utf-8")
        ),
        *mcp_is_off_unless_asked(compose),
        *mcp_has_a_network_of_its_own(compose),
        *mcp_holds_no_credential(compose),
        *mcp_is_hardened(compose),
        *mcp_image_is_unprivileged(
            (ROOT / "mcp" / "Dockerfile").read_text(encoding="utf-8")
        ),
    ]


def dead_ports(base: dict, dev: dict) -> list[str]:
    """A published port on a service that no routable network reaches does nothing.

    Docker makes no host binding for a container that is only on `internal: true`
    networks, and compose does not complain, so the file reads as if the port works
    (#88). The dev override must not claim one.
    """
    internal = {
        name
        for name, net in (base.get("networks") or {}).items()
        if (net or {}).get("internal")
    }
    problems = []
    for name, svc in (dev.get("services") or {}).items():
        if not svc.get("ports"):
            continue
        nets = service(base, name).get("networks", [])
        nets = list(nets.keys()) if isinstance(nets, dict) else list(nets)
        if nets and all(n in internal for n in nets):
            problems.append(
                f"{name} publishes {svc['ports']} but is only on internal "
                f"network(s) {nets}, so Docker creates no host binding"
            )
    return problems


def mentions_dead_db_port(text: str) -> bool:
    """Prose or config that offers the database on a host port nothing opens."""
    return "DEV_DB_PORT" in text


# --- tests -------------------------------------------------------------------


def main() -> int:
    compose = load()

    print("The real compose.yaml")
    problems = every_rule(compose)
    check("every isolation rule holds", not problems, "; ".join(problems))
    check(
        "it has the three services it is about",
        all(service(compose, n) for n in (API, DB, PROXY)),
    )

    dev = yaml.safe_load(DEV.read_text(encoding="utf-8"))
    dead = dead_ports(compose, dev)
    check(
        "the dev override publishes no port that does nothing",
        not dead,
        "; ".join(dead),
    )
    for path in (".env.example", "compose.dev.yaml"):
        check(
            f"{path} offers no DEV_DB_PORT, which has no effect",
            not mentions_dead_db_port((ROOT / path).read_text(encoding="utf-8")),
        )
    running = (ROOT / "docs" / "running.md").read_text(encoding="utf-8")
    check(
        "running.md does not point the server tests at the stack's own database",
        "localhost:5432" not in running,
    )

    print("Mutation tests: each rule must notice when it is broken")

    probe = {"services": {DB: {"ports": ["127.0.0.1:5432:5432"]}}}
    check(
        "a dev port on an internal-only service is noticed",
        bool(dead_ports(compose, probe)),
    )
    probe = {"services": {API: {"ports": ["127.0.0.1:8000:8000"]}}}
    check("a dev port on the api is not", not dead_ports(compose, probe))
    check("a DEV_DB_PORT mention is noticed", mentions_dead_db_port("DEV_DB_PORT=5432"))

    broken = copy.deepcopy(compose)
    broken["services"][API]["ports"] = ["127.0.0.1:8000:8000"]
    check("publishing a port on the api is noticed", bool(api_ports(broken)))

    broken = copy.deepcopy(compose)
    broken["services"][DB]["ports"] = ["5432:5432"]
    check("publishing a port on the database is noticed", bool(db_ports(broken)))

    broken = copy.deepcopy(compose)
    broken["networks"][DATA]["internal"] = False
    check("an internal network made routable is noticed", bool(db_network(broken)))

    broken = copy.deepcopy(compose)
    broken["services"][DB]["networks"] = [DATA, EDGE]
    check("the database joining the edge network is noticed", bool(db_network(broken)))

    broken = copy.deepcopy(compose)
    broken["services"]["sidecar"] = {"image": "x", "networks": [EDGE]}
    check("a new service on the edge network is noticed", bool(edge_members(broken)))

    broken = copy.deepcopy(compose)
    broken["services"][PROXY]["ports"] = ["0.0.0.0:8080:80"]
    check(
        "the proxy binding every interface is noticed",
        bool(proxy_binds_loopback(broken)),
    )

    broken = copy.deepcopy(compose)
    broken["services"][PROXY]["ports"] = []
    check("a proxy with no port is noticed", bool(proxy_binds_loopback(broken)))

    broken = copy.deepcopy(compose)
    broken["services"][DB]["volumes"] = ["/tmp/pg:/var/lib/postgresql/data"]
    check(
        "the database leaving its named volume is noticed",
        bool(database_persists(broken)),
    )

    broken = copy.deepcopy(compose)
    del broken["volumes"][VOLUME]
    check("an undeclared named volume is noticed", bool(database_persists(broken)))

    for image in ("postgres:latest", "postgres", "postgres:17-alpine"):
        broken = copy.deepcopy(compose)
        broken["services"][DB]["image"] = image
        check(f"db image '{image}' is noticed", bool(database_image_pinned(broken)))

    def hardening_mutation(label: str, mutate) -> None:
        broken = copy.deepcopy(compose)
        mutate(broken["services"])
        check(f"{label} is noticed", bool(container_hardening(broken)))

    for name in (DB, API, PROXY):
        hardening_mutation(
            f"{name} losing no-new-privileges",
            lambda s, n=name: s[n].pop("security_opt", None),
        )
        hardening_mutation(
            f"{name} losing its memory limit", lambda s, n=name: s[n].pop("mem_limit")
        )
        hardening_mutation(
            f"{name} losing its pids limit", lambda s, n=name: s[n].pop("pids_limit")
        )
        hardening_mutation(
            f"{name} losing its cpu limit", lambda s, n=name: s[n].pop("cpus")
        )
        hardening_mutation(
            f"{name} becoming privileged",
            lambda s, n=name: s[n].update(privileged=True),
        )
    for name in (API, PROXY):
        hardening_mutation(
            f"{name} keeping its default capabilities",
            lambda s, n=name: s[n].pop("cap_drop"),
        )
        hardening_mutation(
            f"{name} with a writable root filesystem",
            lambda s, n=name: s[n].update(read_only=False),
        )
    hardening_mutation("the proxy running as root", lambda s: s[PROXY].pop("user"))
    hardening_mutation(
        "the proxy running as uid 0", lambda s: s[PROXY].update(user="0:0")
    )
    hardening_mutation(
        "the proxy adding back SYS_ADMIN",
        lambda s: s[PROXY].update(cap_add=["NET_BIND_SERVICE", "SYS_ADMIN"]),
    )
    hardening_mutation(
        "the api adding any capability back", lambda s: s[API].update(cap_add=["CHOWN"])
    )
    hardening_mutation(
        "the ownership fixer joining a network",
        lambda s: s[PROXY_INIT].update(networks=["edge"]),
    )
    hardening_mutation(
        "the ownership fixer keeping network access",
        lambda s: s[PROXY_INIT].pop("network_mode"),
    )
    hardening_mutation(
        "the ownership fixer keeping every capability",
        lambda s: s[PROXY_INIT].pop("cap_drop"),
    )
    hardening_mutation(
        "the proxy not waiting for the ownership fixer",
        lambda s: s[PROXY].pop("depends_on"),
    )
    hardening_mutation("the ownership fixer being removed", lambda s: s.pop(PROXY_INIT))

    def role_mutation(label: str, mutate) -> None:
        broken = copy.deepcopy(compose)
        mutate(broken["services"])
        check(f"{label} is noticed", bool(owner_credential_stays_in_migrate(broken)))

    role_mutation(
        "the api being given the owner's password",
        lambda s: s[API]["environment"].update(POSTGRES_PASSWORD="x"),
    )
    role_mutation(
        "the api being given a DATABASE_URL",
        lambda s: s[API]["environment"].update(DATABASE_URL="postgresql://x"),
    )
    role_mutation(
        "the api losing both of its restricted credentials",
        lambda s: [
            s[API]["environment"].pop(k)
            for k in ("APP_POSTGRES_PASSWORD", "APP_DATABASE_URL")
        ],
    )
    role_mutation(
        "the api being told to migrate",
        lambda s: s[API]["environment"].update(RUN_MIGRATIONS="true"),
    )
    role_mutation(
        "the api not waiting for migrate", lambda s: s[API]["depends_on"].pop(MIGRATE)
    )
    role_mutation("the migrate service being removed", lambda s: s.pop(MIGRATE))
    role_mutation(
        "migrate joining the internet-facing network",
        lambda s: s[MIGRATE].update(networks=["data", "edge"]),
    )
    role_mutation(
        "migrate publishing a port", lambda s: s[MIGRATE].update(ports=["9:9"])
    )
    role_mutation(
        "migrate restarting forever", lambda s: s[MIGRATE].update(restart="always")
    )
    role_mutation(
        "migrate losing the owner credential",
        lambda s: s[MIGRATE]["environment"].pop("POSTGRES_PASSWORD"),
    )
    for svc_name in compose["services"]:
        broken = copy.deepcopy(compose)
        broken["services"][svc_name].pop("logging")
        check(
            f"{svc_name} losing its log cap is noticed", bool(logs_are_capped(broken))
        )
        broken = copy.deepcopy(compose)
        broken["services"][svc_name]["logging"] = {"driver": "json-file"}
        check(
            f"{svc_name} with a log driver but no size cap is noticed",
            bool(logs_are_capped(broken)),
        )
    for name in SESSION_SETTINGS:
        broken = copy.deepcopy(compose)
        del broken["services"][API]["environment"][name]
        check(
            f"{name} not reaching the api is noticed",
            bool(session_settings_reach_the_api(broken)),
        )
    broken = copy.deepcopy(compose)
    del broken["services"][API]["environment"]["EMERGENCY_ACCESS_IDS"]
    check(
        "EMERGENCY_ACCESS_IDS not reaching the api is noticed",
        bool(emergency_setting_reaches_the_api(broken)),
    )
    hardening_mutation(
        "migrate keeping its default capabilities", lambda s: s[MIGRATE].pop("cap_drop")
    )
    hardening_mutation(
        "migrate with a writable root filesystem",
        lambda s: s[MIGRATE].update(read_only=False),
    )

    def build_mutation(label: str, mutate) -> None:
        broken = copy.deepcopy(compose)
        mutate(broken["services"])
        check(f"{label} is noticed", bool(one_build_for_page_and_rules(broken)))

    def proxy_mount(target: str, value: str):
        def mutate(s: dict) -> None:
            s[PROXY]["volumes"] = [
                value if _bind(m)[1] == target else m for m in s[PROXY]["volumes"]
            ]

        return mutate

    def manifest_mount(**changes):
        def mutate(s: dict) -> None:
            for m in s[MIGRATE]["volumes"]:
                if isinstance(m, dict) and m.get("target") == MANIFEST_TARGET:
                    m.update(changes)

        return mutate

    build_mutation(
        "the page served from a fixed path, not APP_DIR",
        proxy_mount("/srv/app", "./docs/app:/srv/app:ro"),
    )
    build_mutation(
        "the page mounted writable",
        proxy_mount("/srv/app", f"{APP_DIR_DEFAULT}:/srv/app"),
    )
    build_mutation(
        "APP_DIR defaulting somewhere else",
        proxy_mount("/srv/app", "${APP_DIR:-./site}:/srv/app:ro"),
    )
    build_mutation(
        "the policy read from a fixed path, not CSP_FILE",
        proxy_mount(
            "/etc/caddy/csp.caddy", "./proxy/csp.caddy:/etc/caddy/csp.caddy:ro"
        ),
    )
    build_mutation(
        "the manifest taken from another directory than the page",
        manifest_mount(source="./docs/app/manifest.json"),
    )
    build_mutation("the manifest mounted writable", manifest_mount(read_only=False))
    build_mutation(
        "a missing manifest mounted as an empty directory", manifest_mount(bind={})
    )
    build_mutation("the manifest not mounted", lambda s: s[MIGRATE].pop("volumes"))
    build_mutation(
        "migrate told the manifest is elsewhere",
        lambda s: s[MIGRATE]["environment"].update(RETIREMENT_MANIFEST="/tmp/m.json"),
    )
    build_mutation(
        "the acknowledgment not reaching migrate",
        lambda s: s[MIGRATE]["environment"].pop("RETIREMENT_RULES_ACK"),
    )
    build_mutation(
        "migrate mounting the whole build",
        lambda s: s[MIGRATE]["volumes"].append(f"{APP_DIR_DEFAULT}:/srv/app:ro"),
    )

    # --- the MCP service (#164): off unless asked, alone on its network, no credential
    def mcp_mutation(label: str, rule, mutate) -> None:
        broken = copy.deepcopy(compose)
        mutate(broken)
        check(f"{label} is noticed", bool(rule(broken)))

    s_ = lambda c: c["services"]  # noqa: E731
    mcp_mutation(
        "the mcp service without its profile (on by default)",
        mcp_is_off_unless_asked,
        lambda c: s_(c)[MCP].pop("profiles"),
    )
    mcp_mutation(
        "the gate without its profile",
        mcp_is_off_unless_asked,
        lambda c: s_(c)[MCP_GATE].pop("profiles"),
    )
    mcp_mutation(
        "the mcp service in another profile as well",
        mcp_is_off_unless_asked,
        lambda c: s_(c)[MCP].update(profiles=[MCP_PROFILE, "default"]),
    )
    mcp_mutation(
        "a new service with no profile",
        mcp_is_off_unless_asked,
        lambda c: s_(c).update(extra={"image": "x"}),
    )
    mcp_mutation(
        "mcp on the edge network",
        mcp_has_a_network_of_its_own,
        lambda c: s_(c)[MCP].update(networks=[AGENT, EDGE]),
    )
    mcp_mutation(
        "mcp on the data network",
        mcp_has_a_network_of_its_own,
        lambda c: s_(c)[MCP].update(networks=[AGENT, DATA]),
    )
    mcp_mutation(
        "the agent network made routable",
        mcp_has_a_network_of_its_own,
        lambda c: c["networks"][AGENT].update(internal=False),
    )
    mcp_mutation(
        "the proxy on the agent network",
        mcp_has_a_network_of_its_own,
        lambda c: s_(c)[PROXY].update(networks=[EDGE, AGENT]),
    )
    mcp_mutation(
        "the api on the agent network",
        mcp_has_a_network_of_its_own,
        lambda c: s_(c)[API].update(networks=[EDGE, DATA, AGENT]),
    )
    mcp_mutation(
        "a published port on mcp",
        mcp_has_a_network_of_its_own,
        lambda c: s_(c)[MCP].update(ports=["8000:8000"]),
    )
    mcp_mutation(
        "a published port on the gate",
        mcp_has_a_network_of_its_own,
        lambda c: s_(c)[MCP_GATE].update(ports=["8082:8082"]),
    )
    mcp_mutation(
        "a stranger on the agent network",
        mcp_has_a_network_of_its_own,
        lambda c: s_(c).update(other={"image": "x", "networks": [AGENT]}),
    )
    for var in ("MCP_TOKEN", "AGENT_ID_SECRET", "POSTGRES_PASSWORD", "API_KEY"):
        mcp_mutation(
            f"{var} given to mcp",
            mcp_holds_no_credential,
            lambda c, var=var: s_(c)[MCP]["environment"].update({var: "x"}),
        )
    mcp_mutation(
        "mcp talking to the api directly",
        mcp_holds_no_credential,
        lambda c: s_(c)[MCP]["environment"].update(API_BASE_URL="http://api:8000"),
    )
    mcp_mutation(
        "mcp depending on the api",
        mcp_holds_no_credential,
        lambda c: s_(c)[MCP].update(
            depends_on={"api": {"condition": "service_started"}}
        ),
    )
    mcp_mutation(
        "mcp with an env file",
        mcp_holds_no_credential,
        lambda c: s_(c)[MCP].update(env_file=[".env"]),
    )
    mcp_mutation(
        "the gate without the shared secret",
        mcp_holds_no_credential,
        lambda c: s_(c)[MCP_GATE]["environment"].pop("PROXY_SHARED_SECRET"),
    )
    mcp_mutation(
        "mcp with a writable root filesystem",
        mcp_is_hardened,
        lambda c: s_(c)[MCP].update(read_only=False),
    )
    mcp_mutation(
        "mcp keeping its capabilities",
        mcp_is_hardened,
        lambda c: s_(c)[MCP].pop("cap_drop"),
    )
    mcp_mutation(
        "mcp adding a capability back",
        mcp_is_hardened,
        lambda c: s_(c)[MCP].update(cap_add=["NET_ADMIN"]),
    )
    mcp_mutation(
        "the gate running as root",
        mcp_is_hardened,
        lambda c: s_(c)[MCP_GATE].update(user="0:0"),
    )
    mcp_mutation(
        "the gate's image unpinned",
        mcp_is_hardened,
        lambda c: s_(c)[MCP_GATE].update(image="caddy:2"),
    )
    mcp_mutation(
        "the mcp service unconfined",
        container_hardening,
        lambda c: s_(c)[MCP].pop("security_opt"),
    )

    real_mcp = (ROOT / "mcp" / "Dockerfile").read_text(encoding="utf-8")
    check(
        "the mcp image: the real Dockerfile passes",
        not mcp_image_is_unprivileged(real_mcp),
    )
    for label, old, new in (
        ("dropping USER", "USER 10002:10002", ""),
        ("USER root", "USER 10002:10002", "USER 0:0"),
        ("a login shell", "--shell /usr/sbin/nologin", "--shell /bin/bash"),
        ("an unlocked install", "--require-hashes", ""),
        ("keeping pip", "&& /opt/venv/bin/pip uninstall --yes pip setuptools", ""),
        ("a floating base image", "python:3.12-slim@sha256:", "python:3.12-slim#"),
        ("no health check", "HEALTHCHECK", "# HEALTHCHECK"),
        (
            "a shell-form CMD",
            'CMD ["python", "-m", "chai_mcp"]',
            "CMD python -m chai_mcp",
        ),
    ):
        check(
            f"the mcp image: {label} is noticed",
            bool(mcp_image_is_unprivileged(real_mcp.replace(old, new))),
        )

    asked = mcp_default_set_is_off(compose_services)
    docker_there = compose_services() is not None
    if docker_there:
        check(
            "compose itself: a bare `up` leaves mcp off, the profile starts it",
            not asked,
            "; ".join(asked),
        )
        check(
            "compose itself: a bare `up` starts exactly the default services",
            set(compose_services() or []) == DEFAULT_SERVICES,
            str(compose_services()),
        )
    else:
        check(
            "docker compose is available to ask what `up` starts",
            not os.environ.get("REQUIRE_TESTS"),
            "docker compose is not available (REQUIRE_TESTS is set)",
        )
    check(
        "a profile that starts mcp by default is noticed by the compose check",
        bool(
            mcp_default_set_is_off(
                lambda *f: [MCP, MCP_GATE, "db"] if not f else [MCP, MCP_GATE]
            )
        ),
    )

    real = (ROOT / "proxy" / "Dockerfile").read_text(encoding="utf-8")
    check(
        "the cloud proxy image: a real Dockerfile passes",
        not cloud_proxy_image_is_unprivileged(real),
    )
    check(
        "the cloud proxy image: dropping USER is noticed",
        bool(cloud_proxy_image_is_unprivileged(real.replace("USER 65532:65532", ""))),
    )
    check(
        "the cloud proxy image: dropping the chown is noticed",
        bool(
            cloud_proxy_image_is_unprivileged(
                re.sub(r"^RUN chown.*$", "", real, flags=re.M)
            )
        ),
    )
    check(
        "the cloud proxy image: a chown after USER is noticed",
        bool(
            cloud_proxy_image_is_unprivileged(
                real.replace(
                    "RUN chown -R 65532:65532 /data /config\nUSER 65532:65532",
                    "USER 65532:65532\nRUN chown -R 65532:65532 /data /config",
                )
            )
        ),
    )

    for side in (API, PROXY):
        broken = copy.deepcopy(compose)
        del broken["services"][side]["environment"]["PROXY_SHARED_SECRET"]
        check(
            f"PROXY_SHARED_SECRET missing from {side} is noticed",
            bool(shared_secret_reaches_both_ends(broken)),
        )

    stray = ROOT / "compose.override.yaml"
    stray.write_text("services: {}\n", encoding="utf-8")
    try:
        check("a compose.override.yaml is noticed", bool(override_file_is_named()))
    finally:
        stray.unlink()

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("compose isolation checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
