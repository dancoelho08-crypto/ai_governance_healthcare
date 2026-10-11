#!/usr/bin/env python3
"""A save the server refused is not retried, and says why (#186).

When the API refuses a write with a 4xx (a 422 for a malformed value, a framework
stamp it will not accept (R-67), a lone surrogate; also 400, 409, 413), the same
bytes will be refused again. The dashboard used to treat every non-auth failure as
"server unavailable": six retries, then "Couldn't save ... check your connection"
while the server was up. Now a refusal is sent once, the edit stays in the field and
in the pending patch, and the toast quotes the server's reason as text.

Drives the real built page in Chromium against a stand-in API that counts PATCHes:

  - 422, 400, 409 and 413 are each sent exactly once, and the page keeps the
    edit (the field, `pending`), shows the server's reason, and says "refused",
    not "check your connection";
  - the reason is text, never markup, and is capped; FastAPI's list form is read;
  - 500, 502, 503, a dropped connection, 408 and 429 are still retried, six sends
    in all, as before; a retry that then succeeds clears the pending edit;
  - 401, 403 and 404 keep their own handling (access changed, project gone), once;
  - the message exists in every language;
  - and mutations of the built page each fail some check, so the checks bite.

    pixi run test-save-refused
"""

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

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
APP = DOCS / "app" / "index.html"

MAX_SEND = 6  # MAX_SAVE_ATTEMPTS in app/js/00-core/40-writes.js
LOCALES = ("en", "es", "fr", "de", "hi", "ru", "zh-Hans", "he")
sys.path.insert(0, str(ROOT / "scripts"))

import build_app  # noqa: E402

CSP_META = re.compile(r'<meta http-equiv="Content-Security-Policy"[^>]*>')

PAYLOAD = "<img src=x onerror=window.__pwned=1><b>bold</b>"


class Run:
    def __init__(self, loud: bool) -> None:
        self.loud = loud
        self.failed: list[str] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        if self.loud:
            print(
                f"  {'PASS' if ok else 'FAIL'}  {name}{'' if ok else f'  <- {detail}'}"
            )
        if not ok:
            self.failed.append(name)


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


def boot(browser, url: str, replies: list):
    """Boot the page against a stand-in API. Each PATCH takes the next of `replies`
    (the last repeats): ('status', body-or-None) or 'abort'. Returns page, patches."""
    patches: list[dict] = []

    def patch(route):
        patches.append(json.loads(route.request.post_data or "{}"))
        reply = replies[min(len(patches), len(replies)) - 1]
        if reply == "abort":
            route.abort()
        else:
            status, body = reply
            route.fulfill(
                status=status,
                body=json.dumps(body if body is not None else {}),
                content_type="application/json",
            )

    health = {
        "status": "ok",
        "version": "t",
        "database": "up",
        "db_role": "restricted",
        "auth_mode": "proxy-header:proxy",
    }
    page = browser.new_page(viewport={"width": 1300, "height": 900})
    page.set_default_timeout(8000)
    # Shrink the retry backoff (0.8s to 8s, the only fractional delay), so six
    # sends take a moment, not 20s.
    page.add_init_script(
        """(() => {
          const real = window.setTimeout.bind(window);
          window.setTimeout = (fn, ms, ...a) =>
            real(fn, !Number.isInteger(ms) && ms < 9000 ? 5 : ms, ...a);
        })()"""
    )
    json_ct = "application/json"
    page.route(
        "**/api/health",
        lambda r: r.fulfill(status=200, body=json.dumps(health), content_type=json_ct),
    )
    page.route(
        "**/api/me",
        lambda r: r.fulfill(
            status=200,
            body='{"id":"a@b","name":"A B","email":"a@b","dev":false}',
            content_type=json_ct,
        ),
    )
    page.route(
        "**/api/projects",
        lambda r: r.fulfill(
            status=200,
            body=json.dumps([{"id": "p1", "meta": {"solution": "Original"}}]),
            content_type=json_ct,
        ),
    )
    page.route("**/api/projects/p1", patch)
    page.route(
        "**/api/projects/p1/log",
        lambda r: r.fulfill(status=200, body="{}", content_type=json_ct),
    )
    page.route("**/api/events", lambda r: r.abort())
    page.goto(url)
    page.wait_for_function(
        "() => typeof LOADED !== 'undefined' && LOADED", timeout=15000
    )
    page.wait_for_function("() => MODE === Mode.API")
    page.evaluate("openProject('p1', 'setup')")
    page.wait_for_selector('[data-bind="meta.solution"]')
    return page, patches


