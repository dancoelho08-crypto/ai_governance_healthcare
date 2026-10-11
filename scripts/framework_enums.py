"""Closed sets a framework definition uses that code outside the checker needs too.

Standard library only, so the build manifest (``build_manifest.py``) and the server's
tests can import it without the checker's dependencies (jsonschema).
"""

from __future__ import annotations

from enum import StrEnum


class GateClass(StrEnum):
    """A decision's class: GateClass in app/js (D-74)."""

    GO = "go"
    CONDITIONAL = "conditional"
    REVISE = "revise"
    STOP = "stop"
    RETIRE = "retire"


class CrossRefRelation(StrEnum):
    """How far an item's crossRefs reach the other framework's: an item's
    ``crossRefs.relation``. Here, not in check_framework.py, because
    scripts/gen_crosswalk.py checks docs/crosswalk.md by it too (#174)."""

    EQUIVALENT = "equivalent"
    PARTIAL = "partial"
    OPTICA_ONLY = "optica-only"


# The classes that end a project: the engine's phase() calls a project Stopped or
# Retired when any of its gates holds an option of one of these classes, and the
# server starts its retention clock then (R-56, R-66).
ENDING_CLASSES = frozenset({GateClass.STOP, GateClass.RETIRE})
