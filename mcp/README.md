# The MCP service

A read-only [MCP](https://modelcontextprotocol.io/) server over the governance
dashboard's [agent API](../docs/agent-api.md): three tools (`whoami`,
`list_portfolio`, `get_project`), one for each of the agent API's three `GET`
routes. **Optional, and off by default**: it is a compose profile
(`docker compose --profile agent-mcp up -d`), not part of a plain `up`.

What it is for, what it returns and never will, how to switch it on, how a person
gets a token and a client connects, and the decision it puts in the operator's
hands (sending answers to a model) are in [the MCP page](../docs/mcp.md). Read that
first. This file is for someone changing the code.

## What the code guarantees

- **No credential of its own.** Each request's `Authorization` header is read from
  that request, forwarded to the agent API for that one call, and dropped. It is
  not
  a setting, a field, a cache key, a log argument or an error message
  (`chai_mcp/upstream.py`). The service is stateless: no session survives a request.
- **Only three routes.** `chai_mcp.upstream.Route` has exactly the three agent
  routes, all `GET`. A tool takes a validated project reference, filters that are
  words, dates and numbers, and never a URL or a path. A redirect is never followed.
- **Only the allowlisted tools.** `chai_mcp.server.ToolName` is the list. The tests
  fail on a tool, a resource or a prompt that is not on it.
- **Answers are checked again.** Every response is parsed into `chai_mcp.models`,
  which forbid unknown fields and hold every string to the shape of a vocabulary
  word, an opaque id or a date. A response that does not fit is refused whole.
- **A failure is a fixed message** (`chai_mcp.upstream.Message`), never the
  upstream's body and never the token.
- **Host and Origin are validated** (DNS rebinding), a query string is refused,
  only
  `POST /mcp` is served, and the body, the time and the calls in flight are bounded
  (`chai_mcp/asgi.py`, `chai_mcp/server.py`).

## Layout

| Path | What |
|---|---|
| `chai_mcp/config.py` | Settings from the environment. None is a secret. |
| `chai_mcp/models.py` | The tool results, mirroring the API's response models. |
| `chai_mcp/upstream.py` | The one hop to the agent API, and the error messages. |
| `chai_mcp/server.py` | The FastMCP server and its three tools. |
| `chai_mcp/asgi.py` | The HTTP front: path, method, Host, Origin, bearer, query. |
| `Dockerfile`, `requirements.txt` | The image, built like the API's: two stages, a lock verified by hash, digest-pinned bases, non-root, no pip. |
| `tests/` | See below. |

## Tests

```bash
pip install -e "../server[dev]" -e ".[dev]"
cd mcp && pytest
```

`TEST_DATABASE_URL` points at a PostgreSQL the tests may `TRUNCATE`. Without it
the
database tests skip; `REQUIRE_TESTS=1` (CI) turns a skip into a failure.

| File | What it shows |
|---|---|
| `tests/test_mcp_service.py` | The real service and the SDK's own client against a recording stand-in for the API: the tools, what is forwarded, every failure's message, Host and Origin, limits, statelessness, and that the token is in no log. |
| `tests/test_mcp_integration.py` | The same, in front of the **real** agent API on a real PostgreSQL: documented results from real records, hostile text planted in a record never reaching a model, a wrong token being one message, two callers never mixing. |
| `tests/test_mcp_process.py` | `python -m chai_mcp` as the container runs it: refusing an unsafe setting, and its output holding no token. |
| `tests/test_mcp_contract.py` | The models are the API's response models, field for field. |
| `tests/test_mcp_docs.py` | `docs/mcp.md` against the service's own schemas, and its curl examples run against the real chain. |
| `tests/test_mcp_mutations.py` | Every guard broken in a copy of the service and noticed. |

The proxy's `/mcp` route and the gate are tested against a real Caddy in
`tests/test_proxy_identity.py` and `tests/test_proxy_mcp_mutations.py`, the compose
profile in `tests/test_compose_isolation.py`, and the whole thing in the real stack
in `tests/test_stack_mcp.py`.

## Changing the dependencies

`requirements.txt` is the lock the image installs from, verified by hash.
Regenerate it with `make lock-mcp` and review the diff: a changed hash is a changed
dependency. The SDK is pinned to the 1.x line in `pyproject.toml`.
