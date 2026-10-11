#!/usr/bin/env python3
"""The Markdown report is rendered by CommonMark renderers and the HTML audited (#167).

`md_problems` (tests/test_injection.py) reads the Markdown as text. That is a list of
patterns somebody thought of, and it is not what a reader runs: a reader opens the
file in GitHub, an editor preview or a wiki, and a Markdown renderer decides what
each character means. So this renders the export, the way the HTML report is opened
in a page of its own, and audits what comes out.

Every string in a project is poisoned with the injection suite's payloads (the same
list, the same `TAINT`), for every sample, with OPTICA off and on, in every language,
and for the example custom build (a poisoned definition and poisoned records). Each
export is rendered by markdown-it-py (a CommonMark reference implementation, locked
in pixi.lock; nothing is fetched at test time) in four configurations:

  commonmark          the CommonMark preset, raw HTML refused
  commonmark + html   the same with raw HTML passed through: a viewer that does not
                      sanitize, the worst case
  gfm                 tables, strikethrough and autolinks, raw HTML refused
  gfm + html          GitHub's flavor with no sanitizer, the worst case

The audit has three parts:

  * the tokens: no `html_block`, `html_inline`, image, hard break, code or quotation
    exists, so no value became markup a renderer could pass through;
  * the HTML, parsed by Python's parser: only the expected elements (headings,
    paragraphs, lists, table parts, strong, em, a, hr), no `on*` or style attribute,
    no attribute starting with a script scheme, every link http(s) without
    credentials, no comment or declaration;
  * the same HTML loaded in a real page, audited by the injection suite's own
    `AUDIT`: nothing ran, no element carries the payloads' marker.

And the structure holds: the block tags of a poisoned export equal those of the same
project poisoned with a harmless word, so a value cannot start a heading, a list, a
quotation or a table row (or end a cell) in what a reader sees.

    pixi run test-markdown-render
"""

from __future__ import annotations

import faulthandler
import functools
import itertools
import json
import re
import shutil
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from browser_engine import launch
from markdown_it import MarkdownIt
from playwright.sync_api import sync_playwright
from test_injection import (
    APP,
    AUDIT,
    PAYLOADS,
    TAINT,
    open_app,
    wait_until,
)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_app  # noqa: E402

EXAMPLE = ROOT / "app" / "frameworks" / "example"
CONFIG = EXAMPLE / "build.json"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


BENIGN = "benign words"
# What the injection suite's payloads do not cover: a link to another scheme or a
# bare host, a backslash before a tag (#124), and an unquoted attribute value that
# ends in the backslash an escaped `>` leaves behind.
EXTRA_PAYLOADS = [
    "[a](ftp://evil.example/x) [b](//evil.example/y) <ftp://evil.example/z>",
    "\\<img src=x onerror=window.__pwned++ data-inj=1\\> \\\\<b>",
    "www.evil.example/x https://u:p@evil.example/ //evil.example mailto:a@b.example",
    "a@b.example ![i](https://t.example/p.png) [r]: https://x.example\n[r]",
]
# Not the pseudo-locale en-XA: it is a developer tool that pads text with tildes.
LANGUAGES = ["en", "de", "es", "fr", "he", "hi", "ru", "zh-Hans"]

# ---- the renderers ---------------------------------------------------------


def renderer(name: str) -> MarkdownIt:
    gfm = name.startswith("gfm")
    md = MarkdownIt(
        "gfm-like" if gfm else "commonmark", {"html": name.endswith("html")}
    )
    if gfm:
        # A bare address becomes a link; an email address would be a mailto: link,
        # which is not an http(s) link and is not what this audits.
        md.linkify.set({"fuzzy_email": False})
        # linkify-it also links a protocol-relative `//host`. GitHub does not (its
        # autolinks are http(s)://, www. and email), so the schema is removed.
        md.linkify.add("//", None)
        # Nor does it link `ftp:` or `mailto:` written out (linkify-it's own defaults).
        md.linkify.add("ftp:", None)
        md.linkify.add("mailto:", None)
    return md


