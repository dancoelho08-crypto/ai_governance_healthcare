#!/usr/bin/env python3
"""Check every framework definition against its schema and its rules (#168, R-63).

A framework is data: app/frameworks/<id>/framework.json. The engine runs whatever
the definition says, so a definition that is wrong in a way the engine trusts is a
broken build or, worse, a build that quietly means something else. This is the
gate in front of that trust. It checks:

* the shape, against schema/framework.schema.json (JSON Schema draft 2020-12),
  including every id's pattern (^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$, so dot-free) and
  no JavaScript prototype name as an id;
* every rule the schema cannot state:
  - ids are explicit and unique: sections, items, gates, categories, statuses,
    whos, phases, section numbers, and option values within a gate;
  - references resolve: an item's category and who, a section's category, a
    gate's `after`, a phase's `reachedBy` and section, `review.gate` and its
    anchors, each flag's gate and plugin, each section slot, `requires`, and
    every crossRef (its framework, which must be required, and its ids);
  - the lifecycle is coherent: an option value has one class in every gate, the
    first phase has no `reachedBy` and the others have one, phase roles never go
    backward and `live` appears at most once, the review gate is the last gate, a
    primary with gates can end a project (a stop or retire option, R-56), and a
    flag rule has exactly the parameters it needs;
  - a supplement declares no gates (the server could not attribute a sign-off),
    and only a supplement may be opt-in;
  - names do not collide: every view id is unique across all definitions and the
    shell's own views, a category is never "overall", a supplement's id is not a
    reserved top-level record key, a namespace includes the id and is not another
    definition's or the shell catalog's, and `export.schemaId` is `<id>-review/<n>`
    ("chai-review/" belongs to CHAI's records alone);
  - review.monthsByRiskTier is keyed by the risk tiers setup stores;
  - samples belong to a primary and name items, statuses, gates, options and
    risk tiers that exist.

Each problem is one line naming the file and the JSON path. Exit 1 if any.

    pixi run check-framework
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterable, Iterator
from enum import StrEnum
from pathlib import Path
from typing import Any, assert_never

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent))

from framework_enums import ENDING_CLASSES, CrossRefRelation, GateClass

ROOT = Path(__file__).resolve().parent.parent
FRAMEWORKS = ROOT / "app" / "frameworks"
DEFINITION = "framework.json"
SCHEMA = ROOT / "schema" / "framework.schema.json"
SHELL_CATALOG = ROOT / "app" / "i18n" / "en.json"
# The frameworks the published build contains, and its primary (#168). The rules
# across definitions (views, namespaces, requires) apply to this build; a definition
# outside it is checked on its own.
CONFIG = ROOT / "app" / "frameworks.json"
CONFIG_LABEL = "app/frameworks.json"
SCHEMA_VERSION = 1

# The id rule, in the schema as $defs.id.pattern; schema_drift() keeps them equal.
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"
ID_RE = re.compile(ID_PATTERN)

# JavaScript's own property names. An id becomes an object key in the app, and one
# of these would read or write the prototype (#124). A protocol list, not a set
# this repository defines, so a constant; the schema carries the same list.
UNSAFE_NAMES = frozenset(
    {
        "__proto__",
        "constructor",
        "prototype",
        "toString",
        "toLocaleString",
        "valueOf",
        "hasOwnProperty",
        "isPrototypeOf",
        "propertyIsEnumerable",
        "__defineGetter__",
        "__defineSetter__",
        "__lookupGetter__",
        "__lookupSetter__",
    }
)


class SchemaKeyword(StrEnum):
    """JSON Schema keywords whose failures get a plainer message."""

    NOT = "not"
    PATTERN = "pattern"


class Role(StrEnum):
    PRIMARY = "primary"
    SUPPLEMENT = "supplement"


class StatusClass(StrEnum):
    """What the engine does with a status: scoring, overdue, open gaps."""

    DONE = "done"
    PARTIAL = "partial"
    OPEN = "open"
    DECLINED = "declined"
    EXCLUDED = "excluded"


class PhaseRole(StrEnum):
    """In lifecycle order: a later phase never has an earlier role."""

    PLANNING = "planning"
    BUILD = "build"
    PILOT = "pilot"
    LIVE = "live"


class FlagRule(StrEnum):
    PAST_DUE = "pastDue"
    OPEN_WHEN_LIVE = "openWhenLive"
    REVIEW = "review"
    REVISE_AT_REVIEW = "reviseAtReview"
    APPROVAL_WITHOUT_RATIONALE = "approvalWithoutRationale"
    IDLE = "idle"


class UiSlot(StrEnum):
    """A screen's whole-sentence catalog key a definition may supply (the engine's
    UiSlot in app/js/10-frameworks/01-engine/10-facade.js). A slot a definition
    leaves out gets the engine's neutral key, so none is required."""

    RAIL_OVERVIEW = "railOverview"
    RAIL_SHORT = "railShort"
    PIP_TITLE = "pipTitle"
    SECTION_EYEBROW = "sectionEyebrow"
    SECTION_ANSWERED = "sectionAnswered"
    DECLINED_COUNT = "declinedCount"
    CHIP_NOTE = "chipNote"
    LEGEND = "legend"
    EXTERNAL_COUNT = "externalCount"
    COVERED_BY = "coveredBy"
    NOT_COVERED = "notCovered"
    GATE_EYEBROW = "gateEyebrow"
    GATE_GAPS = "gateGaps"
    GATE_ANSWERED_PARTIAL = "gateAnsweredPartial"
    GATE_ALL_MET = "gateAllMet"
    GATE_GAP_ITEM = "gateGapItem"
    DASH_LEDE = "dashLede"
    DASH_EMPTY = "dashEmpty"
    SETUP_EYEBROW = "setupEyebrow"
    FW_LEDE = "fwLede"
    DEL_REMOVES = "delRemoves"
    DEL_DESTROYS = "delDestroys"
    REPORT_EYEBROW = "reportEyebrow"
    TITLE_SUFFIX = "titleSuffix"
    COL_SECTION = "colSection"
    COL_ITEM = "colItem"
    COL_CATEGORY = "colCategory"
    CHECKPOINTS = "checkpoints"
    COL_GATE = "colGate"
    NO_GAPS = "noGaps"
    READINESS_DETAIL = "readinessDetail"
    MD_OVERALL = "mdOverall"
    DISCLAIMER = "disclaimer"
    MD_FOOTER = "mdFooter"
    FW_NOTE = "fwNote"
    FLAG_LIVE_OPEN = "flagLiveOpen"
    FLAG_NO_RATIONALE = "flagNoRationale"
    FLAG_NO_DEPLOY_DATE = "flagNoDeployDate"
    OVERVIEW_TITLE = "overviewTitle"
    OVERVIEW_LEDE = "overviewLede"
    CARD_ANSWERED = "cardAnswered"
    CARD_PROGRESS = "cardProgress"
    CARD_DECLINED = "cardDeclined"
    WHO_OWES = "whoOwes"
    RELAY = "relay"
    COL_WHO = "colWho"
    COL_OUTSTANDING = "colOutstanding"
    NEVER_TITLE = "neverTitle"
    NEVER_DETAIL = "neverDetail"
    OFF = "off"
    TURN_ON = "turnOn"
    TOGGLE_ON_DETAIL = "toggleOnDetail"
    TOGGLE_OFF_DETAIL = "toggleOffDetail"


