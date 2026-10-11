#!/usr/bin/env python3
"""Credentials in an address are removed, wherever text enters or leaves (R-70, #194).

A GitHub-flavored renderer turns a bare https://user:pass@host/ in any value into a
link, so a password typed into a field would be printed in the Markdown report and
offered as a click. The owner decided (D-88, option c) that the dashboard detects
credentials in an address and removes them, leaving the rest, and says so. This is
where each part is shown, and shown failing:

  * the pure function `stripAddressCredentials`, on a table of cases (every scheme
    and shape a renderer links, and the look-alikes that must stay), checked against
    the URL parser and against markdown-it's linkify, then mutated one rule at a time;
  * entry: every free-text field of every view, typed or pasted, stores no
    credentials, shows what it kept, tells the person, and leaves no secret in the
    record, the change history or the browser's storage;
  * import: a JSON file and a review saved by an older version;
  * the Markdown report, for a record that already holds credentials (planted past
    the entry guard, the way a server's record or an older record arrives): none in
    the Markdown, and the stored record, its fingerprint and the JSON export unchanged.

    pixi run test-address-credentials
"""

from __future__ import annotations

import faulthandler
import json
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from browser_engine import launch
from markdown_it import MarkdownIt
from playwright.sync_api import sync_playwright
from test_injection import TAINT, open_app, wait_until

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "docs" / "app" / "index.html"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}")
    if not ok:
        failures.append(name)


# A password no sentence here contains, so finding it anywhere means it leaked.
USER = "usr"
SECRET = "S3cr3tPw"
WITH = f"https://{USER}:{SECRET}@h.example/x?e=a@b.c"
CLEAN = "https://h.example/x?e=a@b.c"
TYPED = f"see {WITH} end"
TYPED_CLEAN = f"see {CLEAN} end"

# ---- the table ------------------------------------------------------------------
# (input, what remains, addresses cleaned). The first block stays as it is.
CASES: list[tuple[str, str, int]] = [
    # nothing to remove
    ("", "", 0),
    ("plain text", "plain text", 0),
    ("https://example.org/path", "https://example.org/path", 0),
    ("https://host/path?email=a@b.c", "https://host/path?email=a@b.c", 0),
    ("https://example.org/#frag@x", "https://example.org/#frag@x", 0),
    ("https://example.org?u=a@b", "https://example.org?u=a@b", 0),
    ("https://host/a@b/c", "https://host/a@b/c", 0),
    ("https://example.org/a,b@c", "https://example.org/a,b@c", 0),
    ("user:pass@host.example", "user:pass@host.example", 0),
    ("user:pass@www.host.example", "user:pass@www.host.example", 0),
    ("someone@example.org", "someone@example.org", 0),
    ("mailto:someone@example.org", "mailto:someone@example.org", 0),
    ("www.example.org/x", "www.example.org/x", 0),
    ("a@b", "a@b", 0),
    ("https://example.org:8080/x", "https://example.org:8080/x", 0),
    ("https://[::1]:8080/x", "https://[::1]:8080/x", 0),
    ("//example.org/x", "//example.org/x", 0),
    ("a//b@c", "a//b@c", 0),
    ("http://example.org//u@h", "http://example.org//u@h", 0),
    ("ftp://example.org/file", "ftp://example.org/file", 0),
    ("https://bücher.example/p", "https://bücher.example/p", 0),
    ("see (https://example.org/a) now", "see (https://example.org/a) now", 0),
    ("mail a@b.c or see https://e.org", "mail a@b.c or see https://e.org", 0),
    ("https:/example.org@x", "https:/example.org@x", 0),
    ("foo:// bar@baz", "foo:// bar@baz", 0),
    ("https://my user:pw@h", "https://my user:pw@h", 0),
    ("https://user:pass", "https://user:pass", 0),
    ("https://user", "https://user", 0),
    # a scheme, in any case, and what follows it
    ("https://user:pass@example.org/path", "https://example.org/path", 1),
    ("http://user@example.org", "http://example.org", 1),
    ("HTTPS://User:Pass@Example.org/", "HTTPS://Example.org/", 1),
    ("HtTp://u:p@h.example", "HtTp://h.example", 1),
    ("ftp://u:p@h.example/f", "ftp://h.example/f", 1),
    ("sftp://u@h.example", "sftp://h.example", 1),
    ("git+ssh://u:p@h.example/r.git", "git+ssh://h.example/r.git", 1),
    ("svn+ssh://u@h.example", "svn+ssh://h.example", 1),
    ("a.b-c://u@h", "a.b-c://h", 1),
    ("irc://u:p@h.example", "irc://h.example", 1),
    ("1http://u@h", "1http://h", 1),
    ("a" * 40 + "://u@h", "a" * 40 + "://h", 1),
    ("ab-1-2-3://u@h", "ab-1-2-3://h", 1),
    # the shapes of the credentials
    ("https://us%40er:p%3Aw@host.example/", "https://host.example/", 1),
    ("https://:@example.org", "https://example.org", 1),
    ("https://@example.org", "https://example.org", 1),
    ("https://user:@example.org", "https://example.org", 1),
    ("https://:pass@example.org", "https://example.org", 1),
    ("https://a@b@example.org/", "https://example.org/", 1),
    ("https://a:b@c:d@example.org/", "https://example.org/", 1),
    ("https://u\\_x:p@h.example/", "https://h.example/", 1),
    ("https://用户:密码@例え.jp/", "https://例え.jp/", 1),
    ("https://u:p@bücher.example/p", "https://bücher.example/p", 1),
    # ports, IPv6, query, fragment: the host and what follows it are kept
    ("https://u:p@[2001:db8::1]:8443/x", "https://[2001:db8::1]:8443/x", 1),
    ("https://u:p@example.org:8080/p?q=1#f", "https://example.org:8080/p?q=1#f", 1),
    ("https://u:p@example.org?x=a@b", "https://example.org?x=a@b", 1),
    ("https://u:p@example.org#a@b", "https://example.org#a@b", 1),
    ("https://u:p@example.org/a@b/c?d=e@f", "https://example.org/a@b/c?d=e@f", 1),
    # nothing after the @: a person typing one character at a time
    ("https://user:pass@", "https://", 1),
    ("https://user@", "https://", 1),
    # several addresses in one value
    (
        "a https://u:p@one.example b http://v@two.example/x c",
        "a https://one.example b http://two.example/x c",
        2,
    ),
    (
        "https://u:p@a.example,https://v:q@b.example",
        "https://a.example,https://b.example",
        2,
    ),
    ("https://h/?e=a@b https://u:p@h2/", "https://h/?e=a@b https://h2/", 1),
    ("https://x@https://y@h", "https://https://h", 2),
    # inside Markdown and other text
    ("[docs](https://u:p@example.org/d)", "[docs](https://example.org/d)", 1),
    (
        "[https://u:p@example.org](https://example.org)",
        "[https://example.org](https://example.org)",
        1,
    ),
    ("<https://u:p@example.org/>", "<https://example.org/>", 1),
    ("<ftp://u:p@example.org>", "<ftp://example.org>", 1),
    ("see https://u:p@example.org/x.", "see https://example.org/x.", 1),
    ("(https://u:p@example.org)", "(https://example.org)", 1),
    ("https://u:p@example.org/x,", "https://example.org/x,", 1),
    ('"https://u:p@example.org"', '"https://example.org"', 1),
    ("https://u:p@example.org!", "https://example.org!", 1),
    ('{"url": "https://u:p@e.org/x"}', '{"url": "https://e.org/x"}', 1),
    ("l1\nhttps://u:p@h.example\nl3", "l1\nhttps://h.example\nl3", 1),
    ("\thttps://u:p@h.example", "\thttps://h.example", 1),
    ("| https://u:p@h.example |", "| https://h.example |", 1),
    # a protocol-relative address, which some renderers link
    ("//u:p@example.org/x", "//example.org/x", 1),
    ("see //u@example.org", "see //example.org", 1),
    ("x //u:p@h", "x //h", 1),
]