def settle(page, condition: str) -> None:
    """Wait for `condition`; a build that never reaches it is a failed check below,
    not a crash, so a mutation is reported rather than aborting the run."""
    with contextlib.suppress(PlaywrightTimeout):
        page.wait_for_function(f"() => {condition}", timeout=4000)


def edit(page, text: str) -> None:
    field = page.locator('[data-bind="meta.solution"]')
    field.fill(text)
    field.blur()


def state(page) -> dict:
    return page.evaluate(
        """() => ({
          field: document.querySelector('[data-bind="meta.solution"]')?.value,
          pending: JSON.stringify(pending.p1 || null),
          toast: document.getElementById('toast').textContent,
          saved: document.getElementById('saved').textContent,
          pwned: !!window.__pwned,
          toastEls: document.getElementById('toast').children.length,
        })"""
    )


def scenarios(browser, base: str, run: Run) -> None:
    check = run.check
    url = base + "/index.html"

    print("A refusal is sent once, kept, and explained")
    refusals = (
        (422, {"detail": "Framework stamp not accepted."}, "Framework stamp"),
        (400, {"detail": "Malformed."}, "Malformed"),
        (409, {"detail": "Already exists."}, "Already exists"),
        (413, {"detail": "Body too large."}, "Body too large"),
        (
            422,
            {"detail": [{"loc": ["body", "meta", "solution"], "msg": "bad value"}]},
            "meta.solution: bad value",
        ),
    )
    for status, body, expect in refusals:
        page, patches = boot(browser, url, [(status, body)])
        edit(page, "My new text")
        page.wait_for_timeout(1500)  # past every retry a wrong build would make
        s = state(page)
        label = f"{status} {expect!r}"
        check(f"{label}: sent exactly once", len(patches) == 1, str(len(patches)))
        check(f"{label}: the toast quotes the server", expect in s["toast"], s["toast"])
        check(
            f"{label}: it does not blame the connection",
            "connection" not in s["toast"].lower(),
            s["toast"],
        )
        check(
            f"{label}: the edit stays in the field",
            s["field"] == "My new text",
            str(s["field"]),
        )
        check(
            f"{label}: and in the pending patch",
            "My new text" in s["pending"],
            s["pending"],
        )
        check(
            f"{label}: the label says refused, not saved",
            "refused" in s["saved"].lower(),
            s["saved"],
        )
        page.close()

    print("The server's words are text, and short")
    page, patches = boot(browser, url, [(422, {"detail": PAYLOAD + "x" * 500})])
    edit(page, "Payload")
    page.wait_for_timeout(800)
    s = state(page)
    check("markup is shown as characters", PAYLOAD[:20] in s["toast"], s["toast"])
    check("no element was made from it", s["toastEls"] == 0, str(s["toastEls"]))
    check("and nothing ran", not s["pwned"])
    check("the quote is capped", len(s["toast"]) < 400, str(len(s["toast"])))
    page.close()

    page, patches = boot(browser, url, [(422, {})])
    edit(page, "No reason")
    page.wait_for_timeout(800)
    s = state(page)
    check(
        "a refusal with no reason still says so, once",
        len(patches) == 1 and "refused" in s["toast"].lower(),
        s["toast"],
    )
    page.close()

    print("Transient failures are still retried")
    transient = (
        ("500", [(500, {"detail": "x"})]),
        ("502", [(502, None)]),
        ("503", [(503, None)]),
        ("408", [(408, None)]),
        ("429", [(429, None)]),
        ("a dropped connection", ["abort"]),
    )
    for name, replies in transient:
        page, patches = boot(browser, url, replies)
        edit(page, "Retry me")
        settle(page, "document.getElementById('saved').textContent === 'Not saved'")
        s = state(page)
        check(
            f"{name}: sent {MAX_SEND} times",
            len(patches) == MAX_SEND,
            str(len(patches)),
        )
        check(f"{name}: the edit is kept", "Retry me" in s["pending"], s["pending"])
        check(
            f"{name}: and the final message is the connection one",
            "connection" in s["toast"].lower(),
            s["toast"],
        )
        page.close()

    page, patches = boot(browser, url, [(503, None), (503, None), (200, {})])
    edit(page, "Third time")
    settle(page, "!pending.p1 && !flushing.p1")
    check("a retry that succeeds clears the pending edit", len(patches) == 3)
    page.close()

    print("Access and deletion keep their own handling")
    for status, expect in ((403, "access"), (401, "access"), (404, "")):
        page, patches = boot(browser, url, [(status, None)])
        edit(page, "Denied")
        page.wait_for_timeout(1200)
        s = state(page)
        check(f"{status}: sent once", len(patches) == 1, str(len(patches)))
        check(
            f"{status}: not the refused message",
            "refused" not in s["toast"].lower(),
            s["toast"],
        )
        if expect:
            check(
                f"{status}: says access changed",
                expect in s["toast"].lower(),
                s["toast"],
            )
        page.close()

    print("The message exists in every language")
    page, _ = boot(browser, url, [(200, {})])
    en = page.evaluate("tEn('toast.saveRefused', {detail: 'ZZ'})")
    for loc in LOCALES:
        got = page.evaluate(
            """loc => ['toast.saveRefused', 'toast.saveRefusedBare', 'saved.refused']
                 .map(k => withLocale(loc, () => t(k, {detail: 'ZZ'})))""",
            loc,
        )
        ok = all("{" not in g and not g.startswith(("toast.", "saved.")) for g in got)
        ok = ok and "ZZ" in got[0] and (loc == "en" or got[0] != en)
        check(f"{loc}: toast, bare toast and label are all written", ok, str(got))
    page.close()