class CategoriesOn(StrEnum):
    ITEMS = "items"
    SECTIONS = "sections"


class RiskTier(StrEnum):
    """The values setup stores in meta.riskTier: the keys of RISK_KEY in
    app/js/10-frameworks/05-project/00-setup.js. tests/test_check_framework.py
    checks the two lists agree."""

    LOW = "Low"
    MODERATE = "Moderate"
    HIGH = "High"


class ShellView(StrEnum):
    """View ids the shell and the primary's fixed screens already use."""

    SETUP = "setup"
    REPORT = "report"
    CHANGELOG = "changelog"
    CARD = "card"


class DocumentKey(StrEnum):
    """Top-level keys of a stored record. A supplement stores its answers under its
    own id, so its id may not be one of these."""

    META = "meta"
    ACCESS = "access"
    ARCHIVED = "archived"
    ITEMS = "items"
    GATES = "gates"
    CARD = "card"
    METRICS = "metrics"
    CARD_UPDATED_AT = "cardUpdatedAt"
    CARD_UPDATED_BY = "cardUpdatedBy"
    CREATED_AT = "createdAt"
    CREATED_BY = "createdBy"
    UPDATED_AT = "updatedAt"
    UPDATED_BY = "updatedBy"
    ID = "id"
    STATE = "_state"
    CONTENT_HASH = "contentHash"
    GENERATED = "generated"
    OPTICA = "optica"


# Which definition may use a name that is otherwise reserved. Keyed lookups only:
# a framework id is data, not a set this checker branches on.
DOCUMENT_KEY_OWNER: dict[str, str] = {DocumentKey.OPTICA: "optica"}
# Shell catalog prefixes a definition owns (its keys already live in app/i18n/*.json).
SHELL_PREFIX_OWNER: dict[str, str] = {"chai": "chai", "te": "chai", "optica": "optica"}
SCHEMA_ID_SUFFIX = "-review/"
# An export file name's suffix CHAI's exports carry, so no other framework's files
# can be taken for a CHAI review.
FILE_SUFFIX_OWNER = {"chai-review": "chai"}
# A schema id prefix that only one framework's records may carry: CHAI's exports
# have said "chai-review/" since before frameworks were data.
SCHEMA_ID_OWNER: dict[str, str] = {"chai-review/": "chai"}

