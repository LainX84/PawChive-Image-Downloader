"""Gallery classification and change detection (pure functions)."""

from __future__ import annotations

import hashlib
from enum import Enum

from ..site.models import Post


class GalleryStatus(str, Enum):
    EMPTY = "empty"                    # no attachments at all
    AWAITING_FULL = "awaiting_full"    # only previews on the server (has_full = false)
    AWAITING_REVIEW = "awaiting_review"
    QUEUED = "queued"
    PARTIAL = "partial"                # some files failed / unavailable
    COMPLETE = "complete"
    ERROR = "error"                    # could not be understood (site change)
    IGNORED = "ignored"                # dismissed by the user
    REMOVED = "removed"                # no longer on the website


class PostKind(str, Enum):
    EMPTY = "empty"
    PREVIEWS_ONLY = "previews_only"
    SINGLE = "single"
    MULTIPLE = "multiple"
    UNREADABLE = "unreadable"


def fingerprint(post: Post) -> str:
    """Changes whenever the set of files, availability or edit time changes."""
    parts = [
        "full" if post.has_full else "preview",
        post.edited.isoformat() if post.edited else "",
        post.title,
        *sorted(f.sha256 for f in post.files),
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def classify_post(post: Post) -> PostKind:
    if not post.files:
        return PostKind.UNREADABLE if post.skipped_paths else PostKind.EMPTY
    if not post.has_full:
        return PostKind.PREVIEWS_ONLY
    return PostKind.SINGLE if len(post.files) == 1 else PostKind.MULTIPLE
