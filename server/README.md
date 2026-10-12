# CHAI governance API

The shared-storage backend for the dashboard. It implements the six-method
store contract the browser uses, plus the operations only a server can honor,
over REST and Server-Sent Events, on PostgreSQL.

For running this behind Google Cloud IAP, an AWS ALB or Azure Easy Auth, see
[`docs/deploy.md`](../docs/deploy.md). For the Compose stack, see
[`docs/self-hosting.md`](../docs/self-hosting.md).

## The contract

| Store method | HTTP |
|---|---|
| `subscribeAll(cb, err)` | `GET /api/projects` + `GET /api/events` |
| `create(id, data)` | `POST /api/projects/{id}`: 409 if it exists |
| `update(id, patch)` | `PATCH /api/projects/{id}`: deep merge |
| `remove(id)` | `DELETE /api/projects/{id}`: removes the project and its live log, keeps the version history, writes a tombstone |
| `log(id, entry)` | `POST /api/projects/{id}/log` |
| `subscribeLog(id, cb)` | `GET /api/projects/{id}/log` + `GET /api/events` |

Only the server store has these, and the dashboard offers each only when the
store does:

| Store method | HTTP |
|---|---|
| `purgeVersions(id)` | `DELETE /api/projects/{id}/versions`: destroys the content of every revision **and** of the audit log. Owners only; irreversible |
| `getHold(id)`, `setHold(id, action, reason)` | `GET` and `POST /api/projects/{id}/hold`: a litigation hold stops disposal. Owners only; a reason is required |
| `recordExport(id, format)` | `POST /api/projects/{id}/exports`, and `POST /api/exports` for the portfolio CSV: the dashboard reports an export it built, so it joins the read trail |

The rest of the API:

| | |
|---|---|
| `GET /api/health` | Unauthenticated. Status, version, `db_role`, `events`, and the session settings the browser needs |
| `GET /api/me` | Who the proxy says you are |
| `GET /api/principals?ids=a,b,c` | Names and emails for identity ids, for people the caller can already see (below) |
| `GET /api/projects/{id}/versions`, `.../versions/{rev}` | The revision list, and one revision, for anyone who can read the project. A purged revision answers empty with `purged: true` |
| `GET /api/events` | One event per change, for as long as the stream is held |
| `GET /api/agent/me`, `/api/agent/portfolio`, `/api/agent/projects/{ref}` | The read-only agent API: stored statuses, decisions and dates, people and projects as opaque ids, answered to a per-user bearer token and no other credential. Off until `AGENT_ID_SECRET` is set ([The agent API](../docs/agent-api.md)). An optional, separate [MCP service](../mcp/README.md) wraps these three routes for chatbots |
| `POST`, `GET /api/agent-tokens`, `DELETE /api/agent-tokens/{id}` | Mint, list and revoke your own agent tokens, with the session, never with a token |