# The same address in every position a field can hold it, to be sure no field is
# special: a value that is only the address, the address first, last, and between.
POSITIONS = [
    ("{a}", "{c}"),
    ("{a} tail", "{c} tail"),
    ("head {a}", "head {c}"),
    ("head {a} tail", "head {c} tail"),
    ("head\n{a}\ntail", "head\n{c}\ntail"),
]


def run_table(page) -> list[str]:
    got = page.evaluate(
        "(cases) => cases.map(c => { const r = stripAddressCredentials(c);"
        " return [r.text, r.removed, stripAddressCredentials(r.text).removed]; })",
        [c[0] for c in CASES],
    )
    bad = []
    for (raw, want, n), (text, removed, again) in zip(CASES, got, strict=True):
        if text != want or removed != n or again != 0:
            bad.append(f"{raw!r}: {text!r}/{removed}/{again} (want {want!r}/{n}/0)")
    return bad


# ---- what a renderer does --------------------------------------------------------


def linkify(default: bool) -> MarkdownIt:
    md = MarkdownIt("gfm-like", {"html": False})
    md.linkify.set({"fuzzy_email": False})
    if not default:
        # What GitHub links (tests/test_markdown_render.py): not ftp:, //, mailto:.
        md.linkify.add("//", None)
        md.linkify.add("ftp:", None)
        md.linkify.add("mailto:", None)
    return md


def credentialed_links(html: str) -> list[str]:
    return [
        h
        for h in re.findall(r'href="([^"]*)"', html)
        if "//" in h and "@" in urlsplit(h).netloc
    ]


def renderer_checks() -> None:
    print("A renderer links the address with its credentials, and not without")
    renderers = {"GitHub's": linkify(False), "linkify-it's own defaults": linkify(True)}
    for name, md in renderers.items():
        linked = [c for c, _, n in CASES if n and credentialed_links(md.render(c))]
        check(
            f"{name} linkify makes credentialed links from the table (not vacuous)",
            len(linked) >= 10,
            str(len(linked)),
        )
        left = [(c, w) for c, w, _ in CASES if credentialed_links(md.render(w))]
        check(
            f"{name} linkify makes no credentialed link from what remains",
            not left,
            str(left[:3]),
        )


