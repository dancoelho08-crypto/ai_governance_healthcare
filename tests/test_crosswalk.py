#!/usr/bin/env python3
"""docs/crosswalk.md and OPTICA's framework definition cannot disagree (#174, D-84).

The crosswalk page described the corrected mapping (0 equivalent, 61 partial,
16 OPTICA-only, 36 CHAI criteria cited) while the definition the dashboard and
the generated OPTICA checklist are drawn from still held the earlier pass (3
equivalent, 60 partial, 14 OPTICA-only, 35 cited). Nothing connected the two.
scripts/gen_crosswalk.py now writes the page's item table from the definition
and checks every count and correction the page states about the current mapping
against it (the page's section 7 says what cannot be, and is not). This suite:

* runs the check on the committed page and definitions, and finds nothing;
* shows the check finding the original #174 disagreement: the page against the
  definition as it was before the fix;
* breaks the definition one way at a time (one relation, one criterion id, one
  "who answers", an equivalence back, a "not yet recorded" item recorded) and
  demands the check notice, both with the table left stale and with the table
  regenerated, so a regenerated table cannot hide a broken claim;
* breaks the page one way at a time (a headline count, an id in the table, the
  never-cited list, a citation fix, a reworded claim, the markers, the "not yet
  recorded" sentence, and each countable sentence in the prose: the chapter
  splits, the gain over the previous pass, the stages the relay puts a CHAI
  criterion at, the reached/touched/absent lists and tables, the chapter counts)
  and demands the check notice, including the two chapter sentences #174's
  verifier found false, restored;
* ties the "not yet recorded" items to the open question R-69: answering it, or
  dropping it, while the items are still unrecorded is a failure;
* checks the previous pass's figures on the page against a record of that pass;
* checks the Who enum the checker reads matches the definition's own ``whos``;
* checks the pre-commit hook runs the check when the page, the definitions or
  the checker change, and that ``gen-docs`` rewrites the table.

No browser, database or Docker: nothing here can skip.

    pixi run test-crosswalk
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location(
    "gen_crosswalk", ROOT / "scripts" / "gen_crosswalk.py"
)
gen = importlib.util.module_from_spec(spec)
sys.modules["gen_crosswalk"] = gen
spec.loader.exec_module(gen)

PAGE = gen.PAGE.read_text(encoding="utf-8")
OPTICA = json.loads(gen.OPTICA.read_text(encoding="utf-8"))
CHAI = json.loads(gen.CHAI.read_text(encoding="utf-8"))
OPTICA_DOCS = gen.OPTICA_DOCS.read_text(encoding="utf-8")
REQUIREMENTS = gen.REQUIREMENTS.read_text(encoding="utf-8")
PRECOMMIT = ROOT / ".pre-commit-config.yaml"
PIXI = ROOT / "pixi.toml"
# Each item's crossRefs and who answers as the definition held them before #174
# was fixed (commit 255136b): the earlier pass the page had already corrected.
BEFORE_FIX = ROOT / "tests" / "fixtures" / "optica_crossrefs_before_174.json"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def item(defn: dict, num: str) -> dict:
    return next(i for s in defn["sections"] for i in s["items"] if i["num"] == num)


def problems(
    page: str = PAGE, optica: dict = OPTICA, requirements: str = REQUIREMENTS
) -> list[str]:
    return gen.check(page, optica, CHAI, OPTICA_DOCS, requirements)


def regenerated(optica: dict) -> str:
    """The page as `pixi run gen-crosswalk` would write it from `optica`."""
    return gen.splice(PAGE, gen.render_table(gen.load_items(optica)))


def definition_mutation(
    name: str, mutate: Callable[[dict], None], expect: str, stale_only: bool = False
) -> None:
    """Break a copy of OPTICA's definition; the check must notice, and name `expect`.

    Run twice: with the committed page (the table is now stale), and with the
    table regenerated from the broken definition. Unless `stale_only` (a change
    no sentence on the page speaks to), the regenerated run must still fail,
    on a claim, so regenerating the table cannot hide a contradiction."""
    broken = copy.deepcopy(OPTICA)
    mutate(broken)
    stale = problems(PAGE, broken)
    check(
        f"{name}: noticed with the table stale",
        any("stale" in p for p in stale),
        f"{stale}",
    )
    fresh = problems(regenerated(broken), broken)
    if stale_only:
        check(f"{name}: the regenerated table alone agrees", fresh == [], f"{fresh}")
    else:
        check(
            f"{name}: noticed with the table regenerated",
            any(expect in p for p in fresh),
            f"wanted {expect!r} in {fresh}",
        )


def page_mutation(name: str, old: str, new: str, expect: str) -> None:
    """Edit the page once; the check must notice, and name `expect`."""
    count = PAGE.count(old)
    if count != 1:
        check(f"{name}: the text is on the page once", False, f"{count}x {old!r}")
        return
    found = problems(PAGE.replace(old, new), OPTICA)
    check(name, any(expect in p for p in found), f"wanted {expect!r} in {found}")


def requirements_mutation(name: str, old: str, new: str, expect: str) -> None:
    """Edit REQUIREMENTS.md once; the check must notice, and name `expect`."""
    count = REQUIREMENTS.count(old)
    if count != 1:
        check(
            f"{name}: the text is in REQUIREMENTS.md once", False, f"{count}x {old!r}"
        )
        return
    found = problems(PAGE, OPTICA, REQUIREMENTS.replace(old, new))
    check(name, any(expect in p for p in found), f"wanted {expect!r} in {found}")


def main() -> int:
    print("The committed page agrees with the committed definitions")
    found = problems()
    check("no problems", found == [], "\n    ".join(found))
    check(
        "the table on the page is the definition's",
        gen.table_region(PAGE) == gen.render_table(gen.load_items(OPTICA)),
    )
    items = gen.load_items(OPTICA)
    rows = gen.render_table(items).count("\n") - 1
    check("the table has a row per item", rows == len(items), f"{rows}")

    print("The original #174 disagreement is found")
    before = copy.deepcopy(OPTICA)
    earlier = json.loads(BEFORE_FIX.read_text(encoding="utf-8"))["items"]
    for section in before["sections"]:
        for raw in section["items"]:
            raw.update(earlier[raw["num"]])
    old = problems(regenerated(before), before)
    for expect in (
        "headline Equivalent: the page says 0, the definition gives 3",
        "criteria cited: the page says 36, the definition gives 35",
        "items citing s3-7",
        "equivalent rows (app/frameworks/optica/docs.toml)",
    ):
        check(f"names {expect!r}", any(expect in p for p in old), f"{old}")

    print("A broken definition is noticed")
    definition_mutation(
        "one relation changed (2.2 to partial)",
        lambda d: item(d, "2.2")["crossRefs"].update(relation="partial", ids=["s1-2"]),
        "headline Partial",
    )
    definition_mutation(
        "an equivalence back (12.1)",
        lambda d: item(d, "12.1")["crossRefs"].update(relation="equivalent"),
        "headline Equivalent",
    )
    definition_mutation(
        "one id removed (s3-7 from 11.6)",
        lambda d: item(d, "11.6")["crossRefs"]["ids"].remove("s3-7"),
        "s3-7 at 11.6",
    )
    definition_mutation(
        "one id added (s1-5 at 1.1, a criterion the page says is never cited)",
        lambda d: item(d, "1.1")["crossRefs"]["ids"].append("s1-5"),
        "criteria never cited",
    )
    definition_mutation(
        "one id swapped (s4-3 to s4-1 at 7.1)",
        lambda d: item(d, "7.1")["crossRefs"].update(ids=["s4-1"]),
        "criteria of 7.1",
    )
    definition_mutation(
        "who answers changed (11.3 back to adopter)",
        lambda d: item(d, "11.3").update(who="adopter"),
        "who answers 11.3",
    )
    definition_mutation(
        "a not-yet-recorded item recorded (5.3)",
        lambda d: item(d, "5.3")["crossRefs"].update(relation="partial", ids=["s3-2"]),
        "5.3 is named as not yet recorded",
    )
    # An id the page's prose never speaks to: only the table can notice, which is
    # why the table is on the page. Regenerating it is then the reviewable change.
    definition_mutation(
        "one id swapped where no sentence looks (s3-4 to s3-1 at 4.4)",
        lambda d: item(d, "4.4")["crossRefs"].update(ids=["s3-1"]),
        "",
        stale_only=True,
    )
    # The chip shows an item's first criterion, so the order of its ids matters.
    # The page's table states it, so a reordering is caught as a stale table and
    # regenerating it is the reviewable change.
    definition_mutation(
        "an item's criteria reordered (1.6: s5-3 first, so its chip changes)",
        lambda d: item(d, "1.6")["crossRefs"]["ids"].reverse(),
        "",
        stale_only=True,
    )
    broken = copy.deepcopy(OPTICA)
    item(broken, "1.1")["crossRefs"]["framework"] = "nist"
    found = problems(regenerated(broken), broken)
    check(
        "a crossRef to a framework other than CHAI is noticed",
        any("1.1's crossRefs name framework 'nist'" in p for p in found),
        f"{found}",
    )
    broken = copy.deepcopy(OPTICA)
    broken["requires"] = []
    found = problems(regenerated(broken), broken)
    check(
        "OPTICA not requiring CHAI is noticed",
        any("does not require 'chai'" in p for p in found),
        f"{found}",
    )
    # The table has no completion-stage column, so only the prose can notice.
    broken = copy.deepcopy(OPTICA)
    item(broken, "11.3")["attrs"]["stage"] = "D"
    found = problems(PAGE, broken)
    check(
        "a completion stage changed (11.3, which produces s3-7, from E to D)",
        any("completion stages citing s3-7" in p for p in found),
        f"{found}",
    )

    print("A broken page is noticed")
    page_mutation(
        "a headline count changed",
        "| Partial          |        61 |",
        "| Partial          |        60 |",
        "headline Partial",
    )
    row = next(line for line in PAGE.splitlines() if line.startswith("| 1.1 |"))
    page_mutation(
        "an id in the table changed", row, row.replace("s1-4", "s1-5"), "stale"
    )
    page_mutation(
        "a relation in the table changed",
        next(line for line in PAGE.splitlines() if line.startswith("| 2.2 |")),
        "| 2.2 | adopter | partial | s1-2 |",
        "stale",
    )
    page_mutation(
        "the never-cited list changed",
        "**s1-5, s3-5, s4-8, s5-4, s6-5**",
        "**s1-5, s3-5, s4-8, s5-4**",
        "criteria never cited",
    )
    page_mutation(
        "a citation fix moved",
        "+s3-7 at 11.3 and 11.6",
        "+s3-7 at 11.4 and 11.6",
        "+s3-7 at 11.4",
    )
    page_mutation(
        "a chapter's criteria count changed",
        "| 11 | Monitoring plan      |  6 | s6; s3         |    5 |",
        "| 11 | Monitoring plan      |  6 | s6; s3         |    4 |",
        "criteria in chapter 11",
    )
    page_mutation(
        "the producer split changed",
        "|    29 |   38% |",
        "|    30 |   38% |",
        "items answered by developer",
    )
    page_mutation(
        "a claim reworded so the checker cannot read it",
        "36 of 41 criteria are cited somewhere",
        "Thirty-six of the criteria are cited somewhere",
        "no longer states how many CHAI criteria are cited",
    )
    page_mutation(
        "the table's markers removed",
        gen.END,
        "",
        "between exactly one pair of markers",
    )
    page_mutation(
        "a recorded item named as not yet recorded",
        "recorded there: 5.3 and 7.4 are partial",
        "recorded there: 5.3, 7.2 and 7.4 are partial",
        "7.2 is named as not yet recorded",
    )

    print("Each countable sentence in the prose is checked")
    for name, old, new, expect in (
        (
            "the false chapter 3, 4 and 5 counts restored (nine, nine and seven)",
            "They cite five, nine\nand seven distinct criteria",
            "They cite nine, nine\nand seven distinct criteria",
            "criteria chapter 3 cites",
        ),
        (
            "the false chapter 7 shape restored (six criteria, three CHAI stages)",
            "ten CHAI criteria across four CHAI stages",
            "six CHAI criteria across three CHAI stages",
            "criteria in chapter 7",
        ),
        (
            # At least: 7.4 is not yet recorded (R-69), so its criteria could add.
            "chapter 7's CHAI stages below what is recorded",
            "ten CHAI criteria across four CHAI stages",
            "ten CHAI criteria across three CHAI stages",
            "CHAI stages of chapter 7",
        ),
        (
            "chapter 7's vendor items",
            "Twelve items,\nsix answerable only by the vendor",
            "Twelve items,\nfive answerable only by the vendor",
            "vendor items in chapter 7",
        ),
        (
            "the false 'no chapter' sentence restored",
            "**Of the seven chapters the vendor answers in, only chapter 6 can be"
            " completed\nby one party.**",
            "**No chapter can be completed by one party.**",
            "no longer states which chapters one party can complete",
        ),
        (
            "the chapter one party can complete",
            "only chapter 6 can be completed",
            "only chapter 2 can be completed",
            "one party can complete",
        ),
        (
            "a two-way split (chapter 4's five-five)",
            "Chapter 4 splits five-five",
            "Chapter 4 splits six-four",
            "the split of chapter 4",
        ),
        (
            "a three-way split (chapter 11's two-two-two)",
            "chapter 11 two-two-two",
            "chapter 11 two-one-three",
            "the split of chapter 11",
        ),
        (
            "a split chapter left out (chapter 8)",
            "chapter 8 two-one and\nchapter 11",
            "and\nchapter 11",
            "chapters the vendor shares with another party",
        ),
        (
            "the count before the gain",
            "up from 35 (85.4%)",
            "up from 34 (82.9%)",
            "criteria cited before the gain",
        ),
        (
            "the items that demand the gain",
            "OPTICA 11.3 and\n11.6 demand",
            "OPTICA 11.3 and\n11.4 demand",
            "items citing s3-7",
        ),
        (
            "the stages s3-7 is produced at",
            "OPTICA\nproduces it at stages E and F",
            "OPTICA\nproduces it at stages D and F",
            "completion stages citing s3-7",
        ),
        (
            "the stage the developer is asked for s6-3",
            "OPTICA asks the developer for it at stage B",
            "OPTICA asks the developer for it at stage C",
            "the developer's items citing s6-3",
        ),
        (
            "12.1's completion stage",
            "(12.1) are written at\nstage F",
            "(12.1) are written at\nstage E",
            "the completion stage of 12.1",
        ),
        (
            "the item s4-1 leaves without an anchor",
            "so 7.5 is left with no anchor",
            "so 7.1 is left with no anchor",
            "relation of 7.1",
        ),
        (
            "the items that keep a mapping",
            "which is why 7.1, 7.2 and 6.5 keep",
            "which is why 7.1, 7.5 and 6.5 keep",
            "7.5 keeps a mapping",
        ),
        (
            "the stage table's Total Reached cell",
            "| **Total**                  | 41 |    36 |  **25** |",
            "| **Total**                  | 41 |    36 |  **26** |",
            "criteria reached in all stages",
        ),
        (
            "a stage's reached count, the row still adding up",
            "| s4 Assess                  |  8 |     7 |       5 |       0 |      3 |",
            "| s4 Assess                  |  8 |     7 |       6 |       0 |      2 |",
            "criteria reached in s4",
        ),
        (
            "the number to plan with",
            "**25 of 41, not 36 of 41,",
            "**26 of 41, not 36 of 41,",
            "criteria reached (the number to plan with)",
        ),
        (
            "the shareable list loses a criterion",
            "s3-4, s3-6, s3-7;",
            "s3-4, s3-6;",
            "criteria genuinely shareable",
        ),
        (
            "the shareable list names a criterion never cited",
            "s3-4, s3-6, s3-7;",
            "s3-4, s3-6, s3-5;",
            "criteria graded more than once",
        ),
        (
            "the criteria cited but producing nothing",
            "s2-6, s4-4 and s4-5 - because",
            "s2-6, s4-4 and s4-8 - because",
            "which criteria are cited but produce nothing",
        ),
        (
            "the criteria cited yet absent",
            "s4-5\n(installation qualification) and s2-6",
            "s4-5\n(installation qualification) and s4-8",
            "which criteria are cited yet absent",
        ),
        (
            "the criterion touched though never cited",
            "Conversely s6-5 is never cited",
            "Conversely s6-4 is never cited",
            "s6-4 cited",
        ),
        (
            "a stage's effective coverage",
            "Stage 4 is\n5/8",
            "Stage 4 is\n6/8",
            "Stage 4 reached/n",
        ),
        (
            "the weakest stage's coverage",
            "weakest is at pilot (2/6)",
            "weakest is at pilot (3/6)",
            "Stage 5 reached/n",
        ),
        (
            "a criterion's track in section 3",
            "| s6-5    | P     |",
            "| s6-5    | S     |",
            "the track of s6-5",
        ),
        (
            "the absent criteria by track",
            "three are CHAI's safety track",
            "two are CHAI's safety track",
            "absent criteria in the safety track",
        ),
        (
            "how many criteria OPTICA misses outright",
            "Seven criteria are absent outright",
            "Six criteria are absent outright",
            "criteria absent outright",
        ),
        (
            "the absent table loses a row",
            "| s5-4    | F     | Pilot results checked across patient groups    |\n",
            "",
            "criteria in section 3's absent table",
        ),
        (
            "an OPTICA total named in passing",
            "Searching all 77 OPTICA items",
            "Searching all 76 OPTICA items",
            "OPTICA items ('all 76 OPTICA items')",
        ),
        (
            "a CHAI total named in passing",
            "conditionals in the\n41 are",
            "conditionals in the\n40 are",
            "CHAI criteria ('conditionals in the 40')",
        ),
        (
            "who the adopting organization's items are assigned to",
            "the organizational data lead or the organizational AI lead",
            "the organizational data lead or the MLOps expert",
            "stakeholders of the adopting organization's items",
        ),
        (
            "the development-process questions with no anchor",
            "four of the six\ndevelopment-process questions",
            "three of the six\ndevelopment-process questions",
            "development-process questions with no anchor",
        ),
    ):
        page_mutation(name, old, new, expect)

    print("The 'not yet recorded' items are tied to the open question R-69")
    check(
        "R-69 is an open question",
        gen.requirement(REQUIREMENTS, "R-69") is not None
        and gen.is_open(gen.requirement(REQUIREMENTS, "R-69")[1])
        and gen.requirement(REQUIREMENTS, "R-69")[2] == "Open questions",
        f"{gen.requirement(REQUIREMENTS, 'R-69')}",
    )
    r69 = REQUIREMENTS[REQUIREMENTS.index("### R-69") :]
    status = r69[r69.index("- Status:") : r69.index("\n", r69.index("- Status:"))]
    requirements_mutation(
        "R-69 answered while 5.3 and 7.4 are unrecorded",
        status,
        "- Status: **Answered** (5.3 cites s3-2)",
        "R-69 is answered",
    )
    requirements_mutation(
        "R-69 removed",
        "### R-69 Which CHAI criteria",
        "### R-99 Which CHAI criteria",
        "R-69, which REQUIREMENTS.md lacks",
    )
    requirements_mutation(
        "R-69 no longer asks about 7.4",
        "do OPTICA 5.3 and 7.4 cite?",
        "does OPTICA 5.3 cite?",
        "items R-69 asks about",
    )
    page_mutation(
        "the sentence no longer cites R-69",
        "(R-69 in\nREQUIREMENTS.md, #174)",
        "(#174)",
        "not yet recorded, and the open question about them",
    )
    page_mutation(
        "the sentence cites an answered question (R-21)",
        "(R-69 in\nREQUIREMENTS.md, #174)",
        "(R-21 in\nREQUIREMENTS.md, #174)",
        "R-21 is answered",
    )

    print("The previous pass's figures match a record of that pass")
    earlier_items = {
        num: gen.replace(
            items[num],
            relation=gen.CrossRefRelation(raw["crossRefs"]["relation"]),
            ids=tuple(raw["crossRefs"]["ids"]),
        )
        for num, raw in earlier.items()
    }
    previous = {
        row[0].lower(): row[2]
        for row in gen.table_rows(gen.section_text(PAGE, "1"))
        if len(row) == 3
    }
    for rel in gen.CrossRefRelation:
        count = sum(it.relation is rel for it in earlier_items.values())
        label = gen.RELATION_LABEL[rel].lower()
        check(
            f"previous pass, {label}: {previous.get(label)}",
            previous.get(label) == str(count),
            f"the record gives {count}",
        )
    check(
        "previous pass, total items",
        previous.get("total items") == str(len(earlier_items)),
    )
    earlier_cited = {c for it in earlier_items.values() for c in it.ids}
    now_cited = {c for it in items.values() for c in it.ids}
    flat_page = gen.flat(PAGE)
    m = re.search(r"up from (\d+) \((\d+\.\d)%\)", flat_page)
    check(
        "'up from 35 (85.4%)' is the previous pass's count",
        m is not None
        and int(m.group(1)) == len(earlier_cited)
        and m.group(2) == f"{100 * len(earlier_cited) / 41:.1f}",
        f"{m and m.group(0)}; the record cites {len(earlier_cited)}",
    )
    check(
        "and the one gain is s3-7",
        now_cited - earlier_cited == {"s3-7"} and earlier_cited <= now_cited,
        f"{sorted(now_cited ^ earlier_cited)}",
    )
    m = re.search(r"The previous pass read (\d+)/(\d+) there", flat_page)
    s4 = [i["id"] for s in CHAI["sections"] if s["id"] == "s4" for i in s["items"]]
    check(
        "'the previous pass read 7/8' at Stage 4",
        m is not None
        and int(m.group(1)) == len(earlier_cited & set(s4))
        and int(m.group(2)) == len(s4),
        f"{m and m.group(0)}",
    )

    print("The checker's closed sets match the definition")
    check(
        "Who is the definition's whos",
        sorted(w["value"] for w in OPTICA["whos"]) == sorted(gen.Who),
        f"{OPTICA['whos']}",
    )
    header = next(
        row
        for row in gen.table_rows(gen.section_text(PAGE, "1"))
        if row[0] == "CHAI stage"
    )
    check(
        "Grade is the stage table's last three columns",
        [c.lower() for c in header[3:]] == list(gen.Grade),
        f"{header}",
    )
    check(
        "every relation has a page label",
        set(gen.RELATION_LABEL) == set(gen.CrossRefRelation),
    )
    check(
        "the number words parse",
        gen.number("Twenty-three") == 23 and gen.number("16") == 16,
    )
    check(
        "an item range expands",
        gen.item_nums("10.5-10.7, 11.3 and 11.4")
        == ["10.5", "10.6", "10.7", "11.3", "11.4"],
    )

    print("The check runs when it should")
    hooks = {
        h.get("id"): h
        for repo in yaml.safe_load(PRECOMMIT.read_text(encoding="utf-8"))["repos"]
        for h in repo.get("hooks", [])
    }
    hook = hooks.get("check-crosswalk", {})
    check("the check-crosswalk hook exists", bool(hook))
    check("it runs the check", hook.get("entry") == "pixi run check-crosswalk")
    pattern = re.compile(hook.get("files", "(?!)"))
    for path in (
        "docs/crosswalk.md",
        "app/frameworks/optica/framework.json",
        "app/frameworks/chai/framework.json",
        "app/frameworks/optica/docs.toml",
        "scripts/gen_crosswalk.py",
        "scripts/framework_enums.py",
        "REQUIREMENTS.md",
    ):
        check(f"runs on {path}", bool(pattern.search(path)))
    check("does not run on an unrelated file", not pattern.search("README.md"))
    tasks = tomllib.loads(PIXI.read_text(encoding="utf-8"))["tasks"]
    check(
        "check-crosswalk checks",
        tasks.get("check-crosswalk") == "python scripts/gen_crosswalk.py --check",
    )
    check(
        "gen-docs rewrites the table",
        "gen-crosswalk" in tasks.get("gen-docs", {}).get("depends-on", []),
    )

    print()
    if failures:
        print(f"{len(failures)} failed: {', '.join(failures)}")
        return 1
    print("all passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
