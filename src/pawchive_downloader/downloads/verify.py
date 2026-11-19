"""File integrity checks."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from ..site.errors import IntegrityError
from ..site.models import IMAGE_EXTENSIONS

log = logging.getLogger(__name__)
_CHUNK = 1024 * 1024

# Signature -> canonical type. Order matters for overlapping prefixes.
_SIGNATURES: tuple[tuple[int, bytes, str], ...] = (
    (0, b"\x89PNG\r\n\x1a\n", "png"),
    (0, b"\xff\xd8\xff", "jpeg"),
    (0, b"GIF87a", "gif"),
    (0, b"GIF89a", "gif"),
    (0, b"BM", "bmp"),
    (0, b"II*\x00", "tiff"),
    (0, b"MM\x00*", "tiff"),
    (0, b"%PDF", "pdf"),
    (0, b"PK\x03\x04", "zip"),
    (0, b"7z\xbc\xaf\x27\x1c", "7z"),
    (0, b"Rar!\x1a\x07", "rar"),
    (0, b"\x1a\x45\xdf\xa3", "matroska"),
    (0, b"8BPS", "psd"),
)
_IMAGE_TYPES_BY_EXT = {
    "png": {"png"}, "jpg": {"jpeg"}, "jpeg": {"jpeg"}, "jfif": {"jpeg"}, "gif": {"gif"},
    "webp": {"webp"}, "bmp": {"bmp"}, "tif": {"tiff"}, "tiff": {"tiff"}, "avif": {"avif"}, "heic": {"heic"},
}
_IMAGE_TYPES = {"png", "jpeg", "gif", "webp", "bmp", "tiff", "avif", "heic"}


def detect_type(head: bytes) -> str | None:
    if len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"avif", b"avis"):
            return "avif"
        if brand in (b"heic", b"heix", b"mif1", b"msf1"):
            return "heic"
        return "mp4"
    for offset, magic, kind in _SIGNATURES:
        if head[offset: offset + len(magic)] == magic:
            return kind
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_content_type(content_type: str | None) -> None:
    value = (content_type or "").split(";")[0].strip().lower()
    if value in ("text/html", "application/xhtml+xml"):
        raise IntegrityError("the server returned a web page instead of the file")


def verify_file(path: Path, expected_sha256: str, extension: str, expected_size: int | None = None) -> None:
    """Raise :class:`IntegrityError` unless *path* is exactly the expected original."""
    size = path.stat().st_size
    if size == 0:
        raise IntegrityError("downloaded file is empty")
    if expected_size is not None and size != expected_size:
        raise IntegrityError(f"size mismatch: expected {expected_size} bytes, got {size}")
    actual = sha256_file(path)
    if actual != expected_sha256.lower():
        raise IntegrityError("SHA-256 mismatch: the file is corrupted or is not the original")
    ext = extension.lower()
    if ext in IMAGE_EXTENSIONS:
        with open(path, "rb") as fh:
            head = fh.read(32)
        detected = detect_type(head)
        if detected is None or detected not in _IMAGE_TYPES:
            raise IntegrityError(f"file has a .{ext} name but no valid image signature")
        expected_types = _IMAGE_TYPES_BY_EXT.get(ext)
        if expected_types and detected not in expected_types:
            # The hash proves this is the uploaded original; the uploader just
            # used the wrong extension. Keep it, but record the oddity.
            log.info("File %s is %s data with a .%s extension (hash verified)", path.name, detected, ext)
