"""Structured logging with secret redaction.

* ``Logs/pawchive.log``: JSON lines (one event per line), rotated.
* An in-memory ring buffer feeds the log view of the user interface.
* :class:`RedactingFilter` masks cookies, tokens and registered secret values
  on every handler, so secrets cannot reach a log file by accident.
"""

from __future__ import annotations

import collections
import json
import logging
import logging.handlers
import re
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE_NAME = "pawchive.log"
_PATTERNS = [
    re.compile(r"(?i)(cookie|set-cookie|authorization|x-csrf-token|session)\s*[:=]\s*([^\s,'\"}]+(?:;\s*[^\s,'\"}]+)*)"),
    re.compile(r"(?i)(token|password|passwd|secret|api[_-]?key)\s*[:=]\s*([^\s,'\"}]+)"),
]
REDACTED = "[REDACTED]"


class RedactingFilter(logging.Filter):
    def __init__(self, secrets_provider: Callable[[], list[str]] | None = None) -> None:
        super().__init__()
        self._secrets_provider = secrets_provider
        self._local = threading.local()

    def redact(self, text: str) -> str:
        for pattern in _PATTERNS:
            text = pattern.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
        if self._secrets_provider and not getattr(self._local, "busy", False):
            self._local.busy = True  # guard against re-entry if the provider logs
            try:
                secrets = self._secrets_provider()
            except Exception:  # never fail logging because of the provider
                secrets = []
            finally:
                self._local.busy = False
            for secret in sorted(secrets, key=len, reverse=True):
                if secret and len(secret) >= 4:
                    text = text.replace(secret, REDACTED)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = self.redact(message)
        record.args = None
        if record.exc_info and record.exc_info[1] is not None:
            # Format now so that the redacted text is what gets written.
            record.exc_text = self.redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "thread": record.threadName,
            "message": record.getMessage(),
        }
        if record.exc_text:
            payload["exception"] = record.exc_text
        return json.dumps(payload, ensure_ascii=False)


class MemoryHandler(logging.Handler):
    """Keeps the last N formatted records for the UI."""

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self.records: collections.deque[tuple[float, str, str, str]] = collections.deque(maxlen=capacity)
        self._lock_records = threading.Lock()
        self.listeners: list[Callable[[tuple[float, str, str, str]], None]] = []

    def emit(self, record: logging.LogRecord) -> None:
        entry = (record.created, record.levelname, record.name.removeprefix("pawchive_downloader."), record.getMessage())
        with self._lock_records:
            self.records.append(entry)
        for listener in list(self.listeners):
            try:
                listener(entry)
            except Exception:
                pass

    def snapshot(self) -> list[tuple[float, str, str, str]]:
        with self._lock_records:
            return list(self.records)


_memory_handler: MemoryHandler | None = None
_redactor: RedactingFilter | None = None


def memory_handler() -> MemoryHandler | None:
    return _memory_handler


def setup_logging(logs_dir: Path, level: str = "INFO", secrets_provider: Callable[[], list[str]] | None = None,
                  console: bool = False) -> RedactingFilter:
    global _memory_handler, _redactor
    logs_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.setLevel(logging.DEBUG)

    _redactor = RedactingFilter(secrets_provider)
    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / LOG_FILE_NAME, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(JsonFormatter())
    file_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    file_handler.addFilter(_redactor)
    root.addHandler(file_handler)

    _memory_handler = MemoryHandler()
    _memory_handler.setLevel(logging.INFO)
    _memory_handler.addFilter(_redactor)
    root.addHandler(_memory_handler)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        stream.addFilter(_redactor)
        root.addHandler(stream)

    for noisy in ("httpx", "httpcore", "keyring"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return _redactor


def set_level(level: str) -> None:
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            handler.setLevel(getattr(logging, level.upper(), logging.INFO))
