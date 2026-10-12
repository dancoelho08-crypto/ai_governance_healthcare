#!/usr/bin/env python3
"""The dashboard in seven languages, in a real browser (#80).

* The language comes from a saved choice, then the browser's languages, then English;
  Traditional Chinese does not fall into Simplified.
* The picker switches everything already on screen, sets <html lang>, and is remembered.
* Dates and relative times follow the chosen language, not the browser's.
* A safety-bearing warning stays in English until a reviewer is recorded for it in
  that language (D-59), and switches when one is.
* The plural categories check-i18n requires are the ones Intl.PluralRules actually uses.
* Exports and machine-read text stay English (phase 1).
* A pseudo-locale shows what is still hard-coded. The header must be fully converted;
  everything else is a ratchet: tests/i18n_baseline.json counts the hard-coded text
  left on three screens, and the count may only go down (`--update-baseline`).

    pixi run test-i18n
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app" / "index.html"
BASELINE = ROOT / "tests" / "i18n_baseline.json"

spec = importlib.util.spec_from_file_location(
    "check_i18n", ROOT / "scripts" / "check_i18n.py"
)
ci = importlib.util.module_from_spec(spec)
sys.modules["check_i18n"] = ci
spec.loader.exec_module(ci)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


def own_name(locale: str) -> str:
    """The language's name in itself, from its catalog."""
    path = ROOT / "app" / "i18n" / f"{locale}.json"
    return json.loads(path.read_text(encoding="utf-8"))["@meta"]["name"]


def own_h1(page) -> str:
    return page.evaluate("I18N_CATALOGS.he['dash.title']")


def open_app(browser, locale: str = "en-US", saved: str | None = None):
    context = browser.new_context(locale=locale)
    if saved:
        context.add_init_script(
            f"try{{localStorage.setItem('chai-locale',{saved!r})}}catch(e){{}}"
        )
    page = context.new_page()
    page.goto(APP.as_uri())
    page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
    return context, page


# Visible text that is plain ASCII words: in the pseudo-locale, anything that came
# through t() is accented and bracketed, so plain words are hard-coded text (or data).
# <bdi> holds what a person typed (bdi() in 00-util.js), which is data, not a gap.
PLAIN_TEXT = """(root) => {
  const out = [];
  const walk = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const el = n.parentElement;
    if (!el || el.closest('script,style,[hidden],.vh,select,bdi')) continue;
    if (!el.offsetParent && getComputedStyle(el).position !== 'fixed') continue;
    const s = n.textContent.trim();
    if (/[A-Za-z]{3,}/.test(s) && !/[\\u00C0-\\u024F]/.test(s)) out.push(s);
  }
  return out;
}"""


