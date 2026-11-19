"""Typed representations of PawChive API objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "jfif", "gif", "webp", "bmp", "avif", "tif", "tiff", "heic"})
VIDEO_EXTENSIONS = frozenset({"mp4", "webm", "mov", "mkv", "avi", "m4v", "wmv", "flv"})
ARCHIVE_EXTENSIONS = frozenset({"zip", "7z", "rar", "tar", "gz", "bz2", "xz"})
DOCUMENT_EXTENSIONS = frozenset({"pdf", "txt", "epub", "cbz", "cbr", "psd", "clip", "kra", "doc", "docx", "md"})


def file_kind(extension: str) -> str:
    ext = extension.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in ARCHIVE_EXTENSIONS:
        return "archive"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    return "other"


@dataclass(frozen=True)
class Creator:
    service: str
    creator_id: str
    name: str
    public_id: str | None
    updated: str | None


@dataclass(frozen=True)
class RemoteFile:
    """One downloadable original file of a post."""

    name: str  # original file name as uploaded
    path: str  # server path, e.g. /1ed/fe/<sha256>.png
    server: str  # node base URL, e.g. https://n4.pawchive.pw
    sha256: str
    extension: str
    position: int  # order inside the post (0 = main file)

    @property
    def kind(self) -> str:
        return file_kind(self.extension)

    @property
    def url(self) -> str:
        from urllib.parse import quote

        return f"{self.server.rstrip('/')}/data{self.path}?f={quote(self.name)}"


@dataclass
class Post:
    post_id: str
    creator_id: str
    service: str
    title: str
    published: datetime | None
    edited: datetime | None
    has_full: bool
    files: list[RemoteFile] = field(default_factory=list)
    skipped_paths: list[str] = field(default_factory=list)  # entries that could not be understood
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_empty(self) -> bool:
        return not self.files