OVERVIEW_CATEGORY = "overall"  # the score's own total; a category may not shadow it
GATE_VIEW_PREFIX = "g"
DEFAULT_SECTION_BODY = "blurb"

# Where each closed set lives in the schema, so schema_drift() can compare.
SCHEMA_ENUMS: dict[type[StrEnum], tuple[str, ...]] = {
    Role: ("properties", "role", "enum"),
    UiSlot: ("properties", "ui", "propertyNames", "enum"),
    StatusClass: (
        "properties",
        "statuses",
        "items",
        "properties",
        "class",
        "enum",
    ),
    GateClass: (
        "properties",
        "gates",
        "items",
        "properties",
        "options",
        "items",
        "properties",
        "class",
        "enum",
    ),
    PhaseRole: ("properties", "phases", "items", "properties", "role", "enum"),
    FlagRule: ("properties", "flags", "items", "properties", "rule", "enum"),
    CategoriesOn: ("properties", "categoriesOn", "enum"),
    CrossRefRelation: (
        "properties",
        "sections",
        "items",
        "properties",
        "items",
        "items",
        "properties",
        "crossRefs",
        "properties",
        "relation",
        "enum",
    ),
}

Path_ = tuple[str | int, ...]


def jpath(parts: Iterable[str | int]) -> str:
    """$.sections[3].items[0].id"""
    out = "$"
    for part in parts:
        out += f"[{part}]" if isinstance(part, int) else f".{part}"
    return out


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, where: str, path: Path_, message: str) -> None:
        self.lines.append(f"{where}: {jpath(path)}: {message}")


# ---------------------------------------------------------------- loading


def load_schema(path: Path = SCHEMA) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def framework_strings(doc: dict) -> dict[str, str]:
    """Every content key a definition implies, with its English: the keys the
    engine's tf() asks for (app/js/10-frameworks/01-engine/10-facade.js). A
    translation of a developer's framework holds exactly these (R-65)."""
    ns = doc["id"]
    keys = {"section": "section", "sectionBody": "blurb", "category": "category"}
    keys.update(doc.get("keys", {}))
    out: dict[str, str] = {}
    if CategoriesOn(doc.get("categoriesOn", CategoriesOn.ITEMS)) is CategoriesOn.ITEMS:
        for c in doc.get("categories", []):
            out[f"{ns}.{keys['category']}.{c['id']}"] = c["name"]
    for s in doc["sections"]:
        out[f"{ns}.{keys['section']}.{s['id']}.title"] = s["title"]
        if s.get(keys["sectionBody"]):
            out[f"{ns}.{keys['section']}.{s['id']}.{keys['sectionBody']}"] = s[
                keys["sectionBody"]
            ]
    for s in doc["sections"]:
        for it in s["items"]:
            out[f"{ns}.item.{it['id']}"] = it["text"]
    for g in doc.get("gates", []):
        out[f"{ns}.gate.{g['id']}.title"] = g["title"]
        if g.get("question"):
            out[f"{ns}.gate.{g['id']}.q"] = g["question"]
        if g.get("help"):
            out[f"{ns}.gate.{g['id']}.help"] = g["help"]
        for o in g["options"]:
            out[f"{ns}.option.{o['value']}"] = o.get("label", o["value"])
            if o.get("short"):
                out[f"{ns}.short.{o['value']}"] = o["short"]
    for st in doc["statuses"]:
        if "msg" not in st:
            out[f"{ns}.status.{st['value']}"] = st["label"]
    for w in doc.get("whos", []):
        if "msg" not in w:
            out[f"{ns}.who.{w['value']}"] = w["label"]
    for ph in doc.get("phases", []):
        if "msg" not in ph:
            out[f"{ns}.phase.{ph['key']}"] = ph["label"]
    return out


def shell_keys(path: Path = SHELL_CATALOG) -> frozenset[str]:
    """Every key in the shell catalog, en.json."""
    catalog = json.loads(path.read_text(encoding="utf-8"))
    return frozenset(key for key in catalog if not key.startswith("@"))


def catalog_problems(where: str, doc: dict, keys: frozenset[str]) -> Report:
    """Every catalog key a definition names exists, and the screens it will show
    have the sentences they need."""
    r = Report()
    ui = doc.get("ui", {})
    for slot, key in ui.items():
        if key not in keys:
            r.add(
                where, ("ui", slot), f"{key!r} is not a key in {label(SHELL_CATALOG)}"
            )
    for si, status in enumerate(doc["statuses"]):
        for field in ("msg", "reasonMsg"):
            if field in status and status[field] not in keys:
                r.add(
                    where,
                    ("statuses", si, field),
                    f"{status[field]!r} is not a catalog key",
                )
        if "reasonField" in status:
            for field in ("reasonLabel", "reasonMsg"):
                if field not in status:
                    r.add(
                        where,
                        ("statuses", si),
                        f"a status with a reasonField needs {field}",
                    )
    for wi, who in enumerate(doc.get("whos", [])):
        if "msg" in who and who["msg"] not in keys:
            r.add(where, ("whos", wi, "msg"), f"{who['msg']!r} is not a catalog key")
    for pi, phase in enumerate(doc.get("phases", [])):
        if "msg" in phase and phase["msg"] not in keys:
            r.add(
                where, ("phases", pi, "msg"), f"{phase['msg']!r} is not a catalog key"
            )
    return r


