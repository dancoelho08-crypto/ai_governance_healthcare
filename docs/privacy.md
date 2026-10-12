# Privacy: what is kept, for how long, and what can be erased

This page is the position a privacy officer or data protection officer (DPO) can
point at. It describes what the server-backed deployment stores about **people**
(the staff who use it), what it does not let anyone remove, what it does, and how
to find one person's data. It is a description of the software, not legal advice,
and it does not say that any use of it complies with GDPR, HIPAA or any other law.
Whether it does is for your organization and counsel.

It applies only to the server-backed deployment. The static dashboard keeps
everything in the visitor's browser and sends nothing anywhere.

## In short

| Question | Answer |
|---|---|
| Whose personal data is in it? | The staff who sign in. Patient data is out of scope in every mode. |
| What is recorded about them? | Their identifier, name and email as the proxy asserted them, when they acted and what they did, and what they read. |
| How long is it kept? | A project's record for the life of the AI solution plus 6 years after it is retired, and the read trail for 6 years, by default. Your records schedule takes precedence. |
| Who disposes of it, and when? | An operator, with `make dispose`, on a schedule your records officer approves. It reports first and changes nothing until told to. |
| Can it be stopped? | Yes. A project's owner can place a litigation hold, with a reason, and the project and its read trail are kept until it is lifted. |
| Can one person's data be found? | Yes: `make subject-access`, and **Search all text** in the dashboard for the projects you can open. |
| Can it be erased? | The *content* can be destroyed. The *fact* that someone acted cannot, because that is what an audit trail is. The details are below. |

## What personal data the server holds

The data subjects are the people who sign in: their identifier (the identity the
proxy asserts, usually an email address), their name and email as the proxy sent
them, when they acted, and what they did.

| Where | What identifies a person |
|---|---|
| `projects` | who created and last changed a project; the access list and the sign-off names inside `doc` |
| `project_log` | who wrote each audit entry, and any name in its text |
| `project_version` | who made each revision; a frozen copy of the whole project and its access list as of that revision |
| `project_deletion` | who deleted a project |
| `access_event` | who read what, and the source address |
| `principals` | the name and email the proxy asserted for each identifier |
| `agent_token` | the owner's identifier, a label they typed, when a token was made, used and revoked, and a hash of its secret ([The agent API](agent-api.md)) |

## What an agent call discloses

A person can mint a token for a program to read, on their behalf, what their own
dashboard shows ([The agent API](agent-api.md)). What a call returns is the stored
statuses, decisions and dates of the projects that person can open, an overdue
comparison, and who may open each project as **opaque ids**: a keyed pseudonym that
names nobody without the key. A project is returned as an opaque reference too,
not by its id or its name, and an item or checkpoint id is returned only if it
is a
word of the framework definitions. No name, no email and no free text is returned
(no note, no rationale, no evidence title, no project name). The projects are the
person's own and archived ones are left out. Every answered call is a row in the
read trail, marked as agent access, with the token's public id and the projects
returned, so it can be answered who read what and by which token; a refusal of a
token
that exists is a row, and a flood of unknown tokens is counted in the security
log without being a row. A token is deleted with the person's `principals` row,
and
a token that has not been revoked still stops working after 8 hours.

**Through the MCP server.** If the operator turns on the optional [MCP
server](mcp.md), a person's chatbot can make these same calls, and the answers
go wherever that chatbot's model runs: on the person's machine, in your cloud
account, or at a model provider. That is a disclosure of the set of your AI
tools and where each stands, as opaque ids, statuses, decisions and dates. It is
not patient data, and it holds no name, email or free text, but it may still be
sensitive to your organization. **Where answers may go is the operator's
decision**, and the MCP page has the checklist: which model, where it runs,
whether the data leaves your network, what its operator keeps, and who can mint
a token. The MCP service itself stores nothing and logs no token or query string,
and the API cannot tell a call through it from a direct one: both are one row in
the read trail, marked as agent access. Turning the MCP service off does not stop
a person using the agent API with their own program; leaving `AGENT_ID_SECRET`
empty does.

