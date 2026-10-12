#!/usr/bin/env python3
"""The agent access page: a person mints, sees and revokes their own tokens (#164).

Drives the real built page in Chromium against a stand-in API. What it pins:

  - the page is offered in server mode only, and not at all in the browser-only copy;
  - a mint shows the token once, in one element, and the list never has the secret;
  - the token, planted as a distinctive canary, is nowhere else: not in browser
    storage, the address, history, the log, a toast, the console, `pending`,
    PROJECTS or STORE, and not in the DOM after "I have copied it", after a change
    of language, or after leaving the page and coming back;
  - a label with markup is text; the server's words are text;
  - revoke asks first, sends one DELETE, and the list moves on;
  - the cap, 429, 401/403, 5xx, a dropped connection and "feature off" each say so;
  - every language has every string, Hebrew is laid out right to left, and the page
    has no horizontal scroll on a phone;
  - focus moves to the reveal and back, and the live regions never hold the token;
  - a read-only viewer may mint (R-71: any role);
  - and mutations of the built page (the token written to storage, left in the DOM
    after dismiss, a label as markup, no confirm, kept across a re-render, a silent
    copy failure, ...) are each noticed.

    pixi run test-agent-access
"""

# ruff: noqa: E501 (the mutations name exact lines of the built page)

from __future__ import annotations

import contextlib
import functools
import http.server
import json
import re
import shutil
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
APP = DOCS / "app" / "index.html"
sys.path.insert(0, str(ROOT / "scripts"))

import build_app  # noqa: E402

CSP_META = re.compile(r'<meta http-equiv="Content-Security-Policy"[^>]*>')
LOCALES = ("en", "es", "fr", "de", "hi", "ru", "zh-Hans", "he")
JSON = "application/json"

CANARY = "CANARYSECRET"
SECRET = "agt_0123456789abcdef." + CANARY + "x" * (43 - len(CANARY))
ASSERT_SHAPE = re.fullmatch(r"agt_[0-9a-f]{16}\.[A-Za-z0-9_-]{43}", SECRET)
assert ASSERT_SHAPE, "the stand-in token must have the shape the page accepts"
SECRET2 = "agt_fedcba9876543210." + CANARY + "y" * (43 - len(CANARY))
MARKUP = "<img src=x onerror=window.__pwned=1><b>x</b>"
IDS = ["aaaaaaaaaaaaaaa1", "aaaaaaaaaaaaaaa2", "aaaaaaaaaaaaaaa3"]


class Run:
    def __init__(self, loud: bool, fast: bool = False) -> None:
        self.loud = loud
        self.fast = fast  # a mutation run stops at the first check that notices it
        self.failed: list[str] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        if self.loud:
            print(
                f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}"
            )
        if not ok:
            self.failed.append(name)
            if self.fast:
                raise Noticed(name)


class Noticed(Exception):
    """Raised in a mutation run, at the first check the mutation fails."""