# ---- the parser ------------------------------------------------------------------

USERS = ["", "u", "user:pass", "us%40er:p%3Aw", "a:b:c"]
HOSTS = ["example.org", "example.org:8080", "[::1]", "1.2.3.4", "xn--bcher-kva.example"]
TAILS = ["", "/", "/p/q", "/p?e=a@b", "?x=1", "#f", "/a@b"]


def parser_checks(page) -> None:
    print("The URL parser agrees: credentials removed exactly where it sees them")
    rows = []
    for scheme in ("http", "https"):
        for user in USERS:
            for host in HOSTS:
                for tail in TAILS:
                    rows.append(
                        f"{scheme}://{user}@{host}{tail}"
                        if user
                        else f"{scheme}://{host}{tail}"
                    )
    out = page.evaluate(
        """(rows) => rows.map(r => {
          let u = null; try { u = new URL(r); } catch (e) {}
          const s = stripAddressCredentials(r);
          let after = null; try { after = new URL(s.text); } catch (e) {}
          return {r, had: !!(u && (u.username || u.password)), parsed: !!u,
                  removed: s.removed, text: s.text,
                  clean: !!after && !after.username && !after.password,
                  same: !!u && !!after && u.host === after.host
                        && u.pathname === after.pathname && u.search === after.search
                        && u.hash === after.hash,
                  safe: safeUrl(s.text) !== ""};
        })""",
        rows,
    )
    bad = []
    for o in out:
        if o["had"] and not (o["removed"] and o["clean"] and o["same"] and o["safe"]):
            bad.append(o["r"])
        if not o["had"] and o["removed"]:
            # An address the parser sees no credentials in is left alone.
            bad.append("changed: " + o["r"])
    check(
        f"{len(rows)} generated addresses: whatever the URL parser sees as "
        "credentials is removed, the host, path, query and fragment kept, and the "
        "rest of each is untouched",
        len(rows) > 150 and not bad and sum(o["had"] for o in out) > 100,
        "; ".join(bad[:3]),
    )
    # safeUrl, the one place that defines what a link is, refuses what this cleans.
    refused = page.evaluate(
        """(r) => r.map(x => {
          let u = null; try { u = new URL(x); } catch (e) {}
          return [!!(u && (u.username || u.password)), safeUrl(x),
                  safeUrl(stripAddressCredentials(x).text)];
        })""",
        [c[0] for c in CASES if re.fullmatch(r"https?://\S+", c[0]) and c[2]],
    )
    seen = [r for r in refused if r[0]]
    check(
        "safeUrl refuses every address the parser gives credentials, and most of "
        "them are links once cleaned",
        len(seen) >= 8
        and all(a == "" for _, a, _ in seen)
        and sum(b != "" for _, _, b in seen) >= len(seen) - 4,
        str(seen[:3]),
    )
    ms = page.evaluate(
        "(n) => { const t = performance.now();"
        " stripAddressCredentials('a'.repeat(n) + ' ' + ':'.repeat(n) + '//'.repeat(n));"  # noqa: E501
        " return performance.now() - t; }",
        200_000,
    )
    check("a long value is cleaned in linear time", ms < 2000, f"{ms:.0f} ms")


# ---- mutations of the function --------------------------------------------------

RULE_MUTATIONS = [
    (
        "the scheme rule removed",
        'const ADDR_SCHEME = "[A-Za-z][A-Za-z0-9+.\\\\-]{0,31}";',
        'const ADDR_SCHEME = "(?!)";',
    ),
    (
        "the protocol-relative rule removed",
        "(^|[^:/\\\\w])(//)${ADDR_USERINFO}",
        "(?!)(^|[^:/\\\\w])(//)${ADDR_USERINFO}",
    ),
    (
        "the scheme matched in lower case only",
        "[A-Za-z][A-Za-z0-9+.\\\\-]{0,31}",
        "[a-z][a-z0-9+.\\\\-]{0,31}",
    ),
    (
        "the userinfo ends at the first @, not the last",
        'const ADDR_USERINFO = "[^\\\\s/?#<>]*@";',
        'const ADDR_USERINFO = "[^\\\\s/?#<>@]*@";',
    ),
    (
        "the userinfo runs past a / ? or #",
        'const ADDR_USERINFO = "[^\\\\s/?#<>]*@";',
        'const ADDR_USERINFO = "[^\\\\s<>]*@";',
    ),
    (
        "the userinfo runs past a space",
        'const ADDR_USERINFO = "[^\\\\s/?#<>]*@";',
        'const ADDR_USERINFO = "[^/?#<>]*@";',
    ),
    (
        "an @ with nothing after it is not removed",
        'const ADDR_USERINFO = "[^\\\\s/?#<>]*@";',
        'const ADDR_USERINFO = "[^\\\\s/?#<>]*@(?=[^\\\\s/?#<>])";',
    ),
    (
        "only the first address of a value",
        '"g") }),\n  Object.freeze({ rule: AddrRule.RELATIVE',
        '"") }),\n  Object.freeze({ rule: AddrRule.RELATIVE',
    ),
    (
        "the scheme not removed from the result (the whole address dropped)",
        "case AddrRule.SCHEME: return a;",
        'case AddrRule.SCHEME: return "";',
    ),
    (
        "the count not kept",
        "      removed++;\n",
        "",
    ),
    (
        "a scheme longer than 31 characters not matched",
        "{0,31}",
        "{0,3}",
    ),
]