CONFIGS = ["commonmark", "commonmark+html", "gfm", "gfm+html"]
RENDERERS = {name: renderer(name) for name in CONFIGS}

# ---- the audit ---------------------------------------------------------------

# What the export is made of. Code, a quotation, an image, a line break, a
# strikethrough and every active element are absent on purpose: the export never
# writes them, so one appearing means a value made it.
ALLOWED_TAGS = {
    "h1", "h2", "h3", "p", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th",
    "td", "strong", "em", "a", "hr",
}  # fmt: skip
INLINE_TAGS = {"strong", "em", "a"}
ALLOWED_TOKENS = {
    "heading_open", "heading_close", "paragraph_open", "paragraph_close",
    "bullet_list_open", "bullet_list_close", "ordered_list_open",
    "ordered_list_close", "list_item_open", "list_item_close", "table_open",
    "table_close", "thead_open", "thead_close", "tbody_open", "tbody_close",
    "tr_open", "tr_close", "th_open", "th_close", "td_open", "td_close",
    "strong_open", "strong_close", "em_open", "em_close", "link_open",
    "link_close", "hr", "text", "softbreak", "inline",
}  # fmt: skip
SCHEME = re.compile(r"^[\s\x00-\x20]*(javascript|data|vbscript):", re.I)


def token_problems(md: MarkdownIt, source: str) -> list[str]:
    """Tokens a Markdown file must never produce, whatever a value says."""
    bad: set[str] = set()

    def walk(tokens) -> None:
        for token in tokens:
            if token.type not in ALLOWED_TOKENS:
                bad.add(f"a {token.type} token")
            if token.children:
                walk(token.children)

    walk(md.parse(source))
    return sorted(bad)


class Auditor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.bad: set[str] = set()
        self.blocks: list[str] = []
        # A bare address a GFM renderer made a link of (its text is its address).
        # Not a link the app wrote: the notes parser refuses credentials (R-62).
        self.autolinked: list[str] = []
        self._credentials: str | None = None
        self._text = ""

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag not in ALLOWED_TAGS:
            self.bad.add(f"an element that is not expected: <{tag}>")
        elif tag not in INLINE_TAGS:
            self.blocks.append(tag)
        for name, value in attrs:
            value = value or ""
            if name.startswith("on"):
                self.bad.add(f"an {name} attribute")
            if name == "style":
                self.bad.add("a style attribute")
            if SCHEME.match(value):
                self.bad.add(f"an attribute starting with {value[:12]!r}")
            if tag == "a" and name == "href":
                parts = urlsplit(value)
                if parts.scheme.lower() not in ("http", "https"):
                    self.bad.add(f"a link that is not http(s): {value[:30]!r}")
                elif "@" in parts.netloc:
                    self._credentials, self._text = value, ""
            elif name not in ("href",):
                self.bad.add(f"an attribute: {tag} {name}")

    def handle_data(self, data: str) -> None:
        self._text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._credentials is not None:
            if self._text == self._credentials:
                self.autolinked.append(self._credentials)
            else:
                self.bad.add("a link with credentials")
            self._credentials = None

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        self.handle_starttag(tag, attrs)

    def handle_comment(self, data: str) -> None:
        self.bad.add("a comment")

    def handle_decl(self, decl: str) -> None:
        self.bad.add("a declaration")

    def handle_pi(self, data: str) -> None:
        self.bad.add("a processing instruction")

    def unknown_decl(self, data: str) -> None:
        self.bad.add("a CDATA section")


def html_audit(html: str) -> tuple[list[str], list[str]]:
    auditor = Auditor()
    auditor.feed(html)
    auditor.close()
    return sorted(auditor.bad), auditor.blocks


def autolinked_credentials(html: str) -> list[str]:
    auditor = Auditor()
    auditor.feed(html)
    auditor.close()
    return auditor.autolinked


