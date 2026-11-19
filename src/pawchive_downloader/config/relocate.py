"""Moving the application's data folders to a new location.

The database and logs are open while the application runs (and Windows does
not allow moving open files), so a move is *scheduled* in the settings and
performed at the next start, before anything is opened.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

PENDING_KEY = "pending_relocation"
FOLDER_SETTINGS = ("archive_dir", "temp_dir", "database_dir", "logs_dir")


@dataclass
class RelocationReport:
    moved: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _has_content(path: Path) -> bool:
    try:
        return path.is_dir() and any(path.iterdir())
    except OSError:
        return False


def _same(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return str(a) == str(b)


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def plan_relocation(old: dict[str, str], new: dict[str, str]) -> list[tuple[str, str]]:
    """Pairs (old, new) of changed folders, when at least one contains data.

    Existing empty folders are included too, so the old location is left
    completely empty and can be removed.
    """
    pairs = []
    any_content = False
    for key in FOLDER_SETTINGS:
        src, dst = Path(old.get(key, "")), Path(new.get(key, ""))
        if not str(src).strip() or not str(dst).strip() or _same(src, dst) or not src.exists():
            continue
        any_content = any_content or _has_content(src)
        pairs.append((str(src), str(dst)))
    return pairs if any_content else []


def _merge_move(src: Path, dst: Path, report: RelocationReport) -> None:
    """Move the children of *src* into an existing *dst*, never overwriting."""
    for child in list(src.iterdir()):
        target = dst / child.name
        if target.exists():
            if child.is_dir() and target.is_dir():
                _merge_move(child, target, report)
                continue
            report.skipped.append(str(child))
            continue
        try:
            os.replace(child, target)
        except OSError:
            shutil.move(str(child), str(target))
    try:
        src.rmdir()
    except OSError:
        pass


def relocate(pairs: list[tuple[str, str]]) -> RelocationReport:
    """Move each old folder to its new place. Same-drive moves are instant."""
    report = RelocationReport()
    old_parents: set[Path] = set()
    for old_text, new_text in pairs:
        src, dst = Path(old_text), Path(new_text)
        if not src.exists():
            continue
        if _inside(dst, src):
            report.problems.append(f"{dst} is inside {src}; move it manually.")
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if _has_content(dst):
                _merge_move(src, dst, report)
            else:
                if dst.exists():
                    dst.rmdir()
                try:
                    os.replace(src, dst)
                except OSError:
                    shutil.move(str(src), str(dst))  # different drive: copy + delete
            report.moved.append(f"{src} → {dst}")
            old_parents.add(src.parent)
        except OSError as exc:
            report.problems.append(f"{src} → {dst}: {exc.strerror or exc}")
    # Remove the old container folder if it is now empty (e.g. ...\PawChiveDownloader).
    for parent in old_parents:
        try:
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass
    return report
