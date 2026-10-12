"""``python -m chai_mcp``: run the service. Refuses to start on an unsafe setting."""

from __future__ import annotations

import sys

import uvicorn

from .asgi import create_app
from .config import ConfigError, Settings
from .logs import configure_logging


def main() -> int:
    configure_logging()
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",
        port=settings.port,
        # uvicorn's access log prints the request target, query string included.
        access_log=False,
        server_header=False,
        proxy_headers=False,
        timeout_graceful_shutdown=10,
        timeout_keep_alive=5,
        # More simultaneous connections than this are answered 503, not held.
        limit_concurrency=256,
        log_config=None,
        # Its own lines are reduced to nothing by the log filter anyway.
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
