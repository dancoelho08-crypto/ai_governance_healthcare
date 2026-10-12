"""Logging: what is written, and what is deliberately not (M2).

A client controls the text of its request, and every library that handles it may log
what it received: a validation error quotes the input, a traceback quotes a frame, a
method name or a tool name arrives in a message. So this service does not trust any
logger but its own:

* Only the ``chai.mcp`` loggers may carry text of their own, and they log a method,
  a path (cut short) and a status, an exception CLASS, and fixed words.
* Every other logger (the SDK, uvicorn, pydantic, asyncio, httpx) is at WARNING, and
  a record from one is reduced to its logger, its level and the class of its exception.
  Its message, its arguments and its traceback are never written.
* Every line is one JSON object, so a newline or a control character in a value cannot
  start a line of its own, and no record is longer than ``MAX_RECORD``.
* A burst is bounded: past ``BURST`` records, only ``RATE`` a second are written, and
  the number dropped is said once the burst is over.
"""

from __future__ import annotations

import json
import logging
import sys
import time

# Libraries that log a request's URL or headers. At WARNING, and reduced besides.
QUIET = ("httpx", "httpcore", "hpack")
OWN = "chai.mcp"
MAX_RECORD = 300
MAX_FIELD = 120
BURST = 50
RATE = 10.0


def quiet_libraries() -> None:
    for name in QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)


def _own(name: str) -> bool:
    return name == OWN or name.startswith(OWN + ".")


class Reduce(logging.Filter):
    """Reduce a record from a logger that is not ours to what is safe to say of it."""

    def filter(self, record: logging.LogRecord) -> bool:
        text = record.getMessage() if _own(record.name) else "(details withheld)"
        error = record.exc_info[0].__name__ if record.exc_info else None
        record.msg, record.args = text, None
        record.exc_info = record.exc_text = None
        record.stack_info = None
        record.error_class = error  # type: ignore[attr-defined]
        return True


class Bound(logging.Filter):
    """A token bucket: a burst, then a steady rate, and a note of what was lost."""

    def __init__(self, burst: int = BURST, rate: float = RATE) -> None:
        super().__init__()
        self._burst, self._rate = float(burst), rate
        self._tokens = float(burst)
        self._at = time.monotonic()
        self._dropped = 0

    def filter(self, record: logging.LogRecord) -> bool:
        now = time.monotonic()
        self._tokens = min(self._burst, self._tokens + (now - self._at) * self._rate)
        self._at = now
        if self._tokens < 1:
            self._dropped += 1
            return False
        self._tokens -= 1
        if self._dropped:
            record.msg = f"{record.msg} [{self._dropped} records dropped]"
            self._dropped = 0
        return True


class OneLine(logging.Formatter):
    """One JSON object per record, bounded, with no traceback."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name[:MAX_FIELD],
            "msg": record.getMessage()[: MAX_FIELD * 2],
        }
        error = getattr(record, "error_class", None)
        if error:
            entry["error"] = str(error)[:MAX_FIELD]
        line = json.dumps(entry, ensure_ascii=True)
        if len(line) > MAX_RECORD:
            entry["msg"] = entry["msg"][: max(0, MAX_RECORD - 120)]
            line = json.dumps(entry, ensure_ascii=True)
        return line[:MAX_RECORD]


def configure_logging(stream=None) -> logging.Handler:
    """Install the one handler, and put every logger but ours at WARNING."""
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(OneLine())
    handler.addFilter(Reduce())
    handler.addFilter(Bound())
    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    logging.getLogger(OWN).setLevel(logging.INFO)
    logging.getLogger("chai.mcp.access").setLevel(logging.INFO)
    quiet_libraries()
    return handler
