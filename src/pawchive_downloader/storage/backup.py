"""Online SQLite backups with rotation."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from .db import Database

log = logging.getLogger(__name__)


def backup_database(db: Database, backup_dir: Path, keep: int = 7, label: str = "") -> Path:
    """Copy the live database with SQLite's backup API (safe while in use)."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = f"-{label}" if label else ""
    target = backup_dir / f"pawchive-{stamp}{suffix}.db"
    with sqlite3.connect(str(target)) as dest:
        db.connection.backup(dest)
    dest.close()
    rotate_backups(backup_dir, keep)
    log.info("Database backup written to %s", target)
    return target


def rotate_backups(backup_dir: Path, keep: int) -> None:
    backups = sorted(backup_dir.glob("pawchive-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[max(1, keep):]:
        try:
            old.unlink()
        except OSError as exc:
            log.warning("Could not delete old backup %s: %s", old, exc)


def latest_backup_date(backup_dir: Path) -> datetime | None:
    backups = list(backup_dir.glob("pawchive-*.db"))
    if not backups:
        return None
    return datetime.fromtimestamp(max(p.stat().st_mtime for p in backups))