# Run in a page that holds the rendered HTML in #out: the injection suite's AUDIT
# (a canary, the marker attribute, active elements, on* and script links) and the
# elements and attributes the export is allowed.
PAGE_AUDIT = """(args) => {
  const [base, audit, allowed] = args;
  const bad = eval('(' + audit + ')')(base);
  for (const el of document.querySelectorAll('#out *')) {
    if (!allowed.includes(el.tagName.toLowerCase()))
      bad.push('an element that is not expected: ' + el.tagName);
    if (el.hasAttribute('style')) bad.push('a style attribute');
  }
  return bad;
}"""


def audit_in_page(browser, htmls: list[str], bad: list[str], where: str) -> None:
    """Open every rendering in a page of its own, with no policy and no sanitizer."""
    ctx = browser.new_context()
    ctx.add_init_script("window.__pwned = 0")
    page = ctx.new_page()
    page.set_content("<!doctype html><title>x</title><div id=out></div>")
    page.evaluate(
        "(h) => { document.getElementById('out').innerHTML = h.join('<hr>'); }", htmls
    )
    page.wait_for_timeout(50)
    base = {"script": 0, "iframe": 0, "form": 0}
    # The page itself has no policy, so `eval` is available to the audit helper
    # here; the app under test is never run in this page.
    for problem in page.evaluate(PAGE_AUDIT, [base, AUDIT, sorted(ALLOWED_TAGS)]):
        bad.append(f"{where}: in a page: {problem}")
    ctx.close()


@functools.cache
def control_blocks(config: str, source: str) -> list[str]:
    return html_audit(RENDERERS[config].render(source))[1]


def audit_exports(
    browser,
    exports: dict[str, str],
    controls: dict[str, str],
    where: str,
    configs: list[str] = CONFIGS,
    in_page: bool = True,
) -> list[str]:
    """Render every export in every configuration and audit it. `controls` holds the
    same exports made with a harmless word, for the structure to be compared."""
    bad: list[str] = []
    for config in configs:
        md = RENDERERS[config]
        rendered = []
        for label, source in exports.items():
            at = f"{where} {label} [{config}]"
            for problem in token_problems(md, source):
                bad.append(f"{at}: {problem}")
            html = md.render(source)
            rendered.append(html)
            problems, blocks = html_audit(html)
            bad += [f"{at}: {p}" for p in problems]
            want = control_blocks(config, controls[label])
            if blocks != want:
                bad.append(
                    f"{at}: the structure changed ({len(blocks)} vs {len(want)})"
                )
        # Only where raw HTML passes through can a page have anything to run.
        if in_page and config.endswith("html"):
            audit_in_page(browser, rendered, bad, f"{where} [{config}]")
    return bad


# ---- making the exports --------------------------------------------------------

EXPORT = """async ([doc, locale, optica, framework, id]) => {
  setLocale(locale);
  const d = doc;
  if (framework) d.meta.framework = framework;
  await STORE.create(id, d);
  for (let i = 0; i < 100 && !PROJECTS.has(id); i++)
    await new Promise(r => setTimeout(r, 20));
  openProject(id, 'setup');
  // The export is of this project and no other (a stale one would pass for it).
  if (CUR !== id || S.meta.solution !== d.meta.solution)
    throw new Error('the project is not open: ' + CUR);
  if (optica) setFrameworkEnabled('optica', true);
  const md = exportMD();
  await STORE.remove(id);
  return md;
}"""


_ids = itertools.count()


def next_id() -> str:
    """A new id per export: reusing one lets the page keep the last project open."""
    return f"mdr{next(_ids)}"


def taint(page, doc: dict, payload: str) -> dict:
    out = page.evaluate(TAINT, [doc, payload])
    out.pop("id", None)
    return out


def hostile_refs(page, doc: dict, payload: str) -> None:
    """Evidence references (R-61): the poison in a title, address and file name."""
    ref = {
        "title": payload,
        "url": "https://e.example/?q=" + payload,
        "date": "2026-01-01",
        "at": "1",
        "file": {"name": payload, "size": 5, "sha256": "a" * 64},
    }
    items = doc.get("items") or {}
    if items:
        items[next(iter(items))]["refs"] = {"rinj000001": ref}


