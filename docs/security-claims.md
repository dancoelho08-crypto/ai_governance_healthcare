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
- **Asserted in:** `server/app/main.py` — "Per-key request accounting over a
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
  GFM renderer also links a bare address a person typed, including one with
  credentials (`https://user:pass@host/`), and the export does not stop it: the link's
  text is its address, and the audit reports it apart from a link with other text.
  A claim about every renderer cannot be proven with one, so this stays partial.
- **Enforced by:**
  `tests/test_markdown_render.py::every payload, sample and language renders as text in every configuration`
  `tests/test_markdown_render.py::the example build's poisoned definition and records render as text`
  `tests/test_markdown_render.py::every weakened export is rejected`
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
