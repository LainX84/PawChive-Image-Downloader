"""Validation and preparation of the configured directories."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .settings import Settings


@dataclass(frozen=True)
class PathProblem:
    setting: str
    path: str
    message: str


def check_writable_dir(path: Path) -> str | None:
    """Return ``None`` if *path* exists (or can be created) and is writable,
    otherwise a human-readable reason."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"cannot be created: {exc.strerror or exc}"
    if not path.is_dir():
        return "exists but is not a folder"
    try:
        fd, probe = tempfile.mkstemp(dir=path, prefix=".write-test-")
        os.close(fd)
        os.unlink(probe)
    except OSError as exc:
        return f"is not writable: {exc.strerror or exc}"
    return None


def _is_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def validate_paths(settings: Settings) -> list[PathProblem]:
    """Check every configured folder. *settings* must be resolved."""
    problems: list[PathProblem] = []
    entries = {
        "archive_dir": Path(settings.archive_dir),
        "temp_dir": Path(settings.temp_dir),
        "database_dir": Path(settings.database_dir),
        "logs_dir": Path(settings.logs_dir),
    }
    for name, path in entries.items():
        if not str(path).strip():
            problems.append(PathProblem(name, str(path), "is empty"))
            continue
        reason = check_writable_dir(path)
        if reason:
            problems.append(PathProblem(name, str(path), reason))

    archive, temp = entries["archive_dir"], entries["temp_dir"]
    # The temporary area must never be mixed with completed archive files.
    if _is_inside(temp, archive) or _is_inside(archive, temp):
        problems.append(
            PathProblem("temp_dir", str(temp), "must not be inside the archive folder (or vice versa)")
        )
    return problems


def prepare_directories(settings: Settings) -> None:
    """Create the full directory layout. Raises ``OSError`` on failure."""
    for path in (
        settings.archive_path,
        settings.downloads_temp_path,
        settings.held_temp_path,
        Path(settings.database_dir),
        Path(settings.database_dir) / "backups",
        settings.logs_path,
    ):
        path.mkdir(parents=True, exist_ok=True)
