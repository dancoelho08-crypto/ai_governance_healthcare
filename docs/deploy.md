# Deploying with SSO on Google Cloud, AWS and Azure

This page describes how to run the dashboard and its API as a managed
container service on Google Cloud, AWS or Azure, with the sign-in handled
by the cloud's own front door rather than by the application.

**Governance metadata only.** Never enter patient-identifiable information, in
any storage mode, the self-hosted server included. The controls on this page
(access control, audit, backups, encryption at rest) protect the integrity of
the review record and the staff personal data in it. They are not a basis for
storing patient data, and nothing here makes the deployment suitable for it.

Where a section cites a HIPAA Security Rule standard (45 CFR Part 164), it
names the practice the control follows. The rule governs systems that hold
electronic protected health information (ePHI), and this one must not, so a
cited standard is not a legal requirement on this system. The controls follow
those standards anyway: they are what a hospital's security team already
measures against, and they protect the sign-off record and the staff data in it.

The application does not authenticate anybody. It reads an identity
header that a reverse proxy puts on every request and uses it for
`GET /api/me`, for audit-log attribution, and for checkpoint sign-offs.
That is a deliberate choice, and it buys a lot: no password handling, no
session store, no OIDC client library, and SSO that matches whatever the
hospital already uses. It also has exactly one hard requirement.

!!! danger "The front door is the entire security model"

    An identity header is only as trustworthy as the guarantee that no
    request can reach the container without passing through the proxy
    that sets it. If anyone can open a TCP connection to the container
    directly, they can send `X-Goog-Authenticated-User-Email:
    cmo@hospital.org` and the API will believe them.

    Every section below has a **Close the back door** subsection. Those
    steps are not hardening. They are the deployment.

## What you are deploying

### The container

One image serving both the static dashboard and the API described in
[Self-hosting](self-hosting.md). It listens on a single port, speaks
plain HTTP (TLS is terminated at the front door), and expects:

