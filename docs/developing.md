# Developing it

This page is for people who change the code or the documentation: how the
repository is laid out, how the dashboard is built, how to add a framework or a
language, which tests prove what, and the rules a change has to meet.

## The repository

| Path | What is there |
|---|---|
| `app/` | The dashboard's source: CSS, JavaScript, the message catalogs |
| `docs/app/index.html` | The dashboard, **generated** from `app/`. Never edited by hand |
| `server/` | The API: FastAPI, asyncpg, the SQL migrations, and its tests (`server/README.md`) |
| `proxy/` | The Caddy front door and its image |
| `compose.yaml`, `compose.dev.yaml` | The stack, and the opt-in development override |
| `scripts/` | Build, check and operator tools: `make doctor`, `make dispose`, `make phi-scan` and the guardrails |
| `tests/` | The browser, proxy, stack and documentation suites |
| `schema/`, `examples/` | The project JSON schema, and the Python examples ([Exports](exports.md)) |
| `docs/` | This site's pages. The checklists and metrics pages are generated |
| `REQUIREMENTS.md`, `DECISIONS.md` | What must stay true, and why it is built the way it is |
| `CLAUDE.md` | The working rules for this repository |

## How the app is built

`docs/app/index.html` is **generated**. Do not edit it.

The dashboard has to ship as one self-contained file: it is served by the proxy
in the deployed stack, it is opened straight off disk with no server, and it is
published to GitHub Pages as the example page. But a single file holding the
CSS, two governance frameworks, eight languages and all the rendering is not
maintainable. So the source is split under `app/` and concatenated by
`scripts/build_app.py`:

```text
app/
  index.html                   shell, with CSS and JS insertion markers
  css/app.css
  i18n/
    <language>.json            the message catalogs; en.json is the source
    framework/<language>.json  the framework content, per language
  js/
    00-core/                   framework-agnostic: util, languages, model,
                               stores, state, writes, search, DOM helpers
    10-frameworks/
      00-registry.js           the framework contract
      05-project/              project setup (not owned by any framework)
      01-engine/               the engine: rules, screens, a framework's words
      10-chai/                 CHAI's plug-ins: model card, metrics, T&E picker,
                               samples, its own controls
      90-register.js           registers every definition in the build
    20-app/                    shell, dashboard, exports, session, events, boot
                               (none of which names a framework)
```

Files concatenate in filename order, so a definition must live in a file that
sorts before its first use, normally in `00-core/`.

```bash
pixi run build-app     # app/ -> docs/app/index.html
pixi run check-app     # syntax, undefined names, use before declaration, duplicates
pixi run test-app      # end-to-end browser tests
```

`check-app` checks the published page and a build of every
`app/frameworks/*/build.json`, because a build of other frameworks leaves
framework code out and a reference into it would otherwise show only as a blank
page. It parses the script with tree-sitter's JavaScript grammar and resolves
every name through its scopes, and fails on:

- a name nothing declares that is not a JavaScript or browser global. Shared
  code may reach a name only some builds have only behind `typeof`, which asks
  whether it was built: `typeof name` itself, or a use inside the branch a typeof
  test of that name guards, as in
  `if (typeof chaiCardMarkdown === "function") return chaiCardMarkdown(ctx);`
  (the consequent of an `if` or `?:`, or the right of `&&`, tested with
  `=== "function"` or another type, or `!== "undefined"`, either way round, with
  `==` and `!=` counting the same, and parentheses and comments inside them
  ignored). The other side must be a string literal
  whose value is one `typeof` returns (`"undefined"`, `"object"`, `"boolean"`,
  `"number"`, `"bigint"`, `"string"`, `"symbol"`, `"function"`); escapes are
  decoded, so `"undefin\x65d"` is `"undefined"`. Nothing wider: not the else
  branch, not code after `if (typeof x !== "function") return;`, not a `||`
  form, not a comparison with a variable or a template literal. `delete name`
  reads nothing and is not reported. A new browser
  global goes in `BROWSER_GLOBALS` in
  `scripts/check_app.py`, and `pixi run test-check-app` must find it in each
  browser engine;
