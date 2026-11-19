"""Downloads one file into a ``.part`` file with HTTP Range resume."""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

from ..site.errors import DownloadCancelled, IncompleteDownload, IntegrityError, NetworkError
from ..site.http import HttpClient
from .throttle import BandwidthLimiter, CancelFlag
from .verify import check_content_type, verify_file

log = logging.getLogger(__name__)
_CONTENT_RANGE_RE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)")

ProgressCallback = Callable[[int, int | None], None]


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    size: int
    resumed_from: int


def _parse_content_range(value: str | None) -> tuple[int, int, int | None] | None:
    if not value:
        return None
    m = _CONTENT_RANGE_RE.match(value.strip())
    if not m:
        return None
    total = None if m.group(3) == "*" else int(m.group(3))
    return int(m.group(1)), int(m.group(2)), total


class FileDownloader:
    def __init__(self, client: HttpClient, chunk_size: int = 256 * 1024,
                 limiter: BandwidthLimiter | None = None) -> None:
        self.client = client
        self.chunk_size = chunk_size
        self.limiter = limiter

    def download(
        self,
        url: str,
        part_path: Path,
        expected_sha256: str,
        extension: str,
        on_progress: ProgressCallback | None = None,
        cancel: CancelFlag | None = None,
    ) -> DownloadResult:
        """Download (or resume) *url* into *part_path* and verify it.

        On success the verified file stays at *part_path* (the caller moves it).
        On network errors the ``.part`` file is kept for a later resume. On an
        integrity failure it is deleted so the next attempt starts clean.
        """
        part_path.parent.mkdir(parents=True, exist_ok=True)
        existing = part_path.stat().st_size if part_path.exists() else 0
        # identity encoding: the bytes on disk must be exactly the bytes served,
        # otherwise Range offsets and the SHA-256 check would not line up.
        headers = {"Accept-Encoding": "identity"}
        if existing:
            headers["Range"] = f"bytes={existing}-"
        resumed_from = 0
        total: int | None = None

        with self.client.stream_file(url, headers=headers) as response:
            if response.status_code == 416:
                # Requested range starts at/after the end: the part may already be complete.
                try:
                    verify_file(part_path, expected_sha256, extension)
                    return DownloadResult(part_path, part_path.stat().st_size, existing)
                except (IntegrityError, OSError):
                    part_path.unlink(missing_ok=True)
                    raise IncompleteDownload("stored partial file was invalid; restarting from zero")
            check_content_type(response.headers.get("content-type"))

            if response.status_code == 206 and existing:
                parsed = _parse_content_range(response.headers.get("content-range"))
                if not parsed or parsed[0] != existing:
                    raise IncompleteDownload("server answered with an unexpected byte range")
                total = parsed[2]
                mode = "ab"
                resumed_from = existing
            else:
                if existing:
                    log.info("Server ignored the Range request for %s; restarting from zero", part_path.name)
                length = response.headers.get("content-length")
                total = int(length) if length and length.isdigit() else None
                mode = "wb"
                existing = 0

            written = existing
            try:
                with open(part_path, mode) as fh:
                    # iter_raw yields data as soon as it arrives, so an interrupted
                    # transfer keeps everything received up to that point.
                    try:
                        for chunk in response.iter_raw():
                            if cancel is not None and cancel.is_set():
                                raise DownloadCancelled("download stopped")
                            fh.write(chunk)
                            written += len(chunk)
                            if on_progress:
                                on_progress(written, total)
                            if self.limiter is not None:
                                self.limiter.consume(len(chunk), cancel)
                    finally:
                        # Whatever happens, the bytes received so far are safely in the
                        # .part file, ready to be resumed with a Range request.
                        fh.flush()
                        os.fsync(fh.fileno())
            except (httpx.TransportError, httpx.StreamError) as exc:
                raise NetworkError(f"transfer interrupted after {written} bytes: {exc.__class__.__name__}") from exc

        if total is not None and written < total:
            raise IncompleteDownload(f"transfer ended early ({written} of {total} bytes)")
        try:
            verify_file(part_path, expected_sha256, extension, expected_size=total)
        except IntegrityError:
            part_path.unlink(missing_ok=True)
            raise
        return DownloadResult(part_path, written, resumed_from)