def mutated(source: str, old: str, new: str) -> str:
    assert old in source, old
    out = source.replace(old, new, 1)
    assert out != source
    # The page's own policy names the script by hash: it would refuse an edited copy.
    return re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>', "", out, count=1)


def rule_mutations(browser, source: str, work: Path) -> None:
    print("A weakened rule is noticed by the table (mutation)")
    caught: list[bool] = []
    for n, (label, old, new) in enumerate(RULE_MUTATIONS):
        copy = work / f"rule{n}.html"
        copy.write_text(mutated(source, old, new), encoding="utf-8")
        ctx, page, _ = open_app(browser, copy.as_uri())
        bad = run_table(page)
        caught.append(bool(bad))
        check(f"{label}: noticed", bool(bad), "nothing was noticed")
        ctx.close()
    check(
        "every weakened rule is noticed",
        len(caught) == len(RULE_MUTATIONS) and all(caught),
        str(caught),
    )


# ---- the page, as a person uses it -----------------------------------------------

DEEP_FIND = """(secret) => {
  const hits = [];
  const look = (name, text) => { if (String(text).includes(secret)) hits.push(name); };
  look('the open record', JSON.stringify(S));
  look('the stored record', JSON.stringify(storedRecord(S)));
  look('the pending patch', JSON.stringify(pending));
  look('the history', JSON.stringify(LOG));
  look('the log queue', JSON.stringify(logQueue));
  for (const p of PROJECTS.values()) look('a project', JSON.stringify(p));
  for (let i = 0; i < localStorage.length; i++)
    look('browser storage', localStorage.getItem(localStorage.key(i)));
  return hits;
}"""


def open_project(page, optica: bool = True) -> str:
    page.evaluate("loadSamples()")
    wait_until(page, "PROJECTS && PROJECTS.size > 0", 15)
    pid = page.evaluate("[...PROJECTS.keys()].sort()[0]")
    page.evaluate(f"openProject({pid!r}, 'setup')")
    page.wait_for_timeout(300)
    if optica:
        page.click('[data-framework="optica"]')
        page.wait_for_timeout(400)
    return pid


FIELDS = """() => [...document.querySelectorAll(
    '#main [data-bind]:is(textarea, input[type=text])')]
  .filter(el => !el.readOnly).map(el => el.dataset.bind)"""

PASTE = """([path, value]) => {
  const el = document.querySelector('[data-bind="' + path + '"]');
  if (!el) return null;
  document.getElementById('toast').textContent = '';
  el.value = value;
  el.dispatchEvent(new Event('input', {bubbles: true}));
  const out = {stored: get(path), shown: el.value,
               toast: document.getElementById('toast').textContent};
  el.dispatchEvent(new Event('blur'));   // the edit is finished: the history is written
  return out;
}"""

DRAINED = "logQueue.length === 0 && !Object.keys(changeBuf).length"


def fields_of_every_view(page) -> dict[str, str]:
    """Every free-text field there is, as the page draws it: path -> the view."""
    found: dict[str, str] = {}
    for view in page.evaluate("activeViews().map(v => v.id)"):
        page.evaluate(f"go({view!r})")
        page.wait_for_timeout(60)
        for path in page.evaluate(FIELDS):
            found.setdefault(path, view)
    return found


def toast_text(page, key: str) -> str:
    return page.evaluate("(k) => t(k)", key)