- a `const`, `let` or `class` read before its declaration has run: earlier in
  the same code (top level, an IIFE or `new function(){...}`, a static block, a
  computed key `[k]` of a class or object member, the right-hand side of
  `for (const a of ...)`, a destructuring default reading a name bound later in
  the same pattern, a class's own name in a computed key of its members, as in
  `class C { [C]() {} }`, which is bound only after every key is evaluated), or
  in a function that top-level code calls before the declaration (`new K()`
  runs K's constructor and instance field initializers, not a function a field
  holds; calling a generator runs none of its body; a name two block functions
  declare has both bodies followed, since which block ran last is not known);
- a name two modules declare at top level, including a function declared in a
  top-level block (or as the whole body of an `if` or `else`, which Annex B
  treats as a block) that replaces another module's function or var. As in Annex
  B, a block function whose name a top-level `let`, `const` or `class` also
  declares (before or after it) binds nothing at top level, so is not reported,
  and neither are two block functions of one name;
- a syntax error, from the parse and from `node --check`. Without node the
  check says it skipped `node --check`, which `REQUIRE_TESTS=1` makes a failure
  (CI's lint and test workflows both set it).

Where it is exact, and where it is not (D-80). `tests/check_app_cases.py` holds
some three hundred scripts that `pixi run test-check-app` runs both through the
check and in node, and the check must report a problem on exactly the ones node
throws a ReferenceError on while loading them: typeof guards, undefined names in
code that runs, reads in the temporal dead zone (destructuring, computed keys, a
class's own name, IIFEs, static blocks and fields, generators, `delete`, `await`),
Annex B block functions, and calls through the call graph. On those cases it is
exact. Its known limits:

- the call graph follows only calls of a plain name (`f()`, `new K()`), not
  method calls, callbacks or events, and assumes every path through a called
  function runs, so it can miss a load-order bug reached another way, and can
  report a read on a branch that does not run during load, or in the body of a
  block function another block of that name replaced first;
- through calls, only top-level `const`, `let` and `class` are checked: a
  function called before a `const` of its own enclosing function is declared
  is missed;
- a parameter default reading a later parameter, a `switch` jumping past a
  `let` in another case, `with` and direct `eval` are not modeled;
- a typeof guard is the exact form above, so safe code in another shape (an
  early return, an else branch, `||`, a `switch`) is reported;
- code after the first `await` of an async function (the boot module is an async
  IIFE) is taken to run after load. "First" is first in the text, so an `await`
  on a branch not taken hides a read that does run during load;
- a name the app means to declare that is also a browser global (`open`,
  `close`, `print`, `origin`, `history`, `Image`, ...) passes as the global if
  its declaration goes missing;
- a name a script adds to `window` at run time is reported if read bare, and
  `window.x` is not checked at all.

A function body that runs only after load is, correctly, never reported.

A prek hook rebuilds on any change under `app/`, so the generated file can never
go stale.

## The store

All persistence goes through classes in `app/js/00-core/20-stores.js` that
implement one interface:

| Method | Purpose |
|---|---|
| `subscribeAll(cb)` | Stream the project list; returns an unsubscribe function |
| `create(id, data)` | Create a project |
| `update(id, patch)` | Deep-merge a patch into a project |
| `remove(id)` | Delete a project and its live audit log. The server keeps its version history |
| `log(id, entry)` | Append an audit-log entry |
| `subscribeLog(id, cb)` | Stream the most recent log entries for a project |

Two implementations ship: `LocalStore` (browser `localStorage`, the example page)
and `ApiStore` (the self-hosted FastAPI and PostgreSQL backend). `ApiStore` is
selected automatically when `/api/health` answers, so one build serves both the
GitHub Pages copy and the Docker stack. It never falls back silently: if a
server was expected and cannot be reached, the app stops and says so.

`ApiStore` also has methods only a server can honor: `purgeVersions` (destroy a
project's history), `getHold` and `setHold` (litigation holds), `recordExport`
(the export beacon) and `showOlderLog`. The app offers each of these only when
the store has the method, so a store without them is not shown a button that does
nothing.

To back the tool with something else, such as Firestore, Supabase or your own
service, add a class implementing the six methods and select it at boot.

!!! warning "Sign-off needs real identity"

    `LocalStore` has no concept of a user, so checkpoint sign-offs it records
    are self-asserted. If sign-offs need to carry weight for audit, your backend
    must supply an authenticated identity, as the API does from the proxy.

## Adding a framework

A framework is a **definition**, `app/frameworks/<id>/framework.json`, in the
shape `schema/framework.schema.json` describes: its sections and items, the
statuses an item can take (each with a class the engine scores by), its
checkpoints (each option with a class: go, conditional, revise, stop or
retire), its phases, review and flags, and the catalog keys its screens use.
`pixi run check-framework` checks it, with rules a schema cannot state.

One engine (`app/js/10-frameworks/01-engine/`) draws every screen and computes
every status from a definition, and `10-frameworks/90-register.js` registers
each one in the build. A framework needs code only for something no definition
can say: CHAI's model card, its key metrics, its T&E picker and its samples
live in `app/js/10-frameworks/10-chai/` and reach the engine through
`frameworkExtras()` and `registerPlugin()`. OPTICA has no code at all.

Nothing else in the app names a framework. `pixi run test-framework-boundary`
fails if the shell, the engine, the setup screen or the registration names
anything a framework's own code defines, or says a framework's name in a
string (browser storage keys aside).

!!! warning "One framework owns the status"

    Exactly one framework per build is the **primary**: the portfolio's status,
    phase, flags, readiness score and report come from it (CHAI, in the default
    build). That is deliberate: the portfolio needs **one** status, and
    averaging two frameworks' judgments would produce a number that means
    nothing.

    The shell asks the primary through its **spine**: items, sections,
    categories and gates with their labels, a decision's class (`GateClass`),
    the answers, phase, flags, status, next review, score and report body,
    plus optional Markdown and JSON extras and worked examples. The full list
    is in `00-registry.js`, and `90-register.js` builds it from a
    definition; CHAI's extras are in `10-chai/25-spine.js`.

    Optional frameworks never propagate status in either direction. An OPTICA
    answer cannot move a CHAI score, and vice versa. The frameworks ask
    different parties for different evidence at different moments, and no OPTICA
    item fully discharges a CHAI criterion; see the [crosswalk](crosswalk.md).
    Evidence can be cited in both; a judgment in one is never a judgment in
    the other.

    To build the dashboard with a framework of your own in place of CHAI
    and OPTICA, see [Bring your own framework](frameworks/custom.md).

## Languages

The dashboard speaks English, Spanish, French, German, Hindi, Russian,
Simplified Chinese and Hebrew. It picks the reader's saved choice, then the
browser's languages, then English, and the picker in the header switches it. The
choice is per browser: two people can read the same project in different
languages.

Hebrew reads right to left, and the whole layout mirrors: the step rail moves to
the right, accents sit on the reading edge, tables run right to left. Text a
person typed keeps its own direction, so an English vendor name in a Hebrew page
keeps its punctuation, and so does English shown because a warning is not yet
reviewed. The stylesheet uses logical properties (`margin-inline-start`,
`text-align:start`), and `check-i18n` fails on a left or right that would not
mirror.

Every string comes from a message catalog, `app/i18n/<language>.json`, embedded
into the single dashboard file by the build. English (`en.json`) is the source.
A framework's own text (its sections, items and checkpoints) is translated in
`app/i18n/framework/<language>.json` for CHAI and OPTICA, which must have all
eight languages. A framework you bring is translated in
`app/frameworks/<id>/i18n/<language>.json`: English is its definition, and any
other language is optional, but a language you supply must be complete
(`check-i18n` names what is missing). Where a language is missing, the
framework's words show in English with a note saying so. The words of a screen
around a framework (headings, eyebrows, the report's footer) are the engine's
neutral ones unless the definition names its own catalog keys (`ui`).
`pixi run check-i18n` fails if a catalog lacks a key, has an extra one, drops or
invents a `{placeholder}`, misses a plural form the language needs, holds markup,
or if code puts an English literal on screen without going through `t()`.

The translations are **machine-drafted**. The Simplified Chinese one has been
reviewed and approved by a fluent reader; the others have not. Safety-bearing
warnings (the patient-data notice and the storage-mode banners, listed under
`"@meta".safety` in `en.json`) are shown in English until someone fluent in the
language reviews them. A wrong translation of a warning is worse than an English
one. To record a review, add the key and who reviewed it, with the date, to
that catalog's `"@meta".reviewers`, for example
`"safety.scope": "A. Reviewer, 2026-10-08"`.

Reports follow the reader: the HTML, PDF and Markdown exports are written in the
chosen language and say which. The JSON and CSV exports stay English, because
scripts and the Croissant exporter read them.

The framework content (CHAI's stages, criteria, checkpoints and model card
fields) is translated too, in `app/i18n/framework/<language>.json`, and each
screen showing it says the wording is an unofficial translation. The English in
the framework definitions stays the source: `tests/test_framework_i18n.py` fails
if a criterion changes without its catalogs. A record still stores the English
value, such as a checkpoint decision. OPTICA's chapters and questions are
translated the same way, and so are the names of CHAI's suggested metrics (a
metric you add keeps CHAI's English name). The server's error messages are
English, but the dashboard never shows them: it shows its own translated text
for each error code.

`tests/test_i18n.py` counts the hard-coded text left on screen in a pseudo-locale,
and that count may only go down.

To add a language: copy `en.json` to `app/i18n/<tag>.json` and
`framework/en.json` to `app/i18n/framework/<tag>.json`, translate the values,
set `"@meta"`, add the tag to `Locale` and `LOCALE_CHOICES` in
`app/js/00-core/02-i18n.js` (and to `RTL_LOCALES` if it reads right to left) and
its plural categories to `scripts/check_i18n.py`, and run `pixi run build-app`.

## The server

The API, its migrations and its configuration are described in
[`server/README.md`](https://github.com/tonyreina/ai_governance_healthcare/blob/main/server/README.md).
Its tests need a real PostgreSQL, because what they test *is* the database's
behavior.

## Running the tests

If something is up but not working, start here:

```bash
make doctor             # asks the running stack what is wrong
```

```bash
pixi run check          # every lint and build hook
pixi run test-app       # the dashboard, in a real browser
pixi run test-access    # roles and the delete confirmation
pixi run test-te        # the CHAI metric picker
pixi run test-pdf       # renders a real PDF and reads it back
pixi run test-proxy     # the proxy against a real Caddy (needs Docker)
pixi run test-stack     # end to end against a running stack
pixi run test-enums     # the enum guardrail
pixi run test-workflows # does CI run every test that exists?
```

`pixi task list` shows every suite. The ones that need Docker (the proxy, the
stack, the backup, purge, disposal and subject-access suites) say so in their
description. Each guardrail is shown failing by a test of its own, because a
check that has never been seen to fail is a claim, not a control.

The server's own suite needs a PostgreSQL to test against, because what it
tests *is* the database's behavior: a row lock serializing two writers, a
trigger refusing to rewrite history:

```bash
docker run -d --name chai-test-db -p 55432:5432 \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=chai_test postgres:17-alpine
cd server
pip install -e '.[dev]'
TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/chai_test pytest
```

The stack's own database is not reachable from the host, so the tests run against
a throwaway one.

This one is a URL you write yourself, so percent-encode the password if it
contains `/`, `@`, `:`, `?` or `#`. The stack itself does that for you.

Without `TEST_DATABASE_URL` those tests skip and say why. A skip exits 0, so on
your own machine it looks like a pass. Set `REQUIRE_TESTS=1` to turn every skip
into a failure; CI always does.

### In CI

Every pull request and every push to `main` runs all of the above in GitHub
Actions (`.github/workflows/test.yml`): the server suite against a PostgreSQL 17
service container, the dashboard suites in Chromium, the proxy against a real
Caddy, and the whole Compose stack end to end. One job, **tests passed**, fails
if any of them failed, was canceled, or was skipped.

`main` requires that job: a pull request cannot be merged while it is pending or
red, and there is no administrator bypass.

`pixi run test-workflows` checks the CI configuration itself: it fails if a
`test-*` task is not run by CI, or a test file has no task, so a test cannot be
added and quietly left out.

## The rules a change has to meet

The working rules are in [CLAUDE.md](https://github.com/tonyreina/ai_governance_healthcare/blob/main/CLAUDE.md).
In short:

- **Requirements and decisions are binding.** `REQUIREMENTS.md` says what must
  stay true and `DECISIONS.md` why things are built as they are. A change that
  conflicts with an entry says so first, and records the new decision in the same
  change.
- **Tests ship with the code.** New behavior gets a test that fails without
  it. A bug fix starts with a regression test that fails for the right reason.
  A change that crosses a boundary (the API and the database, the proxy and the
  identity header) gets an integration test against the real thing, never a
  fake.
- **A skip is a failure.** CI sets `REQUIRE_TESTS=1`. Never add a `skip` to get
  a check green.
- **A closed set of values gets a type.** A role, a status or a mode is a
  `StrEnum` in Python and a frozen object in JavaScript, never a bare string.
  `pixi run check-enums` enforces it as a ratchet that only shrinks.
- **Text a person types stays text.** Every value is escaped on its way into
  markup, a link built from text goes through `safeUrl()`, and the server passes
  values to SQL as parameters and never in the SQL text. `pixi run test-injection`
  poisons every string in a project and audits every screen and export,
  `pixi run check-injection` refuses new ways of turning text into markup, and a
  server test fails on SQL built at run time. `pixi run test-markdown-render`
  renders the Markdown export with markdown-it-py (CommonMark and GFM, raw HTML
  refused and passed through) and audits the HTML, so the Markdown is checked
  as a reader's renderer reads it and not only as text.
  The page-policy and injection suites run in Chromium by default; set
  `TEST_BROWSER=firefox` or `webkit` to run them in another engine (CI runs
  both, because each engine enforces the policy itself). An unknown value is an
  error, not Chromium.
- **A security claim names its test.** Any sentence in the docs or the interface
  that asserts a security property gets a row in [Security claims](security-claims.md)
  with the test that enforces it, and `pixi run check-claims` fails if a quoted
  sentence is no longer where the row says it is.
- **American English** everywhere, checked by `pixi run check-spelling`.

## The documentation site

The pages are built with [Zensical](https://zensical.org), configured in
`zensical.toml`, with sources in `docs/`. The dashboard lives at
`docs/app/index.html` and is copied into the build verbatim, so the published
site serves the docs at `/` and the app at `/app/`.

```bash
pixi run docs-serve    # live preview at http://localhost:8000
pixi run docs-build    # writes ./site, and fails on a broken internal link
```

The GitHub Actions workflow at `.github/workflows/pages.yml` builds the site and
publishes it on every push to `main`. Enable it once under **Settings → Pages →
Build and deployment → Source: GitHub Actions**.

The checklist and metrics pages under `frameworks/` are generated (`pixi run
gen-docs`) and are not edited by hand.

!!! note "`--strict` does not validate the nav"

    The strict build fails on broken internal links, but a `nav` entry in
    `zensical.toml` pointing at a page that does not exist still builds
    cleanly. After changing the nav, check the rendered site.

## Linting and git hooks

Markdown is linted with [rumdl](https://rumdl.dev), configured in `.rumdl.toml`.
The `mkdocs` flavor is set there deliberately: Zensical shares Material for
MkDocs' Markdown dialect, and under the `standard` flavor an admonition block is
misread as an indented code block and reported as `MD046`.

Git hooks are managed with [prek](https://prek.j178.dev), a drop-in replacement
for pre-commit:

```bash
pixi run hooks-install   # install the git hook shims, once per clone
pixi run check           # run every hook over all files
pixi run lint-fix        # rumdl and ruff, fixing what they can in place
```

The same hooks run in CI, so CI cannot drift from what contributors get locally.

## Staying in step with CHAI

This project paraphrases CHAI's lifecycle, mirrors the Applied Model Card's
field names, and crosswalks both against OPTICA. None of that updates itself.

`.github/workflows/chai-updates.yml` runs weekly, compares
[CHAI's content repository](https://github.com/coalition-for-health-ai/responsible-ai-content)
against the snapshot in `data/chai-upstream.json`, and on any difference opens
a single issue, updated in place and not reopened weekly, assigned to the
repository owner, listing what moved and which files here derive from it.

```bash
pixi run check-chai         # compare now; exits 1 if upstream moved
pixi run check-chai-write   # accept the current upstream as the baseline
```

!!! warning "Two CHAI documents are not watched"

    The Assurance Standards Guide and the Applied Model Card template are PDFs
    with no machine-readable version feed. The check cannot see them, and says
    so in the issue it opens rather than implying full coverage. Check those by
    hand when the alert fires.