def shell_prefixes(path: Path = SHELL_CATALOG) -> frozenset[str]:
    """The first segment of every key in the shell catalog, en.json."""
    catalog = json.loads(path.read_text(encoding="utf-8"))
    return frozenset(key.split(".", 1)[0] for key in catalog if not key.startswith("@"))


def definition_files(root: Path) -> list[Path]:
    return sorted(root.glob(f"*/{DEFINITION}"))


def label(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------- the schema


def _dig(schema: dict, keys: tuple[str, ...]) -> Any:
    node: Any = schema
    for key in keys:
        node = node[key]
    return node


def schema_drift(schema: dict) -> list[str]:
    """The schema and this file state the same closed sets and the same id rule."""
    out = []
    for enum, keys in SCHEMA_ENUMS.items():
        try:
            listed = _dig(schema, keys)
        except (KeyError, TypeError):
            out.append(f"{label(SCHEMA)}: {enum.__name__} is not where expected")
            continue
        if sorted(listed) != sorted(enum):
            out.append(
                f"{label(SCHEMA)}: {jpath(keys)} lists {sorted(listed)}, "
                f"but {enum.__name__} is {sorted(enum)}"
            )
    id_def = schema.get("$defs", {}).get("id", {})
    if id_def.get("pattern") != ID_PATTERN:
        out.append(f"{label(SCHEMA)}: $.$defs.id.pattern is not ID_PATTERN")
    if sorted(id_def.get("not", {}).get("enum", [])) != sorted(UNSAFE_NAMES):
        out.append(f"{label(SCHEMA)}: $.$defs.id.not.enum is not UNSAFE_NAMES")
    return out


def _schema_message(error: ValidationError) -> str:
    if error.validator == SchemaKeyword.NOT and error.instance in UNSAFE_NAMES:
        return f"{error.instance!r} is a JavaScript prototype name, not a safe id"
    if error.validator == SchemaKeyword.PATTERN and isinstance(error.instance, str):
        return f"{error.instance!r} does not match {error.validator_value}"
    return error.message


def schema_problems(where: str, doc: Any, validator: Draft202012Validator) -> Report:
    report = Report()
    for error in sorted(
        validator.iter_errors(doc), key=lambda e: list(e.absolute_path)
    ):
        report.add(where, tuple(error.absolute_path), _schema_message(error))
    return report


# ---------------------------------------------------------------- one definition


def _duplicates(
    report: Report, where: str, entries: Iterable[tuple[Path_, Any]], what: str
) -> None:
    seen: dict[Any, Path_] = {}
    for path, value in entries:
        if value in seen:
            report.add(
                where,
                path,
                f"duplicate {what} {value!r} (also at {jpath(seen[value])})",
            )
        else:
            seen[value] = path


def _items(doc: dict) -> Iterator[tuple[Path_, dict]]:
    for si, section in enumerate(doc["sections"]):
        for ii, item in enumerate(section["items"]):
            yield ("sections", si, "items", ii), item


def definition_problems(where: str, doc: dict, folder: str | None = None) -> Report:
    """Rules about one definition alone. Assumes the schema passed."""
    r = Report()
    fid = doc["id"]
    role = Role(doc["role"])
    if folder is not None and folder != fid:
        r.add(where, ("id",), f"{fid!r} is not the directory's name {folder!r}")

    sections = doc["sections"]
    gates = doc.get("gates", [])
    categories = doc["categories"]
    statuses = doc["statuses"]
    whos = doc.get("whos", [])
    phases = doc.get("phases", [])
    plugins = set(doc.get("plugins", []))

    # Explicit, unique ids.
    _duplicates(
        r,
        where,
        ((("sections", i, "id"), s["id"]) for i, s in enumerate(sections)),
        "section id",
    )
    _duplicates(
        r,
        where,
        ((("sections", i, "n"), s["n"]) for i, s in enumerate(sections)),
        "section number",
    )
    _duplicates(r, where, (((*p, "id"), it["id"]) for p, it in _items(doc)), "item id")
    _duplicates(
        r,
        where,
        ((("gates", i, "id"), g["id"]) for i, g in enumerate(gates)),
        "gate id",
    )
    _duplicates(
        r,
        where,
        ((("categories", i, "id"), c["id"]) for i, c in enumerate(categories)),
        "category id",
    )
    _duplicates(
        r,
        where,
        ((("statuses", i, "value"), s["value"]) for i, s in enumerate(statuses)),
        "status value",
    )
    _duplicates(
        r,
        where,
        ((("whos", i, "value"), w["value"]) for i, w in enumerate(whos)),
        "who value",
    )
    _duplicates(
        r,
        where,
        ((("phases", i, "key"), p["key"]) for i, p in enumerate(phases)),
        "phase key",
    )
    for gi, gate in enumerate(gates):
        _duplicates(
            r,
            where,
            (
                (("gates", gi, "options", oi, "value"), o["value"])
                for oi, o in enumerate(gate["options"])
            ),
            f"option value in gate {gate['id']!r}",
        )
        for oi, option in enumerate(gate["options"]):
            if option["value"] in UNSAFE_NAMES or "." in option["value"]:
                r.add(
                    where,
                    ("gates", gi, "options", oi, "value"),
                    f"{option['value']!r} is not a safe option value",
                )

    for ci, category in enumerate(categories):
        if category["id"] == OVERVIEW_CATEGORY:
            r.add(
                where,
                ("categories", ci, "id"),
                f"{OVERVIEW_CATEGORY!r} is the score's total, not a category",
            )

    # The section body field is the one keys.sectionBody names.
    body = doc.get("keys", {}).get("sectionBody", DEFAULT_SECTION_BODY)
    known = {"id", "n", "title", "category", "slots", "items", body}
    for si, section in enumerate(sections):
        for key in section:
            if key not in known:
                r.add(
                    where,
                    ("sections", si, key),
                    f"unknown field; the text field is keys.sectionBody ({body!r})",
                )

    # Categories sit on items or on sections, never both, never neither.
    on = CategoriesOn(doc.get("categoriesOn", CategoriesOn.ITEMS))
    category_ids = {c["id"] for c in categories}
    for si, section in enumerate(sections):
        match on:
            case CategoriesOn.SECTIONS:
                if "category" not in section:
                    r.add(
                        where,
                        ("sections", si),
                        "categoriesOn is sections, but this section has no category",
                    )
                elif section["category"] not in category_ids:
                    r.add(
                        where,
                        ("sections", si, "category"),
                        f"no category {section['category']!r}",
                    )
            case CategoriesOn.ITEMS:
                if "category" in section:
                    r.add(
                        where,
                        ("sections", si, "category"),
                        "categoriesOn is items, so a section has no category",
                    )
            case _:
                assert_never(on)
    for path, item in _items(doc):
        match on:
            case CategoriesOn.ITEMS:
                if "category" not in item:
                    r.add(
                        where,
                        path,
                        "categoriesOn is items, but this item has no category",
                    )
                elif item["category"] not in category_ids:
                    r.add(
                        where, (*path, "category"), f"no category {item['category']!r}"
                    )
            case CategoriesOn.SECTIONS:
                if "category" in item:
                    r.add(
                        where,
                        (*path, "category"),
                        "categoriesOn is sections, so an item has no category",
                    )
            case _:
                assert_never(on)
        who_values = {w["value"] for w in whos}
        if "who" in item and item["who"] not in who_values:
            r.add(where, (*path, "who"), f"no who {item['who']!r} in whos")

    # Plugins are namespaced by the framework, and slots and flags name declared ones.
    for pi, plugin in enumerate(doc.get("plugins", [])):
        if plugin.split(".", 1)[0] != fid:
            r.add(where, ("plugins", pi), f"{plugin!r} is not namespaced {fid + '.'!r}")
    for si, section in enumerate(sections):
        for ki, slot in enumerate(section.get("slots", [])):
            if slot not in plugins:
                r.add(
                    where,
                    ("sections", si, "slots", ki),
                    f"no plugin {slot!r} in plugins",
                )

    # Supplements.
    if role is Role.SUPPLEMENT and "gates" in doc:
        r.add(
            where,
            ("gates",),
            "a supplement may not declare gates (its sign-off could not be attributed)",
        )
    if role is Role.PRIMARY and "optIn" in doc:
        r.add(
            where,
            ("optIn",),
            "only a supplement can be opt-in; the primary is always on",
        )

    # Gates.
    section_ids = {s["id"] for s in sections}
    gate_ids = [g["id"] for g in gates]
    classes: dict[str, tuple[GateClass, Path_]] = {}
    ends = False
    for gi, gate in enumerate(gates):
        if gate["after"] not in section_ids:
            r.add(where, ("gates", gi, "after"), f"no section {gate['after']!r}")
        for oi, option in enumerate(gate["options"]):
            cls = GateClass(option["class"])
            ends = ends or cls in ENDING_CLASSES
            path = ("gates", gi, "options", oi, "class")
            first = classes.setdefault(option["value"], (cls, path))
            if first[0] is not cls:
                r.add(
                    where,
                    path,
                    f"option {option['value']!r} is {cls} here, {first[0]} at "
                    f"{jpath(first[1])}",
                )
    if role is Role.PRIMARY and gates and not ends:
        r.add(
            where,
            ("gates",),
            "a primary with gates needs a stop or retire option, "
            "or no project can end (R-56)",
        )

    # Phases.
    last_role: PhaseRole | None = None
    order = list(PhaseRole)
    live_at: Path_ | None = None
    for pi, phase in enumerate(phases):
        prole = PhaseRole(phase["role"])
        if pi == 0 and "reachedBy" in phase:
            r.add(
                where,
                ("phases", 0, "reachedBy"),
                "the first phase is where a project starts; it has no reachedBy",
            )
        if pi > 0 and "reachedBy" not in phase:
            r.add(where, ("phases", pi), "a phase after the first needs reachedBy")
        if "reachedBy" in phase and phase["reachedBy"] not in gate_ids:
            r.add(where, ("phases", pi, "reachedBy"), f"no gate {phase['reachedBy']!r}")
        if "section" in phase and phase["section"] not in section_ids:
            r.add(where, ("phases", pi, "section"), f"no section {phase['section']!r}")
        if last_role is not None and order.index(prole) < order.index(last_role):
            r.add(
                where,
                ("phases", pi, "role"),
                f"{prole} comes after {last_role}; roles never go backward",
            )
        if prole is PhaseRole.LIVE:
            if live_at is not None:
                r.add(
                    where,
                    ("phases", pi, "role"),
                    f"a second live phase (first at {jpath(live_at)})",
                )
            else:
                live_at = ("phases", pi, "role")
        last_role = prole

    # Review.
    review = doc.get("review")
    if review is not None:
        if review["gate"] not in gate_ids:
            r.add(where, ("review", "gate"), f"no gate {review['gate']!r}")
        elif review["gate"] != gate_ids[-1]:
            r.add(
                where,
                ("review", "gate"),
                f"the review gate {review['gate']!r} must be the last gate "
                f"({gate_ids[-1]!r})",
            )
        for ai, anchor in enumerate(review.get("anchors", [])):
            if anchor not in gate_ids:
                r.add(where, ("review", "anchors", ai), f"no gate {anchor!r}")
        tiers = set(RiskTier)
        for tier in review.get("monthsByRiskTier", {}):
            if tier not in tiers:
                r.add(
                    where,
                    ("review", "monthsByRiskTier", tier),
                    f"not a risk tier setup stores ({', '.join(RiskTier)})",
                )

    # Flags.
    for fi, flag in enumerate(doc.get("flags", [])):
        path = ("flags", fi)
        if ("rule" in flag) == ("plugin" in flag):
            r.add(where, path, "a flag names exactly one of rule or plugin")
            continue
        if "plugin" in flag:
            if flag["plugin"] not in plugins:
                r.add(
                    where,
                    (*path, "plugin"),
                    f"no plugin {flag['plugin']!r} in plugins",
                )
            for extra in ("gate", "days"):
                if extra in flag:
                    r.add(where, (*path, extra), "a plugin flag takes no parameters")
            continue
        rule = FlagRule(flag["rule"])
        match rule:
            case FlagRule.REVIEW | FlagRule.REVISE_AT_REVIEW:
                needs = {"gate"}
            case FlagRule.IDLE:
                needs = {"days"}
            case (
                FlagRule.PAST_DUE
                | FlagRule.OPEN_WHEN_LIVE
                | FlagRule.APPROVAL_WITHOUT_RATIONALE
            ):
                needs = set()
            case _:
                assert_never(rule)
        for param in ("gate", "days"):
            if param in needs and param not in flag:
                r.add(where, path, f"rule {rule} needs {param}")
            if param not in needs and param in flag:
                r.add(where, (*path, param), f"rule {rule} takes no {param}")
        if "gate" in flag and flag["gate"] not in gate_ids:
            r.add(where, (*path, "gate"), f"no gate {flag['gate']!r}")
        if rule is FlagRule.OPEN_WHEN_LIVE and live_at is None:
            r.add(where, path, "rule openWhenLive needs a live phase")

    # Samples name what exists, and only a primary has them (a supplement's
    # answers live under its own key, which a sample does not write).
    samples = doc.get("samples", [])
    if samples and role is not Role.PRIMARY:
        r.add(where, ("samples",), "only a primary framework has samples")
    item_ids = {it["id"] for _, it in _items(doc)}
    status_values = {s["value"] for s in statuses}
    options = {g["id"]: {o["value"] for o in g["options"]} for g in gates}
    _duplicates(
        r,
        where,
        ((("samples", i, "name"), s["name"]) for i, s in enumerate(samples)),
        "sample name",
    )
    for si, sample in enumerate(samples):
        for item, status in sample.get("answers", {}).items():
            if item not in item_ids:
                r.add(where, ("samples", si, "answers", item), f"no item {item!r}")
            elif status not in status_values:
                r.add(where, ("samples", si, "answers", item), f"no status {status!r}")
        for gate, decision in sample.get("decisions", {}).items():
            if gate not in options:
                r.add(where, ("samples", si, "decisions", gate), f"no gate {gate!r}")
            elif decision[0] not in options[gate]:
                r.add(
                    where,
                    ("samples", si, "decisions", gate, 0),
                    f"gate {gate!r} has no option {decision[0]!r}",
                )
        tier = sample.get("meta", {}).get("riskTier")
        if tier is not None and tier not in set(RiskTier):
            r.add(
                where,
                ("samples", si, "meta", "riskTier"),
                f"not a risk tier setup stores ({', '.join(RiskTier)})",
            )

    # Namespaces and the export id.
    if fid not in doc["namespaces"]:
        r.add(where, ("namespaces",), f"must include the id {fid!r}")
    export = doc.get("export")
    if export is not None:
        schema_id = export["schemaId"]
        if not schema_id.startswith(fid + SCHEMA_ID_SUFFIX):
            r.add(
                where,
                ("export", "schemaId"),
                f"{schema_id!r} is not {fid}{SCHEMA_ID_SUFFIX}<n>",
            )
        for prefix, owner in SCHEMA_ID_OWNER.items():
            if schema_id.startswith(prefix) and owner != fid:
                r.add(
                    where,
                    ("export", "schemaId"),
                    f"{prefix!r} is reserved to {owner!r}",
                )

    if export is not None and "fileSuffix" in export:
        suffix = export["fileSuffix"]
        owner = FILE_SUFFIX_OWNER.get(suffix)
        if owner is not None and owner != fid:
            r.add(
                where, ("export", "fileSuffix"), f"{suffix!r} is reserved to {owner!r}"
            )

    # A supplement's id is its records' top-level key.
    if (
        role is Role.SUPPLEMENT
        and fid in set(DocumentKey)
        and DOCUMENT_KEY_OWNER.get(fid) != fid
    ):
        r.add(where, ("id",), f"{fid!r} is a reserved top-level key of a record")
    return r


# ---------------------------------------------------------------- the build


def view_ids(doc: dict) -> Iterator[tuple[Path_, str]]:
    prefix = doc.get("viewPrefix", doc["id"] + "-")
    for si, section in enumerate(doc["sections"]):
        yield ("sections", si, "id"), prefix + section["id"]
    for gi, gate in enumerate(doc.get("gates", [])):
        yield ("gates", gi, "id"), GATE_VIEW_PREFIX + gate["id"]
    if Role(doc["role"]) is Role.SUPPLEMENT:
        yield ("id",), doc["id"]


def build_problems(defs: dict[str, dict], prefixes: frozenset[str]) -> Report:
    """Rules across every definition: views, namespaces, requires and crossRefs."""
    r = Report()
    by_id = {doc["id"]: (where, doc) for where, doc in defs.items()}

    shell = {str(v): "the shell" for v in ShellView}
    views: dict[str, str] = dict(shell)
    for where, doc in defs.items():
        for path, view in view_ids(doc):
            if not ID_RE.match(view) or view in UNSAFE_NAMES:
                r.add(where, path, f"view id {view!r} is not a safe id")
            if view in views:
                r.add(where, path, f"view id {view!r} is already used by {views[view]}")
            else:
                views[view] = f"{where} {jpath(path)}"

    suffixes: dict[str, str] = {}
    for where, doc in defs.items():
        suffix = (doc.get("export") or {}).get("fileSuffix")
        if suffix is None:
            continue
        if suffix in suffixes:
            r.add(
                where,
                ("export", "fileSuffix"),
                f"{suffix!r} is also the file suffix of {suffixes[suffix]}",
            )
        else:
            suffixes[suffix] = where

    owners: dict[str, str] = {}
    for where, doc in defs.items():
        fid = doc["id"]
        for ni, ns in enumerate(doc["namespaces"]):
            if ns in prefixes and SHELL_PREFIX_OWNER.get(ns) != fid:
                r.add(
                    where,
                    ("namespaces", ni),
                    f"{ns!r} is a shell catalog prefix (app/i18n/en.json)",
                )
            if ns in owners:
                r.add(
                    where,
                    ("namespaces", ni),
                    f"{ns!r} is also a namespace of {owners[ns]}",
                )
            else:
                owners[ns] = where

    for where, doc in defs.items():
        fid = doc["id"]
        required = doc.get("requires", [])
        for ri, other in enumerate(required):
            if other == fid:
                r.add(where, ("requires", ri), "a framework cannot require itself")
            elif other not in by_id:
                r.add(
                    where,
                    ("requires", ri),
                    f"no framework {other!r} in the build ({CONFIG_LABEL})",
                )
        named: set[str] = set()  # one line per missing target, not one per item
        for path, item in _items(doc):
            ref = item.get("crossRefs")
            if ref is None:
                continue
            target = ref["framework"]
            relation = CrossRefRelation(ref["relation"])
            # The relation and the ids must agree: the dashboard's chip reads the
            # ids, so a partial with none would show "not covered" (#174).
            match relation:
                case CrossRefRelation.EQUIVALENT | CrossRefRelation.PARTIAL:
                    if not ref["ids"]:
                        r.add(
                            where,
                            (*path, "crossRefs", "ids"),
                            f"crossRef relation {str(relation)!r} names no item",
                        )
                case CrossRefRelation.OPTICA_ONLY:
                    if ref["ids"]:
                        r.add(
                            where,
                            (*path, "crossRefs", "ids"),
                            f"crossRef relation {str(relation)!r} names items"
                            f" {ref['ids']}, and must name none",
                        )
                case _:
                    assert_never(relation)
            if target not in by_id:
                if target not in named:
                    named.add(target)
                    r.add(
                        where,
                        (*path, "crossRefs", "framework"),
                        f"no framework {target!r} (first of its crossRefs)",
                    )
                continue
            if target not in required and target not in named:
                named.add(target)
                r.add(
                    where,
                    (*path, "crossRefs", "framework"),
                    f"{target!r} is not in requires",
                )
            target_items = {it["id"] for _, it in _items(by_id[target][1])}
            for ki, ref_id in enumerate(ref["ids"]):
                if ref_id not in target_items:
                    r.add(
                        where,
                        (*path, "crossRefs", "ids", ki),
                        f"no item {ref_id!r} in {target!r}",
                    )
    return r


# ---------------------------------------------------------------- entry points


def load_config(path: Path = CONFIG) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def config_problems(config: Any, defs: dict[str, dict]) -> list[str]:
    """The build config names frameworks that exist, its primary among them, and
    exactly one primary-role definition: the one it names."""
    where = CONFIG_LABEL
    if not isinstance(config, dict) or not isinstance(config.get("frameworks"), list):
        return [f"{where}: $: must be an object with a list of frameworks"]
    selected = config["frameworks"]
    primary = config.get("primary")
    out = []
    by_id = {doc["id"]: doc for doc in defs.values()}
    for i, fid in enumerate(selected):
        if fid not in by_id:
            out.append(f"{where}: $.frameworks[{i}]: no valid definition {fid!r}")
    if len(set(selected)) != len(selected):
        out.append(f"{where}: $.frameworks: lists a framework twice")
    if primary not in selected:
        out.append(f"{where}: $.primary: {primary!r} is not in frameworks")
    primaries = [
        fid
        for fid in selected
        if fid in by_id and Role(by_id[fid]["role"]) is Role.PRIMARY
    ]
    if len(primaries) != 1:
        out.append(
            f"{where}: $.frameworks: a build needs exactly one primary, found "
            f"{len(primaries)} ({', '.join(primaries) or 'none'})"
        )
    elif primaries[0] != primary:
        out.append(
            f"{where}: $.primary: {primary!r} is not the primary; {primaries[0]!r} is"
        )
    return out


def problems(
    defs: dict[str, Any],
    schema: dict | None = None,
    prefixes: frozenset[str] | None = None,
    folders: dict[str, str] | None = None,
    config: Any = None,
    catalog: frozenset[str] | None = None,
) -> list[str]:
    """Every problem in a set of definitions, keyed by where each came from.

    `folders` maps a definition to its directory name; by default the parent of
    the path it is keyed by."""
    schema = load_schema() if schema is None else schema
    prefixes = shell_prefixes() if prefixes is None else prefixes
    out = schema_drift(schema)
    validator = Draft202012Validator(schema)
    valid: dict[str, dict] = {}
    for where, doc in defs.items():
        report = schema_problems(where, doc, validator)
        out += report.lines
        if report.lines:
            continue  # the rules below assume the shape
        folder = (folders or {}).get(where, Path(where).parent.name)
        out += definition_problems(where, doc, folder).lines
        out += catalog_problems(
            where, doc, shell_keys() if catalog is None else catalog
        ).lines
        valid[where] = doc
    config = load_config() if config is None else config
    out += config_problems(config, valid)
    selected = set(config.get("frameworks", [])) if isinstance(config, dict) else set()
    build = {w: d for w, d in valid.items() if d["id"] in selected}
    out += build_problems(build, prefixes).lines
    return out


def load(paths: Iterable[Path]) -> tuple[dict[str, Any], list[str]]:
    defs: dict[str, Any] = {}
    errors = []
    for path in paths:
        try:
            defs[label(path)] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{label(path)}: $: cannot read: {exc}")
    return defs, errors


def main(argv: list[str] | None = None) -> int:
    paths = definition_files(FRAMEWORKS)
    if not paths:
        print(f"check-framework: no {DEFINITION} under {label(FRAMEWORKS)}")
        return 1
    defs, errors = load(paths)
    found = errors + problems(defs)
    for line in found:
        print(line)
    if found:
        print(f"check-framework: {len(found)} problem(s)")
        return 1
    print(f"check-framework: {len(defs)} definition(s) OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
