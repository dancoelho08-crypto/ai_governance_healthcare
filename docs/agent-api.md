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
| People as **opaque ids** (`u_` and 32 hex characters). | A directory. No name and no email appears in any response. |
| Structured values only. | A source of text. No note, no rationale, no evidence or reference title, no committee name, and no free-text owner: the text people type never reaches an agent. |
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
- **The identity header means nothing on the agent routes.** The front door's
  header is ignored there, and the proxy strips it, so a client cannot choose
  who it is by sending one.
- **A stolen token is bounded, not harmless.** It stops working at the eighth
  hour on its own. Its owner can revoke it now, and an operator can revoke it
  without them. Every call it makes is in the read trail, marked as agent access,
  with the token's id; the calls the rate limit turns away are in the security
  log instead.
- **A wrong token learns nothing.** Missing, malformed, unknown, expired, revoked
  and removed are the same answer: the same status, the same body, the same
  header. Which it was is in the read trail, for the operator, and nowhere else.
- **The server cannot leak what it never copies.** Each response is built field by
  field from an allowlist of stored keys. A new field in the stored record
  reaches no agent until someone adds it, in a reviewed change.
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
characters of URL-safe base64 (256 random bits). Only the public id is ever
logged, and only a SHA-256 hash of the whole token is stored, so the server
cannot show a token again.

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

### Minting through the API

The token routes use the signed-in session, exactly as the dashboard does, so
they are called from a browser tab where you are signed in, or from a command line
that carries the same identity (the local development stack has a fixed one). A
page in the dashboard for minting, listing and revoking is planned; until it
exists, from the browser console of the signed-in dashboard:

```js
await (await fetch("/api/agent-tokens", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({label: "my assistant"}),
})).json()
```

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
whose record follows another framework than the server's is returned with its
`framework` id, and can be filtered by it. An agent never has emergency access,
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

A status or a decision is one of the words in the framework definitions the server
knows: the statuses `met`, `partial`, `notmet`, `na`, `declined`, `done`, `started`,
`todo`, `skip` and the checkpoint decisions of the published and example
frameworks. Anything else that is stored, free text included, is returned as
`null`. An operator who builds their own framework adds its words with
`AGENT_EXTRA_VALUES`. Item ids and checkpoint ids are returned only when they look
like an id (letters, digits, `-` and `_`).

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
| `projects[].id` | string | The project id. |
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
      "id": "p1k2m3n4o5",
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

### `GET /api/agent/projects/{project_id}`

One project, with the same fields as an element of `projects` above.

**Response fields**

| Field | Type | Meaning |
|---|---|---|
| `id` | string | The project id. |
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
| `422` | The project id is not valid. |
| `429` | Too many requests for this token. |

```bash
curl -sS "$BASE/api/agent/projects/$PROJECT_ID" -H "Authorization: Bearer $TOKEN"
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

Each token may make 60 calls per 60 seconds (`AGENT_RATE_LIMIT_MAX_REQUESTS`), lower
than the limit a person at the dashboard has (240). The limit is per token, so one
agent cannot spend another's; calls with a token that cannot be read are counted
against the address they came from. A refused call (a `429`) is in the security
log, once per client per window, and not in the read trail. The limiter lives in
each replica, so behind several the ceiling is that many times the setting.

## What a call leaves behind

Every call, answered or refused, writes one row to the read trail (`access_event`)
and the same fact to the security log. An answered call's row is written in the
same transaction as the answer, so an answer that cannot be recorded is not given.
The row is marked as agent access and carries the token's public id, never its secret:

| Column | An agent call |
|---|---|
| `via` | `agent` (a session read is `session`). |
| `actor` | The token's owner's identity id. For a call whose token was not valid and so named nobody, `unknown`. |
| `token_id` | The token's public id, or the one the caller presented. |
| `action` | `agent_me`, `agent_portfolio`, `agent_project`, or `agent_refused`. |
| `project_id` | For one project, and for a refused project. |
| `detail` | The route; for a portfolio the ids returned, the count, the total and the filters; for a refusal the reason (`malformed`, `unknown`, `revoked`, `expired`, or `not_visible` for a project the owner's dashboard does not show), which the caller is never told. |

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

The security events are `agent_token.minted`, `agent_token.revoked`, `agent.refused`
and, for a successful call, `record.read` with `via` set to `agent`
([the list](deploy.md#security-events-collecting-retaining-and-alerting)).

## For the operator

### Turn it on

1. Set `AGENT_ID_SECRET` to a long random value: `openssl rand -base64 48`. It
   keys the opaque ids and is not stored in the database; keep it like a
   password. Changing it changes every id an agent is shown, and loses nothing.
2. Apply the migration. `013_agent_tokens.sql` runs with the others
   (`python -m app.migrate`, compose's `migrate` service, or `RUN_MIGRATIONS=true`).
   It creates `agent_token` and marks the read trail. Nothing is stored in a
   table until a person mints a token.
3. Let the agent path through your front door ([below](#let-the-path-through-your-front-door)).
4. Restart the API.

| Setting | Default | Meaning |
|---|---|---|
| `AGENT_ID_SECRET` | empty (the API is off) | At least 32 characters. Keys the opaque ids. |
| `AGENT_RATE_LIMIT_MAX_REQUESTS` | `60` | Calls per token per `RATE_LIMIT_WINDOW_SECONDS`. |
| `AGENT_MAX_ACTIVE_TOKENS` | `5` | Live tokens one person may hold. |
| `AGENT_EXTRA_VALUES` | empty | Comma-separated status and decision words of your own framework build. |

### Let the path through your front door

An agent has no single sign-on session, so its requests must reach the API's
agent routes **without** your front door asking them to sign in. Only the
three `GET` routes under `/api/agent/` need this: the token routes
(`/api/agent-tokens`) are a person's, and stay behind sign-on.

The proxy in this repository does its half: `proxy/Caddyfile` forwards exactly
the three agent `GET` routes, strips every identity header a client sends on
them and sets none, answers anything else under the prefix with `404`, and
leaves every other route as it was. What it cannot do is open a front door that
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

- `agent.refused` events in bursts from one `source_ip`: a guesser. The row in
  the read trail says `unknown` for a token that matched nothing and names the
  person for one that matched and had stopped working.
- `ratelimit.tripped` with a `key` that begins `agent`: an agent in a loop, or
  a guesser.
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