def exports_of(page, samples: list[dict], payload: str, plan: list) -> dict[str, str]:
    """The Markdown export of every (sample, locale, OPTICA) in the plan, every
    string in the sample replaced by the payload."""
    out: dict[str, str] = {}
    for index, locale, optica in plan:
        doc = taint(page, samples[index], payload)
        hostile_refs(page, doc, payload)
        original = samples[index].get("meta", {}).get("framework")
        out[f"sample {index} {locale} optica={optica}"] = page.evaluate(
            EXPORT, [doc, locale, optica, original, next_id()]
        )
    page.evaluate("setLocale('en')")
    return out


def plan_for(count: int) -> list:
    """Every sample in English with OPTICA off and on, and the first sample, with
    OPTICA on, in every other language."""
    plan = [(i, "en", on) for i in range(count) for on in (False, True)]
    return plan + [(0, loc, True) for loc in LANGUAGES if loc != "en"]


def open_with_samples(browser, url: str | None = None, loader: str = "loadSamples()"):
    ctx, page, errors = open_app(browser, url)
    page.evaluate(loader)
    wait_until(page, "PROJECTS && PROJECTS.size >= 2", 15)
    samples = page.evaluate("[...PROJECTS.values()].map(p => clone(p))")
    for pid in page.evaluate("[...PROJECTS.keys()]"):
        page.evaluate("(id) => STORE.remove(id)", pid)
    return ctx, page, errors, samples


def default_build(browser, payloads: list[str]) -> None:
    print("The default build: every sample, every language, poisoned")
    ctx, page, errors, samples = open_with_samples(browser)
    plan = plan_for(len(samples))
    controls = exports_of(page, samples, BENIGN, plan)
    seen = set(re.findall(r"^#{1,3} ", "\n".join(controls.values()), re.M))
    check(
        "the control exports have headings of three levels (not vacuous)",
        seen == {"# ", "## ", "### "},
        str(seen),
    )
    every: list[str] = []
    for payload in payloads:
        exports = exports_of(page, samples, payload, plan)
        bad = audit_exports(browser, exports, controls, "default")
        every += bad
        check(f"{payload[:44]!r}", not bad, "; ".join(sorted(set(bad))[:4]))
    check(
        "every payload, sample and language renders as text in every configuration",
        not every,
        str(len(every)),
    )
    check("no page errors", not errors, "; ".join(errors[:3]))
    ctx.close()


# ---- the example custom build ----------------------------------------------------


def build_example(work: Path, name: str, payload: str) -> Path:
    """The example build with every definition text replaced by the payload."""
    frameworks = work / name / "frameworks"
    shutil.copytree(EXAMPLE, frameworks / "example")
    shutil.rmtree(frameworks / "example" / "i18n")
    path = frameworks / "example" / "framework.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["name"] = payload
    doc["title"] = payload
    doc["notice"] = payload
    doc["sections"][0]["title"] = payload
    doc["sections"][0]["items"][0]["text"] = payload
    doc["categories"][0]["name"] = payload
    doc["statuses"][0]["label"] = payload
    doc["gates"][0]["title"] = payload
    doc["gates"][0]["question"] = payload
    doc["gates"][0]["options"][1]["short"] = payload
    doc["phases"][0]["label"] = payload
    path.write_text(json.dumps(doc), encoding="utf-8")
    out = work / name / "out"
    code = build_app.main(
        ["--config", str(CONFIG), "--out", str(out)], frameworks=frameworks
    )
    if code != 0:
        raise SystemExit(f"build_app exited {code}")
    return out / "index.html"


