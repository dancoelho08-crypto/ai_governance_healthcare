# Requirements

Things that must stay true of this project. New code adheres to these unless
the user says otherwise, and the user's instruction is then recorded here.

How this file is used is set out in [CLAUDE.md](CLAUDE.md). The reasoning
behind how each requirement is met lives in [DECISIONS.md](DECISIONS.md).

Each entry has a stable ID. Never renumber or reuse an ID: other files and
issues cite them. A requirement that no longer applies is marked **Retired**
with the reason and the date, not deleted.

**Status** is one of:

- **Active**: in force. New code must satisfy it.
- **Open**: a question the project has not answered. Do not assume an answer.
- **Retired**: superseded or dropped. Kept so the history makes sense.

**Enforced by** says what fails if the requirement is broken. "Nothing" is an
honest answer and is a gap worth closing; see R-19.

## Product

### R-01 The dashboard is one self-contained file

- Status: Superseded by R-60 (2026-10-08): the Claude artifact is no longer a
  target
- The built dashboard (`docs/app/index.html`) is a single HTML document. It must
  run as a Claude artifact, open straight off disk with no server, and publish
  to GitHub Pages. Native ES modules and anything that needs a second file are
  out, because `file://` blocks module loading.
- Source is split under `app/` and concatenated by `scripts/build_app.py`.
  The built file is generated and is never edited by hand.
- Source: `scripts/build_app.py` module docstring.
- Enforced by: `pixi run check-app`, and the `build-app` pre-commit hook, which
  fails if the built file differs from its sources.

### R-02 Storage goes through one interface

- Status: Active
- All persistence uses the six-method store interface (`subscribeAll`,
  `create`, `update`, `remove`, `log`, `subscribeLog`). `ApiStore` (Docker
  stack), `DbStore` (Claude artifact) and `LocalStore` (browser) implement it.
  A new backend adds a class; it does not add a branch in the app.
- Source: README, "Evaluate it without deploying anything".
- Enforced by: Nothing.

### R-03 Never silently fall back

- Status: Active
- If a server was expected and cannot be reached, the app stops and says so. It
  must not degrade to browser-only storage, because that hands a user a working
  private workspace that looks like the shared one.
- Source: README; `app/js/20-app/80-boot.js` ("access control failing open
  into a usable app").
- Enforced by: `tests/test_boot_storage.py`.

### R-04 The mode the user is in is never ambiguous

- Status: Active
- Storage mode is the most consequential fact about a deployment and the least
  visible. Each mode must label itself truthfully, and the label for one mode
  must not be reused for another.
- History: #55 (the server mode reported "Saved in this browser") and #64 (the
  Claude artifact mode was labeled "Shared workspace", as the server mode is)
  are both fixed. Each mode now has its own header label, saved label and, for
  the artifact and browser-only modes, a standing notice in the layout.
- Source: `app/js/20-app/40-readonly.js`, `showStorageWarning` comment.
- Enforced by: `tests/test_boot_storage.py`: the saved label and the header
  label for every mode (each present, no two alike), and the artifact notice.

### R-05 The dashboard and its exports contact no third party

- Status: Active
- No webfont, CDN, analytics or other third-party request, on page load or when
  an exported report is opened. This is also what lets the Content-Security-
  Policy be as tight as it is.
- Source: `tests/test_no_third_party.py` docstring; closed issue #17.
- Enforced by: `pixi run test-no-3p`.

## Identity and access

### R-06 Identity comes from the proxy and nowhere else

- Status: Active
- The API reads exactly the identity headers the proxy sets. Never from a body,
  a query parameter, a cookie or a token. The API has no user table, no password
  hash, no login form and no token endpoint.
- Source: `server/app/auth.py` module docstring; DECISIONS D-03.
- Enforced by: `server/tests/test_auth.py`; `tests/test_proxy_identity.py`.

### R-07 The API is reachable only through the proxy

- Status: Active
- The API publishes no host port. This is the security boundary: the whole
  identity model is "trust a header", which is only safe if nothing else can
  reach the API. Adding a service to the `edge` network widens the boundary.
