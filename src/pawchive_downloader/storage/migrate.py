"""Schema migrations based on ``PRAGMA user_version``.

Migrations are the numbered ``.sql`` files in ``storage/migrations``. Each is
applied inside a single transaction; a backup is taken first whenever an
existing database is upgraded.
"""

from __future__ import annotations

import logging
import re
from importlib import resources
from pathlib import Path

from .backup import backup_database
from .db import Database

log = logging.getLogger(__name__)
_NAME_RE = re.compile(r"^(\d{4})_[\w-]+\.sql$")


class MigrationError(RuntimeError):
    pass


def available_migrations() -> list[tuple[int, str, str]]:
    package = resources.files("pawchive_downloader.storage") / "migrations"
    found = []
    for entry in package.iterdir():
        match = _NAME_RE.match(entry.name)
        if match:
            found.append((int(match.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    found.sort()
    for expected, (number, name, _) in enumerate(found, start=1):
        if number != expected:
            raise MigrationError(f"migration numbering gap at {name}")
    return found


def current_version(db: Database) -> int:
    return int(db.scalar("PRAGMA user_version") or 0)


def migrate(db: Database, backup_dir: Path | None = None, keep_backups: int = 7) -> int:
    """Bring the schema up to date and return the resulting version."""
    migrations = available_migrations()
    latest = migrations[-1][0] if migrations else 0
    version = current_version(db)
    if version > latest:
        raise MigrationError(
            f"the database was created by a newer version of the application (schema {version} > {latest})"
        )
    pending = [m for m in migrations if m[0] > version]
    if not pending:
        return version
    if version > 0 and backup_dir is not None:
        backup_database(db, backup_dir, keep_backups, label=f"before-v{latest}")
    for number, name, sql in pending:
        log.info("Applying database migration %s", name)
        statements = [s.strip() for s in _split_sql(sql) if s.strip()]
        with db.transaction() as conn:
            for statement in statements:
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {number}")
    return latest


def _split_sql(script: str) -> list[str]:
    """Split on semicolons at line ends; our migrations contain no triggers."""
    lines = [line for line in script.splitlines() if not line.strip().startswith("--")]
    return "\n".join(lines).split(";")
