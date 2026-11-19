"""Diagnostic bundle export for troubleshooting."""

from __future__ import annotations

import json
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from ..config.settings import Settings
from ..storage.db import Database
from ..version import __version__
from .logging_setup import RedactingFilter

_TABLES = ("authors", "works", "galleries", "files", "download_queue", "review_requests", "scan_log")


def export_diagnostics(target: Path, settings: Settings, db: Database | None,
                       redactor: RedactingFilter | None = None) -> Path:
    """Write a zip with logs, sanitized settings and database statistics.

    The archive contains no cookies, no file contents and no database rows.
    """
    redact = redactor.redact if redactor else (lambda text: text)
    if target.is_dir():
        target = target / f"pawchive-diagnostics-{datetime.now():%Y%m%d-%H%M%S}.zip"
    info: dict[str, object] = {
        "app_version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    stats: dict[str, object] = {}
    if db is not None:
        for table in _TABLES:
            stats[table] = db.scalar(f"SELECT COUNT(*) FROM {table}")
        stats["file_status"] = {r[0]: r[1] for r in db.query("SELECT status, COUNT(*) FROM files GROUP BY status")}
        stats["gallery_status"] = {r[0]: r[1] for r in db.query("SELECT status, COUNT(*) FROM galleries GROUP BY status")}
        stats["queue_errors"] = {r[0] or "none": r[1] for r in db.query(
            "SELECT error_class, COUNT(*) FROM download_queue GROUP BY error_class")}
        stats["schema_version"] = db.scalar("PRAGMA user_version")
    settings_data = settings.to_dict()
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("info.json", json.dumps(info, indent=2))
        bundle.writestr("settings.json", json.dumps(settings_data, indent=2))
        bundle.writestr("database-stats.json", json.dumps(stats, indent=2, default=str))
        logs_dir = Path(settings.logs_dir)
        for log_file in sorted(logs_dir.glob("pawchive.log*")):
            text = log_file.read_text(encoding="utf-8", errors="replace")
            bundle.writestr(f"logs/{log_file.name}", redact(text))
    return target
