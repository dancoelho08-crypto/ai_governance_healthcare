# The agent API

<!-- rumdl-disable MD013 MD036 -->
<!-- The contract tables and the curl commands are single long lines that cannot be wrapped. -->

A read-only way for a program acting for one person, an assistant that answers
questions about your AI portfolio, say, to read what the governance records
*say*, through a token that person mints for themselves. This page is the
contract: what it returns, what it will never return, how a token works, the
exact HTTP of every endpoint, and what an operator does to switch it on.

The agent API is **off** until an operator sets `AGENT_ID_SECRET`. Nothing
described here exists on a server where it is not set.

## What it is, and what it is not

| It is | It is not |
|---|---|
| Read-only. Three `GET` routes under `/api/agent/`, and nothing that writes. | A way to change a record, an access list or a sign-off. No write route exists, and the proxy refuses any other method on the path. |
| The stored values: each answered item's status and due date, each checkpoint's decision and its date, who set it, who may open the project. | A verdict. No phase, no flag, no score, no color, no "on track" or "out of compliance". Those are the dashboard's computations, and the dashboard is where they are shown. |
| The same projects the token's owner's own dashboard shows. | A wider view. Nothing archived, nothing the owner cannot open, and never emergency access, whoever minted the token. |
| People and projects as **opaque ids** (`u_` and `pr_`, then 32 hex characters). | A directory, or a list of names. No name and no email appears in any response, and a project is a reference, not its name. |
| Structured values only: ids and words of the framework definitions, dates, and the opaque ids. | A source of text. No note, no rationale, no evidence or reference title, no committee name, no free-text owner and no project name. A record's own keys (a project id, an item or checkpoint key) are chosen by whoever wrote it, so none is returned unless it is a word of the framework definitions; the project itself is returned as a reference. |
| One comparison with the calendar: `overdue` is true when a stored due date is before today (UTC). | A schedule. It does not know whether an item is settled. |

An answer is a record of what someone registered, with who and when where the
record stores them. It is not a statement that a project is safe, approved or
compliant, and an agent that reports it as one is wrong.

## The threat model, in plain words

