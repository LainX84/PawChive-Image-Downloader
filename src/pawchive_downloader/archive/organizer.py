"""Atomic, collision-safe placement of verified files into the archive."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from .naming import with_counter

log = logging.getLogger(__name__)
_CHUNK = 1024 * 1024


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_dir(directory: Path) -> None:
    if os.name != "posix":
        return  # directory fsync is not available on Windows
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


@dataclass(frozen=True)
class PlacementResult:
    path: Path
    already_present: bool  # an identical file was already at the target


class Organizer:
    """Moves files into place. A process-wide lock serializes name choices so
    two workers never pick the same free name."""

    _lock = threading.Lock()

    @staticmethod
    def _copy_then_replace(source: Path, incoming: Path) -> None:
        with open(source, "rb") as src, open(incoming, "wb") as dst:
            shutil.copyfileobj(src, dst, _CHUNK)
            dst.flush()
            os.fsync(dst.fileno())

    def place(self, source: Path, directory: Path, file_name: str, sha256: str | None = None) -> PlacementResult:
        """Move *source* to ``directory/file_name`` without overwriting anything.

        If the name is taken by an identical file (same SHA-256), the source is
        discarded and the existing path is returned. If it is taken by a
        different file, ``" (2)"``, ``" (3)"``… is appended.
        """
        directory.mkdir(parents=True, exist_ok=True)
        with self._lock:
            target = directory / file_name
            counter = 2
            while target.exists():
                if sha256 and sha256_of(target) == sha256:
                    source.unlink(missing_ok=True)
                    return PlacementResult(target, already_present=True)
                target = directory / with_counter(file_name, counter)
                counter += 1

            incoming = directory / f".{target.name}.incoming"
            try:
                try:
                    # Same volume: a rename is atomic and instant.
                    os.replace(source, incoming)
                except OSError:
                    # Different volume (e.g. Temp on C:, Archive on D:).
                    self._copy_then_replace(source, incoming)
                    source.unlink(missing_ok=True)
                os.replace(incoming, target)
            except BaseException:
                if incoming.exists() and not source.exists():
                    # Put the data back so a retry can reuse it.
                    try:
                        os.replace(incoming, source)
                    except OSError:
                        pass
                raise
            _fsync_dir(directory)
            return PlacementResult(target, already_present=False)

    def move_within_archive(self, current: Path, directory: Path, file_name: str | None = None) -> Path:
        """Used by rename/merge/reassign. Never overwrites; returns the new path."""
        name = file_name or current.name
        result = self.place(current, directory, name, sha256=None)
        return result.path

    @staticmethod
    def remove_empty_dirs(start: Path, stop_at: Path) -> None:
        """Remove *start* and its empty parents up to (not including) *stop_at*."""
        current = start
        try:
            stop = stop_at.resolve()
            while current.resolve() != stop and current.is_dir() and not any(current.iterdir()):
                current.rmdir()
                current = current.parent
        except OSError as exc:
            log.debug("Could not remove empty folder %s: %s", current, exc)