def entry_checks(browser) -> dict[str, str]:
    print("Entry: every free-text field, pasted")
    ctx, page, errors = open_app(browser)
    open_project(page)
    fields = fields_of_every_view(page)
    areas = {p.split(".")[0] for p in fields}
    check(
        "the sweep reaches the project, the items, the checkpoints, the metrics, "
        "the card and OPTICA",
        {"meta", "items", "gates", "metrics", "card"} <= areas
        and any(p.startswith("optica.") for p in fields),
        str(sorted(areas)),
    )
    check("the sweep found many fields", len(fields) > 60, str(len(fields)))
    expected = toast_text(page, "toast.credsRemoved")
    bad: list[str] = []
    for path, view in fields.items():
        page.evaluate(f"go({view!r})")
        out = page.evaluate(PASTE, [path, TYPED])
        if out is None:
            bad.append(f"{path}: not drawn in {view}")
            continue
        if out["stored"] != TYPED_CLEAN:
            bad.append(f"{path}: stored {out['stored']!r}")
        if out["shown"] != TYPED_CLEAN:
            bad.append(f"{path}: the field shows {out['shown']!r}")
        if out["toast"] != expected:
            bad.append(f"{path}: toast {out['toast']!r}")
    check(
        f"all {len(fields)} fields store the address without its credentials, show "
        "it so, and say so",
        not bad,
        "; ".join(bad[:3]),
    )
    wait_until(page, DRAINED, 10)
    page.wait_for_timeout(900)
    leaks = page.evaluate(DEEP_FIND, SECRET)
    check(
        "the password is nowhere: not the record, the history, the queue or storage",
        not leaks,
        str(leaks),
    )
    leaks = page.evaluate(DEEP_FIND, f"{USER}:")
    check("nor the user name with it", not leaks, str(leaks))
    history = page.evaluate("LOG.map(e => e.text)")
    check(
        "the history records the edits, with the address as kept",
        any(CLEAN in h for h in history),
        str(history[:2]),
    )
    check("no page errors", not errors, "; ".join(errors[:3]))
    ctx.close()
    return fields


def typing_checks(browser) -> None:
    print("Entry: typed one character at a time")
    ctx, page, _ = open_app(browser)
    open_project(page, optica=False)
    page.evaluate("go('setup')")
    page.wait_for_timeout(100)
    sel = '[data-bind="meta.org"]'
    page.fill(sel, "")
    page.click(sel)
    page.keyboard.type(TYPED, delay=2)
    shown = page.input_value(sel)
    caret = page.evaluate(f"document.querySelector('{sel}').selectionStart")
    check(
        "the field ends as the address without credentials", shown == TYPED_CLEAN, shown
    )
    check(
        "the caret stays after the host, where the person is typing",
        caret == len(TYPED_CLEAN) or caret == len(shown),
        f"{caret} of {len(shown)}",
    )
    check("the stored value is the same", page.evaluate("S.meta.org") == TYPED_CLEAN)
    page.keyboard.type(" and more")
    check(
        "typing goes on after it",
        page.input_value(sel) == TYPED_CLEAN + " and more",
        page.input_value(sel),
    )
    page.click(
        '[data-bind="meta.developer"]'
    )  # leave the field: the history is written
    wait_until(page, DRAINED, 10)
    page.wait_for_timeout(900)
    check(
        "no password in the history or storage",
        not page.evaluate(DEEP_FIND, SECRET),
        str(page.evaluate(DEEP_FIND, SECRET)),
    )
    ctx.close()


def other_entry_checks(browser) -> None:
    print("Entry: the references, a new project and a hold reason")
    ctx, page, _ = open_app(browser)
    open_project(page, optica=False)
    item = page.evaluate("ENGINES.chai.items[0].id")
    page.evaluate("go('s1')")
    page.evaluate(f"openItems.add({item!r}); renderMain(false)")
    box = f'[data-refs="items.{item}"]'
    page.fill(f"{box} [data-refin=title]", TYPED)
    page.fill(f"{box} [data-refin=url]", "https://example.org/report")
    page.click(f"{box} [data-addref]")
    wait_until(page, f"refList(S.items['{item}']).length === 1")
    title = page.evaluate(f"refList(S.items['{item}'])[0].title")
    check("a reference's title loses the credentials", title == TYPED_CLEAN, title)
    check(
        "and the person is told",
        page.inner_text("#toast") == toast_text(page, "toast.credsRemoved"),
        page.inner_text("#toast"),
    )
    page.fill(f"{box} [data-refin=url]", WITH.replace("/x?e=a@b.c", "/"))
    page.click(f"{box} [data-addref]")
    page.wait_for_timeout(100)
    check(
        "a reference's own address with credentials is refused, not stored (R-61)",
        page.inner_text("#toast") == toast_text(page, "refs.badUrl")
        and page.evaluate(f"refList(S.items['{item}']).length") == 1,
        page.inner_text("#toast"),
    )
    wait_until(page, DRAINED, 10)
    check("no password anywhere", not page.evaluate(DEEP_FIND, SECRET))

    # A new project's name.
    page.evaluate("goHome()")
    page.wait_for_timeout(200)
    page.click('[data-act="new"]')
    page.fill("#newname", f"Name {WITH}")
    page.click("#newform button[type=submit], #newform [type=submit]")
    wait_until(
        page,
        "[...PROJECTS.values()].some(p => p.meta.solution.startsWith('Name '))",
        10,
    )
    name = page.evaluate(
        "[...PROJECTS.values()].find(p => p.meta.solution.startsWith('Name ')).meta.solution"  # noqa: E501
    )
    check("a new project's name loses the credentials", name == f"Name {CLEAN}", name)
    check("no password anywhere", not page.evaluate(DEEP_FIND, SECRET))

    # A litigation-hold reason: written to the server only, so the store is given
    # a place to receive it (the way tests/test_injection.py does).
    pid = page.evaluate("[...PROJECTS.keys()].sort()[0]")
    page.evaluate(f"openProject({pid!r}, 'setup')")
    page.wait_for_timeout(300)
    page.evaluate(
        """async () => {
            ME.id = 'owner@hospital.example';
            S.access = {owners: [ME.id], writers: [], readers: []};
            window.__held = null;
            STORE.getHold = async () => ({held: false, history: []});
            STORE.setHold = async (id, action, reason) => { window.__held = reason; };
            go('setup');
            await fillHold();
            openHoldDialog('place');
        }"""
    )
    page.fill("#holdReason", f"because {WITH}")
    page.click("[data-hold-go]")
    wait_until(page, "window.__held !== null", 5)
    held = page.evaluate("window.__held")
    check(
        "a hold reason is sent without the credentials",
        held == f"because {CLEAN}",
        held,
    )
    ctx.close()