Where an answer goes after it leaves this server is **not** this server's decision
and not something it can see. If the program that holds a token sends answers to
a
model run by someone else, that is a disclosure of your governance metadata to that
operator, and whether it is acceptable, under what agreement, is for your
organization and your counsel to decide before a person mints a token. The answers
hold no patient data (patient data is out of scope in every mode), but the list
of
your AI projects and their review status is the kind of thing an organization may
not want to share. A self-hosted model, or one your organization already
approves for
this data, keeps it inside the boundary you have already drawn.

## How long it is kept

The project owner decided these periods (R-54). They are a starting point for
your organization's records retention schedule, which should hold them alongside
its other committee and compliance records, and which takes precedence.

| Record | Kept for |
|---|---|
| A project, its revisions and its audit log | The life of the AI solution, plus 6 years after it is retired |
| The read trail (who opened what) | 6 years, or your audit-log policy if shorter |
| The security event log, in your log system | Your security-log policy (often 1 year readily searchable) |
| Staff names and emails (`principals`) | While the person is active, then as long as a retained record refers to them |
| Backups | 35 days rolling, plus any archive your backup policy keeps |

Why: the record exists to show who reviewed a clinical AI tool and on what
evidence, for as long as anyone could ask, so the clock starts at retirement,
not at creation. Six years follows the practice hospitals already use for
compliance documentation (the HIPAA Security Rule's documentation period, 45 CFR
164.316(b)(2)(i)), and covers most malpractice limitation periods. A litigation
hold suspends any period. If a tool was used on children, ask counsel whether
the limitation periods for minors in your state call for longer. Backups bound
how long an erasure takes to be complete, because a purged value survives in
every older backup until it expires.

### Disposal at the end of the period

`make dispose` lists what is past its period, and changes nothing:

