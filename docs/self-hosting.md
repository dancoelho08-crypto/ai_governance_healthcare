# Self-hosting

This page is for the people who run the shared workspace: IT, security and
operations. It covers the Docker Compose stack on one host. For a managed
container service on Google Cloud, AWS or Azure, read
[Cloud deployment](deploy.md) as well. The settings that matter most there are
the same ones explained here.

**Governance metadata only.** Never enter patient-identifiable information, in
any storage mode. See [Privacy and retention](privacy.md) for what the server
does hold: personal data about the staff who use it.

## What you run

| Service | What it does |
|---|---|
| `proxy` | The front door, and the only service reachable from outside. It serves the dashboard, forwards `/api`, and owns the identity header |
| `api` | The FastAPI service. It never authenticates anyone: it reads identity from the header the proxy sets |
| `db` | PostgreSQL 17, on a network with no route off the host |
| `migrate` | A one-shot job that applies the schema and creates the restricted database role the API serves as |

What you provide: a host, a sign-in in front of the proxy (single sign-on, or an
authenticating proxy of your own), TLS in front of that, secrets, and backups.

## A first deployment

```bash
make env          # creates .env from the template
$EDITOR .env      # see below
make up           # runs the preflight, then starts the stack
make doctor       # asks the running stack whether it is healthy
make check-isolation   # proves the API cannot be reached except through the proxy
```

`.env` ships deliberately incomplete, and `make up` will say exactly what is
missing and why it matters. Set at least:

