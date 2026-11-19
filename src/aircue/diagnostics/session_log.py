"""JSONL session logging with cross-layer correlation (design.md D6)."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import time
import uuid
from pathlib import Path
from typing import Any

SESSION_LOGGER = "aircue.session"

_LOG_MAX_BYTES = 5_000_000
_LOG_BACKUPS = 2
_handler: logging.Handler | None = None


def default_log_dir() -> Path:
    """The design.md D6 log directory under the local application data."""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "AirCue" / "logs"


class JsonlFormatter(logging.Formatter):
    """One JSON object per line; the session id is fixed per process."""

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self.session_id = session_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts_ns": time.monotonic_ns(),
            "session": self.session_id,
            "level": record.levelname,
            "severity": record.levelname.lower(),
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
        }
        payload.update(getattr(record, "fields", None) or {})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, separators=(",", ":"), default=str)


def record_event(
    event: str,
    *,
    generation: int,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Append one correlated record; every layer passes its own generation."""
    logging.getLogger(SESSION_LOGGER).log(
        level,
        event,
        extra={"event": event, "fields": {"generation": generation, **fields}},
    )


def configure_session_logging(
    log_dir: Path | str | None = None,
    *,
    session_id: str | None = None,
    level: str = "INFO",
    max_bytes: int = _LOG_MAX_BYTES,
    backup_count: int = _LOG_BACKUPS,
) -> Path | None:
    """Attach the rotating JSONL handler; returns the file path it writes."""
    global _handler
    close_session_logging()
    formatter = JsonlFormatter(session_id or uuid.uuid4().hex)
    path: Path | None = None
    try:
        directory = default_log_dir() if log_dir is None else Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "aircue.jsonl"
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
    except OSError:
        # A locked-down profile must not stop a session; fall back to stderr.
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger = logging.getLogger("aircue")
    logger.setLevel(level)
    logger.addHandler(handler)
    _handler = handler
    return path


def close_session_logging() -> None:
    """Detach and flush the handler; safe to call more than once."""
    global _handler
    handler = _handler
    if handler is None:
        return
    _handler = None
    logging.getLogger("aircue").removeHandler(handler)
    handler.close()
