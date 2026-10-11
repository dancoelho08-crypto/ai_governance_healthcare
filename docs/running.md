# Running it

The dashboard runs in two places, and **they are not equivalent**. Pick by
what you need, not by what is easiest to open.

## Which mode does what

| | Example page (GitHub Pages, or open a file) | Docker stack |
|---|---|---|
| Storage | Browser `localStorage` | PostgreSQL |
| Shared between people | **No** | Yes |
| Survives clearing site data | **No** | Yes |
| Signed-in identity | **None** | Yes, from your SSO |
| Access control enforced | **No** | **Yes, server-side** |
| Checkpoint sign-off means something | **No, self-asserted** | Yes |
| Patient-identifiable information | **Never** | **Never** |
| Version snapshots | No | **Yes** |
| Who read what is recorded | No | **Yes** |
| Retention, disposal and litigation holds | No | **Yes** |
| Live updates between people | No | Yes |
| Both checklists, model card, metrics | Yes | Yes |
| All exports, including PDF | Yes | Yes |
| Changelog | Yes, this browser | Yes |
| Record fingerprint | Yes | Yes |

Whichever mode you are in, the header names it: *This browser only* or *Shared
workspace*, and a warning under it says what that mode does and does not do. The
app never silently falls back from one to another. If it expected a server and
cannot reach one, it stops and says so.

!!! danger "The published site is a demonstration, not a system of record"

    <https://tonyreina.github.io/ai_governance_healthcare/app/> stores
    everything in **your browser**. Nobody else can see it, it does not survive
    clearing site data, and there is no signed-in user, so a checkpoint
    sign-off there records a name nobody checked.

    It is the right way to evaluate the tool. It is the wrong way to keep a
    governance record. For that, run the stack below.

## Try it with no setup

Open the [demonstration](app/index.html), then **Load sample projects**. You get
ten example AI tools, one per CHAI use case, at different points in the
lifecycle, so you can see what *Out of compliance* and *Needs update* look like
and open a tool to follow it through
[a review](guide.md). Nothing leaves your browser.

To run the same page from a copy of the repository, with no server:

```bash
python3 -m http.server 8000 --directory docs
# then visit http://localhost:8000/app/
```

The page tells you it is in browser-only mode. **Do not put patient-identifiable
information in it.**

## The shared workspace, on your machine

This is the full system: PostgreSQL, the API with access control enforced, a
proxy that supplies identity, and the dashboard served from the same origin so
it finds the API on its own. You need Docker.

```bash
git clone https://github.com/tonyreina/ai_governance_healthcare
cd ai_governance_healthcare

make dev          # leave it running; Ctrl-C stops it
```

Then open <http://localhost:8080>. `make dev` creates `.env` from the template if
there is none, and supplies a development password and a fixed developer
identity, so there is nothing to fill in. The header should say
**Shared workspace**. If it says *This browser only*, the API is not answering;
run `make doctor` in another terminal, or look at `make logs`.

When a save does not go through, the page says which kind of problem it is. If
the server cannot be reached or is failing (a dropped connection, a 5xx, a 408 or
a 429), it keeps your edit and retries six times, backing off, then tells you to
check your connection. If the server is up and *refuses* the change (a 4xx other
than those, such as a 422 for a value it will not accept), it does not retry,
because the same change would be refused again. It keeps your edit in the field,
shows the server's reason, and marks the project *Not saved: change refused*, so
you can correct the value. Losing access (401, 403) and a deleted project (404)
are reported as before.

!!! warning "The development stack mints one fixed identity"

    Locally the proxy sets a single development identity for every request, so
    everything you do is the same person. That is enough to exercise ownership
    and the audit trail. To see two people with different roles you need a real
    identity provider in front, as in
    [Cloud deployment](deploy.md), or the
    [self-hosted stack](self-hosting.md) behind your own sign-in.

`make dev` is a named override rather than `compose.override.yaml`, so a plain
`docker compose up` can never pick it up by accident. It also publishes the API
on `127.0.0.1:8000` and reloads it as you edit, which is exactly what the
production stack refuses to do. Never use it anywhere a real person's name could
end up in an audit log. The database is not published at all; reach it with
`make psql`.

To run the production-shaped stack (`make up`), which refuses to start on unsafe
settings and expects real sign-in, see [Self-hosting](self-hosting.md).

### What to try

These work only in the shared workspace:

- **Access control.** Open a project, go to *Project setup*, and find *Access*.
  You are the owner because you created it. Grant someone else write or read
  access and watch the controls change for them.
- **Version history.** Make a few edits, then read the project's revisions
  through the API:

    ```bash
    curl -s localhost:8080/api/projects/<id>/versions | python -m json.tool
    ```

    Every revision, with its fingerprint, who made it and when.
- **Live updates.** Open the dashboard in two windows and change something in
  one. The other updates without a refresh.
- **Identity cannot be forged.** The proxy strips any identity header the
  client sends and sets its own:

    ```bash
    curl -H "X-Auth-Request-Email: ceo@hospital.example" localhost:8080/api/me
    # still answers with the proxy's identity, not yours
    ```

- **A litigation hold and the retention report.** On a project's setup page, an
  owner sees *Litigation hold*. From a terminal, `make dispose` reports what is
  past its retention period and changes nothing. See
  [Privacy and retention](privacy.md).

## Stopping, and cleaning up

```bash
make down       # stop; the database volume survives
make prune      # stop and DELETE the database volume (all records)
```

## When something is up but not working

```bash
make doctor     # asks the running stack what is wrong
```

It checks the things that fail quietly: whether the password in `.env` is the
one the database accepts, whether the API is serving as its restricted database
role, how large the append-only tables have grown, and what sits under the data
volume. The most common trap is changing `POSTGRES_PASSWORD` after the first
start. PostgreSQL reads it only when it initializes an empty data directory, so
editing `.env` changes what the API presents and not what the database accepts.
See [Rotating the database password](self-hosting.md#rotating-the-database-password):
the fix keeps every record.

## Running the tests

The suites that prove all of this, and how to run them, are in
[Developing it](developing.md#running-the-tests).