- **A token is a password for 8 hours.** Whoever holds it can read what its
  owner's dashboard shows, from anywhere the agent path is reachable. It cannot
  write, and it cannot mint, list or revoke tokens (those routes take the
  person's signed-in session and nothing else).
- **A token reaches one route family.** It is accepted under `/api/agent/` and
  on no other route. On every other route it is not read at all.
- **The identity header means nothing on the agent routes.** The API does not
  read any identity header there, whatever its name, so a client cannot choose
  who it is by sending one. As defense in depth the proxy also deletes the
  sixteen header names it knows (the canonical `X-Auth-Request-*` set and what
  Google IAP, the AWS ALB, Azure Easy Auth and oauth2-proxy set). That list is
  fixed: a header with another name, or a custom `IDENTITY_HEADER`, reaches the
  API and is ignored there.
- **A stolen token is bounded, not harmless.** It stops working at the eighth
  hour on its own. Its owner can revoke it now, and an operator can revoke it
  without them. Every call it makes is in the read trail, marked as agent access,
  with the token's id, and a call a rate limit turns away is counted in the
  security log instead ([what a call leaves behind](#what-a-call-leaves-behind)).
- **A wrong token learns almost nothing.** Missing, malformed, unknown, expired,
  revoked and removed are the same answer: the same status, the same body, the
  same header. The one exception is a source that has already failed too often in
  the window: it is answered `429` instead, whatever it sent. Which it was is in
  the read trail, for the operator, and nowhere else. A token's public id is not a
  secret, and whether an id exists can be told apart by how long the answer takes
  (an existing id with a wrong secret is a little slower, because it may write a
  row). That is not claimed to be hidden: the secret is what protects a token.
- **A flood of wrong tokens costs nothing that lasts.** The token is checked
  before anything is limited, with one read and no write. A bad token is never a
  row unless it names a token that exists, and then rows are bounded per token id
  across every source (10 wrong secrets a minute, 5 for a right secret on a token
  that stopped working, 5 for a project that is not visible) and overall (100 of
  each kind a minute); what is not written is counted in one security-log line a
  window. A source that has failed too often is answered `429` with no write, and
  so is everyone once the failures of all sources together pass a global budget,
  without any per-source accounting, so rotating sources cannot make the server
  work or log more. A working token is never counted against a source or a budget
  and is never refused for them, and nobody can use up another token's allowance
  by naming it.
- **The server cannot leak what it never copies.** Each response is built field by
  field from an allowlist of stored keys. A new field in the stored record
  reaches no agent until someone adds it, in a reviewed change. A key a writer
  chose (an item id, a checkpoint id, a supplement id) is returned only if it is a
  word of the framework definitions the server was built with; a project is
  returned as an opaque reference. So an agent can say "project `pr_...` has
  criterion `s1-3` marked `notmet`", and cannot say what the project is called.
  Names, if they ever arrive, will be an explicit opt-in that labels them as
  untrusted text, and are not in this version.
- **What you send to a model is your decision.** Whatever reads these answers
  may be a model running somewhere. The answers hold governance metadata and
  opaque ids, never patient data (patient data is out of scope everywhere in this
  tool), but the set of projects and their statuses may still be sensitive to
  your organization. Where an answer goes is for the operator to decide;
  [Privacy](privacy.md) says what each call discloses.
- **Removal from your identity provider is not seen.** The app does not read your
  directory, so it cannot learn that someone left. What it can bound is the
  token: 8 hours. See [what removes a token](#what-removes-a-token).

## How a token works

**Mint.** A signed-in person asks the app for a token, any role, for themselves
only. The response holds the token once.

**Shape.** `agt_`, 16 hex characters (the token's public id), a `.`, and 43
characters of URL-safe base64 (256 random bits). The public id is not a secret: it
is in the read trail and the logs, and it shows up in the answer time of a wrong
secret. Only the public id is ever logged by this server, and only a SHA-256 hash
of the whole token is stored, so the server cannot show a token again.

**Where a token may be sent.** In the `Authorization` header and nowhere else: one in
a query parameter, a cookie or another header is refused. Never send it in a URL, or
in a header with any other name. This stack tries to keep it out of its logs if it is
sent anyway, and cannot do so completely:

- The API's access log drops the query string of a request whose decoded path is
  under `/api/agent/`. The proxy's log drops the query string of any request whose
  target is, or might be, an agent route (it contains `agent` in any case, a
  percent-encoded character before the `?`, an absolute-form target, or an empty
  or dot path segment), and the values of `X-Api-Key`, `Api-Key`, `X-Auth-Token`,
  `X-Authorization` and `X-Access-Token` (a fixed list of header names; Caddy
  itself redacts `Authorization` and `Cookie`).
- **A token in a URL path** (`/api/agent/<token>`) is logged by both: it is the
  client's mistake, and nothing here can redact it. A header with another name is
  logged by the proxy. Your front door, load balancer or the client's own logs may
  record any of these.

**Lifetime.** Exactly 8 hours from the moment it is minted, and the database
refuses any other lifetime. It cannot be extended: mint another.

**At most 5 live tokens per person.** A sixth is refused with `409` until one
expires or is revoked. (An operator can change the number with
`AGENT_MAX_ACTIVE_TOKENS`.)

**Store it like a password.** In the agent's secret store or an environment
variable, never in a file that is committed, a chat or a ticket. It lasts
8 hours, so prefer minting a fresh one over keeping one. A token is in the
`Authorization` header of every call; use HTTPS, which the front door provides,
so it is not readable in transit.

**Revoke.** The owner revokes a token with `DELETE /api/agent-tokens/{id}`, and
it stops working on its next call. An operator can revoke one, a person's, or
everyone's with `make agent-tokens` ([below](#revoking-tokens)).

### What removes a token

| What | Effect |
|---|---|
| The 8 hours pass | The token stops working. |
| Its owner revokes it | It stops working on its next call. |
| An operator revokes it | The same. |
| The owner's *principal* is erased from this app | Their tokens are deleted with it. A principal is erased by `make dispose` when the person has not signed in for the read-trail period and no retained record names them ([Privacy](privacy.md)), or by an operator's SQL. |
| The owner's access to a project is removed | The project drops out of what the token sees on its next call. Access is checked on every call. |
| The owner is removed from your **identity provider** | **Nothing happens in this app.** The app does not see your directory. The token keeps working until it expires (at most 8 hours) or an operator revokes it. If someone leaves in a hurry, revoke their tokens: `make agent-tokens REVOKE=1 WHO=<their id>`. |

### Creating, seeing and revoking tokens: the Agent access page

A signed-in person creates and ends their own tokens on the **Agent access** page
of the dashboard (the button is on the portfolio, next to *New project*). It
explains what a token lets a program do, has a field for an optional label, and
lists your tokens with when each was made, when it expires and when it was last
used. It is open to every role: a token reads only what you can already see.

- **Create a token.** The token appears once, in a panel with a Copy button. The
  page shows the token once and the browser keeps it nowhere: not in storage, the
  address or the history. Press *I have copied it* when it is in your secret store,
  and the page forgets it. Leaving the page, changing the language or closing it
  does the same, so copy it before you do any of those.
- **The label** is a name for your own list. The label is shown to you only, as
  text, and an agent is never shown it.
- **Revoke.** Revoke asks first, sends one request, and the list shows the token as
  revoked. It stops working on its next call. (An operator can revoke too:
  [below](#revoking-tokens).)
- **Limits** are the ones above: 8 hours, at most 5 live tokens (a sixth is refused
  with a message that says so), and a rate limit on the token routes.
- **Not on every deployment.** The page is offered only when the dashboard is served
  by the app's server; the browser-only copy has no server to create a token. And on
  a server where `AGENT_ID_SECRET` is not set the page says that agent access is off,
  because the token routes answer `404` (nothing in `/api/health` says so).

### Minting through the API

The token routes use the signed-in session, exactly as the dashboard does, so a
script calls them from a browser tab where you are signed in, or from a command line
that carries the same identity (the local development stack has a fixed one). The
page above is the way to do it by hand; this is for a script. From the browser
console of the signed-in dashboard:

```js
await (await fetch("/api/agent-tokens", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({label: "my assistant"}),
})).json()
```

Whatever runs this holds the token the same way: in its secret store, not in a log.

### `POST /api/agent-tokens`

Mints a token for the signed-in person. Session identity only.

**Request body**

| Field | Type | Meaning |
|---|---|---|
| `label` | string, optional | A name for your own list, up to 64 letters, digits, spaces and `. _ ( ) -`, starting with a letter or digit. It is never shown to an agent. |

**Response fields**

| Field | Type | Meaning |
|---|---|---|
| `id` | string | The token's public id (16 hex characters). Safe to log. |
| `token` | string | The token. **Shown this once.** |
| `label` | string | The label you gave it. |
| `created_at` | string | When it was minted, UTC (ISO 8601). |
| `expires_at` | string | Exactly 8 hours after `created_at`. |

**Status codes**

| Code | Meaning |
|---|---|
| `201` | Minted. The response is `Cache-Control: no-store`. |
| `401` | No identity: the request did not come through the front door. |
| `403` | Not a signed-in person (identity is not enforced), a cross-site request, or not through the proxy. |
| `404` | The agent API is not enabled on this server. |
| `409` | You already hold the most live tokens allowed. |
| `422` | The label is not valid, or the body has a field it should not. |
| `429` | Too many requests. |

```bash
curl -sS -X POST "$BASE/api/agent-tokens" -H "Content-Type: application/json" -d '{"label": "my assistant"}'
```

### `GET /api/agent-tokens`

Your own tokens, newest first (at most 50): ids, labels and dates, never a secret.

**Response fields**

| Field | Type | Meaning |
|---|---|---|
| `id` | string | The token's public id. |
| `label` | string | Its label. |
| `created_at` | string | When it was minted. |
| `expires_at` | string | When it stops working. |
| `revoked_at` | string or null | When it was revoked, or null. |
| `last_used_at` | string or null | The last call that used it, or null. |
| `state` | string | `active`, `expired` or `revoked`. |

**Status codes**

| Code | Meaning |
|---|---|
| `200` | Your tokens (an empty list if none). |
| `401` | No identity. |
| `403` | Not through the proxy. |
| `404` | The agent API is not enabled. |
| `429` | Too many requests. |

```bash
curl -sS "$BASE/api/agent-tokens"
```

### `DELETE /api/agent-tokens/{token_id}`

Revokes one of your own tokens. Revoking one already revoked is not an error.

**Status codes**

| Code | Meaning |
|---|---|
| `204` | Revoked. |
| `401` | No identity. |
| `403` | Cross-site, or not through the proxy. |
| `404` | You hold no such token (another person's counts as none), or the agent API is not enabled. |
| `422` | The id is not 16 hex characters. |
| `429` | Too many requests. |

```bash
curl -sS -X DELETE "$BASE/api/agent-tokens/$TOKEN_ID"
```

## Calling the agent API

Every call carries the token as a bearer credential and **no identity header**:

```bash
curl -sS "$BASE/api/agent/me" -H "Authorization: Bearer $TOKEN"
```

All responses are JSON and are sent with `Cache-Control: no-store`. A request that
carries an identity header beside the token is still a token request: the header is
ignored. A request with only an identity header is a `401`.

### Which projects

The projects the token's owner's own dashboard lists, with archived ones taken
out. That is the same list, from the same code, as `GET /api/projects` gives
that person: a project they own, write or read, and a project with no owner yet
(which every signed-in person can open, as the dashboard shows it). A project
whose record follows another framework than the server's build knows is returned
with a null `framework` and no items or checkpoints; one of a framework of the
build carries its `framework` id, and can be filtered by it. An agent never has emergency access,
whoever minted its token, and a project the owner loses access to leaves what
the token sees on the next call.

### Today, and "overdue"

`as_of` is today's date in **UTC**, from the server's clock. An item is `overdue`
when its stored due date is **before** `as_of`: a due date of yesterday is
overdue, today's is not. A due date that is not a real `YYYY-MM-DD` date is
treated as none. The comparison does not look at the status, so an item that
is settled and has an old due date reads `true`; the status is in the same
object. The dashboard counts overdue differently (it looks at the status, and
at the viewer's local date), so do not expect the two to agree.

### Values you can be given

A project is a **reference**, `pr_` and 32 hex characters (HMAC-SHA256 under
`AGENT_ID_SECRET`, stable in a deployment). Its own id is chosen by whoever created
it and can be anything, a patient's name included, so it is never returned and cannot
be used to ask for it: `GET /api/agent/projects/{ref}` finds the reference among
the projects the token's owner's dashboard shows, and an unknown, an invisible and an
archived project all answer the same `404`.

An item id, a checkpoint id, a supplement's id, a status and a decision are returned
only if they are words of the framework definitions the server's build carries: the
build writes them into `manifest.json`, the migrate job loads them into the database,
and the API checks each against the framework the record follows (a supplement's
answers against the supplement's own; a document key equal to the primary's id is not
a supplement). Anything else a record holds under those keys is returned as `null` or
left out, free text included: no pattern can tell a name from an id, a list of the ids
can. With no manifest loaded, an agent is shown no item, checkpoint or status at all.
People are `u_` and 32 hex characters.

The manifest is **trusted build output**: it carries the same authority as the
framework definitions it is built from, and a poisoned one could put text in front of
agents. The migrate job reads it with a shape and safety filter, not a judgment of
content: each word is 1 to 64 characters with no control, zero-width, bidirectional,
surrogate or private-use character and no surrounding space (spaces inside are fine,
as in `Proceed with conditions`); no kind lists more than 5,000 words and the manifest
no more than 50,000; and a repeated JSON key is an error. A manifest that fails is
refused before the job changes anything.

### `GET /api/agent/me`

Whose token this is.

**Response fields**

| Field | Type | Meaning |
|---|---|---|
| `user` | string | The token's owner, as an opaque id. |
| `token_id` | string | This token's public id. |
| `expires_at` | string | When this token stops working (UTC). |
| `as_of` | string | Today's date in UTC (`YYYY-MM-DD`). |

**Status codes**

| Code | Meaning |
|---|---|
| `200` | The token is valid. |
| `401` | No token, or one that is wrong, expired or revoked. |
| `403` | The request did not come through the authenticating proxy. |
| `404` | The agent API is not enabled on this server. |
| `429` | Too many requests for this token. |

Example response:

```json
{
  "user": "u_4f1c0a7b2e9d4c3a8b6f5e1d0c9b8a7f",
  "token_id": "7d3f9a1c5b2e4f60",
  "expires_at": "2026-10-10T20:00:00Z",
  "as_of": "2026-10-10"
}
```

### `GET /api/agent/portfolio`

The projects, with the stored fields of each, filtered and paged.

**Query parameters**

| Parameter | Type | Meaning |
|---|---|---|
| `status` | string | Only projects with an item (primary or supplement) in this status. Up to 64 letters, digits, spaces and `, & / + . _ -`. |
| `decision` | string | Only projects with a checkpoint holding this decision. Same shape. |
| `overdue` | boolean | `true`: has an overdue item. `false`: has none. |
| `overdue_since` | date | Only projects with an overdue item whose due date is on or after this date (`YYYY-MM-DD`). |
| `overdue_before` | date | Only projects with an overdue item whose due date is before this date. |
| `owner` | string | Only projects this person owns, by opaque id (`u_` and 32 hex), as an earlier call returned it. |
| `framework` | string | Only projects whose record follows this framework id (`chai` for the published build's). |
| `limit` | integer | Page size, 1 to 100. Default 50. |
| `offset` | integer | Where the page starts, 0 to 100000. Default 0. |

Filters combine with *and*. Results are ordered newest change first, then by id,
the order the dashboard uses.

**Response fields**

| Field | Type | Meaning |
|---|---|---|
| `as_of` | string | Today's date in UTC. |
| `total` | integer | Projects matching the filters, before paging. |
| `limit` | integer | The page size used. |
| `offset` | integer | The offset used. |
| `next_offset` | integer or null | The offset of the next page, or null on the last. |
| `projects` | array | The projects on this page, each as below. |
| `projects[].ref` | string | An opaque reference to the project (`pr_` and 32 hex characters). Its own id is never returned. |
| `projects[].framework` | string or null | The framework the record follows: its stamp, or `chai` when it has none. Null if the stored value is not an id. |
| `projects[].updated_at` | string | When the record last changed (UTC). |
| `projects[].updated_by` | string or null | Who changed it last, as an opaque id. |
| `projects[].people` | object | Who may open the project. |
| `projects[].people.owners` | array of strings | Opaque ids of its owners. |
| `projects[].people.writers` | array of strings | Opaque ids of its writers. |
| `projects[].people.readers` | array of strings | Opaque ids of its readers. |
| `projects[].people.truncated` | boolean | True when a list was cut at 100 ids. |
| `projects[].items` | array | The answered items: those with a stored status or due date. |
| `projects[].items[].id` | string | The item's id in its framework's definition. |
| `projects[].items[].status` | string or null | The stored status. Null when none, or not a known word. |
| `projects[].items[].due` | string or null | The stored due date (`YYYY-MM-DD`), or null. |
| `projects[].items[].overdue` | boolean | The stored due date is before `as_of`. |
| `projects[].items_truncated` | boolean | True when more than 500 items were stored. |
| `projects[].gates` | array | The checkpoints with a stored decision, date or sign-off. |
| `projects[].gates[].id` | string | The checkpoint's id in the framework's definition. |
| `projects[].gates[].decision` | string or null | The stored decision. |
| `projects[].gates[].decided_on` | string or null | The stored decision date (`YYYY-MM-DD`). |
| `projects[].gates[].signed_by` | string or null | Who the server recorded as setting the decision, as an opaque id, where stored. |
| `projects[].gates[].signed_at` | string or null | When the server recorded it (UTC), where stored. |
| `projects[].supplements` | array | A supplementary framework's answers on the same project (OPTICA's, for one). |
| `projects[].supplements[].framework` | string | The supplement's framework id. |
| `projects[].supplements[].enabled` | boolean | Whether the project uses it. |
| `projects[].supplements[].items` | array | Its answered items. |
| `projects[].supplements[].items[].id` | string | The item's id in the supplement's definition. |
| `projects[].supplements[].items[].status` | string or null | The stored status. |
| `projects[].supplements[].items[].due` | string or null | The stored due date. |
| `projects[].supplements[].items[].overdue` | boolean | The stored due date is before `as_of`. |
| `projects[].has_overdue` | boolean | True when any item above, a supplement's included, is overdue. |

**Status codes**

| Code | Meaning |
|---|---|
| `200` | The page (empty when nothing matches). |
| `401` | No token, or one that is wrong, expired or revoked. |
| `403` | The request did not come through the authenticating proxy. |
| `404` | The agent API is not enabled on this server. |
| `422` | A parameter is not valid: an unknown shape, a date that is not a date, a `limit` or `offset` out of range. |
| `429` | Too many requests for this token. |

Example response:

```json
{
  "as_of": "2026-10-10",
  "total": 1,
  "limit": 50,
  "offset": 0,
  "next_offset": null,
  "projects": [
    {
      "ref": "pr_0b7a41c96d2e4f58a3c1e9d70b64f2a8",
      "framework": "chai",
      "updated_at": "2026-10-09T15:12:44.031Z",
      "updated_by": "u_4f1c0a7b2e9d4c3a8b6f5e1d0c9b8a7f",
      "people": {
        "owners": ["u_4f1c0a7b2e9d4c3a8b6f5e1d0c9b8a7f"],
        "writers": [],
        "readers": ["u_91a0c3d57e2b46f8a1d9b0c4e7f23a65"],
        "truncated": false
      },
      "items": [
        {"id": "s1-1", "status": "met", "due": null, "overdue": false},
        {"id": "s4-2", "status": "partial", "due": "2026-09-30", "overdue": true}
      ],
      "items_truncated": false,
      "gates": [
        {
          "id": "A",
          "decision": "Proceed with conditions",
          "decided_on": "2026-08-01",
          "signed_by": "u_4f1c0a7b2e9d4c3a8b6f5e1d0c9b8a7f",
          "signed_at": "2026-08-02T10:00:00Z"
        }
      ],
      "supplements": [],
      "has_overdue": true
    }
  ]
}
```

Page through a long result with `next_offset`: ask again with `offset` set to it,
until it is `null`.

```bash
curl -sS "$BASE/api/agent/portfolio" -H "Authorization: Bearer $TOKEN"
curl -sS "$BASE/api/agent/portfolio?status=notmet&overdue=true&limit=20" -H "Authorization: Bearer $TOKEN"
curl -sS "$BASE/api/agent/portfolio?decision=Proceed&framework=chai&limit=2&offset=2" -H "Authorization: Bearer $TOKEN"
curl -sS "$BASE/api/agent/portfolio?overdue_since=2026-09-01&overdue_before=2026-10-01" -H "Authorization: Bearer $TOKEN"
curl -sS "$BASE/api/agent/portfolio?owner=$OWNER_ID" -H "Authorization: Bearer $TOKEN"
```

### `GET /api/agent/projects/{ref}`

One project, by the reference the portfolio gave, with the same fields as an element of `projects` above.

**Response fields**

| Field | Type | Meaning |
|---|---|---|
| `ref` | string | An opaque reference to the project. Its own id is never returned. |
| `framework` | string or null | The framework the record follows. |
| `updated_at` | string | When the record last changed (UTC). |
| `updated_by` | string or null | Who changed it last, as an opaque id. |
| `people` | object | Who may open the project. |
| `people.owners` | array of strings | Opaque ids of its owners. |
| `people.writers` | array of strings | Opaque ids of its writers. |
| `people.readers` | array of strings | Opaque ids of its readers. |
| `people.truncated` | boolean | True when a list was cut at 100 ids. |
| `items` | array | The answered items. |
| `items[].id` | string | The item's id. |
| `items[].status` | string or null | The stored status. |
| `items[].due` | string or null | The stored due date. |
| `items[].overdue` | boolean | The stored due date is before today (UTC). |
| `items_truncated` | boolean | True when more than 500 items were stored. |
| `gates` | array | The checkpoints with a stored decision, date or sign-off. |
| `gates[].id` | string | The checkpoint's id. |
| `gates[].decision` | string or null | The stored decision. |
| `gates[].decided_on` | string or null | The stored decision date. |
| `gates[].signed_by` | string or null | Who the server recorded as setting it, as an opaque id. |
| `gates[].signed_at` | string or null | When the server recorded it. |
| `supplements` | array | A supplementary framework's answers. |
| `supplements[].framework` | string | The supplement's framework id. |
| `supplements[].enabled` | boolean | Whether the project uses it. |
| `supplements[].items` | array | Its answered items. |
| `supplements[].items[].id` | string | The item's id in the supplement's definition. |
| `supplements[].items[].status` | string or null | The stored status. |
| `supplements[].items[].due` | string or null | The stored due date. |
| `supplements[].items[].overdue` | boolean | The stored due date is before today (UTC). |
| `has_overdue` | boolean | True when any item is overdue. |

**Status codes**

| Code | Meaning |
|---|---|
| `200` | The project. |
| `401` | No token, or one that is wrong, expired or revoked. |
| `403` | The request did not come through the authenticating proxy. |
| `404` | No such project, or not one this token's owner's dashboard shows. The answer is the same for a project that does not exist, one that is archived and one the owner may not open. |
| `422` | The reference is not `pr_` and 32 hex characters. |
| `429` | Too many requests for this token. |

```bash
curl -sS "$BASE/api/agent/projects/$PROJECT_REF" -H "Authorization: Bearer $TOKEN"
```

### Errors

An error is JSON with a `detail`. The one for a bad token is always exactly this,
with the header `WWW-Authenticate: Bearer`, whatever was wrong with the token:

```json
{"detail": "Invalid or expired token."}
```

A `429` carries `Retry-After` (seconds) and no other rate-limit header. The `422` of
a bad parameter is a list naming the parameter, in FastAPI's usual shape.

### The rate limit

The token is checked first, and only then is anything limited.

- **A working token** may make 60 calls per 60 seconds
  (`AGENT_RATE_LIMIT_MAX_REQUESTS`), lower than the limit a person at the dashboard
  has (240). Only a call whose token verified spends it, so one agent cannot spend
  another's, and nobody can spend a token's allowance by naming its public id.
- **A person's tokens** share 120 calls per window
  (`AGENT_USER_RATE_LIMIT_MAX_REQUESTS`), so five tokens do not multiply what a
  person's calls cost the server.
- **A failed call** (a token that is missing, wrong, expired or revoked) is counted
  against its source, up to 30 per window (`AGENT_FAILURE_RATE_LIMIT_MAX_REQUESTS`).
  After that the rest are answered `429` with nothing written, which is also what
  a bad token from such a source is told instead of `401`. All sources together
  may fail 600 times per window (`AGENT_GLOBAL_FAILURE_RATE_LIMIT_MAX_REQUESTS`);
  past that every failure is answered `429` with no per-source accounting at all.
  A token that works is never counted against its source or the global budget and
  never refused for them: a flood from an address does not lock out an agent behind
  the same address.
- **The source** is the socket peer. The address the proxy reports in `X-Real-IP` is
  believed only when `TRUSTED_PROXY_CIDR` is set and the peer is inside it, that is,
  when the peer is the proxy; the compose stack sets it. With no range set, every
  caller behind the proxy is one source, which limits them together and cannot be
  rotated by a client. It is always an IP address or `unknown`, never text a client
  sent, and the image starts uvicorn with `--no-proxy-headers`, whose default would
  let a loopback peer set it from `X-Forwarded-For`.

A `429` carries `Retry-After` (seconds) and no other rate-limit header. A working
token that is over its own or its person's allowance is logged once per window as
`ratelimit.tripped` (`key` `agent:` and the token's public id, or `agent-user:` and
the person's id). The tallies hold at most 10,000 sources and 10,000 token ids, drop
the oldest idle ones first, and cost the same for every failure. The limiters live in
each replica, so behind several the ceilings are that many times the settings.

## What a call leaves behind

Not every call is a row, because the read trail is append-only and an unauthenticated
caller must not be able to grow it:

| The call | The trail | The security log |
|---|---|---|
| Answered (`200`) | One row, in the same transaction as the answer, so an answer that cannot be recorded is not given. | `record.read`, with `via` set to `agent` |
| A project the owner's dashboard does not show (`404`) | One row (`agent_refused`, reason `not_visible`), at most 5 per token a window and 100 overall | `agent.refused`, for each row |
| A token that exists, expired or revoked, presented with its right secret (`401`) | One row (`agent_refused`), at most 5 per token id a window and 100 overall | `agent.refused`, for each row |
| A token that exists, presented with a wrong secret (`401`) | One row (`agent_refused`), at most 10 per token id a window across all sources and 100 overall | `agent.refused`, for each row |
| A token that is malformed, or names no token (`401`) | **No row** | Counted in the summary line |
| Over a failure limit, the global budget, or a token's or person's allowance (`429`) | **No row** | Counted in the summary line, or `ratelimit.tripped` once per window |

The three kinds of refusal have budgets of their own, so a flood of wrong secrets (which
anybody who has seen a public id can send) cannot starve the record of a stopped
token's real holder. What is not written is counted in the summary: one
`agent.failures` line per window, written by a background task every half window (and
at shutdown), with the failures, the sources that went over their limit, how many were
answered by the global budget, the sources dropped to stay within the cap, the top
sources with their counts, and how many rows were not written, by kind.

The row is marked as agent access and carries the token's public id, never its secret:

| Column | An agent call |
|---|---|
| `via` | `agent` (a session read is `session`). |
| `actor` | The token's owner's identity id. For a refusal whose secret did not match, `unknown`. |
| `token_id` | The token's public id, or the one the caller presented. |
| `action` | `agent_me`, `agent_portfolio`, `agent_project`, or `agent_refused`. |
| `project_id` | For one project that was returned, its real id (the trail is the operator's); null for a refusal. |
| `detail` | The route; for a portfolio the ids returned, the count, the total and the filters; for a refusal the reason (`unknown` for a wrong secret, `revoked`, `expired`, or `not_visible`, with the `ref` asked for), which the caller is never told. |

What did an agent read? For one person's tokens in a period:

```sql
SELECT at, token_id, action, project_id, detail
  FROM access_event
 WHERE via = 'agent'
   AND actor = 'person@hospital.org'
   AND at >= '2026-01-01' AND at < '2026-02-01'
 ORDER BY at;
```

Which calls were refused, and why, from whom:

```sql
SELECT at, source_ip, token_id, detail ->> 'reason' AS reason, detail ->> 'route' AS route
  FROM access_event
 WHERE via = 'agent' AND action = 'agent_refused'
 ORDER BY at DESC LIMIT 100;
```

A refusal whose `detail` has `"identity_header_ignored": true` carried an identity
header, which the agent routes ignore: a proxy that works strips it, so seeing one
means the request did not come through the agent route of the proxy.

The security events are `agent_token.minted`, `agent_token.revoked`, `agent.refused`,
`agent.failures` (the summary of a window, above) and, for a successful
call, `record.read` with `via` set to `agent`
([the list](deploy.md#security-events-collecting-retaining-and-alerting)).

## For the operator

### Turn it on

1. Set `AGENT_ID_SECRET` to a long random value: `openssl rand -hex 32`. The
   server refuses to start on one shorter than 32 characters, with fewer than
   10 different ones, or made of one short pattern repeated. That is a filter
   for the obvious mistakes and **not a strength test**: a dictionary phrase of
   32 letters passes, so generate the value, do not compose it. It keys the
   opaque ids and is not stored in the database; keep it like a password. Changing
   it changes every id an agent is shown, and loses nothing.
2. Apply the migration. `013_agent_tokens.sql` runs with the others
   (`python -m app.migrate`, compose's `migrate` service, or `RUN_MIGRATIONS=true`).
   It creates `agent_token` and marks the read trail, and `014_agent_vocabulary.sql`
   creates `agent_vocabulary`, which the migrate job fills from the build's
   `manifest.json` (`RETIREMENT_MANIFEST`) on every run, replacing its rows. No
   manifest, no words: an agent is then shown no item or checkpoint. Nothing else is
   stored until a person mints a token.
3. Let the agent path through your front door ([below](#let-the-path-through-your-front-door)).
4. Restart the API.

| Setting | Default | Meaning |
|---|---|---|
| `AGENT_ID_SECRET` | empty (the API is off) | At least 32 characters, at least 10 different, not a repeated pattern. Keys the opaque ids of people and projects. |
| `AGENT_RATE_LIMIT_MAX_REQUESTS` | `60` | Calls per token per `RATE_LIMIT_WINDOW_SECONDS`. |
| `AGENT_FAILURE_RATE_LIMIT_MAX_REQUESTS` | `30` | Failed calls one source may make per window before the rest are answered `429`. |
| `AGENT_GLOBAL_FAILURE_RATE_LIMIT_MAX_REQUESTS` | `600` | Failed calls all sources together may make per window before every failure is answered `429` with no per-source accounting. |
| `AGENT_USER_RATE_LIMIT_MAX_REQUESTS` | `120` | Calls per window all of one person's tokens share. |
| `AGENT_MAX_ACTIVE_TOKENS` | `5` | Live tokens one person may hold. |

### Let the path through your front door

An agent has no single sign-on session, so its requests must reach the API's
agent routes **without** your front door asking them to sign in. Only the
three `GET` routes under `/api/agent/` need this: the token routes
(`/api/agent-tokens`) are a person's, and stay behind sign-on.

The proxy in this repository does its half: `proxy/Caddyfile` forwards exactly
the three agent `GET` routes, deletes sixteen known identity header names on
them as defense in depth and sets none (the API reads no identity header on these
routes in any case), answers anything else under the prefix with `404`, keeps the
query string of these routes out of its log, and leaves every other route as it
was. What it cannot do is open a front door that
sits in front of it. The rest depends on what that is:

| Front door | What to do | Can it? |
|---|---|---|
| This repository's compose stack, or self-hosting with Caddy as the only front door | Nothing: the route is in `proxy/Caddyfile`. | Yes. Tested against a real Caddy. |
| AWS Application Load Balancer with `authenticate-oidc` | Add a listener rule that forwards `/api/agent/*` with no authenticate action, at a higher priority (a lower number) than the rule that authenticates. | Yes, by the ALB's own rule model. Not tested here. |
| Azure Easy Auth (App Service or Container Apps) | List the path as excluded from authentication (`globalValidation.excludedPaths`), so that `/api/agent/*` is served without a sign-in. | Yes, where your platform version supports excluded paths. Not tested here. |
| oauth2-proxy, or an nginx `auth_request` | Skip authentication for the path: oauth2-proxy's `skip_auth_routes` (`GET=^/api/agent/`), or `auth_request off;` in the nginx `location /api/agent/`. | Yes. Not tested here. |
| Keycloak with a gatekeeper or an API gateway | Exempt the path from the gateway's authentication, as the gateway documents. | Depends on the gateway. Not tested here. |
| Google Cloud IAP | IAP protects a whole backend service, with no path exemption inside it. Route `/api/agent/*`, in the load balancer's URL map, to a second backend for the same service with IAP off. | Only with that extra backend. Not tested here. |
| **Any front door that authenticates every path and cannot be told otherwise** | There is nothing to configure. Run the agent from inside the network, calling the proxy directly, or give the agent path its own hostname that the front door does not guard. | **No.** The agent API cannot be offered through such a door, and should stay off. |

Two cautions apply to every row. First, the path is now reachable by anything
that can reach the front door, so the token is the only thing between a caller
and the data: serve it over HTTPS, keep the rate limit, and watch the refusals
([below](#what-to-monitor)). Second, only the agent path: a path exemption that
is broader than `/api/agent/` opens the dashboard's API to anyone.

The API enforces what the proxy cannot. A request that arrives on an agent route
with an identity header and no token is a `401`, and a token with no identity
header on any other route is a `401` too.

### Revoking tokens

The app has no administrator role, so ending someone's token is an operator
action, like `make dispose`: it connects as the database owner.

```bash
make agent-tokens                                  # list live tokens
make agent-tokens WHO=person@hospital.org          # one person's
make agent-tokens REVOKE=1 TOKEN=7d3f9a1c5b2e4f60  # one token, by its public id
make agent-tokens REVOKE=1 WHO=person@hospital.org # all of one person's
make agent-tokens REVOKE=1 ALL=1                   # everyone's
```

A revoked token stops working on its next call. The row stays, with who and when,
marked as revoked by the operator, until the person's principal is erased. Revoke
everyone's after `make restore`, because a backup can hold a token that was
revoked after the dump was taken (tokens last 8 hours, so a backup older than
that holds only expired ones).

### What to monitor

- `agent.failures` lines with a large `failures`, `limited_sources` or
  `global_limited`: a guesser, or an agent with a dead token in a loop. The line
  lists the top `source`s with their counts. A burst of `agent.refused` events (each
  one a read-trail row) for one token id is somebody who knows that id; the row says
  `unknown` for a wrong secret and names the person for a token that matched and had
  stopped working. `rows_not_written` says how many rows the budgets turned away.
- `ratelimit.tripped` with a `key` that begins `agent:` or `agent-user:`: a working
  token or a person over an allowance, an agent in a loop.
- `agent_token.minted` from a person who does not use agents.
- A person's tokens when they leave: the app does not see your directory.

### Troubleshooting

| You see | It means |
|---|---|
| `401` with `Invalid or expired token.` | The token is missing, malformed, wrong, expired (8 hours), revoked or its owner is gone. Mint a new one. The server will not say which. |
| `401` on the token routes (`/api/agent-tokens`) | The request has no signed-in session. A token is not accepted there; use the session. |
| `404` on every `/api/agent/` route | The agent API is off (`AGENT_ID_SECRET` is empty), or the proxy is refusing a method or path the agent routes do not have. |
| `403` | The request did not come through the proxy (`TRUSTED_PROXY_CIDR`, `PROXY_SHARED_SECRET`). |
| `409` when minting | You hold the most live tokens allowed. Revoke one. |
| `422` on the portfolio | A parameter has the wrong shape. The error names it. |
| `429` | Too many calls: wait the `Retry-After` seconds. |
| A project you can open is missing | It is archived, or you do not own, write or read it, and it has an owner. |
| A status or decision is `null` | It was not set, or is not one of the known words. |
| The same person has a different id | `AGENT_ID_SECRET` changed. |
| The front door asks the agent to sign in | The agent path is not let through. See [the table above](#let-the-path-through-your-front-door). |

## Claims, and what backs them

Each security sentence on this page is a row in [Security claims](security-claims.md),
with the test that fails if it stops being true: what a token may reach, that it
cannot mint, list or revoke, that the identity header is ignored, that every bad
token is one answer, that no name, email or free text is returned, that an agent
sees what the owner's dashboard shows and never an archived project, that every
call is in the read trail, and that a token dies with its principal.
