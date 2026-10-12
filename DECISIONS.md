# Design decisions

Why the project is built the way it is, so the reasoning is not rediscovered
the hard way. Requirements say what must stay true; this file says why a given
approach was chosen and what was rejected. See [REQUIREMENTS.md](REQUIREMENTS.md).

How this file is used is set out in [CLAUDE.md](CLAUDE.md). In short: new code
follows an **Accepted** decision unless the user says otherwise, and a change
of mind adds a new entry that supersedes the old one. Never edit history.

Each entry has a stable ID. Never renumber or reuse one. A decision that no
longer holds is marked **Superseded by D-nn** and left in place.

**Status** is one of:

- **Accepted**: in force, and reflected in the code.
- **Proposed**: argued for and filed, not yet built or confirmed by the owner.
  Do not treat it as settled.
- **Superseded**: replaced. Kept for the history.

Entry shape: the decision, why, what was rejected, and where it comes from.

## Identity and the network

### D-01 Caddy, not nginx, as the identity boundary

- Status: Accepted
- Header deletion is a first-class verb in Caddy (`request_header -X`), where
  nginx can only send an empty header and silently does nothing if another
  `proxy_set_header` appears in a more specific block. SSE works by default.
  The whole config is one file.
- Rejected: nginx. Three ways to get the identity strip or SSE streaming subtly
  wrong, each with a failure that looks like an application bug.
- Source: `proxy/Caddyfile` header comment.

### D-02 The identity strip and set run in a fixed order

- Status: Accepted
- Strip the canonical headers, set them from the configured source, then strip
  the provider headers, reject if empty, forward. The provider strip must come
  after the set, because the set reads a provider header through a placeholder.