def planted_doc(page, payload: str) -> dict:
    sample = page.evaluate("clone([...PROJECTS.values()][0])")
    doc = page.evaluate(TAINT, [sample, payload])
    doc.pop("id", None)
    return doc


def history_checks(browser) -> None:
    print("The history never copies a credential an older record holds")
    ctx, page, _ = open_app(browser)
    page.evaluate("loadSamples()")
    wait_until(page, "PROJECTS && PROJECTS.size > 0", 15)
    doc = page.evaluate("clone([...PROJECTS.values()][0])")
    doc.pop("id", None)
    doc["meta"]["org"] = WITH
    page.evaluate("async (d) => { await STORE.create('old1', d); }", doc)
    wait_until(page, "PROJECTS.has('old1')", 5)
    page.evaluate("openProject('old1', 'setup')")
    page.wait_for_timeout(300)
    check(
        "the older record holds the credentials, as planted (not vacuous)",
        page.evaluate("S.meta.org") == WITH,
    )
    page.evaluate(PASTE, ["meta.org", "changed"])
    wait_until(page, DRAINED, 10)
    page.wait_for_timeout(200)
    entries = page.evaluate(
        "LOG.filter(e => e.change).map(e => e.text + JSON.stringify(e.change))"
    )
    check("the edit is in the history", len(entries) >= 1, str(entries))
    leaks = [e for e in entries if SECRET in e]
    check(
        "and holds no password, in its words or its from and to", not leaks, str(leaks)
    )
    ctx.close()


def import_checks(browser, fields: dict[str, str]) -> None:
    print("Import: a JSON file and a review an older version saved")
    ctx, page, _ = open_app(browser)
    open_project(page)
    record = page.evaluate("clone(storedRecord(S))")
    record.pop("id", None)
    plant = TYPED
    set_paths = 0
    for path in fields:
        keys = path.split(".")
        node = record
        for key in keys[:-1]:
            nxt = node.get(key) if isinstance(node, dict) else node[int(key)]
            if nxt is None:
                break
            node = nxt
        else:
            last = keys[-1]
            if isinstance(node, dict):
                node[last] = plant
                set_paths += 1
            elif isinstance(node, list) and last.isdigit() and int(last) < len(node):
                node[int(last)] = plant
                set_paths += 1
    check("the file carries credentials in many fields", set_paths > 40, str(set_paths))
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "review.json"
        f.write_text(json.dumps({"_state": record}), encoding="utf-8")
        known = page.evaluate("[...PROJECTS.keys()]")
        before = len(known)
        page.set_input_files("#importFile", str(f))
        wait_until(page, f"PROJECTS.size === {before + 1}", 10)
    new = page.evaluate(f"[...PROJECTS.keys()].find(k => !{known!r}.includes(k))")
    page.evaluate(f"openProject({new!r}, 'setup')")
    page.wait_for_timeout(300)
    check(
        "the person is told",
        page.inner_text("#toast") == toast_text(page, "toast.importedCreds"),
        page.inner_text("#toast"),
    )
    bad = []
    for path in fields:
        value = page.evaluate(f"get({path!r})")
        if isinstance(value, str) and value != TYPED_CLEAN:
            bad.append(f"{path}: {value!r}")
    check(
        "every field that carried credentials holds the address without them",
        not bad,
        "; ".join(bad[:3]),
    )
    wait_until(page, DRAINED, 10)
    page.wait_for_timeout(200)
    leaks = page.evaluate(DEEP_FIND, SECRET)
    check("the password is nowhere after the import", not leaks, str(leaks))
    ctx.close()

    # An older version's review, kept in this browser.
    ctx, page, _ = open_app(browser)
    legacy = {
        "meta": {"solution": f"Old {WITH}", "org": WITH},
        "items": {},
        "gates": {},
        "metrics": [{"name": WITH, "value": "1"}],
        "card": {"name": WITH},
    }
    page.evaluate(
        "(j) => { localStorage.removeItem('chai-legacy-imported');"
        " localStorage.setItem('chai-review-v1', JSON.stringify(j)); }",
        legacy,
    )
    page.evaluate("goHome()")
    page.wait_for_timeout(300)
    page.click('[data-act="legacy"]')
    wait_until(page, "PROJECTS.size > 0", 10)
    got = page.evaluate("[...PROJECTS.values()][0]")
    check(
        "a legacy review keeps its address without the credentials",
        got["meta"]["org"] == CLEAN
        and got["meta"]["solution"] == f"Old {CLEAN}"
        and got["metrics"][0]["name"] == CLEAN
        and got["card"]["name"] == CLEAN,
        json.dumps(got)[:300],
    )
    check(
        "and the person is told",
        page.inner_text("#toast") == toast_text(page, "toast.legacyImportedCreds"),
        page.inner_text("#toast"),
    )
    wait_until(page, DRAINED, 10)
    leaks = [h for h in page.evaluate(DEEP_FIND, SECRET) if h != "browser storage"]
    check("the password is nowhere in the page's records", not leaks, str(leaks))
    ctx.close()