- Source: `compose.yaml` header; `server/app/auth.py`.
- Enforced by: `tests/test_compose_isolation.py` (the compose file), and
  `scripts/check_isolation.py`, which `make check-isolation` runs against a live
  stack: `tests/test_check_isolation.py` breaks each of its three steps and
  demands it notice, and `tests/test_stack.py` runs it against the real stack.
  (Step 3 used to assert nothing, #56.)

### R-08 Fail closed on identity

- Status: Active
- An unset or empty identity source rejects every request (401). It never falls
  back to a usable default. The stack refuses to start on a literal identity
  source, a placeholder or short database password, or a non-loopback bind over
  plain HTTP.
- Source: `proxy/Caddyfile` ("NO DEFAULT VALUE"); `scripts/preflight.py`.
- Enforced by: `tests/test_proxy_identity.py`; `tests/test_preflight.py` for
  the preflight gate. It reads `.env` the way compose does (an empty value is
  the default, an unquoted `#` after whitespace starts a comment), because
  reading it differently fails open.

### R-09 Sign-offs are attributed to the authenticated user

- Status: Active
- A checkpoint sign-off records the identity the proxy asserted and the server
  clock, not a name or date the client supplied. The server writes `signedBy`
  and `signedAt` whenever a decision is set or changed, clears them when it is
  cleared, ignores them on an unchanged decision, and refuses to let them be
  blanked while a decision stands. With identity disabled nothing is attributed.
- History: this was violated (#31). A writer could record a decision as the CMO,
  on any date, while the deployment guide claimed the opposite.
- Source: `docs/deploy.md`, "A checkpoint sign-off means something."; DECISIONS
  D-24.
- Enforced by: `server/tests/test_signoff.py` (the rules, and the exploit against
  the real API); `tests/test_stack.py` (the same exploit through a real Caddy).

### R-30 One person has one identity id, whichever way they arrive

- Status: Active
- The id is the key every access list is matched against, so the plain-header
  and JWT paths, and any front door, must give the same person the same id. The
  front door's scheme prefix (Google IAP's `accounts.google.com:`) is stripped in
  one place, after both parsers, and `make up` refuses a Google identity source
  whose `IDENTITY_STRIP_PREFIX` is not Google's, because ids stored with the
  prefix stop matching later and every project vanishes from its owner.
- History: the strip applied to plain headers only, compose passed the prefix
  through empty, and `.env.example` re-emptied it with a later line (#35).
- Source: #35; DECISIONS D-34.
- Enforced by: `server/tests/test_auth.py` (both paths agree),
  `tests/test_preflight.py` (the refusal, and the template's own Google block
  passing), and `server/tests/test_identity_repair.py` (the documented repair,
  run against PostgreSQL).

### R-31 A published export names no individual unless asked

- Status: Active
- The Croissant exporter's default `maintainer` is an organizational contact, not
  the review team or clinical sponsor, and is omitted when no organization is
  recorded. `--include-maintainer-names` publishes the names and prints a
  warning that lists them, as `--include-cohort-detail` does for cohorts.
- Why: a published record that names the people responsible for a clinical
  system links identified individuals to it, its site and a time. That is
  personal data under GDPR Art. 4(1).
- History: names were emitted unconditionally while cohort detail was gated
  (#60).
- Source: #60.
- Enforced by: `tests/test_croissant_export.py`, which also checks the output
  still validates against `mlcroissant`.

### R-32 The containers run with the least privilege they work with

- Status: Active
- The proxy (the only service reachable from outside) runs as a non-root user,
  drops every capability but `NET_BIND_SERVICE`, and has a read-only root
  filesystem. The API drops every capability and is read-only. Every service
  sets `no-new-privileges` and a memory, CPU and process limit. The ownership
  fixer `proxy-perms` has no network and only `CHOWN` and `DAC_READ_SEARCH`. The
  cloud image `proxy/Dockerfile` is unprivileged to match.
- `db` cannot drop all capabilities: the Postgres entrypoint starts as root and
  drops to the postgres user.
- A change that adds a service, a capability, a network or a root user to this
  set needs a decision, not a drive-by edit.
- History: the proxy ran as root with default capabilities, and no service had
  a limit (#50).
- Source: #50; DECISIONS D-35.
- Enforced by: `tests/test_compose_isolation.py` (the rule, with a mutation test
  for each part, and the cloud Dockerfile) and `tests/test_stack.py`, which
  `docker inspect`s the running containers.

### R-33 A denial is logged, and the log never carries the document

- Status: Active
- Every authorization refusal on an existing project (the 404 that hides it
  from a non-reader, and the 403s for a missing write or owner right) emits one
  `access.denied` security event: actor, project id, what was needed, what the
  user held, and the status returned. It never logs document contents.
  A project that does not exist is not a denial.
- Why: a compromised staff account probing other people's records left no trace
  (#53). Denied access is the highest-signal, lowest-volume security event.
- Source: #53; 45 CFR 164.308(a)(1)(ii)(D).
- Enforced by: `server/tests/test_denial_log.py`, against a real PostgreSQL.

### R-34 The audit history is reachable in full, and a window says it is one

- Status: Active
- `GET /api/projects/{id}/log` pages with a cursor (`X-Log-Next`, `?before=`) and
  reports the total (`X-Log-Total`), so every entry is reachable through the API.
  The dashboard's changelog and every export (markdown, printable report) say
  "Showing the newest N of M entries" whenever they show less than all. A window
  must never pass for the whole history. Browser-only mode keeps every entry and
  says when its storage is full.
- Why: entry 61 onward was unreachable through the API, exports carried the window
  silently, and browser-only mode deleted entry 101 (#40). 45 CFR
  164.316(b)(2)(i) and 164.312(b).
- Not done: a streaming full-history export route. The cursor and the 500 cap
  reach it, and `server/README.md` shows how.
- Source: #40; DECISIONS D-36.
- Enforced by: `server/tests/test_log_paging.py` (a real PostgreSQL: every entry
  exactly once, in order) and `tests/test_log_window.py` (the disclosure in each
  export, the deeper page, the cap, `LocalStore`).

### R-35 The API serves as a role that cannot undo the append-only triggers

- Status: Active
- The append-only guarantees (R-10, R-12, R-27) are triggers, and a table's owner
  or a superuser can disable them in one statement. So the API serves as a
  restricted role (`app/roles.py`): the project tables' DML it needs, no
  `TRUNCATE`, no DDL, no trigger control, no access to `schema_migrations`. The
  owner's credential lives in the one-shot `migrate` job and is **not** in the
  API's environment. `GRANTS` lists every table, and a test fails if one exists
  that it does not name.
- A deployment with no restricted role still works, serves as the owner, logs a
  warning at startup, reports `"db_role":"owner"` on `/api/health`, and fails
  `make doctor`. It is weaker, not broken.
- History: the API ran migrations and served traffic as the table owner, a
  superuser in compose, so the triggers constrained the application's bugs and
  not the application (#48).
- Not covered: a PostgreSQL superuser bypasses everything; guard that password.
  The cloud job definitions in `docs/deploy.md` have not been run against a real
  managed database.
- Source: #48; DECISIONS D-37.
- Enforced by: `server/tests/test_roles.py` (the statements it is refused, its
  exact privileges, idempotence and rotation), the whole `server/` suite run as
  the restricted role (`TEST_APP_ROLE=1`, in CI), `tests/test_compose_isolation.py`
  (the API holds no owner credential), `tests/test_stack.py` (the running API
  cannot disable a trigger with the credential it holds), `tests/test_preflight.py`
  and `tests/test_doctor.py`.

### R-36 An identity id can be turned into a person, without opening a directory

- Status: Active
- The name and email the proxy asserts are recorded against the id as people sign
  in (`principals`), and `GET /api/principals?ids=` returns them for the caller
  themself and for people named on a project the caller can read, and for no one
  else. The dashboard shows a person where it used to show "someone" (the
  server-backed mode shows the id when it cannot name someone; the artifact and
  browser-only modes keep "someone"). Exports carry the names.
- This creates personal data about staff (name, email, first and last seen),
  documented in `docs/deploy.md` for a record of processing. It is not erased by
  a project purge (#57).
- Source: #39; DECISIONS D-38.
- Enforced by: `server/tests/test_principals.py` (recording, the visibility rule,
  the bounds, that a failure never fails a request), `tests/test_people.py` (the
  real `ApiStore` and name resolution in the DOM and in the exports) and
  `tests/test_stack.py` (through a real proxy).

### R-37 A record can always be reached, and every emergency use is recorded

- Status: Active
- An identity listed in `EMERGENCY_ACCESS_IDS` holds owner rights on every
  project, so a record whose only owner has left stays readable, exportable,
  reassignable, archivable, deletable and purgeable (45 CFR
  164.312(a)(2)(ii)). It is **off by default**: with the variable unset nobody
  has it.
- **Every use is recorded where the project's owners will see it**: a system
  entry (`event: access.breakglass`, never redacted by a purge) in the project's
  own audit log, plus an `access.breakglass` security event. Reads of the same
  project by the same person are throttled to one entry per ten minutes (a
  dashboard polls); writes never are. A delete cannot leave a log entry (the log
  goes with the project) and is recorded by the security event and the
  tombstone's `deleted_by`.
- The identity is only ever what the proxy asserted, compared to configuration.
  A client cannot claim it.
- Owners are warned in the dashboard when they are a project's only owner, and
  `make doctor` counts such projects.
- A path around the access lists that is not recorded is a backdoor, so a change
  that adds one (a new route reachable by this identity, say) must record it.
- Source: #42; DECISIONS D-39.
- Enforced by: `server/tests/test_breakglass.py`, `server/tests/test_offboarding_sql.py`,
  `tests/test_access.py` (the sole-owner warning), `tests/test_doctor.py`, and
  `tests/test_compose_isolation.py` (the setting reaches the API).

### R-38 A revoked session loses its event stream, and a lost stream is reported

- Status: Active
- The API ends an event stream after `SSE_MAX_LIFETIME_SECONDS` (default 900),
  so the browser must reconnect through the front door and be authenticated
  again. A stream that is closed for good is reported in the dashboard and not
  swallowed.
- The dashboard can lock itself after `IDLE_LOCK_MINUTES` of inactivity (off by
  default), saving unsaved edits first, and show a sign-out link to
  `SIGN_OUT_URL`, which is validated as https or a path on this origin and
  re-validated in the browser before it becomes a link.
- The real automatic-logoff control is the front door's session lifetime (45 CFR
  164.312(a)(2)(iii)); `docs/deploy.md` says where to set it for each, and says
  those settings are from the providers' documentation and not exercised here.
- Source: #49; DECISIONS D-40.
- Enforced by: `server/tests/test_session.py` (a stream ends by itself and
  reconnecting requires identity again; the URL allowlist; the settings in
  `/api/health`), `tests/test_session_ui.py` (the lock, saving first, the link
  and its allowlist, the lost stream, and boot from the server's settings), and
  `tests/test_compose_isolation.py` (the settings reach the API).

### R-39 Security events are named, structured and separable

- Status: Active
- Every security-relevant event (a missing identity, a rejected peer or shared
  secret, an unreadable or wrong-audience token, a cross-site write, a denial,
  emergency access, a create, a delete, a purge, a tripped rate limit, a refused
  stream) is emitted through `app/securitylog.py` with a **stable name** from
  `SecurityEvent` and fields that are ids and facts, never a document, a token
  or a secret. In `LOG_FORMAT=json` (the default) each is one JSON object per
  line tagged `"stream": "security"`, and the security stream is held at INFO
  whatever `LOG_LEVEL` says.
- The names are an interface: `docs/deploy.md` lists them and a test fails if
  the list and the enum drift. A new event is a new enum member and a new row.
- Every service's log is capped by the `json-file` driver. That bounds local
  retention; it is **not** a retention policy, and this repository collects,
  retains and alerts on nothing itself: the sink and its retention are the
  operator's, and the per-cloud settings in the docs are unverified.
- Source: #38; DECISIONS D-41.
- Enforced by: `server/tests/test_security_events.py` (the real output, each
  event, no secret in it, no forged second line),
  `tests/test_compose_isolation.py` (the caps), and `tests/test_stack.py` (the
  running API's own log).

### R-40 Every read of a record is recorded, in the transaction of the read

- Status: Active
- A list, a project's revision list, one revision, a project's audit log, an
  event stream attach and an export each write one row to `access_event` (actor,
  action, project, revision, the address the proxy reported) in the same
  transaction as the read, and emit the same fact as a security event. A read
  that cannot be recorded is not served. A refused request is an `access.denied`
  event instead, because nothing was disclosed.
- `access_event` is append-only, has no foreign key (it outlives the project it
  names) and holds ids and facts, never content. The restricted role may only
  `SELECT` and `INSERT` it.
- **Exports are the limit.** They are built in the browser from data it already
  fetched, so the dashboard reports each one with a beacon. That is a record of
  ordinary use, not a control: a client can omit it. The reads that fetched the
  data are recorded and bound what any export could hold.
- Kept for R-54's read-trail period. Since R-56, a row past it and not under a
  litigation hold may be deleted, by the database owner only; the trigger refuses
  any other DELETE, and every UPDATE.
- Why: "which records did a compromised account open, and did it export any?"
  had no answer anywhere, and 45 CFR 164.312(b) is required (#33).
- Source: #33; DECISIONS D-42.
- Enforced by: `server/tests/test_access_audit.py` (each route, the transaction,
  the refusal case, append-only, the constraint matching the enum, the
  investigator's query from the docs), `tests/test_export_beacon.py`, and
  `tests/test_stack.py` (rows in the real database through the proxy).

### R-41 A backup is restored, not assumed

- Status: Active
- `make verify-backup` restores the newest dump (or `FILE=`) into a throwaway
  PostgreSQL of the **same major version as production** (read from
  `compose.yaml`), with no network, and exits non-zero unless it restored
  cleanly with its tables, its rows and its **append-only triggers**. Each stage
  of the pipeline (decrypt, gunzip, restore) is checked on its own; the
  container is always removed; no backups at all is a failure, not a pass.
- `make restore` overwrites the live database, so it asks the operator to type
  `YES` (`CONFIRM=YES` for automation), as `make prune` does.
- `make backup` is documented as a tool, not a plan: it needs a scheduler, a
  copy outside the host and account, and a restore test, each a decision.
- Not done: this repository schedules nothing and holds no backups; RPO and RTO
  are the operator's to set, and the per-platform durability flags in
  `docs/deploy.md` are from provider documentation and not exercised.
- Source: #52; 45 CFR 164.308(a)(7); DECISIONS D-43.
- Enforced by: `tests/test_verify_backup.py` (a real dump restored; the wrong
  passphrase, a truncated dump, a dump that lost its triggers and a missing file
  each fail and leave no container; the prompt).

### R-42 Encryption at rest is a decision on the record, not a default

- Status: Active
- The stack's own `pgdata` volume is not encrypted by this repository and the
  docs say so. `make up` refuses a stack that is reachable beyond this machine
  (a non-loopback `HTTP_BIND`) and uses its own database volume until
  `STORAGE_ENCRYPTION_CONFIRMED=1` is set, which means someone put Docker's data
  root on an encrypted volume and said so. Only `1` counts. A managed database
  (`DATABASE_URL`) is the provider's storage and needs no confirmation here.
- `make doctor` reports what the host shows under the volume and says plainly
  when it cannot tell. It never infers "encrypted" from silence.
- It **cannot verify** encryption: nothing in a container can. The confirmation
  is a declaration, which is what an addressable standard (45 CFR
  164.312(a)(2)(iv)) asks for. The docs are conditional on whether the system
  holds ePHI, because that is open (R-21).
- Since R-49 (patient data out of scope), the docs are no longer conditional:
  the standard is the practice followed, and the exposure is the review record
  and staff personal data (#121, D-52).
- Not covered: column- or document-level encryption, which would break the
  `jsonb` merge and every query.
- Source: #47; DECISIONS D-44.
- Enforced by: `tests/test_preflight.py` (the refusal, the exact accepted value,
  the exemptions) and `tests/test_doctor.py` (what is reported for each host
  shape).

### R-43 What runs is what was reviewed, and something watches it

- Status: Active
- The API's dependencies are installed only from `server/requirements.txt`, a
  hash-pinned lock (`pip install --require-hashes`), regenerated with `make
  lock`. Every base image (both Dockerfiles, the database and proxy in
  `compose.yaml`) is pinned by digest. Every GitHub Action is pinned by commit
  SHA. The runtime image ships no `pip`.
- Dependabot watches pip, both Dockerfiles, compose and the actions, in the
  directories that hold them. Updates arrive as pull requests that pass the same
  `tests passed` check as any change.
- `.github/workflows/security.yml` builds our images and scans them and the lock
  weekly and on every pull request, failing on a HIGH or CRITICAL finding **with
  a fix available**, and writes a CycloneDX SBOM. Findings in the official
  database and proxy base images are reported, not blocking. `.trivyignore` is
  empty and an entry needs a reason and a date.
- `SECURITY.md` says how to report privately and how remediation is ordered by
  severity. Since D-58 it states **no** response or fix times: the project has
  one developer, and the owner commits to none.
- A scheduled job must not push to `main`, which is protected: the CHAI snapshot
  goes to a branch and a pull request.
- Not done: signing or attesting images (the issue's own non-goal). Pixi, which
  locks the docs and test tooling, is not watched by Dependabot.
- Private vulnerability reporting, Dependabot alerts and Dependabot security
  updates are **repository settings**, turned on by the owner on 2026-10-08.
  Nothing in CI checks that they stay on.
- Source: #37; DECISIONS D-45.
- Enforced by: `tests/test_supply_chain.py` (every rule, with a mutation test,
  and the real image built from the lock, importing, with no pip and the locked
  version), `tests/test_workflows.py` (the new test is run by CI), and
  `security.yml` itself.

### R-44 How fast the append-only tables grow is visible

- Status: Active
- `make doctor` reports the revision count and average size of
  `project_version`, the sizes of the audit log, the read trail and the
  database, and says these never shrink by themselves. It sets no threshold.
  `docs/deploy.md` ("Disk and growth") gives the growth model, what each table's
  rows are, and the disk alert to set on each platform.
- Not decided: a retention policy, so nothing is ever trimmed. That waits on the
  retention question (#57). (Since R-54 the periods are decided; nothing applies
  them yet.)
- Why: a full disk stops the audit trail from recording, the one failure this
  system must not have, and nothing measured it (#54).
- Source: #54; DECISIONS D-46.
- Enforced by: `tests/test_doctor.py` (what is reported, and that an unreadable
  answer is skipped, not a crash).

### R-45 The deployment guide does not choose where the data lives

- Status: Active
- No command example in `docs/deploy.md` names a concrete region. Each takes it
  from a variable (`REGION`, `LOCATION`) the reader fills in, and a "Data
  residency" section says the region is their decision, lists example EU regions
  per provider (marked unverified), and raises the cross-border transfer
  question for a data protection officer or counsel.
- The guide gives no legal advice and never says a region is adequate or
  compliant.
- Why: every example named a US region, so a hospital that copied them stored
  records in the US without deciding to (#58).
- Source: #58; DECISIONS D-47.
- Enforced by: `tests/test_deploy_residency.py` (run by CI as
  `test-deploy-residency`, with mutation tests for each rule).

### R-46 One person's data can be found, and what is erasable is written down

- Status: Active
- `make subject-access WHO=<identifier>` reports every table and column that
  holds the identifier, with row counts and projects, and changes nothing. A new
  column that records who did something must be searched by it, or a test fails.
- `docs/privacy.md` states what personal data the server keeps, that no retention
  period is decided, what a purge destroys and what it cannot, that a restore
  brings purged content back, and carries a draft Art. 30 entry. It gives no legal
  advice and does not say the software complies with any law.
- In the dashboard, **Search all text** lists every project the viewer can open
  whose current text contains a phrase, archived ones included, with where it
  was found and a link to each. A name also matches the ids it is stored under.
  It says it does not search earlier versions or the audit log.
- Why: a subject access request meant hand-written SQL over six columns, and there
  was no position a DPO could point at (#57).
- Source: #57; DECISIONS D-48.
- Enforced by: `tests/test_subject_access.py` (real PostgreSQL: every location,
  hostile input, read-only, the schema-drift check, and the restore interaction)
  and `tests/test_text_search.py` (the dashboard search, in a real browser).

### R-48 An export says which storage mode produced it

- Status: Active
- The printable HTML (and so the PDF), the Markdown report, the JSON export and
  the portfolio CSV each state the storage mode that produced them, in the
  header's own `MODE_LABEL` words, with a sentence on what that means for
  sign-offs and audit (`MODE_PROVENANCE`). JSON carries it as `storage` with a
  stable machine `mode`, and the Croissant exporter repeats it in the
  description. Browser-only exports say sign-offs are self-asserted.
- The text says where the record was kept, never whether that place is approved
  for any class of data (R-21 is open). One mode's wording is never another's
  (R-04).
- Source: #93 (split from #64); DECISIONS D-49.
- Enforced by: `tests/test_export_provenance.py`, per mode and per format, in a
  real browser, plus the Croissant record.

### R-49 Governance metadata only, never patient-identifiable data, in any mode

- Status: Active
- The owner's decision on #34 (option 1), 2026-10-08: the tool holds governance
  metadata only. Patient-identifiable information must never be entered, in any
  storage mode, the self-hosted server included. A governance review has no need
  for it, and organizational policy prohibits it.
- Stated at the top of `README.md`, `docs/index.md` and `docs/deploy.md`, as a
  row in the `docs/running.md` comparison, and in the app in all three modes
  (`SCOPE_NOTICE`, one definition). No doc may call any mode suitable or
  approved for patient data.
- It is a policy, not a technical control, so the wording is an instruction and
  never a claim that no such data is present. The purge path stays as the way to
  correct a mistake.
- Staff identifiers are still personal data wherever GDPR (or a similar law)
  applies to the deploying organization; that is the deployer's to determine
  (`docs/privacy.md`). The controls exist for the integrity of the record and
  for that staff data.
- Supersedes: R-21 (answered).
- Source: the owner, on #34; DECISIONS D-50.
- Enforced by: `tests/test_data_scope.py` (docs, with mutation tests) and
  `tests/test_boot_storage.py` (the notice in each mode, in a real browser).

### R-50 A small, rule-based scan, not a detector model

- Status: Active
- The owner's decision, 2026-10-08, answering R-22: no model-based PHI
  detection. The opt-in sidecar (#65) and de-identifying the Croissant export
  (#67) are not built. `make phi-scan` (#66) checks the stored records on demand
  for patterns that look like a pasted patient identifier with few false alarms:
  SSNs, and medical record numbers, dates of birth and patient names when labeled
  as such; phone numbers outside the model card's contact field.
- It does not look for names or dates on their own: a governance record is made
  of them, and a detector that flags every record is one people learn to ignore.
- It scans the live records, unpurged revisions and unredacted audit entries. It
  reports location and kind, **never the matched text**, and never says that no
  patient information is present.
- Why: the scope is governance metadata only (R-49), so the scan checks a policy;
  it is not what makes holding patient data acceptable.
- Supersedes: R-22 (answered).
- Source: the owner; #66; DECISIONS D-51.
- Enforced by: `tests/test_phi_scan.py` (the patterns on pasted and on
  governance text, the dashboard's sample projects producing no match, and the
  real script against a real PostgreSQL).

### R-51 A HIPAA citation names a practice, not an obligation

- Status: Active
- Patient data is out of scope (R-49), so the HIPAA Security Rule does not bind
  this system. Where the docs cite one of its standards, they say it is the
  practice the control follows; a sentence that says what the rule *requires*
  must say it is about systems that hold ePHI. `docs/deploy.md` says this once,
  near the top.
- The controls are unchanged: none is weakened or made optional by this.
- Source: #121, following the owner's decision on #34; DECISIONS D-52.
- Enforced by: `tests/test_data_scope.py` (every page under `docs/` and the
  README, with mutation tests).

### R-52 No key in a document reaches an object's prototype

- Status: Active
- Every dashboard helper that merges, reads or writes by key (`deepMerge`,
  `setLocal`, `patchFromPath`, `edit`, `get`) skips `__proto__`, `constructor`
  and `prototype` (`UNSAFE_KEYS`). A new helper that walks a document by key
  uses `safeKey` too.
- Why: a project document is JSON any writer controls, and `JSON.parse` makes
  `__proto__` an ordinary key. Before this, `deepMerge` wrote through it into
  `Object.prototype`. Nothing reached it with untrusted input yet; nothing
  stopped a future caller from doing so (CodeQL, #124).
- Source: #124.
- Enforced by: `tests/test_untrusted_keys.py` (each helper, in a real browser,
  with a probe shown to catch a naive merge). It failed on four checks against
  the build before the fix.

### R-53 A restore does not undo a purge

- Status: Active
- `make restore` reads every purge in the live database into a ledger before it
  overwrites anything, and re-applies the ledger after, with the original time
  and person and a system entry in each project's audit log. A row written after
  a purge is never part of it, whatever its number.
- When the live database cannot be read, the restore says that purges will not
  be re-applied and carries on. Every `versions.purged` security event carries
  what a re-apply needs (`incarnation`, `purged_at`, `through_rev`,
  `through_seq`), so the ledger can be rebuilt from the security log.
- Why: a dump taken before a purge still holds the content, so an ordinary
  recovery undid an erasure without anyone noticing (#57, #116).
- Source: #116, #57 (option 4); DECISIONS D-55.
- Enforced by: `tests/test_purge_ledger.py` (a real dump, purge, restore and
  re-apply on PostgreSQL, with a mutation test for the time guard, and the
  Makefile's order), `server/tests/test_security_events.py` (the event's fields
  match the rows the purge changed) and `tests/test_verify_backup.py` (the
  restore reads the purges before it overwrites).

### R-54 Retention periods

- Status: Active
- The owner's decision, 2026-10-08, answering R-47:
    - a project, its revisions and its audit log: the life of the AI solution,
      plus 6 years after it is retired;
    - the read trail: 6 years, or the organization's audit-log policy if shorter;
    - the security event log: the organization's security-log policy;
    - staff names and emails (`principals`): while active, then as long as a
      retained record refers to them;
    - backups: 35 days rolling, plus any archive the backup policy keeps.
- The organization's own records retention schedule takes precedence, and a
  litigation hold suspends any period. `docs/privacy.md` states the periods and
  why, and its Art. 30 draft points to them.
- Applied since R-56: `make dispose` reports what is past these periods and
  disposes of it, staff names and emails included (D-64). The security log and
  backups are outside the database and follow the organization's own policies.
- Supersedes: R-47 (answered).
- Source: the owner, on #57; DECISIONS D-56.
- Enforced by: `server/tests/test_retention.py` for the record, read-trail and
  `principals` periods.

### R-55 The dashboard's languages, and what may be shown untranslated

- Status: Active
- The owner chose, 2026-10-08: English, Spanish, French, German, Hindi, Russian
  and Mandarin, written as Simplified Chinese (`zh-Hans`), and later the same
  day Hebrew (`he`), the first language written right to left. The choice is
  per browser, not stored with a project.
- A right-to-left language mirrors the whole layout (`<html dir>`, logical CSS
  properties), and user-typed text and English fallbacks keep their own
  direction (D-63). `check-i18n` fails on a physical left or right.
- Every string a reader sees comes from `app/i18n/<tag>.json`, embedded in the
  single file (R-01); English is the source. `check-i18n` fails on a missing or
  extra key, a changed placeholder, a missing plural form, markup in a value, or
  an unused key.
- Translations are machine-drafted. A safety-bearing string (`"@meta".safety`)
  shows in English in a language until a reviewer is recorded for it in that
  catalog.
- Reviewed so far: Simplified Chinese, approved by Cody Chen (the owner's
  report, 2026-10-08), recorded for every safety-bearing string in
  `zh-Hans.json`, which therefore shows its warnings in Chinese. Its framework
  and metric-name notes cite that review instead of calling the wording
  machine-drafted (the owner's instruction, 2026-10-08); they still call it
  unofficial, because it is not CHAI's.
- Dates and relative times use the chosen language. Since D-60, the HTML, PDF
  and Markdown exports are written in the reader's language and name it; the
  JSON and CSV exports stay English (a machine contract), as do server messages.
- Since D-60, the framework content is translated too, each translated screen
  marked as an unofficial translation; stored values (decisions, categories,
  metric names) stay English.
- Hard-coded text is a ratchet: the pseudo-locale count in
  `tests/i18n_baseline.json` may only go down. Text code sets on screen at run
  time (a toast, a label a handler swaps, a tooltip), which that count cannot
  see, must go through `t()`; `check-i18n` fails on an English literal there.
- Source: the owner, on #80; DECISIONS D-59.
- Enforced by: `tests/test_i18n.py` (real browser), `tests/test_check_i18n.py`
  (every rule shown failing) and the `check-i18n` hook.

### R-56 Records past their retention period are disposed of, unless held

- Status: Active; what "retired" means is amended by R-66 (2026-10-10)
- The owner's decision, 2026-10-08, on #57: the exception to the append-only
  rule (R-10, R-40) that applying R-54 needs is granted, on these terms.
- **Disposal is a purge.** A retired project past its period loses its live
  record (a deletion record is written, as for any delete) and the content of
  its revisions (the rows keep number, author, time and hash, R-12). A deleted
  project's history is purged the same way. Read-trail rows past their period
  are deleted. So is a person's name and email (`principals`) once they have not
  signed in for the read-trail period and no retained record names them
  (D-64). Nothing else is removed.
- **An operator runs it.** `make dispose` reports and changes nothing;
  `make dispose APPLY=1 BY=<name>` disposes, in one transaction, and writes a
  `disposal_run` row with who ran it, the periods and what went. Only the
  database owner can: the API's role cannot run `dispose_due()` or delete from
  `access_event`.
- **A litigation hold stops it.** A project whose latest `retention_hold` row is
  a placement is kept, with its read trail. Holds are append-only and need a
  reason. Only an owner of the project may place, lift or see one.
- Retired means checkpoint A, B or C decided "Stop" or D decided "Retire", the
  dashboard's own rule. The clock starts at the later of that decision's date
  and the record's last change.
- Source: the owner, on #57; DECISIONS D-62.
- Enforced by: `server/tests/test_retention.py` (real PostgreSQL: what is due,
  what disposal leaves, holds, the trigger, the API role refused, the retired
  rule kept equal to the dashboard's), `tests/test_dispose.py` (the script,
  against real migrations), `server/tests/test_holds.py` (the hold API) and
  `tests/test_holds_ui.py` (the setup page).

### R-57 The docs home page speaks to a hospital executive, and does not overclaim

- Status: Active
- The owner's instruction, 2026-10-08: the docs say why the project exists and
  what gap it fills in hospital AI governance, in terms a hospital CEO would
  understand and could act on, and the rest of the docs follow the code.
- `docs/index.md` and `docs/adopting.md` make the case, and they state the limits
  as plainly as the benefits: no license fee but also no support contract, no
  claim that it makes patients safer, no certification, no patient data. They
  claim no customer, price, support term or certification the project cannot back.
- The pages are organized by who reads them (executive, governance committee, IT
  and security, privacy and records, developer), and a page that states what the
  software does is rewritten when the code changes it.
- Source: the owner, this session; DECISIONS D-65.
- Enforced by: `tests/test_data_scope.py` (the data scope leads each page a
  deployer reads first) and `pixi run check-claims` (a security sentence names its
  test). The rest is by review: nothing checks that a page's prose is true.

### R-58 An export carries a SHA-256 fingerprint of its record

- Status: Active
- The owner's instruction, 2026-10-08, closing #150: the fingerprint notice said
  a SHA-256 travels in the JSON export, and it did not. The JSON export, the HTML
  report (which the PDF prints) and the Markdown report each carry a SHA-256 and
  an MD5 of the record, and the JSON carries the project id they cover.
- The MD5 equals the one the setup page and the change log show, so a quoted
  fingerprint ties an export to the record on screen. MD5 is a version
  fingerprint only. A hash of a file anyone can edit is evidence of tampering only
  if the hash is kept somewhere the editor cannot reach, and the documentation
  says so.
- Source: the owner, on #150; DECISIONS D-66.
- Enforced by: `tests/test_fingerprint.py` (the digest against `hashlib`, the
  export recomputed in Python from the file alone, what moves it, tampering
  noticed, the reports and their translation, the schema).

### R-59 Text a person types stays text

- Status: Active
- The owner's instruction, 2026-10-08: scan for injection attacks and guard
  against them (#155). A governance record is written by many people and read by
  a board and a regulator, and the dashboard's page policy has to allow inline
  script (R-01), so escaping is the barrier and has to hold everywhere.
- Every string in a project, every key's value, the change log, people's names,
  the search box, saved interface state, the legacy record and an imported file
  reach the screen, the exports and the database as text: nothing runs, nothing
  becomes markup, a Markdown export cannot be made to start a heading, a link to
  a script, an image or raw HTML, a spreadsheet cell is not a formula, and no
  SQL is built from text.
- A new way of turning text into markup (an `eval`, a URL built from text, an
  unescaped attribute value, a new `innerHTML`) is reviewed before it is added.
- The proxy serves a policy that allows the dashboard's script by its hash, not
  by `'unsafe-inline'` (D-68), as a second barrier. The static Pages copy and
  the Claude artifact host set their own headers, so there escaping is the only
  one.
- Source: the owner, on #155; DECISIONS D-67.
- Enforced by: `tests/test_injection.py`, `tests/test_check_injection.py` with
  `pixi run check-injection`, `server/tests/test_sql_injection.py`.

### R-60 One self-contained file, for the deployed stack and the example page

- Status: Active
- The owner's decision, 2026-10-08: the Claude artifact mode is removed. The
  dashboard runs in two places only, the deployed stack (served by the proxy
  from PostgreSQL) and the example page (GitHub Pages, or a file opened from
  disk, with everything in the browser).
- The built dashboard (`docs/app/index.html`) is still a single HTML document
  with no second file, because `file://` blocks module loading and the example
  page must work opened from disk. Source is split under `app/` and
  concatenated by `scripts/build_app.py`; the built file is generated and never
  edited by hand.
- The page carries its own Content-Security-Policy as a meta tag first in its
  `<head>`, the same policy the proxy sends (D-68), so it holds on both.
- Supersedes: R-01. Amends the lists in R-02 (`ApiStore` and `LocalStore` are
  the implementations; `DbStore` is gone) and R-04 (there is no artifact mode or
  notice to label); the entries keep the history.
- Source: the owner, this session; DECISIONS D-69.
- Enforced by: `pixi run check-app`, the `build-app` pre-commit hook,
  `tests/test_boot_storage.py` (each mode's label and notice) and
  `tests/test_csp.py`.

### R-28 A project's creator is always one of its owners

- Status: Active
- Creating a project lists the caller first among its owners, whatever the body
  says, and keeps any other owner the body names (so "create and share" works).
  The client's `owners` list can neither attribute a record to someone who did
  not make it nor leave it with no reachable owner.
- Applies when identity is enforced (`REQUIRE_IDENTITY`); with it off nothing
  is attributed.
- History: the client's `owners` was kept verbatim (#44).
- Source: #44.
- Enforced by: `server/tests/test_access.py`
  (`test_creator_stays_an_owner_when_naming_someone_else` and the tests beside
  it), against a real PostgreSQL.

### R-29 A Docker build context holds only what its Dockerfile copies

- Status: Active
- `proxy/Dockerfile` builds with the repository root as its context, so the root
  `.dockerignore` is an allowlist (`*`, then the two paths the Dockerfile COPYs).
  `.env`, `backups/`, `.git/` and the licensed source PDF must never be sent to
  the daemon, whatever a Dockerfile happens to copy. `server/.dockerignore` keeps
  `.env*` and the tests out of the API image's context.
- A new `COPY` of another path needs that path allowed in the same change.
- History: no root `.dockerignore` existed, so every build uploaded the whole
  tree (#63). The image never held the secrets; the exposure was the context
  itself, on a remote or shared builder, one `COPY . .` from a published secret.
- Source: #63; DECISIONS D-32.
- Enforced by: `tests/test_dockerignore.py`, against the real contexts and a
  real build, with decoys; it also shows the decoys leak without the file.

## Audit and data

### R-10 The audit log and version history are append-only

- Status: Active
- `project_log` refuses UPDATE. `project_version` refuses DELETE and refuses any
  UPDATE except a purge. `at` and `by` on a log entry are overwritten
  server-side.
- Source: `server/migrations/001_init.sql`, `003_version_access.sql`.
- Enforced by: database triggers; `server/tests/test_versions.py`. The triggers
  bind a role only if it cannot disable them, which is R-35.

### R-11 History outlives the record it describes

- Status: Active
- Deleting a project does not delete its version history, and history keeps the
  access rules the record had when it was written, so deletion never widens
  access.
- Source: `002_versions.sql`, `003_version_access.sql`, `004_version_incarnation.sql`.
- Enforced by: `server/tests/test_versions.py`.
- Note: this is in tension with erasure, which is why deleting a project is NOT
  erasure and a separate, explicit purge exists (R-12, D-29).

### R-12 Disposal leaves a tombstone, not a gap

- Status: Active
- Purging a version empties its content and keeps its revision, author,
  timestamp and original `content_md5`, so "this existed and was purged by whom
  and when" stays answerable.
- A purge also redacts the project's audit log in the same transaction, by
  whitelist, because the client writes the values into the entry's prose and may
  add any field it likes (#36). The database permits that one transition and
  refuses any other UPDATE.
- Source: `003_version_access.sql`.
- Enforced by: `server/tests/test_versions.py`.

### R-27 Deletion is auditable, and erasure is a separate explicit step

- Status: Active
- Deleting a project writes a permanent, append-only tombstone (who, when, what
  it last hashed to) and keeps the version history. Destroying the content of the
  history and the audit log is a separate, owner-only, irreversible step, offered
  in the delete dialog only where there is a history to destroy, and ordered so
  that a failure never leaves the user believing data is gone.
- The documentation says that deleting is not erasure, and what no step reaches:
  earlier backups, and the identifiers of the people who made changes.
- Source: #36; DECISIONS D-29.
- Enforced by: `server/tests/test_disposal.py`, `tests/test_disposal_ui.py`, and
  `tests/test_stack.py` through a real proxy.

### R-13 Backups are encrypted

- Status: Active
- `make backup` refuses to run without a passphrase and writes only encrypted
  dumps. A plaintext dump requires an explicit `PLAINTEXT=1` and is for
  throwaway databases.
- The passphrase is never in a process's argv: it comes from the environment and
  reaches gpg through a mode-600 file (`scripts/backup_crypto.sh`), and the
  Makefile never expands it as `$(BACKUP_PASSPHRASE)` (make pastes that into the
  `sh -c` text). A failed dump or decrypt fails the command and keeps no file.
- History: the passphrase was on gpg's command line (#41), and a failed
  `pg_dump` or a wrong passphrase on restore exited 0.
- Still open: `make backup BACKUP_PASSPHRASE=...` puts it in make's own argv, so
  the docs say to export it. Where the passphrase is kept long term is the
  operator's key-management question.
- Source: `Makefile`, `backup` target comment; #41; DECISIONS D-33.
- Enforced by: `tests/test_backup_crypto.py` (the guards, the recipe text, the
  process table while gpg runs, the exit status of a restore and of a failed
  backup).

## Security posture

### R-14 Cross-site writes are refused

- Status: Active
- State-changing requests carrying `Sec-Fetch-Site` outside the trusted set are
  rejected. CORS is off unless explicitly configured, and never `*`.
- Source: `server/app/main.py` docstring.
- Enforced by: `server/tests/test_csrf.py`.

### R-15 Request size and rate are bounded

- Status: Active
- The edge refuses an `/api` body over 2,000,000 bytes (Caddy `max_size 2MB`
  is SI, not 2 MiB). The API refuses over 1,048,576 bytes
  (`REQUEST_BODY_LIMIT_BYTES`) and rate-limits per replica at 240 requests per
  60 seconds.
- Source: `proxy/Caddyfile`; `server/app/config.py`.
- Enforced by: `tests/test_proxy_identity.py`;
  `server/tests/test_api_hardening.py`.

### R-16 Security headers on every response

- Status: Active
- The Content-Security-Policy, HSTS, `nosniff`, Referrer-Policy and frame
  denial apply to `/api/*` responses and the dashboard alike, and `Server` is
  removed.
- The policy's `script-src` is the SHA-256 of the dashboard's one inline script,
  generated from the built page into `proxy/csp.caddy` (D-68). The exported
  report carries a policy of its own that allows no script.
- Source: `proxy/Caddyfile`; closed issues #14, #27, #154.
- Enforced by: `tests/test_proxy_identity.py`, `tests/test_csp.py`.

### R-25 The documented first-run path works with any password

- Status: Active
- A password generated the way `preflight.py` and `.env.example` tell the
  operator to generate it (`openssl rand -base64 32`), or chosen by a password
  manager, must work. Nothing may build a URL by interpolating the password.
- History: this was violated. Compose pasted `${POSTGRES_PASSWORD}` into the
  connection URL, and a `/` in the password made the API crash on startup, reading
  the start of the password as a port number. About half of all generated
  passwords did this. Found by an operator running `make dev`, not by a test.
- Source: the user's bug report; DECISIONS D-25.
- Enforced by: `server/tests/test_database_url.py`, including a real PostgreSQL
  role whose password contains every awkward character, and a guard that fails if
  compose ever interpolates the password into a URL again.

### R-26 Showcase media is first-party, bounded and honest about the mode

- Status: Active
- The walkthrough video lives on the docs site (`docs/assets/`), not on a
  third-party host, so the project's no-third-party rule (R-05) holds for its own
  front page. Each file is capped at 10 MB, starts playing before it finishes
  downloading, has controls and a poster, and never autoplays.
- The page must say the video was recorded on the Docker stack and that the
  demonstration copy at `/app/` is browser-only, because a viewer will otherwise
  assume the demo behaves like the video (R-04).
- **Known gap:** the narration has no captions or transcript (#75).
- Source: the user's instruction to publish the walkthrough; DECISIONS D-26.
- Enforced by: `tests/test_docs_media.py`, and a pre-commit hook that applies the
  10 MB cap to `docs/assets/` media while the repo-wide limit stays at 512 KB.

## Engineering rules

### R-17 American English only

- Status: Active
- American spelling in prose, code, comments, docstrings, commit messages and
  UI copy. Quoted material and third-party field names keep their original
  spelling.
- Enforced by: `pixi run check-spelling` (pre-commit).

### R-18 A closed set of values has an enumerated type

- Status: Active
- Code never branches on a bare string for a closed set. Python uses
  `StrEnum`; JavaScript uses a frozen constant object. Existing uses are
  baselined and only shrink.
- Source: [CLAUDE.md](CLAUDE.md); DECISIONS D-19.
- Enforced by: `pixi run check-enums`; the Claude Code hook in
  `.claude/settings.json` (Write, Edit, MultiEdit and Bash); `pixi run
  test-enums`.
- Not enforced: a hoisted constant, a dispatch dict, a literal on the left of
  `in`, a lowercase JavaScript state variable. See CLAUDE.md. These rest on
  review.

### R-19 A security claim names the test that enforces it

- Status: Active
- A claim in documentation or the UI ("sign-off means something", "check-
  isolation asserts all of this") is true or it is removed. Each one is listed in
  `docs/security-claims.md` with the sentence quoted and a test CI runs, or is
  listed honestly as `partial`, `unenforced` or `violated` with a reason and an
  issue.
- History: this was the root cause of #31, #55, #56, #61 and #62.
- Source: the claim-versus-reality findings of the hospital security review; #68;
  DECISIONS D-27.
- Enforced by: `pixi run check-claims` (every commit, and CI through the
  pre-commit hooks) and `tests/test_check_claims.py`. What it cannot do is
  find a claim nobody wrote down: a new assertive sentence still needs a human
  to add its row, which is what CLAUDE.md requires.

### R-23 Code ships with unit and integration tests

- Status: Active
- Whenever code is added or changed, unit and integration tests are added or
  updated in the same change. A bug fix starts with a regression test shown to
  fail. A guardrail is shown to fail (mutation tests). Integration tests use the
  real thing at a boundary (PostgreSQL, a browser, Caddy, Compose), never a fake
  for what is under test.
- Source: the user's instruction; [CLAUDE.md](CLAUDE.md); #32.
- Enforced by: review and CLAUDE.md for "tests accompany the change". CI
  enforces the weaker half: every test that exists runs on every pull request
  (`tests/test_workflows.py`).

### R-24 In CI, a test that cannot run fails

- Status: Active
- `REQUIRE_TESTS=1` turns a skip into a failure for every suite: no database, no
  Docker, no `node`, no stack, no Playwright. A skip exits 0 and reads as a pass.
- Source: #32.
- Enforced by: `.github/workflows/test.yml` sets it at workflow level, and
  `tests/test_workflows.py` fails if that is removed.

### R-20 Decisions and requirements are tracked

- Status: Active
- This file and `DECISIONS.md` are kept current as part of the change that
  alters them. See CLAUDE.md.
- Enforced by: review, and the instruction in CLAUDE.md.

## Open questions

### R-21 What data classification does the server-backed mode carry?

- Status: **Answered by R-49** (2026-10-08, the owner's decision on #34)
- "Do not put patient-identifiable information in it" is stated only for the
  browser-only mode. The server mode, which a hospital deploys, states nothing,
  and its own migration comments anticipate a patient identifier pasted into an
  evidence field. Until the owner decides, do not write documentation or UI
  copy that implies the server mode is, or is not, approved for PHI.
- GDPR applies regardless: the data subjects include hospital staff.

### R-22 Is PHI detection in scope, and where does it run?

- Status: **Answered by R-50** (2026-10-08, the owner's decision)
- Context since R-49: the scope is now governance metadata only, so a detector
  would be a check on a policy, not the basis for holding patient data. The owner
  has said they expect a name detector to flag the investigator and approver
  names and dates a governance record is made of; that is input, not a decision.
- Proposed, not decided: an opt-in sidecar behind `POST /api/phi-check`, plus an
  offline `make phi-scan`. The model cannot live in the browser (R-01).
  Whatever is built must not say "no PHI detected"; it states what was scanned
  and that a clean result is not a guarantee.

### R-47 How long is each kind of record kept?

- Status: **Answered by R-54** (2026-10-08, the owner's decision)
- Nothing expires: the audit log, revisions, deletion record and read trail are
  append-only, and no period is stated anywhere. The owner has to decide a period
  for each, reconciling a documented retention floor for governance records
  (45 CFR 164.316(b)(2)(i), six years where HIPAA applies) with storage
  limitation (GDPR Art. 5(1)(e)), and whether the fact of an action is kept after
  its content is erased (Art. 17(3)(b)). That is a legal and organizational call.
- Until answered: do not write a retention period into docs, UI copy or code, and
  do not add a job that deletes on a schedule. `docs/privacy.md` says it is
  undecided and its Art. 30 draft leaves the field to be filled in.
- Source: #57.

### R-69 Which CHAI criteria do OPTICA 5.3 and 7.4 cite?

- Status: Open
- docs/crosswalk.md moves OPTICA 5.3 and 7.4 from OPTICA-only to partial, but
  names no CHAI criterion for either. The page narrows them: 5.3 cites exactly
  one of s2-1, s2-2, s3-2, s3-4, s4-6 or s6-3 (s6-3 would also add CHAI stage
  s6 to chapter 5's stage set, which the page lists as s2; s1 s3 s4); 7.4 cites
  from s3-1, s3-2 and s4-3. The owner has decided (2026-10-10) to leave both
  unresolved for now.
- Until answered: OPTICA's definition keeps 5.3 and 7.4 OPTICA-only with no
  criteria, so the dashboard shows them as not covered by CHAI, and the page
  says so in its section 7, citing this entry. Do not record a criterion for
  either, and do not write documentation or UI copy that names one.
- When answered: record the criteria in `app/frameworks/optica/framework.json`
  and take both items out of the page's "not yet recorded" sentence.
  `pixi run check-crosswalk` accepts that sentence only while this entry's status
  is Open, so answering it without recording them fails the check.
- Source: docs/crosswalk.md (sections 1 and 2); the owner's answer in the #174
  session (2026-10-10); DECISIONS D-84.
- Enforced by: `scripts/gen_crosswalk.py --check` (`pixi run check-crosswalk`) and
  `tests/test_crosswalk.py`, which shows the check failing when this entry is
  answered while the items are still unrecorded.

### R-61 Evidence is referenced, never uploaded

- Status: Active
- A criterion's evidence can point at a link and at a file, but this tool does
  not hold the file. A file picked as evidence is fingerprinted in the browser;
  the record keeps its name, size and SHA-256 and nothing else, and no code path
  sends the file or its bytes anywhere.
- A reference's link opens only if it is an http or https address with no
  credentials, when typed and when read back from a stored or imported record.
- References are stored so that two people adding one at the same moment both
  keep theirs, and each appears in the HTML, Markdown and JSON exports and in
  the change history.
- The owner's decision, 2026-10-08: no uploads ("forget about the upload"),
  links to external sites allowed.
- Source: the owner, this session; DECISIONS D-70; claims C-85, C-86.
- Enforced by: `tests/test_refs.py`, `server/tests/test_refs_merge.py` and the
  reference cases in `tests/test_injection.py`.

### R-62 Notes take restricted Markdown, and nothing that can carry markup

- Status: Active
- The evidence or notes field of a criterion (CHAI and OPTICA) and a
  checkpoint's rationale accept bold, italic, bulleted and numbered lists, and
  links. Nothing else is formatting: raw HTML, images, tables and headings are
  shown as the text they are. A link opens only if it is http or https, and its
  address is always printed beside it.
- The stored value is the text as typed. The screen, the HTML and PDF reports and
  the Markdown report are each written from one parsed tree, never from the
  source, so a value reaches them only as something the parser built.
- The owner's decision, 2026-10-08: allow formatting and links to external
  sites, no uploads (R-61), and guard against injection (R-59).
- Source: the owner, this session; DECISIONS D-71; claim C-87.
- Enforced by: `tests/test_markdown.py` and the Markdown-dressed payloads in
  `tests/test_injection.py`.

### R-63 A build can use its own governance framework

- Status: Active
- The owner's decision, 2026-10-10 (#168): a developer can build the dashboard
  with their own framework, with its own stages, criteria and checkpoints,
  instead of CHAI and OPTICA. Frameworks are data run by one generic engine;
  the choice is made at build time, as a reviewed change and a rebuild, never
  by an upload at run time; and a build may leave CHAI and OPTICA out
  entirely. The default build stays CHAI plus OPTICA.
- Exactly one framework per build is the primary: the portfolio's status,
  phase, flags, score and report come from it, never from a mix of two.
- The shell (`app/js/00-core`, `app/js/20-app`) names no framework. It asks the
  primary through the registry's spine, so a framework is replaced without a
  change outside its own directory.
- Existing records keep their item and checkpoint ids, so they need no
  migration.
- Source: the owner, this session; issue #168; DECISIONS D-74.
- Enforced by: `tests/test_framework_boundary.py` (the shell names no CHAI or
  OPTICA identifier, and a stand-in primary drives the portfolio and every
  export). A definition (`app/frameworks/<id>/framework.json`) is checked by
  `pixi run check-framework` (pre-commit and CI) against
  `schema/framework.schema.json` and the rules a schema cannot state, each rule
  shown failing in `tests/test_check_framework.py`. The app runs CHAI and
  OPTICA from their definitions through the engine (D-75), and every screen
  they show is drawn by the engine from the definition (D-77); the snapshot
  (`tests/test_snapshot.py`) shows that changed nothing a reader sees. The
  boundary test now also covers the engine, the setup screen and the
  registration, and string literals that name a framework. A build of other
  frameworks is `build_app.py --config FILE --out DIR` (D-79):
  `tests/test_build_config.py` shows it writes only to `--out`, never under
  `docs/` or `proxy/`, and leaves the published page untouched; and
  `tests/test_custom_build.py` builds the example framework and shows every
  screen, the report and every export name nothing of CHAI or OPTICA, with a
  control that finds their words in the published build. A custom build can run
  behind the server: its `--out` holds the `manifest.json` the server retires by
  (R-66; `tests/test_build_config.py` shows it is written there, for the build's
  own primary, and the server tests in R-66 show a stand-in primary's manifest
  loaded, acknowledged and retired by).

### R-64 A supplement never feeds the primary

- Status: Active
- No answer in a supplement framework (OPTICA, or a developer's) changes the
  primary's status, phase, flags, next review or score, and the primary never
  reads a supplement's answers. Evidence may be cited in both; a judgment in one
  is never a judgment in the other.
- Source: docs/crosswalk.md and docs/developing.md, where this was stated but
  recorded nowhere as a requirement; the owner's decision that a build has one
  primary (R-63).
- Enforced by: `tests/test_engine.py` ("OPTICA answers change nothing CHAI
  decides, on every sample", with a control that shows the comparison can fail)
  and `tests/test_optica.py` ("CHAI score unmoved by an OPTICA answer").

### R-65 A developer's framework may bring only English

- Status: Active
- The owner's decisions, 2026-10-10 (#168): a developer's framework must have
  English, which is its definition; any other language is optional; a language
  it does supply must be complete (`check-i18n` names the missing keys), so a
  screen is never half one language; and where a language is not supplied, the
  framework's words show in English with a visible note saying so. This applies
  to a developer's frameworks only: CHAI and OPTICA keep all eight languages,
  required as before.
- Amends R-55: a framework's translations may also live in
  `app/frameworks/<id>/i18n/<locale>.json`. R-55's zh-Hans review covers CHAI's
  and OPTICA's wording only; a developer's framework shows a neutral note that
  names no reviewer.
- A framework that names no catalog keys of its own reads in the engine's
  neutral words (section, item, decision), translated in every language; the two
  neutral report footers are safety-bearing and show in English in a language
  until a reviewer is recorded, as R-55 already requires.
- Source: the owner, this session (two answers on 2026-10-10); #168; D-78.
- Enforced by: `tests/test_check_i18n.py` (a partial language, an extra key,
  markup, an English file, an unknown language, CHAI's text moved out: each
  refused), `tests/test_build_config.py` (a custom build ships no CHAI or OPTICA
  text and records its languages), `tests/test_engine.py` (neutral wording, and
  the note per framework, never naming a reviewer it does not have).

### R-66 Retired means what the record's framework says ends a project

- Status: Active
- Amends R-56's definition of retired, which named CHAI's checkpoints and words.
  R-56 is otherwise unchanged.
- The owner's design for #168 (design v2, 2026-10-10, "Server (PR C)"): a build
  may use its own framework (R-63), so the server decides when a project is
  retired, and so when disposal is due, from the same definition the dashboard was
  built with, and never changes disposal silently.
- **Retired means** one of the project's checkpoints holds a decision that the
  definition of the project's framework (`meta.framework.id`; a record without one
  is CHAI's) gives a `stop` or `retire` class at that checkpoint. In the published
  build that is still "Stop" at A, B or C or "Retire" at D. The clock starts as
  R-56 says: at the later of those decisions' dates and the record's last change.
- **The build is the unit.** The rules reach the database only from the manifest
  built beside the page (`docs/app/manifest.json` by default), loaded by the
  migrate job as the database owner. The API cannot change them.
- **Never silently.** Any change, a rule added or dropped or a new primary, is
  made only when the operator acknowledges exactly that change (every rule held
  before and after it, the primary before and after, from the point in the
  history it was shown at, in the database that showed it), after being shown
  every project that would become due or stop being due as the projects stood
  then. It binds the rules and the primary, not the records: a project edited
  between the refusal and the acknowledged run is affected without having been
  listed. An acknowledgment accepts that one change once, in the database that
  printed it, and nothing else: another database refuses it, and so does a copy
  restored from a dump that creates the tables again (as `make restore` does),
  elsewhere or over the same database in place. Two things are, to it, the same
  database: a copy of the database's files (a snapshot, a base backup,
  point-in-time recovery, a promoted replica), so a staging database made that
  way and its original each accept a value printed on the other, and a restore
  of the data alone into the tables already there, which accepts again a value
  spent after the dump was taken. A sync
  that changes nothing (the same rules, the same primary) needs no
  acknowledgment. A build leaves the rules of frameworks it does not list. A missing
  or malformed manifest, or a primary with no ending decision, stops the job, and
  stops an API that migrates itself with a manifest. Every change is recorded,
  append-only, with who and when.
- **The stamp is the build's.** Through the API a new record may name only the
  active primary as its framework (`meta.framework` exactly `{"id": <primary>}`).
  It may name none only while that primary is CHAI, whose records an unstamped
  one is; under another primary a new record without the stamp is refused. No
  write changes an existing record's framework, as retention reads it: a record
  written before a switch keeps the framework it had, and one written under a
  later primary keeps it after a rollback. A change of primary never lands
  between a create's check of the stamp and its commit.
- Source: the owner's design v2 on #168; DECISIONS D-76. Numbered R-66 as that
  design names it ("R-66 amends R-56"), leaving R-64 and R-65 to the entries it
  assigns them.
- Enforced by: `server/tests/test_retention.py` (real PostgreSQL and the real
  migrate job: every option of CHAI's definition and of a stand-in primary is due
  exactly when its class ends a project; a record follows only its own
  framework's rules, a blank stamp is CHAI's and the clock starts at the latest
  ending decision, each with a mutation test; an addition, a removal or a new
  primary refused without the change's acknowledgment and applied with it; an
  acknowledgment never accepting a different change, a rollback, a later change,
  a switch to another primary over the same rules, another database with the
  same history, or a copy restored from a dump into another database or in
  place, each part with a mutation test; an identity with a missing part
  refusing the change; a stale manifest refused; unlisted
  frameworks' rules kept),
  `server/tests/test_retirement_rules.py` (a malformed or missing manifest fails
  the job; the API's own migration syncs or warns, and with no manifest never
  reports the rules synced; the stamp is refused unless it
  is the active primary's, and required under another primary; no patch changes
  a record's framework, with mutation tests; the API role can only read the
  rules; their history is append-only; the sync takes the migration lock before
  it reads; a create that read the primary holds off a sync that switches it,
  and creates share the lock, each with a mutation test; `/api/health` reports
  the rule set),
  `tests/test_dispose.py` and `tests/test_verify_backup.py` (records with no rules
  are counted; the history keeps its trigger, enabled, after a restore, and the
  rules are the ones its latest change recorded; a real dump does not carry the
  database's identity),
  `tests/test_build_config.py` (the manifest is the definitions' own, and names
  the primary even when the config does not list it first),
  `tests/test_compose_isolation.py` (the page and the manifest come from one build
  directory) and `tests/test_stack.py` (the running stack's rules are the served
  default build's, confirmed by a sync, and its page shows no banner; it cannot
  show a different rule set, which the server tests do), and
  `tests/test_rules_banner.py` (the page carries its manifest's rule-set hash,
  and against a server whose rules, primary or sync differ it says so and
  records no decision and creates no record, D-83; the dashboard side D-76 left
  undone, now done). Security claims C-88 to C-90 and C-95.

### R-67 A build opens only its own framework's records

- Status: Active
- Every record a build of other frameworks makes is stamped with its primary
  (`meta.framework.id`). A record with no stamp was made by the published build
  and belongs to its primary, CHAI. A build lists, opens and imports only records
  of its own primary: another framework's record is left off the portfolio, with
  a note saying how many, and refused when opened or imported, saying whose it
  is. Its answers are never read against another framework's items.
- In local mode a build of other frameworks keeps its records and its view state
  under browser storage keys suffixed with its primary's id, so its work and the
  published build's never mix on one origin.
- The published build writes no stamp, so its records, exports and fingerprints
  are unchanged (the snapshot shows it).
- Source: #168 design v2 ("Records and identity"), implementing R-63; D-79.
- Enforced by: `tests/test_custom_build.py` ("every record it makes is stamped
  with its primary", "its records are stored under the example's key, not the
  published build's", "the portfolio lists only the example's record", "opening
  an unstamped record is refused", "opening another primary's record is
  refused", the import refusals, and "the example's own export is accepted");
  `tests/test_snapshot.py` (the published build unchanged). The server checks
  the stamp against its build (R-66): it accepts a new record's `meta.framework`
  only as exactly its active primary's (a patch keeps the record's own
  framework), and under a primary other than CHAI refuses a
  new record without it (`server/tests/test_retirement_rules.py`:
  `test_the_api_refuses_a_stamp_that_is_not_the_active_primary`,
  `test_under_another_primary_a_record_must_carry_its_stamp`; C-90), and
  `tests/test_build_config.py` shows a `--config` build writes its own
  `manifest.json` beside its page, the file the server loads its primary from.
  Served by an API whose primary is another framework, a build's page says so
  and makes no record (`tests/test_rules_banner.py`, "the example's page on the
  published build's server says so", "a new record is refused under another
  primary"; D-83).

### R-68 An export matches its published schema, and anyone can recompute its fingerprint

- Status: Active
- Every JSON export, of the published build and of a build of any other
  framework, validates against `schema/project.schema.json`, and the schema
  describes every field the export writes and requires every field it always
  writes.
- The fingerprint of a record is one rule, computed alike by the dashboard, the
  server's version history and `examples/load_export.py`: over the record as
  stored, the same fields left out, keys in the same order (UTF-16 code units),
  strings written alike (a lone surrogate as its `\u` escape), the project's id
  included. Each place that states which fields are left out names the same
  ones, and the export and the documentation state the whole rule.
- Source: #177 (the schema "can drift from projectJSON() unnoticed", and the
  skip list is "defined three times ... with no test pinning them equal"); D-82.
- Enforced by: `tests/test_export_schema.py`, `tests/test_fingerprint_skip.py`,
  `server/tests/test_fingerprint.py`.