@contextlib.contextmanager
def serve(directory: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    handler = functools.partial(Quiet, directory=str(directory))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        httpd.allow_reuse_address = True
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            yield f"http://127.0.0.1:{httpd.server_address[1]}"
        finally:
            httpd.shutdown()


class Stub:
    """The token routes of the API. `fail` maps an operation to a status, or to
    "abort"; `rows` is what GET returns; every request is counted."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.fail: dict[str, object] = {}
        self.detail: object = None
        self.posts: list[dict] = []
        self.deletes: list[str] = []
        self.gets = 0
        self.secret = SECRET

    def row(self, tid: str, label: str, *, state: str = "active", **extra) -> dict:
        return {
            "id": tid,
            "label": label,
            "created_at": "2026-01-01T08:00:00Z",
            "expires_at": "2099-01-01T16:00:00Z"
            if state == "active"
            else "2026-01-01T16:00:00Z",
            "revoked_at": "2026-01-01T09:00:00Z" if state == "revoked" else None,
            "last_used_at": None,
            "state": state,
            **extra,
        }

    def handle(self, route) -> None:
        req = route.request
        method = req.method
        op = {"GET": "list", "POST": "mint", "DELETE": "revoke"}[method]
        if op == "list":
            self.gets += 1
        elif op == "mint":
            self.posts.append(json.loads(req.post_data or "{}"))
        else:
            self.deletes.append(req.url.rsplit("/", 1)[-1])
        f = self.fail.get(op)
        if f == "abort":
            route.abort()
            return
        if f:
            body = {} if self.detail is None else {"detail": self.detail}
            route.fulfill(status=int(f), body=json.dumps(body), content_type=JSON)
            return
        if op == "list":
            route.fulfill(status=200, body=json.dumps(self.rows), content_type=JSON)
        elif op == "mint":
            label = self.posts[-1].get("label", "")
            tid = self.secret.split(".")[0][4:]
            self.rows.insert(0, self.row(tid, label))
            route.fulfill(
                status=201,
                headers={"Cache-Control": "no-store"},
                body=json.dumps(
                    {
                        "id": tid,
                        "token": self.secret,
                        "label": label,
                        "created_at": "2026-01-01T08:00:00Z",
                        "expires_at": "2099-01-01T16:00:00Z",
                    }
                ),
                content_type=JSON,
            )
        else:
            tid = self.deletes[-1]
            for r in self.rows:
                if r["id"] == tid:
                    r["state"] = "revoked"
                    r["revoked_at"] = "2026-01-01T10:00:00Z"
            route.fulfill(status=204, body="")


OBSERVE = """(() => {
  window.__toasts = [];
  const start = () => {
    const el = document.getElementById('toast');
    if (!el) return setTimeout(start, 10);
    new MutationObserver(() => window.__toasts.push(el.textContent))
      .observe(el, {childList: true, characterData: true, subtree: true});
  };
  start();
})()"""


def boot(
    browser,
    base: str,
    stub: Stub,
    *,
    width: int = 1100,
    projects=None,
    scheme: str = "light",
):
    """Open the page in server mode. Returns (context, page, console, errors)."""
    ctx = browser.new_context(
        viewport={"width": width, "height": 900},
        permissions=["clipboard-read", "clipboard-write"],
        color_scheme=scheme,
    )
    page = ctx.new_page()
    page.set_default_timeout(8000)
    console: list[str] = []
    errors: list[str] = []
    page.on("console", lambda m: console.append(m.text))
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(OBSERVE)
    health = {
        "status": "ok",
        "version": "t",
        "database": "up",
        "db_role": "restricted",
        "auth_mode": "proxy-header:proxy",
    }
    page.route(
        "**/api/health", lambda r: r.fulfill(body=json.dumps(health), content_type=JSON)
    )
    page.route(
        "**/api/me",
        lambda r: r.fulfill(
            body='{"id":"a@b","name":"A B","email":"a@b","dev":false}',
            content_type=JSON,
        ),
    )
    page.route(
        "**/api/projects",
        lambda r: r.fulfill(body=json.dumps(projects or []), content_type=JSON),
    )
    page.route(
        "**/api/projects/*/log", lambda r: r.fulfill(body="{}", content_type=JSON)
    )
    page.route("**/api/events", lambda r: r.abort())
    page.route(re.compile(r".*/api/agent-tokens(/.*)?$"), stub.handle)
    page.goto(base + "/index.html")
    page.wait_for_function("() => typeof LOADED !== 'undefined' && LOADED")
    page.wait_for_function("() => MODE === Mode.API")
    return ctx, page, console, errors


def open_page(page) -> None:
    page.click('[data-act="agent-open"]')
    page.wait_for_selector("#agentPage")
    page.wait_for_function(
        "() => AGENT.load !== AgentLoad.LOADING && AGENT.load !== AgentLoad.IDLE"
    )


def mint(page, label: str = "") -> None:
    page.fill("#agentLabel", label)
    page.click("#agentCreate")
    page.wait_for_selector("#agentReveal")
    page.wait_for_function("() => !AGENT.busy && AGENT.load === AgentLoad.READY")


# Everything the token could be found in, other than the one element that shows it.
SWEEP = """async ([canary, domToo]) => {
  const hits = [];
  const look = (name, text) => { if (String(text).includes(canary)) hits.push(name); };
  for (let i = 0; i < localStorage.length; i++)
    look('localStorage', localStorage.key(i) + localStorage.getItem(localStorage.key(i)));
  for (let i = 0; i < sessionStorage.length; i++)
    look('sessionStorage', sessionStorage.key(i) + sessionStorage.getItem(sessionStorage.key(i)));
  try {
    for (const d of (await indexedDB.databases())) {
      look('indexedDB name', d.name);
      const db = await new Promise((res, rej) => { const r = indexedDB.open(d.name);
        r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
      for (const n of db.objectStoreNames) {
        const all = await new Promise(res => { const r = db.transaction(n).objectStore(n).getAll();
          r.onsuccess = () => res(r.result); r.onerror = () => res([]); });
        look('indexedDB', JSON.stringify(all));
      }
    }
  } catch (e) {}
  look('the address', location.href);
  look('history state', JSON.stringify(history.state));
  look('the title', document.title);
  look('cookies', document.cookie);
  look('the log', JSON.stringify(LOG));
  look('pending', JSON.stringify(pending));
  look('PROJECTS', JSON.stringify([...PROJECTS.values()]));
  look('the open record', JSON.stringify(S));
  look('STORE', JSON.stringify(STORE, (k, v) => (v instanceof EventSource ? null : v)));
  look('the page state', JSON.stringify(AGENT));
  look('a toast', JSON.stringify(window.__toasts));
  look('the toast element', document.getElementById('toast').textContent);
  look('the status region', document.getElementById('agentStatus')?.textContent || '');
  look('the error region', document.getElementById('agentErr')?.textContent || '');
  if (domToo) look('the DOM', document.documentElement.outerHTML);
  if (domToo) look('the secret variable', AGENT_SECRET);
  return hits;
}"""


def sweep(page, canary: str = CANARY, dom: bool = True) -> list[str]:
    return page.evaluate(SWEEP, [canary, dom])


def holders(page) -> list[str]:
    """The ids of the elements whose text or attributes hold the canary."""
    return page.evaluate(
        """(c) => [...document.querySelectorAll('*')].filter(e =>
          [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.includes(c))
          || [...e.attributes].some(a => a.value.includes(c)))
          .map(e => e.id || e.tagName)""",
        CANARY,
    )


def say(page, key: str, **params) -> str:
    return page.evaluate("([k, p]) => t(k, p)", [key, params])


def scenarios(browser, base: str, run: Run) -> None:
    check = run.check

    print("Mint: shown once, in one element, and nowhere else")
    stub = Stub()
    ctx, page, console, errors = boot(browser, base, stub)
    check(
        "the portfolio offers the page in server mode",
        page.locator('[data-act="agent-open"]').count() == 1,
    )
    open_page(page)
    check("the page has one h1", page.locator("#agentPage h1").count() == 1)
    check(
        "focus moves to the page heading",
        page.evaluate("document.activeElement.id") == "agentTitle",
    )
    label = page.locator("#agentLabel")
    check(
        "the label field is not remembered and is capped",
        label.get_attribute("autocomplete") == "off"
        and label.get_attribute("maxlength") == "64"
        and page.evaluate("AGENT_LABEL_MAX") == 64,
    )
    check(
        "an empty list says so",
        say(page, "agent.list.empty") in page.inner_text("#agentCount"),
    )
    page.fill("#agentLabel", MARKUP)
    page.press("#agentLabel", "Enter")  # the form is keyboard-operable
    page.wait_for_selector("#agentReveal")
    page.wait_for_function("() => !AGENT.busy && AGENT.load === AgentLoad.READY")
    check("one POST was sent", len(stub.posts) == 1, str(stub.posts))
    check("with the label as typed", stub.posts[0] == {"label": MARKUP})
    check(
        "the token is shown, as text",
        page.inner_text("#agentSecret") == SECRET,
        page.inner_text("#agentSecret"),
    )
    check(
        "the reveal panel has the focus",
        page.evaluate("document.activeElement.id") == "agentReveal",
    )
    check(
        "it is a labeled region and says it is shown once",
        page.get_attribute("#agentReveal", "role") == "region"
        and page.get_attribute("#agentReveal", "aria-labelledby") == "agentRevealTitle"
        and say(page, "agent.shownOnce") in page.inner_text("#agentReveal"),
    )
    check(
        "the token is in one element only",
        holders(page) == ["agentSecret"],
        str(holders(page)),
    )
    check(
        "and in no place a page keeps things",
        sweep(page, dom=False) == [],
        str(sweep(page, dom=False)),
    )
    check(
        "the live regions are live and never hold it",
        page.get_attribute("#agentStatus", "role") == "status"
        and page.get_attribute("#agentErr", "role") == "alert"
        and CANARY not in page.inner_text("#agentStatus"),
    )
    check(
        "the list shows the new token by id, with no secret",
        page.locator(".agent-token").count() == 1
        and "aaaaaaaa" not in page.inner_text("#agentList")
        and "0123456789abcdef" in page.inner_text("#agentList")
        and CANARY not in page.inner_text("#agentList"),
        page.inner_text("#agentList"),
    )
    check(
        "a label with markup is text",
        page.locator("#agentList img, #agentList b").count() == 0
        and MARKUP in page.inner_text("#agentList")
        and not page.evaluate("!!window.__pwned"),
    )
    check(
        "the new token is live",
        say(page, "agent.state.active") in page.inner_text("#agentList"),
    )

    print("Copy")
    page.click("#agentCopy")
    page.wait_for_function("document.getElementById('agentStatus').textContent !== ''")
    check(
        "copy puts the token on the clipboard and says so",
        page.evaluate("navigator.clipboard.readText()") == SECRET
        and say(page, "agent.copied") in page.inner_text("#agentStatus"),
        page.inner_text("#agentStatus"),
    )
    page.evaluate(
        "navigator.clipboard.writeText = () => Promise.reject(new Error('no'));"
        "document.execCommand = () => false;"
        "document.getElementById('agentStatus').textContent = ''"
    )
    page.click("#agentCopy")
    page.wait_for_function("document.getElementById('agentStatus').textContent !== ''")
    check(
        "a copy that fails says so, and leaves the token selected",
        say(page, "agent.copyFailed") in page.inner_text("#agentStatus")
        and CANARY in page.evaluate("getSelection().toString()"),
        page.inner_text("#agentStatus"),
    )

    print("Dismiss: the node and the variable are gone")
    page.click("#agentDone")
    check("the panel is gone", page.locator("#agentReveal, #agentSecret").count() == 0)
    check(
        "the variable is cleared",
        page.evaluate("AGENT_SECRET === null"),
    )
    check(
        "focus returns to the form",
        page.evaluate("document.activeElement.id") == "agentLabel",
    )
    hits = sweep(page)
    check("the token is nowhere, DOM included", hits == [], str(hits))
    check("and not in the console", not any(CANARY in m for m in console), str(console))
    check("no page errors", not errors, "; ".join(errors[:3]))
    ctx.close()

    print("Re-render and leaving clear a token that was not dismissed")
    stub = Stub()
    ctx, page, console, errors = boot(browser, base, stub)
    open_page(page)
    mint(page, "one")
    page.select_option("#lang", "de")
    page.wait_for_function("() => document.documentElement.lang === 'de'")
    check(
        "a change of language draws the page again without the token",
        page.locator("#agentReveal").count() == 0
        and page.evaluate("AGENT_SECRET === null")
        and page.locator("#agentPage").count() == 1
        and say(page, "agent.title") in page.inner_text("#agentTitle"),
    )
    check("so nothing holds it", sweep(page) == [], str(sweep(page)))
    check(
        "and the list is still there, in the new language",
        page.locator(".agent-token").count() == 1
        and say(page, "agent.state.active") in page.inner_text("#agentList"),
    )
    page.select_option("#lang", "en")
    mint(page, "two")
    page.click('#agentPage [data-home="1"]')
    page.wait_for_selector("#plistHost")
    check(
        "going back to the portfolio clears it",
        page.evaluate("AGENT_SECRET === null") and sweep(page) == [],
        str(sweep(page)),
    )
    open_page(page)
    check(
        "and coming back does not show it again",
        page.locator("#agentReveal").count() == 0 and sweep(page) == [],
    )
    mint(page, "three")
    page.click(".brand-btn")
    page.wait_for_selector("#plistHost")
    check("the brand button clears it too", sweep(page) == [], str(sweep(page)))
    open_page(page)
    mint(page, "four")
    page.evaluate("dispatchEvent(new Event('pagehide'))")
    check("the page closing clears it", page.evaluate("AGENT_SECRET === null"))
    check(
        "the console never had it", not any(CANARY in m for m in console), str(console)
    )
    ctx.close()

    print("The list holds public fields only")
    stub = Stub()
    stub.rows = [
        stub.row(IDS[0], "mine", token=SECRET, secret_hash=CANARY),
        stub.row(IDS[1], "old", state="expired"),
        stub.row(IDS[2], "gone", state="revoked"),
        {"id": "../x", "label": "bad id"},
    ]
    ctx, page, _, _ = boot(browser, base, stub)
    open_page(page)
    check(
        "a secret the server should never send is neither kept nor shown",
        sweep(page) == [],
        str(sweep(page)),
    )
    check(
        "an id that is not a token id is dropped",
        page.locator(".agent-token").count() == 3,
    )
    check(
        "live, expired and revoked each say what they are",
        all(
            say(page, k) in page.inner_text("#agentList")
            for k in (
                "agent.state.active",
                "agent.state.expired",
                "agent.state.revoked",
            )
        ),
    )
    check(
        "only a live token can be revoked",
        page.locator("#agentList button").count() == 1,
    )
    check(
        "the count says how many are live",
        say(page, "agent.live", count=1) in page.inner_text("#agentCount"),
        page.inner_text("#agentCount"),
    )
    check(
        "dates are in the reader's language",
        "2026" in page.inner_text(".agent-token-facts"),
    )
    ctx.close()

    print("Revoke: asks, sends once, and the list moves on")
    stub = Stub()
    stub.rows = [stub.row(IDS[0], "keep"), stub.row(IDS[1], MARKUP)]
    ctx, page, _, errors = boot(browser, base, stub)
    open_page(page)
    btn = page.locator(f'button[data-token-id="{IDS[1]}"]')
    btn.click()
    check(
        "a confirmation opens, as a dialog, with Cancel focused",
        page.get_attribute("#agentConfirm .modal", "role") == "dialog"
        and page.evaluate("document.activeElement.textContent")
        == say(page, "dash.cancel"),
    )
    check(
        "it names the token as text",
        IDS[1] in page.inner_text("#agentConfirm")
        and page.locator("#agentConfirm img").count() == 0,
    )
    page.keyboard.press("Escape")
    check(
        "Escape cancels, nothing is sent, and focus returns to the button",
        page.locator("#agentConfirm").count() == 0
        and stub.deletes == []
        and page.evaluate("document.activeElement.dataset.tokenId") == IDS[1],
    )
    btn.click()
    page.click("#agentConfirm .modal .btn:not(.danger)")
    check("Cancel sends nothing", stub.deletes == [])
    btn.click()
    page.click("#agentConfirm .btn.danger")
    page.wait_for_function("() => !AGENT.busy && AGENT.tokens.some(r => r.revoked_at)")
    check(
        "DELETE was sent once, for that token",
        stub.deletes == [IDS[1]],
        str(stub.deletes),
    )
    check(
        "the list shows it revoked, with no button",
        page.locator(f'button[data-token-id="{IDS[1]}"]').count() == 0
        and page.locator(f'button[data-token-id="{IDS[0]}"]').count() == 1
        and say(page, "agent.state.revoked") in page.inner_text("#agentList"),
    )
    check(
        "and the page announces it",
        say(page, "agent.revoked", id=IDS[1]) in page.inner_text("#agentStatus"),
        page.inner_text("#agentStatus"),
    )
    stub.fail["revoke"] = 404
    page.click(f'button[data-token-id="{IDS[0]}"]')
    page.click("#agentConfirm .btn.danger")
    page.wait_for_function(
        "() => document.getElementById('agentErr').textContent !== ''"
    )
    check(
        "a token already gone says so and the list is refreshed",
        page.inner_text("#agentErr") == say(page, "agent.err.gone"),
        page.inner_text("#agentErr"),
    )
    check("no page errors", not errors, "; ".join(errors[:3]))
    ctx.close()

    print("Every failure says what happened")
    cases = (
        ("mint", 409, None, "agent.err.cap"),
        ("mint", 429, None, "agent.err.rate"),
        ("mint", 401, None, "agent.err.denied"),
        ("mint", 403, None, "agent.err.denied"),
        ("mint", 500, "boom", "agent.err.server"),
        ("mint", 503, None, "agent.err.server"),
        ("mint", "abort", None, "agent.err.network"),
    )
    for op, status, detail, key in cases:
        stub = Stub()
        stub.fail[op] = status
        stub.detail = detail
        ctx, page, console, errors = boot(browser, base, stub)
        open_page(page)
        page.fill("#agentLabel", "x")
        page.click("#agentCreate")
        page.wait_for_function(
            "() => document.getElementById('agentErr').textContent !== ''"
        )
        got = page.inner_text("#agentErr")
        check(f"{op} {status}: {key}", got == say(page, key), got)
        check(
            f"{op} {status}: no token is shown and the button works again",
            page.locator("#agentReveal").count() == 0
            and not page.is_disabled("#agentCreate"),
        )
        check(
            f"{op} {status}: the server's words are not repeated",
            "boom" not in got and len(stub.posts) == 1,
        )
        ctx.close()

    stub = Stub()
    stub.secret = "agt_0123456789abcdef.<b>not the shape of a token</b>"
    ctx, page, _, _ = boot(browser, base, stub)
    open_page(page)
    page.click("#agentCreate")
    page.wait_for_function(
        "() => document.getElementById('agentErr').textContent !== ''"
    )
    check(
        "an answer that is not a token is not shown as one",
        page.locator("#agentReveal").count() == 0
        and page.inner_text("#agentErr") == say(page, "agent.err.shape")
        and "not the shape" not in page.inner_text("#main"),
    )
    ctx.close()

    stub = Stub()
    stub.fail["mint"] = 422
    stub.detail = MARKUP + "z" * 400
    ctx, page, _, _ = boot(browser, base, stub)
    open_page(page)
    page.fill("#agentLabel", "bad")
    page.click("#agentCreate")
    page.wait_for_function(
        "() => document.getElementById('agentErr').textContent !== ''"
    )
    got = page.inner_text("#agentErr")
    check(
        "a refusal quotes the server as text, capped",
        MARKUP[:20] in got
        and len(got) < 400
        and page.locator("#agentErr *").count() == 0
        and not page.evaluate("!!window.__pwned"),
        got[:80],
    )
    ctx.close()

    stub = Stub()
    stub.fail["list"] = 500
    ctx, page, _, _ = boot(browser, base, stub)
    open_page(page)
    check(
        "a list that cannot load says so and offers a retry",
        page.inner_text("#agentErr") == say(page, "agent.err.server")
        and page.locator("#agentList button").count() == 1,
    )
    del stub.fail["list"]
    page.click("#agentList button")
    page.wait_for_function("() => AGENT.load === AgentLoad.READY")
    check("and the retry works", page.inner_text("#agentErr") == "")
    ctx.close()

    stub = Stub()
    stub.fail["list"] = 404
    ctx, page, _, _ = boot(browser, base, stub)
    open_page(page)
    check(
        "a server with the feature off says so, and shows no form",
        say(page, "agent.off.detail") in page.inner_text("#agentOff")
        and page.is_visible("#agentOff")
        and not page.is_visible("#agentForm")
        and not page.is_visible("#agentList"),
    )
    ctx.close()

    stub = Stub()
    stub.fail["mint"] = 404
    ctx, page, _, _ = boot(browser, base, stub)
    open_page(page)
    page.click("#agentCreate")
    page.wait_for_function("() => AGENT.load === AgentLoad.OFF")
    check(
        "a mint answered 404 turns the page into the same explanation",
        page.is_visible("#agentOff") and not page.is_visible("#agentForm"),
    )
    ctx.close()

    print("Any role may mint, so a read-only viewer sees a working form")
    proj = {
        "id": "p1",
        "meta": {"solution": "Theirs"},
        "access": {"owners": ["boss@x"], "readers": ["a@b"]},
    }
    stub = Stub()
    ctx, page, _, _ = boot(browser, base, stub, projects=[proj])
    page.evaluate("openProject('p1', 'setup')")
    check("the viewer is read-only on that project", page.evaluate("RO") is True)
    page.evaluate("goHome()")
    open_page(page)
    mint(page, "reader")
    check(
        "a token is made",
        len(stub.posts) == 1 and not page.is_disabled("#agentLabel"),
    )
    check("and is nowhere else", sweep(page, dom=False) == [])
    ctx.close()

    print("The page is not offered without a server")
    page = browser.new_page()
    page.set_default_timeout(8000)
    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.url))
    page.route(
        "**/api/**", lambda r: r.fulfill(status=404, body="", content_type="text/plain")
    )
    page.goto(base + "/index.html")
    page.wait_for_function("() => typeof MODE !== 'undefined' && MODE === Mode.LOCAL")
    page.wait_for_selector("#plistHost")
    check(
        "no button in the browser-only copy",
        page.locator('[data-act="agent-open"]').count() == 0,
    )
    page.evaluate("openAgentPage()")
    check(
        "and opening it does nothing",
        page.locator("#agentPage").count() == 0
        and not any("agent-tokens" in u for u in requests),
    )
    page.close()

    print("Every language has every string; Hebrew is right to left")
    stub = Stub()
    ctx, page, _, _ = boot(browser, base, stub)
    en_keys = page.evaluate(
        "Object.keys(I18N_CATALOGS.en).filter(k => k.startsWith('agent.'))"
    )
    check("there are agent strings", len(en_keys) > 40, str(len(en_keys)))
    for loc in LOCALES:
        bad = page.evaluate(
            """([loc, keys]) => keys.filter(k => {
              const e = I18N_CATALOGS.en[k], c = I18N_CATALOGS[loc][k];
              if (c === undefined || c === '' || (typeof c === 'object' && !c.other)) return true;
              const s = typeof c === 'string' ? c : Object.values(c).join(' ');
              const ph = x => [...new Set(JSON.stringify(x).match(/\\{\\w+\\}/g) || [])].sort().join();
              return ph(c) !== ph(e) || /[<>]/.test(s);
            })""",
            [loc, en_keys],
        )
        check(
            f"{loc}: every agent string is there, with its placeholders",
            not bad,
            str(bad),
        )
        if loc != "en":
            same = page.evaluate(
                """([loc, keys]) => keys.filter(k => typeof I18N_CATALOGS.en[k] === 'string'
                  && I18N_CATALOGS[loc][k] === I18N_CATALOGS.en[k])""",
                [loc, en_keys],
            )
            allowed = {"agent.id", "agent.revokeLabel"}
            check(
                f"{loc}: it is translated, not copied", set(same) <= allowed, str(same)
            )
        counts = page.evaluate(
            "([loc]) => [0,1,2,5,11,21].map(n => withLocale(loc, () => t('agent.live', {count: n})))",
            [loc],
        )
        check(
            f"{loc}: the count reads for 0, 1, 2, 5, 11 and 21",
            all("{" not in c and c for c in counts),
            str(counts),
        )
    safety = page.evaluate("I18N_CATALOGS.en['@meta'].safety")
    check(
        "the store-it-like-a-password warning is safety-bearing (R-55)",
        "agent.storeWarning" in safety and "agent.shownOnce" in safety,
    )
    zh = page.evaluate(
        "withLocale('zh-Hans', () => [t('agent.storeWarning'), t('agent.shownOnce')])"
    )
    check(
        "so it shows English until a reviewer is recorded",
        zh[0].startswith("Treat a token like a password")
        and zh[1].startswith("Copy it now"),
        str(zh),
    )
    ctx.close()

    for loc, width in (("he", 360), ("en", 360), ("de", 320), ("he", 1100)):
        stub = Stub()
        stub.rows = [stub.row(IDS[0], "L" * 64), stub.row(IDS[1], "x", state="revoked")]
        ctx, page, _, _ = boot(browser, base, stub, width=width)
        page.select_option("#lang", loc)
        page.wait_for_function(f"() => document.documentElement.lang === '{loc}'")
        open_page(page)
        mint(page, "")
        rtl = page.evaluate("document.documentElement.dir") == "rtl"
        check(
            f"{loc} {width}px: direction is {'rtl' if loc == 'he' else 'ltr'}",
            rtl == (loc == "he"),
        )
        # The page's own content. (The header's brand is wider than a 360px Hebrew
        # screen today, which is not this page's.)
        over = page.evaluate(
            """() => Math.max(0, ...[...document.querySelectorAll('#agentPage, #agentPage *')]
              .map(e => e.getBoundingClientRect())
              .map(r => Math.max(r.right - innerWidth, -r.left)))"""
        )
        check(
            f"{loc} {width}px: the page's content stays on screen", over <= 1, str(over)
        )
        if loc == "he":
            box = page.evaluate(
                """() => { const r = document.querySelector('.agent-token').getBoundingClientRect();
                  const b = document.querySelector('.agent-token-head .agent-badge').getBoundingClientRect();
                  return [r.left, r.right, b.left, b.right]; }"""
            )
            check(
                "he: the state badge is at the left end of the head (the end of the line)",
                box[2] - box[0] < box[1] - box[3],
                str(box),
            )
        ctx.close()
    ctx, page, _, _ = boot(browser, base, Stub(), width=360, scheme="dark")
    open_page(page)
    mint(page, "")
    check(
        "dark mode at phone width: no horizontal scroll, and the page is dark",
        page.evaluate(
            "Math.max(0, ...[...document.querySelectorAll('#agentPage *')]"
            ".map(e => e.getBoundingClientRect().right - innerWidth))"
        )
        <= 1
        and page.evaluate("getComputedStyle(document.body).backgroundColor")
        != "rgb(237, 241, 242)",
    )
    ctx.close()

    print("Keyboard: the whole flow without a pointer")
    stub = Stub()
    stub.rows = [stub.row(IDS[0], "k")]
    ctx, page, _, _ = boot(browser, base, stub)
    open_page(page)
    page.focus("#agentLabel")
    page.keyboard.type("kb")
    page.keyboard.press("Tab")
    check(
        "Tab goes from the label to Create",
        page.evaluate("document.activeElement.id") == "agentCreate",
    )
    page.keyboard.press("Enter")
    page.wait_for_selector("#agentReveal")
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    check(
        "Tab walks the reveal to Copy then Done",
        page.evaluate("document.activeElement.id") in {"agentCopy", "agentDone"},
    )
    page.focus("#agentDone")
    page.keyboard.press("Enter")
    check("Enter on Done dismisses it", page.locator("#agentReveal").count() == 0)
    ctx.close()


def mutate(src: str, old: str, new: str) -> str:
    assert src.count(old) == 1, (
        f"mutation target not unique ({src.count(old)}): {old[:60]}"
    )
    html = src.replace(old, new)
    return CSP_META.sub(lambda _: build_app.csp_meta(html), html, count=1)


MUTATIONS = {
    "the token is written to localStorage": (
        "  AGENT_SECRET = token;\n",
        "  AGENT_SECRET = token; localStorage.setItem('k', token);\n",
    ),
    "the token is written to sessionStorage": (
        "  AGENT_SECRET = token;\n",
        "  AGENT_SECRET = token; sessionStorage.setItem('k', token);\n",
    ),
    "the token goes in the address": (
        "  AGENT_SECRET = token;\n",
        "  AGENT_SECRET = token; location.hash = token;\n",
    ),
    "the token goes in a toast": (
        '  agentAnnounce(t("agent.tokenMade"));\n',
        '  agentAnnounce(t("agent.tokenMade")); toast(AGENT_SECRET);\n',
    ),
    "the token goes in the console": (
        "  AGENT_SECRET = token;\n",
        "  AGENT_SECRET = token; console.log(token);\n",
    ),
    "the token goes in the pending patch": (
        "  AGENT_SECRET = token;\n",
        "  AGENT_SECRET = token; pending.x = {t: token};\n",
    ),
    "the token goes in the live region": (
        '  agentAnnounce(t("agent.tokenMade"));\n',
        '  agentAnnounce(t("agent.tokenMade") + AGENT_SECRET);\n',
    ),
    "the token stays in the DOM after dismiss": (
        "function dismissAgentReveal(){\n  dropAgentSecret();",
        "function dismissAgentReveal(){\n  AGENT_SECRET = null;",
    ),
    "the variable survives dismiss": (
        "function dismissAgentReveal(){\n  dropAgentSecret();",
        "function dismissAgentReveal(){\n  { const p = document.getElementById(AgentEl.REVEAL); if(p) p.remove(); }",
    ),
    "the token is kept across a re-render": (
        "function renderAgentPage(focusTop){\n  agentLeave();\n",
        "function renderAgentPage(focusTop){\n",
    ),
    "the token outlives leaving the portfolio": (
        "function renderDashboardShell(){\n  agentLeave();",
        "function renderDashboardShell(){\n  ;",
    ),
    "the token outlives the page closing": (
        'addEventListener("pagehide", agentLeave);',
        "",
    ),
    "a label is put in as markup": (
        'name.dir = "auto";',
        'name.dir = "auto"; name.innerHTML = r.label;',
    ),
    "a server's words are put in as markup": (
        "box.textContent = failure === AgentFailure.REFUSED && detail",
        "box.innerHTML = failure === AgentFailure.REFUSED && detail",
    ),
    "revoke asks nothing": (
        'b.addEventListener("click", () => confirmRevokeAgentToken(r, b));',
        'b.addEventListener("click", () => revokeAgentToken(r.id));',
    ),
    "revoke is sent twice": (
        '    await STORE.req(`${AGENT_PATH}/${id}`, {method: "DELETE"});\n',
        '    await STORE.req(`${AGENT_PATH}/${id}`, {method: "DELETE"});\n'
        '    await STORE.req(`${AGENT_PATH}/${id}`, {method: "DELETE"});\n',
    ),
    "a failed copy is silent": (
        'agentAnnounce(t(ok ? "agent.copied" : "agent.copyFailed"));',
        'agentAnnounce(t("agent.copied"));',
    ),
    "a secret in the list is kept": (
        "id: r.id, label: s(r.label)",
        "id: r.id, token: r.token, label: s(r.label)",
    ),
    "the feature being off is not noticed": (
        "AGENT.load = f === AgentFailure.OFF ? AgentLoad.OFF : AgentLoad.FAILED;",
        "AGENT.load = AgentLoad.FAILED;",
    ),
    "a failed mint is silent": (
        "    else agentSay(f, err && err.detail);\n    if(agentPageShown()) paintAgentPage();\n    return;",
        "    if(agentPageShown()) paintAgentPage();\n    return;",
    ),
    "the label field is remembered by the browser": (
        'id="agentLabel" autocomplete="off"',
        'id="agentLabel" autocomplete="on"',
    ),
    "the page is offered without a server": (
        '${MODE===Mode.API?`<button class="btn" data-act="${esc(Act.AGENT_OPEN)}">',
        '${true?`<button class="btn" data-act="${esc(Act.AGENT_OPEN)}">',
    ),
    "the page opens without a server": (
        "  if(MODE !== Mode.API) return;   // no server, no tokens: the page is not offered\n",
        "",
    ),
    "the reveal does not take the focus": (
        "  panel.focus();\n}",
        "}",
    ),
    "the live region is not live": (
        'id="agentStatus" class="vh" role="status" aria-live="polite"',
        'id="agentStatus" class="vh"',
    ),
    "a token is accepted in any shape": (
        "if(!AGENT_TOKEN_SHAPE.test(token)){",
        "if(false){",
    ),
}


def main() -> int:
    src = APP.read_text(encoding="utf8")
    js = "\n".join(
        p.read_text(encoding="utf8")
        for p in sorted((ROOT / "app" / "js" / "20-app").glob("60-*.js"))
    )
    assert "agentLeave" in js and "agentLeave" in src, "build the app first"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        with tempfile.TemporaryDirectory() as tmp, serve(DOCS / "app") as base:
            real = Run(loud=True)
            scenarios(browser, base, real)

            print("Mutations of the built page are each noticed")
            for name, (old, new) in MUTATIONS.items():
                out = Path(tmp) / "m"
                shutil.copytree(DOCS / "app", out, dirs_exist_ok=True)
                try:
                    (out / "index.html").write_text(
                        mutate(src, old, new), encoding="utf8"
                    )
                except AssertionError as e:
                    real.failed.append(f"mutation target missing: {name}: {e}")
                    print(f"  FAIL  {name}: {e}")
                    continue
                with serve(out) as mbase:
                    quiet = Run(loud=False, fast=True)
                    try:
                        scenarios(browser, mbase, quiet)
                    except Noticed:
                        pass
                    except Exception as e:  # a mutation may break the flow outright
                        quiet.failed.append(f"crashed: {type(e).__name__}")
                caught = bool(quiet.failed)
                print(f"  {'PASS' if caught else 'FAIL'}  {name}")
                if not caught:
                    real.failed.append(f"mutation survived: {name}")
        browser.close()

    print()
    if real.failed:
        print(f"{len(real.failed)} check(s) failed")
        for f in real.failed:
            print(f"  - {f}")
        return 1
    print("agent-access checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