- a retired project whose retirement date and last change are both older than the
  record period. Retired means a checkpoint holds a decision that the project's
  framework ends a project on: in the published build, "Stop" at checkpoint A, B
  or C, or "Retire" at D. A build of another framework retires on its own
  decisions, which the database loads from that build
  ([Self-hosting](self-hosting.md#which-build-it-serves-and-the-retirement-rules));
  a record written before records carried their framework is read as CHAI's;
- the history of a deleted project, counted from its deletion;
- the read-trail rows older than the read-trail period;
- the name and email (`principals`) of anyone who has not signed in for the
  read-trail period and whom no retained record names. Whoever changed a
  retained record stays listed as long as that record is kept.

`make dispose APPLY=1 BY=<your name>` disposes of them, in one transaction.
Disposal is a purge, not a disappearance: the live record is deleted and a
deletion record (who, when, the last hash) is kept, the revisions are emptied and
keep their number, time and hash, and the read-trail rows are deleted. Each run
is recorded with who ran it and what it disposed of. Run it on a schedule your
records officer approves (monthly is typical), and read the report first.

Only the database owner can dispose. The API cannot: its database role has no
right to delete the read trail and cannot run the disposal. Nor can it change
which decisions retire a project: its role may only read those rules. Nor can a
writer choose which framework's rules a record follows: the API accepts a new
record's framework only when it is the primary framework of the build the rules
came from, while that primary is not CHAI it refuses a new record that leaves its
framework out (which would make it CHAI's), and it refuses any change that would
move an existing record to another framework's rules.
The report counts the records whose framework has no retirement rules, which
never come due. The
database refuses to delete a read-trail row younger than the period, even for
the owner, unless the period itself is changed.

The periods are in the `retention_policy` table (6 and 6 years by default). If
your schedule differs, change them as the owner (`make psql`, then
`UPDATE retention_policy SET record_years = 10;`); the change is stamped with
who and when. A record period starts at retirement and is reset by any later
edit, so it can only ever run longer than the date suggests.

**A litigation hold stops disposal.** A project under a hold is listed in the
report and kept, with its read trail, until the hold is lifted. An owner of the
project places or lifts one on its setup page, under **Litigation hold**, and
gives a reason (a matter name or reference). Holds are append-only, each with
who, when and why. The reason is shown only to the project's owners; the
project's history records only that a hold was placed or lifted.

A hold does not stop an owner's manual purge or delete in the dashboard; it
stops the schedule.

A restore can bring back records disposed of after the dump was taken, so
`make restore` ends by printing what is due; run `make dispose APPLY=1` again.

## What can be erased, and what cannot

- **Content can be destroyed.** A revision's content can be purged: its `doc` is
  emptied and the row keeps its number, its author, its time and its original hash.
  An audit entry can be redacted the same way: its text and the value that changed
  are replaced, and the entry keeps who, when and which field. Both record who
  purged and when.
- **The fact of an action cannot.** Who made a revision, who wrote an entry, who
  deleted a project and who read what are rows the database refuses to update or
  delete, and the purge never touches them. That is the point of an audit trail,
  and it is the reason erasure and the trail are in tension.
- **Deleting a project is not erasure.** The history is kept after a delete so
  that the decision can still be reviewed; only a purge destroys content.

A request to erase a person is therefore, in this software, a request to purge
the content that names them and to decide, as a matter of policy, whether the record
of their having acted is kept. GDPR Art. 17(3)(b) allows refusing erasure where
processing is necessary to comply with a legal obligation. Whether a medical-device
governance record qualifies is an argument for your DPO to make with counsel; this
page records only that the software cannot remove the fact of an action without
changing the database by hand, which is a privileged path it exists to avoid.

## Finding one person's data (subject access)

```bash
make subject-access WHO=ceo@hospital.org
```

It reads the running database and reports which tables and columns mention that
identifier, how many rows, and in which projects, plus the person's `principals`
row. It reports locations, not contents: your privacy office decides what is
produced. A match inside a jsonb column is a place to look, not a finding,
since an identifier that is a prefix of another matches both. It changes nothing.

In the dashboard, anyone can do the same for the projects they can open: tick
**Search all text** beside the portfolio search and type a name, an email or a
phrase. Every project whose current text contains it is listed, archived ones
included, with where it was found, and each result opens the project. A
person's name also finds the ids they are stored under (access lists and
sign-offs hold ids). It searches the current version only: earlier revisions
and the audit log are not in the browser, which is what `make subject-access`
is for.

## A restore brings purged content back

A dump taken **before** a purge, restored **afterward**, reinstates every purged
document and redacted entry, because the dump holds their content. So a purge made
for an erasure request could be undone by an ordinary recovery.

`make restore` puts the purges back. Before it overwrites the database it reads
every purge the live database holds into a ledger file in `backups/` (who purged
which project, when, and how far; no content), and after the restore it applies
them again, with their original time and person. Each project's audit log gets a
system entry saying so. Run twice, it changes nothing the second time.

If the live database cannot be read (it is the thing you are recovering from),
`make restore` says that purges will **not** be re-applied, and carries on. The
security log still has every purge (`versions.purged` carries what a re-apply
needs), so rebuild the ledger from it and apply that:

```bash
python3 scripts/purge_ledger.py from-log security.jsonl --out ledger.json
make reapply-purges LEDGER=ledger.json
```

Purge events written before this existed lack those fields; the script counts
them and they have to be re-applied by hand. And old backups still hold erased
content for as long as they exist, which is a retention matter for the backup
copies too.

## Records of processing (GDPR Art. 30)

This tool is itself the kind of thing a hospital inventories. A starting point for
the entry, to be completed and owned by the controller:

| Field | Draft |
|---|---|
| Controller | *your organization* |
| Purpose | Recording the review and sign-off of AI solutions the organization deploys or evaluates |
| Data subjects | Staff who sign in to the governance server |
| Categories of data | Identifier, name, email, the actions they took and when, what they read (and whether through an agent token), source address |
| Recipients | *those you give access to the project; the operators of the database and its backups* |
| Transfers outside the region | *see "Data residency" in [Cloud deployment](deploy.md); a decision for your DPO* |
| Retention | See "How long it is kept" above (R-54); confirm against your records retention schedule |
| Security measures | See [Security claims](security-claims.md) and [Self-hosting](self-hosting.md) |