Every read of a record is also written to `access_event`, in the transaction of
the read. See [the read trail](../docs/deploy.md#the-read-trail).

The two `subscribe*` methods are a fetch plus a stream: fetch once, hold
`/api/events` open, refetch what an event says changed. Events carry an id and
never a document, because `NOTIFY` caps its payload at 8000 bytes and a project
can exceed that.

## Three decisions worth knowing

**The deep merge runs in Python, inside a transaction, behind
`SELECT ... FOR UPDATE`.** The row lock is what makes two concurrent PATCHes to
different fields safe: the second blocks at the `SELECT` until the first
commits, then merges onto the committed document. A recursive `jsonb` merge in
PL/pgSQL would be equally atomic and was rejected for a different reason — it
would be a second implementation of a merge rule the browser already defines in
`app/js/00-core/00-util.js`, and two implementations drift. `tests/test_merge.py`
runs the real JavaScript under node and demands identical output.

PostgreSQL's `||` operator is not an option at all: it merges only the top
level, so `{"items": {"s4-2": {...}}}` would discard every other key under
`items`.

**The audit log is append-only.** No route updates or deletes an entry, and a
trigger refuses `UPDATE` on the table (`migrations/001_init.sql`), with exactly
one exception: the redaction a purge performs (`migrations/005_disposal.sql`),
which the trigger verifies by comparing the result with `project_log_redacted()`.
Deleting a project removes its live log by cascade. `at` and
`by` are overwritten on write with the server clock and the proxy identity,
even though the browser sends both — a log whose author is a field the client
sets is not a log.

**Identity comes from a proxy header and nothing else, on every route but the
agent API's.** No cookie, no bearer token, no query parameter. Which header is
configurable, because each cloud sends a different one. The three read-only
routes under `/api/agent/` are the one exception: they answer to a per-user
bearer token and ignore the identity header ([the agent API](../docs/agent-api.md)).

## The one hard requirement

**This service must be unreachable except through the proxy.** It trusts a
request header, and a header is trivially forged:

```bash
curl -H 'X-Forwarded-Email: cmo@hospital.org' https://api.example.org/api/me
```

If that can reach the container from anywhere but the proxy, anyone can be
anyone — including signing off a checkpoint in a colleague's name. Network
isolation is the security boundary; `docs/deploy.md` has the per-cloud steps
and a `make check-isolation` that asserts them.

Two optional second locks, both off by default and neither a substitute:
`TRUSTED_PROXY_CIDR` rejects a request whose TCP peer is outside the given
ranges, and `PROXY_SHARED_SECRET` rejects one that does not carry a secret only
the proxy knows.

This is why the container runs uvicorn with `--no-proxy-headers` (uvicorn's default
is to trust `X-Forwarded-For` from a loopback peer): the headers would rewrite the
peer address from something the client controls, and the CIDR check, and the agent
API's per-source limit, would be checking the attacker's own claim.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — | `postgresql://…`; `postgres://` and `postgresql+asyncpg://` are accepted too. Wins over the `POSTGRES_*` variables. **Percent-encode the password** (`/ @ : ? #` end the URL early); a broken one fails at startup and says so. |
| `POSTGRES_PASSWORD`, `POSTGRES_USER`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB` | —, `chai`, `localhost`, `5432`, `chai` | Used when `DATABASE_URL` is unset. The API builds the URL and encodes the password, so **any password works**. `compose.yaml` uses these. One of the two is required. |
| `PORT` / `API_PORT` | `8000` | Port to bind. Cloud Run sets `PORT`; `compose.yaml` sets `API_PORT`. |
| `IDENTITY_MODE` | `proxy` | Preset: `proxy`, `iap`, `alb`, `easyauth`. |
| `IDENTITY_HEADER` | `X-Forwarded-Email` | The header carrying identity. Overrides the preset. Alias: `AUTH_HEADER_EMAIL`. |
| `IDENTITY_NAME_HEADER` | `X-Forwarded-User` | Display name. Alias: `AUTH_HEADER_NAME`. |
| `IDENTITY_ID_HEADER` | — | Stable user id, if the proxy sends one. Alias: `AUTH_HEADER_ID`. |
| `IDENTITY_STRIP_PREFIX` | — | Removed from the value. `iap` sets `accounts.google.com:`. |
| `IDENTITY_HEADER_FORMAT` | per preset | `plain`, or `jwt` to read claims out of a signed assertion. |
| `IDENTITY_AUDIENCE` | — | In `jwt` mode, require this `aud` claim or `signer` header field. |
| `REQUIRE_IDENTITY` | `true` | Leave it on. `false` serves unidentified requests as `anonymous`. |
| `TRUSTED_PROXY_CIDR` | — | Comma-separated CIDRs the TCP peer must fall inside. |
| `PROXY_SHARED_SECRET` | — | Require `X-Proxy-Secret` to match. |
| `DEV_INSECURE_AUTH` | `false` | **Dev only.** See below. |
| `CORS_ORIGINS` | — | Off. Explicit list only; the app is same-origin with the API. |
| `SSE_MAX_LIFETIME_SECONDS` | `900` | Longest an event stream stays open before the server ends it and the browser reconnects through the front door. `0` is no limit. |
| `IDLE_LOCK_MINUTES` | `0` | Minutes of inactivity before the dashboard locks. `0` is off. Sent to the browser in `/api/health`. |
| `SIGN_OUT_URL` | — | Where the front door ends a session; an `https` URL or a path on this origin. Shown as a "Sign out" link. |
| `AGENT_ID_SECRET` | — | Turns the agent API on: at least 32 random characters, keying the opaque ids it shows for people and projects. Empty, no token can be minted and `/api/agent/` answers 404. See [the agent API](../docs/agent-api.md). |
| `AGENT_RATE_LIMIT_MAX_REQUESTS` | `60` | Calls per agent token per rate-limit window, lower than `RATE_LIMIT_MAX_REQUESTS`. |
| `AGENT_FAILURE_RATE_LIMIT_MAX_REQUESTS` | `30` | Failed agent calls per source per window; the rest are answered 429 with nothing written. |
| `AGENT_GLOBAL_FAILURE_RATE_LIMIT_MAX_REQUESTS` | `600` | Failed agent calls all sources together may make per window before every failure is answered 429 with no per-source accounting. |
| `AGENT_USER_RATE_LIMIT_MAX_REQUESTS` | `120` | Agent calls per window all of one person's tokens share. |
| `AGENT_MAX_ACTIVE_TOKENS` | `5` | Live agent tokens one person may hold. |
| `RUN_MIGRATIONS` | `true` | Apply `migrations/*.sql` at boot, under an advisory lock. **Must be `false`** when the API serves as the restricted role (it cannot create tables); `python -m app.migrate` migrates instead. |
| `APP_DATABASE_URL` | — | The restricted role's connection string. Wins over the pieces below. |
| `APP_POSTGRES_USER` | `chai_app` | The restricted role's name. |
| `APP_POSTGRES_PASSWORD` | — | Its password. With this set the API serves as that role, and `DATABASE_URL`/`POSTGRES_PASSWORD` (the owner's) belong to `python -m app.migrate` only. See `app/roles.py` for exactly what the role may do. |
| `RETIREMENT_MANIFEST` | — | **Required by `python -m app.migrate`.** The build's `manifest.json`, from which it loads which checkpoint decisions retire a project (`app/retirement.py`, D-76). Missing or malformed fails the job. With `RUN_MIGRATIONS=true` the API syncs from it too, with the same refusal; unset there, the API migrates without syncing, logs a warning, and `/api/health` reports `retirement_rules.synced: false` for as long as that API runs, even if an earlier sync recorded the rules (`synced` is otherwise true when the latest change of the rules came from a manifest). |
| `RETIREMENT_RULES_ACK` | — | The acknowledgment of one change of the retirement rules, which the job prints when a manifest would add or drop a rule or change the primary; without it, the job refuses (exit 3). Its format is `transition_ack()` in [`app/retirement.py`](app/retirement.py), whose docstring is the definition: SHA-256 of the canonical JSON of the database's identity (cluster system identifier, database OID, history table OID; migration 012), the id and time of the latest `retirement_rule_change` row, and every rule and the primary before and after. Spent once used; refused by another database and by a copy restored from a dump that creates the tables again (`make restore`). A copy of the database's files (a snapshot, a base backup, a promoted replica) shares the identity, so it and its original accept each other's values, and a data-only restore into the existing tables keeps it, so a value spent since the dump is accepted again. |
| `EVENTS_CHANNEL` | `chai_events` | `LISTEN`/`NOTIFY` channel. |
| `LOG_LEVEL` | `info` | The application log's level. Security events are held at INFO whatever this says. |
| `LOG_FORMAT` | `json` | `json`: one object per line, security events named and tagged `"stream": "security"`. `text`: the human-readable line. |

### Per cloud

| | `IDENTITY_MODE` | Header it reads |
|---|---|---|
| Google Cloud IAP | `iap` | `X-Goog-Authenticated-User-Email` (prefix stripped) |
| AWS ALB (`authenticate-oidc`) | `alb` | `x-amzn-oidc-data`, claims read out of the JWT |
| Azure Easy Auth | `easyauth` | `X-MS-CLIENT-PRINCIPAL-NAME` |
| oauth2-proxy, nginx, Caddy | `proxy` | `X-Forwarded-Email` |

In `jwt` mode the signature is **not** verified. That is safe for exactly the
same reason plain-header mode is safe and no other: nothing but the proxy can
reach the port. Verifying it properly is the upgrade path — check
`x-amzn-oidc-data` against `https://public-keys.auth.elb.<region>.amazonaws.com/<kid>`
and require the `signer` to be your load balancer's ARN. `IDENTITY_AUDIENCE` catches
a token minted for a different service in the same account; without a signature
check it stops misconfiguration, not a determined forger.

## Who an id is

Access lists, sign-offs and log entries hold identity ids, which mean nothing to
a reviewer (an IAP numeric subject id, an ALB `sub`). The API records the name
and email the proxy asserts as people sign in (`principals`, throttled to one
write an hour per person unless the name changes) and `GET /api/principals?ids=`
returns them.

It answers **only for people the caller can already see**: themself, and anyone
named on a project the caller can read (its access lists, sign-offs, last editors
and log authors). Any other id is omitted, not refused, so the table cannot be
walked. At most 100 ids per request. Recording never fails a request.

## Text is data

Every value reaches SQL as a parameter. `tests/test_sql_injection.py` fails on
any call that passes anything but a constant string, except the two places that
run trusted DDL (the migration files and the role the API serves as, whose name
and password the server quotes with `format(%I, %L)`), and it round-trips hostile
text through every place the API takes text. PostgreSQL cannot store the NUL
character (U+0000), so a request containing one is refused with a 422 rather
than failing with a server error.

## Reading the whole audit history

`GET /api/projects/{id}/log` returns the newest page (60 by default, newest
first). It used to be the only page. Now:

- `?limit=N` asks for up to 500 entries.
- `X-Log-Total` is how many entries the project has in all, so a caller can say
  "newest 60 of 412" instead of presenting a window as the history.
- `X-Log-Next` is present only when there is more. Pass it as `?before=` to get
  the next page. It is opaque and safe in a URL; do not build one yourself.

```bash
# every entry, oldest last, for a regulator
url=/api/projects/sepsis-2026/log
while [ -n "$url" ]; do
  curl -si "https://host$url" -H "$AUTH" | tee page.txt | sed -n '/^\r$/,$p'
  next=$(sed -n 's/^[Xx]-[Ll]og-[Nn]ext: \(.*\)\r$/\1/p' page.txt)
  url=${next:+/api/projects/sepsis-2026/log?before=$next}
done
```

The dashboard's changelog shows the window it has and says so ("Showing the
newest 60 of 412 entries"), with a *Show older entries* button on the server
store that goes up to 500; every export carries the same sentence. Paging is
access-controlled exactly like the first page.

## Emergency access

`EMERGENCY_ACCESS_IDS` (comma-separated identity ids) names identities that
hold owner rights on every project, for a record whose only owner has left. Every
use is recorded in that project's own audit log as a system entry (`event:
access.breakglass`, never redacted by a purge) and as an `access.breakglass`
security event (see below); reads of the same project by the same person are one
entry per ten minutes, writes are never throttled. Off by default. See
`docs/deploy.md`, "Offboarding, and emergency access".

## Denied access is logged

A request from an authenticated user that is refused on a project they have no
right to produces one `access.denied` security event, with a stable name so an
alert can match it without parsing prose:

```text
(one line; wrapped here)
access.denied actor='ann@hospital.org' project='sepsis-2026'
    need=write held=reader status=403
```

`need` is what the route required (`read`, `write` or `own`), `held` is the role
the user actually has (`none` if they have none), and `status` is what the caller
was told: **404** when they could not even read the project (so its existence is
not confirmed to them) and **403** when they could read it but not do this. The
line carries the project id and never the document. A request for a project that
does not exist is not a denial and is not logged. A burst of these from one actor
is worth an alert; the per-cloud alert policy is where that lives.

## Retention and litigation holds

How long records are kept is decided (R-54) and stored in the one-row
`retention_policy` table, 6 years for a retired project's record and for the read
trail by default. Disposal is **not** something the API does. `dispose_due()`, in
`migrations/008_retention.sql` and `009_principal_disposal.sql`, is run by an
operator as the database owner (`make dispose APPLY=1`). In one transaction it
deletes the live record of each retired project past its period and leaves a
tombstone, purges its revisions, deletes read-trail rows past their period, and
removes staff names no retained record refers to; it records the run in
`disposal_run`. The API's role cannot execute it and has no `DELETE` on the read
trail, and the read trail's trigger refuses a `DELETE` of a row younger than the
period or belonging to a project under a hold.

What counts as retired is data, not SQL (`migrations/010_retirement_rules.sql`,
R-66): `retirement_rule` lists every (framework, checkpoint, decision) that
ends a project, and `retention_due()` matches a record against the rows of its own
framework (`meta.framework.id`; a record without one is CHAI's). `python -m
app.migrate` loads the rows of the frameworks the build's manifest lists, refusing
any change (an added or a removed rule, or a new primary) unless
`RETIREMENT_RULES_ACK` acknowledges exactly that change, leaves the rows of
frameworks it does not list, and records every change in the append-only
`retirement_rule_change`. The API's role may only read both. The API accepts a
new record's `meta.framework` only when it is exactly
`{"id": <the active primary>}`, and requires it while that primary is not CHAI;
it refuses a patch that would change the framework `record_framework()` reads
for the record, or set the stamp to anything but exactly that framework.

A hold is the one retention action the API performs: `POST /api/projects/{id}/hold`
adds a row to the append-only `retention_hold` table, and a project whose latest
row is a `place` is skipped by `dispose_due()`. Placing it writes `hold.placed`
to the security log and a system entry, without the reason, to the project's log.
Who may do this, and what an operator does, is in
[`docs/privacy.md`](../docs/privacy.md).

## Dev mode

`DEV_INSECURE_AUTH=1` authenticates every request as one fixed fake user and
ignores the identity header entirely, so the stack runs on a laptop with no
proxy. It announces itself three ways: a banner in the startup log, an
`X-Chai-Auth-Mode: DEV-INSECURE` header on every response, and `auth_mode` in
`GET /api/health`.

Never set it anywhere a real person's name could end up in an audit log.

## Running the tests

The pure tests — merge semantics, identity parsing — need nothing. The rest
need a real PostgreSQL, because what they test *is* the database's behavior: a
row lock serializing concurrent PATCHes, a unique constraint producing one 409,
a trigger refusing an `UPDATE`. A fake would test the fake.

```bash
docker run -d --name chai-test-db -p 55432:5432 \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=chai_test postgres:17-alpine

pip install -e '.[dev]'
TEST_DATABASE_URL=postgresql://postgres:test@localhost:55432/chai_test pytest -q
```

Without `TEST_DATABASE_URL` the database tests skip and say why.

## Layout

```text
app/
  main.py        app factory, lifespan, CORS off, errors, rate and size limits
  config.py      environment -> Settings, with the per-cloud presets
  auth.py        identity from the proxy header; the peer and secret checks
  access.py      roles (Level), the access checks, and the record of a denial
  accessaudit.py the read trail: what is recorded, and the export formats
  agent.py       the read-only agent API, its allowlisted responses, token routes
  agent_tokens.py agent tokens: mint, verify, revoke, and the opaque person and
  project ids
  agent_limits.py what bounds a flood of agent calls: failures, rows, the
  per-token limit
  ratelimit.py   the sliding-window limiter
  emergency.py   break-glass access, and its record in the project's own log
  db.py          asyncpg pool, DSN normalizing, migrations under a lock
  migrate.py     the one-shot migration job and the restricted role's grants
  roles.py       the database role the API serves as, and exactly what it may do
  merge.py       the deep merge, mirroring the browser's
  models.py      pydantic models for the envelope, not for the document
  routes.py      every endpoint in the contract
  events.py      LISTEN/NOTIFY -> SSE fan-out
  principals.py  identity ids -> names, only for people the caller can see
  signoff.py     checkpoint sign-offs, attributed to the authenticated caller
  retention.py   litigation hold actions, and who a disposal names
  securitylog.py the named security events, one JSON object per line
migrations/
  001_init.sql                 projects, project_log, the append-only trigger
  002_versions.sql             project_version: a copy on every save
  003_version_access.sql       history keeps its access list; the purge
  004_version_incarnation.sql  one history per incarnation of an id
  005_disposal.sql             the deletion tombstone; the purge redacts the log
  006_principals.sql           names and emails the proxy asserted
  007_access_event.sql         the read trail
  008_retention.sql            retention policy, holds, dispose_due()
  009_principal_disposal.sql   staff names no retained record refers to
  013_agent_tokens.sql         agent tokens, and the read trail marking agent access
  014_agent_vocabulary.sql     the framework words an agent may be shown
tests/
```

Nothing in the image refers to this directory by name, so it can be built from
`./server` or `./api` without edits.