def mutate(src: str, old: str, new: str) -> str:
    assert src.count(old) == 1, f"mutation target not unique: {old[:60]}"
    html = src.replace(old, new)
    # The page names its script by hash; a mutated script needs its own policy.
    return CSP_META.sub(lambda _: build_app.csp_meta(html), html, count=1)


MUTATIONS = {
    "422 is treated as retryable": (
        "if(status>=HttpStatus.CLIENT_MIN && status<HttpStatus.SERVER_MIN) "
        "return SaveOutcome.REFUSED;",
        "",
    ),
    "the refusal drops the edit instead of keeping it": (
        "keep the edit so it can be corrected.\n      restore();",
        "keep the edit so it can be corrected.\n",
    ),
    "the server's reason goes in as markup": (
        "t.textContent=msg;",
        "t.innerHTML=msg;",
    ),
    "the server's reason is not capped": (
        "d.length>REFUSAL_DETAIL_MAX ?",
        "false ?",
    ),
    "a network failure is not retried": (
        'err.code = "unavailable"; err.outcome = SaveOutcome.RETRY;',
        'err.code = "unavailable";',
    ),
    "a 500 is refused, not retried": (
        "return SaveOutcome.RETRY;\n}\nconst REFUSAL",
        "return SaveOutcome.REFUSED;\n}\nconst REFUSAL",
    ),
}


def main() -> int:
    src = APP.read_text(encoding="utf8")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        with tempfile.TemporaryDirectory() as tmp, serve(DOCS / "app") as base:
            real = Run(loud=True)
            scenarios(browser, base, real)

            print("Mutations of the built page are each noticed")
            for name, (old, new) in MUTATIONS.items():
                out = Path(tmp) / "m"
                shutil.copytree(DOCS / "app", out, dirs_exist_ok=True)
                (out / "index.html").write_text(mutate(src, old, new), encoding="utf8")
                with serve(out) as mbase:
                    quiet = Run(loud=False)
                    scenarios(browser, mbase, quiet)
                caught = bool(quiet.failed)
                print(f"  {'PASS' if caught else 'FAIL'}  {name}")
                if not caught:
                    real.failed.append(f"mutation survived: {name}")
        browser.close()

    print()
    if real.failed:
        print(f"{len(real.failed)} check(s) failed")
        return 1
    print("save-refused checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