def example_build(browser, work: Path, payloads: list[str]) -> None:
    print("The example custom build: poisoned definition and records")
    base_index = build_example(work, "control", BENIGN)
    ctx, page, errors, samples = open_with_samples(
        browser, base_index.as_uri(), "spine().samples.loadAll()"
    )
    plan = [(i, "en", False) for i in range(len(samples))]
    plan += [(0, loc, False) for loc in ("es", "de")]
    controls = exports_of(page, samples, BENIGN, plan)
    check("the example's controls exist", len(controls) >= 3, str(len(controls)))
    ctx.close()
    every: list[str] = []
    for n, payload in enumerate(payloads):
        index = build_example(work, f"p{n}", payload)
        ctx, page, errors, samples = open_with_samples(
            browser, index.as_uri(), "spine().samples.loadAll()"
        )
        exports = exports_of(page, samples, payload, plan)
        bad = audit_exports(browser, exports, controls, "example")
        every += bad
        check(f"{payload[:44]!r}", not bad, "; ".join(sorted(set(bad))[:4]))
        check("no page errors", not errors, "; ".join(errors[:3]))
        ctx.close()
    check(
        "the example build's poisoned definition and records render as text",
        not every,
        str(len(every)),
    )


# ---- the audit shown failing --------------------------------------------------------


def audit_notices(label: str, html_or_md: str, want: str, config: str = "gfm+html"):
    md = RENDERERS[config]
    found = token_problems(md, html_or_md) + html_audit(md.render(html_or_md))[0]
    check(
        f"the audit notices {label}",
        any(want in f for f in found),
        str(found),
    )


def audit_units() -> None:
    print("The audit notices what it is meant to (on Markdown a renderer would run)")
    audit_notices("raw HTML", '<b onclick="x">hi</b>', "html_inline")
    audit_notices("an HTML block", "<div>\nhi\n</div>\n", "html_block")
    audit_notices("an image", "![i](https://t.example/p.png)", "image")
    audit_notices("a code span", "`x`", "code_inline")
    audit_notices("a quotation", "> x", "blockquote")
    audit_notices("a hard break", "a\\\nb", "hardbreak")
    audit_notices("strikethrough", "~~x~~", "s_open")
    problems, _ = html_audit(
        '<p onclick="1" style="x"><a href="https://u:p@e.example/">x</a>'
        '<a href="//e.example/">y</a><a data-x="javascript:1">z</a></p>'
        "<script>1</script><!-- c -->"
    )
    for want in (
        "onclick",
        "style attribute",
        "credentials",
        "not http(s)",
        "starting with",
        "<script>",
        "comment",
    ):
        check(
            f"the HTML audit notices {want}",
            any(want in p for p in problems),
            str(problems),
        )
    # Known (C-82, D-85): a GFM renderer links a bare address a person typed, with
    # its credentials, and the export does not stop it. The text of that link is
    # its address, so it is reported apart from a link with other text, which fails.
    found = html_audit(
        '<p><a href="https://u:p@e.example/">https://u:p@e.example/</a></p>'
    )
    check(
        "a bare address with credentials is a known gap, not a pass or a fail",
        not found[0]
        and autolinked_credentials(
            RENDERERS["gfm"].render("see https://u:p@e.example/ now")
        )
        == ["https://u:p@e.example/"],
    )
    check(
        "a link with credentials and other text fails",
        html_audit('<a href="https://u:p@e.example/">trusted</a>')[0]
        == ["a link with credentials"],
    )
    check(
        "a renderer that does not autolink makes no such link",
        not autolinked_credentials(
            RENDERERS["commonmark"].render("see https://u:p@e.example/ now")
        ),
    )
    # The renderer that refuses raw HTML shows it as text: only the html-enabled
    # configurations can notice it, which is why the worst case is audited.
    safe = RENDERERS["commonmark"]
    check(
        "a renderer that refuses raw HTML shows it as text",
        not token_problems(safe, "<b>x</b>"),
    )
    check(
        "so the structure of a changed heading is noticed by comparing",
        html_audit(safe.render("# a"))[1] != html_audit(safe.render("a"))[1],
    )


