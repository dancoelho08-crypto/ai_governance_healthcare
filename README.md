# AI Governance for Healthcare

**Know which AI is running in your hospital, who approved it, and whether anyone
is still watching.**

A system of record for hospital AI governance. Every AI tool your organization
evaluates or runs is reviewed against the
[Coalition for Health AI (CHAI)](https://chai.org) lifecycle, approved at
go/no-go checkpoints by named people, and brought back for review when it is
due, on one dashboard.

**Governance metadata only.** Never enter patient-identifiable information, in
any storage mode, the self-hosted server included. A governance review has no
need for a patient's data, and the tool is not designed, configured or reviewed
to hold it. It does hold personal data about staff (who reviewed and signed
what); see [docs/privacy.md](docs/privacy.md).

**Live site:** <https://tonyreina.github.io/ai_governance_healthcare/>:
documentation, with a **demonstration** copy of the dashboard at
[`/app/`](https://tonyreina.github.io/ai_governance_healthcare/app/). That copy
stores everything in your browser. It is not a system of record.

## Why this exists

Serious frameworks for governing health AI now exist: CHAI's lifecycle and the
OPTICA adoption checklist from Clalit Health Services, which the WHO Regional
Office for Europe named among four complementary approaches in 2026. But a
framework is a document. It tells a committee what to ask. It does not remember
the answers, assign the follow-up, notice that a review is overdue, or show a
board which tools need attention.

And approval at purchase is the start of governance, not the end: how well a
clinical AI model works depends on your patients and your data, and it can drift
or be changed after the committee has gone home. What a hospital needs is a
review that recurs, and a record that shows it did. That record is what this
builds. It does not claim to make patients safer; no framework has yet been shown
to ([the evidence](docs/frameworks/evidence.md)). It makes governance legible,
attributable and reviewable.

## What you get

- **Portfolio dashboard**: every AI project with its lifecycle position, readiness
  score, next periodic review date, and a status of *Out of compliance*,
  *Needs update*, *On track*, or *Retired*, with the reasons spelled out. The
  status is computed from the record by fixed rules
  ([how](docs/compliance-rules.md)).
- **Lifecycle checklists**: 41 criteria across the six CHAI stages, each tagged
  to one of CHAI's five principles, with status, evidence, owner, and due date.
- **Four go/no-go checkpoints** (after stages 1, 4, 5 and 6) with decision,
  rationale, and a sign-off history attributed to the signed-in person.
- **Applied model card** following the field structure of the CHAI Applied Model
  Card, with a live preview, and a picker for CHAI's recommended metrics.
- **OPTICA adoption review**, optional per project: 77 questions in 13 chapters,
  each marked as answered by your organization, the solution's developer or
  either, never mixed into the CHAI status.
- **An audit trail enforced by the database**: append-only history, a record of
  who read what, retention periods, litigation holds and subject-access tools.
- **Exports**: standalone HTML report, PDF, Markdown, JSON (per project) and CSV
  (portfolio), in the reader's language.
- **Eight languages**: English, Spanish, French, German, Hindi, Russian,
  Simplified Chinese and Hebrew (right to left).

It does not find AI tools, test models, or hold patient data, and it is not a
certification. [Adopting it](docs/adopting.md) sets out what it takes and what to
ask your own organization first.

**Walkthrough:** a [90-second video](https://tonyreina.github.io/ai_governance_healthcare/#see-it-in-action)
of the dashboard on the Docker stack, using sample data. It shows the server-backed
mode, which the browser-only demonstration copy above is not.

## Running it

There are two modes and **they are not equivalent**. Only the deployed stack
enforces access control, keeps an audit log on a server, or produces a
checkpoint sign-off that means anything. The other is the example page.

| | Deployed stack | Example page (GitHub Pages, or a file) |
|---|---|---|
| Storage | PostgreSQL | Browser `localStorage` |
| Shared between people | Yes | **No** |
| Identity | Your hospital SSO | **None** |
| Access control enforced | **Yes, server-side** | **No** |
| Audit log | Yes, append-only | This browser only |
| Version snapshots | **Yes** | No |

See [Running it](docs/running.md) for the full comparison.

### Deploy the shared workspace

This is the mode to use for anything you intend to keep. It runs a Caddy front
door, a FastAPI service and PostgreSQL; sign-in is handled by whatever SSO the
hospital already has, and the API reads identity from the proxy and nowhere
else.

```bash
make env                      # creates .env from the template
$EDITOR .env                  # set the two passwords + IDENTITY_ID_SOURCE
make up                       # refuses to start on unsafe settings
```

`.env` ships deliberately incomplete: `make up` runs
[`scripts/preflight.py`](scripts/preflight.py) first and will tell you exactly
what is missing and why it matters. The stack binds to loopback by default,
because it speaks plain HTTP and expects TLS to be terminated in front of it.

- **[Self-hosting](docs/self-hosting.md)**: the Compose stack, identity, backups,
  encryption, the two database roles, and the commands an operator uses.
- **[Cloud deployment](docs/deploy.md)**: Google Cloud (IAP), AWS (ALB + OIDC)
  and Azure (Easy Auth), each with a *Close the back door* section. Those
  sections are not hardening; they are the deployment. The API trusts an
  identity header, so it must be unreachable except through the proxy.
- **[Privacy and retention](docs/privacy.md)**: what personal data the server
  holds, how long, and how it is disposed of.

```bash
make dev               # local stack: fixed dev identity, hot reload, exposed API
make doctor            # diagnose a stack that is up but not working
make check-isolation   # prove the API is not reachable except through the proxy
make down              # stop. The pgdata volume survives this.
```

### Evaluate it without deploying anything

The dashboard is also a single self-contained file that runs with no server at
all. Everything is stored in that one browser: colleagues cannot see it, there
is no access control, no server-side audit log, and clearing site data deletes
it. The app says so in a standing banner when it is in this mode.

Use it to try the checklists out. **Do not put patient-identifiable
information in it.**

```bash
python3 -m http.server 8000 --directory docs
# then visit http://localhost:8000/app/
```

All persistence goes through one interface, implemented by `ApiStore` (the
deployed stack) and `LocalStore` (the example page). To back the tool
with something else, add a class with the same methods. The app selects one at
boot and **never silently falls back**: if a server was expected and cannot be
reached, it stops and says so. See [Developing it](docs/developing.md#the-store).

## Documentation

The site is built from [`docs/`](docs/) and published at the link above.

| If you are... | Read |
|---|---|
| A CEO, board member or executive sponsor | [Adopting it](docs/adopting.md) |
| On the governance committee | [A review, start to finish](docs/guide.md), and [how statuses are decided](docs/compliance-rules.md) |
| In IT or security | [Self-hosting](docs/self-hosting.md), [Cloud deployment](docs/deploy.md) and the [security claims](docs/security-claims.md), each with the test that enforces it |
| The privacy or records officer | [Privacy and retention](docs/privacy.md) |
| Comparing the frameworks | [The frameworks](docs/frameworks/index.md) and the [crosswalk](docs/crosswalk.md) |
| A developer | [Developing it](docs/developing.md), [the API](server/README.md) and [Python exports](docs/exports.md) |

`REQUIREMENTS.md` records what must stay true of this project and
`DECISIONS.md` why it is built the way it is; [CLAUDE.md](CLAUDE.md) sets the
working rules.

## About CHAI content

This project is independent and is not affiliated with or endorsed by CHAI.
See [NOTICE.md](NOTICE.md).

## Reporting a vulnerability

Please do not open a public issue. See [SECURITY.md](SECURITY.md).

## License

Apache License 2.0, see [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
