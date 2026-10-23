"""Structured logging for the merge service.

One JSON object per line on stdout. Dozzle -- the container log viewer the
server is watched through -- detects JSON, colours rows by ``level`` and lets
each field be searched, which a ``key=value`` line does not give you.

    {"ts":"2026-09-22T14:35:02.101Z","level":"INFO","event":"merge_stage",
     "message":"MIXING 60%","job":"mrg_01J8XK","room":"R-001"}

``event`` is the stable machine key to grep or alert on; ``message`` is the
short human line Dozzle shows in the collapsed row.

Two rules this module enforces so callers cannot get them wrong:

* **Everything goes to stdout.** Splitting across stdout and stderr lets the
  two interleave out of order in ``docker logs``, which is exactly the wrong
  thing when you are reading a failure back.
* **Presigned URLs are truncated to scheme://host/path.** The query string
  holds the signature, which is effectively a credential, and container logs
  are both persisted on the host and displayed in a browser. Never log a raw
  URL -- pass it through :func:`safe_url`.

Level comes from ``RECOG_LOG_LEVEL`` (default ``INFO``). Run at ``DEBUG`` only
while chasing something: it prints full ffmpeg command lines and per-track beep
detection detail.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from urllib.parse import urlsplit

LOGGER_NAME = "recog"

#: Fields that are part of the envelope and must not be overwritten by a caller.
_RESERVED = frozenset({"ts", "level", "event", "message", "traceback"})


def safe_url(url: str | None) -> str | None:
    """Drop the query string, which is where a presigned signature lives.

    Keeps enough to diagnose a transfer -- which host, which object -- without
    writing a usable credential into the container logs.
    """
    if not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<unparseable>"
    if not parts.netloc:
        return "<relative>"
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


class _JsonFormatter(logging.Formatter):
    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", self.converter(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "event": getattr(record, "event", record.name),
            "message": record.getMessage(),
        }
        for key, value in getattr(record, "fields", {}).items():
            if key not in _RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["traceback"] = "".join(traceback.format_exception(*record.exc_info)).strip()
        return json.dumps(payload, ensure_ascii=False, default=str)


def _build_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:  # already configured (re-import, or a test re-running)
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel((os.environ.get("RECOG_LOG_LEVEL") or "INFO").upper())
    # Ours is the only handler that should see these; root may be configured by
    # a host process with a format of its own.
    logger.propagate = False
    return logger


_logger = _build_logger()


def _emit(level: int, event: str, message: str, exc_info: bool, fields: dict) -> None:
    if not _logger.isEnabledFor(level):
        return
    _logger.log(
        level,
        message or event,
        exc_info=exc_info,
        extra={"event": event, "fields": fields},
    )


def debug(event: str, message: str = "", **fields) -> None:
    _emit(logging.DEBUG, event, message, False, fields)


def info(event: str, message: str = "", **fields) -> None:
    _emit(logging.INFO, event, message, False, fields)


def warn(event: str, message: str = "", **fields) -> None:
    _emit(logging.WARNING, event, message, False, fields)


def error(event: str, message: str = "", *, exc_info: bool = False, **fields) -> None:
    """``exc_info=True`` attaches the active traceback as a ``traceback`` field.

    Worth using on anything caught by a bare ``except``: without it the cause of
    an unexpected failure is gone for good.
    """
    _emit(logging.ERROR, event, message, exc_info, fields)


def is_debug() -> bool:
    """Guard for fields that cost something to build (a full command line)."""
    return _logger.isEnabledFor(logging.DEBUG)


def set_level(level: str) -> None:
    """Used by tests; production reads RECOG_LOG_LEVEL at import."""
    _logger.setLevel(level.upper())
