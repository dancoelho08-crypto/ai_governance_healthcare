#!/usr/bin/env python3
"""docs/crosswalk.md agrees with OPTICA's framework definition (#174, D-84).

The crosswalk page is the reviewed OPTICA-to-CHAI mapping; OPTICA's definition
(app/frameworks/optica/framework.json) is what the dashboard's "covered by CHAI"
chips and the generated OPTICA checklist are drawn from. The two disagreed for
months (#174), because nothing connected them. This script connects them:

* It writes the page's item-by-item table (between the two markers below) from
  the definition, so the per-item view on the page *is* the definition.
* With ``--check`` it also reads every count, list and named correction the
  page's prose states about the current mapping (the headline relations, the
  CHAI criteria cited and never cited, the per-stage and per-chapter tables and
  sentences, the corrections applied and rejected, the producer split, the relay
  of completion stages) and recomputes each from the definition. A numeric
  claim reworded so its pattern no longer matches is a failure too, but a few
  sentences are found by a looser search and can be reworded unnoticed; the check
  is a tripwire for the page's counts and lists, not proof that every sentence is
  true.

Items the page marks as reviewed but "not yet recorded" in the definition (its
section 7 says which, citing an open question in REQUIREMENTS.md, R-69) are read
as the page states their relation; the definition must still hold them as
OPTICA-only with no criteria, so recording them means removing them from that
sentence. The sentence is accepted only while the question it cites is Open:
once the owner answers it, the check demands the items be recorded. Counts that
depend on their unknown criteria are checked as a lower bound only.

What it does not check, because the definition cannot say: the previous pass's
figures (tests/test_crosswalk.py checks those against a record of that pass),
the coverage grades, the audit's history, and the reviewer's grading of each
CHAI criterion as reached, touched or absent, which is checked only for agreeing
with itself (the stage table, the section 3 tables and the section 6 lists) and
with what is cited.

    pixi run gen-crosswalk      # rewrite the table
    pixi run check-crosswalk    # the table is current and every checked claim holds
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from framework_enums import CrossRefRelation

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "crosswalk.md"
OPTICA = ROOT / "app" / "frameworks" / "optica" / "framework.json"
CHAI = ROOT / "app" / "frameworks" / "chai" / "framework.json"
OPTICA_DOCS = ROOT / "app" / "frameworks" / "optica" / "docs.toml"
REQUIREMENTS = ROOT / "REQUIREMENTS.md"

BEGIN = (
    "<!-- Generated from app/frameworks/optica/framework.json by"
    " scripts/gen_crosswalk.py (pixi run gen-crosswalk). Do not edit by hand. -->"
)
END = "<!-- End of the generated table. -->"
DASH = "—"


class Who(StrEnum):
    """Who can answer an OPTICA item: the values of its definition's ``whos``."""

    ADOPTER = "adopter"
    DEVELOPER = "developer"
    EITHER = "either"


class Grade(StrEnum):
    """The page's grading of a CHAI criterion by what a complete OPTICA dossier
    yields against it (section 1): a reviewer's judgment, not the definition's."""

    REACHED = "reached"
    TOUCHED = "touched"
    ABSENT = "absent"


RELATION_LABEL = {
    CrossRefRelation.EQUIVALENT: "equivalent",
    CrossRefRelation.PARTIAL: "partial",
    CrossRefRelation.OPTICA_ONLY: "OPTICA-only",
}

# A table's totals row: "Total items" or "Total".
TOTAL_ROW = re.compile(r"total(?: items)?", re.IGNORECASE)

# How the page names CHAI's tracks (the categories of CHAI's definition).
TRACK_WORDS = {
    "usefulness": "U",
    "fairness": "F",
    "safety": "S",
    "trust and accountability": "T",
    "privacy and security": "P",
}

# How the producer table on the page names each party.
PRODUCER_ROW = (
    ("vendor", Who.DEVELOPER),
    ("adopting", Who.ADOPTER),
    ("either", Who.EITHER),
)

NUMBER_WORDS = {
    word: n
    for n, word in enumerate(
        re.split(
            r"\s+",
            "zero one two three four five six seven eight nine ten eleven twelve"
            " thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty"
            " twenty-one twenty-two twenty-three",
        )
    )
}


@dataclass(frozen=True)
class Item:
    num: str
    chapter: int
    who: Who
    stakeholder: str
    stage: str
    relation: CrossRefRelation
    ids: tuple[str, ...]
    framework: str | None = None


def load_items(optica: dict) -> dict[str, Item]:
    items = {}
    for section in optica["sections"]:
        for raw in section["items"]:
            refs = raw.get("crossRefs") or {}
            items[raw["num"]] = Item(
                num=raw["num"],
                chapter=int(section["n"]),
                who=Who(raw["who"]),
                stakeholder=raw["attrs"]["stakeholder"],
                stage=raw["attrs"]["stage"],
                relation=CrossRefRelation(refs.get("relation", "optica-only")),
                ids=tuple(refs.get("ids", ())),
                framework=refs.get("framework"),
            )
    return items


def chai_stages(chai: dict) -> dict[str, list[str]]:
    """CHAI's stages ("s1") and the criteria in each, in order."""
    return {s["id"]: [i["id"] for i in s["items"]] for s in chai["sections"]}


# --- the generated table ------------------------------------------------------


def render_table(items: dict[str, Item]) -> str:
    rows = [
        "| Item | Who answers | Relation to CHAI | CHAI criteria |",
        "| ---- | ----------- | ---------------- | ------------- |",
    ]
    for it in items.values():
        ids = ", ".join(it.ids) or DASH
        rows.append(f"| {it.num} | {it.who} | {RELATION_LABEL[it.relation]} | {ids} |")
    return "\n".join(rows)


class PageError(ValueError):
    """The page has lost the markers the table is written between."""