| Variable | Purpose |
|---|---|
| `PORT` | Port to bind. Set by the platform on all three clouds. |
| `APP_DATABASE_URL` | PostgreSQL connection string for the **restricted** role the API serves as. See [Two database roles](#two-database-roles). |
| `SSE_MAX_LIFETIME_SECONDS`, `IDLE_LOCK_MINUTES`, `SIGN_OUT_URL` | Optional session controls. See [Session lifetime and automatic logoff](#session-lifetime-and-automatic-logoff). |
| `LOG_FORMAT` | `json` (default) or `text`. See [Security events](#security-events-collecting-retaining-and-alerting). |
| `EMERGENCY_ACCESS_IDS` | Optional. Identity ids with owner rights on every project, every use audited. See [Offboarding, and emergency access](#offboarding-and-emergency-access). |
| `AGENT_ID_SECRET`, `AGENT_RATE_LIMIT_MAX_REQUESTS`, `AGENT_FAILURE_RATE_LIMIT_MAX_REQUESTS`, `AGENT_GLOBAL_FAILURE_RATE_LIMIT_MAX_REQUESTS`, `AGENT_USER_RATE_LIMIT_MAX_REQUESTS`, `AGENT_MAX_ACTIVE_TOKENS` | Optional. The read-only agent API is **off** until `AGENT_ID_SECRET` is set. See [The agent API](agent-api.md), which also says what to let through your front door. |
| `RUN_MIGRATIONS` | `false` when the API serves as a restricted role, which cannot create tables. A migration job runs instead. |
| `DATABASE_URL` | The **owner's** connection string, for the migration job only. A single-role deployment may put it here and omit the two above, which works and is reported as a weaker setup. |
| `IDENTITY_MODE` | `iap`, `alb` or `easyauth` — which header to read. |
| `IDENTITY_AUDIENCE` | Expected `aud` (GCP), **load balancer** ARN (AWS, not the listener's) or client ID (Azure). Read **only** when `IDENTITY_HEADER_FORMAT=jwt` — the API refuses to start otherwise. |

`GET /api/health` returns `{"status":"ok","version":"..."}` and must not
require authentication — every platform below health-checks it from
inside the load balancer, where no identity header exists. When the database
cannot be reached it answers **503** with `"status":"unavailable"`, so a probe
that reads only the status code takes the replica out of rotation instead of
reporting it healthy.

The body also carries `"events":"live"`. It reads `"local-only"` while the API
has no `LISTEN` session to PostgreSQL, so a change written on another replica
does not reach this one's open dashboards. That is degraded, not down, so the
status stays 200; the API keeps retrying, backing off to a minute. If it stays
`local-only` behind a transaction-pooling proxy such as PgBouncer, which cannot
hold a `LISTEN`, point the API at the database directly or run one replica.

### The database

All three clouds offer managed PostgreSQL, and all three should be
reached over a private network path with no public endpoint. The project
document is stored as a `jsonb` column; `PATCH` performs the recursive
merge described in [Self-hosting](self-hosting.md), in which objects
merge key by key at every level and arrays replace wholesale.

Rotate the database credential with the provider and update `DATABASE_URL`;
there is no `pgdata` volume here and no `db` service, so the
[rotation trap in the compose stack](self-hosting.md#rotating-the-database-password)
does not apply. Prefer the platform's identity-based connection — Cloud SQL IAM
auth, RDS IAM auth, Entra ID — over a password you have to rotate at all.

### Disk and growth

Three tables only ever grow, by design, and a full disk is the one failure this
system must not have: the database stops accepting writes, so the audit trail
stops recording.

| Table | What adds a row | Size of a row |
|---|---|---|
| `project_version` | every save of a project: a **complete copy** of the document, not a diff | the size of the document |
| `project_log` | every change entry, and every purge | a few hundred bytes |
| `access_event` | every list, read, export and stream attach (the read trail) | a few hundred bytes, plus the project ids a list returned |

None is trimmed automatically. A purge empties a revision's `doc` but keeps the
row (that is what makes it a tombstone), so a purge reclaims content and not
rows. `project_version` also survives its project's deletion, on purpose.

**How to estimate it.** Growth per year is about *revisions per year x document
size* for `project_version`, plus a row per read for `access_event`. The bundled
sample reviews are 1.4 to 5.7 KB of JSON each; a thoroughly evidenced review
will be several times that. As an illustration only, with the assumptions
stated: 20 projects, 300 saves a year each, 20 KB a document is 120 MB a year of
history, and 20 people refreshing the dashboard through a working day adds on
the order of hundreds of thousands of read rows a year. Measure your own: the
first number you need is the one `make doctor` prints.

`make doctor` reports the revision count, the average revision size, the audit
log and read trail sizes, and the whole database. It sets no threshold, because
the right one depends on the disk it sits on. **Alert on the disk instead**, and
leave room to act:

| | Disk alert | Let the disk grow |
|---|---|---|
| Cloud SQL | an alert on `cloudsql.googleapis.com/database/disk/utilization` | `--storage-auto-increase` (and a limit) |
| RDS | a CloudWatch alarm on `FreeStorageSpace` | `--max-allocated-storage` enables storage autoscaling |
| Azure Database | a metric alert on `storage_percent` | storage auto-grow |
| Compose stack | an alert on the Docker volume's filesystem | extend the volume |

!!! warning "Not exercised against any real managed database"

    These settings come from the providers' documentation and have not been run
    here. Check them before you rely on them.

How long each of these is kept is decided (see [Privacy and
retention](privacy.md), R-54), and `make dispose` applies it: an operator runs it
after the records officer approves a schedule. It empties the content of retired
projects' revisions, which is most of the volume (the rows stay, because that is
what makes them tombstones), and deletes read-trail rows past their period. Until
the first disposal run, the only way to make room is more disk.

### Encryption at rest

The practice followed here is the HIPAA Security Rule's for encryption at rest
(45 CFR 164.312(a)(2)(iv)): implement it, or document why an equivalent is
reasonable. On a managed database the provider's storage encryption
is the usual answer, and what to confirm differs:

| | Storage encryption | Customer-managed key |
|---|---|---|
| Cloud SQL | on by default, with Google-managed keys | optional, chosen when the instance is created |
| RDS | **off unless you pass `--storage-encrypted` when you create the instance**, and it cannot be turned on for an existing one (restore from an encrypted copy of a snapshot); the command below sets it | optional, with `--kms-key-id` |
| Azure Database for PostgreSQL | on by default, with service-managed keys | optional |

!!! warning "Not exercised against any real managed database"

    These come from the providers' documentation. Confirm the setting on the
    instance you actually have (not the one in this guide), and record that you
    did: the point of an addressable standard is the decision, and a default
    nobody checked is not one.

The Compose stack's own `pgdata` volume is not covered by any of this. See
[Self-hosting](self-hosting.md#encryption-at-rest).

### Data residency

Every example below takes the region from a variable (`REGION` on Google Cloud
and AWS, `LOCATION` on Azure) and leaves it for you to fill in. That is on
purpose: where the records are stored is a decision for your organization, not a
default this guide should make. The database, its backups, the container
registry and the logs each live in a region, and a deployment that never chose
one stored its data wherever the first example happened to point.

For a deployment that must keep data in the EU, these are the regions to look at
first. The names are from each provider's documentation and are **unverified**
here; confirm them, and that every service you use (the database, its backups and
replicas, the registry, the log sink, the identity provider) is available there.

| Provider | Example EU regions |
|---|---|
| Google Cloud | `europe-west1` (Belgium), `europe-west4` (Netherlands) |
| AWS | `eu-central-1` (Frankfurt), `eu-west-1` (Ireland) |
| Azure | `westeurope` (Netherlands), `germanywestcentral` (Frankfurt) |

Choosing an EU region does not by itself settle the question of cross-border
transfer. Support staff, the identity provider, an off-host backup copy and a log
destination elsewhere can each move personal data out of the region. Whether any
of that needs a transfer mechanism, and which, is a question for your data
protection officer or counsel. This guide is not legal advice and does not say
that any region meets a legal requirement.

### Backup and recovery

The model is the HIPAA Security Rule's contingency plan (45 CFR 164.308(a)(7)):
a data backup plan, a disaster recovery plan, and testing them. These records
are the evidence that a clinical AI deployment was reviewed, and by whom: losing
them is itself the compliance event, and re-entry cannot reconstruct sign-off
dates or authorship. So the managed database's durability settings are not
optional extras. Set them when you create the instance:

| | Point-in-time recovery and backup retention | Deletion protection | Copy outside the account |
|---|---|---|---|
| Cloud SQL | `--backup-start-time=03:00 --enable-point-in-time-recovery --retained-backups-count=14 --retained-transaction-log-days=7` | `--deletion-protection` | `gcloud sql export sql` to a bucket in **another project** |
| RDS | `--backup-retention-period 35` (the maximum; it also enables point-in-time recovery) | `--deletion-protection` | snapshots copied to **another account** (AWS Backup, or a shared, re-encrypted snapshot) |
| Azure Database | `--backup-retention 35` | a resource lock on the server | `--geo-redundant-backup Enabled`, which can only be set when the server is created |

!!! warning "Not exercised against any real managed database"

    The flags above are from the providers' documentation. None has been run
    here: check each against the current documentation before you rely on it,
    and do not read the retention numbers as recommendations. They are what the
    mechanism allows.

Decide, and write down, two numbers this repository cannot choose for you:

- **RPO**, how much recent work you can afford to lose. Point-in-time recovery
  gives minutes; a daily dump gives up to a day.
- **RTO**, how long you can be without it. Measure it: restore into a scratch
  instance and time it. For the Compose stack, `make verify-backup` does exactly
  that against a real dump.

Two rules apply on every platform. **A backup lives somewhere an attacker with
your production credentials cannot delete**: another account, project or
subscription, with its own credentials. And **a backup nobody has restored is a
hypothesis**: schedule the restore test, and record the date of the last one.

For the Compose stack the same plan is `make backup` on a schedule, a copy to
off-host storage, and `make verify-backup`; see
[Self-hosting](self-hosting.md#backups-make-backup-is-a-tool-not-a-backup-strategy).

### Retention and disposal

Records past their retention period are disposed of by an operator, not by the
server: `make dispose` reports what is due and changes nothing, and
`make dispose APPLY=1 BY=<your name>` disposes of it and records who did
([Privacy](privacy.md#disposal-at-the-end-of-the-period) has the detail). Before
go-live:

1. **Have your records officer approve the schedule.** That means the retention
   periods (6 years for a retired project's record and for the read trail, by
   default; your organization's records retention schedule takes precedence)
   and how often disposal runs (monthly is typical). Record who approved it and
   when, with your other records-management approvals.
2. **Set the periods if they differ**, as the database owner, in the
   `retention_policy` table. The change is stamped with who made it and when.
3. **Schedule `make dispose`** (or the same `psql` call against your managed
   database) at the approved interval, and have someone read the report before
   each `APPLY=1` run.
4. **Agree who places litigation holds.** An owner of a project places and
   lifts one on its setup page, with a reason; counsel should know that a hold
   is how they stop disposal.

### Two database roles

The audit log and the version history are append-only because of database
triggers, and a table's owner can switch a trigger off with one statement. So
the API must not hold the owner's credential: it serves as a **restricted role**
that can read and write the project tables and nothing else, and a separate job
holds the owner.

1. **The owner** (`DATABASE_URL`) runs `python -m app.migrate` as a one-off job
   before each deploy: a Cloud Run job, an ECS `run-task`, a Container Apps job.
   It applies the migrations, then creates or updates the restricted role from
   `APP_POSTGRES_USER` (default `chai_app`) and `APP_POSTGRES_PASSWORD`. It is
   idempotent, so run it on every deploy; it also re-applies the password, so
   rotating that is a re-run, not a manual `ALTER ROLE`. It also needs
   `RETIREMENT_MANIFEST`, the path of the `manifest.json` built beside the page
   you deploy (`docs/app/manifest.json` for the published build), from which it
   loads which checkpoint decisions retire a project. The API image does not
   carry it, so mount it into the job or copy it into a derived image. Without
   it, or when the manifest would stop the database retiring projects on a
   decision it retires on today, start on one it does not, or change the primary
   framework, the job fails, unless
   `RETIREMENT_RULES_ACK` is set to the acknowledgment it prints ([Self-hosting](self-hosting.md#which-build-it-serves-and-the-retirement-rules)).
   The acknowledgment is bound to the database through `pg_control_system()`,
   which PostgreSQL lets every role call; a managed service that withholds it
   from the job's role leaves the job refusing every change of the rules.
2. **The service** gets `APP_DATABASE_URL` (the restricted role, with
   `?sslmode=verify-full`) and `RUN_MIGRATIONS=false`, and **never** the owner's
   `DATABASE_URL`. If the secret store lets the service read both, the split does
   nothing.

If the platform's identity-based database login (Cloud SQL IAM, RDS IAM, Entra)
creates the user for you, run `python -m app.migrate --print-grants` and apply
what it prints to that user as the owner: it is exactly what the job grants.

`GET /api/health` reports `"db_role":"restricted"` when this is in place and
`"owner"` when the API owns the tables or is a superuser, and the API logs a
warning at startup in that case. `make doctor` fails on it for the compose stack.

!!! warning "Not exercised against a real cloud database"

    The role split is tested against PostgreSQL and the full Compose stack. The
    cloud job definitions above are the shape, not a tested recipe: none has been
    run against Cloud SQL, RDS or Azure Database for PostgreSQL.

!!! note "Do not implement the merge with `jsonb` concatenation"

    PostgreSQL's `||` operator on `jsonb` merges only the top level, so
    `{"items":{"s4-2":{"status":"met"}}}` would discard every other key
    under `items`. Use `jsonb_set` recursively, a PL/pgSQL function, or
    read-modify-write inside a transaction.

### Personal data the server keeps about staff

A governance record names people, so the server holds personal data about the
workforce, and a records-of-processing entry should say so:

| Where | What | Why |
|---|---|---|
| `principals` | the identity id, display name and email the proxy asserted, and when first and last seen | so an access list or a sign-off shows a person instead of an opaque id |
| each project's `access` | ids of its owners, writers and readers | access control |
| `project_log`, `project_version`, `project_deletion` | the id of whoever made each change, and when | the audit trail |

`principals` is built from observed sign-ins: it holds exactly the people who have
used the system, and no one from a directory the system cannot see. It is **not**
open: `GET /api/principals?ids=` answers only for the caller themself and for
people named on a project the caller can already read (its access lists, its
sign-offs, its log authors). Anyone else is omitted, so a signed-in user cannot
walk the table. Rows are updated in place when a name changes and are not reached
by a project purge. The application never deletes one; `make dispose` removes a
person who has not signed in for the read-trail period and whom no retained record
names.

The id alone is what the access lists and the audit trail depend on. If the name
and email are unwanted, the proxy can simply not assert them: the API then records
an empty name and shows the id.

Agent tokens (`agent_token`, [The agent API](agent-api.md)) hold the owner's
identity id, an optional label they typed, when the token was made, used and
revoked, and a hash of its secret. A token is deleted with its owner's
`principals` row, and `make subject-access` finds it. Every agent call is also a
row in the read trail, marked `via = 'agent'`, so what is said above about
`access_event` covers it.

### Streaming: `/api/events`

`GET /api/events` is a long-lived `text/event-stream` response. Three
things break it on managed platforms:

- **Response buffering.** Send `Cache-Control: no-cache` and
  `X-Accel-Buffering: no`, and flush after every event.
- **Timeouts.** Covered per cloud below. Send a comment heartbeat
  (`: ping\n\n`) every 15–30 seconds so idle timers never fire.
- **More than one replica.** An event written on replica A must reach a
  browser subscribed on replica B. Use PostgreSQL `LISTEN`/`NOTIFY` as
  the fan-out bus, or pin the service to a single replica until you do.

### The read trail

Every read of a governance record is recorded, so the question a breach asks has
an answer: *account X was compromised on the 3rd and closed on the 9th; which
records did it open, and did it export any?* This follows the HIPAA Security
Rule's audit controls standard (45 CFR 164.312(b)).

`access_event` holds one row per access, **in the same transaction as the read
it describes**: a list, a project's revision list, one revision, a project's
audit log, an event-stream attach, and an export. A read that cannot be recorded
is not served. It is append-only: a trigger refuses any `UPDATE`, and refuses a
`DELETE` of a row younger than the read-trail period or belonging to a project
under a litigation hold, so old rows go only when an operator disposes of them
(`make dispose`). It has no
foreign key, so it outlives the project it names, and holds ids and facts,
never content: a list records the ids of the projects it returned, an export its
format. A call made with an agent token ([The agent API](agent-api.md)) is a row
too, marked `via = 'agent'` and carrying the token's public id; a refused agent
call is one as well, with the reason. The same fact is also emitted as a
`record.read`, `record.exported` or
`stream.attached` security event, which is the copy a database administrator
cannot alter.

```sql
-- every record this account opened or exported in a period
SELECT at, action, project_id, revision, source_ip, detail
  FROM access_event
 WHERE actor = 'person@hospital.org'
   AND at >= '2026-01-01' AND at < '2026-02-01'
 ORDER BY at;

-- who opened this record
SELECT at, actor, action, revision, source_ip
  FROM access_event
 WHERE project_id = 'sepsis-2026'
 ORDER BY at DESC;
```

A *list* is a read of every project it returned, so look inside `detail ->
'projects'` for those; a list the account made after it lost access to a project
does not contain it.

**What this does not cover.** Exports are built in the browser from data it
already fetched, so the server never sees one happen. The export beacon records
ordinary use; it is **not** a control, because a client can omit it. What bounds
what any export could contain is the reads that fetched the data, and those are
recorded. `source_ip` is what the proxy reported, for correlation, and is not
authentication. It is kept for six years, or your audit-log
policy if shorter (see [Privacy and retention](privacy.md)).

### Updating

What is running is what the repository says: the API's dependencies are locked
with hashes (`server/requirements.txt`), and the base images, the database and
the proxy are pinned by digest (`compose.yaml`, both Dockerfiles). A rebuild
produces the same thing from the same source, and a new base image arrives as a
reviewed pull request from Dependabot, not as whatever a tag points at that day.

That has a consequence for the operator: **`docker compose up -d` does not pull
a newer image.** It runs what is already on the host. So after you merge an
update:

```bash
git pull
docker compose pull db proxy proxy-perms  # database and proxy, at their new digests
docker compose build --pull api           # the API image: new lock, new base image
docker compose up -d                      # recreate only what changed
```

`make lock` regenerates `server/requirements.txt` inside the same Python the
image uses; review its diff, because a changed hash is a changed dependency. For
the cloud image, rebuild and push the proxy image from `proxy/Dockerfile` and
deploy the new tag; the base image inside it is pinned by digest the same way.

A scheduled scan (`.github/workflows/security.yml`) builds our images weekly and
on every pull request, fails on a HIGH or CRITICAL finding that has a fix, and
writes a software bill of materials as a build artifact. Findings in the
official database and proxy images are reported but do not fail it, because they
are not ours to patch. Report a vulnerability in this project as `SECURITY.md`
describes.

### Security events: collecting, retaining and alerting

The only record of a delete, a purge, a rejected request or a 401 used to be a
line of English on container stdout, which nothing collected, so a restart lost
it and nothing could alert on it. The practice followed is the HIPAA Security
Rule's regular review of activity (45 CFR 164.308(a)(1)(ii)(D)) and security
incident detection (164.308(a)(6)(ii)).

The API now writes **one JSON object per line** (`LOG_FORMAT=json`, the default),
and every security-relevant event has a **stable name** and fields. Each line is
tagged `"stream": "security"` (application chatter is `"stream": "app"`), so a
log sink can alert on the first and **retain it for longer** than the second:
six years of debug logging is not the ask. The security stream is held at INFO
whatever `LOG_LEVEL` says, so turning the application log down never stops
recording that a project was deleted.

| Event | Level | Fields | What it means |
|---|---|---|---|
| `auth.no_identity` | warning | `method`, `path`, `header` | A request reached the API with no identity header. In a correct deployment this cannot happen: the proxy sets it on every request. **Alert on any**: it means traffic reached the API around the proxy. |
| `auth.peer_rejected` | warning | `method`, `path`, `peer` | The TCP peer was outside `TRUSTED_PROXY_CIDR`. **Alert on any.** |
| `auth.secret_rejected` | warning | `method`, `path`, `header` | A request lacked the `PROXY_SHARED_SECRET` header (the value is never logged). **Alert on any.** |
| `auth.token_unreadable` | warning | `header`, `reason` | A signed identity assertion could not be decoded (the token is never logged). |
| `auth.audience_rejected` | warning | `aud`, `signer`, `expected` | A token minted for another service reached this one. |
| `csrf.rejected` | warning | `method`, `path`, `site` | A cross-site write was refused. |
| `access.denied` | warning | `actor`, `project`, `need`, `held`, `status` | An authenticated user reached for a project they have no right to. A burst from one `actor` is worth a page. |
| `access.breakglass` | warning | `actor`, `project`, `action` | Emergency access was used. **Alert on any**, then check the project's own audit log. |
| `project.created` | info | `actor`, `project` | A project was created. |
| `project.deleted` | info | `actor`, `project` | A project was deleted (its history is kept; see the deletion tombstone). |
| `versions.purged` | warning | `actor`, `project`, `revisions`, `log_entries`, `incarnation`, `purged_at`, `through_rev`, `through_seq` | A version history and its audit log were destroyed. Review every one. Keep these: they re-apply the purge after a restore. |
| `hold.placed` | warning | `actor`, `project` | A litigation hold now stops this project's disposal. The reason is not logged; it is with the hold. |
| `hold.lifted` | warning | `actor`, `project` | A litigation hold was lifted, so the project can be disposed of when due. Confirm counsel agreed. |
| `retirement.rules_changed` | warning | `framework`, `active_primary`, `added`, `removed`, `unlisted`, `acknowledged`, `rule_set_hash`, `active_rule_set_hash` | The migrate job (or an API with `RUN_MIGRATIONS=true` and a manifest) changed or confirmed the retirement rules from the build's manifest. Review every one; `acknowledged` is true when a rule was added or removed or the primary changed (`active_primary` is the one before, `framework` the one after), which only an operator's `RETIREMENT_RULES_ACK` allows. `unlisted` names frameworks whose rules the manifest left alone. |
| `retirement.rules_refused` | warning | `framework`, `active_primary`, `added`, `removed`, `projects`, `rule_set_hash`, `active_rule_set_hash` | The migrate job refused a manifest that adds or removes a retirement rule, or changes the primary, without the `RETIREMENT_RULES_ACK` for exactly that change, and changed nothing. The new build does not start; over a running stack the old API keeps running ([Self-hosting](self-hosting.md#which-build-it-serves-and-the-retirement-rules)). Either an old build was deployed over a newer one, or the change needs an operator's acknowledgment. |
| `ratelimit.tripped` | warning | `key`, `limit`, `window_seconds` | A client hit the rate limit. Once per client per window. |
| `stream.refused` | warning | `actor` | Too many open event streams for one user. |
| `stream.attached` | info | `actor`, `action`, `source_ip` | An event stream was opened. The read trail records it too. |
| `record.read` | info | `actor`, `action`, `project`, `revision`, `source_ip` | A list or a read of versions or a log. One per row of the read trail. |
| `record.exported` | info | `actor`, `action`, `project`, `format`, `source_ip` | The dashboard reported an export. |
| `agent_token.minted` | info | `actor`, `token_id`, `expires_at` | A person minted an agent token ([Agent API](agent-api.md)). The token's public id, never its secret. |
| `agent_token.revoked` | info | `actor`, `token_id`, `by` | A person revoked one of their own agent tokens. An operator's revocation is a row in `agent_token`, not an event: the script's output is the record. |
| `agent.refused` | warning | `actor`, `action`, `project`, `source_ip`, `via`, `token_id`, `reason`, `route` | An agent call was refused and is a read-trail row: a token that exists but is expired, revoked or given the wrong secret (`reason` says which; the caller is only told it is invalid), or a project the token's user cannot see. Rows are bounded per token id across all sources and overall, by kind: at most 10 wrong-secret rows per token id a window and 5 for a right secret or a project not visible, and 100 of each kind overall. |
| `agent.failures` | warning | `failures`, `limited_sources`, `global_limited`, `evicted_sources`, `top`, `rows_not_written`, `window_seconds` | One line a window, written by a background task every half window (and at shutdown), summarizing the failed agent calls (bad, unknown, expired or revoked tokens) and the trail rows the budgets turned away: how many failures, how many sources went over their limit, how many were answered by the global budget, how many sources were dropped to stay within the table's cap, and the top sources with their counts. No row is written for the failures themselves. A large `failures` is a guesser. |

The names are an interface: an alert is written against them, so a test fails if
this table and the code ever disagree.

Fields are ids and facts, never a document, a token or a secret, and every value
is JSON-encoded, so an identity containing a quote or a newline stays inside its
own string and cannot forge a second record.

**Where it goes.** In the Compose stack every service uses Docker's `json-file`
driver capped at 10 MB by 5 files. That makes local retention *finite and
honest*, about 50 MB a service, and it is **not** a retention policy: ship the
logs to a collector (journald, syslog, Loki, your SIEM) and retain them there.
`LOG_FORMAT=text` gives the readable line for a terminal.

On a cloud, stdout goes to the platform's log service, and what to configure
there is the part this repository cannot test:

| | Sink | An alert on `auth.no_identity` | Retention |
|---|---|---|---|
| Google Cloud Run | Cloud Logging (a JSON line becomes `jsonPayload`; `severity` is read) | a log-based alert on `jsonPayload.event="auth.no_identity"` | the log bucket's retention; route `jsonPayload.stream="security"` to its own bucket |
| AWS ECS | CloudWatch Logs via the `awslogs` driver | a metric filter with the pattern `{ $.event = "auth.no_identity" }` | the log group's retention (2192 days is six years) |
| Azure Container Apps | Log Analytics (`ContainerAppConsoleLogs_CL`) | a log alert on `Log_s has '"event": "auth.no_identity"'` | the table's retention |

!!! warning "Not exercised against any real log service"

    The names, fields and the one-object-per-line format are tested here, against
    the real output. The sink, filter and retention settings above come from the
    providers' documentation and have not been run. Check them before you cite
    them, and set a retention that matches your own policy: how long you must keep
    audit records is your decision, not this table's.

### Session lifetime and automatic logoff

The practice followed is the HIPAA Security Rule's for automatic logoff (45 CFR
164.312(a)(2)(iii)): implement it, or document an equivalent and why. This
application has **no session of its own**:
identity arrives from your front door on every request, so the control that ends
a session is the front door's, and the equivalent to point at is its session
lifetime. Set it to what your risk assessment says for shared clinical
workstations.

| Front door | Where the session lifetime is set | Sign-out |
|---|---|---|
| Google IAP | the IAP reauthentication policy on the protected resource (session duration) | `https://YOUR_APP/?gcp-iap-mode=CLEAR_LOGIN_COOKIE` |
| AWS ALB (`authenticate-oidc`) | the action's `SessionTimeout` (seconds; the default is seven days) | the ALB has no logout endpoint: use your IdP's end-session URL, and keep `SessionTimeout` short |
| Azure Easy Auth | the authentication settings' cookie expiration (`login.cookieExpiration`) | `/.auth/logout` |
| oauth2-proxy | `--cookie-expire` and `--cookie-refresh` | `/oauth2/sign_out` |

!!! warning "Not exercised against any real front door"

    These settings come from the providers' documentation. Nothing in this
    repository starts an IAP, an ALB, Easy Auth or an oauth2-proxy session, so
    check each against the provider's current documentation before you cite it
    in a risk assessment.

What this application adds on top, all configured in the environment:

- **`SSE_MAX_LIFETIME_SECONDS`** (default 900). The live-update stream
  (`/api/events`) authenticates once, when it attaches, so before this a stream
  opened before an account was disabled kept delivering change notifications
  after it. The API cannot ask the identity provider whether a session is still
  good, but it can end the stream, and the browser's reconnect goes back through
  the front door and is authenticated again. A revoked session therefore loses
  its stream within this many seconds. `0` is no limit.
- **`IDLE_LOCK_MINUTES`** (default `0`, off). After this many minutes with no
  input the dashboard hides the record and asks for a reload, which goes back
  through the front door. Unsaved edits are saved first. It is a screen lock for
  an unattended workstation, not a security boundary: the front door's session
  is.
- **`SIGN_OUT_URL`**. Shows a "Sign out" link to your front door's sign-out
  address (the last column above). It must be an `https` URL or a path on this
  origin; anything else is refused at startup, because it becomes a link in the
  page.

If the connection to the event stream is lost for good (for instance because the
session ended and the front door now refuses the reconnect), the dashboard says
it is disconnected instead of continuing to look live.

### Offboarding, and emergency access

Whoever creates a project is its only owner until somebody adds a second, so the
commonest way a record becomes unreachable is that its creator leaves and their
SSO account is disabled. Nobody left can then open, export, reassign, archive or
delete it, and the API answers 404 to everyone else on purpose.

**Before you disable an account**, find what it solely owns and give each project
a second owner (*Project setup → Access*, as any current owner, or as an
emergency-access identity, below). Run this as the database owner, with the
person's id as the proxy asserts it (the same id the access lists hold):

```sql
-- projects whose ONLY owner is this person
SELECT id, doc -> 'meta' ->> 'solution' AS solution
  FROM projects
 WHERE CASE WHEN jsonb_typeof(doc -> 'access' -> 'owners') = 'array'
            THEN jsonb_array_length(doc -> 'access' -> 'owners') = 1
                 AND doc -> 'access' -> 'owners' ->> 0 = 'person@hospital.org'
            ELSE false END;

-- every project with a single owner, whoever it is
SELECT id, doc -> 'meta' ->> 'solution' AS solution,
       doc -> 'access' -> 'owners' ->> 0 AS only_owner
  FROM projects
 WHERE CASE WHEN jsonb_typeof(doc -> 'access' -> 'owners') = 'array'
            THEN jsonb_array_length(doc -> 'access' -> 'owners') = 1
            ELSE false END
 ORDER BY only_owner, id;
```

The dashboard also tells an owner, in *Access*, when they are a project's only
owner, and `make doctor` warns with a count.

**Emergency access** is for when that did not happen. It follows the HIPAA
Security Rule's emergency access procedure (45 CFR 164.312(a)(2)(ii)): a record
nobody can reach is a failure whatever it holds. Set
`EMERGENCY_ACCESS_IDS` to one or more identity ids, comma-separated, as the proxy
asserts them. Each holds owner rights on **every** project: read, export,
reassign, archive, delete and purge.

- It is a path around the access lists, so every use is recorded where the
  project's owners will see it: a system entry in **that project's own audit log**
  ("EMERGENCY ACCESS: ... used break-glass access to change this project. This was
  not granted by this project's access list."), tagged `event: access.breakglass`,
  which a purge never redacts. Reads of the same project by the same person are
  one entry per ten minutes (a dashboard polls); every write, archive, purge or
  reassignment is its own entry. **Every** use, throttled or not, is also an
  `access.breakglass` [security event](#security-events-collecting-retaining-and-alerting).
  Alert on that.
- A *delete* cannot leave an entry in the project's log, because the log goes with
  the project by design. It is recorded by that warning and by the deletion
  tombstone's `deleted_by`.
- These are real SSO identities, so the person still signs in through the front
  door, with whatever MFA it demands. Name people or a sealed account held by the
  Security Officer, not a shared mailbox, and review the list. The API logs who
  holds it at every startup.
- Off by default: with the variable unset nobody has emergency access.

### Browser spellcheck on workstations

What a person types into the dashboard can leave the workstation before it is
saved, if the browser's spellchecker is cloud-backed. Chrome's *Enhanced spell
check* sends typed text to Google, and some Safari and macOS settings route text
through Apple. Evidence and rationale fields are where a patient identifier gets
pasted by mistake, and none of this application's controls apply before a save.

The dashboard turns spellcheck and form history off on its multi-line fields, but
it cannot see or set the browser's own policy. **Disable cloud-backed spellcheck
by policy on workstations that use this tool** (Chrome: the
`SpellCheckServiceEnabled` policy set to false; Edge: `SpellcheckEnabled`, or
the equivalent in your management tooling). That is the control that can be
enforced, and it also covers fields this application does not control.

## The auth model: reverse-proxy header trust

Each cloud front door does the same three things: it intercepts the
request, it redirects the browser through the identity provider, and it
forwards the request to the container with the resulting identity in
HTTP headers. What differs is which headers, and whether they can be
cryptographically verified.

### Why there is no password login

This is the first question a security review asks, so the answer is
recorded here rather than left to be rediscovered.

There is no user table, no password hash and no registration form.
Sign-in is the hospital's existing identity provider, and the application
only ever learns who you are from the proxy in front of it. The one token the
application issues is the read-only agent token ([The agent
API](agent-api.md)): a signed-in person mints it for themselves, it lasts
8 hours, and it reads what their own dashboard shows on three `GET` routes and
nothing else. It is not a way to sign in: no other route accepts it.

That is a decision, not an omission. Adding local accounts — the
`OAuth2PasswordRequestForm` pattern from the FastAPI tutorial, or
anything like it — would mean taking on:

- a credential store, and the hashing and rotation policy that goes with it;
- lockout, complexity and reuse rules;
- multi-factor enrollment and recovery, which an organization handling
  patient data is expected to have;
- token issuance, expiry and revocation;
- an audit trail for credential events, separate from the one this tool
  already keeps for governance decisions.

Every one of those is a thing that can be got wrong, in a tool whose
current authentication surface is reading one header. None of them is
the problem this tool exists to solve.

What delegating to the identity provider buys is more specific than
"less code":

**Offboarding actually works.** A clinician who leaves is disabled once,
in the directory, and loses access here at the same moment they lose
access to everything else. With local accounts, this tool becomes one
more place somebody has to remember to revoke — and the one nobody
remembers, because it is used by a committee that meets monthly.

**MFA is whatever the hospital already requires**, enforced at the front
door, with no second enrollment for users to abandon halfway.

**Password policy is somebody else's job**, and that somebody has already
argued it out with the security office.

**A checkpoint sign-off means something.** The identity attached to it
was asserted by the organization's IdP, not chosen by whoever was at the
keyboard. That is the difference between an audit record and a text
field — see the note on `localStorage` mode in [Running it](running.md).

The API enforces this rather than trusting the browser: `signedBy` and
`signedAt` are written by the server from the proxy's identity and its own
clock, whatever a client sends. Changing a decision re-attributes it to whoever
changed it; clearing one clears its attribution; re-sending an unchanged gate is
a harmless no-op. The committee's own words (`by`, `date`, `rationale`) stay as
written. Two consequences worth knowing: a record imported from elsewhere is
attributed to whoever imports it, because they are the one asserting it here,
and with `REQUIRE_IDENTITY=false` nothing is attributed, which `/api/health`
reports rather than hides.

#### If you have no identity provider

Run one in front; do not move authentication into the application. Put
[oauth2-proxy](https://oauth2-proxy.github.io/oauth2-proxy/) or
[Keycloak](https://www.keycloak.org/) ahead of Caddy and point
`IDENTITY_*_SOURCE` at the headers it sets — the
`Self-hosted oauth2-proxy / Keycloak gatekeeper` block in `.env.example`.
The application is unchanged, and the credential handling stays in
software built for it.

#### A second lock between the proxy and the API

`PROXY_SHARED_SECRET` is a second lock between the proxy and the API, not a way
for a caller to sign in. Set it once in `.env` and Compose gives the same value
to both: the proxy sends it as `X-Proxy-Secret`, and the API answers 403 to any
request that arrives without it. Generate one with `openssl rand -hex 32`. It is
defense in depth beside closing the network, not a substitute for it.

#### If you need non-interactive access

Scripts, scheduled jobs and CI are not users and should not have user
passwords. Authenticate them at the proxy — a service account in the
cloud front door — and leave the browser path alone. For a program that
only needs to *read* the registered statuses on a person's behalf, see
[The agent API](agent-api.md): a per-user, 8-hour, read-only token that
needs its path let through the front door, which that page says how to do. The
exporters under
`examples/` read exported JSON and need no API access at all.

#### The agent API's path, and each front door

The read-only agent API ([The agent API](agent-api.md)) is the one part of the API
that a program with no single sign-on session calls. Its three `GET` routes under
`/api/agent/` must reach the proxy **without** the front door asking for a sign-in,
and nothing else may: `/api/agent-tokens`, which mints a token, is a person's and
stays behind sign-on. What to do depends on the front door, and the page lists
each (Google Cloud IAP, the AWS ALB, Azure Easy Auth, oauth2-proxy, Keycloak and
the Compose stack's own Caddy). The summary is that a front door that
authenticates every path and cannot be told to skip one cannot offer the agent API,
and the API should stay off there (leave `AGENT_ID_SECRET` empty). Only the
proxy in
this repository is tested for the route; the rest is the platform's own documented
behavior, and you should confirm it in your environment before relying on it.

#### The optional MCP service's path, and each front door

The optional [MCP server](mcp.md) (a compose profile, off by default) adds one
more path that a program with no single sign-on session calls: `POST /mcp`. Like
the agent API's, it must reach the proxy **without** the front door asking for a
sign-in, and nothing else may. [The MCP page](mcp.md#let-mcp-through-your-front-door)
lists what to do for each front door (the AWS ALB, Azure Easy Auth, oauth2-proxy
and
nginx, Google Cloud IAP, a gateway, and this stack's own Caddy), and where it
cannot be done: a front door that authenticates every path and cannot be told
otherwise cannot offer it, and the profile should stay off there. Only the proxy
in this repository is tested for the route. The profile needs a place for its two
small containers next to the proxy (`mcp-gate` and `mcp`, on a network of their
own), and `MCP_ALLOWED_HOSTS` set to the host name the **service** sees, which a
front door that rewrites `Host` changes. Serve it over HTTPS only, since a token
travels in every request.

### Plain headers versus signed assertions

Every front door sets a convenient plaintext header such as
`x-goog-authenticated-user-email` or `x-amzn-oidc-identity`. Two of the
three also set a **signed JWT assertion** alongside it.

!!! warning "Prefer the signed assertion — but know what this image does with it"

    The plain headers are indistinguishable from headers an attacker sets by
    hand. A signed assertion *can* be told apart, because it carries a
    signature checkable against the provider's public key.

    **This image does not perform that check.** It decodes the assertion to
    read its claims and, with `IDENTITY_HEADER_FORMAT=jwt`, compares the `aud`
    claim to `IDENTITY_AUDIENCE`. That catches a token minted for another
    service in the same account; it does not catch a forgery, because an
    unverified signature constrains nothing.

    So prefer the assertion — the audience check is worth having, and it is the
    header a future verifying implementation will use. But do not treat it as
    defense in depth today. Closing direct access to the container is the only
    control actually standing between an attacker and a forged identity.

Google's own documentation is blunt about this: "If an attacker bypasses
IAP, the attacker can forge the IAP unsigned identity headers." AWS is
equally direct: "you must verify the signature of `x-amzn-oidc-data`."

### What a verifying `/api/me` would do — not implemented in this image

!!! danger "This image does not verify signatures. Network isolation is the control."

    Read this before deciding whether the stack is safe enough for your
    environment, because the rest of this page assumes you have.

    `server/app/auth.py` **decodes** a signed assertion to read its claims. It
    does **not** verify the signature, the issuer or the expiry, and it cannot:
    no public key is ever fetched. A forged assertion presented to the
    container directly is accepted.

    That is the auth model this project chose — trust a header set by a front
    door, and make the front door the only way in. It is a legitimate choice,
    and it is why every section below spends more space on closing direct
    access than on anything else. But it means the network control is not
    defense in depth. **It is the whole defense.** If the container is
    reachable without passing the front door, identity is forgeable.

    `IDENTITY_AUDIENCE` does give you one real check: with
    `IDENTITY_HEADER_FORMAT=jwt` the `aud` claim is compared to the value you
    set, which catches a token minted for a *different* service in the same
    cloud account. It catches misconfiguration. It does not catch forgery.

The upgrade path, should you want real verification:

```text
1. Read the signed assertion header. If missing -> 401.
2. Verify the signature against the provider's public key.
3. Verify the audience/signer matches THIS service, not merely that
   the token is valid somewhere in the cloud provider's fleet.
4. Verify issuer and expiry.
5. Return {id, name, email} from the verified claims.
```

Step 3 is the one people skip. A signature check alone proves the token
came from the cloud provider — not that it was minted for your service.

!!! danger "Never read identity from the request body or a query string"

    The browser must have no way to influence who it is. Strip any
    inbound copy of the identity headers at the edge of your handler
    before routing, so a client-supplied `X-MS-CLIENT-PRINCIPAL-NAME`
    cannot shadow the one the platform set.

## Google Cloud: Cloud Run behind Identity-Aware Proxy

### Architecture

```text
Browser
  |  HTTPS
  v
Identity-Aware Proxy  <-- Google Workspace / Cloud Identity
  |  adds x-goog-iap-jwt-assertion
  v
Cloud Run service (--no-allow-unauthenticated, --iap)
  |  private IP, Direct VPC egress
  v
Cloud SQL for PostgreSQL (no public IP)
```

IAP can now be enabled directly on a Cloud Run service. This is the
current recommended shape: it protects the `run.app` endpoint itself,
so you do not have to provision an external Application Load Balancer,
a serverless NEG and a managed certificate just to get a front door.

!!! note "The load-balancer route still exists"

    If you need Cloud Armor, a custom domain with your own certificate,
    or path-based routing to several backends, put an external
    Application Load Balancer in front and enable IAP on the backend
    service instead. The audience format changes — see below.

### The headers IAP sets

| Header | Contents | Verifiable? |
|---|---|---|
| `x-goog-iap-jwt-assertion` | Signed JWT (ES256) with the user's identity | **Yes** |
| `x-goog-authenticated-user-email` | `accounts.google.com:user@example.org` | No |
| `x-goog-authenticated-user-id` | `accounts.google.com:1234567890` | No |

Note the namespace prefix on the plain headers: the value is *not* a
bare email address. Code that forgets to strip `accounts.google.com:`
will store a malformed identity in the audit log.

IAP also uses `X-Serverless-Authorization` to authenticate itself to
Cloud Run; Cloud Run strips that header's signature before your
container sees the request. Do not build anything on it.

### Verify the assertion

Validate `x-goog-iap-jwt-assertion` as an ES256 JWT:

- **Keys**: `https://www.gstatic.com/iap/verify/public_key-jwk`
  (JWK set) or `https://www.gstatic.com/iap/verify/public_key` (PEM).
- **Issuer**: `https://cloud.google.com/iap`
- **Audience**, and this is the part that pins the token to *your*
  service:

    | Enablement | `aud` |
    |---|---|
    | IAP directly on Cloud Run | `/projects/PROJECT_NUMBER/locations/REGION/services/SERVICE_NAME` |
    | IAP on a load-balancer backend service | `/projects/PROJECT_NUMBER/global/backendServices/SERVICE_ID` |

The identity you want is the `email` and `sub` claims of the verified
payload — use those, not the plain headers.

### Close the back door

On Cloud Run the enforcement is IAM, not network ACLs. Deploy with
`--no-allow-unauthenticated` so the service refuses any caller that
cannot present a Google-signed ID token with the `run.invoker`
permission, then grant that permission to the IAP service agent and to
nobody else:

```bash
REGION=<your-region>   # see "Data residency"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" \
  --format='value(projectNumber)')
IAP_SA="service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"

gcloud run services add-iam-policy-binding chai-api \
  --region="$REGION" \
  --member="serviceAccount:${IAP_SA}" \
  --role=roles/run.invoker
```

Then confirm nothing else holds it:

```bash
gcloud run services get-iam-policy chai-api --region="$REGION"
```

!!! danger "`allUsers` with `roles/run.invoker` is the back door"

    If that policy lists `allUsers` or `allAuthenticatedUsers` as an
    invoker, the `run.app` URL answers requests that never touched IAP,
    and every identity header becomes a free-text field. The output
    above should contain exactly one invoker: the IAP service agent.

!!! danger "Do not lock down ingress on this path"

    Two commands get recommended constantly for Cloud Run, and **both break
    this architecture**:

    ```bash
    # WRONG on the IAP-direct path -- do not run these here.
    gcloud run services update chai-api --region="$REGION" \
      --ingress=internal-and-cloud-load-balancing
    gcloud run services update chai-api --region="$REGION" --no-default-url
    ```

    With IAP enabled directly on the service, the default `run.app` URL **is**
    the IAP front door. `--no-default-url` deletes it, and
    `--ingress=internal-and-cloud-load-balancing` rejects the IAP-fronted
    traffic that arrives over it. The service stops answering for everyone.

    On this path, ingress stays `all` and the default URL stays enabled. What
    protects the service is the IAM policy above — the only invoker is the IAP
    service agent — not an ingress setting.

    Those two commands are correct on the load-balancer path below, where the
    load balancer is the front door and the `run.app` URL is genuinely a
    bypass.

If you took the load-balancer route instead (Cloud Armor, custom
certificate, path-based routing), then the `run.app` URL *is* a bypass and
both locks apply:

```bash
# Only on the LOAD BALANCER path, where the LB is the front door.
gcloud run services update chai-api --region="$REGION" \
  --ingress=internal-and-cloud-load-balancing
gcloud run services update chai-api --region="$REGION" --no-default-url
```

### Managed PostgreSQL

Cloud SQL for PostgreSQL with **no public IP**, reached over private
services access. Attach it to the service and let Cloud Run manage the
connector:

```bash
gcloud sql instances create chai-db \
  --database-version=POSTGRES_16 \
  --region="$REGION" \
  --tier=db-custom-2-7680 \
  --no-assign-ip \
  --network="projects/${PROJECT_ID}/global/networks/default" \
  --enable-google-private-path
```

### Secrets

Secret Manager, mounted as environment variables, read by the runtime
service account — never baked into the image or passed as `--set-env-vars`.

A `DATABASE_URL` you write by hand must have its password percent-encoded:
a `/`, `@`, `:`, `?` or `#` in it ends the URL early and the API refuses to
start, with a message saying so. The stack's own `POSTGRES_PASSWORD` does not
have this problem, because the API builds the URL and does the encoding.

```bash
# percent-encode the password first:
python3 -c 'import sys, urllib.parse as u
print(u.quote(sys.argv[1], safe=""))' 'the-password'

printf '%s' "postgresql://chai:ENCODED@/chai?host=/cloudsql/${INSTANCE}" \
  | gcloud secrets create chai-database-url --data-file=-

gcloud secrets add-iam-policy-binding chai-database-url \
  --member="serviceAccount:chai-run@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role=roles/secretmanager.secretAccessor
```

### Step by step

```bash
PROJECT_ID=my-project
REGION=<your-region>   # a data residency decision: see "Data residency"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" \
  --format='value(projectNumber)')
IAP_SA="service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com"
AUD="/projects/${PROJECT_NUMBER}/locations/${REGION}/services/chai-api"

gcloud services enable run.googleapis.com iap.googleapis.com \
  sqladmin.googleapis.com secretmanager.googleapis.com

# 1. Runtime identity with least privilege.
gcloud iam service-accounts create chai-run \
  --display-name="CHAI governance API"

# 2. Build and push.
gcloud builds submit --tag "${REGION}-docker.pkg.dev/${PROJECT_ID}/chai/api:v1"

# 3. Deploy with IAP on and anonymous invocation off.
gcloud run deploy chai-api \
  --region="$REGION" \
  --image="${REGION}-docker.pkg.dev/${PROJECT_ID}/chai/api:v1" \
  --service-account="chai-run@${PROJECT_ID}.iam.gserviceaccount.com" \
  --add-cloudsql-instances="${PROJECT_ID}:${REGION}:chai-db" \
  --set-secrets=DATABASE_URL=chai-database-url:latest \
  --set-env-vars="IDENTITY_MODE=iap" \
  --set-env-vars="IDENTITY_HEADER=x-goog-iap-jwt-assertion" \
  --set-env-vars="IDENTITY_HEADER_FORMAT=jwt" \
  --set-env-vars="IDENTITY_AUDIENCE=${AUD}" \
  --min-instances=1 \
  --max-instances=1 \
  --timeout=3600 \
  --no-allow-unauthenticated \
  --iap

# 4. Let IAP, and only IAP, invoke the service.
gcloud run services add-iam-policy-binding chai-api \
  --region="$REGION" \
  --member="serviceAccount:${IAP_SA}" \
  --role=roles/run.invoker

# 5. Decide who may sign in.
gcloud iap web add-iam-policy-binding \
  --resource-type=cloud-run \
  --region="$REGION" \
  --service=chai-api \
  --member="group:ai-governance@hospital.org" \
  --role=roles/iap.httpsResourceAccessor
```

!!! note "`--max-instances=1` is a placeholder, not a recommendation"

    It is there because `/api/events` has no cross-replica fan-out until
    you add `LISTEN`/`NOTIFY`. Raise it once you have. `--timeout=3600`
    sets the hard request limit to the Cloud Run maximum of 60 minutes;
    SSE clients must still reconnect when it expires, which the browser
    `EventSource` does on its own.

## AWS: ECS Fargate behind an Application Load Balancer

!!! warning "App Runner is closed to new customers"

    AWS has closed App Runner to new customers as of 30 April 2026.
    Existing customers may continue to use it, but no new features are
    planned, and App Runner cannot be registered as an ALB target
    anyway — which rules it out for header-trust auth. AWS points new
    workloads at **ECS Express Mode**, which provisions an ECS service
    on Fargate plus an Application Load Balancer from a single API call.
    Express Mode's load balancer is an ordinary ALB in your account, so
    everything below applies; you attach the authenticate rule to the
    listener it created.

### Architecture

```text
Browser
  |  HTTPS :443
  v
Application Load Balancer (public subnets)
  |  listener rule: authenticate-oidc -> Entra ID / Okta / Cognito
  |  adds x-amzn-oidc-data
  v
ECS Fargate tasks (private subnets, no public IP)
  |  security group allows :8080 only from the ALB's security group
  v
RDS for PostgreSQL (private subnets, not publicly accessible)
```

Use `authenticate-oidc` to point the ALB straight at the hospital IdP,
or `authenticate-cognito` if you want a Cognito user pool in between to
federate several IdPs or to add a group-to-role mapping. Both action
types require an **HTTPS** listener.

### The headers the ALB sets

| Header | Contents | Verifiable? |
|---|---|---|
| `x-amzn-oidc-data` | Signed JWT (ES256) of the user-info claims | **Yes** |
| `x-amzn-oidc-identity` | The `sub` claim, plaintext | No |
| `x-amzn-oidc-accesstoken` | The access token, plaintext | No |

AWS labels the latter two "legacy unsigned headers" kept for backward
compatibility, and states plainly that they "cannot be independently
verified by your application."

### Verify the assertion

```text
header: {"alg":"ES256",
         "kid":"<uuid>",
         "signer":"arn:aws:elasticloadbalancing:...:loadbalancer/app/...",
         "iss":"<idp issuer>",
         "client":"<client id>",
         "exp":<unix>}
payload: {"sub":"...","email":"...","name":"...", ...}
```

1. Read `kid` from the JWT header.
2. Fetch the key from
   `https://public-keys.auth.elb.<region>.amazonaws.com/<kid>`.
3. Verify the ES256 signature.
4. **Check `signer` equals your load balancer's ARN.**
5. Take `sub` and `email` from the verified payload.

!!! danger "Skipping the `signer` check is a known, named vulnerability"

    Any AWS customer in the region can create an ALB, point it at their
    own IdP, and obtain a token the regional public key validates. If
    your API accepts any well-signed `x-amzn-oidc-data` without
    comparing `signer` to your own ALB's ARN, an attacker mints their
    own identities. This was published as the "ALBeast" class of
    misconfiguration, and AWS's documentation now states the signer
    check as a requirement, not a suggestion.

Two decoding gotchas: the ALB's JWT segments are base64url **with**
padding characters, which strict decoders reject; and the key endpoint
returns a raw PEM, not a JWKS document.

### Close the back door

The ALB does not isolate anything by itself. Two controls do:

```bash
# 1. The tasks have no public IP and live in private subnets.
NETCFG="awsvpcConfiguration={subnets=[$PRIVATE_A,$PRIVATE_B],\
securityGroups=[$TASK_SG],assignPublicIp=DISABLED}"

aws ecs create-service \
  --cluster chai \
  --service-name chai-api \
  --task-definition chai-api:1 \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "$NETCFG" \
  --load-balancers \
    "targetGroupArn=$TG_ARN,containerName=api,containerPort=8080"

# 2. The task security group accepts :8080 from the ALB's security
#    group only -- reference the group ID, never a CIDR.
aws ec2 authorize-security-group-ingress \
  --group-id "$TASK_SG" \
  --protocol tcp --port 8080 \
  --source-group "$ALB_SG"
```

Referencing `$ALB_SG` rather than a CIDR is what AWS recommends, and it
survives the ALB changing IP addresses. Verify afterwards that the task
security group has no `0.0.0.0/0` rule and no rule sourced from the VPC
CIDR:

```bash
aws ec2 describe-security-groups --group-ids "$TASK_SG" \
  --query 'SecurityGroups[0].IpPermissions'
```

!!! danger "The authenticate action must be the listener default"

    A rule that authenticates `/` while the default action forwards
    everything else leaves `/api/*` wide open to anyone who reaches the
    ALB. Put `authenticate-oidc` on the **default action** of the HTTPS
    listener, ordered before the `forward`, and add exceptions only for
    paths that genuinely must be anonymous. Remember that anything
    inside the VPC can also reach an internal ALB directly.

### Managed PostgreSQL

```bash
aws rds create-db-instance \
  --db-instance-identifier chai-db \
  --engine postgres \
  --engine-version 16.4 \
  --db-instance-class db.t4g.medium \
  --allocated-storage 50 \
  --db-subnet-group-name chai-private \
  --vpc-security-group-ids "$DB_SG" \
  --no-publicly-accessible \
  --storage-encrypted \
  --manage-master-user-password
```

`--manage-master-user-password` has RDS create and rotate the password
in Secrets Manager, so no credential is ever typed on a command line.
Open `$DB_SG` on 5432 to `$TASK_SG` and to nothing else.

### Secrets

Secrets Manager, injected by the ECS agent through the task definition's
`secrets` block, so values never appear in the task definition JSON,
in `describe-task-definition` output, or in the container environment
dump of a crash report:

```json
"secrets": [
  {
    "name": "DATABASE_URL",
    "valueFrom":
      "arn:aws:secretsmanager:<region>:1234:secret:chai/db-url"
  }
]
```

### Identity on the task definition

!!! warning "Set `IDENTITY_MODE` explicitly, or the task reads the wrong header"

    The API's default preset is `proxy`, whose identity header is
    `X-Forwarded-Email` — a header an ALB neither sets nor strips. Leave
    `IDENTITY_MODE` unset and legitimate users get 401, while a request that
    *does* carry `X-Forwarded-Email` is one a client supplied by hand.

```json
"environment": [
  { "name": "IDENTITY_MODE", "value": "alb" },
  { "name": "IDENTITY_AUDIENCE",
    "value":
      "arn:aws:elasticloadbalancing:<region>:1234:loadbalancer/app/chai/a" },
  { "name": "TRUSTED_PROXY_CIDR", "value": "10.0.0.0/16" },
  { "name": "REQUIRE_IDENTITY", "value": "true" }
]
```

`alb` is the one preset whose format is already `jwt`, so it reads
`x-amzn-oidc-data`. An ALB's token has no `aud` claim: it names the load
balancer in the JWT *header's* `signer` field, and that is what
`IDENTITY_AUDIENCE` is compared to. So the value is the **load balancer's** ARN
(`...:loadbalancer/app/NAME/ID`, the `$ALB_ARN` from the setup below), never a
listener's (`...:listener/app/...`), which looks almost the same and can never
match. The API refuses to start on a listener ARN rather than answer 401 to
every request.
Set `TRUSTED_PROXY_CIDR` to the VPC range the load balancer's ENIs sit in,
so the task refuses identity headers arriving from anywhere else.

The OIDC client secret used by the listener rule is a separate concern:
it is stored in the listener configuration itself, so restrict
`elasticloadbalancing:DescribeRules` in your IAM policies.

### Step by step

```bash
REGION=<your-region>   # a data residency decision: see "Data residency"

# 1. ALB in public subnets, with its own security group.
ALB_ARN=$(aws elbv2 create-load-balancer \
  --name chai-alb --type application --scheme internet-facing \
  --subnets "$PUBLIC_A" "$PUBLIC_B" --security-groups "$ALB_SG" \
  --query 'LoadBalancers[0].LoadBalancerArn' --output text)

# 2. IP target group -- awsvpc tasks register by ENI address.
TG_ARN=$(aws elbv2 create-target-group \
  --name chai-tg --protocol HTTP --port 8080 --vpc-id "$VPC_ID" \
  --target-type ip --health-check-path /api/health \
  --query 'TargetGroups[0].TargetGroupArn' --output text)

# 3. HTTPS listener whose DEFAULT action authenticates.
aws elbv2 create-listener \
  --load-balancer-arn "$ALB_ARN" \
  --protocol HTTPS --port 443 \
  --certificates "CertificateArn=$ACM_ARN" \
  --ssl-policy ELBSecurityPolicy-TLS13-1-2-2021-06 \
  --default-actions file://actions.json

# 4. Long-poll friendly idle timeout for /api/events.
aws elbv2 modify-load-balancer-attributes \
  --load-balancer-arn "$ALB_ARN" \
  --attributes Key=idle_timeout.timeout_seconds,Value=4000

# 5. Lock the tasks to the ALB.
aws ec2 authorize-security-group-ingress \
  --group-id "$TASK_SG" --protocol tcp --port 8080 \
  --source-group "$ALB_SG"
```

`actions.json`:

```json
[
  {
    "Type": "authenticate-oidc",
    "Order": 1,
    "AuthenticateOidcConfig": {
      "Issuer": "https://login.microsoftonline.com/<tenant-id>/v2.0",
      "AuthorizationEndpoint": "https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/authorize",
      "TokenEndpoint": "https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token",
      "UserInfoEndpoint": "https://graph.microsoft.com/oidc/userinfo",
      "ClientId": "<client-id>",
      "ClientSecret": "<client-secret>",
      "Scope": "openid email profile",
      "SessionTimeout": 28800,
      "OnUnauthenticatedRequest": "authenticate"
    }
  },
  { "Type": "forward", "Order": 2, "TargetGroupArn": "<tg-arn>" }
]
```

Register `https://<alb-dns-or-cname>/oauth2/idpresponse` as the redirect
URI in the IdP — that path is fixed by the ALB.

!!! note "`OnUnauthenticatedRequest` and single-page apps"

    `authenticate` redirects the browser to the IdP, which is right for
    the initial page load but turns an expired-session `fetch()` into an
    opaque CORS failure. If you split rules by path, use `deny` for
    `/api/*` so the app receives a clean `401` and can reload the shell.

## Azure: Container Apps with Easy Auth and Entra ID

### Architecture

```text
Browser
  |  HTTPS
  v
Container Apps ingress
  |
  v
Easy Auth sidecar (one per replica)  <-- Microsoft Entra ID
  |  adds X-MS-CLIENT-PRINCIPAL
  v
Application container
  |  VNet-integrated
  v
Azure Database for PostgreSQL flexible server (private access)
```

Azure's model differs structurally from the other two. The front door is
not a separate network hop: the authentication middleware runs as a
sidecar container inside every replica, intercepting each request before
it reaches the application container. There is consequently no ingress
path that skips it — which is a real advantage, as long as you never
weaken the sidecar's own configuration.

App Service with Easy Auth behaves identically and uses the same
headers; Container Apps is the better fit here because the workload is a
plain container with no App Service runtime underneath.

### The headers Easy Auth injects

| Header | Contents | Verifiable? |
|---|---|---|
| `X-MS-CLIENT-PRINCIPAL` | Base64-encoded JSON of all claims | No |
| `X-MS-CLIENT-PRINCIPAL-ID` | Caller ID set by the IdP | No |
| `X-MS-CLIENT-PRINCIPAL-NAME` | Human-readable name, usually the UPN | No |
| `X-MS-CLIENT-PRINCIPAL-IDP` | Which provider authenticated the caller | No |
| `X-MS-TOKEN-AAD-ID-TOKEN` | The Entra ID token — requires the token store | **Yes** |
| `X-MS-TOKEN-AAD-ACCESS-TOKEN` | The Entra access token — requires the token store | Yes |

`X-MS-CLIENT-PRINCIPAL` decodes to:

```json
{
  "auth_typ": "aad",
  "claims": [ { "typ": "name", "val": "Dana Okafor" },
              { "typ": "preferred_username", "val": "dana@hospital.org" } ],
  "name_typ": "name",
  "role_typ": "roles"
}
```

Microsoft notes that "external requests aren't allowed to set these
headers, so they're present only if set by App Service" — the platform
strips inbound copies. That guarantee holds only for traffic that
actually traverses the platform ingress.

### Verify the assertion

!!! warning "Easy Auth's identity headers are not signed"

    Unlike IAP and the ALB, Azure gives you base64 JSON, not a JWT. To
    get a verifiable assertion you must **enable the token store** and
    validate `X-MS-TOKEN-AAD-ID-TOKEN` yourself:

    - **Keys**: `https://login.microsoftonline.com/<tenant-id>/discovery/v2.0/keys`
    - **Issuer**: `https://login.microsoftonline.com/<tenant-id>/v2.0`
    - **Audience**: your app registration's client ID — this is the
      check that pins the token to your service.

    If the token header is absent for your flow, the server-side
    fallback is to call the token-store endpoint `/.auth/me` on
    `localhost`, forwarding the inbound request's cookies, and read the
    claims from the JSON it returns. `/.auth/logout` ends the session,
    and `/.auth/login/aad` starts one.

### Close the back door

Because the sidecar is in-replica, the risk is not a network bypass but
a configuration that tells the sidecar to let requests through:

```bash
az containerapp auth update \
  --name chai-api --resource-group chai-rg \
  --enabled true \
  --unauthenticated-client-action Return401 \
  --redirect-provider AzureActiveDirectory \
  --require-https true \
  --token-store true \
  --blob-container-uri "https://chaistore.blob.core.windows.net/tokens"
```

!!! note "Two things about the token store flags"

    `--blob-container-identity` is omitted deliberately. The literal string
    `system` is not an accepted value: the flag takes the *resource ID* of a
    user-assigned managed identity, and leaving it empty is what selects the
    system-assigned identity. Passing `system` fails.

    Both blob flags are Preview, and the whole `containerapp` command group
    needs its extension: run `az extension add --name containerapp` first.

!!! danger "Three settings that reopen the door"

    - `--unauthenticated-client-action AllowAnonymous` passes
      unauthenticated traffic straight to your container with no
      identity headers at all. Use `Return401` for an API, or
      `RedirectToLoginPage` if the same origin also serves the app
      shell. Never `AllowAnonymous`.
    - `--excluded-paths` removes authentication from the paths listed.
      Keep it empty, or limited to `/api/health`.
    - `--require-https false` allows the session cookie over plaintext.
      Keep ingress `allowInsecure` off:
      `az containerapp ingress update -n chai-api -g chai-rg
      --allow-insecure false`.

For defense in depth, take the app off the public internet entirely and
front it with Application Gateway or Front Door:

```bash
LOCATION=<your-location>   # a data residency decision: see "Data residency"

# Internal-only environment: ingress reachable only from the VNet.
az containerapp env create \
  --name chai-env --resource-group chai-rg --location "$LOCATION" \
  --infrastructure-subnet-resource-id "$INFRA_SUBNET_ID" \
  --internal-only true \
  --enable-workload-profiles true

# Or keep a workload-profiles environment public-facing but reachable
# only through a private endpoint.
az containerapp env update \
  --name chai-env --resource-group chai-rg \
  --public-network-access Disabled
```

Private endpoints require a workload-profiles environment and a subnet
of `/27` or larger, and enabling them means disabling public network
access — the two settings are mutually exclusive by design.

### Managed PostgreSQL

```bash
LOCATION=<your-location>   # the same one as above

az postgres flexible-server create \
  --name chai-db --resource-group chai-rg --location "$LOCATION" \
  --version 16 --tier GeneralPurpose --sku-name Standard_D2ds_v5 \
  --vnet chai-vnet --subnet db-subnet \
  --public-access None \
  --active-directory-auth Enabled --password-auth Disabled
```

`--public-access None` with `--vnet` gives the server a private IP and
no public endpoint. `--active-directory-auth Enabled` with
`--password-auth Disabled` lets the container app authenticate to
PostgreSQL with its managed identity, so there is no database password
to store at all.

### Secrets

Key Vault, referenced by the container app's secret collection and
resolved with a managed identity:

```bash
az containerapp secret set \
  --name chai-api --resource-group chai-rg \
  --secrets "db-url=keyvaultref:https://chai-kv.vault.azure.net/secrets/db-url,identityref:system"
```

The Entra client secret for Easy Auth is stored the same way and
referenced by name in the auth configuration.

### Step by step

```bash
RG=chai-rg
APP=chai-api
TENANT=$(az account show --query tenantId -o tsv)

# 1. App registration for the front door.
APP_ID=$(az ad app create \
  --display-name "CHAI governance" \
  --sign-in-audience AzureADMyOrg \
  --query appId -o tsv)

az ad app update --id "$APP_ID" --enable-id-token-issuance true

az ad app update --id "$APP_ID" --web-redirect-uris \
  "https://${APP}.<env>.<location>.azurecontainerapps.io/.auth/login/aad/callback"

SECRET=$(az ad app credential reset --id "$APP_ID" \
  --display-name easyauth --query password -o tsv)

az ad sp create --id "$APP_ID"

# 2. Deploy the container with ingress and a managed identity.
az containerapp create \
  --name "$APP" --resource-group "$RG" --environment chai-env \
  --image "chaiacr.azurecr.io/chai-api:v1" \
  --target-port 8080 --ingress external --transport auto \
  --system-assigned \
  --min-replicas 1 --max-replicas 1 \
  --env-vars IDENTITY_MODE=easyauth \
             IDENTITY_HEADER=X-MS-TOKEN-AAD-ID-TOKEN \
             IDENTITY_HEADER_FORMAT=jwt \
             "IDENTITY_AUDIENCE=$APP_ID" \
             "DATABASE_URL=secretref:db-url"

az containerapp ingress update -n "$APP" -g "$RG" --allow-insecure false

# 3. Wire Entra ID into Easy Auth.
az containerapp auth microsoft update \
  --name "$APP" --resource-group "$RG" \
  --client-id "$APP_ID" --client-secret "$SECRET" \
  --tenant-id "$TENANT" --yes

# 4. Require authentication and turn on the token store.
az containerapp auth update \
  --name "$APP" --resource-group "$RG" \
  --enabled true \
  --unauthenticated-client-action Return401 \
  --redirect-provider AzureActiveDirectory \
  --require-https true \
  --token-store true

# 5. Raise the ingress idle timeout for /api/events (environment-wide,
#    minimum 4 and maximum 30 minutes).
# `update` only edits premium ingress that is already enabled, and `add` is
# what enables it. `add` also requires a workload profile to run on, so
# create one first. This is a chargeable dedicated profile.
az containerapp env workload-profile add \
  --name chai-env --resource-group "$RG" \
  --workload-profile-name ingress-d4 --workload-profile-type D4 \
  --min-nodes 1 --max-nodes 1

az containerapp env premium-ingress add \
  --name chai-env --resource-group "$RG" \
  --workload-profile-name ingress-d4 \
  --request-idle-timeout 30
```

By default any user in the tenant can obtain a token for the
application. Restrict it to the governance group under **Enterprise
applications → Properties → Assignment required**, then assign the
group.

## Header reference

| | Google Cloud | AWS | Azure |
|---|---|---|---|
| Front door | Identity-Aware Proxy | ALB `authenticate-oidc` | Easy Auth sidecar |
| IdP | Workspace / Cloud Identity | Any OIDC IdP, or Cognito | Microsoft Entra ID |
| Signed assertion | `x-goog-iap-jwt-assertion` | `x-amzn-oidc-data` | `X-MS-TOKEN-AAD-ID-TOKEN` |
| Plain identity | `x-goog-authenticated-user-email` | `x-amzn-oidc-identity` | `X-MS-CLIENT-PRINCIPAL-NAME` |
| Signing key source | `www.gstatic.com/iap/verify/public_key-jwk` | `public-keys.auth.elb.<region>.amazonaws.com/<kid>` | Entra JWKS for the tenant |
| Pin-to-service check | `aud` = project/location/service | `signer` = ALB ARN | `aud` = client ID |
| Bypass control | `--no-allow-unauthenticated` + invoker IAM | Task SG sourced from ALB SG | `Return401` + private endpoint |
| Session endpoints | IAP-managed | `/oauth2/idpresponse` | `/.auth/login/aad`, `/.auth/me`, `/.auth/logout` |

## Proving the back door is closed

Do this once per environment, and again after any network change. From
a host that is *not* the front door — your laptop, or a VM in an
unrelated subnet — forge the header and confirm you are refused:

```bash
# Google Cloud: expect 403 from Cloud Run, not 200 from your app.
curl -i https://chai-api-abc123-uc.a.run.app/api/me \
  -H 'X-Goog-Authenticated-User-Email: accounts.google.com:ceo@hospital.org'

# AWS: from an EC2 instance in the VPC but outside the ALB's SG,
# expect a connection timeout, not a response.
curl -i --max-time 5 http://10.0.2.17:8080/api/me \
  -H 'x-amzn-oidc-identity: ceo@hospital.org'

# Azure: expect 401, and no identity echoed back.
curl -i https://chai-api.<env>.<location>.azurecontainerapps.io/api/me \
  -H 'X-MS-CLIENT-PRINCIPAL-NAME: ceo@hospital.org'
```

A `200` with `ceo@hospital.org` in the body means the deployment is
open, every audit-log entry is unreliable, and every checkpoint
sign-off is repudiable. Treat it as an incident, not a to-do.

!!! note "Add this to CI"

    The check is three `curl` calls and a string match. Run it on every
    deploy; a network change six months from now will not announce
    itself.