| Variable | What to put |
|---|---|
| `POSTGRES_PASSWORD` | The database owner's password: `openssl rand -base64 32`. Any characters work |
| `APP_POSTGRES_PASSWORD` | The restricted role's password: a **different** value, generated the same way |
| `IDENTITY_ID_SOURCE` | Which header your sign-in sets: Google IAP, an AWS load balancer or Azure Easy Auth. See [Identity comes from the proxy](#identity-comes-from-the-proxy) |
| `HTTP_BIND` | `127.0.0.1` unless something in front of the proxy needs to reach it |
| `STORAGE_ENCRYPTION_CONFIRMED` | `1`, once you have encrypted the disk under the data volume (see [Encryption at rest](#encryption-at-rest)). Required when the stack is reachable beyond this machine |

The stack binds to loopback by default, because it speaks plain HTTP and expects
TLS to be terminated in front of it. `make up` refuses to start on unsafe
settings: an empty or placeholder password, a literal identity such as
`dev@localhost`, plain HTTP on a network, or an encryption decision nobody made.

## The commands you will use

| Command | What it does |
|---|---|
| `make up`, `make down`, `make ps`, `make logs` | Start, stop and watch the stack. `down` keeps the data |
| `make doctor` | Diagnoses a stack that is up but not working: passwords, the restricted role, table growth, what sits under the volume |
| `make check-isolation` | Asserts the network isolation the security model rests on |
| `make backup`, `make verify-backup`, `make restore` | Encrypted dumps, a restore test into a throwaway database, and a guarded restore. See [Backups](#backups-make-backup-is-a-tool-not-a-backup-strategy) |
| `make reapply-purges` | Re-applies erasures after a restore ([Privacy and retention](privacy.md#a-restore-brings-purged-content-back)) |
| `make dispose` | Reports records past their retention period; `APPLY=1 BY=<name>` disposes of them ([Privacy and retention](privacy.md#disposal-at-the-end-of-the-period)) |
| `make agent-tokens` | Lists agent tokens, or revokes them: `REVOKE=1 TOKEN=<id>`, `WHO=<user>` or `ALL=1` ([The agent API](agent-api.md#revoking-tokens)) |
| `make subject-access WHO=<id>` | Finds every place one person's identifier is stored |
| `make phi-scan` | Looks for pasted patient identifiers, without ever printing them |
| `make psql`, `make shell` | A database prompt, and a shell in the API container |
| `make prune` | Removes the containers **and the database volume**. Destroys all data |

## The Docker Compose stack

`compose.yaml` in the repository root runs the whole thing on one host: the
proxy, the API, a one-shot migration job and PostgreSQL.

| File | What it is |
|---|---|
| `compose.yaml` | The stack. Production-shaped: no port on the API, none on the database. |
| `compose.dev.yaml` | Opt-in override: fixed dev identity, hot reload, the API on `127.0.0.1`. |
| `proxy/Caddyfile` | Serves the dashboard, proxies `/api`, owns the identity header. |
| `proxy/Dockerfile` | Bakes the Caddyfile and the built dashboard into an image for the clouds. |
| `.env.example` | Every variable, commented. Copy to `.env`; it is git-ignored. |
| `Makefile` | The commands above. |

### Which build it serves, and the retirement rules

The proxy serves the dashboard from `APP_DIR` (default `./docs/app`, the
published build) with the policy in `CSP_FILE` (default `./proxy/csp.caddy`,
generated with it). Leave both unset to run the published build. A build of
another framework is a directory holding its own `index.html` and
`manifest.json`, and its own policy file.

`manifest.json` is written by `pixi run build-app` beside the page. It names each
framework in the build and the checkpoint decisions that end a project. Which
decisions those are is the framework's own definition, not a fixed rule: in the
published build, "Stop" at checkpoint A, B or C, or "Retire" at D. The `migrate`
service reads the manifest beside the page the proxy serves and loads those
decisions into the database, which decides from them when a project is retired
and so when it comes due for disposal ([Privacy and retention](privacy.md#disposal-at-the-end-of-the-period)).

- Nothing about disposal changes silently. When the build adds a decision that
  ends a project, no longer has one the database retires on today, or has a
  different primary framework, `migrate` refuses: it lists the decisions added and
  removed, the change of primary, and every project that would become due, or stop
  being due, for disposal, prints the value to set, and exits non-zero. On a
  first deploy the API waits for `migrate` and does not start. On a redeploy over
  a running stack, `docker compose up -d` can still return 0: the API that is
  already running keeps serving, by the rules the database already holds, while
  a service it recreated for the new build, such as the proxy, is left created
  and not started, so the dashboard is down. After every deploy, run
  `docker compose ps -a` and read `docker compose logs migrate`: a `migrate` that
  exited 3 printed the value. If the change is intended, set `RETIREMENT_RULES_ACK`
  in `.env` to that value and run `docker compose up -d` again; then clear it. If
  it is not, deploy the previous build again (`APP_DIR`, `CSP_FILE`) and run
  `docker compose up -d`. The value
  acknowledges exactly the change you were shown: every rule the database holds
  before and after it, of every framework, and the primary before and after, from
  the database's rules as they stood when it was printed. A different change, even
  one between the same primary rule sets, needs its own value. Once used it is
  spent, so one left set from an earlier deploy accepts nothing later, not even
  the same change again, and an older build deployed over a newer one is refused
  the same way. It also belongs to the database that printed it: it includes the
  cluster's system identifier, the database's internal id (OID) and the internal
  id of the rules' history table, none of which a dump carries, so another
  database refuses it even when its history is the same (a value printed on a
  staging database built separately, or restored from a dump, does nothing on
  production), and so does a copy restored from a dump that creates the tables
  again, into another database or cluster or over the same database in place
  (`make backup` dumps with `--clean`, so `make restore` drops and creates every
  table). A restore of the data alone does not: reloading the rows into the
  tables that are already there (`pg_dump --data-only`, or `TRUNCATE` and reload)
  keeps the history table's OID, so it is the same database to `migrate`, and a
  value spent after the dump was taken is accepted again.
- The value binds the rules and the primary, not the projects. The list is of the
  projects as they stood when it was printed: a project decided or edited before
  you run `migrate` again with the value is affected all the same, without having
  been listed. Use the value promptly; to see the list as it stands, run `migrate`
  without it.
- A copy of the database's files is not a dump. A base backup, point-in-time
  recovery, a volume or disk snapshot, or a promoted replica keeps the cluster's
  identifier and both internal ids, so to `migrate` it is the database it was
  copied from, and it accepts again a value printed against the state it holds.
  Clear `RETIREMENT_RULES_ACK` before you restore one, and read what `migrate`
  prints afterward. The same holds for a staging database made that way: it
  shares production's identity, so a value printed on either, against the state
  both hold, is accepted by the other. If you want staging's values never to work
  on production, build staging from a dump (`pg_dump`, then `pg_restore` or
  `psql`, creating the tables), not from a copy of production's files.
- The database's identity comes from `pg_control_system()`, which PostgreSQL lets
  every role call. On a platform that withholds it, `migrate` cannot bind a value
  to the database, so it refuses every change of the rules and says why; a build
  that changes nothing still starts.
- A build that changes nothing (the same rules and the same primary as the
  database) needs nothing: the published build on a new database starts without
  an acknowledgment.
- A build governs only the frameworks it lists. The rules of a framework it does
  not list, such as the primary of an earlier build, are left in place, so that
  framework's records keep retiring by them, and `migrate` says so.
- A missing or unreadable manifest also stops `migrate`. There is no fallback.

Every change is recorded in the append-only `retirement_rule_change` table (who,
when, the rules before and after) and as a `retirement.rules_changed` security
event. `GET /api/health` reports the rule set in use as `retirement_rules`: its
`hash`, which equals `ruleSetHash` in the manifest of the build that set it, its
`primary` framework, and `synced`, which is `true` when the latest change of the
rules came from a build's manifest. It is `false` while the database holds only
010's seed, and on an API that migrated itself (`RUN_MIGRATIONS=true`) with no
`RETIREMENT_MANIFEST`, whatever an earlier sync recorded, since that API did not
check the rules against its build.

The dashboard checks the same thing. The build writes the manifest's
`ruleSetHash` into the page, and a page served by the API compares it, and its
primary framework, with `retirement_rules`. When they agree it shows nothing.
When they do not, a banner below the header (an alert to screen readers) says
the server retires records by different rules than this page shows, or by
another framework's, and asks for the migrate job to be run with this build's
manifest. Until they agree, the page records no checkpoint decision and creates
no new record; other edits still save (the banner says so only to someone who
may edit the open project). When the rules agree but `synced` is
`false`, the banner says no build's manifest set or confirmed them, and stops
nothing, since the rules the server holds are the page's. The banner cannot be
dismissed: it goes away when the rules are fixed and
the page is reloaded. A server that does not send `retirement_rules`, or sends it
as `null`, gets no banner; any other value that is not an object is taken as a
disagreement. The API sends `null` when it cannot read its rules, and remembers
that for 30 seconds, so a page loaded during a brief database failure shows no
banner until it is reloaded. These are the page's own refusals; the server's are
the checks below.

A record's framework is its `meta.framework.id`, and it decides when the record
can be disposed of. The API accepts a new record that sets it only when it is
exactly `{"id": "<primary>"}`, the primary of the build the rules were loaded
from. A record without one is CHAI's, so while the primary is another framework
the API refuses a new record without the stamp. No change to an existing record
can change its framework: a change that would set, remove or blank the stamp, or
replace `meta`, so that the record follows another framework's rules is refused,
and a change that sets the stamp must name the record's own framework exactly. So
a record written before a change of primary keeps the framework it had, and stays
editable, and a record of a later primary keeps its framework after a rollback.
A build of another framework ([Bring your own framework](frameworks/custom.md))
stamps every record it creates with its primary; the published build stamps
none, so its records are CHAI's. A change of primary waits for every new record
in flight, and a new record that starts during it waits for it, so no record is
checked against a primary that has just been replaced.

### Identity comes from the proxy

The API does not authenticate anybody. The proxy deletes any
`X-Auth-Request-User`, `-Name` or `-Email` the browser sent, then sets them
from a source you configure in `.env`:

```bash
# behind an SSO front door: the header it sets. Pick one.
IDENTITY_ID_SOURCE={http.request.header.X-Goog-Authenticated-User-Id}
IDENTITY_STRIP_PREFIX=accounts.google.com:   # Google IAP only; see below
# IDENTITY_ID_SOURCE={http.request.header.X-Amzn-Oidc-Identity}
# IDENTITY_ID_SOURCE={http.request.header.X-Ms-Client-Principal-Id}
```

Google IAP sends its identity as `accounts.google.com:person@hospital.org`.
`IDENTITY_STRIP_PREFIX` removes that prefix before anything is stored, so an
access list holds `person@hospital.org` however the person arrives. Set it
**before anyone signs in**: `make up` refuses a Google source without it,
because access lists built from prefixed ids stop matching later and every
project then disappears from its owner, with no error anywhere. Every other front
door sends an unprefixed value and needs no prefix.

#### If access lists were already stored with the prefix

If people signed in before the prefix was set, their access lists hold
`accounts.google.com:person@hospital.org`, and once the prefix is set those
entries match nobody: every such project disappears from its owner, and a direct
request answers 404. Count the affected entries, then rewrite them. This edits the
database directly, so the application does not record it: note it in your change
record. History is not touched, because a live project's versions are read against
its current access list, so repairing the project repairs who can read them.

```sql
-- how many access entries still carry the prefix
SELECT count(*) AS prefixed_entries
  FROM projects p,
       LATERAL jsonb_each(COALESCE(p.doc -> 'access', '{}')) AS a(role, list),
       LATERAL jsonb_array_elements_text(
         CASE WHEN jsonb_typeof(a.list) = 'array' THEN a.list ELSE '[]' END
       ) AS e(entry)
 WHERE e.entry LIKE 'accounts.google.com:%';

-- remove it from owners, writers and readers
UPDATE projects p
   SET doc = jsonb_set(p.doc, '{access}', (p.doc -> 'access') || (
         SELECT jsonb_object_agg(r.role, COALESCE((
                  SELECT jsonb_agg(
                           regexp_replace(x, '^accounts\.google\.com:', ''))
                    FROM jsonb_array_elements_text(
                           COALESCE(p.doc -> 'access' -> r.role, '[]')) AS x
                ), '[]'))
           FROM unnest(ARRAY['owners', 'writers', 'readers']) AS r(role)))
 WHERE jsonb_typeof(p.doc -> 'access') = 'object'
   AND (p.doc -> 'access' ->> 'owners'  LIKE '%accounts.google.com:%'
     OR p.doc -> 'access' ->> 'writers' LIKE '%accounts.google.com:%'
     OR p.doc -> 'access' ->> 'readers' LIKE '%accounts.google.com:%');
```

Never put a literal such as `dev@localhost` here. It makes every visitor the
same person, so `make up` refuses to start on it. For local development, run
`make dev`: it supplies a fixed developer identity through `compose.dev.yaml`,
the one place a literal belongs.

Headers the proxy does not own pass through untouched, so an API that prefers
to verify a signed assertion itself — the IAP JWT, `x-amzn-oidc-data`,
`X-MS-CLIENT-PRINCIPAL` — still receives it. See
[Deploying with SSO](deploy.md) for running this on Google Cloud, AWS or Azure.

!!! danger "The API must be unreachable except through the proxy"

    This is not hardening, it is the security model. Anyone who can open a TCP
    connection to the API sets the identity header themselves and becomes
    whoever they like, including signing off a checkpoint in a colleague's
    name.

    `compose.yaml` enforces it with networking rather than with a convention:
    the API publishes no host port, the only network it shares with anything
    internet-facing has the proxy as its sole other member, and Postgres sits
    on an `internal: true` network with no route off the host at all.

    `make check-isolation` asserts all of this against a running stack. Run it
    after any change to the networking, and keep it in whatever runs after a
    deploy. It exits non-zero on a published port on `api` or `db`, on a direct
    connection to the API that succeeds, or on a forged identity header that
    comes back as the identity.

    `compose.dev.yaml` deliberately breaks this by publishing the API on
    `127.0.0.1:8000`. That is why it is a named override rather than
    `compose.override.yaml`, which `docker compose up` would pick up silently.

#### The one route that skips the sign-on

The read-only agent API ([The agent API](agent-api.md)) is **off** until
`AGENT_ID_SECRET` is set. With it set, an agent that holds a token a person minted
reaches three `GET` routes under `/api/agent/` with no single sign-on session. The
Caddyfile gives that path its own block: it forwards exactly those three routes,
deletes every identity header a client sends on them and sets none, and answers
any
other method or path under the prefix with a 404. Every other route is as described
above. If a front door of yours sits in front of Caddy and authenticates every path,
it has to let `/api/agent/` through, or the agent API cannot be used; the page says
how, per front door, and says where it cannot be done.

### How the containers are locked down

The proxy is the only service reachable from outside, so it gets the strictest
treatment: it runs as an unprivileged user (uid 65532), drops every Linux
capability except the one the Caddy binary asks for, and has a read-only root
filesystem. The API drops all capabilities and is read-only too, on top of the
unprivileged user its image already uses. All three services set
`no-new-privileges` and have memory, CPU and process limits (see the resource
limits in `.env.example`).

A small one-shot service, `proxy-perms`, hands the proxy's two named volumes to
that user before it starts, because Docker creates them root-owned and a
non-root Caddy could not otherwise write its certificates. It has no network
and only the two capabilities `chown` needs, and it also covers an upgrade: the
volumes an earlier, root-run proxy populated are fixed on the next `up`.

`docker compose ps` hides it once it has exited; `docker compose ps -a` shows
it with exit code 0. The cloud image (`proxy/Dockerfile`) is unprivileged the
same way. In a cloud, set memory and CPU limits and drop capabilities in the
task or service definition, which is where the platform applies them.

### The data survives `docker compose down`

Postgres writes to the named volume `pgdata`.

```bash
docker compose down        # containers and networks go; pgdata stays
docker compose down -v     # pgdata is destroyed, with no undo
make backup                # pg_dump through the running server -> backups/
```

Back up with `make backup`, not by copying the volume's files: a live cluster
copied file-by-file gives a torn snapshot that may not restore.

`make backup` and `make restore` read the passphrase from the `BACKUP_PASSPHRASE`
environment variable, so `export` it (or have your secret store set it). Do not
write `make backup BACKUP_PASSPHRASE=...`: that puts it in `make`'s own command
line, where any local account can read it. The dump is encrypted with GnuPG
through a temporary file that only you can read, and a failed dump, or a
restore with the wrong passphrase, exits non-zero.

### Backups: `make backup` is a tool, not a backup strategy

`make backup` writes an encrypted dump of a running database. On its own it is not
a backup plan (the practice followed is the HIPAA Security Rule's contingency
plan, 45 CFR 164.308(a)(7)), for three reasons, each of which is a decision you
make.

**1. Nothing schedules it.** Run it from the host's scheduler, for example daily
at 02:30. `BACKUP_PASSPHRASE` must be in that job's environment, from a secret
store, never typed on a command line:

```cron
30 2 * * *  /srv/chai/nightly-backup.sh
```

```sh
#!/bin/sh
# /srv/chai/nightly-backup.sh
cd /srv/chai
export BACKUP_PASSPHRASE="$(cat /etc/chai/backup.pass)"
make backup BACKUP_RETAIN=30
make verify-backup
```

**2. It writes to `backups/` on the same disk as the database.** A copy on the
host it protects does not survive losing the host. Copy each file to storage in
**another account or site**, and keep the passphrase somewhere else again. A
backup in the same account as the thing it protects does not survive that account
being compromised.

**3. Nothing restores from it unless you do.** A backup that has never been
restored is a hypothesis. `make verify-backup` restores the newest dump (or
`FILE=...`) into a throwaway PostgreSQL of the same major version as production,
with no network, and checks that the tables, the rows and the **append-only
triggers** came back, enabled. A dump that restores without them, or with them
switched off, has quietly lost the guarantee the history rests on. It also checks
that the retirement rules it restored are exactly the ones their history last
recorded, so a restore never retires by rules nobody recorded choosing. It exits
non-zero otherwise, so run it after the backup, from the same scheduler. How
long it takes is your real restore time, which is the number to write down.

`make restore` overwrites the live database with a dump, so it asks you to type
`YES` first (`CONFIRM=YES` skips the question for automation). Practice the
restore somewhere that is not production before you need it.

### Encryption at rest

The database lives in the Docker volume `pgdata`, which is an ordinary directory
on the host's disk. **Nothing in this stack encrypts it.** If the disk is not
encrypted, whoever holds the disk (stolen, returned to a vendor, improperly
disposed of) can read every record.

The practice followed is the HIPAA Security Rule's for encryption at rest (45 CFR
164.312(a)(2)(iv)): implement it, or document why an equivalent is reasonable.
Either way it has to be a decision on the record. This stack must not hold patient
data (governance metadata only), so what a lost disk exposes is the review records
and the personal data of the staff named in them, which is reason enough.

To encrypt it, put **Docker's data root** (`/var/lib/docker` by default, which
holds `pgdata`) on an encrypted volume:

- **A host you manage:** LUKS/dm-crypt on the device that holds the data root,
  or an encrypted filesystem, and `data-root` in `/etc/docker/daemon.json` if
  you moved it. Keep the key somewhere other than that host.
- **A cloud VM:** the provider's encrypted disks (encrypted EBS volumes,
  encrypted Persistent Disks, encrypted managed disks), enabled when the disk is
  created. Check the setting on the disk that backs the data root, not on the
  boot disk.

Then set `STORAGE_ENCRYPTION_CONFIRMED=1` in `.env`. **That is you telling the
stack it is done: nothing inside a container can check.** `make up` refuses a
stack that is reachable beyond this machine (a non-loopback `HTTP_BIND`) that
uses its own database volume until you do, so the decision is made by someone,
once, on the record. `make doctor` reports what the host shows under the volume
(a dm-crypt layer, or none, or that it cannot tell); treat "none" as "ask",
because a cloud provider may encrypt below what the host can see.

`make backup` already encrypts every dump with a passphrase of its own (see
above); that is separate from, and does not replace, an encrypted volume.

Not covered: application-level or column-level encryption of the project
documents. It would break the `jsonb` merge, version history and every query,
for a threat the disk-level control already addresses.

### Deleting and destroying data

There are three different things, and they reach different amounts. **Deleting a
project does not erase its history.** That is deliberate: an audit trail that
vanishes with its subject is not one. But it means that deleting is not erasure,
and nothing here should be described to anyone as if it were.

| | Live document | Audit log | Version history |
|---|---|---|---|
| **Edit** a field | corrected | an entry is added | the old revision is kept |
| **Delete** the project | removed | removed with it | **kept**, readable by owners |
| **Destroy history** (a purge) | untouched | content destroyed | content destroyed |

**Delete** (`DELETE /api/projects/{id}`) removes the project and its live audit
log. It writes a permanent tombstone to `project_deletion`: who deleted it, when,
and what its last revision hashed to. The tombstone holds no content.

**Destroy history** (`DELETE /api/projects/{id}/versions`, owners only; in the
app, a choice in the delete dialog) is the separate step that answers "this should
never have been recorded", for example a patient identifier pasted into an
evidence field. A purge destroys the content of every revision **and of every
audit-log entry**, including the prose, which carries the values too. What stays
is who changed what, when, which field, and the fingerprint, so the history shows
that something was written and later destroyed, not a gap. The server records the
purge in the log. It is irreversible.

To remove a value that was entered by mistake: correct the live document, then
destroy the history. To remove a whole record: destroy the history, then delete
the project (the dialog does them in that order, so a failure does not leave you
believing the data is gone). Then check:

```sql
select project_id, deleted_by, deleted_at, last_rev from project_deletion;
select count(*) from project_version where doc::text like '%the-value%';
select count(*) from project_log where entry::text like '%the-value%';
```

**Finding it first.** `make phi-scan` looks for what a pasted patient record
leaves behind: an SSN, and a medical record number, date of birth or patient name
that is labeled as one. It reads the live records, every revision not yet purged
and every audit entry not yet redacted, and reports the project, the field and the
revisions, never the matched text. `make phi-scan STRICT=1` exits non-zero on a
match, for a scheduled job. It does not look for names or dates on their own,
because a governance record is made of them, so a clean run is not a finding that
no patient information is present.

**What none of this reaches.** Backups made earlier still hold the data. `make
restore` re-applies the live database's purges after it restores, and says so
when it cannot; see [Privacy and retention](privacy.md) for rebuilding the purges
from the security log. The identifiers of the people who made changes (`created_by`,
`updated_by`, `changed_by`, `by_id`) are not removed either, for as long as the
records they appear in are kept; that is a separate question from erasing content,
and it has a real tension with keeping an audit trail.

**At the end of the retention period** an operator runs the purge on a schedule:
`make dispose` reports what is past its period, and `APPLY=1` purges it, deletes
the oldest read-trail rows and removes staff names that no retained record
mentions. A litigation hold on a project stops it. See
[Privacy and retention](privacy.md#disposal-at-the-end-of-the-period).

### Two database roles

The audit log and the version history are append-only because of database
triggers, and a table's owner can switch a trigger off with one statement. The
Postgres user `.env` calls `POSTGRES_USER` owns every table (and, in this
image, is a superuser), so an API that connected as it would only be bound by the
triggers as long as the API behaved.

So the API does not. Two roles:

| Role | Password | Held by | Can |
|---|---|---|---|
| owner (`POSTGRES_USER`) | `POSTGRES_PASSWORD` | the one-shot `migrate` service only | everything: create tables, disable triggers |
| restricted (`APP_POSTGRES_USER`, default `chai_app`) | `APP_POSTGRES_PASSWORD` | the `api` service | read and write the project tables; it **cannot** disable or drop a trigger, truncate, alter a table or create one |

`migrate` runs before the API on every `up`: it applies migrations and creates the
restricted role with exactly the grants in `server/app/roles.py`
(`docker compose run --rm migrate python -m app.migrate --print-grants` lists
them). The `api` container is given the restricted role's password and none of the
owner's. Set `APP_POSTGRES_PASSWORD` to a **different** `openssl rand -base64 32`
than `POSTGRES_PASSWORD`; `make up` refuses to start if it is empty, short, a
placeholder or the same.

Rotating `APP_POSTGRES_PASSWORD` is a restart, because `migrate` re-applies it:

```bash
docker compose up -d --force-recreate migrate api
```

`make doctor` checks that the restricted role accepts its password and that the
API reports serving as it. A Postgres superuser still bypasses all of this, which
is why the owner's password is the one to guard, and why it lives only in a job.

### Rotating the database password

`POSTGRES_PASSWORD` is read by PostgreSQL **once**, when it initializes an
empty data directory. On an existing `pgdata` volume it is ignored. Editing it
in `.env` therefore changes what the API presents and not what the database
accepts, and the API can no longer reach its own database:

```text
database not ready: password authentication failed for user "chai"
```

Nothing warns about this, and `make up` cannot: `preflight.py` reads `.env` and
has no running database to ask. It is also the check that sends people here,
because it insists the password be strong and not a placeholder — which is
exactly what makes somebody change it.

So ask the running stack instead:

```bash
make doctor
```

It connects as the API does and tells you whether the password in `.env` is the
one the database accepts. The fix keeps every record:

```bash
docker compose exec db \
  psql -U chai -d chai \
  -c "ALTER ROLE chai WITH PASSWORD 'the value now in .env';"

docker compose up -d --force-recreate api
```

That `psql` has no `-h`, so it goes over the container's Unix socket, which
`pg_hba.conf` trusts — it needs no password, which is what makes the rotation
possible when you have locked yourself out.

!!! note "Why `make doctor` connects to `-h db` and not to localhost"

    `initdb` writes a `pg_hba.conf` that trusts the Unix socket *and*
    loopback; the postgres image appends one `host all all all scram-sha-256`
    line, and only that line asks for a password. A check run as
    `psql -h 127.0.0.1` inside the container matches the loopback **trust**
    rule and succeeds with any password at all. The API connects from another
    container over the bridge, so `-h db` is the only path that tests
    anything.

The other option destroys the database, so reach for it only on a stack with
nothing in it worth keeping:

```bash
make backup      # if there is
make prune       # deletes the volume: records, audit log, every version
```

Managed PostgreSQL has none of this problem, because there is no volume and no
`db` service — rotate with the provider and update `DATABASE_URL`. See
[Deploying with SSO](deploy.md).