# Weaken the export and demand the audit notice. Each row: what is weakened, the
# payload that exploits it, and the kind of finding that must appear.
MUTATIONS = [
    (
        "escaping removed from line()",
        "line",
        '<img src=x onerror="window.__pwned++" data-inj>',
        "html_inline",
    ),
    (
        "newlines kept in line()",
        "newline",
        "\n# injected heading\n[x](javascript:1)\n| a | b |\n> quote\n- item",
        "structure changed",
    ),
    (
        "angle brackets left unescaped in line()",
        "angle",
        '<img src=x onerror="window.__pwned++" data-inj>',
        "html_inline",
    ),
    (
        "the backslash left unescaped in line() (#124)",
        "backslash",
        # `>` is escaped to `\\>`, so the tag ends where an unquoted value ends in `\\`.
        "\\<img src=x onerror=window.__pwned++ data-inj=1\\>",
        "html_inline",
    ),
    (
        "mdInlineMarkdown writes the raw text",
        "raw",
        '<img src=x onerror="window.__pwned++" data-inj>',
        "html_inline",
    ),
    (
        "safeUrl lets any link through, so mdInlineMarkdown writes it",
        "link",
        "[a](ftp://evil.example/x) [b](//evil.example/y)",
        "not http(s)",
    ),
]


def weakened_page(source: str, kind: str) -> str:
    """The built page with one escape broken, and the page's own policy dropped (it
    names the script by hash, so it would refuse an edited copy)."""
    escape = 'replace(/[\\\\`*_\\[\\]()<>|!~]/g,c=>"\\\\"+c)'
    newline = 'replace(/[\\r\\n\\u2028\\u2029]+/g," ")'
    assert escape in source and newline in source
    match kind:
        case "line":
            out = source.replace(escape, "replace(/$^/g,c=>c)", 1)
        case "newline":
            out = source.replace(newline, "replace(/$^/g,c=>c)", 1)
        case "angle":
            out = source.replace(escape, escape.replace("<>", ""), 1)
        case "backslash":
            out = source.replace(escape, escape.replace("[\\\\`", "[`"), 1)
        case "raw":
            marker = "function mdInlineMarkdown(source){"
            assert marker in source
            out = source.replace(marker, marker + "return String(source);", 1)
        case "link":
            marker = "function safeUrl(raw){"
            assert marker in source
            out = source.replace(marker, marker + "return String(raw);", 1)
        case _:
            raise ValueError(kind)
    assert out != source, kind
    return re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>', "", out, count=1)


def mutations(browser) -> None:
    print("A weakened export is rejected (mutation)")
    source = APP.read_text(encoding="utf-8")
    ctx, page, _, samples = open_with_samples(browser)
    plan = [(0, "en", False)]
    controls = exports_of(page, samples, BENIGN, plan)
    # The unweakened export passes with each of these payloads, or the mutation
    # would prove nothing.
    for _, _, payload, _ in MUTATIONS:
        exports = exports_of(page, samples, payload, plan)
        bad = audit_exports(browser, exports, controls, "intact", in_page=False)
        check(f"intact export is clean for {payload[:30]!r}", not bad, str(bad[:2]))
    ctx.close()
    caught: list[bool] = []
    with tempfile.TemporaryDirectory() as tmp:
        for label, kind, payload, want in MUTATIONS:
            copy = Path(tmp) / f"{kind}.html"
            copy.write_text(weakened_page(source, kind), encoding="utf-8")
            ctx, page, _, samples = open_with_samples(browser, copy.as_uri())
            exports = exports_of(page, samples, payload, plan)
            bad = audit_exports(browser, exports, controls, "weak")
            caught.append(any(want in b for b in bad))
            check(
                f"{label}: noticed ({want})",
                caught[-1],
                "; ".join(bad[:3]) or "nothing was noticed",
            )
            ctx.close()
    check(
        "every weakened export is rejected",
        len(caught) == len(MUTATIONS) and all(caught),
        str(caught),
    )


def main() -> int:
    faulthandler.dump_traceback_later(1500, exit=True)
    work = Path(tempfile.mkdtemp(prefix="md-render-"))
    try:
        with sync_playwright() as pw:
            browser = launch(pw)
            audit_units()
            default_build(browser, [*PAYLOADS, *EXTRA_PAYLOADS])
            example_build(browser, work, [PAYLOADS[0], PAYLOADS[14], PAYLOADS[24]])
            mutations(browser)
            browser.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("markdown render checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
