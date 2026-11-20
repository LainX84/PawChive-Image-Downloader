"""Cross-platform safe names for archive folders and files."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePath

_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_INVALID_CHARS = re.compile(r'[<>"/\\|?*\x00-\x1f]')
_MAX_COMPONENT = 120


def safe_component(name: str, fallback: str = "Untitled", max_length: int = _MAX_COMPONENT) -> str:
    """Make *name* usable as one path component on Windows, macOS and Linux.

    ``"Isla: Origins - Chapter 1"`` becomes ``"Isla - Origins - Chapter 1"``.
    """
    text = unicodedata.normalize("NFC", name or "")
    text = text.replace(":", " - ")
    text = _INVALID_CHARS.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"(?:\s*-\s*){2,}", " - ", text)  # collapse "a -  - b"
    text = text.strip(" .-")
    if not text:
        text = fallback
    if len(text) > max_length:
        text = text[:max_length].rstrip(" .-")
    stem = text.split(".")[0].upper()
    if stem in _RESERVED_NAMES:
        text = f"{text}_"
    return text


def safe_file_name(stem: str, extension: str, fallback: str = "file") -> str:
    ext = re.sub(r"[^A-Za-z0-9]", "", extension or "").lower()
    clean_stem = safe_component(stem, fallback=fallback, max_length=_MAX_COMPONENT - len(ext) - 1)
    return f"{clean_stem}.{ext}" if ext else clean_stem


def with_counter(file_name: str, counter: int) -> str:
    """``"Page 35.png", 2`` -> ``"Page 35 (2).png"``."""
    path = PurePath(file_name)
    return f"{path.stem} ({counter}){path.suffix}"


@dataclass(frozen=True)
class PlannedName:
    position: int
    page_number: int | None
    file_name: str


@dataclass(frozen=True)
class FileInfo:
    position: int
    original_name: str
    extension: str
    kind: str


_DIGITS = re.compile(r"(\d+)")


def _natural_key(name: str) -> tuple[tuple[int, object], ...]:
    """Sort key where numbers compare numerically ("Page 2" < "Page 10")."""
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold()) for part in _DIGITS.split(name))


def order_images(images: list[FileInfo]) -> list[FileInfo]:
    """Order the images of a post as pages.

    PawChive does not always list attachments in page order (compilations
    such as "Pages 1 - 100" arrive shuffled), but uploaders' file names
    usually carry the sequence ("Comic---277.jpg", "page_12.png"). When every
    name contains a number and the names differ, natural name order is used;
    otherwise the order of the post is kept.
    """
    by_position = sorted(images, key=lambda f: f.position)
    stems = [PurePath(f.original_name).stem for f in by_position]
    if len(by_position) > 1 and all(_DIGITS.search(s) for s in stems) and len(set(stems)) == len(stems):
        return sorted(by_position, key=lambda f: (_natural_key(PurePath(f.original_name).stem), f.position))
    return by_position


def plan_file_names(
    files: list[FileInfo],
    page: int | None,
    page_end: int | None,
    published: datetime | None,
) -> list[PlannedName]:
    """Choose the target name of every file of one post (see architecture §5.4)."""
    images = order_images([f for f in files if f.kind == "image"])
    planned: dict[int, PlannedName] = {}
    date_prefix = published.strftime("%Y-%m-%d") if published else None

    if page is not None and images:
        if page_end is not None and page_end - page + 1 == len(images):
            for offset, info in enumerate(images):
                n = page + offset
                planned[info.position] = PlannedName(info.position, n, safe_file_name(f"Page {n}", info.extension))
        elif len(images) == 1:
            info = images[0]
            planned[info.position] = PlannedName(info.position, page, safe_file_name(f"Page {page}", info.extension))
        else:
            for index, info in enumerate(images, start=1):
                planned[info.position] = PlannedName(
                    info.position, page, safe_file_name(f"Page {page} ({index})", info.extension)
                )
    else:
        # No page number in the title: keep the order shown on the website.
        # The original names cannot be trusted to sort correctly (the post's
        # main image is often a high-numbered file shown first, e.g.
        # "Comic-98.jpg" before "Comic-71.jpg"), and file dates are random
        # because downloads finish in parallel. A zero-padded sequence number
        # makes every file browser show the pages in the website's order.
        in_post_order = sorted(images, key=lambda f: f.position)
        width = max(2, len(str(len(in_post_order))))
        for index, info in enumerate(in_post_order, start=1):
            stem = PurePath(info.original_name).stem or "image"
            if len(in_post_order) > 1:
                stem = f"{index:0{width}d} - {stem}"
            if date_prefix:
                stem = f"{date_prefix} - {stem}"
            planned[info.position] = PlannedName(info.position, None, safe_file_name(stem, info.extension))

    for info in files:
        if info.kind == "image":
            continue
        stem = PurePath(info.original_name).stem or info.kind
        planned[info.position] = PlannedName(info.position, None, safe_file_name(stem, info.extension))

    # Names must be unique inside the post itself.
    used: set[str] = set()
    result: list[PlannedName] = []
    for position in sorted(planned):
        item = planned[position]
        name = item.file_name
        counter = 2
        while name.casefold() in used:
            name = with_counter(item.file_name, counter)
            counter += 1
        used.add(name.casefold())
        result.append(PlannedName(item.position, item.page_number, name))
    return result