def _bounds(page: str) -> tuple[int, int]:
    start, end = page.find(BEGIN), page.find(END)
    if start < 0 or end < start or page.count(BEGIN) != 1 or page.count(END) != 1:
        raise PageError(
            "docs/crosswalk.md must hold the generated table between exactly one"
            f" pair of markers:\n  {BEGIN}\n  {END}"
        )
    return start + len(BEGIN), end


def table_region(page: str) -> str:
    start, end = _bounds(page)
    return page[start:end].strip("\n")


def splice(page: str, table: str) -> str:
    start, end = _bounds(page)
    return page[:start] + "\n\n" + table + "\n\n" + page[end:]


# --- reading the page's claims -------------------------------------------------


def number(word: str) -> int:
    word = word.strip("*").lower()
    return int(word) if word.isdigit() else NUMBER_WORDS[word]


def item_nums(text: str) -> list[str]:
    """Item numbers in prose: "1.1, 9.3 and 12.1", "10.5-10.7"."""
    out: list[str] = []
    for m in re.finditer(r"(\d+)\.(\d+)(?:-(\d+)\.(\d+))?", text):
        if m.group(3):
            if m.group(1) != m.group(3):
                raise ValueError(f"a range across chapters: {m.group(0)}")
            first, last = int(m.group(2)), int(m.group(4))
            out += [f"{m.group(1)}.{k}" for k in range(first, last + 1)]
        else:
            out.append(f"{m.group(1)}.{m.group(2)}")
    return out


def criterion_ids(text: str) -> list[str]:
    return re.findall(r"s\d-\d", text)


def section_text(page: str, number_: str) -> str:
    """The body of "## <number_>. ..." up to the next level-two heading."""
    m = re.search(
        rf"^## {re.escape(number_)}\. .*?$(.*?)(?=^## |\Z)", page, re.M | re.S
    )
    return m.group(1) if m else ""


def table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= set("|-: "):
            continue
        rows.append([c.strip().strip("*").strip() for c in line.strip("|").split("|")])
    return rows


def flat(text: str) -> str:
    return " ".join(text.split())


def requirement(requirements: str, rid: str) -> tuple[str, str, str] | None:
    """An entry of REQUIREMENTS.md: (its title, its status, the section it is in)."""
    m = re.search(
        rf"^### {re.escape(rid)} (.+?)$(.*?)(?=^### |^## |\Z)",
        requirements,
        re.M | re.S,
    )
    if m is None:
        return None
    status = re.search(r"^- Status: (.+)$", m.group(2), re.M)
    sections = re.findall(r"^## (.+)$", requirements[: m.start()], re.M)
    return (
        m.group(1).strip(),
        status.group(1).strip() if status else "",
        sections[-1].strip() if sections else "",
    )


def reach_grades(page: str, r: Report) -> tuple[dict[Grade, set[str]], list[int]]:
    """Section 6's grading of CHAI's criteria: reached ("genuinely shareable"),
    touched (a fragment) and absent, with the counts it states checked; and the
    number of CHAI criteria it states them out of."""
    text = flat(section_text(page, "6"))
    grades: dict[Grade, set[str]] = {}
    out_of: list[int] = []
    if m := r.find(
        r"Genuinely shareable: (\d+) of CHAI's (\d+) criteria\.\*\* A complete OPTICA"
        r" dossier produces evidence a reviewer could accept against (.+?)\. In most",
        text,
        "the criteria genuinely shareable",
    ):
        listed = criterion_ids(m.group(3))
        r.expect("criteria genuinely shareable", int(m.group(1)), len(listed))
        grades[Grade.REACHED] = set(listed)
        out_of.append(int(m.group(2)))
    if m := r.find(
        r"Not shareable: (\d+) of (\d+)\.\*\* (\w+) absent \((.+?)\) and (\w+) where"
        r" OPTICA yields only a fragment \((.+?)\)\.",
        text,
        "the criteria not shareable",
    ):
        absent, touched = criterion_ids(m.group(4)), criterion_ids(m.group(6))
        r.expect("criteria absent", number(m.group(3)), len(absent))
        r.expect("criteria touched", number(m.group(5)), len(touched))
        r.expect("criteria not shareable", int(m.group(1)), len(absent) + len(touched))
        grades[Grade.ABSENT], grades[Grade.TOUCHED] = set(absent), set(touched)
        out_of.append(int(m.group(2)))
    return grades, out_of


def is_open(status: str) -> bool:
    return re.match(r"\**Open\b", status) is not None


class Report:
    def __init__(self) -> None:
        self.problems: list[str] = []

    def expect(self, what: str, claimed: object, actual: object) -> None:
        if claimed != actual:
            self.problems.append(
                f"{what}: the page says {claimed}, the definition gives {actual}"
            )

    def find(self, pattern: str, text: str, what: str) -> re.Match[str] | None:
        m = re.search(pattern, text)
        if m is None:
            self.problems.append(
                f"the page no longer states {what} in the form the checker reads"
                " (update scripts/gen_crosswalk.py with the new wording)"
            )
        return m


