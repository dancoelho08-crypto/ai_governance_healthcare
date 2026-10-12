"""Logging: what is written, and what is deliberately not."""

from __future__ import annotations

import logging

# Libraries that log a request's URL or headers. A filter is the most a URL carries
# here, but there is no reason to write it, and a header is where a token is.
QUIET = ("httpx", "httpcore", "hpack")


def quiet_libraries() -> None:
    for name in QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    quiet_libraries()
