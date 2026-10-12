# Security claims

<!-- rumdl-disable MD013 -->
<!-- Evidence references are single long tokens (a test path plus a test name) that cannot be wrapped. -->

Every security property this project asserts, where it asserts it, and what
backs it. The inventory exists because the same bug kept appearing: a sentence in
the docs or the UI claiming something no test checked, which turned out to be
false (#31, #55, #56, #61, #62).

`pixi run check-claims` reads this page and fails if any row is not true to
its own description. It runs in every commit and in CI.

- **Asserted in** is the file and the sentence, quoted. The quote must still be
  in that file, so when a doc changes, its row has to change with it.
- **Enforced by** names the tests that enforce the claim. Each must exist **and**
  be something CI runs, because a test nobody runs (#32) is decoration.
- **Status** is one of four values, and the honest ones matter most:
    - `enforced`: a test CI runs fails if the claim becomes false.
    - `partial`: tested, but not all of it. The gap and its issue are stated.
    - `unenforced`: true or plausible, with nothing that would notice if it
      stopped being true. The reason is stated.
    - `violated`: the sentence is **not true** today. It stays in the inventory,
      with its issue, rather than being quietly left in the docs.

A claim the code does not back is allowed to stay here, as `violated`, in plain
sight. What is not allowed is a claim that looks enforced and is not.

**Adding a claim.** Any new sentence in the docs or the UI that asserts a
security property gets a row in the same change, with the test that enforces
it. If there is no test, write the test, or soften the sentence, or list it
honestly as `unenforced`. See [CLAUDE.md](https://github.com/tonyreina/ai_governance_healthcare/blob/main/CLAUDE.md).

## The claims

### C-01 Client-supplied identity headers are stripped

- **Claim:** The proxy deletes any identity header a client sends and sets its
  own, so a client cannot choose who it is.
- **Asserted in:** `docs/self-hosting.md` — "The proxy deletes any
  `X-Auth-Request-User`, `-Name` or `-Email` the browser sent"
- **Asserted in:** `docs/running.md` — "**Identity cannot be forged.**"
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::a forged X-Auth-Request-* is refused`
  `tests/test_stack.py::forged identity headers are stripped`

### C-02 Every documented cloud identity configuration resolves an identity

- **Claim:** The IAP, ALB, Azure and oauth2-proxy settings each produce the
  canonical identity headers. (This was broken for months, #23.)
- **Asserted in:** `docs/self-hosting.md` — "behind an SSO front door: the
  header it sets"
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::request is forwarded`
  `tests/test_proxy_identity.py::no provider header reaches the API`

### C-03 A request with no identity is refused, and an unset source fails closed

- **Claim:** An empty or missing identity answers 401. It never falls back to a
  usable default.
- **Asserted in:** `proxy/Caddyfile` — "NO DEFAULT VALUE"
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::a request with no identity is refused`
  `tests/test_proxy_identity.py::an unset identity source fails closed`
  `server/tests/test_auth.py::test_missing_header_is_401_not_an_anonymous_user`

### C-04 The API reads identity from the proxy header and nowhere else

- **Claim:** Not from a body, a query parameter or a cookie. The audit log's
  author is overwritten with the proxy identity.
- **Asserted in:** `README.md` — "the API reads identity from the proxy and
  nowhere else"
- **Asserted in:** `docs/adopting.md` — "the application reads identity from the proxy in front of it and nowhere else"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_auth.py::test_identity_comes_from_the_configured_header`
  `server/tests/test_api.py::test_log_author_is_the_proxy_identity_not_the_body`

### C-05 The API is reachable only through the proxy

- **Claim:** The API publishes no host port, and nothing but the proxy shares
  the internet-facing network with it.
- **Asserted in:** `docs/self-hosting.md` — "the API publishes no host port"
- **Asserted in:** `README.md` — "so it must be unreachable except through the
  proxy."
- **Asserted in:** `docs/self-hosting.md` — "The front door, and the only service reachable from outside."
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::publishing a port on the api is noticed`
  `tests/test_compose_isolation.py::a new service on the edge network is noticed`

### C-06 The database has no route off the host

- **Claim:** Postgres sits on an `internal: true` network and publishes no port.
- **Asserted in:** `docs/self-hosting.md` — "on an `internal: true` network with
  no route off the host at all"
- **Asserted in:** `docs/self-hosting.md` — "PostgreSQL 17, on a network with no route off the host"
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::an internal network made routable is noticed`
  `tests/test_compose_isolation.py::publishing a port on the database is noticed`

### C-07 The stack binds to loopback by default

- **Claim:** It speaks plain HTTP, so it is published on 127.0.0.1 unless the
  operator changes it.
- **Asserted in:** `README.md` — "The stack binds to loopback by default"
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::the proxy binding every interface is noticed`

### C-08 The development override cannot be picked up by accident

- **Claim:** It is a named file, never compose.override.yaml, which a bare
  `docker compose up` would load silently. It deliberately publishes
  the API.
- **Asserted in:** `docs/running.md` — "can never pick it up by accident"
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::a compose.override.yaml is noticed`

### C-09 `make check-isolation` asserts the isolation model

- **Claim:** The docs say the target asserts that the API is unreachable and
  that a forged identity is stripped.
- **Asserted in:** `docs/self-hosting.md` — "`make check-isolation` asserts all
  of this against a running stack."
- **Status:** enforced
- **Enforced by:**
  `tests/test_check_isolation.py::a published port on`
  `tests/test_check_isolation.py::a listening port is noticed`
  `tests/test_check_isolation.py::a proxy that forwards the header is noticed`
  `tests/test_check_isolation.py::with nothing running it exits non-zero, not 0`
  `tests/test_stack.py::check_isolation.py finds the isolation model intact`

### C-10 Access control is enforced on the server

- **Claim:** A reader cannot write, a writer cannot delete, and a stranger gets
  404, not 403, so existence is not confirmed.
- **Asserted in:** `docs/running.md` — "| Access control enforced | **No** | **Yes, server-side** |"
- **Asserted in:** `docs/guide.md` — "On the server these are enforced by the API, not just by the buttons the page shows."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_access.py::TestEnforcement::test_reader_may_not_patch`
  `server/tests/test_access.py::TestEnforcement::test_writer_may_not_delete`
  `server/tests/test_access.py::TestEnforcement::test_stranger_gets_404_not_403`
  `server/tests/test_access.py::TestEnforcement::test_list_hides_projects_you_cannot_read`

### C-11 A writer cannot grant themselves ownership

- **Claim:** Only an owner may change who has access, and a project cannot be
  left with no owner.
- **Asserted in:** `server/app/access.py` — "Only an owner may change who has
  access"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_access.py::TestEnforcement::test_writer_may_not_grant_themselves_ownership`
  `server/tests/test_access.py::TestEnforcement::test_last_owner_cannot_be_removed`

### C-12 A checkpoint sign-off is attributed to the authenticated user

- **Claim:** `signedBy` and `signedAt` are written by the server from the proxy
  identity and its clock, whatever the client sends. (Violated until
  #31.)
- **Asserted in:** `docs/deploy.md` — "**A checkpoint sign-off means
  something.**"
- **Asserted in:** `docs/running.md` — "| Checkpoint sign-off means something | **No, self-asserted** | Yes |"
- **Asserted in:** `docs/index.md` — "On the shared server a sign-off carries the name of the person signed in through your hospital's own single sign-on"
- **Asserted in:** `docs/guide.md` — "On the shared server that identity comes from your hospital's single sign-on and cannot be set from the browser."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_signoff.py::TestTheForgeryFromTheIssue::test_a_writer_cannot_sign_off_as_the_cmo`
  `server/tests/test_signoff.py::TestWhoSignedAndWhen::test_a_new_decision_is_attributed_to_the_caller_not_the_claim`
  `tests/test_stack.py::the sign-off is attributed to the proxy identity, not the claim`

### C-14 Cross-site writes are refused

- **Claim:** A state-changing request a different site initiated is rejected by
  `Sec-Fetch-Site`, so a signed-in user's browser cannot be driven
  from another page.
- **Asserted in:** `server/app/main.py` — "Cross-site writes are refused."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_csrf.py::TestCrossSiteWrites::test_a_cross_site_delete_is_refused`
  `server/tests/test_csrf.py::TestCrossSiteWrites::test_every_write_method_is_covered`

### C-15 Security headers are on every response

- **Claim:** The Content-Security-Policy, HSTS, nosniff and frame denial apply
  to `/api` and the dashboard alike, and `Server` is removed.
- **Asserted in:** `proxy/Caddyfile` — "Security headers, at the SITE level so
  /api/* gets them too."
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::content-security-policy`
  `tests/test_proxy_identity.py::no Server header`
  `server/tests/test_api_hardening.py::test_api_responses_get_security_headers`

### C-16 Request bodies are bounded

- **Claim:** The edge and the API both refuse an oversize body, and the API does
  so without buffering it.
- **Asserted in:** `proxy/Caddyfile` — "A project document is a governance
  record: kilobytes."
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::Caddy cut the over-size body off at the cap`
  `server/tests/test_api_hardening.py::test_body_limit_rejects_large_payloads`
  `server/tests/test_api_hardening.py::TestBodyLimitDoesNotBuffer::test_an_oversize_chunked_body_is_rejected`

### C-17 Abuse is rate limited

- **Claim:** Requests are counted per identity over a sliding window. The limit
  is per replica.
- **Asserted in:** `server/app/ratelimit.py` — "Per-key request accounting over a
  moving window."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_api_hardening.py::test_rate_limit_blocks_burst_requests`
  `server/tests/test_api_hardening.py::TestRateLimiterMemory::test_the_window_really_slides`

### C-18 The audit log is append-only

- **Claim:** No route changes or removes a log entry, and the database refuses
  any UPDATE except the redaction a purge performs, which it verifies
  by comparing the result with a function. Deleting a project removes
  its live log, and records that it did (C-45).
- **Asserted in:** `README.md` — "Audit log | Yes, append-only"
- **Asserted in:** `docs/index.md` — "The database itself refuses to alter the audit log or the revision history"
- **Asserted in:** `docs/adopting.md` — "The audit trail is enforced by the database, not only by the application."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_api.py::test_the_database_itself_refuses_to_update_a_log_entry`
  `server/tests/test_api.py::test_there_is_no_route_to_change_or_remove_a_log_entry`
  `server/tests/test_api.py::test_log_timestamp_is_the_server_clock`
  `server/tests/test_disposal.py::TestTheDatabaseAllowsARedactionAndNothingElse::test_an_arbitrary_update_is_refused`
  `server/tests/test_disposal.py::TestTheDatabaseAllowsARedactionAndNothingElse::test_a_partial_redaction_is_refused`
  `server/tests/test_disposal.py::TestTheDatabaseAllowsARedactionAndNothingElse::test_changing_when_or_who_is_refused`

### C-19 Version history cannot be rewritten

- **Claim:** Every revision is kept, and the only permitted change to one is a
  purge.
- **Asserted in:** `docs/running.md` — "| Version snapshots | No | **Yes** |"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_versions.py::TestVersions::test_history_is_append_only`
  `server/tests/test_versions.py::TestPurge::test_history_cannot_be_rewritten_by_hand`

### C-20 History survives deletion and stays restricted

- **Claim:** Deleting a project does not erase its history, and deleting a
  restricted record does not widen access to it.
- **Asserted in:** `server/migrations/002_versions.sql` — "No foreign key to
  projects, deliberately."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_versions.py::TestVersions::test_history_survives_deletion`
  `server/tests/test_versions.py::TestDeletedHistoryStaysRestricted::test_a_stranger_cannot_read_a_deleted_projects_history`

### C-21 Disposal leaves a tombstone, not a gap

- **Claim:** A purge empties a snapshot's content and keeps its revision,
  author, timestamp and original hash. Only an owner may purge.
- **Asserted in:** `server/migrations/003_version_access.sql` — "The purge below
  is deliberately NOT a delete."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_versions.py::TestPurge::test_an_owner_can_purge_and_the_tombstone_survives`
  `server/tests/test_versions.py::TestPurge::test_a_writer_cannot_purge`

### C-22 Deleting a project does not erase its history, and the docs say so

- **Claim:** Deleting removes the live project and its live audit log. The
  version history is kept, and the guide says plainly that deletion
  is not erasure. (It used to say it deleted "a project and its log",
  which implied the opposite. #36)
- **Asserted in:** `docs/self-hosting.md` — "**Deleting a project does not erase
  its history.**"
- **Asserted in:** `docs/developing.md` — "The server keeps its version
  history"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_versions.py::TestVersions::test_history_survives_deletion`
  `server/tests/test_disposal.py::TestDeletionLeavesATombstone::test_the_log_still_goes_with_the_project`

### C-23 Backups are encrypted, and a plaintext dump is refused

- **Claim:** `make backup` requires a passphrase and writes only an encrypted
  dump.
- **Asserted in:** `Makefile` — "BACKUP_PASSPHRASE is required"
- **Status:** enforced
- **Enforced by:**
  `tests/test_backup_crypto.py::make backup with no passphrase is refused`
  `tests/test_backup_crypto.py::a plaintext dump needs PLAINTEXT=1 and is refused without it`
  `tests/test_backup_crypto.py::the passphrase is in no process's argv while encrypting`
  `tests/test_backup_crypto.py::the dump is not plaintext`
  `tests/test_backup_crypto.py::a backup whose pg_dump fails exits non-zero`

### C-24 `make up` refuses to start on unsafe settings

- **Claim:** A placeholder or short database password, a literal identity source,
  and a non-loopback bind over plain HTTP are all refused, and `.env` is read the
  way compose reads it, so a blank value or a trailing comment cannot get past
  the gate.
- **Asserted in:** `README.md` — "refuses to start on unsafe settings"
- **Asserted in:** `docs/adopting.md` — "`make up` refuses to start on unsafe settings and says why."
- **Asserted in:** `docs/self-hosting.md` — "`make up` refuses to start on unsafe settings: an empty or placeholder password"
- **Status:** enforced
- **Enforced by:**
  `tests/test_preflight.py::an empty password is refused`
  `tests/test_preflight.py::15 characters is refused`
  `tests/test_preflight.py::the message points at make dev for local use`
  `tests/test_preflight.py::0.0.0.0 over plain HTTP is refused`
  `tests/test_preflight.py::SITE_ADDRESS= (blank) is plain HTTP, so 0.0.0.0 is REFUSED`
  `tests/test_preflight.py::so a weak one with a long note is still refused`
  `tests/test_preflight.py::an unsafe .env exits 1`
  `tests/test_preflight.py::FORCE=1 skips the check and exits 0`

### C-25 Any database password works

- **Claim:** A password from `openssl rand -base64 32`, or one with any
  character in it, connects. (About half of them crashed the API
  before #72.)
- **Asserted in:** `.env.example` — "Any password works in POSTGRES_PASSWORD
  above"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_database_url.py::TestThePiecesBecomeAUrlThatSurvivesAnyPassword::test_every_awkward_password_round_trips`
  `server/tests/test_database_url.py::TestARealRoleWithAHostilePassword::test_it_connects_and_a_wrong_password_does_not`

### C-26 Browser-only mode says so, in a standing banner

- **Claim:** The app states in the layout that it is storing in one browser,
  with no access control or audit log, and names the risk.
- **Asserted in:** `README.md` — "The app says so in a standing banner when it
  is in this mode."
- **Asserted in:** `docs/adopting.md` — "and it says so in a standing banner"
- **Status:** enforced
- **Enforced by:**
  `tests/test_boot_storage.py::static host -> standing warning is shown`
  `tests/test_boot_storage.py::static host -> warning names the risk`

### C-27 The app never silently falls back to browser storage

- **Claim:** If a server was expected and cannot be reached, or refuses the
  user, the app stops and says so.
- **Asserted in:** `README.md` — "never silently falls back"
- **Asserted in:** `docs/running.md` — "The app never silently falls back from one to another."
- **Status:** enforced
- **Enforced by:**
  `tests/test_boot_storage.py::no store was created`
  `tests/test_boot_storage.py::nothing written to localStorage`

### C-28 After a save, the app says where the save went

- **Claim:** The server mode says the shared workspace and never the browser;
  only the browser-only mode may mention the browser. (Violated until
  #55.)
- **Asserted in:** `app/js/00-core/40-writes.js` — "What a save tells the user
  about where it went."
- **Status:** enforced
- **Enforced by:**
  `tests/test_boot_storage.py::server mode: a save says it went to the shared workspace`
  `tests/test_boot_storage.py::browser-only mode: a save says it stayed in this browser`
  `tests/test_boot_storage.py::only the browser-only mode may say 'browser'`

### C-29 Each storage mode is labeled distinctly

- **Claim:** The header names the mode, so a user can tell the audited server
  from the example page.
- **Asserted in:** `app/js/00-core/30-state.js` — "and no two modes share one"
- **Status:** enforced
- **Enforced by:**
  `tests/test_boot_storage.py::no two modes share a header label`
  `tests/test_boot_storage.py::every Mode has a header label`

### C-30 Live updates reach other users, and only those who may see the project

- **Claim:** A change arrives over the event stream without a refresh. The
  stream carries ids, not documents, and a stranger is not told a
  restricted project changed.
- **Asserted in:** `docs/running.md` — "Live updates between people"
- **Status:** enforced
- **Enforced by:**
  `tests/test_stack.py::external change arrives over SSE`
  `server/tests/test_events.py::test_a_stranger_does_not_see_a_restricted_project_change`
  `server/tests/test_events.py::test_the_stream_carries_ids_not_documents`

### C-31 The generated dashboard can never go stale

- **Claim:** A hook rebuilds docs/app/index.html on any change under app/ and
  fails the run if the file differs.
- **Asserted in:** `docs/developing.md` — "so the generated file can never go
  stale"
- **Status:** enforced
- **Enforced by:**
  `.pre-commit-config.yaml::build-app`

### C-32 A test cannot be added and quietly left out of CI

- **Claim:** CI fails if a `test-*` task is not run, or a test file has no task.
- **Asserted in:** `docs/developing.md` — "so a test cannot be added and quietly
  left out."
- **Status:** enforced
- **Enforced by:**
  `tests/test_workflows.py::every rule passes on .github/workflows/test.yml`
  `tests/test_workflows.py::a suite dropped from CI is noticed`

### C-33 In CI, a test that cannot run is a failure

- **Claim:** `REQUIRE_TESTS=1` turns a skip into a failure, because a skip exits
  0 and reads as a pass.
- **Asserted in:** `docs/developing.md` — "to turn every skip into a failure; CI
  always does."
- **Status:** enforced
- **Enforced by:**
  `tests/test_workflows.py::REQUIRE_TESTS removed is noticed`
  `tests/test_workflows.py::REQUIRE_TESTS set to 0 is noticed`

### C-34 The walkthrough video says what it shows

- **Claim:** The page says it was recorded on the Docker stack and that the
  demonstration copy is browser-only.
- **Asserted in:** `docs/index.md` — "The video shows a **shared workspace**"
- **Status:** enforced
- **Enforced by:**
  `tests/test_docs_media.py::dropping the mode caveat is noticed`

### C-35 `PROXY_SHARED_SECRET` is a working control

- **Claim:** Set once in `.env`, the proxy sends the secret and the API refuses a
  request without it. It authenticates the proxy to the API, not a caller to the
  proxy.
- **Asserted in:** `docs/deploy.md` — "Set it once in `.env` and Compose gives
  the same value to both"
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::the proxy sends X-Proxy-Secret to the API`
  `tests/test_proxy_identity.py::a client-supplied X-Proxy-Secret is replaced, not forwarded`
  `tests/test_compose_isolation.py::PROXY_SHARED_SECRET missing from`
  `tests/test_stack.py::the API refuses a request that skipped the proxy's secret`
  `tests/test_stack.py::and accepts the same request carrying it`
  `server/tests/test_auth.py::test_shared_secret_blocks_a_request_that_skipped_the_proxy`

### C-36 The self-hosting identity example is the safe one

- **Claim:** The identity example the self-hosting guide shows uncommented is a
  placeholder, never a literal, and local development is sent to `make dev`.
- **Asserted in:** `docs/self-hosting.md` — "Never put a literal such as
  `dev@localhost` here."
- **Status:** enforced
- **Enforced by:**
  `tests/test_preflight.py::passes preflight`
  `tests/test_preflight.py::the scan found the examples it is meant to check`

### C-37 The AWS audience setting matches what the load balancer signs

- **Claim:** The task definition sets `IDENTITY_AUDIENCE` to the value the API
  compares against, and the API refuses to start on a listener ARN.
- **Asserted in:** `docs/deploy.md` — "loadbalancer/app/chai/a"
- **Status:** partial
- **Gap:** No test has a live ALB, so that it puts its load balancer ARN in
  `signer` rests on AWS's documented token format. #51 is fixed to that extent.
- **Enforced by:**
  `server/tests/test_auth.py::TestAlbAudienceIsTheLoadBalancerArn::test_every_arn_the_docs_show_for_the_audience_starts`
  `server/tests/test_auth.py::TestAlbAudienceIsTheLoadBalancerArn::test_a_listener_arn_is_refused_at_startup`
  `server/tests/test_auth.py::TestAlbAudienceIsTheLoadBalancerArn::test_the_load_balancer_arn_is_what_the_alb_signs`

### C-38 MFA is whatever the hospital already requires

- **Claim:** Authentication, including multi-factor, is enforced at the front
  door and not by this application.
- **Asserted in:** `docs/deploy.md` — "**MFA is whatever the hospital already
  requires**"
- **Status:** unenforced
- **Gap:** Rests on the hospital's identity provider and the cloud front door,
  which are outside this repository and cannot be exercised from a test
  here.

### C-39 Following 'Close the back door' makes the API unreachable except through SSO

- **Claim:** Each cloud section's back-door steps are, in the guide's words,
  "not hardening"; they are the deployment.
- **Asserted in:** `docs/deploy.md` — "They are the deployment."
- **Status:** unenforced
- **Gap:** Rests on each cloud's own network configuration. The guide's 'Proving
  the back door is closed' commands are for an operator to run per
  deployment; nothing here runs them.

### C-40 The API refuses identity headers from an unexpected peer

- **Claim:** With `TRUSTED_PROXY_CIDR` set, a request whose TCP peer is outside
  it is rejected, and `X-Forwarded-For` cannot satisfy the check.
- **Asserted in:** `docs/deploy.md` — "refuses identity headers arriving from
  anywhere else"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_auth.py::test_trusted_proxy_cidr_rejects_an_outside_peer`
  `server/tests/test_auth.py::test_x_forwarded_for_cannot_satisfy_the_peer_check`

### C-41 The data survives `docker compose down`

- **Claim:** Postgres writes to a named volume, which `down` leaves alone.
- **Asserted in:** `docs/self-hosting.md` — "containers and networks go; pgdata
  stays"
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::the database leaving its named volume is noticed`

### C-42 The database image is pinned to a major version

- **Claim:** Postgres does not migrate its on-disk format, so a floating tag
  could make a volume unreadable on an unrelated pull.
- **Asserted in:** `compose.yaml` — "Pinned to a major version, never :latest."
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::db image '{image}' is noticed`

### C-43 A purge destroys the content of the history and of the audit log

- **Claim:** Every revision's document is emptied and every audit-log entry is
  redacted, including its prose and any extra field the client added,
  so a value pasted in by mistake is gone from both tables. A client
  cannot exempt its own entry.
- **Asserted in:** `docs/self-hosting.md` — "A purge destroys the content of
  every revision **and of every audit-log entry**"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_disposal.py::TestAPurgeReachesTheAuditLog::test_the_value_is_gone_from_the_history_and_the_log`
  `server/tests/test_disposal.py::TestAPurgeReachesTheAuditLog::test_the_prose_is_redacted_not_just_the_structured_values`
  `server/tests/test_disposal.py::TestAPurgeReachesTheAuditLog::test_a_field_the_server_does_not_own_is_gone_too`
  `server/tests/test_disposal.py::TestAPurgeReachesTheAuditLog::test_a_client_cannot_exempt_its_own_entry_from_redaction`

### C-44 A purge leaves who, when and which field, and records itself

- **Claim:** What survives is the author, the time, the field's path and the
  fingerprint, so the history shows that something was written and
  later destroyed, not a gap. The server writes its own record of the
  purge into the log, and that record is never redacted.
- **Asserted in:** `docs/self-hosting.md` — "What stays is who changed what,
  when, which field, and the fingerprint"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_disposal.py::TestAPurgeReachesTheAuditLog::test_who_what_and_when_survive`
  `server/tests/test_disposal.py::TestAPurgeReachesTheAuditLog::test_the_purge_itself_is_recorded_in_the_log`
  `server/tests/test_disposal.py::TestAPurgeReachesTheAuditLog::test_the_record_of_a_purge_survives_the_next_purge`

### C-45 Deletion leaves a permanent tombstone

- **Claim:** A delete writes who deleted the project, when, and what its last
  revision hashed to, in an append-only table that holds no content
  and survives a purge. A refused or failed delete writes nothing.
- **Asserted in:** `docs/self-hosting.md` — "It writes a permanent tombstone to
  `project_deletion`: who deleted it, when,"
- **Asserted in:** `docs/guide.md` — "writes a permanent record of who deleted it and when"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_disposal.py::TestDeletionLeavesATombstone::test_a_delete_records_who_when_and_what_it_hashed_to`
  `server/tests/test_disposal.py::TestDeletionLeavesATombstone::test_it_survives_a_purge_of_the_history`
  `server/tests/test_disposal.py::TestDeletionLeavesATombstone::test_it_cannot_be_changed_or_removed_by_hand`
  `server/tests/test_disposal.py::TestDeletionLeavesATombstone::test_a_refused_delete_writes_nothing`

### C-46 The delete dialog says what deleting does, and offers to destroy the history

- **Claim:** In the server mode the dialog says the version history is kept,
  offers destroying it as a separate unticked choice, does the
  destroy step first, and does not delete the project if that step
  fails. The modes with no history do not offer it.
- **Asserted in:** `app/i18n/en.json` — "Its version history is
  kept."
- **Status:** enforced
- **Enforced by:**
  `tests/test_disposal_ui.py::it says the version history is KEPT`
  `tests/test_disposal_ui.py::history first, then the project, in that order`
  `tests/test_disposal_ui.py::the project is NOT deleted if its history could not be destroyed`

### C-47 Backups made before a purge still hold the data

- **Claim:** The guide states that a backup taken earlier keeps the destroyed
  content. `make restore` no longer brings it back unnoticed: it re-applies the
  live database's purges, and says so when it cannot (C-75).
- **Asserted in:** `docs/self-hosting.md` — "Backups made earlier still hold the data."
- **Status:** enforced
- **Enforced by:**
  `tests/test_purge_ledger.py::restoring a dump from before the purge brings the content back`
  `tests/test_purge_ledger.py::the mistaken content is gone again`

### C-48 A change cannot be merged to main unless CI passes

- **Claim:** `main` requires the `tests passed` check, pinned to GitHub Actions,
  with no administrator bypass, so a pending or red run blocks the merge.
- **Asserted in:** `docs/developing.md` — "a pull request cannot be merged while it is pending or red"
- **Asserted in:** `docs/adopting.md` — "A change cannot merge unless the whole test suite passes"
- **Status:** unenforced
- **Gap:** A repository setting, not a file, so no test in the repository can
  detect it being switched off. It was verified by hand, by trying to merge a
  throwaway PR with the check pending and then red; both were refused. Re-check it
  with `gh api repos/OWNER/REPO/rules/branches/main`.

### C-49 The dashboard's multi-line fields do not feed the browser's spellchecker

- **Claim:** The free-text fields turn spellcheck and form history off, so what is
  typed into them is not sent to a cloud spellchecker by the dashboard's own
  markup.
- **Asserted in:** `docs/deploy.md` — "The dashboard turns spellcheck and form
  history off on its multi-line fields"
- **Status:** partial
- **Gap:** Single-line inputs (owners, metric names, dates) keep the browser's
  default, on purpose, and a browser or extension may ignore the attribute. The
  deployment guide therefore also tells operators to disable cloud-backed
  spellcheck by policy, which nothing here can enforce. #59
- **Enforced by:**
  `tests/test_text_fields.py::every editable textarea opts out of spellcheck and form history`
  `tests/test_text_fields.py::a field with the browser defaults is noticed`

### C-50 `make up` refuses a Google identity source without its prefix

- **Claim:** Google IAP's `accounts.google.com:` prefix must be stripped, and
  `make up` refuses a Google identity source that does not set it.
- **Asserted in:** `docs/self-hosting.md` — "`make up` refuses a Google source
  without it"
- **Status:** enforced
- **Enforced by:**
  `tests/test_preflight.py::a Google identity source with no strip prefix is refused`
  `tests/test_preflight.py::uncommenting the template's Google block, in place, passes preflight`
  `server/tests/test_auth.py::TestThePrefixIsStrippedOnEveryPath::test_the_same_person_gets_the_same_id_by_either_path`

### C-51 The proxy runs unprivileged, with a read-only filesystem and no extra capabilities

- **Claim:** The only internet-facing service runs as a non-root user, drops every
  capability but one, and cannot write its own filesystem, so a compromise starts
  with far less than root.
- **Asserted in:** `docs/self-hosting.md` — "it runs as an unprivileged user
  (uid 65532), drops every Linux"
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::the proxy running as root`
  `tests/test_compose_isolation.py::the cloud proxy image: dropping USER is noticed`
  `tests/test_stack.py::the proxy runs as an unprivileged user`
  `tests/test_stack.py::the proxy and the api have a read-only root filesystem`

### C-52 Denied access is logged

- **Claim:** A refused request on a project the caller has no right to leaves one
  `access.denied` line naming who, which project, what was needed and what they
  held, without the document's contents.
- **Asserted in:** `server/README.md` — "produces one `access.denied` security event"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_denial_log.py::test_a_stranger_reading_a_project_is_logged`
  `server/tests/test_denial_log.py::test_a_reader_trying_to_write_is_logged`
  `server/tests/test_denial_log.py::test_the_line_does_not_leak_the_document`
  `server/tests/test_denial_log.py::test_permitted_requests_log_no_denial`

### C-53 The API cannot disable the append-only triggers

- **Claim:** The API serves as a restricted database role that cannot disable a
  trigger, truncate a table, alter the schema or hold the owner's credential, so
  the audit log and history are append-only against the application and not only
  against its bugs.
- **Asserted in:** `docs/self-hosting.md` — "it **cannot** disable or drop a
  trigger, truncate, alter a table or create one"
- **Asserted in:** `docs/index.md` — "the shipped stack runs the service as a database role that cannot switch that protection off"
- **Status:** partial
- **Gap:** A PostgreSQL superuser bypasses it, and the owner's password is still
  in `.env` on the host and in the `migrate` job. A deployment that does not set
  `APP_POSTGRES_PASSWORD` serves as the owner (reported on `/api/health`, logged,
  and failed by `make doctor`). The cloud job definitions have not been run against
  a real managed database. #48
- **Enforced by:**
  `server/tests/test_roles.py::test_it_is_refused_every_statement_that_removes_a_guarantee`
  `server/tests/test_roles.py::test_its_table_privileges_are_exactly_the_documented_ones`
  `server/tests/test_roles.py::test_every_table_has_a_decided_grant`
  `tests/test_compose_isolation.py::the api being given the owner's password`
  `tests/test_stack.py::using the credential the API holds, the triggers cannot be disabled`
  `tests/test_stack.py::the API container holds no owner credential`

### C-54 The name lookup answers only for people the caller can already see

- **Claim:** `GET /api/principals` is not a staff directory anyone can walk: it
  answers for the caller and for people named on a project the caller can read,
  and for no one else.
- **Asserted in:** `server/README.md` — "It answers **only for people the caller can
  already see**"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_principals.py::test_it_is_not_a_directory_anyone_can_enumerate`
  `server/tests/test_principals.py::test_the_lookup_resolves_people_on_a_project_you_can_read`
  `server/tests/test_principals.py::test_the_batch_is_bounded`

### C-55 Every use of emergency access is recorded in the project's own audit log

- **Claim:** An identity with emergency access holds owner rights on every project,
  and each use is recorded in that project's own audit log, which a purge never
  redacts, and as a warning an alert can match.
- **Asserted in:** `docs/deploy.md` — "every use is recorded where the
  project's owners will see it"
- **Status:** partial
- **Gap:** Reads of one project by one person are throttled to one entry per ten
  minutes (every read is still an `access.breakglass` security event), and a delete cannot
  leave a log entry because the log goes with the project; it is recorded by the
  warning and the tombstone. Nothing here tests that a deployment alerts on the
  warning. #42
- **Enforced by:**
  `server/tests/test_breakglass.py::test_every_use_on_a_project_is_recorded_in_its_own_log`
  `server/tests/test_breakglass.py::test_the_entry_survives_a_purge`
  `server/tests/test_breakglass.py::test_reads_are_throttled_but_writes_are_not`
  `server/tests/test_breakglass.py::test_without_configuration_nobody_has_emergency_access`
  `server/tests/test_breakglass.py::test_the_record_is_visible_to_the_projects_new_owners`

### C-56 An event stream cannot outlive a revoked session by more than its lifetime

- **Claim:** The API ends an event stream after `SSE_MAX_LIFETIME_SECONDS`, so the
  browser reconnects through the front door and is authenticated again; a revoked
  session loses its stream within that time.
- **Asserted in:** `docs/deploy.md` — "A revoked session therefore loses its stream
  within this many seconds."
- **Status:** partial
- **Gap:** Tested that the API closes the stream and that a reconnect with no identity
  is refused. Nothing here runs a real front door, so that a real IAP, ALB or Easy
  Auth refuses the reconnect after revocation rests on how those products work. #49
- **Enforced by:**
  `server/tests/test_session.py::test_a_stream_is_closed_by_the_server_after_its_lifetime`
  `server/tests/test_session.py::test_reconnecting_works_and_is_authenticated_again`
  `tests/test_session_ui.py::a stream that is closed for good is reported`

### C-57 The front doors' session settings are listed correctly

- **Claim:** The table in the deployment guide names where each front door's session
  lifetime and sign-out are configured.
- **Asserted in:** `docs/deploy.md` — "the IAP reauthentication policy on the
  protected resource (session duration)"
- **Status:** unenforced
- **Gap:** Nothing here starts an IAP, an ALB, an Easy Auth or an oauth2-proxy
  session, so these come from the providers' documentation and could be out of date.
  The page says so. #49

### C-58 Security events are named and the docs list exactly them

- **Claim:** Every security-relevant event has a stable name and fields, written as
  one JSON object tagged `"stream": "security"`, and the table in the deployment
  guide is the complete list.
- **Asserted in:** `docs/deploy.md` — "a test fails if this table and the code ever
  disagree"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_security_events.py::test_the_documented_events_are_exactly_the_ones_the_code_can_emit`
  `server/tests/test_security_events.py::test_every_line_is_one_json_object_with_a_stream`
  `server/tests/test_security_events.py::test_a_request_with_no_identity_is_a_named_event`
  `server/tests/test_security_events.py::test_a_hostile_actor_id_cannot_forge_a_second_line`
  `tests/test_stack.py::creates, deletes and purges are named security events`

### C-59 Security events are collected, retained and alerted on

- **Claim:** The deployment guide tells an operator how to collect, retain and alert on
  the security stream on each platform.
- **Asserted in:** `docs/deploy.md` — "Where it goes."
- **Status:** unenforced
- **Gap:** This repository emits the events and tests that it does. It collects,
  retains and alerts on nothing: the sink, the filters and the retention are the
  operator's, and the per-cloud settings come from the providers' documentation and
  have not been run. The guide says so. #38

### C-60 Every read of a record is recorded, and the trail cannot be edited

- **Claim:** A list, a version read, a log read and a stream attach are each recorded
  in the transaction of the read, in an append-only table that outlives the project,
  so a read that cannot be recorded is not served.
- **Asserted in:** `docs/deploy.md` — "A read that cannot be recorded is not served."
- **Asserted in:** `docs/index.md` — "Who *read* a record is recorded too."
- **Asserted in:** `docs/running.md` — "| Who read what is recorded | No | **Yes** |"
- **Status:** partial
- **Gap:** Exports are built in the browser and reported by a beacon a client can
  omit: they are a record of ordinary use, bounded by the recorded reads that fetched
  the data. The table is append-only against the application and the restricted role;
  a database owner can still disable its trigger, which is why the same facts are also
  security events. Rows past the retention period may be deleted by the owner's
  disposal step (R-56, C-77). #33
- **Enforced by:**
  `server/tests/test_access_audit.py::test_each_read_route_records_what_it_returned`
  `server/tests/test_access_audit.py::test_a_read_that_fails_leaves_no_row`
  `server/tests/test_access_audit.py::test_the_trail_is_append_only`
  `server/tests/test_access_audit.py::test_the_trail_outlives_the_project`
  `server/tests/test_access_audit.py::test_the_check_constraint_and_the_enum_agree`
  `tests/test_export_beacon.py::the PDF export is reported`
  `tests/test_stack.py::each read was recorded in the real database`

### C-61 A backup can be verified by restoring it, and a restore asks first

- **Claim:** `make verify-backup` restores a dump into a throwaway PostgreSQL and
  fails unless the tables, rows and append-only triggers came back with the triggers
  enabled, and, from migration 010, unless the retirement rules are exactly the
  ones the latest `retirement_rule_change` row recorded; and `make restore` asks for
  `YES` before overwriting the live database.
- **Asserted in:** `docs/self-hosting.md` — "`make verify-backup` restores the newest
  dump"
- **Status:** enforced
- **Enforced by:**
  `tests/test_verify_backup.py::a good encrypted dump verifies`
  `tests/test_verify_backup.py::a dump that restores without the append-only triggers fails`
  `tests/test_verify_backup.py::a dump whose rules' history trigger is disabled fails`
  `tests/test_verify_backup.py::a dump whose rules differ from their history's last change fails`
  `tests/test_verify_backup.py::the wrong passphrase fails`
  `tests/test_verify_backup.py::a truncated dump fails`
  `tests/test_verify_backup.py::with no answer it aborts and touches nothing`

### C-62 The per-platform backup settings are listed correctly

- **Claim:** The deployment guide names the flags that set backup retention,
  point-in-time recovery, deletion protection and an off-account copy on each
  managed database.
- **Asserted in:** `docs/deploy.md` — "Two rules apply on every platform."
- **Status:** unenforced
- **Gap:** Nothing here creates a Cloud SQL, RDS or Azure database, so the flags come
  from the providers' documentation and could be out of date. The page says so and
  does not recommend a retention length. #52

### C-63 A production-shaped stack is not brought up without an encryption decision

- **Claim:** `make up` refuses a stack reachable beyond this machine, using its own
  database volume, until the operator confirms the disk is encrypted, and does not
  claim to be able to check it.
- **Asserted in:** `docs/self-hosting.md` — "`make up` refuses a stack that is
  reachable beyond this machine"
- **Status:** enforced
- **Enforced by:**
  `tests/test_preflight.py::a non-loopback bind with no confirmation is refused`
  `tests/test_preflight.py::STORAGE_ENCRYPTION_CONFIRMED=1 accepts it`
  `tests/test_preflight.py::loopback needs no confirmation: that is a laptop`
  `tests/test_doctor.py::when the host cannot be inspected it says it cannot tell, not that it is fine`

### C-64 The managed databases' encryption settings are described correctly

- **Claim:** Cloud SQL and Azure encrypt storage by default, and RDS only if
  `--storage-encrypted` is passed at creation.
- **Asserted in:** `docs/deploy.md` — "**off unless you pass `--storage-encrypted`
  when you create the instance**"
- **Status:** unenforced
- **Gap:** Nothing here creates a managed database, so these come from the providers'
  documentation. The page says so and tells the operator to confirm the setting on
  the instance they have. #47

### C-65 What runs is locked, pinned and watched

- **Claim:** The API's dependencies are installed from a hash-pinned lock, the base
  images and actions are pinned by digest or commit, Dependabot watches each
  ecosystem, and a scan fails on a fixable HIGH or CRITICAL finding in our images.
- **Asserted in:** `docs/deploy.md` — "What is running is what the repository says"
- **Status:** enforced
- **Enforced by:**
  `tests/test_supply_chain.py::every locked requirement is pinned and hashed`
  `tests/test_supply_chain.py::the API image's bases are pinned`
  `tests/test_supply_chain.py::the images compose pulls are pinned`
  `tests/test_supply_chain.py::dependabot covers pip, both Dockerfiles, compose and the actions`
  `tests/test_supply_chain.py::security.yml scans HIGH and CRITICAL, on a schedule`
  `tests/test_supply_chain.py::pip is not in the runtime image`

### C-66 The security policy promises no response times

- **Claim:** `SECURITY.md` commits to no response or fix times, so no one relying on
  it is told the project will meet one.
- **Asserted in:** `SECURITY.md` — "There are no
  response or fix times"
- **Status:** enforced
- **Enforced by:**
  `tests/test_supply_chain.py::SECURITY.md promises no response or fix times`

### C-67 Growth is reported and the disk alerts are documented

- **Claim:** `make doctor` reports how large the append-only tables are, and the
  deployment guide names the disk alert for each platform.
- **Asserted in:** `docs/deploy.md` — "Alert on the disk instead"
- **Status:** partial
- **Gap:** The report is tested; the per-platform alert metrics and flags are from the
  providers' documentation and nothing here creates a database or an alert. Nothing
  trims the tables: the retention periods are decided (R-54) but nothing applies
  them yet. #54
- **Enforced by:**
  `tests/test_doctor.py::the revision count and size are reported`
  `tests/test_doctor.py::the read trail's size is reported too, with why it grows`
  `tests/test_doctor.py::it says these tables never shrink by themselves`

### C-68 The deployment guide makes no legal claim about a region

- **Claim:** The deployment guide leaves the region to the reader and does not say
  that any region meets a legal requirement.
- **Asserted in:** `docs/deploy.md` — "This guide is not legal advice"
- **Status:** partial
- **Gap:** The test checks that the section exists, names no region as adequate or
  compliant, and that no command example names a region. It cannot tell whether
  the provider region names are current; they are marked unverified. #58
- **Enforced by:**
  `tests/test_deploy_residency.py::no command example names a concrete region`
  `tests/test_deploy_residency.py::the Data residency section is complete`

### C-69 A restore brings purged content back, and the docs say so

- **Claim:** A dump restored after a purge reinstates the purged content, so a
  purge for an erasure request is undone by an ordinary recovery unless it is
  re-applied.
- **Asserted in:** `docs/privacy.md` — "A restore brings purged content back"
- **Status:** enforced
- **Enforced by:**
  `tests/test_subject_access.py::a restore of a dump from before a purge brings the purged content back`

### C-70 Subject access finds every place an identifier is stored

- **Claim:** `make subject-access` reports every table and column that records who
  did something, and changes nothing.
- **Asserted in:** `docs/privacy.md` — "It changes nothing."
- **Status:** partial
- **Gap:** Columns named `*_by`, `by_id` or `actor` are checked against the query;
  an identifier stored under another name, or only inside new jsonb, is not. #57
- **Enforced by:**
  `tests/test_subject_access.py::every column that records who did something is searched`
  `tests/test_subject_access.py::it changed nothing`

### C-71 An export carries its own provenance

- **Claim:** Each export states which storage mode produced it, in the header's own
  words, and browser-only exports say sign-offs are self-asserted.
- **Asserted in:** `app/js/00-core/30-state.js` — "Sign-offs here are self-asserted"
- **Status:** enforced
- **Enforced by:**
  `tests/test_export_provenance.py::the HTML report states the mode`
  `tests/test_export_provenance.py::browser-only exports say sign-offs are self-asserted`
  `tests/test_export_provenance.py::the JSON export states the mode`

### C-72 The data scope is stated in every mode

- **Claim:** Every storage mode, the self-hosted server included, tells the user
  never to enter patient-identifiable information, and the docs say so first.
- **Asserted in:** `app/i18n/en.json` — "Governance metadata only: never enter patient-identifiable information."
- **Status:** partial
- **Gap:** A statement of policy. Nothing inspects what is typed into the
  free-text fields, so the tests prove the instruction is shown, not that it is
  followed. Detection is R-22, open. #34
- **Enforced by:**
  `tests/test_boot_storage.py::healthy API -> the data scope is stated in the layout`
  `tests/test_boot_storage.py::static host -> the warning states the same data scope`
  `tests/test_data_scope.py::the comparison table says Never in every mode`

### C-73 The PHI scan never repeats what it finds

- **Claim:** `make phi-scan` reports the project, field and revisions of a match,
  never the matched text, and a clean run does not say no patient information is
  present.
- **Asserted in:** `docs/self-hosting.md` — "never the matched text"
- **Status:** enforced
- **Enforced by:**
  `tests/test_phi_scan.py::the matched text is never printed`
  `tests/test_phi_scan.py::a clean run does not claim there is no patient information`

### C-74 The PHI scan reaches the history

- **Claim:** The scan reads every unpurged revision and unredacted audit entry, not
  only the live record, so a value edited out of the record is still found.
- **Asserted in:** `docs/self-hosting.md` — "every revision not yet purged"
- **Status:** partial
- **Gap:** It finds only the patterns it has. A name, a date or a free-form case
  description is not checked, by design (R-50). Earlier backups are not scanned.
  #66
- **Enforced by:**
  `tests/test_phi_scan.py::the history is scanned, and the revisions are named`
  `tests/test_phi_scan.py::the audit log is scanned`

### C-75 A restore puts purges back

- **Claim:** `make restore` re-applies every purge the live database holds after it
  restores an older dump, and says so when it cannot.
- **Asserted in:** `docs/privacy.md` — "`make restore` puts the purges back."
- **Status:** partial
- **Gap:** When the live database cannot be read, the purges come back only if
  someone rebuilds the ledger from the security log; purge events from before
  this change lack the fields and must be re-applied by hand. #116
- **Enforced by:**
  `tests/test_purge_ledger.py::the mistaken content is gone again`
  `tests/test_purge_ledger.py::work written after the restore is untouched`
  `tests/test_purge_ledger.py::capture, then the restore, then reapply`

### C-76 A translated warning is shown only once someone has reviewed it

- **Claim:** The patient-data notice and the storage-mode banners stay in English
  in a language until a reviewer is recorded for them in that catalog.
- **Asserted in:** `docs/developing.md` — "are shown in English until someone fluent in the"
- **Status:** enforced
- **Enforced by:**
  `tests/test_i18n.py::the unreviewed safety warning stays in English`
  `tests/test_i18n.py::once a reviewer is recorded, it shows in Spanish`

### C-77 Only the database owner can dispose, and not of a recent read

- **Claim:** The API's role cannot run disposal or delete the read trail, and the
  database refuses to delete a read-trail row younger than the period, even for
  the owner.
- **Asserted in:** `docs/privacy.md` — "Only the database owner can dispose. The API cannot: its database role has no"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_retention.py::test_the_api_role_cannot_dispose_or_delete_the_read_trail`
  `server/tests/test_retention.py::test_the_trigger_refuses_what_the_policy_does_not_allow`

### C-78 A litigation hold stops disposal

- **Claim:** A project under a litigation hold, and its read trail, are not
  disposed of until the hold is lifted.
- **Asserted in:** `docs/privacy.md` — "A project under a hold is listed in the"
- **Asserted in:** `docs/privacy.md` — "A project's owner can place a litigation hold, with a reason, and the project and its read trail are kept until it is lifted."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_retention.py::test_a_held_project_is_reported_and_kept_until_the_hold_is_lifted`
  `server/tests/test_retention.py::test_the_read_trail_loses_only_rows_past_the_period_and_not_held`

### C-79 Only a project's owners see or change its litigation hold

- **Claim:** A hold, and the reason given for it, can be seen, placed and lifted
  only by an owner of the project.
- **Asserted in:** `app/i18n/en.json` — "until it is lifted. Only owners see this."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_holds.py::test_only_an_owner_may_see_or_change_a_hold`
  `tests/test_holds_ui.py::sees no hold section`

### C-80 The dashboard and its exports contact no outside service

- **Claim:** No screen, dialog, language or export of the dashboard makes a
  request to another host, none of its exports carries a resource a viewer would
  fetch on its own, and opening a saved report announces nothing to a third party
  (R-05). A link the reader chooses to follow is not such a request.
- **Asserted in:** `docs/index.md` — "The dashboard and its exports contact no
  outside service."
- **Asserted in:** `docs/adopting.md` — "The dashboard and its exports contact no
  outside service."
- **Status:** enforced
- **Enforced by:**
  `tests/test_no_third_party.py::loading the dashboard makes no external request`
  `tests/test_no_third_party.py::no screen, dialog, language or export makes a request to another host`
  `tests/test_no_third_party.py::the Markdown export has no image (an image is a request when it is read)`
  `tests/test_no_third_party.py::opening the saved report makes no request to another host`
  `tests/test_no_third_party.py::the HTML export has no http(s) resource URLs at all`

### C-81 A SHA-256 of the record travels in the JSON export

- **Claim:** The JSON export, and the HTML and Markdown reports, carry a SHA-256 and
  an MD5 of the record, and the digests can be recomputed from the JSON file alone.
- **Asserted in:** `app/i18n/en.json` — "A SHA-256 travels in the JSON export for anyone who needs the stronger property."
- **Status:** enforced
- **Enforced by:**
  `tests/test_fingerprint.py::a second implementation recomputes both from the file alone`
  `tests/test_fingerprint.py::an edited record fails to verify`
  `tests/test_fingerprint.py::the HTML report (which the PDF prints) has both digests`
  `tests/test_fingerprint.py::the notice says a SHA-256 travels in the JSON export, and now it does`
  `tests/test_export_schema.py::a record keyed by numbers: fingerprint recomputed (regression)`
  `tests/test_export_schema.py::answers keyed by numbers: fingerprint recomputed (regression)`
  `tests/test_export_schema.py::load_export.py reads it and says the fingerprint matches`
  `tests/test_fingerprint_skip.py::all six places name the same fields`

### C-82 Text a person types stays text, on every screen and in every export

- **Claim:** A value typed into any field of a project, or imported, never runs and
  never becomes markup in the dashboard, the HTML report, the PDF's frame or the
  Markdown report, cannot become a spreadsheet formula, and a new way of turning text
  into markup is reviewed before it is added (R-59).
- **Asserted in:** `docs/developing.md` — "Text a person types stays text."
- **Asserted in:** `docs/exports.md` — "Whatever a person typed stays text in every export."
- **Status:** partial
- **Gap:** Escaping is the first barrier, and the page's own policy is the second (C-84),
  and both are tested in Chromium, Firefox and WebKit. The Markdown report is now also
  rendered by markdown-it-py, a CommonMark reference implementation, as CommonMark and
  as GFM, each with raw HTML refused and with it passed through (the worst case, no
  sanitizer), and the HTML audited (#167, D-85). What that does not cover is every
  other reader: GitHub's own renderer and sanitizer, an editor preview and a wiki are
  not run, and syntax only some of them add (an @mention, a #reference, `$` math, an
  emoji code, a footnote, an email autolink, a wiki's own markup) is not audited. A
  GFM renderer links a bare address a person typed, and a bare address with
  credentials (`https://user:pass@host/`) used to pass the audit; since #194 (D-88)
  the dashboard removes the credentials on entry and import and the export removes
  them again, and the audit fails on any credentialed link (C-118). A claim about
  every renderer cannot be proven with one, so this stays partial.
- **Enforced by:**
  `tests/test_markdown_render.py::every payload, sample and language renders as text in every configuration`
  `tests/test_markdown_render.py::the example build's poisoned definition and records render as text`
  `tests/test_markdown_render.py::every weakened export is rejected`
  `tests/test_markdown_render.py::a bare address with credentials, linked by a renderer, fails the audit`
  `tests/test_injection.py::an app that does not escape is rejected`
  `tests/test_injection.py::the CSV rule notices a formula cell`
  `tests/test_injection.py::the Markdown rules notice a heading, a script link and raw HTML`
  `tests/test_check_injection.py::a stored value interpolated into a class attribute is counted`
  `tests/test_check_injection.py::is within its baseline`

### C-83 The server never builds SQL from text

- **Claim:** Every SQL call passes a constant string with values as parameters, except
  the migration files and the role the API serves as, and hostile text in any field is
  stored and returned as text.
- **Asserted in:** `docs/developing.md` — "the server passes values to SQL as parameters and never in the SQL text"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_sql_injection.py::test_every_sql_call_passes_a_constant_string`
  `server/tests/test_sql_injection.py::test_the_guard_notices_each_way_text_reaches_sql`
  `server/tests/test_sql_injection.py::test_hostile_text_is_stored_and_returned_as_text`

### C-84 The proxy's policy refuses script the page did not ship

- **Claim:** The Content-Security-Policy the proxy serves, and the same policy carried
  by the page itself as a meta tag (so it holds on the example page and in a copy
  opened from disk), allows the dashboard's one inline script by its SHA-256 and not
  by `'unsafe-inline'`, so an injected script, an event handler or a `javascript:`
  link is refused by the browser, and the exported report carries a policy of its own
  that allows no script at all. Each browser enforces the policy with its own
  implementation, so the tests run in Chromium, Firefox and WebKit (#160).
- **Asserted in:** `proxy/Caddyfile` — "The script is allowed by its hash, not by 'unsafe-inline'."
- **Status:** enforced
- **Enforced by:**
  `tests/test_csp.py::names the hash of the page's one script`
  `tests/test_csp.py::an injected inline script, handler and javascript: link did not run`
  `tests/test_csp.py::a policy that names a different script does not boot the app`
  `tests/test_csp.py::so a script put into a saved report does not run`
  `tests/test_csp.py::served with no header it boots, with no violation`
  `tests/test_csp.py::and refuses an injected script, handler and javascript: link`
  `tests/test_csp.py::opened from disk it refuses the same injection too`
  `tests/test_csp.py::a tag naming a different script does not boot the app`
  `tests/test_proxy_identity.py::content-security-policy`

### C-85 An evidence reference's file never leaves the browser

- **Claim:** Attaching a file to an evidence reference reads it in the browser and
  stores its name, size and SHA-256, and nothing else: the file is not uploaded,
  its bytes are not in the record, and the code that reads it has no way to send
  anything.
- **Asserted in:** `docs/guide.md` — "The file is never uploaded."
- **Asserted in:** `app/i18n/en.json` — "A file is never uploaded: only its name, size and SHA-256 are kept"
- **Status:** enforced
- **Enforced by:**
  `tests/test_refs.py::the stored file is a name, a size and a digest, nothing else`
  `tests/test_refs.py::no bytes of the file are in the record`
  `tests/test_refs.py::adding a file made no network request`
  `tests/test_refs.py::the reference code has no way to send anything`
  `tests/test_refs.py::a fetch in the reference code is noticed`
  `tests/test_refs.py::the stored SHA-256 is hashlib's`
  `server/tests/test_refs_merge.py::test_concurrent_adds_to_one_item_keep_every_reference`

### C-86 A reference's link is http or https, or it is not a link

- **Claim:** The address of an evidence reference becomes a link only if it is an
  http or https address with no credentials in it, both when it is typed and when it
  is read back from a stored or imported record, in the dashboard and in every
  export.
- **Asserted in:** `docs/guide.md` — "**A link opens only if it is an http or https address**"
- **Status:** enforced
- **Enforced by:**
  `tests/test_refs.py::a stored javascript: address is never made a link`
  `tests/test_refs.py::parentheses and brackets in an address cannot end the link early`
  `tests/test_refs.py::entries that are not references are dropped`
  `tests/test_refs.py::with safeUrl weakened, the same probe shows the hole`
  `tests/test_markdown.py::with safeUrl weakened the structure check would catch the hole`
  `tests/test_injection.py::an app that does not escape is rejected`

### C-87 Formatting in notes cannot introduce markup

- **Claim:** In the notes and rationale fields, formatting is limited to bold,
  italic, lists and http(s) links, and for any text the HTML and the Markdown
  written from it contain only that: no raw HTML, image, table, heading, script
  or non-http link, whatever the text holds, and the work is bounded on input
  built to make a parser crawl.
- **Asserted in:** `docs/guide.md` — "raw HTML, images, tables and headings are shown as the text they are"
- **Status:** enforced
- **Enforced by:**
  `tests/test_markdown.py::HTML holds only the subset's tags, links and attributes`
  `tests/test_markdown.py::no raw HTML, image, line break or foreign link`
  `tests/test_markdown.py::its links are the HTML's links`
  `tests/test_markdown.py::with esc weakened the structure check would catch the tag`
  `tests/test_markdown.py::with safeUrl weakened the structure check would catch the hole`
  `tests/test_injection.py::an app that does not escape is rejected`

### C-88 The server retires exactly what the build's definition marks ending

- **Claim:** The database treats a project as retired, and starts its retention
  clock (R-56), exactly when one of its checkpoints holds a decision that the
  project's framework definition, as the deployed build's manifest states it,
  gives a stop or retire class at that checkpoint. A record without a framework
  stamp is CHAI's. The migrate job, and the API when it migrates itself with a
  manifest, refuses any change (an ending decision added or dropped, or a new
  primary) unless `RETIREMENT_RULES_ACK` is the acknowledgment of exactly that
  change: the SHA-256 of every rule the table holds before and after it, the
  primary before and after, the history row it follows (its id and time), and the
  database's identity (012: the cluster's system identifier, the database's OID
  and the OID of the history table, none of which a dump carries). So a value
  printed for one change never accepts a different one (a build that also drops
  an unlisted framework's rules, a rollback to another primary, a switch to
  another primary over the same rules), once used it accepts nothing later, and
  another database refuses it even with the same history, as does a copy restored
  from a dump that creates the tables again (`make restore`), into another
  database or over the same one in place. It leaves the
  rules of frameworks the manifest does not list, and fails without a usable
  manifest, so disposal never changes silently (R-66, D-76). The operator is shown
  the projects that would become due or stop being due as they stood when the
  value was printed; the value binds the rules and the primary, not the records,
  so a project edited before the acknowledged run is affected without having been
  listed. Each guard in the SQL (the join on the record's framework, a blank stamp
  read as CHAI's, the clock at the latest ending decision), the parts of the
  acknowledgment (the identity dropped, a value from one database is accepted by
  another; the database's OID dropped, by a copy in another database; the history
  table's OID dropped, by a copy restored in place; the primary after dropped, by
  a switch to another primary), and the migration lock (taken before the rules
  are read, so a sync waiting on another job works from what that job committed)
  has a test that breaks it and fails.
- **Gap:** the stack test proves only the default build: its rule set is
  010's seed (the same hash), so it shows the migrate job read and confirmed the
  manifest (`synced`), not that a different rule set reaches a running stack. That
  a different set is loaded, refused or acknowledged is the server tests' evidence,
  against a real PostgreSQL and the real migrate job. The server tests restore a
  dump by copying its rows with COPY, as pg_dump does, into a database the real
  migrate job built; `tests/test_verify_backup.py` shows with a real pg_dump that
  the identity differs after a restore into another database, over the same one
  in place, and into another cluster. A copy of the database's files (a base
  backup, a snapshot, point-in-time recovery, a promoted replica) keeps the
  identity and the history, so it accepts again a value printed against the state
  it holds, and a staging database made that way and production each accept a
  value printed on the other; `docs/self-hosting.md` says so, and advises building
  staging from a dump. A restore of the data alone into the tables already there
  (`pg_dump --data-only`, or TRUNCATE and reload, as the owner) keeps the history
  table's OID, so a value spent after the dump was taken is accepted again;
  `docs/self-hosting.md` says so too. Nothing prevents either. And the value does not
  bind the records, so the list the operator saw can be out of date when the
  value is used.
- **Asserted in:** `docs/self-hosting.md` — "another database refuses it even when its history is the same"
- **Asserted in:** `docs/self-hosting.md` — "loads those decisions into the database, which decides from them when a project is retired"
- **Asserted in:** `docs/privacy.md` — "A build of another framework retires on its own decisions"
- **Asserted in:** `docs/frameworks/custom.md` — "from the checkpoint options your definition classes `stop` or `retire`"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_retention.py::test_every_chai_decision_retires_exactly_when_its_class_ends_a_project`
  `server/tests/test_retention.py::test_a_stand_in_primary_retires_by_its_own_words_once_acknowledged`
  `server/tests/test_retention.py::test_a_new_ending_decision_is_refused_until_acknowledged`
  `server/tests/test_retention.py::test_a_leftover_acknowledgment_never_matches_another_transition`
  `server/tests/test_retention.py::test_a_stale_manifest_cannot_undo_a_newer_one`
  `server/tests/test_retention.py::test_a_manifest_leaves_the_rules_of_frameworks_it_does_not_list`
  `server/tests/test_retention.py::test_an_ack_for_a_harmless_addition_never_accepts_a_removal`
  `server/tests/test_retention.py::test_a_rollback_is_acknowledged_and_does_not_revive_an_old_ack`
  `server/tests/test_retention.py::test_a_leftover_ack_never_accepts_a_later_change`
  `server/tests/test_retention.py::test_a_primary_switch_over_the_same_rules_needs_an_ack`
  `server/tests/test_retention.py::test_a_value_printed_for_one_database_is_refused_by_another`
  `server/tests/test_retention.py::test_the_database_test_fails_without_the_identity`
  `server/tests/test_retention.py::test_a_dump_restored_elsewhere_refuses_the_originals_value_both_ways`
  `server/tests/test_retention.py::test_a_dump_restored_in_place_refuses_a_value_printed_before_it`
  `server/tests/test_retention.py::test_the_restore_tests_fail_without_the_history_table_in_the_identity`
  `server/tests/test_retention.py::test_the_restore_tests_fail_without_the_database_oid_in_the_identity`
  `server/tests/test_retention.py::test_without_the_identity_a_change_is_refused_and_nothing_else_is`
  `server/tests/test_retention.py::test_012_reads_the_identity_the_acknowledgment_states`
  `server/tests/test_retention.py::test_an_identity_with_a_null_part_is_refused_cleanly`
  `server/tests/test_retention.py::test_a_value_for_one_new_primary_is_refused_for_another_over_the_same_rules`
  `server/tests/test_retention.py::test_the_new_primary_test_fails_when_the_value_omits_the_primary_after`
  `server/tests/test_retention.py::test_every_part_of_the_acknowledgment_changes_it`
  `server/tests/test_retention.py::test_a_record_follows_only_its_own_frameworks_rules`
  `server/tests/test_retention.py::test_the_mirror_a_chai_record_never_retires_by_anothers_words`
  `server/tests/test_retention.py::test_a_blank_stamp_is_chai`
  `server/tests/test_retention.py::test_the_clock_starts_at_the_latest_ending_decision`
  `server/tests/test_retention.py::test_the_database_retires_by_the_table_not_by_literals`
  `server/tests/test_retirement_rules.py::test_the_migrate_job_fails_closed_without_a_usable_manifest`
  `server/tests/test_retirement_rules.py::test_a_manifest_the_server_would_misread_is_refused`
  `server/tests/test_retirement_rules.py::test_the_api_migrating_itself_syncs_from_its_manifest`
  `server/tests/test_retirement_rules.py::test_the_api_migrating_itself_without_a_manifest_says_so`
  `server/tests/test_retirement_rules.py::test_an_api_with_no_manifest_never_reports_synced`
  `server/tests/test_retirement_rules.py::test_two_syncs_serialize_on_the_migration_lock`
  `server/tests/test_retirement_rules.py::test_the_lock_test_fails_when_the_lock_is_taken_after_the_reads`
  `tests/test_stack.py::the database retires by the served build's rule set, synced from it`
  `tests/test_verify_backup.py`

### C-89 The API's role cannot change which decisions retire a project

- **Claim:** The API's database role can read the retirement rules and their
  history and cannot insert, update, delete or truncate either, and the history
  refuses an update or a delete even from the owner.
- **Asserted in:** `docs/privacy.md` — "Nor can it change which decisions retire a project: its role may only read those rules."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_retirement_rules.py::test_the_api_role_can_read_the_rules_and_not_change_them`
  `server/tests/test_retirement_rules.py::test_the_rules_history_is_append_only_even_for_the_owner`
  `server/tests/test_roles.py`

### C-90 A writer cannot choose which framework's rules retire a record

- **Claim:** A record follows the retirement rules of the framework its
  `meta.framework.id` names, so a writer who could stamp any id could keep a
  record from ever coming due. The API refuses (422) a create that sets
  `meta.framework` to anything but exactly `{"id": <the primary the latest sync
  recorded>}`; a record without one is CHAI's. While that primary is not CHAI, it
  also refuses a create that leaves the stamp out, so omitting it cannot choose
  CHAI's rules. It refuses a patch that would change the framework the record
  follows, as 010's `record_framework()` reads it before and after the patch (by
  setting, removing or blanking the stamp, or replacing `meta`), and a patch that
  sets the stamp to anything but exactly the record's own framework: so a record
  written before a switch keeps its framework and stays editable, and one written
  under a later primary keeps it after a rollback. A create reads the primary
  under the migration lock, shared, so creates do not wait on one another: a sync
  that changes the primary waits for every create in flight, and one that starts
  during the sync waits and reads the new primary, so none is checked against a
  primary that has just been replaced. A patch reads no primary and takes no lock.
  Stamps written before this check,
  or by the database owner, are not re-checked,
  and `make dispose` and `make verify-backup` count the records whose framework
  has no rules (R-66, D-76).
- **Asserted in:** `docs/privacy.md` — "Nor can a writer choose which framework's rules a record follows"
- **Asserted in:** `docs/frameworks/custom.md` — "the API accepts a new record only with your primary's stamp"
- **Asserted in:** `docs/self-hosting.md` — "so no record is checked against a primary that has just been replaced"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_retirement_rules.py::test_the_api_refuses_a_stamp_that_is_not_the_active_primary`
  `server/tests/test_retirement_rules.py::test_the_api_accepts_no_stamp_or_exactly_the_active_primarys`
  `server/tests/test_retirement_rules.py::test_a_stamp_follows_the_primary_the_latest_sync_recorded`
  `server/tests/test_retirement_rules.py::test_under_another_primary_a_record_must_carry_its_stamp`
  `server/tests/test_retirement_rules.py::test_a_correctly_stamped_record_retires`
  `server/tests/test_retirement_rules.py::test_the_sql_reads_a_stamp_as_the_api_does`
  `server/tests/test_retirement_rules.py::test_a_write_that_read_the_primary_holds_off_a_switch`
  `server/tests/test_retirement_rules.py::test_the_race_test_fails_without_the_shared_lock`
  `server/tests/test_retirement_rules.py::test_two_creates_hold_the_lock_at_once`
  `server/tests/test_retirement_rules.py::test_the_shared_lock_test_fails_with_an_exclusive_lock`
  `server/tests/test_retirement_rules.py::test_a_patch_never_waits_on_the_migration_lock`
  `server/tests/test_retirement_rules.py::test_the_no_wait_test_fails_when_a_patch_takes_the_lock`
  `server/tests/test_retirement_rules.py::test_a_patch_cannot_stamp_a_pre_switch_record_with_the_new_primary`
  `server/tests/test_retirement_rules.py::test_a_patch_cannot_unstamp_a_record_after_a_rollback`
  `server/tests/test_retirement_rules.py::test_no_patch_changes_a_records_framework_or_reshapes_its_stamp`
  `server/tests/test_retirement_rules.py::test_a_patch_that_keeps_a_records_framework_still_works`
  `server/tests/test_retirement_rules.py::test_the_framework_check_fails_when_a_patch_is_checked_against_the_primary`
  `server/tests/test_retirement_rules.py::test_the_framework_check_fails_when_only_the_stamp_shape_is_checked`
  `tests/test_dispose.py`
  `tests/test_verify_backup.py`

### C-91 A framework definition's text is never run

- **Claim:** Whatever characters a framework definition holds (a name, an item,
  a status, a checkpoint, a sample), the dashboard shows them as text and runs
  none of them, on every screen and in the HTML and Markdown exports.
- **Asserted in:** `docs/frameworks/custom.md` — "A definition's text is never run as code"
- **Status:** enforced
- **Enforced by:**
  `tests/test_custom_build.py::no definition text is in the page raw, where it could end the script`
  `tests/test_custom_build.py::the markup shows as text, on every screen that shows it`
  `tests/test_custom_build.py::no screen makes an element it names`
  `tests/test_custom_build.py::the flag's checkpoint name is escaped in the Markdown`
  `tests/test_custom_build.py::the HTML export holds no tag from it`
  `tests/test_custom_build.py::the Markdown export holds no tag from it`

### C-92 A build opens only its own framework's records

- **Claim:** A build of other frameworks lists, opens and imports only records
  stamped with its own primary; a record of another framework, including an
  unstamped one from the published build, is left off the portfolio and refused
  when opened or imported (R-67).
- **Asserted in:** `docs/frameworks/custom.md` — "Your build lists, opens and imports only its own records"
- **Status:** enforced
- **Enforced by:**
  `tests/test_custom_build.py::the portfolio lists only the example's record`
  `tests/test_custom_build.py::opening an unstamped record is refused`
  `tests/test_custom_build.py::opening another primary's record is refused`
  `tests/test_custom_build.py::every record it makes is stamped with its primary`

### C-93 A custom build's saved work is kept apart from the published build's

- **Claim:** In local mode a build of other frameworks stores its records under
  browser storage keys carrying its primary's id, never the published build's
  keys.
- **Asserted in:** `docs/frameworks/custom.md` — "your build saves under browser storage keys that carry your primary's id"
- **Status:** enforced
- **Enforced by:**
  `tests/test_custom_build.py::its records are stored under the example's key, not the published build's`
  `tests/test_custom_build.py::its view state is stored under the example's key, not the published build's`

### C-94 A custom build cannot overwrite the published page or its policy

- **Claim:** `build_app.py --config` refuses an `--out` that would write under
  `docs/`, `proxy/` or `app/` (following links), and a custom build leaves the published dashboard and the proxy's
  policy byte for byte as they were.
- **Asserted in:** `docs/frameworks/custom.md` — "The build refuses an `--out` under `docs/` or `proxy/`"
- **Status:** enforced
- **Enforced by:**
  `tests/test_build_config.py::the published page and policy are untouched`
  `tests/test_build_config.py::an --out into docs/, proxy/ or app/ is refused`
  `tests/test_build_config.py::--config without --out is refused`

### C-95 The page says when its server retires records by other rules, and records no decision

- **Claim:** A page served by the API compares the rule-set hash and primary its
  build embedded with the server's `retirement_rules`. When they differ it shows
  an alert saying so, and records no checkpoint decision and creates no record
  until they agree; when the server's rules were not synced from a manifest it
  says so. Nothing is shown when they agree. These refusals are the page's; the
  server's stamp and acknowledgment checks (C-88 to C-90) are what bind.
- **Asserted in:** `docs/self-hosting.md` — "Until they agree, the page records no checkpoint decision and creates no new record"
- **Asserted in:** `docs/frameworks/custom.md` — "it shows a banner saying so and records no decision and creates no new record"
- **Status:** enforced
- **Enforced by:**
  `tests/test_rules_banner.py::a different hash shows the banner`
  `tests/test_rules_banner.py::as an alert`
  `tests/test_rules_banner.py::and a decision is refused even if pressed`
  `tests/test_rules_banner.py::a new record is refused`
  `tests/test_rules_banner.py::a different primary shows the banner`
  `tests/test_rules_banner.py::unsynced rules show the banner`
  `tests/test_rules_banner.py::rules that agree show no banner`
  `tests/test_rules_banner.py::the page embeds its manifest's rule-set hash`

### C-96 A revision's fingerprint is the record's, as the dashboard shows it

- **Claim:** The server hashes each revision in the version history by the rule
  the dashboard and `examples/load_export.py` use (the record as stored, the same
  fields left out, keys in the same order, strings written alike, the project's
  id included), so the same record has one fingerprint on the setup page, in an
  export and in the history, an older record missing fields the dashboard fills
  in included.
- **Asserted in:** `docs/exports.md` — "a revision's fingerprint is the one the setup page and an export showed for that record"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_fingerprint.py::test_the_server_gives_the_record_the_dashboards_fingerprint`
  `server/tests/test_fingerprint.py::TestARevisionCarriesTheRecordsFingerprint::test_the_version_history_agrees_with_an_export`
  `server/tests/test_fingerprint.py::TestAnOlderRecordIsHashedAsStored::test_the_revision_is_the_stored_records_fingerprint`
  `server/tests/test_fingerprint.py::test_a_lone_surrogate_is_written_as_javascript_writes_it`
  `server/tests/test_fingerprint.py::test_the_server_gives_a_real_export_the_dashboards_fingerprint`
  `server/tests/test_fingerprint.py::TestARealSampleRecordsRevision::test_the_version_history_gives_it_the_exports_fingerprint`
  `tests/test_export_schema.py::the committed sample export's fingerprint is the dashboard's digest of its`
  `tests/test_export_schema.py::the dashboard's stored record is the store's, nothing filled in`
  `tests/test_export_schema.py::the shared record's fingerprint is the one the server and`
  `tests/test_export_schema.py::its export's fingerprint is the stored record's`
  `tests/test_export_schema.py::an edit's history entry carries the fingerprint of what was stored`
  `tests/test_fingerprint_skip.py::all six places name the same fields`

### C-118 Credentials are removed from addresses in text

- **Claim:** A user name or password in an address a person types, pastes or
  imports, in any field, is removed and the person is told, the change history
  never records it, and the Markdown report never prints it, even for a record that
  already holds it; the stored record, its fingerprint and the JSON export are not
  changed by the report (R-70).
- **Asserted in:** `docs/guide.md` — "**Credentials are removed from addresses.**"
- **Asserted in:** `docs/exports.md` — "An address in a value never keeps its credentials in the Markdown report"
- **Status:** enforced
- **Enforced by:**
  `tests/test_address_credentials.py::every case: what remains, the count and idempotence`
  `tests/test_address_credentials.py::every weakened rule is noticed`
  `tests/test_address_credentials.py::the password is nowhere: not the record, the history, the queue or storage`
  `tests/test_address_credentials.py::the field ends as the address without credentials`
  `tests/test_address_credentials.py::a reference's title loses the credentials`
  `tests/test_address_credentials.py::a new project's name loses the credentials`
  `tests/test_address_credentials.py::a hold reason is sent without the credentials`
  `tests/test_address_credentials.py::and holds no password, in its words or its from and to`
  `tests/test_address_credentials.py::every field that carried credentials holds the address without them`
  `tests/test_address_credentials.py::a legacy review keeps its address without the credentials`
  `tests/test_address_credentials.py::a record made with credentials is stored without`
  `tests/test_address_credentials.py::the Markdown report has no password`
  `tests/test_address_credentials.py::the stored record is unchanged by the export`
  `tests/test_address_credentials.py::so is its fingerprint`
  `tests/test_address_credentials.py::the JSON export keeps the stored text, as its contract says`
  `tests/test_address_credentials.py::every weakened guard is noticed`
  `tests/test_markdown_render.py::every weakened export is rejected`

### C-97 A token is accepted on the agent routes and on no other

- **Claim:** A bearer token authenticates a request only under `/api/agent/`. On
  every other route it is not read: with no identity header the request is a 401,
  and beside an identity header the session answers and the token is ignored. Only
  the agent module reads the `Authorization` header.
- **Asserted in:** `docs/agent-api.md` — "It is accepted under `/api/agent/` and on no other route. On every other route it is not read at all."
- **Asserted in:** `docs/deploy.md` — "It is not a way to sign in: no other route accepts it."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_a_bearer_alone_authenticates_nobody_on_any_other_route`
  `server/tests/test_agent_api.py::test_the_session_identity_never_reads_a_bearer`
  `server/tests/test_agent_api.py::test_only_the_agent_module_reads_a_bearer_header`
  `server/tests/test_agent_api.py::test_the_agent_prefix_is_exactly_the_agent_routes`
  `server/tests/test_agent_mutations.py::test_each_guard_is_noticed_when_broken`

### C-98 A token cannot mint, list or revoke tokens

- **Claim:** The routes that mint, list and revoke tokens take the signed-in
  session and nothing else, so a stolen token cannot make itself a successor or end
  its owner's other tokens.
- **Asserted in:** `docs/agent-api.md` — "it cannot mint, list or revoke tokens (those routes take the person's signed-in session and nothing else)"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_a_token_cannot_mint_list_or_revoke_tokens`
  `server/tests/test_agent_api.py::test_a_bearer_alone_authenticates_nobody_on_any_other_route`
  `server/tests/test_agent_mutations.py::test_each_guard_is_noticed_when_broken`

### C-99 Every bad token is one answer

- **Claim:** A token that is missing, malformed, unknown, wrong, expired, revoked
  or whose owner is gone gets the same status, the same body and the same header
  on every agent route, except that a source that has already used up its failures
  for the window is answered 429 instead, whatever it sent. Which it was is in the
  read trail, for the operator, and nowhere in the response. Response timing is
  not claimed to be equal: whether a public token id exists can be told by timing.
- **Asserted in:** `docs/agent-api.md` — "and removed are the same answer: the same status, the same body, the same header."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_every_bad_token_gets_the_same_401`
  `server/tests/test_agent_api.py::test_a_token_works_until_the_eighth_hour_and_not_after`
  `server/tests/test_agent_api.py::test_only_a_token_that_exists_leaves_a_trail_row_when_refused`
  `tests/test_stack.py::a token that is wrong is the uniform 401`

### C-100 The identity header means nothing on an agent route

- **Claim:** The API reads no identity header on the agent routes, whatever its
  name, so a client cannot choose who it is by sending one. As defense in depth the
  proxy deletes sixteen identity header names it knows and sets none; that list is
  fixed, and a header with another name reaches the API and is ignored there.
- **Asserted in:** `docs/agent-api.md` — "The API does not read any identity header there, whatever its name, so a client cannot choose who it is by sending one."
- **Asserted in:** `proxy/Caddyfile` — "It is safe because of what this block does NOT do: it never sets an identity"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_the_identity_header_means_nothing_on_an_agent_route`
  `tests/test_proxy_identity.py::no client-supplied identity header reaches the API`
  `tests/test_proxy_identity.py::the proxy sets no identity on the agent route`
  `tests/test_proxy_agent_mutations.py`

### C-101 The proxy forwards only the three agent GET routes on that path

- **Claim:** Without a single sign-on session, the proxy forwards exactly the
  three agent GET routes and answers any other method or path under
  `/api/agent/` with a 404 itself. Every other route is as it was: a request with
  no signed-in identity is refused, whatever it carries.
- **Asserted in:** `docs/agent-api.md` — "forwards exactly the three agent `GET` routes, deletes sixteen known identity header names on them as defense in depth and sets none"
- **Asserted in:** `docs/self-hosting.md` — "deletes the identity header names it knows (a fixed list of sixteen) as defense in depth and sets none"
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::is refused by the proxy`
  `tests/test_proxy_identity.py::agent route: none of those reached the API`
  `tests/test_proxy_identity.py::a bearer alone is refused by the proxy`
  `tests/test_proxy_identity.py::a forged identity beside a bearer is refused`
  `tests/test_proxy_agent_mutations.py`

### C-102 An agent sees what its owner's dashboard shows, and no more

- **Claim:** A token reads the projects the same person's own project list gives,
  from the same code, with archived projects taken out. It never has emergency
  access, whoever minted it, and loses a project the moment its owner loses access.
- **Asserted in:** `docs/agent-api.md` — "The projects the token's owner's own dashboard lists, with archived ones taken out."
- **Asserted in:** `docs/agent-api.md` — "An agent never has emergency access, whoever minted its token"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_a_token_sees_exactly_the_projects_its_users_dashboard_lists`
  `server/tests/test_agent_api.py::test_an_archived_project_is_never_returned_by_any_route`
  `server/tests/test_agent_api.py::test_an_emergency_user_gets_no_emergency_access_through_a_token`
  `server/tests/test_agent_api.py::test_losing_access_takes_the_project_from_a_live_token`
  `server/tests/test_agent_mutations.py::test_each_guard_is_noticed_when_broken`

### C-103 No name, email or free text reaches an agent

- **Claim:** An agent response is built from an allowlist of stored keys, never
  copied from the stored record: no name, no email, no note, rationale, evidence
  title, committee name or project name, and no computed phase, flag, score or
  verdict. A key a writer chose (an item, checkpoint or supplement id) and a
  status or decision are returned only if they are words of the build's framework
  definitions (see C-113); a person and a project are opaque ids.
- **Asserted in:** `docs/agent-api.md` — "No name and no email appears in any response, and a project is a reference, not its name."
- **Asserted in:** `docs/agent-api.md` — "Each response is built field by field from an allowlist of stored keys."
- **Asserted in:** `docs/privacy.md` — "No name, no email and no free text is returned"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_nothing_hostile_planted_anywhere_reaches_an_agent`
  `server/tests/test_agent_api.py::test_the_response_models_are_closed_allowlists`
  `server/tests/test_agent_api.py::test_the_vocabulary_is_the_framework_definitions`
  `server/tests/test_agent_api.py::test_a_builds_own_words_pass_and_the_published_ones_do_not_cross_over`
  `server/tests/test_agent_docs.py::test_the_documented_response_fields_are_the_models_exactly`
  `server/tests/test_agent_mutations.py::test_each_guard_is_noticed_when_broken`

### C-104 People are opaque ids

- **Claim:** A person and a project are shown to an agent only as keyed
  pseudonyms (HMAC-SHA256 under `AGENT_ID_SECRET`, a different domain prefix for
  each): the same one is the same id in every call of a deployment, another
  deployment's key gives other ids, and the id is not the identity or a bare hash
  of it. A project is found by its reference among what the person's dashboard
  shows, and an unknown, an invisible and an archived one are one 404.
- **Asserted in:** `docs/agent-api.md` — "People and projects as **opaque ids** (`u_` and `pr_`, then 32 hex characters)."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_opaque_ids_are_stable_keyed_and_not_the_identity_or_its_hash`
  `server/tests/test_agent_api.py::test_the_same_person_is_the_same_id_across_calls_and_projects`
  `server/tests/test_agent_api.py::test_a_different_deployments_secret_gives_different_ids`
  `server/tests/test_agent_api.py::test_a_short_secret_stops_the_server_starting`
  `server/tests/test_agent_api.py::test_a_project_ref_is_stable_keyed_and_resolves_only_what_is_visible`

### C-105 A token lasts exactly 8 hours and is stored only as a hash

- **Claim:** A token is valid for exactly 8 hours from minting, and the database
  refuses any other lifetime. It is shown once, in the mint response; the server
  keeps a SHA-256 hash of it, and its identity and expiry cannot be rewritten.
- **Asserted in:** `docs/agent-api.md` — "Exactly 8 hours from the moment it is minted, and the database refuses any other lifetime."
- **Asserted in:** `docs/agent-api.md` — "only a SHA-256 hash of the whole token is stored"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_a_minted_token_has_the_shape_and_the_fixed_lifetime`
  `server/tests/test_agent_api.py::test_the_database_refuses_any_other_lifetime`
  `server/tests/test_agent_api.py::test_the_secret_is_shown_once_and_stored_only_as_a_hash`
  `server/tests/test_agent_api.py::test_a_token_works_until_the_eighth_hour_and_not_after`
  `server/tests/test_agent_api.py::test_a_tokens_identity_and_expiry_cannot_be_rewritten`
  `server/tests/test_agent_api.py::test_tokens_are_compared_in_constant_time_and_only_there`
  `server/tests/test_agent_mutations.py::test_each_guard_is_noticed_when_broken`

### C-106 A person holds at most five live tokens

- **Claim:** A sixth live token is refused with a 409, also when two mints arrive
  at once. Expired and revoked tokens do not count.
- **Asserted in:** `docs/agent-api.md` — "A sixth is refused with `409` until one expires or is revoked."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_a_person_holds_at_most_five_live_tokens`
  `server/tests/test_agent_api.py::test_two_mints_at_once_cannot_both_pass_the_count`
  `server/tests/test_agent_api.py::test_the_limit_is_a_setting`

### C-107 A token dies with its owner's principal

- **Claim:** Erasing a person's principal, which `make dispose` does when nothing
  retained names them, deletes their tokens with it, and a deleted token stops
  working. Removal from the identity provider is not seen by the app, so the
  8 hours is the bound there (the page says so).
- **Asserted in:** `docs/agent-api.md` — "Their tokens are deleted with it."
- **Asserted in:** `docs/privacy.md` — "A token is deleted with the person's `principals` row"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_a_token_is_deleted_with_its_principal_and_stops_working`
  `server/tests/test_agent_api.py::test_disposing_of_a_principal_takes_their_tokens_with_it`
  `tests/test_dispose.py::a disposed person's agent tokens go with them`
  `server/tests/test_agent_mutations.py::test_each_guard_is_noticed_when_broken`

### C-108 A revoked token stops working on its next call

- **Claim:** The owner's revocation through the API, and the operator's through
  `make agent-tokens`, end a token on its next call; a person can revoke only their
  own, and the operator's script ends exactly what it is told to and only live
  tokens.
- **Asserted in:** `docs/agent-api.md` — "A revoked token stops working on its next call."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_you_can_list_and_revoke_only_your_own`
  `tests/test_agent_tokens.py::revoke --token ends that token`
  `tests/test_agent_tokens.py::revoke --user ends a person's live tokens`
  `tests/test_agent_tokens.py::revoke --everyone ends every live token`
  `tests/test_stack.py::the owner can revoke it, and it stops working`
  `server/tests/test_agent_mutations.py::test_each_guard_is_noticed_when_broken`

### C-109 Every agent call is in the read trail, marked as agent access

- **Claim:** An answered call writes a row to `access_event`, in the same
  transaction as the answer, marked `via = 'agent'` with the token's public id and
  never its secret. A refusal of a token that exists, or of a project the person
  cannot see, writes one with the reason. A malformed or unknown token, and a call
  turned away by a rate limit, write no row and are counted in the security log.
- **Asserted in:** `docs/agent-api.md` — "Not every call is a row, because the read trail is append-only and an unauthenticated caller must not be able to grow it"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_every_agent_call_is_in_the_read_trail_marked_as_agent_access`
  `server/tests/test_agent_api.py::test_the_portfolio_entry_lists_the_ids_that_were_returned`
  `server/tests/test_agent_api.py::test_only_a_token_that_exists_leaves_a_trail_row_when_refused`
  `server/tests/test_agent_api.py::test_agent_calls_also_reach_the_security_log_without_the_secret`
  `server/tests/test_access_audit.py::test_the_check_constraint_and_the_enum_agree`
  `tests/test_stack.py::each call is in the real read trail, marked as agent access`
  `server/tests/test_agent_mutations.py::test_each_guard_is_noticed_when_broken`

### C-110 An agent token has its own, lower rate limit

- **Claim:** Each token is limited separately and lower than a session is, and
  only a call whose token verified spends it, so nobody can spend another token's
  allowance by naming it. A failed call is counted against its source, which is the
  socket peer (or the proxy-reported address only inside `TRUSTED_PROXY_CIDR`),
  never a header a client can rotate.
- **Asserted in:** `docs/agent-api.md` — "A working token** may make 60 calls per 60 seconds (`AGENT_RATE_LIMIT_MAX_REQUESTS`), lower than the limit a person at the dashboard has (240)."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_an_agent_token_has_its_own_lower_limit`
  `server/tests/test_agent_api.py::test_the_source_is_the_peer_and_not_a_header_a_client_chooses`
  `server/tests/test_agent_api.py::test_the_default_agent_limit_is_lower_than_the_default_session_limit`
  `server/tests/test_agent_mutations.py::test_each_guard_is_noticed_when_broken`

### C-111 The agent API has no write route

- **Claim:** The agent API is three GET routes. A write verb is a 405 from the API
  and a 404 from the proxy, and no route under the prefix changes a record.
- **Asserted in:** `docs/agent-api.md` — "Read-only. Three `GET` routes under `/api/agent/`, and nothing that writes."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_the_agent_routes_are_read_only`
  `tests/test_proxy_identity.py::is refused by the proxy`
  `tests/test_stack.py::a write verb on the agent route is refused by the proxy`
  `server/tests/test_agent_mutations.py::test_each_guard_is_noticed_when_broken`

### C-112 A flood of wrong tokens cannot grow the trail, burn the server or lock out a working one

- **Claim:** The token is checked before anything is limited. A bad token writes no
  read-trail row unless it names a token that exists, and then rows are bounded per
  token id across all sources and overall, by kind (wrong secret, right secret on a
  stopped token, project not visible), so a flood of one kind cannot starve another.
  A source that fails too often, and every source once all failures pass a global
  budget, is answered 429 with nothing written. The failure tally is bounded and
  O(1) per failure, and the flood leaves one summary line a window. A working token
  is never counted against a source or a budget and never refused for them, and a
  person's tokens share one allowance.
- **Asserted in:** `docs/agent-api.md` — "A working token is never counted against a source or a budget"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_a_flood_of_bad_tokens_writes_nothing_and_never_blocks_a_real_token`
  `server/tests/test_agent_api.py::test_nobody_can_spend_another_tokens_allowance_by_naming_it`
  `server/tests/test_agent_api.py::test_the_per_token_limit_counts_only_requests_that_verified`
  `server/tests/test_agent_api.py::test_wrong_secret_rows_are_bounded_per_token_across_every_source`
  `server/tests/test_agent_api.py::test_wrong_secret_rows_are_bounded_overall`
  `server/tests/test_agent_api.py::test_a_flood_of_wrong_secrets_cannot_starve_the_holders_own_refusals`
  `server/tests/test_agent_api.py::test_a_valid_tokens_unknown_refs_write_a_bounded_number_of_rows`
  `server/tests/test_agent_api.py::test_a_persons_tokens_share_one_allowance`
  `server/tests/test_agent_api.py::test_failures_past_the_global_budget_are_refused_without_accounting`
  `server/tests/test_agent_api.py::test_the_summary_is_written_by_the_app_without_another_failure`
  `server/tests/test_agent_api.py::test_the_summary_is_written_when_the_app_shuts_down`
  `server/tests/test_agent_limits.py::test_a_hundred_thousand_sources_cost_a_bounded_time_and_memory`
  `server/tests/test_agent_limits.py::test_an_active_attackers_bucket_survives_the_evictions_it_causes`
  `server/tests/test_agent_limits.py::test_a_flood_of_sources_is_one_log_line_not_one_per_source`
  `server/tests/test_agent_limits.py::test_past_the_global_budget_nothing_is_accounted_per_source`
  `server/tests/test_agent_limits.py::test_the_limiter_sweeps_the_keys_a_window_leaves_behind`
  `server/tests/test_agent_mutations.py::test_each_guard_is_noticed_when_broken`

### C-113 A key a writer chose reaches an agent only if the build's definitions have it

- **Claim:** An item id, a checkpoint id, a supplement id, a status and a decision
  are returned only if they are words of the framework definitions the server's
  build carries, for the framework the record follows; a project's own id is never
  returned. A writer's sentence in any key position does not reach an agent.
- **Asserted in:** `docs/agent-api.md` — "A key a writer chose (an item id, a checkpoint id, a supplement id) is returned only if it is a word of the framework definitions the server was built with"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_a_key_a_writer_chose_never_reaches_an_agent`
  `server/tests/test_agent_api.py::test_a_builds_own_words_pass_and_the_published_ones_do_not_cross_over`
  `server/tests/test_agent_api.py::test_with_no_vocabulary_loaded_an_agent_is_shown_no_framework_words`
  `server/tests/test_agent_api.py::test_the_vocabulary_is_the_framework_definitions`
  `server/tests/test_agent_vocabulary.py::test_loading_replaces_the_table_wholesale`
  `server/tests/test_agent_vocabulary.py::test_the_migrate_job_loads_the_words_from_the_manifest`
  `server/tests/test_agent_vocabulary.py::test_the_server_reads_the_words_strictly`
  `server/tests/test_agent_mutations.py::test_each_guard_is_noticed_when_broken`

### C-114 The token is read from one header, and this stack tries not to log it

- **Claim:** The token is read from the Authorization header and nowhere else: a
  token in a query parameter, a cookie or another header is refused. The API's
  access log drops the query string of a request whose decoded path is under
  `/api/agent/`; the proxy's log drops the query string of any request whose target
  is, or might be, an agent route (the word agent in any case, a percent-encoded
  character before the query, an absolute-form target, an empty or dot path
  segment) and the values of five token-like request headers.
- **Asserted in:** `docs/agent-api.md` — "In the `Authorization` header and nowhere else: one in a query parameter, a cookie or another header is refused."
- **Asserted in:** `docs/agent-api.md` — "The API's access log drops the query string of a request whose decoded path is under `/api/agent/`."
- **Status:** partial
- **Enforced by:**
  `server/tests/test_agent_api.py::test_the_token_comes_from_the_authorization_header_and_nowhere_else`
  `server/tests/test_agent_api.py::test_a_token_sent_in_a_url_is_refused_and_not_logged_by_the_server`
  `server/tests/test_agent_api.py::test_the_access_log_does_not_keep_a_query_on_an_agent_route`
  `tests/test_proxy_identity.py::the proxy's log keeps no query of`
  `tests/test_proxy_identity.py::the proxy's log keeps no token-like request header`
  `tests/test_proxy_agent_mutations.py`
- **Gap:** A token in a URL path is logged by the API and the proxy, a request
  header with a name not on the proxy's fixed list is logged by the proxy, and a
  front door, load balancer or client in front of this stack may log a URL or a
  header (#164). The page says never to send a token anywhere but the Authorization
  header.

### C-115 A client cannot choose the address it is limited by

- **Claim:** The source of a failed agent call is the socket peer, or the address
  the proxy reported when `TRUSTED_PROXY_CIDR` is set and the peer is inside it.
  A client that reaches the API directly and sends its own `X-Real-IP` or
  `X-Forwarded-For` is still one source. The source is always a parsed IP address or
  `unknown`, never text a client sent, and the image starts uvicorn with
  `--no-proxy-headers`, whose default would let a loopback peer set it.
- **Asserted in:** `docs/agent-api.md` — "The source** is the socket peer."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_the_source_is_the_peer_and_not_a_header_a_client_chooses`
  `server/tests/test_agent_api.py::test_the_proxys_address_is_believed_only_inside_the_trusted_range`
  `server/tests/test_agent_api.py::test_behind_a_trusted_proxy_each_client_is_its_own_source`
  `server/tests/test_agent_api.py::test_the_source_is_always_an_address_or_unknown`
  `server/tests/test_agent_api.py::test_uvicorn_is_started_without_proxy_headers_and_that_matters`
  `server/tests/test_agent_mutations.py::test_each_guard_is_noticed_when_broken`

### C-116 A weak secret for the opaque ids is refused at startup

- **Claim:** The server refuses to start on an `AGENT_ID_SECRET` shorter than 32
  characters, with fewer than 10 different ones, or made of one short pattern
  repeated, and the generator the docs give always passes. This is a filter for
  obvious mistakes and not a strength test, and the page says so.
- **Asserted in:** `docs/agent-api.md` — "The server refuses to start on one shorter than 32 characters"
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_a_weak_secret_stops_the_server_starting`
  `server/tests/test_agent_api.py::test_a_short_secret_stops_the_server_starting`

### C-117 A manifest with words no display word has is refused before anything changes

- **Claim:** The migrate job reads the framework words from the manifest with a shape
  and safety filter: it refuses a lone surrogate, a control, zero-width, bidirectional
  or private-use character, a word over 64 characters or with surrounding space,
  more than 5,000 words of a kind or 50,000 in all, and a repeated JSON key, before
  it changes anything. The manifest is trusted build output, and the page says the
  check is not a judgment of content.
- **Asserted in:** `docs/agent-api.md` — "A manifest that fails is refused before the job changes anything."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_vocabulary.py::test_a_word_a_display_word_could_not_be_is_refused`
  `server/tests/test_agent_vocabulary.py::test_a_word_with_spaces_is_a_display_word`
  `server/tests/test_agent_vocabulary.py::test_a_manifest_with_too_many_words_overall_is_refused`
  `server/tests/test_agent_vocabulary.py::test_a_repeated_json_key_is_refused_and_not_silently_resolved`
  `server/tests/test_agent_vocabulary.py::test_a_manifest_that_cannot_be_loaded_stops_the_job_cleanly`
  `server/tests/test_agent_vocabulary.py::test_the_api_role_may_only_read_the_vocabulary`
  `server/tests/test_agent_mutations.py::test_each_guard_is_noticed_when_broken`

### C-119 The MCP service is off unless its profile is asked for

- **Claim:** A plain `docker compose up` starts neither the MCP service nor its
  gate; only `--profile agent-mcp` does. With the profile off, the proxy's `/mcp`
  answers `502` and nothing it reaches is the main API.
- **Asserted in:** `docs/mcp.md` — "The MCP server is **off by default**."
- **Asserted in:** `docs/mcp.md` — "A plain `docker compose up -d` does not start it"
- **Asserted in:** `compose.yaml` — "OFF BY DEFAULT: both services below are in the"
- **Asserted in:** `proxy/Caddyfile` — "OFF BY DEFAULT. The upstream is the `mcp-gate` service"
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::the mcp service without its profile (on by default)`
  `tests/test_compose_isolation.py::the gate without its profile`
  `tests/test_compose_isolation.py::a new service with no profile`
  `tests/test_compose_isolation.py::compose itself: a bare`
  `tests/test_stack_mcp.py::no mcp or mcp-gate container is running`
  `tests/test_stack_mcp.py::the proxy's /mcp is a 502 with nothing behind it`
  `tests/test_proxy_identity.py::mcp route: with {label}, POST /mcp is a 502`

### C-120 The MCP service holds no credential of its own

- **Claim:** The MCP service is given no token, secret, password or key: none in
  its environment, no env file, no way to the database, and no setting that could
  hold a token. The API's shared secret is the gate's, never the service's.
- **Asserted in:** `docs/mcp.md` — "It stores no token, and has none of its own."
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::given to mcp`
  `tests/test_compose_isolation.py::mcp with an env file`
  `tests/test_compose_isolation.py::the gate without the shared secret`
  `mcp/tests/test_mcp_service.py::test_nothing_in_the_settings_can_hold_a_token`
  `mcp/tests/test_mcp_service.py::test_a_token_is_not_kept_after_its_request`
  `mcp/tests/test_mcp_mutations.py::test_each_guard_is_noticed_when_broken`

### C-121 A token is forwarded for one request and is in no log, error or result

- **Claim:** Each request's own bearer token is forwarded, for that request only, to
  the agent API's routes. It is stored nowhere and is in no log line of the MCP
  service, in no error message and in no tool result, and a redirect is never
  followed with it.
- **Asserted in:** `docs/mcp.md` — "It reads the `Authorization` header of each request, forwards it for that request, validates what comes back, and answers."
- **Asserted in:** `docs/mcp.md` — "Never a header, a query string or a body, and so never a token."
- **Status:** enforced
- **Enforced by:**
  `mcp/tests/test_mcp_service.py::test_each_tool_returns_its_documented_result_and_forwards_the_callers_token`
  `mcp/tests/test_mcp_service.py::test_only_the_bearer_is_forwarded_no_identity_and_no_other_credential`
  `mcp/tests/test_mcp_service.py::test_a_redirect_is_not_followed_so_the_token_goes_nowhere_else`
  `mcp/tests/test_mcp_service.py::test_a_token_the_api_rejects_is_one_message_and_is_never_echoed`
  `mcp/tests/test_mcp_service.py::test_the_token_is_in_no_log_line_on_any_path`
  `mcp/tests/test_mcp_service.py::test_a_token_is_not_kept_after_its_request`
  `mcp/tests/test_mcp_process.py::test_what_the_process_writes_holds_no_token`
  `tests/test_stack_mcp.py::the token's secret is in no log of the proxy, gate, service or API`
  `mcp/tests/test_mcp_mutations.py::test_each_guard_is_noticed_when_broken`

### C-122 The MCP tools are exactly three read-only ones

- **Claim:** The service registers `whoami`, `list_portfolio` and `get_project` and
  nothing else: no write tool, no resource, no prompt and no tool that takes a URL
  or a path. Each tool is one call to one of the agent API's three `GET` routes, and
  no tool can reach another route.
- **Asserted in:** `docs/mcp.md` — "There is no write tool, no resource, no prompt, and no tool that takes a URL or a path."
- **Status:** enforced
- **Enforced by:**
  `mcp/tests/test_mcp_service.py::test_only_the_three_allowlisted_tools_are_registered`
  `mcp/tests/test_mcp_service.py::test_no_resource_template_or_prompt_is_registered`
  `mcp/tests/test_mcp_service.py::test_the_protocol_lists_exactly_the_allowlist`
  `mcp/tests/test_mcp_service.py::test_every_tool_is_read_only_typed_and_says_how_to_read_it`
  `mcp/tests/test_mcp_service.py::test_the_upstream_routes_are_the_three_get_routes_and_no_others`
  `mcp/tests/test_mcp_service.py::test_a_call_asks_for_a_reference_it_can_name_and_nothing_else`
  `mcp/tests/test_mcp_service.py::test_no_tool_can_reach_any_route_but_the_three`
  `mcp/tests/test_mcp_contract.py::test_the_routes_are_the_apis_three_get_routes`
  `mcp/tests/test_mcp_mutations.py::test_each_guard_is_noticed_when_broken`
  `tests/test_stack_mcp.py::tools/list is exactly the three read-only tools`

### C-123 No free text, name or email reaches a model through the MCP server

- **Claim:** Text planted in a stored record, in every field and as an item, project
  or checkpoint key, is in no tool result and no error: not a name, an email, a
  sentence of instructions or markup. What is returned is the framework's own words,
  opaque ids and dates.
- **Asserted in:** `docs/mcp.md` — "**No free text is returned in this version**"
- **Status:** enforced
- **Enforced by:**
  `mcp/tests/test_mcp_integration.py::test_hostile_text_planted_in_a_stored_record_never_reaches_a_model`
  `mcp/tests/test_mcp_service.py::test_a_value_that_is_not_a_vocabulary_word_never_reaches_a_model`
  `tests/test_stack_mcp.py::hostile text planted in the record is in no answer`
  `server/tests/test_agent_api.py::test_nothing_hostile_planted_anywhere_reaches_an_agent`

### C-124 The service checks every answer's shape a second time, and says what that cannot do

- **Claim:** Every string the service passes on must be shaped like a vocabulary word
  (up to four plain words of at most 48 characters), an opaque id or a date, and an
  unknown field is refused, so a sentence, an address or markup makes the whole
  answer refused. A shape cannot tell a one-word name from a status, so this is a
  second wall behind the API's list of the build's own words, and the page says so.
- **Asserted in:** `docs/mcp.md` — "A sentence, an address or markup in any field makes the whole answer refused."
- **Status:** partial
- **Enforced by:**
  `mcp/tests/test_mcp_service.py::test_a_value_that_is_not_a_vocabulary_word_never_reaches_a_model`
  `mcp/tests/test_mcp_service.py::test_an_answer_that_is_not_the_documented_shape_is_refused_whole`
  `mcp/tests/test_mcp_service.py::test_a_name_that_is_shaped_like_a_word_is_the_apis_to_stop`
  `mcp/tests/test_mcp_contract.py::test_the_api_and_this_service_agree_on_what_a_vocabulary_word_looks_like`
- **Gap:** a name that is one plain word passes the shape check by design; the API's
  vocabulary allowlist (C-113) is the wall that stops it. A custom framework whose
  words are longer or have other punctuation would be refused whole (D-91 default
  (d)). (#164)

### C-125 A failure is a fixed message, never the token or the upstream's body

- **Claim:** Every failure the service reports is one of a few fixed messages. The
  token and the upstream's response body are in none of them; a 422's message is cut
  to plain characters, and an unexpected failure inside the service says only that it
  could not complete.
- **Asserted in:** `docs/mcp.md` — "A failure is a tool error (`isError` is `true`) with one of a few **fixed** messages."
- **Status:** enforced
- **Enforced by:**
  `mcp/tests/test_mcp_service.py::test_a_failure_is_a_fixed_message_and_never_the_upstream_body`
  `mcp/tests/test_mcp_service.py::test_a_token_the_api_rejects_is_one_message_and_is_never_echoed`
  `mcp/tests/test_mcp_service.py::test_a_422_carries_the_apis_message_cut_to_plain_text`
  `mcp/tests/test_mcp_service.py::test_a_429_says_when_to_retry`
  `mcp/tests/test_mcp_service.py::test_an_unexpected_failure_inside_the_service_is_one_plain_message`
  `mcp/tests/test_mcp_integration.py::test_a_token_that_is_wrong_in_any_way_gets_the_one_message`
  `mcp/tests/test_mcp_docs.py::test_the_error_table_is_every_message_the_service_can_say`

### C-126 The Host and Origin are validated, and no CORS header is sent

- **Claim:** A request whose `Host` is not on the operator's list is refused, so is
  one carrying an `Origin` that is not listed (the list is empty by default), both
  before the token is looked at, and no CORS header is ever sent. The service will
  not start without a host list.
- **Asserted in:** `docs/mcp.md` — "a request whose `Host` header is not on the list is refused with a `421`."
- **Asserted in:** `docs/mcp.md` — "No CORS header is ever sent."
- **Status:** enforced
- **Enforced by:**
  `mcp/tests/test_mcp_service.py::test_a_request_for_another_host_is_refused`
  `mcp/tests/test_mcp_service.py::test_a_browser_origin_that_is_not_listed_is_refused_even_with_a_token`
  `mcp/tests/test_mcp_service.py::test_with_no_origins_configured_no_browser_origin_gets_through`
  `mcp/tests/test_mcp_service.py::test_origin_is_checked_before_the_token`
  `mcp/tests/test_mcp_service.py::test_no_cors_headers_are_ever_sent_and_a_preflight_is_not_served`
  `mcp/tests/test_mcp_process.py::test_it_refuses_to_start_with_no_allowed_host`
  `tests/test_stack_mcp.py::a foreign browser Origin is refused`
  `tests/test_stack_mcp.py::a foreign Host is refused`

### C-127 The proxy's /mcp route skips sign-on, strips every identity header and sets none

- **Claim:** `/mcp` bypasses single sign-on, deletes every header that could be read
  as an identity (and `X-Client-Address` and `X-Proxy-Secret`) and sets none, even
  with a front door configured, forwards only `POST`, `GET` and `DELETE` on exactly
  `/mcp`, caps the body, refuses everything else under the prefix with a `404`, and
  never reaches the main API.
- **Asserted in:** `docs/mcp.md` — "deletes every identity header and sets none, forwards only the transport's three methods on exactly `/mcp`, and answers anything else under the prefix with a `404`."
- **Asserted in:** `proxy/Caddyfile` — "this block never SETS an identity and STRIPS"
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::mcp route: forwarded with no sign-on`
  `tests/test_proxy_identity.py::the proxy sets no identity on the mcp route, with a front door configured`
  `tests/test_proxy_identity.py::mcp route: the service saw exactly the three allowed requests`
  `tests/test_proxy_identity.py::mcp route: nothing reached the main API through it`
  `tests/test_proxy_identity.py::mcp route: a body over the cap is refused`
  `tests/test_proxy_mcp_mutations.py`

### C-128 The MCP service can reach the gate and nothing else

- **Claim:** `mcp` is on the internal `agent` network with `mcp-gate` and no other
  network, publishes no port, and from inside it the API, the proxy and the database
  cannot be reached.
- **Asserted in:** `docs/mcp.md` — "so it cannot reach the API, the database, or the proxy's single sign-on listener."
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::mcp on the edge network`
  `tests/test_compose_isolation.py::the proxy on the agent network`
  `tests/test_compose_isolation.py::the agent network made routable`
  `tests/test_compose_isolation.py::a stranger on the agent network`
  `tests/test_compose_isolation.py::a published port on mcp`
  `tests/test_stack_mcp.py::from inside mcp only the gate is reachable (not the API, proxy or database)`
  `tests/test_stack_mcp.py::mcp is on the agent network and nothing else`

### C-129 The gate serves only the three GET routes and the MCP path, and holds the API's secret

- **Claim:** `mcp-gate` forwards only the three agent `GET` routes to the API and
  only `/mcp` to the service, deletes every identity header and sets none, passes the
  caller's token untouched, sets the caller's address itself and the shared secret
  from its own environment, and refuses everything else.
- **Asserted in:** `proxy/Caddyfile.mcp-gate` — "This file has no sign-on, no identity, and sets no identity header"
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::gate: the answer is not cacheable`
  `tests/test_proxy_identity.py::gate: none of those reached the API`
  `tests/test_proxy_identity.py::gate: the service saw only the allowed requests on /mcp`
  `tests/test_proxy_identity.py::gate: no identity header and no secret reaches the service`
  `tests/test_proxy_identity.py::gate: the caller's address is the gate's own finding, not the client's claim`
  `tests/test_proxy_mcp_mutations.py`

### C-130 The MCP image is non-root, locked and pinned, and its containers are hardened

- **Claim:** The image installs only from a hash-verified lock with no pip, from
  digest-pinned bases, runs as a numeric non-root user with no login shell and a
  health check, is started directly and not through a shell, and its containers have
  a read-only root filesystem, no capability, no new privileges and no published port.
- **Asserted in:** `mcp/Dockerfile` — "Non-root, no login shell, no home directory."
- **Asserted in:** `compose.yaml` — "SECURITY PROPERTY of this service: it can reach mcp-gate and nothing else."
- **Status:** enforced
- **Enforced by:**
  `tests/test_compose_isolation.py::mcp with a writable root filesystem`
  `tests/test_compose_isolation.py::mcp keeping its capabilities`
  `tests/test_compose_isolation.py::the gate running as root`
  `tests/test_compose_isolation.py::the mcp image: the real Dockerfile passes`
  `tests/test_supply_chain.py::the MCP image's bases are pinned`
  `tests/test_supply_chain.py::its user has no login shell`
  `tests/test_supply_chain.py::pip is not in the MCP runtime image`
  `tests/test_stack_mcp.py::mcp has a read-only root filesystem`

### C-131 Only an empty AGENT_ID_SECRET turns the agent API off for everyone

- **Claim:** Turning the MCP service off does not stop a person calling the agent
  API with their own program; the API is off only while `AGENT_ID_SECRET` is empty,
  and the MCP service then says so.
- **Asserted in:** `docs/mcp.md` — "setting `AGENT_ID_SECRET` empty does, and it is the only switch for that."
- **Status:** enforced
- **Enforced by:**
  `server/tests/test_agent_api.py::test_the_agent_api_is_off_without_its_secret`
  `mcp/tests/test_mcp_integration.py::test_it_says_so_when_the_agent_api_is_off`

### C-132 The MCP service is stateless and two callers never see each other's data

- **Claim:** The service keeps no session and hands out no session id; each request
  stands alone with its own token, and interleaved callers with different tokens each
  get exactly their own answers.
- **Asserted in:** `docs/mcp.md` — "Stateless. Each request carries its own token and stands alone."
- **Status:** enforced
- **Enforced by:**
  `mcp/tests/test_mcp_service.py::test_the_service_keeps_no_session`
  `mcp/tests/test_mcp_service.py::test_interleaved_callers_with_different_tokens_never_see_each_others_data`
  `mcp/tests/test_mcp_integration.py::test_two_people_calling_at_once_never_see_each_others_projects`
  `mcp/tests/test_mcp_docs.py::test_the_documented_curl_commands_run_and_answer_what_the_page_shows`

### C-133 The MCP service bounds its body, its time and its concurrency

- **Claim:** A request body over the limit is refused, a call to the API that takes
  longer than the timeout fails, and calls past the in-flight bound are refused
  rather than queued; the proxy and the gate cap the body too.
- **Asserted in:** `docs/mcp.md` — "Calls at once | 16 (`MCP_MAX_IN_FLIGHT`); more are refused, not queued"
- **Status:** enforced
- **Enforced by:**
  `mcp/tests/test_mcp_service.py::test_a_body_over_the_limit_is_refused`
  `mcp/tests/test_mcp_service.py::test_a_slow_governance_server_times_out`
  `mcp/tests/test_mcp_service.py::test_concurrency_is_bounded_and_the_overflow_is_refused`
  `tests/test_stack_mcp.py::a body over the limit is refused`
  `tests/test_proxy_identity.py::mcp route: a body over the cap is refused`

### C-134 The proxy and the gate keep a token out of their logs

- **Claim:** The proxy's log redacts the query string of `/mcp` and the
  `Authorization` header; the gate's log redacts the query string of every request.
- **Asserted in:** `docs/mcp.md` — "The proxy's log redacts a query string on `/mcp` and the `Authorization` header."
- **Status:** enforced
- **Enforced by:**
  `tests/test_proxy_identity.py::the proxy's log keeps no query of /mcp`
  `tests/test_proxy_identity.py::the proxy's log keeps no bearer token`
  `tests/test_proxy_identity.py::gate: its log keeps no`
  `tests/test_proxy_mcp_mutations.py`