def check(
    page: str,
    optica: dict,
    chai: dict,
    optica_docs: str = "",
    requirements: str = "",
) -> list[str]:
    """Every problem with the page against the definitions; empty means agreed.

    `requirements` is REQUIREMENTS.md, where the open question that lets an item
    stay "not yet recorded" lives (R-69)."""
    r = Report()
    recorded = load_items(optica)
    stages = chai_stages(chai)
    criteria = [c for ids in stages.values() for c in ids]
    track = {i["id"]: i.get("category") for s in chai["sections"] for i in s["items"]}
    text = flat(page)

    # Every crossRef points at CHAI, the framework OPTICA requires: the page and
    # the checks below read every id as a CHAI criterion.
    if chai["id"] not in optica.get("requires", []):
        r.problems.append(f"OPTICA's definition does not require {chai['id']!r}")
    for it in recorded.values():
        if it.framework is not None and it.framework != chai["id"]:
            r.problems.append(
                f"{it.num}'s crossRefs name framework {it.framework!r}, not"
                f" {chai['id']!r}: the crosswalk is to CHAI"
            )

    # The generated table is the definition, byte for byte.
    try:
        if table_region(page) != render_table(recorded):
            r.problems.append(
                "the item-by-item table is stale: run `pixi run gen-crosswalk`"
            )
    except PageError as exc:
        r.problems.append(str(exc))

    # Items reviewed on the page but not yet recorded in the definition, while
    # the open question the page cites for them (R-69) stays open.
    pending: set[str] = set()
    m = re.search(
        r"not yet recorded there: (.+?) are partial on this page.*?\((R-\d+)\b",
        text,
    )
    if m:
        pending = set(item_nums(m.group(1)))
        rid = m.group(2)
        entry = requirement(requirements, rid)
        if entry is None:
            r.problems.append(
                f"the items not yet recorded cite {rid}, which REQUIREMENTS.md lacks"
            )
        else:
            title, status, section = entry
            if section != "Open questions":
                r.problems.append(
                    f"{rid} is not under REQUIREMENTS.md's Open questions"
                )
            if not is_open(status):
                r.problems.append(
                    f"{rid} is answered ({status or 'no status'}): record"
                    f" {' and '.join(sorted(pending))} in OPTICA's definition and take"
                    " them out of the 'not yet recorded' sentence"
                )
            r.expect(
                f"items {rid} asks about", sorted(pending), sorted(item_nums(title))
            )
    elif "not yet recorded" in text:
        r.problems.append(
            "the page no longer states which reviewed items are not yet recorded, and"
            " the open question about them, in the form the checker reads (update"
            " scripts/gen_crosswalk.py with the new wording)"
        )
    if m:
        for num in sorted(pending):
            it = recorded.get(num)
            if it is None:
                r.problems.append(f"{num} is named as not yet recorded, and is no item")
            elif it.relation is not CrossRefRelation.OPTICA_ONLY or it.ids:
                r.problems.append(
                    f"{num} is named as not yet recorded, but the definition records"
                    f" it ({it.relation}, {list(it.ids)}): remove it from that sentence"
                )
    items = {
        num: replace(it, relation=CrossRefRelation.PARTIAL) if num in pending else it
        for num, it in recorded.items()
    }

    total = len(items)
    relations = Counter(it.relation for it in items.values())
    cited = {c for it in items.values() for c in it.ids}
    only = {n for n, it in items.items() if it.relation is CrossRefRelation.OPTICA_ONLY}
    chapters = sorted({it.chapter for it in items.values()})
    dev = {n for n, it in items.items() if it.who is Who.DEVELOPER}

    def citing(criterion: str) -> set[str]:
        return {n for n, it in items.items() if criterion in it.ids}

    def relation_of(label: str) -> CrossRefRelation:
        return CrossRefRelation(label.lower())

    # The opening paragraph.
    if m := r.find(
        r"OPTICA checklist \((\d+) items in (\d+) chapters", text, "the item count"
    ):
        r.expect("OPTICA items", int(m.group(1)), total)
        r.expect("OPTICA chapters", int(m.group(2)), len(chapters))
    if m := r.find(
        r"CHAI assurance criteria \((\d+) criteria across (\w+) lifecycle stages",
        text,
        "the CHAI criterion count",
    ):
        r.expect("CHAI criteria", int(m.group(1)), len(criteria))
        r.expect("CHAI stages", number(m.group(2)), len(stages))

    # 1. Headline numbers: the "Corrected" column.
    seen: set[CrossRefRelation] = set()
    for row in table_rows(section_text(page, "1"))[1:]:
        if len(row) != 3:
            continue
        label, corrected = row[0], row[1].strip("*")
        if TOTAL_ROW.fullmatch(label):
            r.expect("headline total", int(corrected), total)
            continue
        if label.lower() in set(CrossRefRelation):
            rel = relation_of(label)
            seen.add(rel)
            r.expect(f"headline {label}", int(corrected), relations[rel])
    for rel in CrossRefRelation:
        if rel not in seen:
            r.problems.append(f"the headline table has no row for {rel}")
    if "**There are no equivalences left.**" in text:
        r.expect("equivalences", 0, relations[CrossRefRelation.EQUIVALENT])

    if m := r.find(
        r"(\d+) of (\d+) criteria are cited somewhere in the corrected crosswalk"
        r" \((\d+\.\d)%\)",
        text,
        "how many CHAI criteria are cited",
    ):
        r.expect("criteria cited", int(m.group(1)), len(cited))
        r.expect("criteria in all", int(m.group(2)), len(criteria))
        r.expect("share cited", m.group(3), f"{100 * len(cited) / len(criteria):.1f}")
    if m := r.find(
        r"\(\d+\.\d%\), up from (\d+) \((\d+\.\d)%\)\. The gain is (s\d-\d), which"
        r" OPTICA (.+?) demand",
        text,
        "the gain over the previous pass",
    ):
        before, gain = int(m.group(1)), m.group(3)
        # The previous pass's own figure is checked against a record of that
        # pass by tests/test_crosswalk.py; here, that one criterion is the gain.
        r.expect("criteria cited before the gain", before, len(cited - {gain}))
        r.expect(f"{gain} cited", True, gain in cited)
        r.expect(
            "share cited before the gain",
            m.group(2),
            f"{100 * before / len(criteria):.1f}",
        )
        r.expect(
            f"items citing {gain}", sorted(item_nums(m.group(4))), sorted(citing(gain))
        )
    if m := r.find(
        r"(\w+) criteria are never cited: \*\*(.+?)\*\*",
        text,
        "the criteria never cited",
    ):
        never = criterion_ids(m.group(2))
        r.expect("criteria never cited", sorted(never), sorted(set(criteria) - cited))
        r.expect("count of criteria never cited", number(m.group(1)), len(never))

    # The effective-coverage table: n and Cited per CHAI stage.
    for row in table_rows(section_text(page, "1")):
        if len(row) == 6 and re.match(r"s\d ", row[0]):
            stage = row[0].split()[0]
            ids = stages.get(stage, [])
            r.expect(f"criteria in {stage}", int(row[1]), len(ids))
            r.expect(f"criteria cited in {stage}", int(row[2]), len(cited & set(ids)))
        elif len(row) == 6 and TOTAL_ROW.fullmatch(row[0]):
            r.expect("criteria in the stage table", int(row[1]), len(criteria))
            r.expect("criteria cited in the stage table", int(row[2]), len(cited))

    # The reviewer's grading of each criterion as reached, touched or absent is
    # not in the definition. What is checked is that it agrees with itself (the
    # stage table, the section 3 tables, the section 6 lists), covers every
    # criterion once, and agrees with what is cited.
    grades, out_of = reach_grades(page, r)
    for stated in out_of:
        r.expect("CHAI criteria (section 6)", stated, len(criteria))
    reached, touched, absent = (grades.get(g, set()) for g in Grade)
    graded = set(Grade) <= grades.keys()
    if graded:
        r.expect(
            "criteria graded more than once",
            [],
            sorted((reached & touched) | (reached & absent) | (touched & absent)),
        )
        r.expect(
            "criteria not graded",
            [],
            sorted(set(criteria) - reached - touched - absent),
        )
        r.expect(
            "graded criteria that are no CHAI criterion",
            [],
            sorted((reached | touched | absent) - set(criteria)),
        )
        r.expect("criteria graded reached but not cited", [], sorted(reached - cited))
    # Per CHAI stage: (n, reached, touched, absent), as the stage table states.
    stage_grades: dict[str, tuple[int, int, int, int]] = {}
    for row in table_rows(section_text(page, "1")):
        if len(row) != 6:
            continue
        is_total = TOTAL_ROW.fullmatch(row[0]) is not None
        if not (is_total or re.match(r"s\d ", row[0])):
            continue
        n, reach, touch, gone = (int(c) for c in (row[1], row[3], row[4], row[5]))
        where = "all stages" if is_total else row[0].split()[0]
        r.expect(
            f"reached, touched and absent in {where} add to n",
            n,
            reach + touch + gone,
        )
        ids = set(criteria) if is_total else set(stages.get(where, []))
        if not is_total:
            stage_grades[where] = (n, reach, touch, gone)
        if graded:
            r.expect(f"criteria reached in {where}", reach, len(reached & ids))
            r.expect(f"criteria touched in {where}", touch, len(touched & ids))
            r.expect(f"criteria absent in {where}", gone, len(absent & ids))
    if m := r.find(
        r"\*\*(\d+) of (\d+), not (\d+) of (\d+), is the number to plan with\.\*\*",
        text,
        "the number to plan with",
    ):
        r.expect(
            "criteria reached (the number to plan with)", int(m.group(1)), len(reached)
        )
        r.expect(
            "criteria in all (the number to plan with)", int(m.group(2)), len(criteria)
        )
        r.expect(
            "criteria cited (not the number to plan with)", int(m.group(3)), len(cited)
        )
        r.expect("criteria in all (not the number)", int(m.group(4)), len(criteria))
    if m := r.find(
        r"(\w+) criteria are cited yet absent.*?: (.+?) appear in the crosswalk only",
        text,
        "the criteria cited yet absent",
    ):
        listed = criterion_ids(m.group(2))
        r.expect("criteria cited yet absent", number(m.group(1)), len(listed))
        r.expect(
            "which criteria are cited yet absent",
            sorted(listed),
            sorted(absent & cited),
        )
    if m := r.find(
        r"Conversely (s\d-\d) is never cited but is partly touched",
        text,
        "the criterion touched though never cited",
    ):
        c = m.group(1)
        r.expect(f"{c} cited", False, c in cited)
        r.expect(f"{c} touched", True, c in touched)
        r.expect("criteria touched though never cited", [c], sorted(touched - cited))
    if m := r.find(
        r"Stage (\d) is (\d+)/(\d+) and Stage (\d) is (\d+)/(\d+)\. OPTICA's strongest"
        r" alignment with CHAI is at the engineering stage, .*? its weakest is at pilot"
        r" \((\d+)/(\d+)\)",
        text,
        "the effective coverage of stages 3, 4 and 5",
    ):
        for stage, reach, n in (
            m.group(1, 2, 3),
            m.group(4, 5, 6),
            ("5", *m.group(7, 8)),
        ):
            got = stage_grades.get(f"s{stage}", (0, 0, 0, 0))
            r.expect(f"Stage {stage} reached/n", f"{reach}/{n}", f"{got[1]}/{got[0]}")
        share = {k: v[1] / v[0] for k, v in stage_grades.items() if v[0]}
        if share:
            r.expect("the stage OPTICA reaches best", "s3", max(share, key=share.get))
            r.expect("the stage OPTICA reaches worst", "s5", min(share, key=share.get))

    # Corrections applied.
    if m := r.find(
        r"(\w+) relation relabels \((.+?)\), plus (\d+\.\d+) retained as (\S+?) ",
        text,
        "the relation relabels",
    ):
        relabeled = 0
        for part in m.group(2).split("; "):
            g = re.fullmatch(r"(.+?) (?:down|up) from (\S+) to (\S+)", part)
            if g is None:
                r.problems.append(f"a relabel the checker cannot read: {part!r}")
                continue
            for num in item_nums(g.group(1)):
                relabeled += 1
                r.expect(
                    f"relation of {num}",
                    g.group(3),
                    RELATION_LABEL[items[num].relation],
                )
        r.expect("relabels", number(m.group(1)), relabeled)
        r.expect(
            f"relation of {m.group(3)}",
            m.group(4),
            RELATION_LABEL[items[m.group(3)].relation],
        )
    if m := r.find(r"(\w+) citation fixes \((.+?)\)\.", text, "the citation fixes"):
        fixes = 0
        for signed, where in re.findall(
            r"((?:[+-]s\d-\d(?: and )?)+) at ((?:\d+\.\d+(?: and )?)+)", m.group(2)
        ):
            for sign, criterion in re.findall(r"([+-])(s\d-\d)", signed):
                for num in item_nums(where):
                    fixes += 1
                    r.expect(
                        f"{sign}{criterion} at {num}",
                        sign == "+",
                        criterion in items[num].ids,
                    )
        r.expect("citation fixes", number(m.group(1)), fixes)
    if m := r.find(
        r"(\w+) producer reassignments \((.+?) from (\w+) to (\w+)\)",
        text,
        "the producer reassignments",
    ):
        moved = item_nums(m.group(2))
        r.expect("producer reassignments", number(m.group(1)), len(moved))
        for num in moved:
            r.expect(f"who answers {num}", m.group(4), items[num].who)

    # Corrections rejected, and the extensions.
    for m in re.finditer(r"(\d+\.\d+) stays partial", text):
        r.expect(
            f"relation of {m.group(1)}",
            RELATION_LABEL[CrossRefRelation.PARTIAL],
            RELATION_LABEL[items[m.group(1)].relation],
        )
    if m := r.find(
        r"(\d+\.\d+) therefore remains partial on (s\d-\d) alone",
        text,
        "7.1's one anchor",
    ):
        it = items[m.group(1)]
        r.expect(f"criteria of {it.num}", [m.group(2)], list(it.ids))
        r.expect(
            f"relation of {it.num}",
            RELATION_LABEL[CrossRefRelation.PARTIAL],
            RELATION_LABEL[it.relation],
        )
    for m in re.finditer(r"why (\d+\.\d+) does become OPTICA-only", text):
        r.expect(
            f"relation of {m.group(1)}",
            RELATION_LABEL[CrossRefRelation.OPTICA_ONLY],
            RELATION_LABEL[items[m.group(1)].relation],
        )
    for m in re.finditer(r"\*(s\d-\d) at (\d+\.\d+): rejected\.\*", text):
        r.expect(
            f"{m.group(1)} at {m.group(2)}", False, m.group(1) in items[m.group(2)].ids
        )
    if m := r.find(
        r"(s\d-\d) is carried by (.+?) only\.", text, "which items carry s3-7"
    ):
        r.expect(
            f"items citing {m.group(1)}",
            sorted(item_nums(m.group(2))),
            sorted(citing(m.group(1))),
        )
    if m := r.find(
        r"OPTICA (\d+\.\d+(?:,? (?:and )?\d+\.\d+)*) are moved from (\w+) to role-dual",
        text,
        "the role-dual extension",
    ):
        for num in item_nums(m.group(1)):
            r.expect(f"who answers {num}", Who.EITHER, items[num].who)
    if m := r.find(r"(s\d-\d) is added to (\d+\.\d+)", text, "the s2-7 extension"):
        r.expect(
            f"{m.group(1)} at {m.group(2)}", True, m.group(1) in items[m.group(2)].ids
        )
    if r.find(
        r"the producer column becomes a pure function of OPTICA's own stakeholder"
        r" assignment",
        text,
        "that who answers follows from the stakeholder",
    ):
        whos: dict[str, set[Who]] = {}
        for it in items.values():
            whos.setdefault(it.stakeholder, set()).add(it.who)
        for stakeholder, found in sorted(whos.items()):
            r.expect(f"who answers for the {stakeholder}", 1, len(found))

    # 2. Chapter by chapter.
    def chapter(ch: int) -> list[Item]:
        return [it for it in items.values() if it.chapter == ch]

    def at_least(what: str, claimed: int, recorded_: int, floor: bool) -> None:
        """A count the definition gives exactly, or, where an item it holds is not
        yet recorded (R-69), at least: their criteria could only add to it."""
        if not floor:
            r.expect(what, claimed, recorded_)
        elif claimed < recorded_:
            r.expect(f"{what} (at least)", claimed, recorded_)

    def chapter_criteria(what: str, ch: int, claimed: int) -> None:
        mine = chapter(ch)
        at_least(
            what,
            claimed,
            len({c for it in mine for c in it.ids}),
            any(it.num in pending for it in mine),
        )

    rows = [row for row in table_rows(section_text(page, "2")) if row[0].isdigit()]
    r.expect("chapters in the chapter table", [int(row[0]) for row in rows], chapters)
    for row in rows:
        if len(row) != 7:
            r.problems.append(f"a chapter row the checker cannot read: {row}")
            continue
        ch = int(row[0])
        mine = [it for it in items.values() if it.chapter == ch]
        ids = {c for it in mine for c in it.ids}
        r.expect(f"items in chapter {ch}", int(row[2]), len(mine))
        claimed_stages = set(row[3].replace(";", " ").split())
        recorded_stages = {c.split("-")[0] for c in ids}
        if any(it.num in pending for it in mine):
            r.expect(
                f"CHAI stages of chapter {ch} (at least)",
                [],
                sorted(recorded_stages - claimed_stages),
            )
        else:
            r.expect(
                f"CHAI stages of chapter {ch}",
                sorted(claimed_stages),
                sorted(recorded_stages),
            )
        chapter_criteria(f"criteria in chapter {ch}", ch, int(row[4]))
        none = sum(it.relation is CrossRefRelation.OPTICA_ONLY for it in mine)
        r.expect(f"unanchored items in chapter {ch}", int(row[5]), none)
    if m := r.find(
        r"\*\*Chapters ([\d, and]+?) are where OPTICA is effectively alone\.\*\*"
        r" (\w+) of OPTICA's (\d+) unanchored items sit in these four chapters.*?"
        r" The other (\w+) are scattered through chapters (.+?)\.",
        text,
        "where the unanchored items sit",
    ):
        alone = {int(c) for c in re.findall(r"\d+", m.group(1))}
        rest = {int(c) for c in re.findall(r"\d+", m.group(5))}
        r.expect("unanchored items", int(m.group(3)), len(only))
        r.expect(
            "unanchored items in those four chapters",
            number(m.group(2)),
            sum(items[n].chapter in alone for n in only),
        )
        r.expect(
            "the other chapters' unanchored items",
            number(m.group(4)),
            sum(items[n].chapter in rest for n in only),
        )
        r.expect(
            "chapters holding unanchored items",
            sorted(alone | rest),
            sorted({items[n].chapter for n in only}),
        )

    if m := r.find(
        r"\*\*Chapter (\d+) \([^)]*\) is the most structurally awkward\.\*\* (\w+)"
        r" items, (\w+) answerable only by the vendor and (\w+) only by the adopter,"
        r" spanning (\w+) completion stages and (\w+) CHAI criteria across (\w+) CHAI"
        r" stages\.",
        text,
        "chapter 7's shape",
    ):
        ch = int(m.group(1))
        mine = chapter(ch)
        floor = any(it.num in pending for it in mine)
        r.expect(f"items in chapter {ch}", number(m.group(2)), len(mine))
        r.expect(
            f"vendor items in chapter {ch}",
            number(m.group(3)),
            sum(it.who is Who.DEVELOPER for it in mine),
        )
        r.expect(
            f"adopter items in chapter {ch}",
            number(m.group(4)),
            sum(it.who is Who.ADOPTER for it in mine),
        )
        r.expect(
            f"completion stages of chapter {ch}",
            number(m.group(5)),
            len({it.stage for it in mine}),
        )
        chapter_criteria(f"criteria in chapter {ch}", ch, number(m.group(6)))
        at_least(
            f"CHAI stages of chapter {ch}",
            number(m.group(7)),
            len({c.split("-")[0] for it in mine for c in it.ids}),
            floor,
        )
    if m := r.find(
        r"\*\*Chapters (\d+), (\d+) and (\d+) touch CHAI widely but shallowly\.\*\*"
        r" They cite (\w+), (\w+) and (\w+) distinct criteria respectively",
        text,
        "the criteria chapters 3, 4 and 5 cite",
    ):
        for ch, count in zip(m.group(1, 2, 3), m.group(4, 5, 6), strict=True):
            chapter_criteria(f"criteria chapter {ch} cites", int(ch), number(count))

    # 3. What OPTICA asks that CHAI never does.
    alone_text = flat(section_text(page, "3").split("**What CHAI asks")[0])
    if m := r.find(r"\((\d+) items, grouped\)", alone_text, "the OPTICA-only count"):
        r.expect("OPTICA-only items listed", int(m.group(1)), len(only))
    grouped = [
        num
        for group in re.findall(r"\*[^*]+\* \(([\d., ]+)\)", alone_text)
        for num in item_nums(group)
    ]
    r.expect("OPTICA-only items in the groups", sorted(grouped), sorted(only))
    r.expect(
        "items listed twice in the groups",
        [],
        sorted(n for n, k in Counter(grouped).items() if k > 1),
    )

    # 4. The producer split.
    who_count = Counter(it.who for it in items.values())
    producer_rows = 0
    for row in table_rows(section_text(page, "4"))[1:]:
        if len(row) != 3:
            continue
        for word, who in PRODUCER_ROW:
            if word in row[0].lower():
                producer_rows += 1
                r.expect(f"items answered by {who}", int(row[1]), who_count[who])
                r.expect(
                    f"share answered by {who}",
                    row[2],
                    f"{round(100 * who_count[who] / total)}%",
                )
                break
    r.expect("rows in the producer table", len(PRODUCER_ROW), producer_rows)
    if m := r.find(
        r"all (\d+) items at completion stage (\w) are assigned to the AI solution"
        r" developer",
        text,
        "the developer's stage",
    ):
        at_stage = [it for it in items.values() if it.stage == m.group(2)]
        r.expect(f"items at stage {m.group(2)}", int(m.group(1)), len(at_stage))
        r.expect(
            f"stage {m.group(2)} items not answered by the developer",
            [],
            [it.num for it in at_stage if it.who is not Who.DEVELOPER],
        )
    if m := r.find(
        r"the (\w+) MLOps-expert items \((.+?)\)", text, "the role-dual items"
    ):
        dual = item_nums(m.group(2))
        r.expect("role-dual items", number(m.group(1)), len(dual))
        r.expect(
            "items either party answers",
            sorted(dual),
            sorted(n for n, it in items.items() if it.who is Who.EITHER),
        )
    if m := r.find(
        r"\*\*(\w+) of the (\d+) vendor items have no CHAI anchor at all\*\* \((.+?)\)",
        text,
        "the vendor items with no anchor",
    ):
        listed = item_nums(m.group(3))
        r.expect("vendor items", int(m.group(2)), len(dev))
        r.expect("vendor items with no anchor", number(m.group(1)), len(listed))
        r.expect(
            "which vendor items have no anchor", sorted(listed), sorted(dev & only)
        )
    vendor_only = sorted(c for c in cited if citing(c) <= dev)
    adopter_only = sorted(c for c in cited if not citing(c) & dev)
    if m := r.find(
        r"only through items the vendor alone can answer\*\*: (.+?)\. (\S+) are"
        r" reachable only through items on the adopting side, including the"
        r" role-dual MLOps ones, and (\w+) through both",
        text,
        "which criteria only one party can reach",
    ):
        routes = re.findall(r"(s\d-\d) \(via (.+?)\)", m.group(1))
        r.expect(
            "criteria only the vendor reaches",
            sorted(c for c, _ in routes),
            vendor_only,
        )
        for criterion, via in routes:
            r.expect(
                f"items citing {criterion}",
                sorted(item_nums(via)),
                sorted(citing(criterion)),
            )
        r.expect(
            "criteria only the adopting side reaches",
            number(m.group(2)),
            len(adopter_only),
        )
        r.expect(
            "criteria both reach",
            number(m.group(3)),
            len(cited) - len(vendor_only) - len(adopter_only),
        )

    if m := r.find(
        r"the remaining (\d+) are assigned to the (.+?), the (.+?) or the (.+?)\.",
        text,
        "who the adopting organization's items are assigned to",
    ):
        adopting = [it for it in items.values() if it.who is Who.ADOPTER]
        r.expect(
            "items the adopting organization answers", int(m.group(1)), len(adopting)
        )
        r.expect(
            "stakeholders of the adopting organization's items",
            sorted(w.lower() for w in m.group(2, 3, 4)),
            sorted({it.stakeholder.lower() for it in adopting}),
        )
    if m := r.find(
        r"(\w+) of the (\w+) development-process questions",
        text,
        "the development-process questions with no anchor",
    ):
        mine = chapter(6)
        r.expect("development-process questions", number(m.group(2)), len(mine))
        r.expect(
            "development-process questions with no anchor",
            number(m.group(1)),
            sum(it.num in only for it in mine),
        )
    if m := r.find(
        r"\*\*Of the (\w+) chapters the vendor answers in, only chapter (\d+) can be"
        r" completed by one party\.\*\* (.+?)\. The natural unit",
        text,
        "which chapters one party can complete",
    ):
        vendor_chapters = sorted(
            {it.chapter for it in items.values() if it.who is Who.DEVELOPER}
        )
        r.expect(
            "chapters the vendor answers in", number(m.group(1)), len(vendor_chapters)
        )
        r.expect(
            "chapters the vendor answers in, one party can complete",
            [int(m.group(2))],
            [ch for ch in vendor_chapters if len({it.who for it in chapter(ch)}) == 1],
        )
        order = {
            2: (Who.DEVELOPER, Who.ADOPTER),
            3: (Who.DEVELOPER, Who.EITHER, Who.ADOPTER),
        }
        split_chapters = []
        for ch_word, split in re.findall(
            r"[Cc]hapter (\d+) (?:splits )?(\w+(?:-\w+)+)", m.group(3)
        ):
            ch, parts = int(ch_word), split.split("-")
            split_chapters.append(ch)
            whos = order.get(len(parts))
            if whos is None:
                r.problems.append(f"a chapter split the checker cannot read: {split}")
                continue
            r.expect(
                f"the split of chapter {ch}",
                [number(p) for p in parts] + [0] * (3 - len(parts)),
                [sum(it.who is w for it in chapter(ch)) for w in whos]
                + [sum(it.who not in whos for it in chapter(ch))] * (3 - len(parts)),
            )
        r.expect(
            "chapters the vendor shares with another party",
            sorted(split_chapters),
            [ch for ch in vendor_chapters if len({it.who for it in chapter(ch)}) > 1],
        )

    # 5. The relay of completion stages, and the most-cited criterion.
    order = sorted({it.stage for it in items.values()})
    if m := r.find(
        r"OPTICA's (\w+) completion stages are not a lifecycle", text, "the stage count"
    ):
        r.expect("completion stages", number(m.group(1)), len(order))
    if m := r.find(
        r"relay that orders \*who answers next\* - (.+?)\. The two", text, "the relay"
    ):
        r.expect(
            "items per completion stage",
            [int(n) for n in re.findall(r"\((\d+)(?: items)?\)", m.group(1))],
            [sum(it.stage == s for it in items.values()) for s in order],
        )
    if m := r.find(
        r"most-cited criterion of all, (s\d-\d), is anchored by (\w+) OPTICA items"
        r" spread across stages (.+?)\.",
        text,
        "the most-cited criterion",
    ):
        counts = Counter(c for it in items.values() for c in it.ids)
        top = max(counts.values())
        r.expect(
            "the most-cited criterion",
            [m.group(1)],
            sorted(c for c, k in counts.items() if k == top),
        )
        r.expect(f"items citing {m.group(1)}", number(m.group(2)), counts[m.group(1)])
        r.expect(
            f"stages citing {m.group(1)}",
            sorted(re.findall(r"\b[A-G]\b", m.group(3))),
            sorted({items[n].stage for n in citing(m.group(1))}),
        )

    # 6. The verdict.
    if m := r.find(
        r"With (\w+) equivalences across (\d+) items", text, "the equivalence count"
    ):
        r.expect(
            "equivalences", number(m.group(1)), relations[CrossRefRelation.EQUIVALENT]
        )
        r.expect("items", int(m.group(2)), total)
    if m := r.find(
        r"expect to obtain (\d+) answers from the vendor, of which (\w+) correspond to"
        r" nothing CHAI ever asked for, and to write (\d+) OPTICA items",
        text,
        "what a CHAI shop must add",
    ):
        r.expect("answers from the vendor", int(m.group(1)), len(dev))
        r.expect(
            "vendor answers with no CHAI anchor", number(m.group(2)), len(dev & only)
        )
        r.expect("OPTICA items with no CHAI source", int(m.group(3)), len(only))

    # 3 and 6 again: what CHAI asks that OPTICA never does, by track.
    ask_text = section_text(page, "3").split(
        "**What CHAI asks that OPTICA never does.**"
    )
    if len(ask_text) != 2:
        r.problems.append(
            "the page no longer has the section 3 part 'What CHAI asks that OPTICA"
            " never does' in the form the checker reads"
        )
    else:
        part = ask_text[1]
        tables = re.split(r"^\| CHAI id ", part, flags=re.M)[1:]
        found: list[list[str]] = []
        for table in tables:
            ids = []
            for row in table_rows("| CHAI id " + table)[1:]:
                if len(row) == 3 and re.fullmatch(r"s\d-\d", row[0]):
                    ids.append(row[0])
                    r.expect(f"the track of {row[0]}", track.get(row[0]), row[1])
            found.append(ids)
        if len(found) == 2:
            r.expect(
                "criteria in section 3's absent table", sorted(absent), sorted(found[0])
            )
            r.expect(
                "criteria in section 3's fragment table",
                sorted(touched),
                sorted(found[1]),
            )
        else:
            r.problems.append(f"section 3 has {len(found)} CHAI tables, not two")
        flat_part = flat(part)
        if m := r.find(
            r"(\w+) criteria are absent outright and (\w+) more are touched only in"
            r" fragments",
            flat_part,
            "how many criteria OPTICA misses",
        ):
            r.expect("criteria absent outright", number(m.group(1)), len(absent))
            r.expect("criteria touched in fragments", number(m.group(2)), len(touched))
        if m := r.find(
            r"Of the (\w+) absent criteria, (\w+) are CHAI's (.+?) track, (\w+) its"
            r" (.+?) track, (\w+) its (.+?) track\. \*\*None is from the (.+?)"
            r" track and none from the (.+?) track\*\*",
            flat_part,
            "the tracks of the absent criteria",
        ):
            r.expect("absent criteria", number(m.group(1)), len(absent))
            by_track = Counter(track.get(c) for c in absent)
            for count, words in (m.group(2, 3), m.group(4, 5), m.group(6, 7)):
                letter = TRACK_WORDS.get(words)
                r.expect(
                    f"absent criteria in the {words} track",
                    number(count),
                    by_track[letter],
                )
            for words in m.group(8, 9):
                letter = TRACK_WORDS.get(words)
                r.expect(f"absent criteria in the {words} track", 0, by_track[letter])
    if m := r.find(
        r"Watch the (\w+) that are cited in the crosswalk but produce nothing"
        r" - (.+?) -",
        text,
        "the criteria cited but producing nothing",
    ):
        listed = criterion_ids(m.group(2))
        r.expect(
            "criteria cited but producing nothing", number(m.group(1)), len(listed)
        )
        r.expect(
            "which criteria are cited but produce nothing",
            sorted(listed),
            sorted(absent & cited),
        )

    # 5. Where the relay puts what CHAI puts at a stage.
    if m := r.find(
        r"CHAI places monitoring ownership at Stage (\d) \((s\d-\d)\); OPTICA produces"
        r" it at stages (\w) and (\w)\.",
        text,
        "where OPTICA produces monitoring ownership",
    ):
        c = m.group(2)
        r.expect(f"the CHAI stage of {c}", f"s{m.group(1)}", c.split("-")[0])
        r.expect(
            f"completion stages citing {c}",
            sorted(m.group(3, 4)),
            sorted({items[n].stage for n in citing(c)}),
        )
    if m := r.find(
        r"CHAI places retraining cadence and change control at Stage (\d) \((s\d-\d)\);"
        r" OPTICA asks the developer for it at stage (\w)\.",
        text,
        "where OPTICA asks the developer for change control",
    ):
        c = m.group(2)
        r.expect(f"the CHAI stage of {c}", f"s{m.group(1)}", c.split("-")[0])
        r.expect(
            f"completion stages of the developer's items citing {c}",
            [m.group(3)],
            sorted({items[n].stage for n in citing(c) & dev}),
        )
    if m := r.find(
        r"deployment success criteria \((\d+\.\d+)\) are written at stage (\w)",
        text,
        "the stage of the deployment success criteria",
    ):
        r.expect(
            f"the completion stage of {m.group(1)}", m.group(2), items[m.group(1)].stage
        )
    if m := r.find(
        r"s4-1 binds, so (\d+\.\d+) is left with no anchor at all\.",
        text,
        "the item s4-1 leaves without an anchor",
    ):
        r.expect(
            f"relation of {m.group(1)}",
            RELATION_LABEL[CrossRefRelation.OPTICA_ONLY],
            RELATION_LABEL[items[m.group(1)].relation],
        )
    if m := r.find(
        r"which is why (.+?) keep their mappings", text, "the items that keep a mapping"
    ):
        for num in item_nums(m.group(1)):
            r.expect(f"{num} keeps a mapping", True, bool(items[num].ids))

    # Whole-checklist and whole-framework totals named in passing.
    for m in re.finditer(
        r"\ball (\d+) (?:OPTICA )?items\b(?! at)|each of the (\d+) OPTICA items", text
    ):
        r.expect(f"OPTICA items ({m.group(0)!r})", int(m.group(1) or m.group(2)), total)
    for m in re.finditer(r"CHAI's (\d+) criteria|conditionals in the (\d+)\b", text):
        r.expect(
            f"CHAI criteria ({m.group(0)!r})",
            int(m.group(1) or m.group(2)),
            len(criteria),
        )

    # The generated OPTICA checklist's own words (its docs.toml).
    if "There are no *equivalent* rows" in optica_docs:
        r.expect(
            "equivalent rows (app/frameworks/optica/docs.toml)",
            0,
            Counter(it.relation for it in recorded.values())[
                CrossRefRelation.EQUIVALENT
            ],
        )
    return r.problems


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="write nothing; fail if the table is stale or any claim disagrees",
    )
    args = parser.parse_args(argv)
    page = PAGE.read_text(encoding="utf-8")
    optica = read_json(OPTICA)
    if args.check:
        problems = check(
            page,
            optica,
            read_json(CHAI),
            OPTICA_DOCS.read_text(encoding="utf-8"),
            REQUIREMENTS.read_text(encoding="utf-8"),
        )
        for problem in problems:
            print(f"docs/crosswalk.md: {problem}", file=sys.stderr)
        if problems:
            return 1
        print("docs/crosswalk.md agrees with OPTICA's definition")
        return 0
    try:
        fresh = splice(page, render_table(load_items(optica)))
    except PageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if fresh != page:
        PAGE.write_text(fresh, encoding="utf-8")
        print("wrote docs/crosswalk.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