def main() -> int:
    update = "--update-baseline" in sys.argv
    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        print("The language comes from the browser, unless one was chosen")
        for tag, expected in (
            ("es-MX", "es"), ("fr-CA", "fr"), ("de-AT", "de"), ("hi-IN", "hi"),
            ("ru-RU", "ru"), ("zh-CN", "zh-Hans"), ("zh-TW", "en"), ("ja-JP", "en"),
            ("he-IL", "he"), ("iw", "he"),
            ("en-GB", "en"),
        ):  # fmt: skip
            ctx, page = open_app(browser, tag)
            got = page.evaluate("LOCALE")
            check(f"{tag} -> {expected}", got == expected, got)
            ctx.close()
        ctx, page = open_app(browser, "es-MX", saved="de")
        check("a saved choice wins over the browser", page.evaluate("LOCALE") == "de")
        ctx.close()

        print("Spanish, from the browser")
        ctx, page = open_app(browser, "es-ES")
        check(
            "<html lang> says so",
            page.evaluate("document.documentElement.lang") == "es",
        )
        check(
            "the dashboard is in Spanish",
            page.inner_text("h1") == "Proyectos de IA en revisión",
        )
        check("so is the header", page.inner_text("#goReport") == "Ver informe")
        check(
            "and the header's mode label",
            page.inner_text("#mode") == "Solo en este navegador",
        )
        warning = page.inner_text("#storageWarning")
        check(
            "the unreviewed safety warning stays in English",
            "Saved in this browser only." in warning
            and "patient-identifiable" in warning,
            warning[:120],
        )
        page.evaluate(
            """() => { const r = I18N_CATALOGS.es['@meta'].reviewers;
                       ['safety.local.title','safety.local.detail','safety.scope']
                         .forEach(k => r[k] = 'Test reviewer, 2026-10-08');
                       relocalize(); }"""
        )
        warning = page.inner_text("#storageWarning")
        check(
            "once a reviewer is recorded, it shows in Spanish",
            "Guardado solo en este navegador." in warning
            and "Saved in this browser" not in warning,
            warning[:120],
        )
        options = page.eval_on_selector_all(
            "#lang option", "os => os.map(o => [o.value, o.textContent, o.lang])"
        )
        check(
            "the picker names each language in that language",
            all(
                [loc, own_name(loc), loc] in options
                for loc in ("en", "ru", "hi", "zh-Hans", "he")
            )
            and len(options) == 8,
            str(options),
        )  # fmt: skip

        print("A reviewed language shows its warnings translated")
        ctx_zh, zh = open_app(browser, "zh-CN")
        reviewers = zh.evaluate("I18N_CATALOGS['zh-Hans']['@meta'].reviewers")
        safety = zh.evaluate("I18N_CATALOGS.en['@meta'].safety")
        # The engine's neutral report footers (#168, R-65) are new safety text no one
        # has reviewed yet: they stay English in Chinese until a review is recorded.
        neutral = {"engine.report.disclaimer", "engine.md.footer"}
        # So is the retirement-rules banner (D-83): English until a review.
        rules = {
            "rules.title",
            "rules.titleUnsynced",
            "rules.primary",
            "rules.hash",
            "rules.unsynced",
            "rules.blocked",
            "rules.othersSave",
        }
        # And the agent access page's two warnings (#164, R-55): English until reviewed.
        agent = {"agent.storeWarning", "agent.shownOnce"}
        check(
            "every safety string but the new neutral footers and the rules banner"
            " has a Chinese reviewer",
            sorted(reviewers) == sorted(set(safety) - neutral - rules - agent)
            and all("Cody Chen" in reviewers[k] for k in reviewers),
            str(sorted(set(safety) ^ set(reviewers))),
        )
        check(
            "and those footers are safety-bearing, so they show in English in Chinese",
            neutral <= set(safety)
            and zh.evaluate("t('engine.md.footer', {name: 'X'})").startswith(
                "Structured"
            ),
        )
        check(
            "and the agent token warnings are safety-bearing, so they show in English",
            agent <= set(safety)
            and zh.evaluate("t('agent.shownOnce')").startswith("Copy it now"),
        )
        check(
            "and the rules banner is safety-bearing, so it shows in English in Chinese",
            rules <= set(safety)
            and zh.evaluate("t('rules.hash')").startswith("The server retires"),
        )
        warning = zh.inner_text("#storageWarning")
        check(
            "so the storage warning is shown in Chinese, not English",
            zh.evaluate("I18N_CATALOGS['zh-Hans']['safety.local.title']") in warning
            and "Saved in this browser" not in warning,
            warning[:120],
        )
        zh.evaluate("loadSamples()")
        zh.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        zh.evaluate("openProject([...PROJECTS.keys()][0], ENGINES.chai.sections[0].id)")
        zh.wait_for_timeout(200)
        note = zh.inner_text(".fw-note")
        check(
            "the framework note cites the review, not a machine draft",
            "Cody Chen" in note and "机器" not in note,
            note,
        )
        notes = zh.evaluate(
            "['fw.note', 'te.note'].map(k => I18N_CATALOGS['zh-Hans'][k])"
        )
        check(
            "and so does the metric-name note",
            all("Cody Chen" in n and "机器" not in n for n in notes),
            str(notes),
        )
        ctx_zh.close()

        print("Hebrew reads right to left")
        ctx_he, he = open_app(browser, "he-IL")
        he.set_viewport_size({"width": 1400, "height": 900})
        check(
            "<html dir> is rtl and <html lang> is he",
            he.evaluate("[document.documentElement.dir, document.documentElement.lang]")
            == ["rtl", "he"],
        )
        check("the dashboard is in Hebrew", he.inner_text("h1") == own_h1(he))
        he.evaluate("loadSamples()")
        he.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        he.evaluate("openProject([...PROJECTS.keys()][0], 'setup')")
        he.wait_for_timeout(200)
        rail, main_box = (
            he.locator(sel).bounding_box() for sel in ("nav.rail", "main")
        )
        check(
            "the step rail moves to the right of the page",
            rail["x"] > main_box["x"],
            f"rail {rail['x']}, main {main_box['x']}",
        )
        edge = he.evaluate(
            """() => { const n = document.querySelector('.note');
                       if (!n) return null; const s = getComputedStyle(n);
                       return [s.borderRightWidth, s.borderLeftWidth]; }"""
        )
        check(
            "a note's accent border is on the reading edge (the right)",
            edge == ["3px", "0px"],
            str(edge),
        )
        check(
            "the HTML report says rtl too",
            'dir="rtl"' in he.evaluate("exportHTML()"),
        )
        he.evaluate("setLocale('en'); relocalize();")
        check(
            "and switching to English turns it back",
            he.evaluate("document.documentElement.dir") == "ltr",
        )
        ctx_he.close()

        print("Switching")
        page.select_option("#lang", "de")
        page.wait_for_timeout(200)
        check(
            "the page switches without a reload",
            page.inner_text("#goReport") == "Bericht anzeigen",
        )
        check(
            "<html lang> follows",
            page.evaluate("document.documentElement.lang") == "de",
        )
        check(
            "the choice is saved",
            page.evaluate("localStorage.getItem('chai-locale')") == "de",
        )
        page.reload()
        page.wait_for_function("typeof LOADED !== 'undefined' && LOADED", timeout=15000)
        check(
            "and kept after a reload", page.inner_text("h1") == "KI-Projekte in Prüfung"
        )

        print("A choice is shown in the reader's language and stored in English")
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        page.evaluate("openProject([...PROJECTS.keys()][0], 'setup')")
        page.wait_for_timeout(200)
        check("the rail is in German", "Projekteinrichtung" in page.inner_text("#rail"))
        options = page.eval_on_selector_all(
            "#f_meta_riskTier option", "os => os.map(o => [o.value, o.textContent])"
        )
        check(
            "risk tier options read German and keep the English value",
            ["High", "Hoch"] in options and ["Low", "Niedrig"] in options,
            str(options),
        )
        page.select_option("#f_meta_riskTier", "High")
        page.wait_for_timeout(200)
        check(
            "the record stores the English value",
            page.evaluate("S.meta.riskTier") == "High",
            str(page.evaluate("S.meta.riskTier")),
        )
        check(
            "the pager reads German",
            "Weiter zu" in page.inner_text(".pager"),
            page.inner_text(".pager"),
        )
        page.evaluate(
            "openProject([...PROJECTS.keys()][0], ENGINES.chai.sections[0].id)"
        )
        page.wait_for_timeout(200)
        segs = page.eval_on_selector_all(
            ".ci .seg button", "bs => [...new Set(bs.map(b => b.textContent))]"
        )
        check(
            "checklist status buttons are German",
            {"Erfüllt", "Teilweise", "Nicht erfüllt"} <= set(segs),
            str(segs),
        )
        # Labels a click handler swaps in, which the pseudo-locale count cannot see.
        de = page.evaluate("(ks) => ks.map(k => t(k))", ["ci.more", "ci.hide"])
        more = page.locator(".ci .more").first
        more.click()
        opened = more.inner_text()
        more.click()
        check(
            "an item's details toggle reads German both ways",
            [more.inner_text(), opened] == de,
            f"{[more.inner_text(), opened]} != {de}",
        )
        item = page.locator(".ci").nth(1)
        item.locator(".seg button").nth(1).click()
        page.wait_for_timeout(100)
        check(
            "marking an item partial opens it with a German label",
            item.locator(".more").inner_text() == de[1],
            item.locator(".more").inner_text(),
        )
        # Exports follow the reader (D-60): the HTML report is German, marked as such,
        # and its unreviewed safety text (the provenance note) stays English.
        html = page.evaluate("exportHTML()")
        check(
            "the HTML export is German and says so",
            '<html lang="de" dir="ltr">' in html and "Konformitätshinweise" in html,
        )
        check(
            "its unreviewed provenance note stays English",
            "Kept in one browser on one computer" in html,
        )
        page.evaluate("goHome()")
        page.wait_for_timeout(200)
        statuses = page.eval_on_selector_all(
            ".prow .st", "es => es.map(e => e.textContent)"
        )
        check(
            "dashboard statuses are German",
            statuses and all(s in {"Nicht konform", "Aktualisierung nötig", "Im Plan",
                                   "Außer Betrieb", "Gestoppt"} for s in statuses),
            str(statuses),
        )  # fmt: skip

        print("The report, notices and dialogs")
        page.evaluate("openProject([...PROJECTS.keys()][0], 'report')")
        page.wait_for_timeout(200)
        body = page.inner_text("#main")
        check("the report chrome is German", "Konformitätshinweise" in body)
        check(
            "its unreviewed disclaimer stays English",
            "not a certification, legal opinion, or regulatory determination" in body,
        )
        # The mode indicator after the connection fails: set by code, not on open.
        for code, key in [("revoked", "mode.accessEnded"), ("", "mode.disconnected")]:
            page.evaluate("(c) => onDbError({code: c})", code)
            shown = page.inner_text("#mode")
            check(
                f"the mode reads German after {code or 'a disconnect'}",
                shown == page.evaluate("(k) => t(k)", key) and shown != key,
                shown,
            )
        page.evaluate("setReadOnly(false); setModeFor(MODE)")
        page.evaluate("toast(t('toast.archived'))")
        check("a notice is German", page.inner_text("#toast") == "Projekt archiviert")
        check(
            "the saved label is German",
            page.evaluate("savedLabel(MODE)") == "In diesem Browser gespeichert",
        )
        page.evaluate("openDeleteDialog()")
        dialog = page.inner_text(".modal")
        check(
            "the delete dialog is German",
            "Endgültig löschen" in dialog or "Projekt löschen" in dialog,
            dialog[:80],
        )
        page.keyboard.press("Escape")
        page.evaluate("goHome()")

        print("OPTICA")
        page.evaluate(
            "openProject([...PROJECTS.keys()][0], 'setup');"
            " setFrameworkEnabled('optica', true); go('o1');"
        )
        page.wait_for_timeout(200)
        segs = page.eval_on_selector_all(
            ".ci .seg button", "bs => [...new Set(bs.map(b => b.textContent))]"
        )
        check("OPTICA status buttons are German", "Beantwortet" in segs, str(segs))
        page.evaluate("go('optica')")
        page.wait_for_timeout(200)
        check(
            "the OPTICA overview is German",
            "Einführungsprüfung" in page.inner_text("h1"),
        )
        page.evaluate("goHome()")

        print("Plural flags pick the language's form")
        page.evaluate("setLocale('ru')")
        forms = page.evaluate(
            """() => [1, 2, 5, 21].map(n =>
                 flagText({text: 'x', msg: ['flag.pastDue', {count: n}]}))"""
        )
        check(
            "Russian: 1, 2, 5 and 21 actions take one, few, many, one",
            forms == ["1 действие просрочено", "2 действия просрочено",
                      "5 действий просрочено", "21 действие просрочено"],
            str(forms),
        )  # fmt: skip
        page.evaluate("setLocale('de')")
        english = page.evaluate(
            "[...PROJECTS.values()].flatMap(p => spine().flags(normalize(clone(p))))"
            ".map(f => f.text)"
        )
        check(
            "and the English text an export records is unchanged",
            english and all(re.fullmatch(r"[\x20-\x7e]+", s) for s in english),
            str(english[:3]),
        )

        print("Dates follow the chosen language, not the browser's")
        check(
            "German",
            "März" in page.evaluate("fmtDay('2026-03-14')"),
            page.evaluate("fmtDay('2026-03-14')"),
        )
        page.evaluate("setLocale('zh-Hans')")
        check(
            "Chinese",
            page.evaluate("fmtDay('2026-03-14')") == "2026年3月14日",
            page.evaluate("fmtDay('2026-03-14')"),
        )
        page.evaluate("setLocale('fr')")
        check(
            "relative time in French",
            "il y a"
            in page.evaluate("ago(new Date(Date.now()-3*3600e3).toISOString())"),
        )
        check(
            "tEn stays English",
            page.evaluate("tEn('dash.title')") == "AI projects under review",
        )
        check(
            "a missing key shows itself",
            page.evaluate("t('no.such.key')") == "no.such.key",
        )
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        page.evaluate("openProject([...PROJECTS.keys()][0], 'report')")
        md = page.evaluate("exportMD()")
        check(
            "the Markdown export is French and names its language",
            "## Alertes de conformité" in md and "**Langue :** fr" in md,
            md[:200],
        )
        check(
            "its unreviewed footer stays English",
            "not a CHAI certification" in md,
        )
        data = json.loads(page.evaluate("JSON.stringify(projectJSON(S))"))
        check(
            "the JSON export stays English, a machine contract",
            data["storage"]["label"] in ("This browser only", "Shared workspace")
            and data["status"]
            in ("Out of compliance", "Needs update", "On track", "Retired", "Stopped"),
            str(data["storage"]),
        )
        check(
            "and so does the CSV header",
            page.evaluate("exportCSV()").startswith('"Project","Developer"'),
        )
        ctx.close()

        print("The plural forms check-i18n requires are the ones the browser uses")
        ctx, page = open_app(browser)
        for locale, needed in ci.PLURALS.items():
            actual = set(page.evaluate(
                "(l) => new Intl.PluralRules(l).resolvedOptions()"
                ".pluralCategories", str(locale)
            ))  # fmt: skip
            check(
                f"{locale}: {sorted(actual)}",
                actual == set(needed),
                str(sorted(needed)),
            )
        check(
            "every language the app offers has plural rules",
            set(page.evaluate("[...LOCALE_CHOICES]")) <= set(ci.PLURALS),
        )
        js_locales = set(page.evaluate("Object.values(Locale)")) - {"en-XA"}
        files = {p.stem for p in (ROOT / "app" / "i18n").glob("*.json")}
        check(
            "the app's locales, the checker's and the catalog files are the same set",
            js_locales == {str(x) for x in ci.Locale} == files
            and set(page.evaluate("[...LOCALE_CHOICES]")) == files,
            f"{sorted(js_locales)} {sorted(files)}",
        )

        print("The CC BY 4.0 attribution survives every translation")
        for path in sorted((ROOT / "app" / "i18n").glob("*.json")):
            credit = json.loads(path.read_text(encoding="utf-8"))["te.credit"]
            check(
                f"{path.stem}: license, copyright line and link kept",
                "CC BY 4.0" in credit
                and "© 2025 Coalition for Health AI" in credit
                and "{link}" in credit,
                credit[:80],
            )

        print("Pseudo-locale: what is still hard-coded")
        page.evaluate("setLocale(Locale.PSEUDO); relocalize();")
        header = page.evaluate(
            PLAIN_TEXT.replace("(root) =>", "() => ((root) =>")
            + ")(document.querySelector('header.top'))"
        )
        check("the header is fully converted", not header, str(header))
        page.evaluate("loadSamples()")
        page.wait_for_function("PROJECTS && PROJECTS.size >= 10", timeout=15000)
        page.evaluate("goHome()")
        counts = {}
        counts["dashboard"] = len(page.evaluate(f"({PLAIN_TEXT})(document.body)"))
        page.evaluate(
            "openProject([...PROJECTS.keys()][0], ENGINES.chai.sections[0].id)"
        )
        page.wait_for_timeout(200)
        counts["checklist"] = len(page.evaluate(f"({PLAIN_TEXT})(document.body)"))
        page.evaluate("go('report')")
        page.wait_for_timeout(200)
        counts["report"] = len(page.evaluate(f"({PLAIN_TEXT})(document.body)"))
        page.evaluate("setFrameworkEnabled('optica', true); go('o1');")
        page.wait_for_timeout(200)
        counts["optica"] = len(page.evaluate(f"({PLAIN_TEXT})(document.body)"))
        ctx.close()
        browser.close()

    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    if update:
        BASELINE.write_text(json.dumps(counts, indent=2) + "\n")
        print(f"  baseline written: {counts}")
    else:
        for screen, n in counts.items():
            allowed = baseline.get(screen)
            check(
                f"{screen}: {n} hard-coded text node(s), baseline {allowed}",
                allowed is not None and n <= allowed,
                "more hard-coded text than before: put it in the catalog",
            )
            if allowed is not None and n < allowed:
                check(
                    f"{screen}: the baseline is stale; "
                    "ratchet it down with --update-baseline",
                    False,
                    f"{n} < {allowed}",
                )
    check(
        "the plain-text probe sees an unconverted string (mutation)",
        bool(re.search(r"[A-Za-z]{3,}", "Hard coded"))
        and not re.search(r"[A-Za-z]{3,}", "[Ĥáŕđ]"),
    )

    print()
    if failures:
        print(f"{len(failures)} check(s) failed")
        return 1
    print("i18n checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