def net_checks(browser) -> None:
    print("createProject is the net under every way a record is made")
    ctx, page, _ = open_app(browser)
    page.evaluate("loadSamples()")
    wait_until(page, "PROJECTS && PROJECTS.size > 0", 15)
    got = page.evaluate(
        """async (w) => {
            const d = blankProject('net'); d.meta.org = w;
            const id = await createProject(d, 'test');
            await new Promise(r => setTimeout(r, 200));
            return PROJECTS.get(id).meta.org;
        }""",
        WITH,
    )
    check("a record made with credentials is stored without", got == CLEAN, got)
    ctx.close()


# ---- the export -----------------------------------------------------------------

PLANT = """async ([doc, id]) => {
  await STORE.create(id, doc);
  for (let i = 0; i < 100 && !PROJECTS.has(id); i++)
    await new Promise(r => setTimeout(r, 20));
  openProject(id, 'setup');
  setFrameworkEnabled('optica', true);
  const stored = JSON.stringify(storedRecord(S));
  const hashes = JSON.stringify(contentHashes(storedRecord(S)));
  const md = exportMD();
  const json = JSON.stringify(projectJSON(S));
  const html = exportHTML();
  return {md, json, html, stored, hashes,
          storedAfter: JSON.stringify(storedRecord(S)),
          hashesAfter: JSON.stringify(contentHashes(storedRecord(S))),
          csv: exportCSV()};
}"""


def export_checks(browser, source: str, label: str = "") -> dict:
    ctx, page, _ = open_app(browser, label or None)
    page.evaluate("loadSamples()")
    wait_until(page, "PROJECTS && PROJECTS.size >= 2", 15)
    doc = planted_doc(page, TYPED)
    # Free text, so the notes, the table cells and the history are all in it.
    page.evaluate("(w) => writeLog([...PROJECTS.keys()][0], w)", f"History {WITH}")
    out = page.evaluate(PLANT, [doc, "plant1"])
    ctx.close()
    return out


def export_report(browser) -> None:
    print("Export: a record that already holds credentials")
    out = export_checks(browser, "")
    md = out["md"]
    check(
        "the planted record holds the credentials (not vacuous)",
        SECRET in out["stored"],
    )
    check("the Markdown report has no password", SECRET not in md, "found")
    check("nor a user name before an @ in an address", f"{USER}:" not in md)
    check(
        "but still has the address, without them",
        CLEAN.replace("?", "?") in md.replace("\\", ""),
    )
    check(
        "the stored record is unchanged by the export",
        out["stored"] == out["storedAfter"],
    )
    check("so is its fingerprint", out["hashes"] == out["hashesAfter"])
    fp = json.loads(out["hashes"])
    check(
        "the Markdown names the stored record's fingerprint",
        all(str(v) in md for v in fp.values() if isinstance(v, str) and len(v) >= 32),
        out["hashes"][:80],
    )
    j = json.loads(out["json"])
    check(
        "the JSON export keeps the stored text, as its contract says",
        SECRET in out["json"] and SECRET in json.dumps(j["_state"]),
    )
    check(
        "the JSON export's _state is the stored record",
        json.dumps(j["_state"], sort_keys=True)
        == json.dumps(
            {k: v for k, v in json.loads(out["stored"]).items() if k != "id"},
            sort_keys=True,
        ),
    )
    check(
        "the HTML report never makes a link of an address in a value",
        not re.search(r'href="[a-z+.-]+://[^"/]*@', out["html"]),
    )


