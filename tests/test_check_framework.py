#!/usr/bin/env python3
"""check-framework notices every way a framework definition goes wrong (#168, R-63).

The real definitions (CHAI and OPTICA) must pass, and every rule is shown failing
on a copy broken in the way it guards against: the checker must report a line that
names the file, the JSON path and the problem. A check that is never shown to fail
is a claim, not a control.

    pixi run test-check-framework
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "check_framework", ROOT / "scripts" / "check_framework.py"
)
ck = importlib.util.module_from_spec(spec)
sys.modules["check_framework"] = ck
spec.loader.exec_module(ck)

CHAI = "app/frameworks/chai/framework.json"
OPTICA = "app/frameworks/optica/framework.json"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def real() -> dict[str, dict]:
    return {
        rel: json.loads((ROOT / rel).read_text(encoding="utf-8"))
        for rel in (CHAI, OPTICA)
    }


REAL = real()
SCHEMA = ck.load_schema()


def run(mutate: Callable[[dict, dict], object], schema: dict | None = None) -> list:
    defs = copy.deepcopy(REAL)
    mutate(defs[CHAI], defs[OPTICA])
    return ck.problems(defs, schema=schema if schema is not None else SCHEMA)


def notices(
    name: str,
    mutate: Callable[[dict, dict], object],
    file: str,
    path: str,
    words: str,
    schema: dict | None = None,
) -> None:
    """The checker reports `words` at `file: path`."""
    found = run(mutate, schema)
    want = f"{file}: {path}: "
    hit = [line for line in found if line.startswith(want) and words in line]
    check(name, bool(hit), f"wanted {want}...{words}; got {found[:4]}")


def gate(chai: dict, gid: str) -> dict:
    return next(g for g in chai["gates"] if g["id"] == gid)


def setv(obj: dict, key: str, value: object) -> None:
    obj[key] = value


def main() -> int:
    print("The real definitions")
    check("check-framework passes on the repository", ck.main([]) == 0)
    found = ck.problems(copy.deepcopy(REAL))
    check("CHAI and OPTICA have no problems", not found, str(found[:4]))
    check("the schema agrees with the checker's enums", not ck.schema_drift(SCHEMA))
    check(
        "every definition under app/frameworks/ is checked",
        {ck.label(p) for p in ck.definition_files(ck.FRAMEWORKS)} >= {CHAI, OPTICA},
    )

    setup = (ROOT / "app/js/10-frameworks/05-project/00-setup.js").read_text("utf-8")
    risk = re.search(r"const RISK_KEY = Object\.freeze\(\{(.*?)\}\)", setup)
    stored = re.findall(r"(\w+)\s*:", risk.group(1)) if risk else []
    check(
        "RiskTier is exactly the risk tiers setup stores (RISK_KEY)",
        sorted(stored) == sorted(ck.RiskTier),
        f"setup stores {stored}",
    )

    print("The schema notices (mutation)")
    notices(
        "a schema version it does not know",
        lambda c, o: setv(c, "schemaVersion", 2),
        CHAI,
        "$.schemaVersion",
        "1 was expected",
    )
    notices(
        "a missing required field",
        lambda c, o: c.pop("namespaces"),
        CHAI,
        "$",
        "'namespaces' is a required property",
    )
    notices(
        "a misspelled top-level field",
        lambda c, o: setv(c, "gate", []),
        CHAI,
        "$",
        "'gate' was unexpected",
    )
    notices(
        "an id with a dot",
        lambda c, o: setv(c["sections"][0]["items"][0], "id", "s1.1"),
        CHAI,
        "$.sections[0].items[0].id",
        "does not match",
    )
    notices(
        "an id that starts with a hyphen",
        lambda c, o: setv(c["categories"][0], "id", "-U"),
        CHAI,
        "$.categories[0].id",
        "does not match",
    )
    notices(
        "an id longer than 64 characters",
        lambda c, o: setv(c["gates"][0], "id", "A" * 65),
        CHAI,
        "$.gates[0].id",
        "does not match",
    )
    for unsafe in ("constructor", "toString", "hasOwnProperty", "valueOf"):
        notices(
            f"a prototype name as an id ({unsafe})",
            lambda c, o, u=unsafe: setv(c["categories"][0], "id", u),
            CHAI,
            "$.categories[0].id",
            "prototype name",
        )
    notices(
        "a dotted namespace",
        lambda c, o: setv(o, "namespaces", ["optica", "optica.x"]),
        OPTICA,
        "$.namespaces[1]",
        "does not match",
    )
    notices(
        "a status class outside StatusClass",
        lambda c, o: setv(c["statuses"][0], "class", "finished"),
        CHAI,
        "$.statuses[0].class",
        "is not one of",
    )
    notices(
        "an option class outside GateClass",
        lambda c, o: setv(c["gates"][0]["options"][0], "class", "approve"),
        CHAI,
        "$.gates[0].options[0].class",
        "is not one of",
    )
    notices(
        "a phase role outside PhaseRole",
        lambda c, o: setv(c["phases"][0], "role", "retired"),
        CHAI,
        "$.phases[0].role",
        "is not one of",
    )
    notices(
        "a flag rule outside FlagRule",
        lambda c, o: setv(c["flags"][0], "rule", "lateish"),
        CHAI,
        "$.flags[0].rule",
        "is not one of",
    )
    notices(
        "categoriesOn outside CategoriesOn",
        lambda c, o: setv(o, "categoriesOn", "chapters"),
        OPTICA,
        "$.categoriesOn",
        "is not one of",
    )
    notices(
        "a crossRef relation outside CrossRefRelation",
        lambda c, o: setv(o["sections"][0]["items"][0]["crossRefs"], "relation", "x"),
        OPTICA,
        "$.sections[0].items[0].crossRefs.relation",
        "is not one of",
    )
    notices(
        "an export schema id not shaped <id>-review/<n>",
        lambda c, o: setv(c["export"], "schemaId", "chai/2"),
        CHAI,
        "$.export.schemaId",
        "does not match",
    )
    notices(
        "empty item text",
        lambda c, o: setv(c["sections"][0]["items"][0], "text", ""),
        CHAI,
        "$.sections[0].items[0].text",
        "should be non-empty",
    )
    notices(
        "an unknown field on an item",
        lambda c, o: setv(c["sections"][0]["items"][0], "weight", 2),
        CHAI,
        "$.sections[0].items[0]",
        "'weight' was unexpected",
    )

    drifted = copy.deepcopy(SCHEMA)
    drifted["properties"]["statuses"]["items"]["properties"]["class"]["enum"].append(
        "finished"
    )
    check(
        "a schema enum that drifts from the checker's",
        any("StatusClass" in line for line in ck.schema_drift(drifted)),
    )
    drifted = copy.deepcopy(SCHEMA)
    drifted["$defs"]["id"]["pattern"] = "^.+$"
    check(
        "a schema id pattern that drifts from ID_PATTERN",
        any("ID_PATTERN" in line for line in ck.schema_drift(drifted)),
    )
    drifted = copy.deepcopy(SCHEMA)
    drifted["$defs"]["id"]["not"]["enum"].remove("constructor")
    check(
        "a schema prototype-name list that drifts from UNSAFE_NAMES",
        any("UNSAFE_NAMES" in line for line in ck.schema_drift(drifted)),
    )

    print("Unique ids (mutation)")
    notices(
        "a duplicate section id",
        lambda c, o: setv(c["sections"][1], "id", "s1"),
        CHAI,
        "$.sections[1].id",
        "duplicate section id 's1'",
    )
    notices(
        "a duplicate section number",
        lambda c, o: setv(c["sections"][1], "n", 1),
        CHAI,
        "$.sections[1].n",
        "duplicate section number",
    )
    notices(
        "a duplicate item id, across sections",
        lambda c, o: setv(c["sections"][2]["items"][0], "id", "s1-1"),
        CHAI,
        "$.sections[2].items[0].id",
        "duplicate item id 's1-1'",
    )
    notices(
        "a duplicate gate id",
        lambda c, o: setv(c["gates"][1], "id", "A"),
        CHAI,
        "$.gates[1].id",
        "duplicate gate id 'A'",
    )
    notices(
        "a duplicate category id",
        lambda c, o: setv(c["categories"][1], "id", "U"),
        CHAI,
        "$.categories[1].id",
        "duplicate category id 'U'",
    )
    notices(
        "a duplicate status value",
        lambda c, o: setv(c["statuses"][1], "value", "met"),
        CHAI,
        "$.statuses[1].value",
        "duplicate status value 'met'",
    )
    notices(
        "a duplicate option value in one gate",
        lambda c, o: setv(c["gates"][0]["options"][1], "value", "Proceed"),
        CHAI,
        "$.gates[0].options[1].value",
        "duplicate option value",
    )
    notices(
        "a duplicate who value",
        lambda c, o: setv(o["whos"][1], "value", "adopter"),
        OPTICA,
        "$.whos[1].value",
        "duplicate who value",
    )
    notices(
        "a duplicate phase key",
        lambda c, o: setv(c["phases"][1], "key", "intake"),
        CHAI,
        "$.phases[1].key",
        "duplicate phase key",
    )
    notices(
        "a prototype name as an option value",
        lambda c, o: setv(c["gates"][0]["options"][0], "value", "constructor"),
        CHAI,
        "$.gates[0].options[0].value",
        "not a safe option value",
    )
    notices(
        "a dotted option value",
        lambda c, o: setv(c["gates"][0]["options"][0], "value", "Go.now"),
        CHAI,
        "$.gates[0].options[0].value",
        "not a safe option value",
    )
    notices(
        "a category named overall",
        lambda c, o: setv(c["categories"][0], "id", "overall"),
        CHAI,
        "$.categories[0].id",
        "the score's total",
    )

    print("Sections, categories, whos and plugins (mutation)")
    notices(
        "a section text field that keys.sectionBody does not name",
        lambda c, o: setv(o["sections"][0], "blurb", o["sections"][0].pop("purpose")),
        OPTICA,
        "$.sections[0].blurb",
        "keys.sectionBody",
    )
    notices(
        "categoriesOn sections, with a section missing its category",
        lambda c, o: o["sections"][0].pop("category"),
        OPTICA,
        "$.sections[0]",
        "has no category",
    )
    notices(
        "categoriesOn sections, with a category on an item",
        lambda c, o: setv(o["sections"][0]["items"][0], "category", "A"),
        OPTICA,
        "$.sections[0].items[0].category",
        "an item has no category",
    )
    notices(
        "categoriesOn items, with a category on a section",
        lambda c, o: setv(c["sections"][0], "category", "U"),
        CHAI,
        "$.sections[0].category",
        "a section has no category",
    )
    notices(
        "an item with no category",
        lambda c, o: c["sections"][0]["items"][0].pop("category"),
        CHAI,
        "$.sections[0].items[0]",
        "has no category",
    )
    notices(
        "an item in a category that does not exist",
        lambda c, o: setv(c["sections"][0]["items"][0], "category", "Z"),
        CHAI,
        "$.sections[0].items[0].category",
        "no category 'Z'",
    )
    notices(
        "a section in a category that does not exist",
        lambda c, o: setv(o["sections"][0], "category", "Z"),
        OPTICA,
        "$.sections[0].category",
        "no category 'Z'",
    )
    notices(
        "an item owed by a who that is not declared",
        lambda c, o: setv(o["sections"][0]["items"][0], "who", "vendor"),
        OPTICA,
        "$.sections[0].items[0].who",
        "no who 'vendor'",
    )
    notices(
        "a plugin not namespaced by its framework",
        lambda c, o: setv(c["plugins"], 0, "optica.modelCard"),
        CHAI,
        "$.plugins[0]",
        "not namespaced",
    )
    notices(
        "a section slot that is not a declared plugin",
        lambda c, o: setv(c["sections"][3], "slots", ["chai.nothing"]),
        CHAI,
        "$.sections[3].slots[0]",
        "no plugin 'chai.nothing'",
    )

    print("Roles (mutation)")
    notices(
        "a supplement that declares gates",
        lambda c, o: setv(o, "gates", copy.deepcopy(c["gates"][:1])),
        OPTICA,
        "$.gates",
        "a supplement may not declare gates",
    )
    notices(
        "an opt-in primary",
        lambda c, o: setv(c, "optIn", True),
        CHAI,
        "$.optIn",
        "only a supplement",
    )

    print("Gates (mutation)")
    notices(
        "a gate after a section that does not exist",
        lambda c, o: setv(c["gates"][0], "after", "s9"),
        CHAI,
        "$.gates[0].after",
        "no section 's9'",
    )
    notices(
        "an option value with two classes across gates",
        lambda c, o: setv(c["gates"][1]["options"][0], "class", "conditional"),
        CHAI,
        "$.gates[1].options[0].class",
        "option 'Proceed' is conditional here, go at $.gates[0]",
    )

    def no_ending(c: dict, o: dict) -> None:
        for g in c["gates"]:
            for opt in g["options"]:
                if opt["class"] in (ck.GateClass.STOP, ck.GateClass.RETIRE):
                    opt["class"] = ck.GateClass.REVISE

    notices(
        "a primary with gates that no option can end",
        no_ending,
        CHAI,
        "$.gates",
        "needs a stop or retire option",
    )

    print("Phases (mutation)")
    notices(
        "a first phase with reachedBy",
        lambda c, o: setv(c["phases"][0], "reachedBy", "A"),
        CHAI,
        "$.phases[0].reachedBy",
        "has no reachedBy",
    )
    notices(
        "a later phase without reachedBy",
        lambda c, o: c["phases"][2].pop("reachedBy"),
        CHAI,
        "$.phases[2]",
        "needs reachedBy",
    )
    notices(
        "a phase reached by a gate that does not exist",
        lambda c, o: setv(c["phases"][1], "reachedBy", "Q"),
        CHAI,
        "$.phases[1].reachedBy",
        "no gate 'Q'",
    )
    notices(
        "a phase on a section that does not exist",
        lambda c, o: setv(c["phases"][1], "section", "s9"),
        CHAI,
        "$.phases[1].section",
        "no section 's9'",
    )
    notices(
        "phase roles going backward",
        lambda c, o: setv(c["phases"][2], "role", "planning"),
        CHAI,
        "$.phases[2].role",
        "never go backward",
    )
    notices(
        "two live phases",
        lambda c, o: c["phases"].append({**c["phases"][-1], "key": "again"}),
        CHAI,
        "$.phases[4].role",
        "a second live phase",
    )

    print("Review (mutation)")
    notices(
        "a review gate that does not exist",
        lambda c, o: setv(c["review"], "gate", "Q"),
        CHAI,
        "$.review.gate",
        "no gate 'Q'",
    )
    notices(
        "a review gate that is not the last gate",
        lambda c, o: setv(c["review"], "gate", "C"),
        CHAI,
        "$.review.gate",
        "must be the last gate",
    )
    notices(
        "a review anchor that does not exist",
        lambda c, o: setv(c["review"], "anchors", ["D", "Q"]),
        CHAI,
        "$.review.anchors[1]",
        "no gate 'Q'",
    )
    for tier in ("Critical", "high", "HIGH"):
        notices(
            f"a risk tier setup never stores ({tier})",
            lambda c, o, t=tier: setv(c["review"], "monthsByRiskTier", {t: 6}),
            CHAI,
            f"$.review.monthsByRiskTier.{tier}",
            "not a risk tier",
        )

    print("Samples (mutation)")
    item0 = REAL[CHAI]["sections"][0]["items"][0]["id"]
    gate0 = REAL[CHAI]["gates"][0]
    option0 = gate0["options"][0]["value"]
    status0 = REAL[CHAI]["statuses"][0]["value"]

    def sample(**over: object) -> dict:
        s = {
            "name": "Example",
            "answers": {item0: status0},
            "decisions": {gate0["id"]: [option0, -10, "Why"]},
            "meta": {"riskTier": "High"},
        }
        s.update(over)
        return s

    found = run(lambda c, o: setv(c, "samples", [sample()]))
    check("a sample that names what exists passes", found == [], str(found[:3]))
    notices(
        "a sample answers an item that does not exist",
        lambda c, o: setv(c, "samples", [sample(answers={"nope": status0})]),
        CHAI,
        "$.samples[0].answers.nope",
        "no item 'nope'",
    )
    notices(
        "a sample answers with a status that does not exist",
        lambda c, o: setv(c, "samples", [sample(answers={item0: "maybe"})]),
        CHAI,
        f"$.samples[0].answers.{item0}",
        "no status 'maybe'",
    )
    notices(
        "a sample decides a gate that does not exist",
        lambda c, o: setv(c, "samples", [sample(decisions={"Q": [option0, 0]})]),
        CHAI,
        "$.samples[0].decisions.Q",
        "no gate 'Q'",
    )
    notices(
        "a sample decides with an option the gate does not have",
        lambda c, o: setv(
            c, "samples", [sample(decisions={gate0["id"]: ["Shrug", 0]})]
        ),
        CHAI,
        f"$.samples[0].decisions.{gate0['id']}[0]",
        "has no option 'Shrug'",
    )
    notices(
        "a sample's risk tier setup never stores",
        lambda c, o: setv(c, "samples", [sample(meta={"riskTier": "Severe"})]),
        CHAI,
        "$.samples[0].meta.riskTier",
        "not a risk tier",
    )
    notices(
        "two samples with one name",
        lambda c, o: setv(c, "samples", [sample(), sample()]),
        CHAI,
        "$.samples[1].name",
        "duplicate",
    )
    notices(
        "a supplement with samples",
        lambda c, o: setv(o, "samples", [{"name": "x"}]),
        OPTICA,
        "$.samples",
        "only a primary",
    )
    # The stamp is the build's to write: a sample cannot set meta.framework.
    found = run(
        lambda c, o: setv(c, "samples", [sample(meta={"framework": {"id": "x"}})])
    )
    check(
        "a sample that sets the record's framework stamp",
        any("samples" in line and "framework" in line for line in found),
        str(found[:3]),
    )
    found = run(
        lambda c, o: setv(c, "samples", [sample(decisions={gate0["id"]: [option0]})])
    )
    check(
        "a decision with no day",
        any("$.samples[0].decisions" in line for line in found),
        str(found[:3]),
    )

    print("Flags (mutation)")
    notices(
        "a flag on a gate that does not exist",
        lambda c, o: setv(c["flags"][2], "gate", "Q"),
        CHAI,
        "$.flags[2].gate",
        "no gate 'Q'",
    )
    notices(
        "a review flag with no gate",
        lambda c, o: c["flags"][2].pop("gate"),
        CHAI,
        "$.flags[2]",
        "rule review needs gate",
    )
    notices(
        "an idle flag with no days",
        lambda c, o: c["flags"][7].pop("days"),
        CHAI,
        "$.flags[7]",
        "rule idle needs days",
    )
    notices(
        "a parameter a rule does not take",
        lambda c, o: setv(c["flags"][0], "days", 3),
        CHAI,
        "$.flags[0].days",
        "rule pastDue takes no days",
    )
    notices(
        "a flag naming both a rule and a plugin",
        lambda c, o: setv(c["flags"][0], "plugin", "chai.metrics"),
        CHAI,
        "$.flags[0]",
        "exactly one of rule or plugin",
    )
    notices(
        "a plugin flag for an undeclared plugin",
        lambda c, o: setv(c["flags"][4], "plugin", "chai.nothing"),
        CHAI,
        "$.flags[4].plugin",
        "no plugin 'chai.nothing'",
    )
    notices(
        "openWhenLive with no live phase",
        lambda c, o: setv(c["phases"][3], "role", "pilot"),
        CHAI,
        "$.flags[1]",
        "needs a live phase",
    )

    print("Names and namespaces (mutation)")
    notices(
        "a definition in a directory of another name",
        lambda c, o: (setv(o, "id", "opt"), setv(o, "namespaces", ["opt"])),
        OPTICA,
        "$.id",
        "is not the directory's name 'optica'",
    )
    notices(
        "namespaces that leave out the id",
        lambda c, o: setv(c, "namespaces", ["te"]),
        CHAI,
        "$.namespaces",
        "must include the id 'chai'",
    )
    notices(
        "an export schema id of another framework",
        lambda c, o: setv(c["export"], "schemaId", "other-review/1"),
        CHAI,
        "$.export.schemaId",
        "is not chai-review/<n>",
    )
    notices(
        "chai-review/ claimed by another framework",
        lambda c, o: setv(
            o, "export", {"schemaId": "chai-review/9", "fileSuffix": "x"}
        ),
        OPTICA,
        "$.export.schemaId",
        "'chai-review/' is reserved to 'chai'",
    )
    for key in ("meta", "items", "gates", "card", "access", "id"):
        notices(
            f"a supplement named after a record's top-level key ({key})",
            lambda c, o, k=key: (setv(o, "id", k), setv(o, "namespaces", [k])),
            OPTICA,
            "$.id",
            "reserved top-level key",
        )
    found = run(lambda c, o: None)
    check("the optica key is allowed for the optica definition", not found, str(found))

    print("Views across the build (mutation)")
    notices(
        "a section view that collides with another framework's",
        lambda c, o: setv(o, "viewPrefix", "s"),
        OPTICA,
        "$.sections[0].id",
        "view id 's1' is already used by app/frameworks/chai",
    )
    notices(
        "a section view that is a gate view ('g' + gate id)",
        lambda c, o: setv(c["sections"][5], "id", "gA"),
        CHAI,
        "$.gates[0].id",
        "view id 'gA' is already used",
    )
    for view in ("setup", "report", "changelog", "card"):
        notices(
            f"a section view that is the shell's {view}",
            lambda c, o, v=view: setv(c["sections"][5], "id", v),
            CHAI,
            "$.sections[5].id",
            f"view id {view!r} is already used by the shell",
        )
    notices(
        "a section view that is a supplement's overview",
        lambda c, o: setv(c["sections"][5], "id", "optica"),
        OPTICA,
        "$.id",
        "view id 'optica' is already used",
    )

    print("Namespaces across the build (mutation)")
    notices(
        "a namespace that is a shell catalog prefix",
        lambda c, o: o["namespaces"].append("dash"),
        OPTICA,
        "$.namespaces[1]",
        "'dash' is a shell catalog prefix",
    )
    notices(
        "a shell prefix another framework owns",
        lambda c, o: o["namespaces"].append("te"),
        OPTICA,
        "$.namespaces[1]",
        "'te' is a shell catalog prefix",
    )
    notices(
        "a namespace two definitions share",
        lambda c, o: (
            c["namespaces"].append("shared"),
            o["namespaces"].append("shared"),
        ),
        OPTICA,
        "$.namespaces[1]",
        "'shared' is also a namespace of app/frameworks/chai",
    )

    print("Requires and crossRefs (mutation)")
    notices(
        "requires a framework that does not exist",
        lambda c, o: setv(o, "requires", ["chai", "nist"]),
        OPTICA,
        "$.requires[1]",
        "no framework 'nist'",
    )
    notices(
        "requires itself",
        lambda c, o: setv(o, "requires", ["chai", "optica"]),
        OPTICA,
        "$.requires[1]",
        "cannot require itself",
    )
    notices(
        "a crossRef to a framework that does not exist",
        lambda c, o: setv(
            o["sections"][0]["items"][0]["crossRefs"], "framework", "nist"
        ),
        OPTICA,
        "$.sections[0].items[0].crossRefs.framework",
        "no framework 'nist'",
    )
    alone = {OPTICA: copy.deepcopy(REAL[OPTICA])}
    lines = [line for line in ck.problems(alone, SCHEMA) if "crossRefs" in line]
    check(
        "a missing crossRef target is reported once, not once per item",
        len(lines) == 1 and "no framework 'chai'" in lines[0],
        str(lines[:3]),
    )
    notices(
        "a crossRef to a framework it does not require",
        lambda c, o: o.pop("requires"),
        OPTICA,
        "$.sections[0].items[0].crossRefs.framework",
        "'chai' is not in requires",
    )
    notices(
        "a crossRef to an item that does not exist",
        lambda c, o: setv(o["sections"][0]["items"][0]["crossRefs"], "ids", ["s1-99"]),
        OPTICA,
        "$.sections[0].items[0].crossRefs.ids[0]",
        "no item 's1-99' in 'chai'",
    )

    print("The command line")
    with tempfile.TemporaryDirectory() as tmp:
        saved = ck.FRAMEWORKS
        try:
            ck.FRAMEWORKS = Path(tmp)
            check("no definitions at all fails", ck.main([]) == 1)
            for rel, doc in REAL.items():
                folder = Path(tmp) / Path(rel).parent.name
                folder.mkdir()
                (folder / "framework.json").write_text(json.dumps(doc), "utf-8")
            check("copies of the real definitions pass", ck.main([]) == 0)
            broken = copy.deepcopy(REAL[CHAI])
            broken["gates"][0]["after"] = "s9"
            (Path(tmp) / "chai" / "framework.json").write_text(json.dumps(broken))
            check("a broken definition exits non-zero", ck.main([]) == 1)
            (Path(tmp) / "chai" / "framework.json").write_text("{not json")
            _defs, errors = ck.load(ck.definition_files(Path(tmp)))
            check("unreadable JSON is reported", bool(errors), str(errors))
            check("unreadable JSON exits non-zero", ck.main([]) == 1)
        finally:
            ck.FRAMEWORKS = saved

    print("Rules shown failing that were not before (review of PR A)")
    notices(
        "a plugin flag takes no parameters",
        lambda c, o: c["flags"].append({"plugin": "chai.modelCard", "gate": "A"}),
        CHAI,
        "$.flags[8].gate",
        "takes no parameters",
    )

    def long_views(c: dict, o: dict) -> None:
        o["viewPrefix"] = "v" * 16
        o["sections"][0]["id"] = "x" * 60

    found = run(long_views)
    check(
        "a view id longer than an id may be is not a safe id",
        any("is not a safe id" in line for line in found),
        str(found[:3]),
    )
    for name in sorted(ck.UNSAFE_NAMES):
        found = run(lambda c, o, n=name: setv(c["sections"][0], "id", n))
        check(
            f"the section id {name!r} is refused",
            any(line.startswith(f"{CHAI}: $.sections[0].id") for line in found),
            str(found[:2]),
        )
    for key in sorted(k for k in ck.DocumentKey if k != ck.DocumentKey.OPTICA):
        defs = copy.deepcopy(REAL)
        defs[OPTICA]["id"] = str(key)
        defs[OPTICA]["namespaces"] = [str(key)]
        found = ck.problems(defs, schema=SCHEMA, folders={OPTICA: str(key)})
        check(
            f"a supplement may not be called {str(key)!r}",
            any(line.startswith(f"{OPTICA}: $.id:") for line in found),
            str(found[:2]),
        )

    print("The build is what app/frameworks.json selects")
    base = {"primary": "chai", "frameworks": ["chai", "optica"]}

    def with_config(config: dict, mutate=lambda c, o: None) -> list:
        defs = copy.deepcopy(REAL)
        mutate(defs[CHAI], defs[OPTICA])
        return ck.problems(defs, schema=SCHEMA, config=config)

    check("the default config is clean", not with_config(base))
    found = with_config(base, lambda c, o: setv(o, "role", "primary"))
    check(
        "two primaries in one build",
        any("exactly one primary, found 2" in line for line in found),
        str(found[:3]),
    )
    found = with_config({"primary": "chai", "frameworks": ["optica"]})
    check(
        "no primary in the build",
        any("exactly one primary, found 0" in line for line in found),
        str(found[:3]),
    )
    found = with_config({"primary": "optica", "frameworks": ["chai", "optica"]})
    check(
        "a config naming a supplement as primary",
        any("is not the primary" in line for line in found),
        str(found[:3]),
    )
    found = with_config({"primary": "chai", "frameworks": ["chai", "nosuch"]})
    check(
        "a config naming a framework with no definition",
        any("no valid definition 'nosuch'" in line for line in found),
        str(found[:3]),
    )
    defs = copy.deepcopy(REAL)
    other = copy.deepcopy(REAL[CHAI])
    other.update(id="zz", namespaces=["zz"])
    other["export"] = {"schemaId": "zz-review/1", "fileSuffix": "zz-review"}
    other["plugins"] = []
    other["flags"] = [f for f in other["flags"] if "plugin" not in f]
    for section in other["sections"]:
        section.pop("slots", None)
    defs["app/frameworks/zz/framework.json"] = other
    found = ck.problems(defs, schema=SCHEMA, config=base)
    check(
        "a definition outside the build is checked alone, not against its views",
        not found,
        str(found[:3]),
    )
    inside = {"primary": "chai", "frameworks": ["chai", "zz"]}
    found = ck.problems(defs, schema=SCHEMA, config=inside)
    check(
        "the same definition inside the build collides with CHAI's views",
        any("already used" in line for line in found),
        str(found[:3]),
    )

    print("Export files and crossRefs")
    optica_export = {"schemaId": "optica-review/1", "fileSuffix": "chai-review"}
    found = run(lambda c, o: setv(o, "export", optica_export))
    check(
        "chai-review is CHAI's file suffix",
        any("'chai-review' is reserved to 'chai'" in line for line in found),
        str(found[:3]),
    )

    def same_suffix(c: dict, o: dict) -> None:
        o["export"] = {"schemaId": "optica-review/1", "fileSuffix": "same"}
        c["export"] = {"schemaId": "chai-review/2", "fileSuffix": "same"}

    found = run(same_suffix)
    check(
        "two frameworks in a build share a file suffix",
        any("is also the file suffix" in line for line in found),
        str(found[:3]),
    )

    def equivalent_empty(c: dict, o: dict) -> None:
        ref = o["sections"][0]["items"][0]["crossRefs"]
        ref["relation"], ref["ids"] = "equivalent", []

    found = run(equivalent_empty)
    check(
        "an equivalent crossRef that names no item",
        any("crossRef relation 'equivalent' names no item" in line for line in found),
        str(found[:3]),
    )

    # A relation and its ids must agree (#174): a partial with no criteria shows
    # in the dashboard as "not covered", and an OPTICA-only item citing one
    # contradicts itself.
    def optica_item(o: dict, num: str) -> tuple[str, dict]:
        for si, section in enumerate(o["sections"]):
            for ii, it in enumerate(section["items"]):
                if it["num"] == num:
                    return f"$.sections[{si}].items[{ii}].crossRefs.ids", it
        raise KeyError(num)

    path, it = optica_item(REAL[OPTICA], "9.1")
    check(
        "9.1 is partial with criteria in the real definition",
        it["crossRefs"]["relation"] == "partial" and it["crossRefs"]["ids"],
    )
    notices(
        "a partial crossRef that names no item (9.1 with [])",
        lambda c, o: optica_item(o, "9.1")[1]["crossRefs"].update(ids=[]),
        OPTICA,
        path,
        "crossRef relation 'partial' names no item",
    )
    path, it = optica_item(REAL[OPTICA], "2.2")
    check(
        "2.2 is OPTICA-only with no criteria in the real definition",
        it["crossRefs"]["relation"] == "optica-only" and not it["crossRefs"]["ids"],
    )
    notices(
        "an OPTICA-only crossRef that names items (2.2 with s1-2)",
        lambda c, o: optica_item(o, "2.2")[1]["crossRefs"].update(ids=["s1-2"]),
        OPTICA,
        path,
        "crossRef relation 'optica-only' names items ['s1-2']",
    )

    print("Catalog keys and the sentences a screen needs (PR B1)")

    def has(found: list, words: str) -> bool:
        return any(words in line for line in found)

    found = run(lambda c, o: c["ui"].update(noSuchSlot="stage.eyebrow"))
    check("a slot the screens do not have", has(found, "$.ui"), str(found[:2]))
    found = run(lambda c, o: c["ui"].update(sectionEyebrow="no.such.key"))
    check(
        "a slot naming a missing catalog key",
        has(found, "'no.such.key' is not a key"),
        str(found[:2]),
    )
    # Every slot a screen needs has the engine's neutral words (PR B2), so a
    # definition that names no catalog keys at all is valid.
    found = run(lambda c, o: (c.pop("ui"), o.pop("ui")))
    check("a definition with no ui slots is valid", not found, str(found[:3]))
    found = run(lambda c, o: o["statuses"][3].pop("reasonMsg"))
    check(
        "a reason field without its label key",
        has(found, "needs reasonMsg"),
        str(found[:2]),
    )
    found = run(lambda c, o: setv(c["statuses"][0], "msg", "status.nosuch"))
    check(
        "a status naming a missing catalog key",
        has(found, "'status.nosuch' is not a catalog key"),
        str(found[:2]),
    )
    found = run(lambda c, o: setv(c["phases"][0], "msg", "phase.nosuch"))
    check(
        "a phase naming a missing catalog key",
        has(found, "'phase.nosuch' is not a catalog key"),
        str(found[:2]),
    )
    found = run(lambda c, o: setv(o["whos"][0], "msg", "who.nosuch"))
    check(
        "a stakeholder naming a missing catalog key",
        has(found, "'who.nosuch' is not a catalog key"),
        str(found[:2]),
    )
    drifted = copy.deepcopy(SCHEMA)
    drifted["properties"]["ui"]["propertyNames"]["enum"].remove("legend")
    check(
        "the schema's slot list and UiSlot drifting apart",
        bool(ck.schema_drift(drifted)),
    )

    if failures:
        print(f"\n{len(failures)} failed: {', '.join(failures)}")
        return 1
    print("\nAll passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