- Why it is written down: the strip once came first, which made every documented
  cloud deployment resolve to an empty identity and answer 401, invisibly, for
  months (#23).
- Source: `proxy/Caddyfile`; `tests/test_proxy_identity.py`.

### D-03 No password login

- Status: Accepted
- There is no user table, hash, registration form or token endpoint. Sign-in is
  the hospital's identity provider; the application learns who you are from one
  header.
- Why: offboarding works because disabling a user in the directory ends access
  everywhere at once; MFA is whatever the hospital already requires; password
  policy is the security office's job; and every credential feature is a thing
  to get wrong in a tool whose authentication surface is one header.
- Rejected: local accounts (the FastAPI `OAuth2PasswordRequestForm` pattern).
- Source: `docs/deploy.md`, "Why there is no password login"; closed issue #28.

### D-04 Network isolation, not code, is the boundary

- Status: Accepted
- The API publishes no host port. The only network `api` shares with anything
  internet-facing is `edge`, and the only other member is `proxy`. The database
  sits on an `internal: true` network with no gateway.
- Why: a header is trivially forged, and no code in the API can compensate for a
  reachable port. `TRUSTED_PROXY_CIDR` and `PROXY_SHARED_SECRET` are defense in
  depth, not substitutes.
- Source: `compose.yaml` header; `server/app/auth.py`.
- Known issue, fixed: `PROXY_SHARED_SECRET` was documented but no shipped config
  sent it, so enabling it made every request 403 (#61). See D-30.

### D-05 No `--proxy-headers`

- Status: Accepted
- uvicorn is not run with proxy-header handling, because that rewrites the peer
  address from `X-Forwarded-For`, which the client controls, and
  `TRUSTED_PROXY_CIDR` would then be checking the attacker's own claim.
- Source: `server/app/main.py` docstring.

### D-06 CSRF defense is `Sec-Fetch-Site`, and CORS is off

- Status: Accepted
- The proxy authenticates on its own session, which a browser attaches to
  cross-site requests too. CORS governs reading a response, not whether a delete
  happened. `Sec-Fetch-Site` is set by the browser and cannot be altered by
  script. A request without it is a non-browser client and is allowed.
- Source: `server/app/main.py`, `reject_cross_site_writes`; closed issue #9.

## Data

### D-07 The project document is opaque `jsonb`

- Status: Accepted
- One `jsonb` column rather than a column per field, so the browser's schema can
  grow without a migration. The API treats the document as opaque apart from the
  merge rule (objects merge key by key, arrays replace).
- Source: `server/migrations/001_init.sql`.

### D-08 The merge runs in Python under a row lock

- Status: Accepted
- A read-modify-write inside a transaction holding `SELECT ... FOR UPDATE`.
- Rejected: a recursive `jsonb` merge in PL/pgSQL. It would be atomic too, but it
  is a second implementation of a rule the browser already defines in
  `app/js/00-core/00-util.js`, and two implementations drift. PostgreSQL's `||`
  is not an option at all: it merges only the top level.
- Source: `server/app/routes.py`, `patch_project` docstring.

### D-09 Version history stores full documents, not diffs

- Status: Accepted
- A governance record is kilobytes and a committee edits it a few times a week.
  Reconstructing a point in time by replaying diffs is the operation you least
  want to debug while answering a regulator.
- Cost: unbounded growth with no retention policy (#54).
- Source: `server/migrations/002_versions.sql`.

### D-10 History survives deletion, with no foreign key

- Status: Accepted
- `project_version` deliberately has no foreign key to `projects`. "The record
  was deleted on this date, and here is what it contained" is itself an audit
  finding. The audit log cascades because it belongs to the live project.
- Consequence: DELETE does not erase content, which collides with erasure (#36).
- Source: `002_versions.sql`.

### D-11 Disposal is a tombstone

- Status: Accepted
- Purge empties `doc` and keeps the row, with `purged_at` and `purged_by`, rather
  than deleting. A vanished row is indistinguishable from a snapshot never taken.
  The trigger permits exactly that transition and nothing else.
- Source: `server/migrations/003_version_access.sql`.

### D-12 Each snapshot carries the access list it was written under

- Status: Accepted
- Otherwise deleting a project removed its live row, the access check was
  skipped, and every retained snapshot became readable by anyone. Deleting a
  restricted record widened access to it.
- Source: `003_version_access.sql`.

### D-13 An incarnation separates reused project ids

- Status: Accepted
- Project ids are caller-chosen and snapshots outlive their project, so a new
  project reusing an id collided with the old history. An incarnation column
  keeps the histories apart.
- Source: `server/migrations/004_version_incarnation.sql`; closed issue #10.

### D-14 Postgres is pinned to a major version

- Status: Accepted
- Postgres does not migrate its on-disk format. Moving 17 to 18 under a live
  volume makes the cluster unreadable and needs `pg_upgrade` or a dump and
  restore. A floating tag would do that on an unrelated `docker compose pull`.
- Source: `compose.yaml`.

## Operations

### D-15 The dashboard is built on the host, not in Docker

- Status: Accepted
- `pixi run build-app` generates `docs/app/index.html`, which the proxy mounts
  read-only. For the cloud, `proxy/Dockerfile` copies it in.
- Source: `compose.yaml`; `proxy/Dockerfile`.

### D-16 The rate limiter is in-process and per replica

- Status: Accepted
- With N replicas the effective ceiling is N times the limit. A shared counter
  would mean Redis or a database round trip per request, for a limiter whose job
  is to blunt a runaway client, not to meter an API. The hard protections are the
  body cap, the SSE stream cap and network isolation.
- Source: `server/app/main.py`, `SlidingWindowRateLimiter` docstring.

### D-17 Backups are `pg_dump` through the running server, encrypted

- Status: Accepted
- Never a copy of the volume's files, which gives a torn snapshot of a live
  cluster. `gpg --symmetric` because it is on far more machines than `age`.
- Source: `Makefile`, `backup` target.

### D-18 `make doctor` checks the password over the API's own path

- Status: Accepted
- `initdb` trusts the Unix socket and loopback, and only the appended
  `host all all all scram-sha-256` line asks for a password. A check using
  `-h 127.0.0.1` passes against a database it is locked out of. `-h db` is the
  only path that tests anything.
- Source: `scripts/doctor.py`; closed issue #26.

## Engineering

### D-19 Enumerated types, enforced by a ratcheting checker

- Status: Accepted
- A closed set of values gets a `StrEnum` (Python) or a frozen object
  (JavaScript). The existing bare-string uses are baselined and may only shrink.
- Why a custom checker and not ruff's `PLR2004`: it produced about 190 hits,
  mostly protocol constants and punctuation, and a noisy guardrail gets switched
  off. The ratchet means legacy code does not block work and new code cannot add
  to the problem.
- Why tests are exempt: a test may pin a wire value on purpose, and that is the
  test that proves a field was not silently renamed.
- Hardened after an adversarial review: 28 evasions were reproduced, 20 closed
  (inline `frozenset` and dict membership, `is`, hyphenated values, `Literal`
  aliases, `Field(pattern=...)`, JS `.includes`, backticks, comparisons wrapped
  across lines, and a pragma hidden in a string). The scanner reads real
  comments, so a pragma only counts in one.
- Hook scope: the first version fired only on Write and Edit, which skips most of
  what an agent working through Bash writes. It now also runs after Bash and
  checks every file git reports changed.
- Left uncaught on purpose: aliased constants, hoisted tuples, dispatch dicts,
  reverse `in`, `operator.eq` and lowercase JS state. Each would flag ordinary
  code in bulk. They are documented as blind spots rather than hidden.
- A file the checker cannot parse is reported as a violation, not skipped.
- Source: `scripts/check_enums.py`; [CLAUDE.md](CLAUDE.md).

### D-22 The storage mode is an enum, and each mode owns its labels

- Status: Accepted
- `Mode` (`app/js/00-core/30-state.js`) is a frozen object with `CONNECTING`,
  `LOCAL`, `API` and `ARTIFACT`. What a save tells the user is looked up in
  `SAVED_LABEL`, keyed by `Mode`, rather than chosen by a comparison.
- Why: `MODE` was assigned `"api"` in one file and compared with `"shared"` in
  another, so the server-backed mode reported "Saved in this browser" after every
  save (#55), contradicting the header beside it.
- An unknown mode falls back to a label that claims nothing ("Saved") rather than
  to one that claims the wrong place. Only `LOCAL` may mention the browser, and
  the test asserts it.
- The artifact mode's value changed from `"shared"` to `"artifact"`. Nothing
  outside the app read it.
- The header is the same shape: `MODE_LABEL`, keyed by `Mode`, with a text and a
  CSS class per mode, and a test that every mode has one and no two share a
  text. The artifact mode was labeled "Shared workspace", as the server was
  (#64), and now says "Claude artifact", saves to "this Claude artifact", and
  shows a standing notice. The notice states where the data lives and what the
  comparison in `docs/running.md` says it lacks, and says not to enter
  patient-identifiable information, as the browser-only banner does. That is
  about the artifact mode only: it says nothing about the server mode, whose
  classification is still open (R-21).
- Source: closed issue #55; R-04.

### D-20 Pre-commit is the only CI gate

- Status: **Superseded by D-23**
- `lint.yml` ran `prek` and nothing else, so no test ran on a pull request (#32).
  Kept for the history: until D-23, a property could not honestly be called
  "tested" on the strength of a test file CI never executed.

### D-23 CI runs every test, in four jobs, and a skip fails

- Status: Accepted
- `.github/workflows/test.yml` runs on every pull request and on main:
  **workflows** (unit: `test-workflows`, `test-enums`, and `actionlint`),
  **server** (the API against a PostgreSQL 17 service container), **browser**
  (the dashboard suites in Chromium) and **stack** (the proxy, then the Compose
  stack end to end). A fifth job, **tests passed**, depends on all of them and
  treats a skipped job as a failure, so one check name can gate a merge and a new
  job cannot be forgotten.
- Why three environments: what the server tests exercise IS the database (a row
  lock, a trigger), the dashboard needs a browser, and the identity handoff needs
  a real Caddy. A fake would test the fake.
- Why `REQUIRE_TESTS`: a skip exits 0. On a runner with no database 106 of 201
  server tests skip and the run is green. See R-24.
- Why the CI configuration has unit tests: the gap opened because a test could be
  added and left out of CI. `test_workflows.py` fails if any `pixi run test-*`
  task is not run by CI, if a test file has no task, if Postgres drifts from the
  version `compose.yaml` pins, or if a job loses its timeout. Each rule has a
  mutation test.
- Found by running it: `test_stack.py`'s browser section had been broken since the
  Content-Security-Policy shipped, because `wait_for_function` evaluates a string
  and the policy forbids `unsafe-eval`. It is fixed with a polling helper, which
  keeps the app under the policy it ships with rather than bypassing it.
- Branch protection is on. The owner enabled the `protect-main` ruleset, which
  requires a pull request and the `tests passed` check (pinned to the GitHub
  Actions app, so nothing else can satisfy it by posting a status of the same
  name) and blocks force-pushes and deletion. It has **no bypass actors**, so it
  applies to administrators too. Verified by trying to merge a throwaway PR
  twice, once with the check pending and once with it red; both were refused.
  The first attempt found that the ruleset had been saved with an EMPTY
  required-checks list, which enforced nothing, so verify it rather than
  trusting that it is on.
- It is a repository setting, not a file, so nothing in the repo can detect it
  being switched off (C-48). To check it: `gh api
  repos/OWNER/REPO/rules/branches/main`.
- Actions are pinned by tag, matching the existing workflows; pinning by commit
  SHA is #37.
- Source: #32; R-23, R-24.

### D-24 The server decides who signed a checkpoint, and when

- Status: Accepted
- `server/app/signoff.py` rewrites `gates.*.signedBy` and `signedAt` from the
  caller and the clock on create and on patch, mirroring what `append_log`
  already does for the audit log's `at` and `by`.
- Attribution follows the *decision*, not the claim. Changing a decision without
  sending any attribution would otherwise leave the record saying the previous
  person made the new decision. Setting or changing one attributes it to the
  caller; clearing one clears it; recording a periodic review attributes the
  reviewer.
- An unchanged decision is a **no-op, not an error**. The browser may re-send a
  whole gate, and a 403 would be read by the app as "your access changed" and put
  the user into read-only mode. Forgery is prevented by ignoring the claim, not
  by punishing it.
- Rejected: failing the request when a client sends a wrong `signedBy`. It turns
  an ordinary resend into a visible failure and teaches nothing the caller can
  act on.
- Only `signedBy` and `signedAt` are the server's. `by`, `date` and `rationale`
  are the committee's own words and stay as sent.
- A project created with pre-signed gates (an import) is attributed to whoever
  creates it. They are the one asserting it in this deployment; the original
  signer is not authenticated here and cannot be.
- With identity disabled (`REQUIRE_IDENTITY=false`) nothing is attributed, the
  same carve-out `access.py` makes, and `/api/health` reports it.
- Known limit: nothing signs the attestation cryptographically. The proxy
  identity is the trust anchor for everything here; making the sign-off match it
  is the fix, not raising it above it.
- Source: closed issue #31; R-09.

### D-25 The API assembles the database URL; compose passes the pieces

- Status: Accepted
- `compose.yaml` hands the API `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`,
  `POSTGRES_DB` and `POSTGRES_PASSWORD`. `build_database_url` in `config.py`
  assembles the URL and percent-encodes every part, so the choice of password is
  irrelevant. An explicit `DATABASE_URL` still wins, for managed instances whose
  URL carries `sslmode` or a Cloud SQL socket the pieces cannot express.
- Why: compose cannot percent-encode. `postgresql://u:${POSTGRES_PASSWORD}@db/..`
  broke on a `/` in the password, which the documented generator produces about
  half the time (measured: 47% of 20,000).
- A hand-written `DATABASE_URL` that cannot be parsed fails at startup with a
  message that names the likely cause and the way out, and **never echoes the
  password**. urllib's own message embeds the offending text, which here is the
  start of the password, and an error that quotes a credential ends up in a log
  aggregator.
- Rejected: telling operators to use `openssl rand -hex`. It shifts the burden to
  every operator and to every password manager, fixes nothing for a password
  chosen by a person, and leaves a first-run path that works only if you happened
  to read the right sentence.
- Rejected: rejecting such passwords in `preflight.py`. Correct passwords would
  be refused to protect a code path that should simply be correct.
- Source: R-25.

### D-26 The walkthrough video is hosted on the docs site, under a bounded cap

- Status: Accepted
- The source recording was 160 MB (2392x1462, 14.5 Mbps), over GitHub's 100 MB
  push limit and the repo's own 512 KB guard. A screen recording compresses
  extremely well: re-encoded to 1920 px wide, H.264, CRF 26, it is **7.5 MB** at
  the same 91 seconds, which also fits GitHub's 10 MB free-plan limit for inline
  video attachments.
- Hosted on the docs site (`docs/assets/`) and played with a plain `<video>`.
  Rejected: YouTube or Vimeo (a third-party iframe, against the spirit of R-05);
  a README drag-and-drop upload (a manual browser step, hosted by GitHub outside
  the repo and not versioned with it); a Release asset (works, but is not shown
  on the project's own page).
- Cost, accepted: about 7.6 MB added to git history, permanently. The repo was
  about 6 MB. Rewriting a public repo's history to remove it later would be worse
  than the cost, so this is the decision to revisit *before* adding a second
  video, not after.
- The repo-wide 512 KB limit is unchanged. Media under `docs/assets/` gets its own
  hook with a 10 MB cap, and `tests/test_docs_media.py` fails if that number and
  the page's assumption ever differ. An exception with a cap is a different thing
  from no limit.
- The poster is the portfolio overview, chosen because it is the most legible
  single frame. The video shows the browser's own chrome (a profile chip and an
  extension button), which is public now.
- Source: R-26.

### D-27 Claims are rows with a quoted sentence and evidence CI runs

- Status: Accepted
- `docs/security-claims.md` has one section per claim: the claim, one or more
  `Asserted in` entries (a file and the sentence **quoted**), a status, the
  evidence, and for anything not fully enforced the gap and its issue.
  `scripts/check_claims.py` verifies it.
- The quote is the key design choice. A claim list that only names tests rots
  silently when the doc is edited. Quoting the sentence means editing the doc
  fails the check until the row is reviewed, which is when "is this still true?"
  gets asked.
- Evidence must be something **CI runs**: a `server/tests` test, a `tests/` suite
  with a pixi task in `test.yml`, or a pre-commit hook. A test nobody runs is
  what #32 was.
- Four statuses, one of them `violated`. A claim the code does not back may stay
  in the inventory, with its issue, so the repository can say "this sentence is
  not true yet" in the open. The alternative, deleting the row or the sentence to
  pass, hides the finding.
- Rejected: scanning the docs for assertive words and requiring a row for each.
  It is noisy, and it would fail on ordinary prose. Finding a claim nobody wrote
  down is a judgment, which is what the CLAUDE.md rule asks of the author.
- The first run found a gap that became a test: the isolation the security model
  rests on had only a manual `make` target. `tests/test_compose_isolation.py` now
  asserts it against the real `compose.yaml` in CI. It also found that
  `preflight.py` has no tests (#77).
- Source: #68; R-19.

### D-28 Preflight reads `.env` exactly as compose does

- Status: Accepted
- `scripts/preflight.py` decides from `.env` alone, so the way for it to be wrong
  is to read `.env` differently from compose, and both mistakes failed open:
  an empty `SITE_ADDRESS=` (compose: the default, plain `http://:80`) was read as
  "not plain HTTP" and passed a bind to the whole network, and
  `POSTGRES_PASSWORD=abc # a long note` was counted at the length of the note while
  compose used `abc`.
- So it follows compose's rules: an empty value is the default (`${VAR:-d}`), an
  unquoted `#` after whitespace starts a comment, a quoted value keeps its `#`,
  and `export` is accepted. Its two defaults are constants, and a test fails if
  they drift from `compose.yaml`.
- Found by writing the tests (#77), not by reading the code: the gate had never
  been tested, and a gate nobody tests is a claim.
- Rejected: shelling out to `docker compose config` to read the resolved values.
  It would be exact, but it needs Docker and the variables set, and preflight must
  run first, before anything is up, on a machine that may have neither.
- Source: #77; R-08.

### D-30 One variable turns on the shared secret at both ends

- Status: Accepted
- `compose.yaml` hands `PROXY_SHARED_SECRET` to both the `api` and the `proxy`
  service, and `proxy/Caddyfile` sends it as `X-Proxy-Secret` with `header_up`.
  Setting it once in `.env` therefore turns the control on at both ends; unset,
  the API does not check and the proxy sends an empty value.
- Why: the API half existed (`_check_shared_secret`) and nothing sent the header,
  so the documented way to enable the control made every request 403 (#61). Two
  settings that must agree are one setting too many.
- `header_up` sets the header, which replaces a value the client sent under the
  same name. Do not add `header_up -X-Proxy-Secret` beside it: Caddy applies
  deletes after sets and the secret would vanish.
- It authenticates the proxy to the API. It is not a way for a caller to
  authenticate to the proxy, which the deployment guide used to suggest.
- The header name is fixed at the API's default, `X-Proxy-Secret`. Compose does
  not pass `PROXY_SECRET_HEADER`, so the two cannot disagree.
- Rejected: documenting it as an operator exercise (set it on the API, add a
  `header_up` to a Caddyfile you edit). That is the configuration nobody tested.
- Source: #61; R-07, D-04.

### D-31 `check-isolation` is a script with an exit code, not shell that prints

- Status: Accepted
- `make check-isolation` runs `scripts/check_isolation.py`. It asserts three things
  and exits non-zero on any failure: no host port on `api` or `db`, a refused
  direct connection to the API, and a forged `X-Auth-Request-*` that does not
  come back as the identity. The third tests for the forged value's absence,
  because the legitimate identity varies by deployment. Not running the stack
  is a failure, not a pass.
- Why: the shell version printed what it found and ended step 3 with `|| true`,
  so it exited 0 whatever it saw (#56). The docs told operators to put it in
  post-deploy automation, where the exit code is the only thing read.
- Why a script: so each decision is a function a test can break
  (`tests/test_check_isolation.py`), and so CI can run it against the real
  stack (`tests/test_stack.py`). A Makefile target is not evidence CI counts
  (R-19).
- Rejected: fixing the shell in place. It would be correct once and untestable
  after.
- Source: #56; R-07, R-19.

### D-32 The root `.dockerignore` is an allowlist

- Status: Accepted
- It excludes everything (`*`) and admits `proxy/Caddyfile` and `docs/app/`,
  the only paths `proxy/Dockerfile` COPYs.
- Why an allowlist: the context is the whole repository, which holds a
  password file, encrypted and plaintext backups, the git history and a
  licensed PDF. A blocklist guards against the secrets somebody thought of; an
  allowlist guards against the next file nobody did.
- Rejected: narrowing the context so the Dockerfile does not need the root
  (build the dashboard into `proxy/` first). It changes the documented build
  command to save a two-line file.
- Rejected: a CI check that a built image contains no `.env`. The image was
  never the problem; the context is, and that is what is tested.
- Source: #63; R-29.

### D-33 The backup passphrase goes through the environment and a mode-600 file

- Status: Accepted
- `scripts/backup_crypto.sh` takes `BACKUP_PASSPHRASE` from the environment,
  writes it with the shell builtin `printf` to a `mktemp` file created under
  `umask 077`, passes gpg `--passphrase-file`, and removes the file in a trap.
- Why: argv is world-readable on Linux, so `gpg --passphrase "$PW"` showed every
  local account the key to every record for as long as the dump ran (#41). Make
  made it worse: `$(VAR)` is pasted into the recipe text, which is the argv of
  `sh -c`, so even a line that never mentions gpg leaked it.
- Rejected: `--passphrase-fd 0` (stdin is already the dump stream in both
  directions); `--passphrase-fd 3` with a here-string (bash only, and the
  Makefile's recipes should not need to be); a gpg-agent or keyring (right for
  interactive use, awkward for a scripted restore).
- The Makefile runs under bash with `pipefail`, and `backup` chains with `&&`.
  Found while testing this: a failed `pg_dump` left an empty "encrypted" file and
  exited 0, and a restore with the wrong passphrase exited 0 having restored
  nothing, because a pipeline's status is its last command's.
- `scripts/doctor.py` gives docker `-e PGPASSWORD` (the name) and passes the value
  in the environment, for the same reason.
- Source: #41; R-13.

### D-34 The identity prefix is stripped once, and the template cannot undo it

- Status: Accepted
- `_normalized()` in `server/app/auth.py` strips `IDENTITY_STRIP_PREFIX` from the
  id, name and email after the plain and JWT parsers, so they cannot diverge.
  Preflight refuses an identity source that reads `X-Goog-Authenticated-User-*`
  unless the prefix is exactly `accounts.google.com:`. The template's bottom
  `IDENTITY_STRIP_PREFIX=` line is commented out, because compose takes the last
  value in a file and the active line re-emptied what the Google block set.
- Why both: the API fix makes the two paths agree, but only if the prefix is
  configured, and compose passes it through empty. The preflight rule stops the
  misconfiguration before any data is written (#35).
- Rejected: defaulting the prefix to Google's in `compose.yaml`. It would strip
  for every other front door too, silently rewriting ids that merely begin with
  that text.
- Rejected, for now: a `make doctor` check that finds stored ids not matching the
  running configuration. The documented count and repair SQL cover deployments
  that already did this; the check is a follow-up.
- Source: #35; R-30.

### D-35 The proxy runs as uid 65532, with a one-shot job to own its volumes

- Status: Accepted
- `user: 65532:65532`, `cap_drop: ALL` plus `NET_BIND_SERVICE`, `read_only`, a
  tmpfs `/tmp`, and a `proxy-perms` service that `chown -R`s `/data` and `/config`
  before the proxy starts.
- Found by running it, not by reading: the stock `caddy` binary has a file
  capability, so under `cap_drop: ALL` the kernel refuses to exec it ("operation
  not permitted") until `NET_BIND_SERVICE` is back in the bounding set, even
  though Docker lets any user bind port 80. Named volumes are root-owned, so a
  non-root Caddy logged `permission denied` on its autosave, instance id and
  locks, and an automatic-HTTPS deployment would have re-issued certificates on
  every restart.
- The upgrade case is the reason the fixer is recursive and has
  `DAC_READ_SEARCH`: volumes an earlier root-run proxy populated hold `0700`
  directories and `0600` keys. Tested with Caddy's local CA: the non-root proxy
  took over such a volume, served HTTPS, logged no permission error and reused
  the certificate.
- Rejected: leaving the proxy root with fewer capabilities. It works, and is
  the smaller change, but a container escape from the one internet-facing
  process would start as root, which is the finding.
- Rejected: `tmpfs` for `/data`. It runs, and loses the certificates.
- Rejected: baking a `chown` into a compose-built image. Compose bind-mounts the
  Caddyfile and dashboard so an edit needs no rebuild (D-15), and only the cloud
  image is built; there the `chown` is in `proxy/Dockerfile`.
- Limits are defaults, overridable through `.env`, sized for kilobytes of
  documents.
- Source: #50; R-32.

### D-36 Paging by header cursor, over the existing index, with a fixed cap

- Status: Accepted
- The response stays a bare JSON array, so the browser's `ApiStore` and any
  existing caller keep working. The total and the next cursor travel in headers
  (`X-Log-Total`, `X-Log-Next`).
- The cursor is `(at, seq)` as `<microseconds>.<seq>`. `project_log_project_at_idx
  (project_id, at DESC, seq DESC)` already serves `(at, seq) < ($2, $3)` exactly,
  and `seq` breaks ties so nothing repeats or vanishes.
- It is not an ISO timestamp. That first version carried `+` and `:`, a query
  string turns `+` into a space, and a client that forgot to encode it failed in
  a way that looked like corruption. Found by the test.
- `limit` is capped at 500 so no request makes the server build an unbounded
  list. The dashboard's *Show older entries* deepens one request (`?limit=120`,
  `180`, ...) rather than holding a cursor, because every change event refetches
  the newest page and would otherwise discard older pages already loaded.
- Rejected: changing the body to `{entries, total, next}`. Cleaner, and breaks
  every caller for no gain over headers.
- Rejected: `OFFSET`. It re-reads and discards all earlier rows on every page, and
  entries written between pages shift it.
- Source: #40; R-34.

### D-37 Two roles, with the owner's credential in a one-shot job

- Status: Accepted
- `python -m app.migrate` (compose's `migrate` service) holds the owner's
  credential, applies migrations and creates the restricted role; the API gets only
  the restricted role's. `APP_POSTGRES_PASSWORD` is required by `make up` and must
  differ from the owner's.
- Why a separate job and not "migrate at boot, then switch roles": a process that
  starts with the owner's credential still has it in its environment and memory.
  The compromise being defended against is exactly an attacker in the API
  process.
- Why not derive the restricted password from the owner's (an HMAC), which would
  need no new setting: the API would have to be given the owner's password to
  compute it, which is the thing being removed.
- Why `GRANTS` is explicit and nothing is inherited: a new table must name what
  the API may do to it. A test fails if one does not. `project_log` gets UPDATE
  (the purge redacts in place; its trigger permits only that) and no DELETE,
  because a project's log is removed by `ON DELETE CASCADE`, which runs with the
  table owner's rights.
- Found by running the whole suite as the restricted role: four tests exercised
  the triggers by issuing statements the restricted role is now refused earlier,
  by a privilege check. They connect as the owner, since the triggers bind the
  owner too; `test_roles.py` covers the role being refused.
- Rejected: row-level security or moving the merge into the database (the
  issue's own non-goals).
- Rejected: leaving it to the operator to grant by hand. That is the configuration
  nobody tests.
- Source: #48; R-35.

### D-38 A principals table, resolved only for people you can already see

- Status: Accepted
- The proxy asserts name and email on every request and the API discarded them.
  `principals` keeps them keyed by id, upserted as people sign in, throttled in
  memory (new, changed, or at most hourly) so a read is not a write. This is the
  issue's option 1.
- The lookup is not open. A signed-in user could otherwise walk a directory of
  every member of staff who ever signed in, so it answers for the caller and for
  people on a project the caller can read, and omits the rest. Omitted, not 403:
  an absent id carries no information about whether the person exists.
- The server-backed mode shows the id when it cannot name someone (the issue's
  option 4, as the fallback): it is what a reviewer can match against a
  directory, where "someone" tells them nothing. The artifact and browser-only
  modes keep "someone".
- Rejected: resolving against the IdP (Graph, Google Directory). More correct and
  a new outbound dependency and credential for a hospital to approve.
- Rejected: a display name typed when granting access. It drifts, and does not help
  ids that predate it.
- Cost, stated: a staff directory exists as a side effect. It is documented as
  personal data in `docs/deploy.md`, and erasing one person from it is not yet a
  supported operation (#57).
- Source: #39; R-36.

### D-39 Break-glass is an identity flag, with an unmissable record of each use

- Status: Accepted
- `Identity.emergency` is set from configuration and the proxy's asserted id
  alone. `access.require()` returns True when a request was allowed only because
  of it, and the route then records the use. The access lists are unchanged: the
  break-glass identity does not appear in them and cannot be removed from a
  project by one.
- Why record in the project's own log, as a system entry: the people who need to
  know are the project's owners, and the log is where they look; a system entry
  (`is_system`) is never redacted by a purge, so the evidence survives the very
  operation an emergency user might run. A separately-named event
  (`access.breakglass`) and a dedicated logger make it alertable.
- Why reads are throttled and writes are not: a dashboard refetches the log and
  versions on every change event, so an unthrottled read entry would write hundreds
  of rows per hour for one open tab. One per person per project per ten minutes
  still says it happened and who. Every use, throttled or not, is an
  `access.breakglass` security event. Revisit if a stricter reading of "every
  use" is wanted.
- Known limit: a delete's log entry goes with the project (by design, D-10/R-11).
  The warning and the tombstone remain. SSE streams are not widened: a break-glass
  identity is not in a project's audience, so it fetches rather than being pushed.
- Rejected: a role hierarchy or organization admin (the issue's own non-goal).
- Rejected: an `UPDATE` run by hand against the database. That is the privileged
  path the role model exists to avoid, and it leaves no record in the application.
- Source: #42; R-37.

### D-40 Bound the stream's life; do not build a session layer

- Status: Accepted
- The API stays free of sessions (D-03): identity comes from the proxy. The one
  place a revoked identity kept working was the event stream, which
  authenticates at attach. The API cannot re-ask the identity provider, so the
  fix is to **end the stream** on a timer and let the browser's reconnect do the
  re-authentication, which is exactly what the front door is for. This is the
  issue's option 2, adapted: it said to re-check the identity on the keepalive
  tick, and there is nothing in the API to check it against.
- The idle lock is a screen lock, off by default. It reloads rather than
  re-authenticating in place, because only the front door can authenticate. It
  flushes pending edits first.
- `SIGN_OUT_URL` is an allowlist (https, or a single-slash path), applied by the
  server at startup and again in the browser, because the server's answer is
  data and the value becomes a link. `javascript:`, `data:`, plain `http:` and
  `//host` are refused.
- Found while writing it: `ApiStore` set `es.onerror = () => {}`, so a stream
  that was closed for good (what a refused reconnect looks like) was swallowed
  and the page went on looking live. It now reports `stream_closed`.
- Rejected: building sign-in or a session in the API (the issue's own non-goal).
- Rejected, for now: closing the stream when the identity's *access* to a
  project changes. Events are already filtered by the audience at publish time.
- Source: #49; R-38.

### D-41 One security-event stream, JSON, tagged, and not the application log

- Status: Accepted
- `emit(SecurityEvent.X, message, **fields)` writes through a dedicated
  `chai.security` logger. The JSON formatter tags every line with its `stream`
  (`security` or `app`) so a sink can route and retain them separately (the
  issue's option 4) and an alert is a field match (option 1). The human-readable
  message is kept, so `LOG_FORMAT=text` and existing tests still read naturally.
- The security logger is held at INFO regardless of `LOG_LEVEL`, because an
  event that disappears when someone turns the application log down is not an
  audit.
- Values are `json.dumps`ed, so an identity with a quote or newline stays in its
  own string. Tokens and secrets are never fields: a token that cannot be
  decoded logs only the exception's class.
- The rate-limit event is once per client per window, or a flood of refused
  requests would become a flood of log lines, which is the denial of service
  again.
- It replaced the per-module loggers `chai.access` and `chai.emergency`, which
  could not be filtered together and whose names were in the docs as the thing
  to alert on. Those references now point at the events.
- Found while testing: `configure_logging` took a string and compared it to the
  enum by identity, so passing `"json"` silently selected the text format. It
  now coerces at its boundary (`LogFormat(fmt)`), which also rejects an unknown
  value.
- Rejected: a log shipper in the stack. A hospital has its own collector, and
  one more container that holds the security stream is one more thing to harden.
- Rejected: an audit table for these (option 3 of #33 is the read trail, which
  is a different thing). A database admin can alter a table; a sink outside the
  database is the tamper-evident copy. Both are in #33.
- Source: #38; R-39.

### D-42 A table and the security stream, in the transaction of the read

- Status: Accepted
- Both of the issue's recorded options: an append-only `access_event` table,
  written in the same transaction as the read (option 1), and the same fact as a
  named security event (option 2), which is the copy outside the database that
  an administrator cannot alter. Option 3.
- A list is one row carrying the ids it returned, not one row per project: the
  dashboard refetches the list on every change event, and a row per project
  would multiply that. The ids are in `detail`, so "did account X open project
  P" is still answerable.
- Fail closed: the insert is part of the transaction, so a read that cannot be
  recorded is a 500. An availability cost, taken on purpose: an audit control
  that silently stops recording is the failure this exists to prevent.
- Nothing is recorded for a refused request or a missing project. Nothing was
  disclosed; the refusal is `access.denied`.
- `source_ip` is `X-Real-IP` (the proxy's `{remote_host}`), else the peer. It is
  for correlation and the docs say so; nothing authorizes on it (D-05).
- Exports cannot be controlled, only recorded, because they happen in the
  browser. Rejected: moving export generation to the server. It would make the
  beacon a real control, and break the single-file, no-server dashboard (R-01)
  for every other mode.
- Rejected: an `UPDATE`-able table, or a foreign key to `projects`: the trail
  must outlive the record it describes (D-10).
- Source: #33; R-40.

### D-43 Verify a backup by restoring it into a throwaway container

- Status: Accepted
- The check is "does this dump restore into the database I run, and does it keep
  what it is for". So the throwaway is the production major version, read from
  `compose.yaml` so the test cannot drift from what runs, and the checks are the
  tables, the rows and the append-only triggers (a restore that drops them
  silently loses the guarantee, so a clean `psql` exit is not enough).
- Isolation: no network, data on tmpfs, a memory cap, a random name, removed in
  a `finally`. Nothing touches the live database; it needs no running stack.
- Each pipeline stage's exit status is read, because a pipeline's status is its
  last command's and a failed decrypt used to look like a successful restore
  (D-33).
- It cannot tell that a dump is recent or that an off-host copy is the same
  file: it checks the file it is given. The docs say so, and that the time it
  takes is the restore time to record.
- Rejected: restoring into the live stack's `db` service. A verification must
  not be able to damage production.
- Rejected: shipping a scheduler or an off-host uploader. Where backups run and
  land is the operator's decision; the gap was that nothing said it was one.
- Source: #52; R-41.

### D-44 Ask once, on the record, for something that cannot be checked

- Status: Accepted
- Encryption at rest of the host's disk cannot be verified from inside a
  container, so preflight does not pretend to: it refuses a production-shaped
  stack until the operator asserts it with a deliberately specific value (`=1`,
  not `true` or `yes`), in the spirit of the dev-auth acknowledgment. That turns
  "nobody thought about it" into "someone decided", which is what an addressable
  specification asks for.
- "Production-shaped" is a non-loopback bind using the stack's own volume. A
  laptop on loopback is not asked, and a managed database is the provider's
  storage.
- `make doctor` reports what the host shows (a `crypt` layer under the device)
  and says "cannot tell" when it cannot; the cloud provider may encrypt below
  that.
- Rejected: pretending to detect it. A check that sometimes reports "encrypted"
  from incomplete information is worse than none.
- Rejected: column- or document-level encryption (the issue's own non-goal).
- A non-loopback bind is also what the plain-HTTP rule keys on (D-28), so the
  two share one definition of loopback (`LOOPBACK_HOSTS`).
- Source: #47; R-42.

### D-45 Lock with hashes, pin by digest, scan what we build

- Status: Accepted
- The lock is `server/requirements.txt` (pip-compile, `--generate-hashes`,
  resolved in the image's own Python) and the project itself is **not**
  pip-installed: installing it would resolve build dependencies from PyPI, an
  unpinned step in a pinned build, and the runtime already sets
  `PYTHONPATH=/app`. The file is named `requirements.txt` so Dependabot's pip
  ecosystem updates it directly.
- Found by scanning rather than by reading: four HIGH findings in the API image
  were not our dependencies. They were libraries **vendored inside pip**, which
  shipped in the runtime venv where nothing uses it. Removing pip removed them.
  The same scan found 22 in the official `postgres:17` image's `gosu`, which we
  cannot patch.
- So the scan gate covers what we build (`--ignore-unfixed`, fail), and the
  official images are reported without failing: a CVE in someone else's image
  must not turn every unrelated pull request red. It is not part of `tests
  passed` for the same reason, but runs on every pull request so a finding is
  visible.
- Actions by SHA with the tag in a comment, which Dependabot understands. Trivy
  via its action, so Dependabot maintains it, rather than a floating `docker
  run`.
- `chai-updates.yml` pushed straight to `main`, which has been protected since
  D-23, so that step could no longer succeed. It now pushes a branch and opens a
  pull request, and dispatches `test.yml` on it, because a pull request opened
  with `GITHUB_TOKEN` does not start workflows and the required check would
  otherwise never appear. This has not run in Actions yet: the next scheduled or
  manual run is its first.
- The SLA in `SECURITY.md` is a set of **targets** the owner should confirm;
  they are a policy, and are mine only as a first draft. (Superseded by D-58:
  the owner declined them.)
- Rejected: signing and attestation (the issue's own non-goal); a `docker run`
  of Trivy by a floating tag; failing every pull request on third-party image
  findings.
- Source: #37; R-43.

### D-46 Report size, alert on the disk, do not guess a threshold

- Status: Accepted
- `make doctor` prints numbers and what they mean, and no pass/fail line. A
  fixed threshold would be wrong on every disk but the one it was written for,
  and a threshold that is sometimes wrong is a warning people learn to ignore.
  The control is an alert on the disk, which the docs say how to set per
  platform.
- The read trail (D-42) is included because a row per list is written on every
  change event for every viewer, which is the fastest-growing source in a busy
  deployment. I measured about 560 bytes a row at 12 projects, growing with the
  project count because a list stores the ids it returned.
- Rejected: coalescing rapid revisions (the issue's option 3). It changes the
  "one row per revision" invariant the history's value rests on, for a saving
  the disk alert already makes survivable.
- Rejected, for now: a retention policy with a disposal path (option 4). It
  needs the retention period decided first (#57).
- Source: #54; R-44.

### D-47 Leave the region to the reader and say it is their decision

- Status: Accepted
- Examples take the region from a variable the reader must fill in. A copied
  command with `<your-region>` left in fails loudly, which is the point: a
  default that works is a default that was never chosen.
- The residency section lists example EU regions and names what else can move
  data out of a region, and stops there. Whether a transfer mechanism is needed
  is a legal question this project does not answer.
- Rejected: swapping the US defaults for EU ones (it only moves the unmade
  decision); a region per provider table of "compliant" regions (a legal claim
  nobody here can back); a script that checks the region (the guide is prose
  and the resources are in the reader's account).
- Source: #58; R-45.

### D-48 State the position and ship the finder; do not invent a retention period

- Status: Accepted
- The floor the issue named is writing the position down and a way to find one
  person's data. Both are done. The retention period is not: it is an owner
  decision with legal weight (R-47, Open), so the page says it is undecided
  rather than inventing six years or any other number.
- The finder is SQL run through `psql` in the database container, like `doctor`,
  with the subject passed as a psql variable so it is quoted, never spliced. It
  reports locations and counts, not contents, so the tool does not itself produce
  a copy of staff data that someone must then protect.
- A test asks the database for every column named `*_by`, `by_id` or `actor` and
  fails if the query does not mention it. It already caught one the first draft
  missed (`project_log.purged_by`).
- Rejected: pseudonymizing staff identifiers (a significant redesign, worth it
  only if erasure requests are real); a DSR workflow in the app (the issue's own
  non-goal); a post-restore step that re-applies purges (needs a place for the
  list of purges that survives a restore, #116).
- Source: #57; R-46, R-47.

### D-49 Provenance comes from the same table as the header

- Status: Accepted
- The export text is built from `MODE_LABEL` and a sibling `MODE_PROVENANCE`, both
  keyed by `Mode`, so a new mode cannot ship without wording and the export cannot
  drift from what the header says. The JSON gets a `storage` object with the enum
  value, so a script reads the mode and never parses prose.
- The portfolio CSV gets a trailing "Stored in" column, not a comment row, so a
  spreadsheet's sort and filter still work. An empty portfolio exports no row to
  carry it; that is the one case it is silent.
- Rejected: a watermark on the PDF only (the HTML and Markdown are filed too);
  stating that a mode is "approved" or "safe" (R-21 is open, and it is a legal call).
- Source: #93; R-48.

### D-50 State the scope in every mode; do not build a detector to back it, yet

- Status: Accepted
- The owner chose option 1 on #34 over option 3 (state the policy and build a
  detector as the safeguard). The scope is the same in every mode, so one
  constant (`SCOPE_NOTICE`) is rendered by each mode's notice, and the server
  mode, which had none, gets one.
- The wording is an instruction ("never enter"), not an assurance ("contains no
  patient data"), because nothing checks the free-text fields. A mistake is
  corrected by an owner's purge, which the server notice names.
- The HIPAA Security Rule citations in `docs/deploy.md` (encryption at rest,
  backups, emergency access) were written while the scope was open. With no
  ePHI in scope they describe good practice the controls follow, not a legal
  requirement on this system; rewording them is a follow-up, not part of this.
- Rejected: option 2 (PHI in scope; a BAA and required standards) and option 3
  (a detector as the safeguard), by the owner's decision. PHI detection (R-22)
  stays open.
- Source: the owner, on #34; R-49.

### D-51 Scan for labeled identifiers on demand; no model, no sidecar

- Status: Accepted
- The owner's decision. With patient data out of scope (R-49), what is wanted is
  a way to notice a mistake, not a control that makes patient data acceptable.
  Rules catch the shapes a paste leaves (an SSN, a labeled MRN or date of birth)
  with almost no false alarms; a model catches names and dates, which a
  governance record is full of, and would flag nearly every record.
- The scan reads through the database container like `make subject-access`, so
  it covers revisions and audit entries a live read cannot reach. Purged content
  is skipped: it is already destroyed.
- It never prints the matched text, because a report that quotes it is a second
  copy in a terminal or a ticket. Location, kind and the revisions are enough to
  find it.
- The false-positive rate was measured on this corpus: the dashboard's ten
  sample projects, 1,365 strings, produce no match, and a test keeps it so.
- Rejected: the OpenMed sidecar (#65) and Croissant de-identification (#67), by
  the owner's decision; surfacing the scan in `make doctor` (a scan of every
  revision is not a quick health check).
- Supersedes: D-21.
- Source: the owner; #66; R-50.

### D-52 Keep the citations, change what they claim

- Status: Accepted
- The HIPAA Security Rule standards stay cited, because they are the vocabulary
  a hospital security team reviews against and they explain why each control
  exists. What changed is the claim: "follows the practice of", not "is
  required". The one sentence that tied encryption to a PHI breach rule (45 CFR
  164.402) is gone from the docs and from `make preflight`'s refusal, which now
  names what a lost disk does expose: the review records and staff data.
- Code comments and test docstrings that cite a standard as the reason a control
  exists are left as they are: they explain intent, and they are not read as a
  statement to a deployer.
- Rejected: removing the citations (it would hide why a control exists);
  weakening a control because the rule no longer binds (the sign-off record and
  staff data still need it).
- Source: #121; R-49, R-51.

### D-53 Search the text the browser already holds; no search endpoint

- Status: Accepted
- The owner asked for a dashboard search that finds every project containing
  some text and links to it (#57). It runs over the projects the browser has
  already loaded, which are exactly the ones the viewer may open, so it adds no
  read path, needs no new server route or read-trail action (R-40), and works
  the same in all three storage modes.
- A name also searches the ids it belongs to, because the lists that matter for
  a subject access request (access, sign-offs, last changed by) hold ids.
- The cost is coverage: only current versions. Earlier revisions and the audit
  log are server-side and reachable with `make subject-access`; the UI says so
  rather than implying the search is complete.
- Rejected: a server-side full-text endpoint over history (a new read path over
  every revision, with its own access rules and read-trail rows, for a need the
  administrator command already meets).
- Source: the owner, on #57; R-46.

### D-54 Pseudonymizing staff identifiers is deferred

- Status: Accepted
- The owner's decision on #57's option 3, 2026-10-08. Storing opaque ids and
  breaking the mapping on erasure would leave every existing revision and log
  entry holding real ids, because they are append-only (R-10), unless history
  were rewritten under an exception to it. Names typed into free-text fields
  would survive either way. The issue's own condition for doing it, erasure
  requests expected to be real, has not been met.
- Erasure stays as `docs/privacy.md` states it: content can be purged, and the
  fact of who did what is kept.
- Revisit if erasure requests become real.
- Source: the owner, on #57; R-10, R-46.

### D-55 The purge ledger lives outside the dump: the live database, then the log

- Status: Accepted
- A purge is recorded in the rows it changes, which is exactly what an older dump
  overwrites. So the ledger has to come from somewhere the dump does not: the live
  database just before the restore (the ordinary case), or the security log, which
  is shipped off the host (the case where the database is what was lost).
- A purge empties every revision of one incarnation and redacts every entry of
  the project's log, so one ledger line is enough: project, incarnation, moment,
  person, and the last revision and entry reached. Re-applying matches on those,
  and on time, because a restored sequence can reuse a number.
- The re-apply is the same transition the purge made, so the append-only
  triggers (R-10, R-12) allow it unchanged; nothing is relaxed for it. It runs as
  the owner, as `make restore` already does.
- The ledger names who purged what, so it is written mode 600 into `backups/`.
- Rejected: a ledger written at backup time (it holds only purges older than the
  newest dump, which a restore of that dump already has); re-applying from the
  restored database itself (the purge is what the old dump lacks).
- Source: #116, #57; R-53.

### D-56 Count from retirement, and defer to the organization's schedule

- Status: Accepted
- The owner accepted the recommended periods (R-54). The governance record's
  clock starts when the AI solution is retired, because the record's job is to
  show who reviewed a tool still in use. Six years follows the HIPAA Security
  Rule's documentation period, the figure hospital compliance teams already work
  to, and covers most malpractice limitation periods.
- The read trail and the security log defer to the organization's existing
  audit-log and security-log policies, which already exist and are set by the
  people who answer for them.
- Recorded as documentation first. Automatic disposal is a separate decision,
  because it is the first scheduled deletion from append-only tables (R-10).
- Rejected: a period counted from creation (it could delete the sign-off of a
  tool still in use); a single period for every table (the read trail and logs
  have their own owners and policies).
- Source: the owner, on #57; R-54.

### D-57 The confusable-character check is removed

- Status: Accepted
- The owner's instruction, 2026-10-08. `scripts/check_homographs.py` failed any
  file holding Greek, Cyrillic, Armenian or fullwidth characters, because one
  link once spelled a word with a Cyrillic "o". The dashboard is gaining
  translations (#80), and a Simplified Chinese catalog uses fullwidth
  punctuation as a matter of course, so the check would have blocked the
  languages the owner chose. It also had no tests of its own.
- What it caught is no longer checked anywhere: a lookalike letter in a URL or
  an identifier in the docs or code.
- Source: the owner; #80.

### D-58 The security policy promises no response or fix times

- Status: Accepted
- The owner's decision, 2026-10-08: the project has one developer and cannot
  commit to the targets D-45 drafted (acknowledge in 5 business days, fix a
  critical in 14). A target a reporter or a hospital reads is a commitment,
  whatever it is called, so the policy states none. It keeps how to report
  privately, that remediation goes in order of severity, what is in scope, and
  that a deployment needing a response commitment must get it from whoever
  operates it.
- Supersedes the SLA bullet of D-45 (the rest of D-45 stands).
- Source: the owner.

### D-59 Embedded catalogs, English warnings until reviewed, and a ratchet

- Status: Accepted; its "exports stay English" and its rejection of translating
  the framework content are superseded by D-60
- Languages and defaults are the owner's (R-55): the six languages plus Russian,
  Simplified Chinese for Mandarin, a per-browser choice, machine-drafted
  translations, and safety-bearing text in English until reviewed.
- Catalogs are JSON files the build embeds as one frozen object, because the
  dashboard is one file that must work from disk and as an artifact (R-01).
  `t()` returns text and callers escape it; a catalog never holds HTML, so a
  translation cannot inject markup. `tHtml()` places markup the caller built.
- Plurals use the browser's `Intl.PluralRules`; the checker's table of the
  forms each language needs is tested against it, so neither can drift.
- The English text of a mode stays in `MODE_LABEL` for exports, and the header
  uses a catalog key: exports are a record and stay stable.
- Converting every screen at once was not done. A pseudo-locale counts the text
  still hard-coded on three screens, and the baseline may only shrink, like the
  enum ratchet (D-19).
- The spelling check skips catalogs other than `en.json`, because a word that is
  British in English can be correct in another language (German, French).
- Rejected: fetching catalogs at run time (breaks R-01); an i18n library (R-05,
  and size); translating the framework content now (third-party text with
  attribution terms, its own plan).
- Source: the owner, on #80; R-55.

### D-60 Reports follow the reader; framework content is translated, marked

- Status: Accepted
- The owner's decision, 2026-10-08, on both open parts of #80.
- **Exports.** The HTML, PDF and Markdown reports are written in the reader's
  language and name it (`<html lang>`, a "Language" line). The JSON and CSV
  exports stay English: scripts and the Croissant exporter read their keys and
  values. The provenance note and the report footers are safety-bearing, so
  they stay English in a report until a reviewer is recorded, like on screen.
- **Framework content.** The CHAI criteria, stages, checkpoints, model card
  fields and metric categories, the OPTICA questions, and the CHAI metric names
  are translated, machine-drafted, with a note on each translated framework
  screen that the wording is an unofficial translation. The CHAI metric text is
  CC BY 4.0, which permits translation with attribution and an indication of
  changes, and the note says it was translated. Values a record stores (a
  checkpoint decision, a metric category, a metric's name) stay English, so a
  record does not change with the language of whoever filled it in.
- Rejected: a per-export language choice (a second control for the same thing);
  leaving framework content English (a translated interface around English
  criteria is the hardest of both worlds to read).
- Supersedes: D-59's "exports stay English" and its rejection of translating
  the framework content.
- Source: the owner, on #80; R-55.

### D-61 The documentation site stays in English

- Status: Accepted
- The owner's decision, 2026-10-08, on #80. The nine pages under `docs/` are
  written for the people who deploy and run the software, and stay English. Only
  the dashboard and its reports are translated (R-55, D-60).
- Rejected: translating the docs (nine pages that change with the code, for a
  readership that already works in English, at the cost of keeping seven copies
  true).
- Source: the owner, on #80.

### D-62 Disposal is a purge, run by an operator, stopped by a hold

- Status: Accepted
- The owner's choices, 2026-10-08, on #57, each the recommended option:
    - disposal reuses the purge, so a tombstone stays (R-12); only the read
      trail loses rows outright;
    - it reports first and applies on request (`make dispose`, `APPLY=1`),
      scheduled by the organization, not by the server;
    - a hold is per project, placed and lifted with a reason, and append-only.
- Built in SQL (`008_retention.sql`), not in the API: the database enforces it
  whoever is connected, the API's role is refused it, and the read trail's
  trigger checks the period itself, so even the owner cannot delete a row too
  young without first changing the recorded policy.
- The periods live in a one-row `retention_policy` table rather than in the
  code, because R-54 makes the organization's schedule take precedence. A
  change is stamped with who and when.
- The clock is the later of the retirement date and the last change, so a
  typo'd or future date, or a later edit, keeps a record longer, never shorter.
- An owner of a project places and lifts a hold on its setup page, or through
  `POST /api/projects/{id}/hold` with a reason. The reason stays with the hold
  and is shown only to owners; the project's history says only that a hold was
  placed or lifted, and the security log names who, not why.
- Disposal of `principals` was added after, by D-64.
- Rejected: deleting every row (leaves no evidence the record existed, against
  R-12); a timer in the server (a wrong date or setting deletes with nobody
  looking); one global hold switch (one dispute would freeze every project).
- Source: the owner, on #57; R-56.

### D-63 Right to left by logical properties and isolated user text

- Status: Accepted
- The owner added Hebrew on 2026-10-08, on #80, the first language written right
  to left; the proposal had asked for this to be decided before it was a
  retrofit.
- **The layout mirrors itself.** `<html dir>` follows the language
  (`localeDir()`), and the stylesheet uses logical properties
  (`margin-inline-start`, `text-align:start`, `inset-inline-start`, the
  `border-start-end-radius` family); the inset accent shadows read a `--dir`
  variable. `check-i18n` refuses a physical left or right, an uneven
  four-value `margin`/`padding`/`border-radius`, or a one-sided inset shadow,
  in the stylesheet or a script's inline style; `rtl-ok: <reason>` excuses one
  that is symmetric or off screen.
- **Text keeps its own direction.** What a person typed is shown through
  `bdi()`, a `<bdi>` that takes its direction from its own text, and fields use
  `unicode-bidi:plaintext`. English that `t()` shows in place of a translation
  (an unreviewed warning, a missing key) is wrapped in a left-to-right isolate
  in a right-to-left page. Without these, an English name in a Hebrew page
  shows its period at the wrong end.
- Rejected: detecting every paragraph's direction from its first strong
  character (Hebrew strings that begin with "CHAI", "MD5" or "OPTICA" would be
  laid out left to right); a separate right-to-left stylesheet (two layouts to
  keep in step).
- The pseudo-locale probe skips `<bdi>`, since it holds data, not interface
  text; the counts it reported had been mostly data.
- Source: the owner, on #80; R-55.

### D-64 A person's name goes when nothing retained names them

- Status: Accepted
- Applies the owner's period for staff names and emails (R-54): "while active,
  then as long as a retained record refers to them". There is no offboarding
  signal, so "no longer active" is read as "not signed in for the read-trail
  period", and "refers to them" as any mention of their id or email, matched as
  a case-insensitive substring, in any column that records who did something or
  inside any document, log entry, read detail or hold reason
  (`principal_referenced()`, `009_principal_disposal.sql`).
- Both readings err toward keeping: a prefix match keeps both people, and a
  purge keeps a revision's author (R-12), so whoever changed a retained record
  stays listed as long as it does.
- It runs inside `dispose_due()`, after the read trail, so a person known only
  from reads disposed of in the same run goes in that run, and the
  `disposal_run` row counts them.
- A test lists every column named like `*_by`, `by_id` or `actor` and fails if
  `principal_referenced()` does not read it in that table's clause.
- Rejected: deleting on last sign-in alone (would strip the name from records
  that still show what the person did); keeping principals forever (against
  the owner's period).
- Source: R-54, #57.

### D-65 Documentation by audience, with the executive case made honestly

- Status: Accepted
- The owner asked for the docs to explain why the project exists and what gap it
  fills, for a hospital CEO, and for the rest to be rewritten from the current
  code (R-57).
- **By audience.** `docs/index.md` is the executive case, `docs/adopting.md` the
  decision (cost, people, infrastructure, risks, how to try it), `docs/guide.md`
  the committee's walkthrough, `docs/self-hosting.md` and `docs/deploy.md` the
  operator's, `docs/privacy.md` the privacy officer's and `docs/developing.md` the
  developer's. Operator and developer material that shared a page were split so
  each reader finds theirs.
- **The pitch states its limits.** The project is open source with one
  maintainer, no support contract and no hosted service, and the repository holds
  no commercial offer. So the executive pages make the case for adopting and
  running it, and say what that costs and what it does not give, rather than
  inventing a price, a support term or a customer.
- **What was kept.** The cloud recipes in `docs/deploy.md` stay as they were
  apart from sentences the code had made false (disposal, the staff directory and
  the read trail): their provider settings are unverified and rewriting them
  would invent confidence. The crosswalk, the framework pages and the generated
  checklists are research and generated content, not descriptions of the code.
- Rejected: one long README for every reader (the executive case and the
  `make` commands do not belong in the same scroll); a pricing or services page
  (nothing in the repository supports one); translating the docs (D-61).
- Source: the owner, this session; R-57.

### D-66 The SHA-256 is computed in the page, and verified by a second implementation

- Status: Accepted
- The owner chose to make the notice true (#150) rather than remove it.
- **Synchronous, in the page.** The browser's `crypto.subtle` is asynchronous, and
  absent on some `file://` origins, while every export is built as one synchronous
  string (the PDF prints `exportHTML()`). So SHA-256 is written in
  `app/js/00-core/12-hash.js` beside the MD5 it already had, with its constants
  derived from the primes as FIPS 180-4 defines them.
- **Checked against something that is not the same code.** The test compares
  the digest with Python's `hashlib` on every padding boundary and on non-ASCII
  text, and `examples/load_export.py` recomputes both digests from an export file
  in Python, written from the rule rather than the JavaScript. A bug in either
  side, including a difference in how keys are ordered or text is escaped, fails
  the test.
- **What it covers.** The project record including its id, as canonical JSON,
  so the MD5 is the one the setup page shows. The id is exported as `project_id`
  so a reader can recompute; import ignores it.
- Rejected: an asynchronous export path (every caller and test would change for
  no gain); a signature (that needs a key, which this tool does not hold);
  putting the digest in each audit entry (the entry already carries the MD5).
- Source: the owner, on #150; R-58.

### D-67 Poison everything and look, rather than trace which fields are safe

- Status: Accepted
- The owner asked for a scan and a guard (#155).
- **A test that poisons the document.** `tests/test_injection.py` takes a
  populated project and replaces every string in it with each of 24 payloads,
  including the fields an import can fill with anything (statuses, decisions,
  dates), an extra key named like the payload, the change log, people's names,
  the search box, saved state, the legacy record, the litigation-hold history
  and an imported file. It renders every screen the project has and every
  export, and checks that nothing ran, no payload markup was parsed, and the
  text is still there as text. Because it poisons whatever the document holds, a
  field added tomorrow is covered the day it is added. A mutation removes the
  app's escape and the test must fail.
- **A ratchet for the rest.** `scripts/check_injection.py` refuses `eval`, `new
  Function`, `document.write`, `insertAdjacentHTML`, a `srcdoc` or `outerHTML`
  assignment, a `javascript:` URL, a string timer and an `on*=` handler in
  markup, and counts unescaped attribute interpolations and `innerHTML`
  assignments per file so a new one fails. The existing ones were each read and
  come from code. It is a tripwire, not proof: a value escaped for the wrong
  context is invisible to it, which the payload test covers by behavior.
- **On the server:** an AST test fails on any SQL call whose first argument is
  not a constant string, except the two named places that run trusted DDL, and a
  database test round-trips hostile text. A NUL character is a 422.
- Rejected: a sanitizer library (R-01 allows no dependency, and escaping on
  output is the right tool for text that is never meant to be markup); a
  taint-tracking analysis of the JavaScript (more machinery than the app, and
  the poison test finds the same bugs by running the code).
- Source: the owner, on #155; R-59.

### D-68 The proxy's policy names the page's script by its hash

- Status: Accepted
- The owner asked for the open issues to be fixed (#154).
- **Generated, because the hash changes with every build.**
  `scripts/build_app.py` computes the SHA-256 of the page's one inline script
  and writes the policy header to `proxy/csp.caddy`. The Caddyfile imports it,
  compose mounts it and the cloud image copies it. The build refuses a page with
  more or fewer than one inline script. The existing build-app hook already
  fails when a generated file differs, so the policy cannot go stale.
- **No `'unsafe-inline'` for script.** An injected `<script>`, an `on*` handler
  or a `javascript:` link is refused by the browser even if the page failed to
  escape something. Style stays inline, because the app styles itself.
- **The exported report has a policy of its own**, inline in the file: no script
  at all and no outside resource, so a report opened from disk or a mail
  attachment cannot run one either.
- **Where it applies.** The proxy, which is the shared workspace. The GitHub
  Pages copy cannot set headers, and a policy meta tag in the page would also
  bind the Claude artifact host, which injects its own script, so neither gets
  one.
- Rejected: a nonce (the page is one static file served the same way everywhere,
  so there is nothing to template per request); a hash maintained by hand in the
  Caddyfile (it would break the dashboard on the first build after someone
  forgot).
- Source: the owner; R-16, R-59.

### D-69 The Claude artifact mode is removed

- Status: Accepted
- The owner's decision, 2026-10-08: "I just need the true deployed app and the
  example http webpage." The dashboard no longer runs as a Claude artifact.
- **What went:** `DbStore`, the `ARTIFACT` mode and its header, saved-label,
  provenance and notice strings in all eight languages, the artifact's
  downloads and read-only handling, the copy-it-yourself fallback for views
  that cannot download, the artifact column of the comparison tables, claim
  C-13 (which asserted the artifact's identity and sign-off, and rested on a
  runtime outside the repository), and the tests that drove a stand-in for the
  artifact runtime.
- **What it bought:** the page can carry its own Content-Security-Policy. The
  artifact host injected script of its own, which a policy in the page would
  have blocked, so the page had to go without one there. With the host gone,
  the build writes the same policy into the page as a meta tag (the proxy still
  sends it as a header), which also covers the example page and a copy opened
  from disk. Issue #157 closed with it.
- **Compatibility:** exports from earlier versions may carry
  `storage.mode: "artifact"`; the schema still accepts it and says it is no
  longer produced.
- Not done: removing `artifact` from old DECISIONS and REQUIREMENTS entries
  (history stays; R-60 says what changed).
- Supersedes: R-01 (by R-60). The artifact parts of D-22 (the `Mode` enum
  listed `ARTIFACT`) remain as history; D-22's enum now has three members,
  `CONNECTING`, `LOCAL` and `API`.
- Source: the owner; R-60.

### D-29 Redaction is defined once, in SQL, and the trigger verifies the result

- Status: Accepted
- `project_log_redacted(entry)` is the single definition of what a redacted
  entry is: a **whitelist** of `at`, `by`, `hash`, the changed field's `path`,
  and a fixed marker for the text. The trigger on `project_log` permits an
  UPDATE only if the new entry **equals that function applied to the old one**,
  so it checks what was done, not what the caller says it did. A partial
  redaction, one that keeps `change.to`, a change to when or who, and un-purging
  are all refused.
- Why a whitelist: the log stores arbitrary fields the client sends, and the
  client writes the values into the prose (`text`) as well as `change.from/to`.
  The issue named only `from` and `to`; a blacklist of known fields would have
  left the identifier readable in the prose.
- "Already purged" and "written by the system" are **columns**, set only by the
  server. Were they keys inside the entry, a client could send `{"purged":
  true}` and make an entry carrying the value survive every purge.
- Deletion writes `project_deletion` (append-only, no content, no foreign key,
  so it outlives the row) inside the delete transaction. A refused or failed
  delete writes nothing.
- **Deleting is still not erasure,** by design (D-10): the history is kept so
  the record can be audited. The dialog says so, and offers the destroy step as
  a separate choice, run first so a failure does not delete the project.
- Rejected: redacting only `change.from/to` (leaves the prose); blacklisting
  known sensitive fields; making the purge delete the rows (a vanished row looks
  like a snapshot never taken, D-11); letting deletion cascade-delete the
  history (an audit trail that vanishes with its subject is not one).
- Not done: removing the identifiers of the people who made changes
  (`created_by`, `changed_by`, `by_id`), and reaching backups. Both are
  documented, and the first is #57.
- Source: #36; R-12, R-27.

## Proposed, not yet decided

### D-21 PHI detection runs in an opt-in sidecar, advisory only

- Status: **Superseded by D-51** (was Proposed: #65, #66, #67)
- The detector (OpenMed) cannot be bundled into a single-file dashboard (R-01),
  and adding it to the API image would add gigabytes and a large CVE surface. A
  separate container, absent by default, behind `POST /api/phi-check`.
- Advisory, never blocking: a governance record says "patient" constantly. The
  acknowledgment is itself recorded.
- Must not claim "no PHI detected". OpenMed publishes no aggregate F1, precision
  or recall, and says a clean result is not a compliance claim.
- Waits on R-21: the data classification is the owner's decision first.

### D-70 Evidence references are an object keyed by id, and the file is a fingerprint

- Status: Accepted
- The owner asked whether evidence could be uploaded (PDFs) and decided against
  it: "forget about the upload", with links to external sites allowed (R-61).
- **Stored at `<item>.refs`, an object keyed by reference id.** The merge rule
  replaces arrays wholesale, so an array would lose one of two references added
  at the same time; keyed by id, both survive, and removal is a `null` at one
  key. `server/tests/test_refs_merge.py` shows both against PostgreSQL.
- **A file is a name, a size and a SHA-256, computed in the browser.** It uses
  Web Crypto when the page has it and the page's own SHA-256 (D-66) when it does
  not, because Web Crypto is absent on plain http. The two are tested against
  `hashlib` at every padding boundary. The cap is 256 MB because the file is read
  into memory in one piece; hashing in chunks needs the page's own SHA-256 to be
  incremental, which it is not.
- **A link goes through `safeUrl()`**: http and https only, no credentials, no
  whitespace or control characters, 2,000 characters at most. The reader of a
  stored record runs it again, so a record written by something else (an import,
  an API call) cannot carry `javascript:` into a link.
- **Markdown links are `[title](address)` with parentheses encoded**, not the
  angle-bracket form, because `encodeURIComponent` leaves parentheses alone (a
  bug the test found) and a reader of the file cannot tell `(<url>)` from raw
  HTML.
- **Rejected:** uploading files to the server (this tool would then hold documents
  that may name a patient, with retention, disposal and breach duties it was
  designed to avoid); an array of references (loses concurrent adds); fetching a
  link to check it or to preview it (an outbound request on the reader's behalf,
  against C-80).
- Source: the owner; R-61.

### D-71 Notes are parsed to a tree, and both outputs are written from it

- Status: Accepted
- The owner asked for formatting in the notes field, with links to outside sites
  allowed, and for protection against injection. The subset is bold, italic,
  flat lists and http(s) links (R-62).
- **One tree, two writers.** `mdParse()` builds blocks of inline runs. `mdHTML()`
  escapes every run; `mdInlineMarkdown()` writes the subset back with every other
  special character escaped. Neither looks at the source again, so the structure
  of the output is the parser's, whatever the text holds. The alternative, a
  library that renders Markdown to HTML and then a sanitizer, was rejected: it
  is a third-party dependency in a page that must be one file (R-60), and
  sanitizing after the fact is the pattern whose misses are the standing source
  of XSS.
- **Not a full Markdown.** No nesting of lists, no tables, no headings, no
  images, no autolinks, no raw HTML. Each one is either a way to carry markup or
  a request an outside server (an image) when a record is read. A line that looks
  like one is shown as text.
- **The address is always shown.** A link written `[safe words](https://elsewhere)`
  is the standard disguise for a phishing link, so the report prints the address
  beside the words.
- **Bounded.** The first 50,000 characters are parsed and the rest is shown as
  plain text; nesting stops at three levels; every pattern is anchored at the
  position being read. `tests/test_markdown.py` times input built to make a
  parser crawl.
- **Scope.** Evidence or notes (CHAI and OPTICA) and a checkpoint's rationale.
  The model card's long fields, the decline reason and the setup notes stay plain
  text for now.
- Source: the owner; R-62.

### D-72 The cloud proxy rebuilds Caddy with a patched Go, until upstream does

- Status: Accepted (as a fix to a failing required check; revert condition
  below)
- The image scan began failing on 2026-10-09 with no change in this repository:
  the official `caddy:2` image of 2026-10-05 (Caddy v2.11.7) is built with Go
  1.26.8, which has two HIGH denial-of-service fixes pending in `net/http` and
  `crypto/tls` (CVE-2026-78667, CVE-2026-97031). A newer scanner database also
  flags `golang.org/x/net` v0.59.0 (CVE-2026-78669). The proxy is the process
  every request reaches first, and the newest official image was the one pinned.
- **What changed:** `proxy/Dockerfile` builds the same Caddy release from source
  in the official `caddy:2-builder` image (Go 1.27.2), with `golang.org/x/net`
  raised to v0.60.0 and the standard modules only, and copies the binary into the
  official `caddy:2` runtime image. Both images are pinned by digest.
  `tests/test_proxy_image.py` builds and runs it and checks it is the release
  `compose.yaml` pins with the same modules, and that a different release is
  noticed.
- **Rejected:** a `.trivyignore` entry (it weakens the check that found a real
  issue, which the repository rules forbid); waiting for upstream (every pull
  request would stay blocked on `tests passed`).
- **Not changed:** the local compose stack still runs the official image, which
  the scan reports without blocking; it is reached only from the network an
  operator chooses.
- **Revert when** an official `caddy:2` is built with a fixed Go and a fixed
  `golang.org/x/net`: drop the build stage and the `COPY --from`, and remove
  `test-proxy-image` with it.
- Source: GitHub Actions run 37977974877 (the image scan on PR #165).

### D-73 The policy and injection suites run in three browser engines

- Status: Accepted
- The page's Content-Security-Policy is enforced by each browser's own
  implementation, and a hospital's workstations are not all Chromium. The
  page-policy (`tests/test_csp.py`) and injection (`tests/test_injection.py`)
  suites also run in Firefox and WebKit, in the `engines` CI job (#160).
- `TEST_BROWSER` chooses the engine, Chromium by default. An unknown value is an
  error, not a fallback, so a typo in the CI matrix cannot run Chromium twice
  and call it cross-browser. `tests/test_workflows.py` fails if the job, either
  engine or either suite goes missing.
- **What the first runs found:** WebKit reports the app's refused `file://`
  request for `/api/health` as a page error even though the app catches it, so
  the app no longer probes for a server from a page opened from disk. Headless
  Firefox could block on the PDF export's real print dialog, so the injection
  test replaces that one frame's `print()` and checks it was reached.
- **Rejected:** running every browser suite in all three engines (most test the
  app's logic, which does not vary by engine, and would triple CI time).
- Source: #160.

### D-74 The shell asks one primary framework through a spine

- Status: Accepted; its CHAI-specific spine (`10-chai/25-spine.js`) superseded
  by D-77, where the engine provides the spine from the definition
- Step 1 of #168 (R-63). The portfolio, the exports, the change history and
  the events used CHAI's definitions directly (about thirty places), so CHAI
  could be joined by another framework but not replaced.
- **One primary per build.** The registry requires exactly one framework marked
  `primary`, and throws at boot otherwise. The portfolio needs one status, and
  folding two frameworks' judgments into one number would be meaningless (the
  same reason OPTICA never feeds CHAI's status, docs/crosswalk.md).
- **The spine** (`app/js/10-frameworks/00-registry.js`) is what the shell may
  ask: items, sections, categories, gates and their labels, a decision's class,
  the answers, phase, flags, status, next review, score, the report body, and
  optional Markdown and JSON extras and worked examples. CHAI implements it in
  `10-chai/25-spine.js`; the generic engine of step 2 will implement it from a
  definition.
- **Hooks for a framework's own controls.** A side panel (`panel`), clicks and
  changes the framework handles (`onClick`, `onChange`), an opt-in switch
  (`toggle`), and the change history's words for its keys (`describePath`,
  `statusName`). A framework without a panel hides the button that opens it.
- **Decisions have a class.** `GateClass` (go, conditional, revise, stop,
  retire) replaces regular expressions over the English option names, which
  the enum rule forbids and which a framework with other words would break.
- **What changed that a reader can see:** in the Markdown report, framework
  text (criteria, stage and checkpoint names) now goes through the same
  escaping as typed text, so a parenthesis in a criterion is written `\(`.
  This is safer for a definition written by someone else and renders the same.
- **Rejected:** a shell that asks every framework and merges the answers (two
  statuses for one project); leaving CHAI's names in the shell behind
  `typeof` checks (a framework could still not be removed).
- Found and left for step 2: catalog strings use CHAI's nouns for generic
  parts ("Stage {n}" on the portfolio track, "Checkpoints", "Principle"); and
  the server is not framework-neutral, because the retention SQL
  (`server/migrations/008_retention.sql`) decides retirement, and so when
  disposal is due, from CHAI's own "Stop" and "Retire" decisions.
- Source: #168; R-63.

### D-75 Frameworks are definitions, run by one engine (#168 PR A)

- Status: Accepted (implements the owner's decision in #168, R-63; design v2 on
  the issue)
- **The definition** is `app/frameworks/<id>/framework.json`, with the shape in
  `schema/framework.schema.json` and the rules a schema cannot state in
  `scripts/check_framework.py` (pre-commit and CI; every rule shown failing in
  `tests/test_check_framework.py`). Ids are explicit (never positional), match
  one safe pattern, and are never a prototype or reserved record key. Every word
  the engine acts on is a member of an engine enum: a status's class, a gate
  option's class, a phase's role, a flag rule. A supplement may not declare
  gates (the server attributes sign-off only on the primary's top-level
  `gates`), and a primary with gates must have a stop or retire option, so a
  project can always end and come due for disposal (R-56).
- **The build** embeds the definitions `app/frameworks.json` selects as
  `FRAMEWORK_DEFS`. The published build is pinned to CHAI plus OPTICA and any
  other config is refused, until a build of other frameworks has a place of its
  own to go (step 3). Rules across definitions (view ids, namespaces, requires,
  file suffixes) apply to that build; a definition outside it is checked alone,
  and the config must name exactly one primary.
- **The engine** (`app/js/10-frameworks/01-engine/`) computes score, phase,
  review and flags from a definition. CHAI's and OPTICA's rule functions now
  delegate to it, and their content constants are derived from the JSON. These
  are transitional, inside their own directories, until the generic renderers
  replace them (PR B). The model card's and metrics' flags are code plug-ins,
  placed in the flag list where the definition puts them.
- **Proof that nothing a reader sees changed**: `tests/test_snapshot.py` pins
  529 pieces (every view of every sample with OPTICA off and on, three
  languages, read-only, the side panel and every export) from before the port,
  and shows zero difference after it. `tests/test_engine.py` covers the engine's
  rules on stand-in definitions CHAI and OPTICA never exercise.
- **One generator writes every framework's checklist page**
  (`scripts/gen_framework_docs.py`), from the definition plus the page's own
  prose in `app/frameworks/<id>/docs.toml`. It replaces `gen_chai_checklist.py`
  (which regex-scraped the built page), `gen_optica_checklist.py` and
  `gen_optica_module.py`, and retires `data/optica_items.json`: OPTICA's
  definition holds every field it had, checked field by field. The CHAI and
  OPTICA pages are byte-identical except one sentence, which told editors to
  edit a generated file.
- **Tests that read JS now read the definitions**: the retention parity test
  (`server/tests/test_retention.py`) and the translation drift test
  (`tests/test_framework_i18n.py`). They stay tied to what the app runs because
  `tests/test_build_config.py` and `tests/test_framework_docs.py` show the page
  embeds exactly the definitions on disk, and `tests/test_engine.py` shows the
  engine ends a project on exactly CHAI's stop and retire options.
- **Rejected:** keeping JS copies of the content beside the JSON (two sources);
  a looser schema that ignores unknown fields (a typo becomes a silent no-op);
  checking every definition under `app/frameworks/` as one build (a custom
  framework outside the published build would collide with CHAI's views);
  rewriting the views and tests in the same change as the engine (a regression
  could be written into the new assertions; PR B does that against the snapshot).
- Found and filed: the OPTICA page's prose says there are no "equivalent" rows,
  but the data has three (part of #174).
- Source: #168; R-63; D-74.

### D-76 Retirement rules are a table, loaded from the build's manifest

- Status: Accepted (implements the owner's design v2 on #168, "Server (PR C)";
  R-66)
- **Why:** `008_retention.sql` decided retirement, and so disposal (R-56), from
  CHAI's words written into `retention_due()` (found in D-74). A build of another
  framework would never retire anything, or would read its words with CHAI's
  meaning. Disposal destroys records, so the rule must follow the deployed
  definition and must never change without someone choosing it.
- **The table.** `retirement_rule(framework_id, gate_id, decision)`, migration
  010, seeded with CHAI's four rows so a database that has not synced retires
  exactly what 008 did. `retention_due()` keeps its signature, columns, kinds and
  clock, and joins each live record to the rows of its framework
  (`record_framework(doc)`: `meta.framework.id`, or `chai` when unstamped). The
  checkpoint id is a JSON key read with `->`, never a path built from text.
  `retired_under(...)` takes a rule set as arrays, so the sync can ask what a rule
  set it has not applied would retire through the same SQL.
- **The manifest is the deploy unit.** `scripts/build_app.py` writes
  `manifest.json` beside the page (`scripts/build_manifest.py`, standard library
  only): per framework its id, role, version, the SHA-256 of its canonical JSON
  and its ending pairs, and the hash of the primary's rule set. Compose mounts
  `${APP_DIR}/manifest.json` (read-only, `create_host_path: false`) into the
  migrate service from the same directory the proxy serves (`APP_DIR`, default
  `./docs/app`; `CSP_FILE`, default `./proxy/csp.caddy`), so page and rules are
  one build. A build of other frameworks (`--config FILE --out DIR`, D-79) writes
  `DIR/manifest.json` beside `DIR/index.html`, never the published one, and is
  served by pointing `APP_DIR` and `CSP_FILE` at it (`tests/test_build_config.py`).
  The API image stays framework-neutral.
- **Every change is acknowledged, by the whole change.** Inside
  `python -m app.migrate`, as the owner, in one transaction under
  `MIGRATION_LOCK_ID`, taken before anything is read. A manifest governs the rules
  of the frameworks it lists. Any change, a pair added, a pair removed or a new
  primary (which decides the stamp the API accepts, and so whose rules new records
  follow), is made only when `RETIREMENT_RULES_ACK` equals the SHA-256 of the
  canonical JSON `{"database": {"cluster", "database", "history"}, "follows": <id
  of the latest retirement_rule_change row>, "at": <its time, UTC, to the
  microsecond>, "before": {"primary", "rules"}, "after": {"primary", "rules"}}`,
  where each `rules` is every row of `retirement_rule`, of every framework,
  sorted (`transition_ack()` in `server/app/retirement.py` is the definition).
  `database` is the database's identity, read by migration 012's
  `retirement_ack_database()`: the cluster's system identifier
  (`pg_control_system()`), the database's OID, and the OID of
  `retirement_rule_change`. A dump carries none of them.
  Otherwise the job exits 3, listing the rules added and removed, the change of
  primary, and every live project that would become due or stop being due (as
  it stands then; see the limit below), prints the exact value to set, and
  changes nothing. A sync that changes nothing
  (the same rows, the same primary) needs no acknowledgment, so the default build
  on a fresh database (whose seed is its rule set) starts without one. Because the
  value binds the full change, one printed for a change the operator was shown
  never accepts a different one: a build that keeps the same primary rule set but
  also drops an unlisted framework's rules, or a rollback to an earlier primary
  over the same rows. Because it names the history row it follows, which the
  change itself moves on, it is spent once used: a value left set accepts no later
  change, not even the same change made again. Because it binds the database's
  identity, a value printed by one database is refused by another with the same
  history (staging built separately or from a dump, and production, or two
  fresh databases migrated alike), which
  the history row's id alone did not do, and by a copy restored from a dump: into
  another database (a new database OID) or cluster (a new system identifier), or
  over the same database in place, as `make restore` does (`make backup` dumps
  with `--clean`, so the restore creates every table again and the history table
  has a new OID). A restore of the data alone into the tables already there
  (`--data-only`, or TRUNCATE and reload, as the owner) keeps that OID, so it is
  the same database; see the limit below. If the identity cannot
  be read (a platform that withholds `pg_control_system()`, which PostgreSQL
  grants to every role), the job refuses every change and says why; a sync that
  changes nothing does not read it. Additions need it too: a stale or mistaken
  build that adds a rule can make records due at once.
- **A create checks the stamp under the lock, shared.** The API's create takes
  `pg_advisory_xact_lock_shared(MIGRATION_LOCK_ID)` before it reads the active
  primary, and the sync takes the same lock exclusively before it reads. So a
  sync that changes the primary waits for every create in flight, and a create
  that starts during it waits and reads the new primary: no record is checked
  against a primary that has just been replaced. Creates do not block one
  another (the lock is shared). Taken before the create's INSERT, so a migration
  holding the lock never waits on a create that waits for it. The restricted
  role may call it (advisory lock functions are granted to PUBLIC), which the
  suite shows by running as that role. A patch reads no primary (below), so it
  takes no lock and never waits on a sync or a migration for it.
- **A manifest governs only what it lists.** Rows of a framework the manifest
  does not list (the primary of an earlier build) are left as they are, so that
  framework's records keep retiring by their own rules; the job reports them,
  and the change event names them (`unlisted`).
- **Confirmed, and reported.** The first manifest to find the database holding
  exactly its rules and primary (010's seed, for the default build) records a
  `manifest` row confirming them, with no acknowledgment. A new primary over rows
  the database already holds is a change, acknowledged like any other.
  `/api/health` reports `retirement_rules` as `hash`,
  `primary` (the latest row's framework) and `synced`: true when that row came
  from a manifest, not 010's seed, and false on an API that migrated itself with
  no manifest (below), whatever the row says, since that API checked nothing
  against its build.
- **The stamp is checked.** A record follows the rules of its
  `meta.framework.id`, so a writer who could stamp any id could keep a record
  from ever coming due. The API refuses (422) a create that sets
  `meta.framework` to anything but exactly `{"id": <the active primary>}` (the
  primary of the latest change row). A record with no stamp is CHAI's, so while
  the active primary is not CHAI the API also refuses a create that leaves the
  stamp out: omitting it would otherwise choose CHAI's rules. No patch changes an
  existing record's framework: the API reads it before and after the merge with
  010's `record_framework()` (the function retention reads it with, so an absent
  or blank stamp is CHAI's in both) and refuses (422) a patch that would change
  it, by setting, removing or blanking the stamp or replacing `meta`, and a patch
  that sets the stamp to anything but exactly `{"id": <the record's own
  framework>}`. A record written before a switch keeps the framework it had and
  stays editable; one written under a later primary keeps it after a rollback.
  A build of other frameworks stamps every record it makes with
  its primary (R-67, D-79); the published build stamps none, which reads as
  CHAI's. Stamps
  written before this check, or by the owner directly, are not re-checked;
  `make dispose` and `make verify-backup` count the records whose framework has
  no rules, which never come due.
- **The API's own migration path syncs too.** With `RUN_MIGRATIONS=true` (the
  single-role setup) and `RETIREMENT_MANIFEST` set, the API runs the same sync
  with the same refusal before it serves; a refusal or a bad manifest stops it
  starting. Without a manifest it migrates, logs a warning, and `/api/health`
  reports `synced: false` for as long as it runs, even over rules an earlier
  sync recorded (`Database.rules_unsynced`, set by `migrate_and_sync()`).
- **Fail closed.** No `RETIREMENT_MANIFEST`, an unreadable or malformed manifest
  (strict: unknown keys, bad ids, a supplement with pairs, a hash that does not
  match its pairs), or a primary with no ending decision exits 1 before anything
  is changed or provisioned, so on a first deploy the API, which waits for the
  job, does not start. Over a running stack the running API keeps serving by the
  rules the database holds, a service Compose recreated (the proxy) is left
  created and not started, and `docker compose up -d` can return 0;
  `docs/self-hosting.md` tells the operator to check `docker compose ps -a` after
  every deploy. No fallback to CHAI's rules or to whatever the table holds.
- **Recorded.** Each change appends to `retirement_rule_change` (who, when, the
  rules before and after, the rule-set and definition hashes, whether the change
  was acknowledged), append-only by trigger, which `make verify-backup` requires
  present and enabled after a restore, along with `retirement_rule` holding exactly
  the rules the latest change row recorded; migration 011 adds its
  `changed_by` to `principal_referenced` (R-54). Each change or refusal is a
  security event (`retirement.rules_changed`, `retirement.rules_refused`). The
  latest row's hash is the active rule set and its framework the active
  primary; `/api/health` reports both as `retirement_rules`, and
  `make dispose` and `make verify-backup` print the rules they found. The
  API's role has SELECT only on both tables.
- **Rejected:** the client recording a retirement date in the document (the
  server would trust a value any writer can set, and records written before it
  would never retire); the server reading the definitions from the image (the
  image would no longer be framework-neutral, and a rebuild of the page without
  a rebuild of the image would split them); a sync that mirrors the manifest
  exactly (a stale or wrong build would silently stop disposal of every record it
  does not know); falling back to CHAI's rules when the manifest is missing (a
  custom build would dispose by words it does not use); an acknowledgment equal
  to the new rule-set hash (a value left set after one change let a stale manifest
  revert to that set later, and it named a destination, not a change); an
  acknowledgment of the transition between two primary rule-set hashes, `{"from",
  "to"}` (shown against PostgreSQL 17 in review: a value printed for an addition
  that affected no project accepted a different build with the same primary rule
  set that removed all of CHAI's rules, and a rollback to another primary over the
  same rows went through with no acknowledgment, after which an old value matched
  again); an acknowledgment naming only the history row's id (shown against
  PostgreSQL 17 in review: a value printed for one database was accepted by
  another fresh one, and by staging's twin in production); reading the primary
  for a write without a lock (shown against PostgreSQL 17 in review: a create
  that read CHAI as primary committed, unstamped, after an acknowledged switch to
  another, a record no acknowledgment listed); checking a patch's stamp against
  the active primary (shown against PostgreSQL 17 in review: under acme, a patch
  stamping a pre-switch CHAI record `{"id": "acme"}` was accepted and the record
  stopped coming due; after a rollback to CHAI, `{"meta": null}` on an acme record
  was accepted and it began following CHAI's rules: either way a write moved a
  record between rule sets with no acknowledgment listing it); a random nonce
  stored in the database to tell databases apart (it told separately built
  databases apart, but a dump carries it, so staging restored from a production
  dump accepted production's values, shown in review); a row lock or
  `SERIALIZABLE` for that instead (the sync would have to lock every project,
  and a serialization
  failure is a retry every write path would need); additive
  sync without an acknowledgment (a stale or mistaken build could make records due
  at once, silently); a manifest removing the rules of frameworks it does not list
  (switching primary would stop the earlier primary's records ever coming due).
- **Limit, stated:** a copy of the database's files is the database. A base
  backup, point-in-time recovery, a volume or disk snapshot, or a promoted replica
  keeps the system identifier, the database's OID and the history table's OID, so
  it accepts again a value printed against the state it holds, and a staging
  database made that way and its original each accept a value printed on the
  other. A restore of the data alone into the existing tables
  keeps the history table's OID too, and puts back the history row a spent value
  follows, so that value is accepted again. `docs/self-hosting.md` says to clear
  `RETIREMENT_RULES_ACK` before restoring either, and to build staging from a
  dump. Nothing prevents it: telling such a copy from the original would need
  state outside the database. (A dump restored with its tables created again,
  anywhere, is told apart.)
- **Limit, stated:** the acknowledgment binds the rules and the primary, not the
  records. The projects listed as becoming due, or stopping being due, are those
  at the moment the refusal was printed; a project decided or edited between that
  and the acknowledged run is affected without having been listed.
- **Not done here:** a tested recipe for delivering the manifest to a cloud
  migrate job (docs/deploy.md says what it needs); it is still not done. The
  dashboard's banner when its embedded hash differs from `/api/health`, or when
  `synced` is false, listed here before, is D-83.
- **Resolved:** the engine's `phase()` used to look a decision's class up by its
  value across all checkpoints, while the rules here are per checkpoint. #182
  (#168 PR B2, merged into this branch) classes a decision by its own
  checkpoint's options (`decisionClass(d, gateId)` in
  `app/js/10-frameworks/01-engine/00-engine.js`: D decided "Stop" ends nothing),
  which is what the rules here do; `tests/test_engine.py` ("A decision is classed
  by its own checkpoint, as the server retires") holds it. This change does not
  touch `app/js/`.
- **Enforced by:** `server/tests/test_retention.py` (real PostgreSQL and the real
  migrate job: every option of a definition is due exactly when its class ends a
  project; additions, removals and a new primary refused without the change's
  acknowledgment, the value printed (its format pinned by an independent
  computation) and the projects listed both ways; the two review sequences above
  refused; every value used through a run of changes refused for each later one;
  a stale manifest refused; unlisted frameworks' rows kept; a value printed by
  one database refused by another with an identical history, and accepted by
  the other once the identity is dropped; a dump restored into another database
  refusing the original's value and the original refusing the copy's, and a dump
  restored in place refusing a value printed before it, each with a mutation
  test dropping the part of the identity that tells them apart; a value for one
  new primary refused for another over the same rules, with a mutation test; a
  change refused, with no value printed, when the identity cannot be read;
  mutation tests that
  drop the framework join, the blank-stamp `nullif` and the latest-decision clock
  and see the result change),
  `server/tests/test_retirement_rules.py` (the stamp checks, a create without the
  stamp under another primary, the API's own sync and its warning, `/api/health`,
  the migration lock: the holder commits a rule change while the sync waits, and
  the sync refuses from the new state; the same race with the lock taken after
  the reads is shown to slip through; a create held after reading the primary
  makes a switching sync wait, and without the shared lock the switch commits
  under it; two creates hold the lock at once, and with an exclusive lock one
  waits; a patch never waits on a migration holding the lock, and would if it
  took it; both review repros refused, with every shape of a stamp change, a
  patch that keeps the framework accepted, and mutation tests checking a patch
  against the primary, or only when it sets the stamp, that let them through),
  `tests/test_dispose.py` and
  `tests/test_verify_backup.py` (the count of records with no rules; the
  history's trigger present and enabled after a restore, a replica-only trigger
  counted as not enabled, with a mutation test, and the rules equal to the last
  recorded change, including one rule swapped for another, each with a dump that
  breaks it; with a real pg_dump, the identity differs after a restore into
  another database, in place and into another cluster). Claims C-61 and
  C-88 to C-90.
- Source: #168 (design v2); R-56, R-63, R-66.

### D-77 Every framework screen is the engine's, drawn from the definition

- Status: Accepted (implements the owner's decision in #168, R-63)
- **One implementation of each screen**: a section's checklist, a checkpoint's
  decision, a supplement's overview and its switched-off screen, and the
  primary's report (`app/js/10-frameworks/01-engine/20-views.js`). The rail,
  routing, record shape, spine and change-history words come from one
  registration per definition (`10-frameworks/90-register.js`). CHAI's own code
  is now only its plug-ins: the model card (form, panel, report section, flags),
  the key metrics (stage 4's slot, a flag), the T&E picker and the samples.
  OPTICA has no code at all; it is its definition.
- **Where wording differs, a definition names a whole-sentence catalog key**
  (`ui` slots: a section's eyebrow, the answered line, the overview's headings),
  never a noun the engine pastes into a sentence. CHAI and OPTICA name today's
  keys, so every translation is unchanged. A framework without a slot's key is
  refused by `check-framework` until PR B2 gives the engine neutral defaults.
- **Status tags keep their CSS names** by a status's class (done is styled as
  "met", open as "notmet"), so the report looks the same for any framework.
- **The transitional names are gone**: `STAGES`, `GATES`, `PRINCIPLES`,
  `OPTICA`, `OPTICA_ITEMS`, `allItems`, `opticaScore`, `setOpticaEnabled`,
  `scoreOf`, `STATUS` and the rest. Tests use the engine (`ENGINES`, `FACADES`,
  `setFrameworkEnabled`) or the spine. The boundary test fails if one returns.
- **Proof**: `tests/test_snapshot.py` before and after: 399 of 529 pieces are
  byte-identical (every CHAI screen, the report, every export) and the other
  130 (OPTICA's 13 chapter views on 10 samples) differ only in whitespace
  between block elements; the fixture was regenerated for those. A stand-in
  primary still drives the portfolio and every export
  (`tests/test_framework_boundary.py`), which caught the Markdown export reaching
  past the spine during this change.
- **Rejected:** keeping a JS copy of each framework's screens beside the engine
  (two implementations to keep equal); interpolating definition nouns into shell
  sentences (it breaks grammar in de, ru, he, hi and zh-Hans, per the design
  review); byte-identical output for OPTICA too (one template cannot reproduce
  two whitespace styles, and inter-block whitespace does not render).
- Source: #168; R-63; D-74; D-75.

### D-78 A framework's words: its own keys, or the engine's neutral ones

- Status: Accepted (implements the owner's decisions in #168 and R-65)
- **Every shell sentence a framework affects is a slot** (`UiSlot`, 52 of them):
  the section and checkpoint screens, the report's headings and footer, the
  portfolio's lede and track, setup, the delete dialog, three flags and the
  translation note. A definition names a catalog key for a slot or leaves it to
  the engine's neutral key (`engine.*`, in all eight catalogs). CHAI and OPTICA
  name today's keys, so their wording and every translation are unchanged (the
  snapshot shows zero difference). A definition with no slots at all is valid.
- **No noun is pasted into a sentence** (the design review: it breaks grammar in
  de, ru, he, hi and zh-Hans). A sentence that names the framework takes its
  `name`, a proper noun. The English text of a flag in an export takes the
  definition's `nouns` ("criterion" for CHAI, "item" by default).
- **The note under translated framework text is per framework**: its own slot
  (CHAI and OPTICA keep `fw.note`, whose zh-Hans text names its reviewer), the
  engine's neutral note, or, when the framework has no translation into the
  reader's language, a note that its words are in English. An English fallback
  in a right-to-left page is isolated left to right, as `t()` already did.
- **The build ships only the selected frameworks' text**: keys in a namespace
  another framework owns are left out of both catalogs, a developer's
  translation files are merged (a repeated key is refused), and
  `FRAMEWORK_LOCALES` records each framework's languages.
- **Rejected:** requiring every slot of a custom framework (an author would have
  to edit the shell's catalogs in eight languages); moving the safety footers
  into CHAI's catalog (the reviewer gate works only for shell keys, per the
  design review), so CHAI keeps them and a custom build gets neutral ones that
  start unreviewed; per-key fallback inside a supplied language (the owner chose
  complete-if-supplied).
- Source: #168; R-65; D-77.

### D-79 A build of other frameworks: `--config` with `--out`, and stamped records

- Status: Accepted (implements the owner's decision in #168, R-63; R-67)
- **The switch is two flags that go together.** `build_app.py --config FILE
  --out DIR` builds the frameworks `FILE` names into `DIR/index.html` and
  `DIR/csp.caddy`. Without them the build is the published one, and refuses any
  config other than `app/frameworks.json`'s pinned CHAI plus OPTICA. An `--out`
  that would write under `docs/`, `proxy/` or `app/` is refused, checked on the
  files it writes after following links, so a custom build can never overwrite
  the published page, the proxy's policy or the sources. `pixi run
  build-example` builds the example into the ignored `build/`.
- **The example framework** (`app/frameworks/example/`) is made up, small, and
  not in the published build. It is the thing to copy, the thing
  `tests/test_custom_build.py` drives, and its checklist page is published
  beside the guide (`docs/frameworks/custom.md`). It supplies Spanish only, so it
  also shows R-65 both ways.
- **Records carry their framework** (R-67): stamped only in a custom build, so
  the published build's records, exports and fingerprints do not change, and an
  unstamped record is read as `BUILD.legacy` (CHAI). The shell reads the build's
  own primary from the embedded `BUILD`, never from a literal.
- **Samples can be data** (`samples` in a definition: names, metadata, answers,
  and decisions as `[option, day offset, rationale]`), checked by
  `check-framework`, for a framework with no code. CHAI keeps its plug-in.
- **Everything embedded in the page's script is escaped for it** (`js_json`):
  every `<` in a definition or a catalog is written as `\u003c`, so no text can
  end the inline script and become markup. The published page is unchanged (its
  text has no `<`).
- **The stamp is not content**: searching all text skips `meta.framework`, so a
  search for part of the framework's id does not match every record.
- **The side panel is hidden when the primary has none**, so a custom build
  carries no landmark naming CHAI's model card.
- **A definition's words are escaped in the Markdown export** like a value a
  person typed: a framework's name, a status label, a checkpoint's name in a
  flag. The published build's export is unchanged (its words have nothing to
  escape); a custom definition's could have carried markup into a viewer that
  renders HTML. Found by `tests/test_custom_build.py`.
- **Rejected:** stamping every record, the published build's too (it would
  change every existing export and fingerprint for no gain, since unstamped
  already means CHAI); stamping an unstamped record when it is loaded (a build
  would silently claim the published build's records); one storage key for every
  build (a custom build would list, and could open, CHAI records it cannot
  read); a definition chosen at run time (R-63: a build is a reviewed change).
- Source: #168; design v2; R-63; R-67.

### D-80 check-app resolves every name on a real parse of the built script

- Status: Proposed (implements #176; the parser and the rules below are this
  change's choice, for the owner to accept)
- **What it checks.** `scripts/check_app.py` parses the inline script of the
  published page, and of a build of every `app/frameworks/*/build.json` made
  into a temporary directory, and resolves every identifier through its scopes.
  It fails on a name nothing declares that is not an ECMAScript or browser
  global, on a `const`, `let` or `class` read before its declaration has run
  (directly, in an IIFE, `new function(){...}` or static block, in a computed
  key of a class or object member, in the right-hand side of a
  `for (const a of ...)` reading `a`, in a destructuring default reading a name
  the same pattern binds later, a class's own name in a computed key of its
  members, or in a function that top-level code calls by name before the
  declaration; a generator's body is not run by its call, nor a function held
  by an instance field by `new`; `delete x` reads nothing), and on a name
  declared twice at top level (a function in a top-level block, or as the body
  of an `if` or `else`, that replaces another function or var counts; as in
  Annex B, one whose name a top-level `let`, `const` or `class` declares binds
  nothing there and does not, and two block functions of one name do not).
- **What "exact" covers.** `tests/check_app_cases.py` holds some three hundred
  scripts that `tests/test_check_app.py` runs both through the check and in
  node; the check must report a problem on exactly the ones node throws a
  ReferenceError on while loading. Exact is claimed for those cases (typeof
  guards, undefined names in code that runs, the temporal dead zone in the
  shapes listed above, Annex B block functions, calls through the call graph)
  and for nothing wider.
  `node --check` still runs, and its absence is a failure under
  `REQUIRE_TESTS`, which both the lint and the test workflows set.
- **The parser is tree-sitter's JavaScript grammar**, two PyPI wheels locked
  with hashes in `pixi.lock`, and the scope analysis is the script's own. It
  runs offline, without node, and parses the syntax the app uses (`?.`, `??`,
  private fields, static blocks).
- **What this asks of future code.** Shared code may reach a name only some
  builds have (a framework's own code, which a build of other frameworks leaves
  out) only behind `typeof name`, which the check accepts as the question "was
  this built?": the operand of `typeof` itself, and a use inside the branch a
  typeof test of the same name guards (the consequent of an `if` or `?:`, or
  the right of `&&`, tested `=== "<a type>"` or `!== "undefined"`, either way
  round, `==` and `!=` alike, against a string literal whose decoded value is
  one `typeof` returns), and nothing wider (not the else branch, not code after
  an early return, not `||`, not a variable or template literal). A new
  browser global the app uses goes in `BROWSER_GLOBALS`, and
  `tests/test_check_app.py` must find it in Chromium, Firefox and WebKit.
- **Its limits, stated in the script and in `docs/developing.md`:** the call
  graph follows only calls of a plain name (`f()`, `new K()`), not method calls,
  callbacks or events, assumes every path through a called function runs, and
  follows every block function of a name (so it can report a body another
  block replaced first); through calls it checks only top-level `const`, `let`
  and `class`, so a function called before a `const` of its own enclosing
  function is missed; a parameter default reading a later parameter is not
  modeled; a typeof guard is one exact form, so safe code in another shape is
  reported;
  code after the first `await` (first in the text) of an async function is taken
  to run after load, so an `await` on a branch not taken hides a read that runs
  during load; a name the app means to declare that is also a browser global
  (`open`, `print`, `origin`, ...) passes as that global if its declaration goes
  missing; `with`, direct `eval` and globals a script adds to `window` at run
  time are not modeled (read bare, one is reported; `window.x` is not checked);
  a `switch` jumping past a `let` in another case is not seen.
- **Rejected:** softening the docstring to what the old code did (#176 names it
  as a false claim, and a custom build makes the failure likely); ESLint's
  `no-undef` and `no-use-before-define` (npm packages pixi cannot lock here, and
  `no-use-before-define` flags a function body that only runs later); the Python
  `esprima` port (ES2017, cannot parse `?.` or `??`); node's bundled acorn
  (reachable only with `--expose-internals`, not a stable interface, and still
  no scope analysis); loading the page in a browser and watching for a
  ReferenceError (finds only what that load happens to run); patterns over the
  text (the old check's approach, which saw only declarations at column 0).
- Source: #176; the workflow task for it.
- Enforced by: `pixi run check-app` (pre-commit and CI's lint job);
  `tests/test_check_app.py` (`pixi run test-check-app`, in the browser and
  engines jobs), which shows each rule failing, including on copies of `app/`
  broken and rebuilt, and requires the check and node to agree on every script
  of `tests/check_app_cases.py`.

### D-81 The spelling guard: listed roots, broad reports, suggestions only

- Status: Proposed (built for #169; the owner has not yet confirmed it)
- **Nothing is ever written.** `pixi run check-spelling` reports. `pixi run
  fix-spelling` (`--fix`) prints, on stdout, a unified diff of suggested
  respellings that `git apply` takes, with paths from the repository root
  (a file outside it is named as given when that is a relative path that does
  not climb; one given by an absolute path or with "..", which `git apply`
  refuses, is left out of the patch, said so on stderr, and makes the exit 1),
  under a header saying the patch is a
  suggestion to review before applying, and lists on stderr every other hit,
  with the reason it is not in the patch, for a person to fix by hand. It
  exits 1 when there is any hit, or a file it cannot read. There is no flag
  that writes a file. Five rounds of review showed an in-place rewriter built
  on heuristics corrupting the owner's text each time a heuristic misread it
  (a genus in emphasis, link labels, `<pre>` and `<script>`, front matter,
  templates, package names, French, quotations). A suggestion a person reviews
  makes that imperfection harmless.
- **Roots, not words.** `scripts/check_spelling.py` holds British roots in
  families (-our, -re, -ce, -ise, -yse, a doubled l), and generates each root's
  inflections and prefixed forms (plural, -ed, -ing, -er, -able, -isation,
  -llist, un-, re-, mis- and the like). Words in no family are listed in
  `EXPLICIT` with their inflections spelled out, and none of them may also be
  generated. A list of exact forms missed a plural while it listed the singular
  (#169), and every other unlisted inflection would have passed the same way. A
  generated form that is not a real word is harmless: each keeps the British
  part of its root, so it can only match a British spelling. Forms that are
  American too ("analyses", "cancellation", "enrolled", "programmed") are never
  generated.
- **Medical spellings are roots too, matched as whole words.** `MEDICAL` lists
  British medical stems (the stems of
  haemorrhage, haematology, oedema, oesophagus, <!-- spelling-ok -->
  oestrogen, foetus, faeces and anaesthesia, <!-- spelling-ok -->
  the -aemia, -rrhoea and -pnoea stems, <!-- spelling-ok -->
  the sulphur, paediatric and coeliac stems <!-- spelling-ok -->
  and the rest), each with a closed set of English endings and a few known
  prefixes. A listed word is caught only if it is one of the generated forms,
  entire, so "phytoestrogen" and "proestrus" are not touched. No listed ending
  is -alis, -ium, -icus, -ica, -ae or -ensis, so a species epithet such as
  faecalis is never listed; <!-- spelling-ok -->
  a few listed English words end in a Latin-looking -us or -i
  (foetus, oestrus, oesophagus, oesophagi). <!-- spelling-ok -->
  The -our and -re roots also take a few closed compounds
  (colourblind, harbourmaster, centrefold, theatregoer), <!-- spelling-ok -->
  and the -our family the prefix re-.
- **Reporting is broad.** A false report costs a `spelling-ok` marker; a
  missed one costs the rule. Every listed hit is reported, in any case, and
  every shape hit, whatever word stands before it: the earlier rule that
  silenced a word after a capitalized word that was not a sentence opener hid
  "Severe hyperammonaemia" and "NHS haemovigilance" <!-- spelling-ok -->
  (the verifier's 132 combinations), and is removed.
- **Shapes match inside a word.** A lowercase word is reported when it holds a
  British medical segment anywhere and is longer than the segment
  (`SHAPES`, `by_shape()`):
  haem, oedem, oesophag, oestr, foet, faec, caec, paed, <!-- spelling-ok -->
  aesthe after an-, kin-, syn-, par-, dys-, hyper-, <!-- spelling-ok -->
  hypo-, hyp- or cen- (so every anaes- word), <!-- spelling-ok -->
  gynae, aetio, the British leuco- stems (leucocyt-, <!-- spelling-ok -->
  leucopen-, leucodystroph-, leucotom-, leucotrien-, <!-- spelling-ok -->
  leucopoie-, leucoencephal-, leucoplak-, leucoderm-, <!-- spelling-ok -->
  leucaem-), <!-- spelling-ok -->
  palaeo, praecord, pharmacopoei, spirochaet, sulph, tumour, <!-- spelling-ok -->
  -rrhoe-, -pnoe-, -aemia and -aemic, and, only at the end, <!-- spelling-ok -->
  -litre and -gramme; and the word gynae. <!-- spelling-ok -->
  Where an American word holds a segment's letters by accident, the pattern is
  narrowed: an oe- segment counts only at the start or after "a", "i", "o"
  or "y", each with a British word only it lets through (American
  "videoedema", "phytoestrogen", "shoestring" are clean, so a British compound
  with another letter before it, such as
  lipoedema, must be listed); <!-- spelling-ok -->
  "haem" inside a word only before "a" or "o" ("alphaemission"); "foet" only
  before an English ending ("infoetl"); "aesthe" only after those prefixes
  ("aesthetic", "nonaesthetic", "antiaesthetic"); "leuco" only in those
  stems, because American geology, botany and chemistry keep it
  ("leucocratic", "leucoplast", "leucomalachite"; `spelling_corpus/american.txt`
  keeps the verifier's list of them). The verifier's 131 medical words
  (`tests/fixtures/spelling_corpus/medical.txt`) are reported, but for two the
  en_US dictionary accepts (below). The suggested respelling
  of a shape is a guess, so a shape is never in the patch.
- **Not reported by shape:** a capitalized word; a word of the letters a-f
  alone (hex); a word with a Latin ending (-us but not -ous, -ae, -ii, -alis,
  -icus, -ica, -icum, -ensis), or one of `LATIN_EPITHETS`, Latin epithets whose
  ending looks English ("faecium", "haematobium"); a word holding one of
  `SHAPE_EXCEPTIONS`, American biology the dictionary lacks ("caecilian",
  "paedomorphosis", "oestrid", "haemosporidian", "haemogregarine",
  "haemonchosis", "asafoetida"); and
  `DICTIONARY_WORDS`, whole words the en_US dictionary accepts as American
  ("leucotomy", "pharmacopoeia" and their plurals). The verifier listed those
  two as British; the dictionary test below and the verifier disagree, and the
  dictionary wins until the owner decides otherwise. Their derivatives the
  dictionary does not list ("pharmacopoeial") are reported. <!-- spelling-ok -->
- **The binomial skip.** No word, listed or by shape, is reported when it is a
  binomial's epithet: it is lowercase and a true Latin epithet (`epithet()`):
  it ends in a Latin form (-a, -i, -is, -um, -us but not -ous), does not
  end in an English medical form (`ENGLISH_FORM`: -ia, so every -aemia; -oea,
  so every -rrhoea and -pnoea; -oma; -itis; -sis), is not one of `NOT_EPITHETS`
  (English -um and -a nouns that look Latin:
  caecum, haemoperitoneum, <!-- spelling-ok -->
  haemopericardium, haematometra, <!-- spelling-ok -->
  praecordium), and is not a listed word, <!-- spelling-ok -->
  except foetus (`LISTED_EPITHETS`, a species epithet too); <!-- spelling-ok -->
  and the word before it, past
  emphasis, quotes, brackets, HTML tags and `&nbsp;`, and on the line before if
  nothing but markup precedes it on its own (a blank line ends that), is one of
  `GENERA` (genera with British-looking epithets: Tritrichomonas,
  Campylobacter, Enterococcus, Schistosoma, Mycoplasma and others) or an
  abbreviated genus: exactly one capital and a period ("T."), the capital at
  the start of the text or directly after whitespace, "*", "_", a quote or an
  opening bracket (so "UK." and "Fig. 2A." are none), and the word before it
  none of `NOT_GENUS_WORDS` (Dr, Mr, Mrs, Ms, Prof, Hep, Group, Twin, Fig,
  Figure, Bed, Lead, Vitamin, Appendix, Table, Type, Grade, Stage, Class,
  Factor, Hepatitis, Genotype, in any case), so
  "Twin A. foetus" is reported. <!-- spelling-ok -->
  Word-level exceptions are listed whole in `LATIN_EPITHETS` and pass wherever
  they stand: those with a Latin-looking ending the rules above call English
  ("haemophilum") and the -ans, -ens and -os ones
  ("haemolysans", <!-- spelling-ok -->
  "oedematiens", "haemobos", "caecicola"). <!-- spelling-ok -->
  "sulphur" is reported even as the butterfly's name, <!-- spelling-ok -->
  since it is the British spelling of "sulfur". <!-- spelling-ok -->
  So "Tritrichomonas foetus" and <!-- spelling-ok -->
  "Enterococcus faecalis" pass, <!-- spelling-ok -->
  and "Severe foetus", "Staphylococcus bacteraemia", <!-- spelling-ok -->
  "Neisseria gonorrhoea", "Mycoplasma oesophagitis", <!-- spelling-ok -->
  "B. oedema" and "Hepatitis C. ischaemia" are reported <!-- spelling-ok -->
  (the verifier's seventh pass found eleven such English words skipped as
  epithets by the first rule, which asked only for a Latin-looking ending).
  The genus list is closed: an epithet after a genus not on it is reported,
  and needs a marker or a new `GENERA` entry.
- **The en_US dictionary is the guard against false reports.** The test
  expands the en_US Hunspell dictionary (`aoo-mozilla-en-dict-us`, pinned in
  `pixi.toml` for the test only), reads each word as the checker does (its
  runs of letters), and demands no rule, listed or by shape, matches any of its
  lowercase words except
  "towards" and "whilst", <!-- spelling-ok -->
  which CLAUDE.md rules out. The dictionary lacks most medical words, so the
  test's own list of American look-alikes still matters.
- **What is not prose is not reported:** a URL (with "://", or a scheme written
  without it: mailto:, urn:, doi:, data: and a few more), an email address and
  a git address, a domain (by a listed top-level domain), a file name with a
  listed extension, a path (starting "./", "../" or "/", or with an extension
  in a segment, where an abbreviation with dots such as "e.g." or "i.e." is no
  extension, so "oedema/e.g." is read), a digest named by its <!-- spelling-ok -->
  algorithm, and a run of 16 or more base64 characters that ends in "=" or
  holds a digit and changes between upper case, lower case and digits at least
  every other character on average. Hex needs no rule beyond the shape one: a
  word is a run of letters, and no listed British word is spelled with a-f
  alone (the tests check every one).
- **What the patch suggests.** Only a hit for which all of these hold
  (`left_by()`); the report names, for each other hit, the first that fails:
  1. the word is listed, not found by its shape;
  2. it is all lowercase (a capitalized word may be a journal, a company, a
     place or a genus);
  3. the file is Markdown, reStructuredText or plain text (`.md`, `.rst`,
     `.txt`, in any case), or the hit is inside a value of `app/i18n/en.json`
     (not a key, not an array's item);
  4. it is not in code: a fenced (` ``` ` or `~~~`) or indented Markdown block,
     a reStructuredText literal block (after "::") or code directive, text
     between backticks, a line starting with "import ", "from ... import ",
     "$ ", ">>> " or "... ", or the word after "import", "require" or
     "library";
  5. between it and the whitespace or line end around it stands nothing but,
     before it, `(`, `[`, `"`, `'` or `*`, and after it, those that close, `*`,
     or `,` `;` `:` `.` `!` `?`.
  These are a filter for the patch only; they never suppress a report.
- **Quotations (R-17).** R-17 says quoted material keeps its original spelling.
  Nothing rewrites it, because nothing is rewritten automatically. The check
  still reports a quoted British word, so a quotation in our own files still
  needs `spelling-ok` on its line or a scoped `.spelling-allow` entry, as
  before.
- **Known limits.** A British word whose stem is not listed and whose shape is
  not a rule passes ("paeony", "diaeresis", "haem" alone, and an oe- compound
  with a consonant before the segment that is not listed;
  `tests/fixtures/spelling_corpus/unlisted.txt` keeps examples). The patch can
  still be wrong (a lowercase listed word inside a quotation, a name written in
  lowercase), which is why it is a suggestion. An epithet after a genus not in
  `GENERA`, and a name made only of listed words, are reported and need
  `spelling-ok`. A word spelled with the letters a-f alone is hex and is not
  read, so "caeca" passes. <!-- spelling-ok -->
  A base64 run that is mostly long words, a URL with a scheme
  not listed and no "://", a domain with an unlisted top-level domain and a
  file name with an unlisted extension are read as prose; a word joined to a
  listed top-level domain by a dot ("oedema.co") is read as a domain and not
  reported. Commit messages are not read. "oenology" is left out on purpose:
  American uses it too.
- **Left out on purpose**, because they are standard or common American
  spellings: "dialogue", "analogue" and the other -ogue words (except the
  catalog word, which CLAUDE.md names); "burnt", "dreamt", "spelt"; "glamour";
  "fulfilled", "enrolled" (the American past tense doubles the l); "analyses"
  (the plural of "analysis").
- **Words as code writes them.** The scan splits identifiers at underscores,
  hyphens, digits and case changes, so each word of a camelCase or SHOUTING_CASE
  name is checked (R-17 covers code), in any case. The ligatures "œ" and "æ" are
  read as "oe" and "ae". A word with an accented letter is not English and is
  not read at all ("décentre").
- **Exemptions are narrow.** A `.spelling-allow` entry is `glob: phrase`: the
  phrase is exempt, exactly and case-sensitively, only in the files the glob
  matches, and only the phrase is blanked, so a British word elsewhere on the
  same line is still caught. An entry with no glob is refused; `*` is the
  explicit way to exempt a phrase everywhere, and needs a comment saying why.
  The GitHub Actions status function and result value are exempt only in
  `.github/workflows/*.yml`; Python's asyncio exception class and its
  `.cancelled()` <!-- spelling-ok -->
  method call only in `*.py`, so the word in a Python comment or docstring, or
  as a bare call, is still caught. The `spelling-ok` marker still exempts its
  whole line. The allowlist file itself is skipped, like the checker, and so are
  the files directly in `tests/fixtures/spelling_corpus/`: each holds British
  phrases on purpose.
- **Nothing is skipped in silence.** A file that is not valid UTF-8, or cannot
  be read, is reported as a problem, not passed.
- **A whole-repository run reads what the hook reads.** Run with no arguments,
  the checker reads every text file outside `SKIP_DIRS` (git and tool
  directories, build output, caches), judged by identify's rule that
  pre-commit's `types: [text]` uses for a file it cannot name by extension: in
  the first 1024 bytes, no byte outside 0x20-0x7E and 0x80-0xFF but BEL, BS,
  TAB, LF, VT, FF, CR and ESC (so no NUL, other control byte or DEL). So
  `pixi run check-spelling` reads shell scripts, `.caddy` files, `.env.example`,
  the ignore files and the lock file, as the hook does. Symbolic links are not
  read (pre-commit does not pass them; the target is read on its own). On the
  command line a file named twice (with and without `./`, through a symbolic
  link to a directory, or by a link and its target) is read once, and a symbolic
  link to a file stands for its target, so a patch never names one file twice
  and always applies; a link to no file is said to be skipped and makes the
  exit 1. The one
  difference left: the hook reads only files git tracks, while the no-argument
  run also reads untracked files that are not in `SKIP_DIRS`.
- **Shown to fail:** `tests/test_check_spelling.py` checks every generated word,
  and every word of a hand-written table, in each of the nine contexts it lists
  (prose, a comment, a string, snake_case, kebab-case, camelCase, Title case,
  UPPER CASE, UPPER_SNAKE). The table names every `EXPLICIT` word, a form of
  every family stem, ending and prefix, and a form of every `MEDICAL` stem with
  each of its own prefixes, and the test demands it does, and that the patch
  suggests every row. It runs the verifier's corpus
  (`tests/fixtures/spelling_corpus/`: about 1,100 lines of organisms, drugs,
  places, journal titles, names, American words, code, URLs, hex and encoded
  data, the line-wrapped binomial, the demonstration that the first version
  corrupted, the 131 medical words and the 132 opener combinations): every
  clean line produces no finding, no name is in the patch, every British line
  is found and suggested exactly where the rules allow. It shows that `--fix`
  changes no file's bytes or modification time, for every kind of file and the
  whole corpus, named or found by a whole-repository run; that its patch
  starts with the suggestion header, passes `git apply --check` on a copy and
  makes exactly the expected text (a last line with no newline, CRLF endings,
  a form feed inside a line, the English catalog, several files); and that a
  hit with no suggestion is listed, not patched. `FIX_CASES` pins each patch
  rule both ways (every boundary character, every kind of file, every kind of
  code, the verifier's cases), and `BINOMIALS` the binomial skip. It also
  checks each shape pattern with a word only it matches, each narrowing with
  the American word it protects, the exceptions, the en_US dictionary, that
  the patch honors `skip()`, capitalized words and identifiers, what is not
  prose, `.cancelled()` <!-- spelling-ok -->
  in and out of Python, the marker, the allowlist and its scope, unreadable
  files, which files a run reads, `SKIP_DIRS` and `QUOTED_VERBATIM` exactly, the
  corpus skip, and the exit codes. Then each is broken in a copy of the checker
  (the test's `MUTATIONS`: dropped stems, endings, prefixes and `EXPLICIT`
  words; a Latin ending or an inside-a-word match added; each shape pattern
  dropped and each narrowing undone; each exclusion and the binomial skip
  removed or widened; each not-prose rule removed or widened; each patch rule
  removed, and each boundary character added or dropped; `--fix` writing a
  file, ignoring `skip()`, losing its header, its exit code, its list of the
  rest, the no-newline marker, git's line splitting or the file's line
  endings, reading a file named twice twice, reading a named link rather
  than its target or naming a path `git apply` refuses; each alternative of
  each narrowed pattern, each exception, Latin epithet and dictionary word,
  and each English form of the binomial skip dropped; each URL scheme and
  top-level domain the checker lists, which the test also demands equal a
  list written in it; and the file rules), and the test demands the break is
  noticed.
  A mutant stops at the first property that notices it, the fast ones first,
  and the en_US dictionary is expanded once and handed to every mutant's
  process, so the whole run takes about half a minute (it took ten, because
  every mutant ran every property, the 250,000 lines of the every-word check
  among them). The
  tests of the removed in-place rewrite were deleted with it, not weakened.
- **Rejected:** narrowing `--fix` further (each of five rounds narrowed it,
  and each round's verifier found another kind of text it corrupted; a
  rewriter that is right only where its heuristics are right is wrong somewhere
  new each time); removing `--fix` entirely (the respellings of listed words in
  prose are mechanical and usually right, so a patch saves real work, and a
  person reviewing a diff catches what a heuristic cannot); a flag that
  re-enables writing (the same corruption, one flag away); keeping the
  after-a-capitalized-word suppression for reports (it silenced real British
  words after every capitalized word that was not a sentence opener);
  listing more exact forms (the failure #169 describes, repeated for the next
  unlisted one); matching any word that contains a British stem (flags
  "enrolled" and "fulfilled"); a dictionary as the checker's word list (a new
  install, and still a list; the dictionary is a dependency of the test only,
  as a guard); allowlist phrases that apply in every file (a protocol's
  spelling in a workflow exempted the same word in our prose).
- Source: #169; R-17; the verifier's findings on the first five versions of
  this change; the orchestrating instruction of round six to stop writing
  files.
- Enforced by: `pixi run check-spelling` (pre-commit, and CI through `prek run
  --all-files`); `pixi run test-check-spelling` (pre-commit when the checker,
  its allowlist, its tests or its corpus change, and CI's test workflow).

### D-82 One export schema for every framework, and one fingerprint rule

- Status: Proposed (implements #177; the choices below are this change's, for
  the owner to accept)
- **The schema describes any framework's export.** `schema/project.schema.json`
  was CHAI's alone (`"schema": {"const": "chai-review/2"}`, CHAI's statuses,
  categories and item ids), so every export of a build of another framework
  (D-79) failed it. It now states the structure every export shares, with
  `schema` matching `<id>-review/<n>` (the pattern a definition's
  `export.schemaId` must match), and keeps CHAI's lists under an
  `if schema == "chai-review/2"` condition, so the published contract refuses
  everything it refused before, but for another framework's export id.
  That is tested, not asserted: every mutant of a real CHAI export (each path
  set to text, a number, null, true, an object and a list, and deleted) that the
  schema before #177 refuses (`tests/fixtures/project.schema.before-177.json`),
  the new one refuses too. The first version of this change failed it: it had
  lost the metric categories of the record (`_state.metrics[].cat`). Another
  framework's definition-made values (item ids, statuses, categories, phases,
  checkpoints) are stated by its definition, and `tests/test_export_schema.py`
  checks the example's export against its definition, and CHAI's lists in the
  schema against CHAI's definition, OPTICA's and the page's.
- **What the exports wrote and the schema did not say is now described, not
  removed:** `flags[].msg` (the catalog key the dashboard shows a flag with,
  exported since #80), `_state.access`, `createdBy`, `updatedBy`,
  `meta.framework` (R-67) and a supplement's record (`_state.optica`). No field
  of the published export changed but one sentence: in the pinned snapshot
  (`tests/fixtures/snapshot_default.json`) each sample's `export.json` piece
  changed, all ten of them, and only in `fingerprint.of`, which now states the
  whole rule (below). The digests in those exports are unchanged: a sample's
  stored record and its filled-in copy are the same until OPTICA is switched.
- **Every field the export always writes is required**, at the top and inside
  the objects it always writes whole (a checklist row, a flag, the fingerprint,
  the provenance, CHAI's scores and model card), so dropping one from
  projectJSON() fails CI: the test drops each in turn. An export from before
  the provenance and the fingerprint (#93, #150) no longer validates; keeping
  them optional for it would let the current export drop them unnoticed.
- **The derived fields stay open; the test closes them.** The published schema
  allows fields it does not name in the derived objects, so a reader's validator
  does not break when one is added. The test validates every export a second
  time with every described object closed, so a field projectJSON() adds
  without describing it fails CI.
- **The record (`_state`) is described as the dashboard writes it.** An answer
  has a status, evidence, an owner, a due date, references (each a closed
  object under a reference id) and, only where a status asks for one, a reason
  (string-valued, under the field the definition names). A key of the record
  that is not one the schema names is a supplement's record: it must be a
  framework id, and a supplement has only `enabled` and `answers`. Under the
  CHAI condition the record is closed: its keys are the ones named and
  `optica`, its item ids CHAI's, its answers' statuses and fields CHAI's (and
  OPTICA's, with `declineReason`), its card fields and checkpoints CHAI's. It
  was open (`_state.items.*` any object, any key a supplement), so a bogus
  status or an unknown key passed.
- **The fingerprint rule is one rule.** The skip list is written in six places:
  three programs (the dashboard, the server, `examples/load_export.py`), two
  sentences (the export's `of`, `docs/exports.md`) and the dashboard's comment
  giving each field's reason. They are kept as copies, each in its own
  language, and `tests/test_fingerprint_skip.py` reads all six and fails on any
  difference, with a mutation adding and removing a field in each.
- **Fixed by this change, each a case of the same record hashing two ways:**
  the dashboard serialized integer-like keys (`"9"`, `"10"`) in numeric order,
  because a JavaScript object reorders them, while the rule and every other
  reader sort them as strings, so a record keyed by numbers (a framework whose
  item ids are numbers) failed `verify_fingerprint`; the server sorted keys by
  code point, not by UTF-16 code unit as the dashboard does; the server hashed a
  revision without the project's id, which the dashboard's fingerprint includes;
  and the dashboard's "Project created" history entry was hashed without the id.
  That entry's hash is shown in the history view, so the snapshot's `changelog`
  piece of every sample changed (OPTICA off and on); it now equals the
  record's fingerprint.
  A golden record (`tests/fixtures/fingerprint_record.json`) is given the same
  digests by all three implementations. Revisions the server stored before this
  keep the hash they were stored with (history is append-only), so their
  fingerprints differ from the dashboard's.
- **The fingerprint is of the record as stored.** The dashboard fills in what
  an older record lacks (`meta.chaiUseCase`, `card`, `access`, a checkpoint) to
  show it, and hashed that filled-in copy, while the server hashed the stored
  record, so an older record had two fingerprints. The dashboard now keeps the
  record as the store holds it beside the filled-in copy (`storedRecord`,
  moved by every patch it sends), hashes that on the setup page, in each
  history entry and in every export, and exports it as `_state`, so a reader
  recomputes the server's digest. This changed the rest of the pinned snapshot:
  switching OPTICA on writes `optica.enabled` to the stored record, while the
  filled-in copy also has `optica.answers: {}`, so from then on the two differ.
  The history view's "Record fingerprint" and the hash of the entry recording
  the switch were the filled-in copy's and are now the stored record's, in the
  `changelog` pieces captured after a switch: every sample's `optica-on` piece,
  and the first sample's `en-XA`, `he` and `read-only` pieces (captured after
  OPTICA was switched on and off again). Nothing else in the snapshot changed:
  33 of 529 pieces, each listed here. Rejected: normalizing on the server (it would
  need each framework's `normalize()`, which is the dashboard's code, and would
  change every stored revision's digest); writing the filled-in fields back
  when a record is opened (a read that writes, and a reader cannot write).
- **A lone surrogate is written as `JSON.stringify` writes it,** its lowercase
  `\u` escape, so the canonical text is UTF-8 the dashboard can encode. Python's
  `json.dumps` wrote the surrogate itself, which UTF-8 cannot encode, so
  `load_export.py` and the server raised `UnicodeEncodeError` on such a record;
  both now encode with `backslashreplace`, which changes nothing else. Rejected:
  U+FFFD, which `TextEncoder` would substitute for a raw surrogate but never sees
  one, since `JSON.stringify` has escaped it; Python would then disagree with
  the browser. The server refuses such a record anyway (PostgreSQL's `jsonb`
  cannot hold one), so it reaches only a browser-only export.
- **The rule is stated whole where a reader reads it.** The export's `of`
  sentence and `docs/exports.md` say the record as stored, the key order (UTF-16
  code units) and the lone surrogate's escape, and
  `tests/test_fingerprint_skip.py` fails if either stops saying one. A skip list
  is read where it is written, so the test also fails if a program does
  anything with its list but test membership (`.has()`, `in`): an `.add()`, a
  second assignment or another module setting it would make the list the
  program uses differ from the one the test read.
- **A flag's text is English, its dates included.** The engine wrote a review
  flag's date in the reader's language ("5. Sept. 2026" in a German export),
  while the export and the portfolio CSV are documented as English; the flag's
  `msg` carries the date for the dashboard to show in the reader's language.
- **Not covered:** numbers that are not integers are written by JavaScript and
  Python differently in some ranges (`1e-7`, `1e21`); the dashboard stores none,
  so the rule does not specify them.
- **An answer is closed for every framework the schema names.** An answer may
  hold text under the reason field its definition names, and the schema cannot
  know another framework's, so `$defs/answer` allows any text field: in the
  example framework's build, a text field added to an answer, or `due` written
  under another name, passed. Each primary framework in this repository now has
  a condition on its export id (`chai-review/2`, `example-review/1`) that names
  its record's keys and an answer's fields, its reason fields by name, so any
  other field is refused; `tests/test_export_schema.py` fails if a primary
  definition has no condition, or a condition's lists differ from the
  definition's. A framework the schema does not name keeps the open answer.
  Written by hand, not generated, for the reason below.
- **Every path the schema describes is in a real export.** The test walks every
  valid export it made (samples, OPTICA on, an empty, a hostile, a planted
  review due soon, a record made by a signed-in person with access lists, an
  OPTICA answer declined with its reason, owner, due date and a file added
  through the evidence form, the example build's) and fails if a path the
  schema describes has no value in any, unless it is listed with the reason
  (today one: a primary framework's reason field, which neither primary has).
- **Rejected:** a schema per framework generated by `build_app.py` (more
  machinery for no reader: a custom build is not published, and the published
  schema's `$id` is one URL); leaving the schema CHAI's and documenting that
  other builds have none (a build of another framework would export a file that
  no published contract describes, and `load_export.py` refused it); removing
  `flags[].msg` from the export (changes a file format readers may already
  parse, for no gain); generating the skip lists from one file (three languages
  and two prose sentences; a generator would be a build step for the server and
  the example script, which need only the standard library); a list of the
  fields hard-coded in the server only, compared by a server test (the prose
  copies would still drift).
- Source: #177; D-79; R-67; R-68.
- Enforced by: `tests/test_export_schema.py` (`pixi run test-export-schema`,
  browser job); `tests/test_fingerprint_skip.py` (`pixi run
  test-fingerprint-skip`, workflows job); `server/tests/test_fingerprint.py`
  (server job, against PostgreSQL: the shared record and
  `tests/fixtures/sample_export.json`, a real export of a sample, whose digest
  `tests/test_export_schema.py` checks is still the dashboard's);
  `tests/test_snapshot.py`.

### D-83 The page says when its server retires by other rules, and stops decisions

- Status: Proposed (implements the client side D-76 listed as not done, and the
  owner's design v2 on #168, "a blocking banner on mismatch"; the choices below
  that the design left open, what "blocking" stops, dismissal, and an older
  server, are this change's, for the owner to accept)
- **The page carries its rules.** `scripts/build_app.py` writes the primary's
  rule-set hash into the page as `BUILD.ruleSetHash`, computed by
  `build_manifest.manifest()`, the function that writes `manifest.json` beside
  it, for the published build and for a `--config`/`--out` build alike, so the
  page and its manifest cannot name different hashes.
- **What it compares.** In API mode only, `checkRetirementRules()`
  (`app/js/20-app/57-rules.js`, over `app/js/00-core/35-rules.js`) reads
  `/api/health`'s `retirement_rules` at boot. A `primary` other than
  `BUILD.primary` is one problem; otherwise a `hash` other than
  `BUILD.ruleSetHash` is another (a different primary always has a different
  hash, so its sentence replaces the vaguer one); `synced` not `true` is a
  third. Anything but exactly the page's value counts as a difference: a
  missing field, a `synced` that is not the boolean `true`, and a
  `retirement_rules` that is not an object at all (a string, a number, a
  boolean, a list), which is reported as other rules and blocks. Each has
  its own sentence (`rules.primary`, `rules.hash`, `rules.unsynced`), and each
  asks for the migrate job to be run with this build's `manifest.json`. A
  closed set, so `RulesProblem` is a frozen object.
- **A disagreement stops what the rules govern, and only that.** While the
  primary or the hash differs, the banner is `role="alert"`, the decision
  buttons are disabled, the decision handler and `createProject()` (new, import,
  samples) refuse with a toast, and every other write (checklist answers, text,
  access, litigation holds, purge, deletion, exports) goes on. A decision is
  what makes a record due for disposal, so one recorded on a page that shows
  other rules than the server's could make a record due when the page says it is
  not; a new record would be retired by rules the person was not shown. A
  litigation hold and the purge path protect records and must work exactly when
  something is wrong. A disabled decision button names the banner with
  `aria-describedby`. The banner says other changes still save only to a person
  with a project open that they may edit; to a reader it says only what stops.
- **Unsynced alone stops nothing.** When the hash and primary agree and
  `synced` is false, the server holds the page's rules (the hash is of the rules
  themselves) but no manifest confirmed them; the banner is `role="status"`
  and says so.
- **Not dismissable.** The fix is the operator's, and a banner one person closes
  hides the problem from the next decision. It goes when the rules are fixed and
  the page reloaded. It is one element for the life of the page, inserted empty
  with its role and filled a moment later (a live region inserted already full is
  not reliably announced, `role="status"` above all); a change of language or of
  the open project changes only the words that differ, in place, rather than
  inserting a new alert. It takes `dir="auto"` with each part isolated, so it
  reads in the direction of the words it shows (English in Hebrew until
  reviewed) rather than each sentence aligned its own way. Its sentences
  are safety-bearing (`@meta.safety`), so they stay English until a reviewer is
  recorded (D-59).
- **No server, no banner.** In local mode or from a file there is nothing to
  compare. A server that sends no `retirement_rules` (one from before #168
  PR C), or sends `null` (it cannot read them), gets no banner and no refusal:
  the page has nothing to compare, and the stack ships page and API together.
- **Rejected:** a whole-page read-only mode (it would stop litigation holds and
  the purge path, and all work, over an operator's misconfiguration); a banner
  with no refusal (a decision recorded under it is retired by rules the person
  was not shown); a banner dismissable per session (it hides the problem from
  the next decision, and from the next person at a shared workstation); a
  softer note for a server that sends no `retirement_rules` (every such server
  predates the rules table, so the note would show on every older deployment
  and say nothing an operator could act on); reading `manifest.json` from the
  server at run time instead of embedding the hash (a page from a file has no
  server, and the page must say what it was built with, not what is beside it);
  comparing only the hash (a primary mismatch would then be reported in the
  vaguer words).
- **Limits, stated:** the refusals are the page's, so a person who edits the
  page or calls the API directly can still record a decision; the server's own
  checks (D-76: the stamp, the acknowledgment) are what bind. The comparison is
  made once, at boot: a migrate job that runs while the page is open is seen on
  the next reload. `null` is also what a server that has the rules table sends
  when it fails to read it (`Database.retirement_rules_cached` in
  `server/app/db.py` returns `None` on a database error, and caches that for 30
  seconds), so a page that boots during a transient failure shows no banner and
  refuses nothing, though the server's rules may not be its own; it is told on
  the next reload after the failure clears.
- Source: #168 (design v2, the client side); D-76's "Not done here"; the
  workflow task for it.
- Enforced by: `tests/test_rules_banner.py` (`pixi run test-rules-banner`, in
  CI's browser job): the embedded hash is the manifest's, for the published
  build and the example built into a temporary `--out`; no banner when the
  rules agree, when `retirement_rules` is absent or null, or from a file; each
  disagreement's own sentence, title, role and blocking style, the banner
  visible; a hash differing in its last character, a missing hash or primary, a
  primary the page's is a prefix of, and a `retirement_rules` that is a string,
  a boolean, a number or a list each blocking; a missing `synced`, `"false"` and
  `1` each unsynced; a decision and a new record refused and other edits saved
  under a disagreement, the disabled buttons described by the banner, and "other
  changes still save" not said to a reader; nothing refused when only `synced`
  is false; the server's words shown as text; the banner inserted empty and
  filled after, changed in place (the same element, one banner) on a change of
  language, for the published build and the example, and left to right in
  Hebrew; and twenty-eight mutations of the built pages (among them the hash
  compared with the wrong field or by its first character, the primary check
  skipped, compared by prefix or with the legacy framework, a missing hash or
  primary or a malformed answer taken as agreement, `synced` ignored, compared
  as not false or by truthiness, each refusal dropped, the buttons left enabled
  or undescribed, the alert role, the blocking style or the title dropped, the
  titles or the two frameworks swapped, the banner hidden, inserted full,
  reinserted on a redraw or its words never changed, its direction unset, and
  "other changes still save" said to a reader) each caught.
  `tests/test_stack.py` checks the real stack's page shows no banner. Claim
  C-95.

### D-84 The crosswalk is checked against OPTICA's definition

- Status: Proposed (built for #174; the owner has not yet confirmed it)
- **The problem.** docs/crosswalk.md described the reviewed, corrected crosswalk
  (0 equivalent, 61 partial, 16 OPTICA-only, 36 CHAI criteria cited; 59 and 18
  after the owner dropped the 5.3 and 7.4 claim) while OPTICA's
  definition, which the dashboard's "covered by CHAI" chips and the generated
  OPTICA checklist are drawn from, still held the earlier pass (3 equivalent, 60
  partial, 14 OPTICA-only, 35 cited, no s3-7). Nothing connected the two, so the
  page, the checklist and the app disagreed for as long as the data existed.
- **The data follows the page.** The definition now records every change the
  page states (its "Corrections applied", the 7.1 and 7.2 rulings, the s2-7 and
  role-dual extensions, and the producer reassignments of 1.4, 11.3, 11.4 and
  11.6). Nothing was inferred: the page is the reviewed source, and only what
  it says was copied.
- **The page's item table is generated.** `scripts/gen_crosswalk.py` writes
  section 7 of the page (each item's who answers, relation and CHAI criteria)
  from the definition, between two markers, as part of `pixi run gen-docs`. The
  per-item view on the page is the definition, so it cannot drift.
- **The prose is checked.** `pixi run check-crosswalk` reads every count, list
  and named correction the page states about the current mapping and recomputes
  each from the definition: the headline relations, the criteria cited and never
  cited and the one gained over the previous pass, the stage and chapter tables,
  the chapter sentences (chapter 7's shape, the criteria chapters 3, 4 and 5
  cite, which chapters one party can complete and how each splits), corrections
  applied and rejected, the producer split and who the adopting organization's
  items are assigned to, the relay of completion stages and the stages it puts
  s3-7, s6-3 and 12.1 at, the most-cited criterion, the items that keep or lose
  a mapping, and the whole-checklist totals named in passing. Most of these are
  read by pattern, and a numeric claim reworded so its pattern no longer
  matches is a failure. Some sentences are found by a looser search, and
  rewording one of those (naming a different item, or changing a number the
  pattern does not capture) is not noticed: the check is a tripwire for the
  counts and lists on the page, not proof that every sentence is true. It
  also checks the OPTICA checklist's "There are no *equivalent* rows"
  (`app/frameworks/optica/docs.toml`), which stops being checked if that
  sentence is reworded. The page's item-by-item attributions in prose (which
  item supplies which criterion in the section 3 and section 6 lists) are not
  checked. Four of them disagreed with the definition (s1-6 at 12.5, s2-3 at
  7.2, s2-4 at 7.7, and s1-6 "across 10.3, 12.5 and 13.1"); the owner decided
  (#191, 2026-10-10) to remove those claims rather than correct them, and they
  are gone from the page. Attributions that remain are still not checked.
- **What the check cannot derive, and so does not claim.** The reviewer's
  grading of each CHAI criterion as reached, touched or absent is not in the
  definition. The check holds it to itself and to what is cited: the stage
  table, the two section 3 tables (with each criterion's track, from CHAI's
  definition) and the section 6 lists must agree, grade every criterion once,
  and never grade an uncited criterion reached. The previous pass's figures are
  checked by `tests/test_crosswalk.py` against the record of that pass
  (`tests/fixtures/optica_crossrefs_before_174.json`). The coverage grades and
  the audit's history are not checked. Section 7 of the page says exactly this.
  The verifier on #174 found two chapter sentences false under the earlier,
  unchecked prose (chapter 3 cites five criteria, not nine; chapter 7 ten
  criteria across four CHAI stages, not six across three), and a third ("No
  chapter can be completed by one party": chapters 1, 2, 6, 9, 12 and 13 can
  be); all three are corrected from the data and now checked.
- **Reviewed but not recorded: the claim is dropped.** The page had moved 5.3 and
  7.4 from OPTICA-only to partial without naming the CHAI criteria they reach,
  while the definition kept them OPTICA-only, and an escape hatch in the check
  read them as the page said while the open question R-69 stayed Open, with the
  counts they could change checked as lower bounds. The owner decided on
  2026-10-10 to drop the claim (R-69, answered). The escape hatch is removed:
  the check no longer reads REQUIREMENTS.md, every count is exact (chapters 5
  and 7 included, with no lower bounds), and it fails if the page says any item
  is "partial on this page" or "not yet recorded". 5.3 and 7.4 are OPTICA-only
  on the page as in the definition, which records no criterion for either, and
  the page's counts are the definition's (59 partial, 18 OPTICA-only). Prose
  that depended on their being partial was deleted, not rewritten.
- **A relation and its ids agree.** `scripts/check_framework.py` requires an
  equivalent or partial crossRef to name at least one item and an OPTICA-only
  one to name none, so the definition cannot record a partial the chip would
  show as not covered. `check-crosswalk` also requires every crossRef to name
  CHAI, the framework OPTICA requires, since it reads every id as a CHAI
  criterion.
- **The order of an item's ids matters.** The dashboard's chip shows the first
  criterion an item lists and names the rest in its tooltip, so the first is
  the item's lead anchor. The order is the definition's, and the page's
  generated table states it; reordering an item's ids leaves the table stale and
  `check-crosswalk` fails until it is regenerated, which makes the new chip a
  reviewed change. `tests/test_optica.py` checks, in a browser, that each chip
  shows the first id its definition lists.
- **OPTICA's definition is version "2".** Its mappings changed, so its
  `version` moved from "1" to "2". The version is read only by the build
  manifest (`docs/app/manifest.json`, which the server's retirement rules
  read as text); the record's stamp names only the framework id, so no stored
  record or export changes.
- **The residue text is not maintained.** Each OPTICA item's `attrs.residue`
  (what OPTICA asks beyond CHAI) came with the earlier pass. Nothing displays
  it: not the dashboard, the generated checklist or the crosswalk page. It is
  empty for 1.1, 9.3 and 12.1 and was written for the earlier relation of 3.2,
  6.3, 7.5 and 8.1. It was left as it is rather than rewritten, because the
  page does not supply the text and none is invented here (the only edit is
  the spelling "rigour" to "rigor" in 12.2's, under R-17). <!-- spelling-ok -->
  Anything that starts to show it must first bring it up to date.
- **Rejected:** generating the whole page from the definition (its argument is
  prose, written by a reviewer, not data); hand-maintaining a second per-item
  table on the page (two copies, the failure #174 already was); parsing only the
  headline numbers (a changed criterion id would pass whenever the counts
  happened to hold); guessing 5.3's and 7.4's criteria from the chapter table's
  totals (the page constrained them but did not name them); recording 5.3 and
  7.4 as partial with no ids (the chip would say "not covered" while the data
  said partial, which the new coherence rule now refuses); keeping the "not yet
  recorded" escape hatch while R-69 was open (dropped with the claim); claiming
  on the page that "every count" is checked while the reached/touched/absent
  grading cannot be (softened to what is checked, and that grading checked for
  consistency).
- Source: #174; the #168 coupling map that found it; docs/crosswalk.md; the
  verifier's findings on the #174 branch; the owner's answer on 5.3 and 7.4
  (2026-10-10, R-69).
- Enforced by: `pixi run check-crosswalk` (pre-commit and CI) and
  `tests/test_crosswalk.py` (`pixi run test-crosswalk`, CI's workflows job): the
  committed page and definitions agree; the original #174 disagreement, from a
  fixture of the earlier pass, is found; one relation, one criterion id added,
  removed or swapped, one "who answers", an equivalence back and a
  criterion recorded for 5.3 or 7.4 while the page says OPTICA-only are each
  caught in the definition, with the
  table stale and with it regenerated; a headline count, an id or relation in
  the table, the never-cited list, a citation fix, a chapter count, the
  producer split, a reworded claim, the markers, 5.3 or 7.4 listed as partial,
  61 partial and 16 OPTICA-only restored, the "not yet recorded" paragraph
  restored and a chapter 5 or 7 count off by one are each caught on the page,
  as is each countable prose sentence (the two false chapter sentences restored
  among them); a crossRef to another framework is caught.
  `tests/test_check_framework.py` (`pixi run test-check-framework`) shows the
  coherence rule failing (9.1 partial with no ids, 2.2 OPTICA-only with s1-2).
  `tests/test_optica.py` (`pixi run test-app`) checks each chip in a browser.

### D-85 The Markdown export is audited as rendered, worst case first

- Status: Proposed (a testing choice made on #167; the owner may change it)
- **Render the export, audit the HTML.** `tests/test_markdown_render.py` renders
  the Markdown report with markdown-it-py, a CommonMark reference
  implementation, in four configurations: the CommonMark preset and GFM
  (tables, strikethrough, autolinks), each with raw HTML refused and with it
  passed through. The passed-through ones are the worst case, a viewer with no
  sanitizer, and are the ones that count. `md_problems` stays as a cheap
  first look at the text.
- **What is audited.** The tokens (no `html_block`, `html_inline`, image, hard
  break, code, quotation or strikethrough exists); the HTML in Python (only
  headings, paragraphs, lists, table parts, strong, em, a and hr, no `on*` or
  style attribute, no attribute starting with `javascript:`, `data:` or
  `vbscript:`, every link http(s) without credentials); the same HTML opened in
  a page with the injection suite's own `AUDIT`; and the structure: the block
  tags of an export poisoned with a payload equal those of the same project
  poisoned with a harmless word, so a value cannot start a heading, a list, a
  quotation or a table row.
- **Configuration is part of the test.** linkify's email autolink is off (it
  makes `mailto:` links, not what is audited) and its protocol-relative `//host`
  schema is removed, because GitHub does not make either from bare text. The
  developer-only pseudo-locale `en-XA` is left out, since it pads strings with
  tildes the renderer reads as strikethrough; no reader chooses it.
- **Known, and not fixed here (fixed by #194, D-88: the export removes the
  credentials and the audit no longer allows any credentialed link; read the
  rest as the state when this was written).** A GFM renderer (GitHub's too)
  turns a bare address in a value into a link, including
  `https://user:pass@host/`, because `line()` escapes Markdown's structure and
  not an address. The audit allows a credentialed link only when its text is its
  address, and a test pins that this is what happens, so a fix (escaping the
  colon after a scheme) would be noticed and the pin removed. It is the owner's
  call whether the Markdown report should stop addresses from linking. Also not
  noticed by the structure comparison: a pipe that ends a table cell early,
  because GFM drops the excess cells and the block tags stay the same.
- **Reproducible.** `markdown-it-py` and `linkify-it-py` are in
  `pixi.toml`'s pypi-dependencies and locked in `pixi.lock` with hashes; nothing
  is fetched at test time.
- **Rejected:** keeping text patterns alone (it audits what someone thought of,
  not what a renderer does); a JavaScript Markdown renderer in the page (D-71 already
  rejected one); claiming `enforced` for C-82, since one
  renderer family cannot stand for GitHub's sanitizer, an editor or a wiki.
- Source: #167; the owner's task for it; claim C-82.
- Enforced by: `tests/test_markdown_render.py` (`pixi run test-markdown-render`,
  in CI's browser job and in the engines matrix): every payload of the injection
  suite across every sample, OPTICA off and on, every language, and the example
  build; and mutations of the built page (escaping removed, newlines kept,
  angle brackets or a pipe unescaped, `mdInlineMarkdown` writing raw text or any
  link) each rejected.

### D-87 OPTICA's overview says what it groups by, not five stakeholders in sequence

- Status: Proposed (built for #175; the owner has not yet confirmed it)
- **The problem.** The OPTICA overview's lede ("answered by five stakeholders in
  sequence"), its "who owes the next answers" note ("OPTICA is a relay: each stage
  is completed by one stakeholder before the next begins"), its column header
  ("Stakeholder") and the setup toggle ("answered by five stakeholders") described
  OPTICA's own procedure, while the table groups items by `who`, a three-valued
  producer (adopter, developer, either), sorted by item count. The screen showed
  neither five stakeholders nor stages. Found by the #168 coupling map.
- **What the definition holds.** Every item has `attrs.stakeholder` (five distinct
  values: clinical expert 33, AI solution developer 29, organizational data lead
  7, MLOps expert 5, organizational AI lead 3) and `attrs.stage` (A-G). They are
  English strings in the data, in no catalog, and no screen reads them.
- **Decision: the words describe what is shown.** The lede states the size and
  the question OPTICA asks; the note says outstanding items are listed by who can
  answer them (your organization, the solution's developer, or either party); the
  column is "Who answers" (key `optica.col.who`, was `optica.col.stakeholder`);
  the toggle says "77 adoption questions in 13 chapters". All eight languages
  are machine-drafted. None of these keys is safety-bearing (`"@meta".safety`
  lists warnings, disclaimers and provenance, not these), so no zh-Hans reviewer
  record applies or is lost (R-55). `docs/guide.md`, `README.md` and
  `docs/frameworks/optica.md` say the dashboard does not show the five
  stakeholders or the stages; the procedure itself, as the paper states it, is
  unchanged on the framework page.
- **Rejected: show the five stakeholders and the stages.** It needs a way for a
  definition to name the attribute a screen groups by (a schema and engine change
  under D-75 and D-77), translated names for the five stakeholders and seven
  stages (new reviewer-facing content, D-78), and a decision on whether the
  adopting organization's three roles become one row each. It is a feature,
  not a correction, and nothing here is blocked on it. Left for the owner to
  ask for.
- **Rejected: change the data to three stakeholders.** The five stakeholders are
  OPTICA's, not ours, and the crosswalk page cites them (D-84).
- **Rejected: keep the text and add a footnote.** The sentence would still be
  false of the screen it heads.
- Source: #175; the #168 coupling map; docs/frameworks/optica.md; D-75; D-77.
- Enforced by: `tests/test_optica.py` (`pixi run test-app`, CI's app job): in
  every language the overview has one row per `who` value in the definition,
  labeled by that value's own catalog text, and neither the overview nor the
  setup toggle, lede or note says five of anything, "in sequence" or a relay
  while it does not have five rows.

### D-86 A save the server refused is not retried, and says why

- Status: Proposed (the retry rule is the owner's request on #186; the
  classification below, and what a refusal keeps and says, are this change's,
  for the owner to accept)
- **Three outcomes, by one function.** `classifyStatus()`
  (`app/js/00-core/20-stores.js`) maps an HTTP status to a `SaveOutcome`: 401
  and 403 are `DENIED`, 404 is `GONE`, 408, 429 and 5xx are `RETRY`, any other
  4xx is `REFUSED`. A request that gets no response at all is `RETRY`; before
  this it carried no code and was not retried, so the documented "retries on a
  dropped connection" was not true of it either. `flush()` (`40-writes.js`)
  branches on `err.outcome`, not on a status number or a string.
- **A refusal is sent once.** The server understood and said no; the same bytes
  get the same answer (a malformed value, a framework stamp it will not accept
  (R-67), a lone surrogate, an oversize body, a conflict). The edit is restored
  to `pending`, so it stays in the field and is merged with the person's next
  correction, and the label says "Not saved: change refused", never "check your
  connection" (the server is up).
- **The server's reason is quoted, as text and capped.** `refusalDetail()` reads
  FastAPI's string or list `detail`, collapses whitespace and cuts at 200
  characters, because the text can be derived from the request. The toast shows
  it with `textContent` (never markup) and lasts longer than the usual toast. The
  reason is English, as server messages are (R-55); the sentence around it is
  translated.
- **Limit, stated:** a refused edit stays in `pending`, so the next save of that
  project sends it again, merged with the new edit, and is refused again until the
  person corrects the field. Correcting the same field overwrites the bad value,
  which is the intent; an unrelated edit made first is held back by the same
  refusal until then. The message names the server's reason each time.
- **Rejected:** retrying a 4xx a few times "in case" (it never succeeds and delays
  the message by the whole backoff); dropping the edit on refusal (the person
  loses what they typed, which #186 and the comment on `flush()` exist to prevent);
  showing the raw status text (it names no value to change); treating 409 as a
  special case with its own message (it is a refusal like the others, and the
  server's detail says what conflicts).
- Source: #186; `tests/test_save_refused.py`.
- Enforced by: `tests/test_save_refused.py` (each refused status sent once with
  the edit kept; each transient failure sent six times; markup in the reason
  shown as text; every language; six mutations of the built page each noticed).

### D-88 Credentials in an address are detected and removed, not escaped or refused

- Status: Accepted (the owner chose option c on #194, 2026-10-10)
- **The problem.** `exportMD()`'s `line()` escapes Markdown's structure and not
  a bare address, so a GFM renderer links `https://user:pass@host/` typed into
  any field, with the password, which bypassed C-86's "http(s) with no
  credentials" (D-85 had pinned it as a known gap).
- **The rule.** One pure function, `stripAddressCredentials(text) -> {text,
  removed}`, in `app/js/00-core/55-refs.js` beside `safeUrl`, the one place that
  says what an address is. It removes the userinfo (`user:pass@`, `user@`) of
  anything with a scheme and `://` (any scheme: markdown-it's linkify links
  `http`, `https` and `ftp` bare, and any scheme in angle brackets) and of a
  protocol-relative `//` (linkify-it's defaults link it; GitHub does not). The
  userinfo runs to the last `@` before the first `/`, `?` or `#`, as the URL
  standard has it, so `https://host/path?email=a@b.c` is untouched and
  `https://a@b@host/` loses both. It cleans an `@` with nothing after it, since
  a person typing has not typed the host yet. Case-insensitive; the rules are a
  frozen set (`AddrRule`). It is idempotent, and linear in time (the scheme is
  bounded). `scrubAddressCredentials` applies it to every string inside a value.
  `user:pass@host` with no scheme is left alone: no renderer links it (tested
  with linkify-it, with and without ftp and `//`), and stripping it would eat
  ordinary email-like text. The URL parser is the test's oracle, not a
  dependency: it refuses a half-typed address that this must still clean.
- **Where it applies.** (1) Entry: `edit()` is the one funnel every typed,
  pasted or programmatic field write passes through (project setup, every
  criterion's evidence, owner and reason, checkpoint rationale, decider and
  conditions, metrics, the model card, OPTICA answers, an evidence reference's
  title); it cleans before the value is stored, queued or described in the
  history, returns what was stored so the field shows it, and toasts
  (`toast.credsRemoved`). Also a new project's name, and a hold reason. An
  evidence reference's own address field still refuses credentials outright
  (C-86), which is stricter. (2) Import: a JSON file and an older review saved
  in this browser are scrubbed in full before the record is made, with their own
  message, and `createProject` scrubs again as the net under every way a record
  is made. (3) Backstop: `line()`, the notes' Markdown (`mdInlineMarkdown`, each
  run in `mdEscape`) clean what they write, so a record already holding
  credentials (the server's, or one older than this) never prints them in the
  Markdown report, and the stored record and its fingerprint are untouched. (4)
  The change history: `logChange` cleans a copy of the earlier and the new
  value, so a credential an older record holds is never copied into an entry.
- **Not changed.** The JSON export (`_state` is the record as stored, and its
  fingerprint is over it) and the CSV. A credential stored before this rule is
  still in them, and in a server's version history. Honest limit: typed one
  character at a time, `https://user:pass` is stored by autosave before the `@`
  is typed, so a save in between can reach the server's history; the rule
  removes it from the record when the address is completed, and cannot recall a
  revision. The HTML and PDF reports never link text (every value is escaped),
  so they were not changed, and still print a credential an older record holds
  as plain text. An access id typed in the grant box is an identity, not an
  address, and is not cleaned.
- **Rejected:** escaping the scheme in the export only (`https\://...`: it hides
  the link, leaves the secret in the report and in every other copy, and relies
  on every renderer honoring the escape); leaving it (a password printed in a
  board report and offered as a click); refusing at entry (the owner chose to
  clean and tell, which does not lose what the person typed and does not block
  them); hoisting a regex constant per field (the funnel is `edit()`); stripping
  `user:pass@host` with no scheme (false positives, no link to prevent).
- Source: #194; the owner's decision on it; DECISIONS D-85; claims C-82, C-118.
- Enforced by: `tests/test_address_credentials.py` (`pixi run
  test-address-credentials`, in CI's browser job) and `tests/test_markdown_render.py`
  (any credentialed link fails the audit; mutations of the backstop are rejected).

### D-89 Agents read through per-user tokens the app mints

- Status: Accepted for the owner's decisions 1 to 4 and 5 on #164 (2026-10-10);
  the defaults listed below are Proposed, for the owner to confirm; decision 5's
  last sentence (the docs name no client or model) is amended by D-91
- **The question.** An agent has no browser session, so it cannot come through the
  front door's single sign-on, and R-06 says the API reads identity from the proxy
  header and nothing else. #164 asks for a way for a program to read the registered
  statuses on a person's behalf. Two options were on the table: (a) the app mints
  per-user bearer tokens, or (b) the front door authenticates the agent and the
  app
  keeps trusting its header.
- **Decided (owner, 2026-10-10).**
    1. **Option (a).** Per-user bearer tokens, minted by the app.
    2. **Lifetime and control.** 8 hours, fixed. The user mints their own, any role.
       An admin can revoke. A token dies with its user.
    3. **What the API returns.** Stored fields only: statuses, decisions, dates
       and
       the overdue comparison. No computed phase, flags or status colors. No free
       text in v1. People as opaque ids, never names or emails.
    4. **What an agent sees.** Only the projects the user's own dashboard shows.
       Nothing archived. No emergency access, ever.
    5. **Defaults.** No write tools or endpoints. Every agent call in the read trail,
       marked as agent access. A separate, lower rate limit. Answers carry who and
       when, never verdicts. The MCP service is PR 3: separate, optional, off by
       default. The docs name no client or model.
- **How it is built.**
    - Routes. `/api/agent/me`, `/api/agent/portfolio` and
      `/api/agent/projects/{ref}`: GET only, and the only routes that read a token.
      The routes that mint, list and revoke (`/api/agent-tokens`) take the session
      identity and never a token, so a stolen token cannot extend itself. The prefix
      is `/api/agent/` exactly, so `/api/agent-tokens` is not under it. The
      token is
      read from the Authorization header and nowhere else.
    - Token. `agt_<16 hex id>.<43 chars of url-safe base64>`: 256 random bits. The
      id is public (the row, the log, the limiter's key); only SHA-256 of the whole
      token is stored, compared with `hmac.compare_digest`; shown once. A CHECK
      in
      migration 013 fixes the lifetime at 8 hours, a trigger lets only `last_used_at`
      and a one-time `revoked_at` change, and `principal_id` is a foreign key with
      `ON DELETE CASCADE`.
    - Identity on the route. The identity header is not read, so a request carrying
      both is a bearer request. The network locks (`TRUSTED_PROXY_CIDR`,
      `PROXY_SHARED_SECRET`) still apply.
    - Visibility. `access.readable_rows()` is the one list: `GET /api/projects`
      and
      the agent API both call it, so they cannot drift; the agent adds "not
      archived", and never passes `emergency`.
    - Allowlist. A new pydantic model per response, filled field by field from named
      stored keys. A record is opaque JSON the browser owns, so its keys and values
      are whatever a writer typed (a project id, an item key, a checkpoint key
      and a
      supplement key can each be a sentence about a patient), and no pattern
      tells a
      name from an id. So a key or a value is returned only if it is a word of the
      framework definitions of the build: the item ids, checkpoint ids, status
      values, checkpoint options and supplement ids. The server image is
      framework-neutral (D-76), so the words travel the way the retirement rules
      do:
      `scripts/build_manifest.py` writes them into `manifest.json` (a `vocab` of
      four
      lists per framework), the migrate job (and an API with `RUN_MIGRATIONS=true`
      and a manifest) loads them into `agent_vocabulary` (migration 014), replacing
      the rows wholesale on every run, and the API checks each against the framework
      the record follows. Unlike the retirement rules this needs no acknowledgment
      and keeps no history: the words decide only what an agent may see and nothing
      about disposal, so a wrong load shows an agent less or more, never changes
      when
      a record is destroyed; the manifest is trusted build output with the authority
      of the definitions it is built from, and the loader is a shape and safety
      filter
      (no invisible, control or surrogate characters, 64 characters, 5,000 words
      a
      kind, no repeated JSON key) and not a judgment of content, so a poisoned
      manifest could put text in front of agents; they are outside the rule-set
      hash, and the API
      role may
      only read the table. A manifest with no words empties it, and an agent is
      shown
      no item or checkpoint. A project id is chosen by the client and can be
      anything, so it is returned as a reference (below), and dates must be real
      ISO
      dates. This replaces the hand-kept `ItemStatus`, `GateDecision` and
      `AGENT_EXTRA_VALUES`: a build of another framework carries its own words
      in its
      own manifest (D-79), so there is nothing left to list by hand.
    - Opaque ids. A person is `u_` and the first 128 bits of HMAC-SHA256 keyed by
      `AGENT_ID_SECRET`, over the identity id; a project is `pr_` and the same
      construction over the project id, the HMAC input carrying a different domain
      prefix for each. Stable in a deployment, and not reversible without the
      key (a
      pseudonym: whoever holds the key and a candidate list can test candidates,
      so
      the key is kept like a password and is in no table, and the server refuses
      a
      short, patterned or low-variety one). The principal id itself is the identity
      (usually an email) and is not opaque. This does not reopen D-54: nothing stored
      is pseudonymized. `GET /api/agent/projects/{ref}` finds the ref by
      scanning the
      rows the person's dashboard shows, so an unknown, an invisible and an archived
      project are one 404. In v1 an agent can say "project `pr_...` has criterion
      `s1-3` marked `notmet`" and cannot name the project; a name would arrive
      as an
      explicit opt-in, labeled untrusted text, as the issue says of free text.
    - Limits. The token is checked before anything is limited (one indexed read,
      no
      write). A verified token spends only its own allowance and its person's
      (120 a
      window across all that person's tokens). A failure spends only its source's
      (30 a window, then 429 with no write) and a global budget (600 a window across
      all sources, then 429 with no per-source accounting at all, so rotating source
      keys cannot make the server work or log more). A failure is a read-trail row
      only when it names a token that exists, within budgets by kind that cannot
      starve each other: wrong secrets (which anybody who has seen a public id can
      send) at most 10 per token id a window across all sources, a right secret
      on a
      stopped token and a project not visible 5 per token id, and 100 of each kind
      overall. The tallies are bounded (10,000 sources, oldest idle dropped first,
      never an active attacker's bucket reset) and O(1) per failure. What is not
      written is one aggregated `agent.failures` line a window, written by a
      background task every half window and at shutdown. The source is the socket
      peer, or the address the proxy reported when `TRUSTED_PROXY_CIDR` is set and
      the peer is inside it, validated as an IP address or `unknown`; the image
      starts uvicorn with `--no-proxy-headers`.
    - Proxy. `proxy/Caddyfile` has a handle, above the sign-on one, that forwards
      only the three GET routes, deletes sixteen identity header names it knows
      and
      sets none (the API reads no identity header on these routes, so the list is
      defense in depth and is fixed), and answers anything else under the prefix
      with
      a 404. A request that slips through to a route that needs an identity arrives
      with none and gets a 401. The API's access log drops the query string of a
      request whose decoded path is under `/api/agent/`; Caddy's log drops it
      for any
      request whose raw target is or might be an agent route (the word agent, a
      percent-encoded character, an absolute-form target, a dot or empty segment:
      Caddy routes on the cleaned path and logs the raw one) and redacts five
      token-like header names. A token in a URL path, in a header with another name,
      or logged by a front door in front of this stack is not covered, and the docs
      say so (C-114 is partial).
    - Operator. `scripts/agent_tokens.py` and `make agent-tokens` list and
      revoke, as
      the database owner, the way `make dispose` works.
- **Rejected.**
    - Option (b), a front door that authenticates the agent. Each front door
      differs, several cannot give a non-browser client a credential at all, and
      the app would still have to trust a header from a client with no session.
    - A shared service account. It violates the rule that access follows the
      person: one identity cannot be "the same staff access control" as every user,
      and the read trail would name the account and not the person.
    - Accepting a token on the existing routes. It would let a stolen token write,
      delete and mint its own successors.
    - A longer lifetime, or a refresh. The point of 8 hours is that nothing in the
      app has to notice a departure.
    - An in-app administrator role. The repository has none, and adding one to
      revoke a token would add an identity and a permission to review.
- **Proposed defaults, for the owner to confirm.** Where the owner's answer left
  a
  gap, this is what was built.
    - (a) "An admin can revoke" is an operator action (`make agent-tokens`),
      with no
      new role; a person can also revoke their own through the API.
    - (b) "Dies with the user" means the user's principal is erased from this app
      (`make dispose`, or SQL), which deletes the tokens by foreign key. Removal
      from the identity provider is **not seen**, because the app does not read
      the
      directory; the 8 hours is the bound, and the docs say so.
    - (c) At most 5 live tokens per person, settable with `AGENT_MAX_ACTIVE_TOKENS`.
    - (d) "Visible" is exactly what `GET /api/projects` lists for the person
      (access lists enforced, unclaimed projects included, as the dashboard shows
      them), minus archived. Records stamped for another framework are returned
      with
      their `framework` id and can be filtered by it; the dashboard of a build of
      one framework hides the others', and this does not.
    - (e) The API is off until `AGENT_ID_SECRET` is set (at least 32 characters).
    - (f) `overdue` is a plain comparison of a stored due date with today's date
      in
      UTC, with no look at the status, so a settled item with an old due date reads
      overdue. The dashboard's flag looks at the status and the viewer's local date.
    - (g) The per-token limit is 60 a minute (`AGENT_RATE_LIMIT_MAX_REQUESTS`);
      a
      source may fail 30 times a window (`AGENT_FAILURE_RATE_LIMIT_MAX_REQUESTS`),
      all sources together 600 (`AGENT_GLOBAL_FAILURE_RATE_LIMIT_MAX_REQUESTS`),
      and
      a person's tokens share 120 calls (`AGENT_USER_RATE_LIMIT_MAX_REQUESTS`).
      A
      429 is not a read-trail row (a flood of refusals must not become a flood of
      rows); the failures are one aggregated security-log line a window. The row
      budgets by kind (10, 5, 5 per token id, 100 overall) are defaults too.
    - (h) A refusal is a read-trail row (`agent_refused`) only for a token that
      exists, naming the person only when the secret matched (an expired or revoked
      token) and `unknown` for a wrong secret; the reason is in the row and
      never in
      the response. A project a valid token cannot see is also a row (`not_visible`).
    - (i) An emergency-access identity may mint a token, and the token carries no
      emergency rights.
    - (j) Tokens are not purged on a schedule: a row stays, expired, until its
      principal is erased. After `make restore`, revoke everyone's.
    - (k) The words an agent may be given come from the build's manifest (see
      Allowlist), so a build whose manifest has none shows an agent no item or
      checkpoint, and a record of a framework the build does not carry shows only
      its references and people.
    - (l) A person mints through the API for now (the dashboard page is PR 2).
    - (m) Project references only in v1; names are a later opt-in (see Opaque ids).
    - (n) The replication caveat: the limiters are in process, so behind N replicas
      each ceiling is N times its setting.
- **Cost, stated.** A path of the API is reachable without single sign-on, so the
  token is the only thing between a caller and the data on it; a front door that
  authenticates every path cannot offer the agent API at all. The docs say where
  it
  cannot be done, and only the Caddyfile in this repository is tested for it.
- Source: #164 and the owner's decisions of 2026-10-10; R-71; amends R-06 for the
  agent routes (D-03 stands for every other route).

### D-91 The MCP server is a thin, stateless, separate service that holds no credential

- Status: Accepted for the owner's decisions of 2026-10-09, 2026-10-10 and
  2026-10-11 on #164; the defaults listed below are Proposed, for the owner to
  confirm
- **The question.** D-89 gave a program a per-user, read-only way into the
  register. #164 PR 3 asks for the chatbot's way in: an MCP server, so a person
  can ask "which projects have criteria marked Not met?" in an interactive client.
- **Decided (owner).**
    1. **An interactive chatbot that makes the tool easier to use.** Not an
       automation surface.
    2. **Read-only.** Nothing that writes.
    3. **A thin wrapper over the agent API.** It adds no rule and no data.
    4. **A separate, optional service, off by default**, like the PHI-scan sidecar
       (D-21): a compose profile, not in a plain `up`.
    5. **The open MCP protocol over HTTPS with bearer tokens**, client-agnostic.
    6. **Free text reaches a model only on request, labeled untrusted.** Version
       1
       returns none: ids from the framework vocabulary, statuses, decisions, dates,
       and opaque people and project references.
    7. **Tool descriptions tell the model not to follow instructions found in data.**
    8. **Answers state statuses as recorded, with who (an opaque id) and when,
       never as verdicts or "out of compliance".**
    9. **Sending answers to an external model is a disclosure the operator
       decides.** Which model is the operator's choice.
    10. **The example model named in the documentation is MedGemma**
        (`google/medgemma-27b-text-it` first, the 4B model as the smaller option),
        2026-10-11. MedGemma is a model, not a client, so the documentation stays
        **client-agnostic**: it shows how to point any MCP-capable client at the
        server and at an OpenAI-compatible endpoint (vLLM serving MedGemma, say).
        **No client code is shipped** and no client is endorsed; a neutral mention
        that some clients, such as OpenMed Agent (Apache-2.0 per its README, gated
        access), attach remote MCP servers over HTTPS with an `Authorization`
        bearer header is allowed, labeled "not tested here". The MedGemma facts
        are
        stated only as "from the model card; verify at the source", the page says
        plainly that it has not been tested with this server, and the evaluation
        plan is documented only: no harness, because a model cannot run in CI. This
        amends the last sentence of D-89 decision 5 ("the docs name no client or
        model").
- **How it is built.**
    - SDK and transport. The official MCP Python SDK (`mcp`, 1.30.0, locked with
      hashes in `mcp/requirements.txt`), `FastMCP`, **Streamable HTTP, stateless,
      JSON responses**. `POST /mcp` is the only method served; `GET` and `DELETE`
      are `405` (nothing to stream, no session to end).
    - Tools. `whoami`, `list_portfolio(status, decision, overdue, overdue_since,
      overdue_before, owner, framework, limit, offset)` and `get_project(ref)`,
      each
      with typed input and an output model (`structuredContent` and the same JSON
      as text), annotated read-only. `chai_mcp.server.ToolName` is the
      allowlist, a
      test enumerates what is registered, and `chai_mcp.upstream.Route` is the
      three routes, all `GET`.
    - The token. Read from the `Authorization` header of the request that carries
      the call, forwarded in a client built for that call and closed after it
      (no pool, no cookie jar, no redirect followed), and kept nowhere. Tests walk
      what the app can reach for it, sweep the log, and mutate each way of keeping
      it.
    - Answers are checked twice. The API builds them from an allowlist (D-89); the
      service parses each into models that forbid extra fields and hold each string
      to a shape (up to four plain words of at most 48 characters, an opaque id,
      a
      date). A shape cannot tell a name that is one word from a status, which a
      test
      states: the first wall is the API's list of the build's own words.
    - Failures are a few fixed messages (`token rejected or expired`, `no such
      project...`, `the governance server is unavailable`, and so on). A 422's own
      message is cut to plain characters, a 429 carries `Retry-After`. The upstream
      body and the token are in none.
    - Isolation. `mcp` is on an internal `agent` network with `mcp-gate`, a Caddy
      with two listeners (the same pinned image as the proxy): `:8082` carries the
      proxy's `/mcp` to the service, `:8081` carries the caller's token from the
      service to the three agent `GET` routes and adds the shared secret the API
      may
      require (`PROXY_SHARED_SECRET`), which the service never holds. `mcp-gate`
      is
      on `edge` and `agent`; `mcp` is on `agent` alone. The caller's address travels
      as `X-Client-Address`, set by the gate from what the proxy reported, so the
      API's per-source limit counts the person and not the one service that carries
      every person's calls.
    - The proxy. `/mcp` is a `handle` that skips sign-on, deletes the sixteen
      identity header names, `X-Client-Address` and `X-Proxy-Secret`, sets none,
      forwards `POST`, `GET` and `DELETE` on exactly `/mcp`, caps the body at 64
      KB,
      and answers the rest of the prefix with `404`; the upstream is
      `${MCP_UPSTREAM:-mcp-gate:8082}`, so with the profile off the name does not
      resolve and Caddy answers `502`. The log's query redaction covers `/mcp`.
    - The service's own front. Host and Origin validated by the SDK's transport
      security before the token is looked at, `MCP_ALLOWED_HOSTS` required to start,
      no CORS and no `OPTIONS`, a query string refused, a 64 KB body, a 10 second
      timeout, 16 calls in flight (more are refused, not queued), one log line a
      request (method, path, status), uvicorn's access log off.
    - The image. `mcp/Dockerfile`, built like the API's: two stages, a lock verified
      by hash, digests pinned, no pip at runtime, uid 10002 with a `nologin` shell,
      started directly by `python -m chai_mcp`, a health check, read-only root,
      every capability dropped, no port published. It is built and scanned (HIGH
      and
      CRITICAL with a fix fail the job) in `security.yml`, and watched by Dependabot.
- **Rejected.**
    - A route inside the API process. It would make the API parse a chatbot's
      protocol, and could not be switched off or isolated from the database.
    - A service account for the MCP service. The access follows the person (D-89).
    - A service that stores tokens, or exchanges one for another. A stored token
      is a
      thing to steal; forwarding costs nothing.
    - Write tools, or any tool that takes a URL or a path. Read-only is the
      decision, and a URL is an exfiltration channel.
    - Stateful sessions and a server-sent stream. Nothing to stream, and a session
      is state a token could outlive.
    - Putting `mcp` on `edge`, or giving it the shared secret and the API's address.
      A compromised parser of chatbot requests would then reach the API, and the
      proxy's sign-on listener on the same network trusts a header a front door
      sets.
    - OAuth for the MCP server. The credential is the app's own per-user bearer
      token
      (D-89); a second authorization scheme would be a second thing to get wrong.
    - Shipping a client, bundling a model, or endorsing either. The documentation
      shows how to connect one; which is the operator's choice.
- **Proposed defaults, for the owner to confirm.**
    - (a) The tool names and parameters above, and that `list_portfolio` takes the
      agent API's filters unchanged.
    - (b) Stateless JSON responses and `POST` only, with `GET` and `DELETE` answered
      `405` after the proxy forwards them (so a client told `405` behaves as the
      transport says).
    - (c) The extra `mcp-gate` service and the `agent` network, rather than putting
      `mcp` beside the proxy.
    - (d) The second wall's shape (four words, 48 characters). A custom framework
      whose ids, statuses or decisions are longer or have other punctuation
      would have
      its answers refused whole until the shape is widened in `models.py`.
    - (e) The limits: 64 KB, 10 seconds, 16 in flight.
    - (f) `MCP_ALLOWED_HOSTS` is required to start; the loopback names are always
      allowed (for the container's health check).
    - (g) The SDK is pinned to the 1.x line (1.30.0). A 2.x exists and was not
      adopted.
    - (h) A query string on `/mcp` is refused (`400`), and the proxy's log
      redacts it
      anyway.
    - (i) With the profile off, `/mcp` answers `502`, not `404`: the route is in
      the
      proxy and nothing is behind it.
    - (j) The MCP tests run in the server job (they need the same PostgreSQL), from
      `mcp/`, with the package installed from `mcp/pyproject.toml`; the proxy
      and stack
      tests run in the stack job.
    - (k) `make down`, `logs`, `ps` and `prune` name the profile, so a running MCP
      service is stopped with the rest.
    - (l) The documentation names `google/medgemma-4b-it` as the 4B model, as a
      model
      card fact to verify, gives a `vllm serve` command marked untested, and
      names no
      tool-call parser (the card does not mention function calling).
    - (m) The service cannot tell a person's own call from a model's, and
      neither can
      the API: both are agent access in the read trail.
- **Cost, stated.** `/mcp` is a second path reachable without single sign-on, so
  the
  token is the only thing between a caller and the data on it, and a front door
  that
  authenticates every path cannot offer the MCP server at all. The documentation
  says
  where, per front door, and only this repository's Caddy is tested for it. An answer
  sent to a model is out of this system's hands; turning the service off does
  not stop
  a person calling the agent API with their own program, and the only switch for
  that
  is an empty `AGENT_ID_SECRET`.
- Source: #164 and the owner's decisions of 2026-10-09, 2026-10-10 and 2026-10-11;
  R-73; D-89; D-21 (the opt-in sidecar pattern).