def entry_mutations(browser, source: str, work: Path) -> None:
    print("A weakened guard is noticed (mutation)")
    caught: list[bool] = []
    rows = [
        (
            "edit() does not remove the credentials",
            "  val = cleaned.value;\n",
            "",
            "entry",
        ),
        (
            "edit() does not tell the person",
            '  if(cleaned.removed) toast(t("toast.credsRemoved"));\n',
            "",
            "toast",
        ),
        (
            "the field keeps showing what was typed",
            "    el.value = stored;\n",
            "",
            "shown",
        ),
        (
            "the history copies the earlier value",
            'from = scrubAddressCredentials(from && typeof from === "object" ? clone(from) : from).value;',  # noqa: E501
            "from = from;",
            "history",
        ),
        (
            "the import does not remove them",
            'const cut=scrubAddressCredentials(p).removed;\n    const id=await createProject(p,"Imported from a JSON export");',  # noqa: E501
            'const cut=0;\n    const id=await createProject(p,"Imported from a JSON export");',  # noqa: E501
            "import",
        ),
        (
            "createProject is not a net",
            "  scrubAddressCredentials(data);  //",
            "  //",
            "net",
        ),
    ]
    for n, (label, old, new, kind) in enumerate(rows):
        copy = work / f"entry{n}.html"
        copy.write_text(
            mutated(APP.read_text(encoding="utf-8"), old, new), encoding="utf-8"
        )
        ctx, page, _ = open_app(browser, copy.as_uri())
        page.evaluate("loadSamples()")
        wait_until(page, "PROJECTS && PROJECTS.size > 0", 15)
        pid = page.evaluate("[...PROJECTS.keys()].sort()[0]")
        page.evaluate(f"openProject({pid!r}, 'setup')")
        page.wait_for_timeout(300)
        noticed = False
        match kind:
            case "entry" | "toast" | "shown":
                out = page.evaluate(PASTE, ["meta.org", TYPED])
                noticed = (
                    out["stored"] != TYPED_CLEAN
                    if kind == "entry"
                    else out["toast"] != toast_text(page, "toast.credsRemoved")
                    if kind == "toast"
                    else out["shown"] != TYPED_CLEAN
                )
            case "history":
                doc = page.evaluate("clone([...PROJECTS.values()][0])")
                doc.pop("id", None)
                doc["meta"]["org"] = WITH
                page.evaluate("async (d) => { await STORE.create('old1', d); }", doc)
                wait_until(page, "PROJECTS.has('old1')", 5)
                page.evaluate("openProject('old1', 'setup')")
                page.wait_for_timeout(300)
                page.evaluate(PASTE, ["meta.org", "changed"])
                wait_until(page, DRAINED, 10)
                noticed = any(
                    SECRET in e
                    for e in page.evaluate(
                        "LOG.filter(e => e.change).map(e => e.text + JSON.stringify(e.change))"  # noqa: E501
                    )
                )
            case "import":
                record = page.evaluate("clone(storedRecord(S))")
                record.pop("id", None)
                record["meta"]["org"] = WITH
                f = work / f"mut{n}.json"
                f.write_text(json.dumps({"_state": record}), encoding="utf-8")
                before = page.evaluate("PROJECTS.size")
                page.set_input_files("#importFile", str(f))
                wait_until(page, f"PROJECTS.size === {before + 1}", 10)
                noticed = page.inner_text("#toast") != toast_text(
                    page, "toast.importedCreds"
                )
            case "net":
                got = page.evaluate(
                    """async (w) => {
                        const d = blankProject('net'); d.meta.org = w;
                        const id = await createProject(d, 'test');
                        await new Promise(r => setTimeout(r, 200));
                        return PROJECTS.get(id).meta.org;
                    }""",
                    WITH,
                )
                noticed = got != CLEAN
        caught.append(noticed)
        check(f"{label}: noticed ({kind})", noticed, "nothing was noticed")
        ctx.close()
    check(
        "every weakened guard is noticed",
        len(caught) == len(rows) and all(caught),
        str(caught),
    )


def main() -> int:
    faulthandler.dump_traceback_later(1200, exit=True)
    source = APP.read_text(encoding="utf-8")
    work = Path(tempfile.mkdtemp(prefix="addr-cred-"))
    try:
        with sync_playwright() as pw:
            browser = launch(pw)
            ctx, page, errors = open_app(browser)
            print(f"The function, on {len(CASES)} cases")
            bad = run_table(page)
            check(
                "every case: what remains, the count and idempotence",
                not bad,
                "; ".join(bad[:3]),
            )
            check("the table has at least 60 cases", len(CASES) >= 60, str(len(CASES)))
            positions = []
            for raw, want, n in CASES:
                if n == 1 and "\n" not in raw:
                    for before, after in POSITIONS:
                        positions.append((before.format(a=raw), after.format(c=want)))
            got = page.evaluate(
                "(xs) => xs.map(x => stripAddressCredentials(x).text)",
                [p[0] for p in positions],
            )
            wrong = [
                (a, g, w) for (a, w), g in zip(positions, got, strict=True) if g != w
            ]
            check(
                f"the same {len(positions)} addresses inside text, first, last and between",  # noqa: E501
                not wrong,
                str(wrong[:2]),
            )
            parser_checks(page)
            check("no page errors", not errors, "; ".join(errors[:3]))
            ctx.close()
            renderer_checks()
            rule_mutations(browser, source, work)
            fields = entry_checks(browser)
            typing_checks(browser)
            other_entry_checks(browser)
            history_checks(browser)
            import_checks(browser, fields)
            net_checks(browser)
            export_report(browser)
            entry_mutations(browser, source, work)
            browser.close()
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)
    print()
    if failures:
        print(f"{len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("address credential checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
