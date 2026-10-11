"""The build manifest: what the server needs to know about the frameworks a page was
built with (#168 PR C, D-76).

``scripts/build_app.py`` writes it beside the page (``docs/app/manifest.json`` for
the default build). The migrate job reads it (``server/app/retirement.py``) and
loads the retirement pairs into ``retirement_rule``, so the server decides when a
record is retired, and so when disposal is due (R-56, R-66), from the same
definitions the page runs.

Per framework: its id, role, version, the SHA-256 of its definition's canonical JSON,
and its retirement pairs, every (gate id, option value) whose class ends a project,
which is what the engine's ``phase()`` treats as Stopped or Retired. Then the hash of
the primary's rule set, which ``/api/health`` reports back.

Standard library only: the server's tests import it to build stand-in manifests, and
the server image does not carry the checker's dependencies.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from framework_enums import ENDING_CLASSES, GateClass

MANIFEST_FORMAT = 1


def canonical_json(value: object) -> bytes:
    """One byte string per JSON value: sorted keys, no spaces, UTF-8. The server
    computes the rule-set hash the same way (server/app/retirement.py)."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def retirement_pairs(definition: dict) -> list[dict[str, str]]:
    """Every (gate id, option value) whose class ends a project, sorted."""
    pairs = {
        (gate["id"], option["value"])
        for gate in definition.get("gates", [])
        for option in gate["options"]
        if GateClass(option["class"]) in ENDING_CLASSES
    }
    return [{"gate": g, "decision": d} for g, d in sorted(pairs)]


def vocabulary(definition: dict) -> dict[str, list[str]]:
    """The words of a definition an agent may be shown (#164, D-89): its item ids,
    checkpoint ids, status values and checkpoint options. Sorted, so the manifest
    is byte-stable. What a record stores outside these is free text to the server,
    and the agent API drops it."""
    return {
        "items": sorted(
            {
                item["id"]
                for section in definition.get("sections", [])
                for item in section.get("items", [])
            }
        ),
        "gates": sorted({g["id"] for g in definition.get("gates", [])}),
        "statuses": sorted({s["value"] for s in definition.get("statuses", [])}),
        "decisions": sorted(
            {
                option["value"]
                for gate in definition.get("gates", [])
                for option in gate["options"]
            }
        ),
    }


def rule_set_hash(framework_id: str, pairs: list[dict[str, str]]) -> str:
    """SHA-256 of a framework's retirement rules."""
    rules = sorted([p["gate"], p["decision"]] for p in pairs)
    return hashlib.sha256(
        canonical_json({"framework": framework_id, "retire": rules})
    ).hexdigest()


def manifest(defs: dict[str, dict], primary: str) -> dict:
    """The manifest for a build of ``defs`` (id -> definition) with ``primary``."""
    frameworks = [
        {
            "id": fid,
            "role": d["role"],  # passed through; the server parses it
            "version": d["version"],
            "sha256": hashlib.sha256(canonical_json(d)).hexdigest(),
            "retire": retirement_pairs(d),
            # Read by the migrate job into agent_vocabulary (migration 014). It
            # decides what an agent may see and nothing about disposal, so it is
            # outside the rule-set hash and needs no acknowledgment (D-89).
            "vocab": vocabulary(d),
        }
        for fid, d in defs.items()
    ]
    retire = next((f["retire"] for f in frameworks if f["id"] == primary), None)
    if retire is None:
        raise SystemExit(f"error: the primary {primary!r} is not in the build")
    if not retire:
        raise SystemExit(
            f"error: the primary framework {primary!r} has no stop or retire option, "
            "so no project could ever come due for disposal (R-56)"
        )
    return {
        "manifest": MANIFEST_FORMAT,
        "primary": primary,
        "frameworks": frameworks,
        "ruleSetHash": rule_set_hash(primary, retire),
    }


def manifest_json(defs: dict[str, dict], primary: str) -> str:
    return json.dumps(manifest(defs, primary), ensure_ascii=False, indent=2) + "\n"
