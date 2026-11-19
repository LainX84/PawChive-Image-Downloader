"""Error classification and back-off policy."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from ..site.errors import (
    AccessBlocked,
    AuthRequired,
    DownloadCancelled,
    HostPaused,
    HttpError,
    IntegrityError,
    NetworkError,
    NotFound,
    RateLimited,
    ServerError,
    SiteStructureChanged,
)


class ErrorClass(str, Enum):
    TRANSIENT = "transient"      # retry with exponential back-off
    RATE_LIMITED = "rate_limited"  # retry after Retry-After, pause host
    BLOCKED = "blocked"          # pause host, notify user
    AUTH = "auth"                # stop, ask user for a session
    UNAVAILABLE = "unavailable"  # 404: original not on the server (yet)
    INTEGRITY = "integrity"      # bad bytes: restart from zero
    DISK = "disk"                # local problem: pause the whole queue
    STRUCTURE = "structure"      # site changed: needs an update
    CANCELLED = "cancelled"
    PERMANENT = "permanent"


def classify(exc: BaseException) -> ErrorClass:
    if isinstance(exc, DownloadCancelled):
        return ErrorClass.CANCELLED
    if isinstance(exc, (RateLimited, HostPaused)):
        return ErrorClass.RATE_LIMITED
    if isinstance(exc, AccessBlocked):
        return ErrorClass.BLOCKED
    if isinstance(exc, AuthRequired):
        return ErrorClass.AUTH
    if isinstance(exc, NotFound):
        return ErrorClass.UNAVAILABLE
    if isinstance(exc, IntegrityError):
        return ErrorClass.INTEGRITY
    if isinstance(exc, (NetworkError, ServerError)):
        return ErrorClass.TRANSIENT
    if isinstance(exc, SiteStructureChanged):
        return ErrorClass.STRUCTURE
    if isinstance(exc, HttpError):
        return ErrorClass.TRANSIENT if exc.status in (408, 425) else ErrorClass.PERMANENT
    if isinstance(exc, OSError):
        return ErrorClass.DISK
    return ErrorClass.PERMANENT


@dataclass
class RetryPolicy:
    base_seconds: float = 60.0
    max_seconds: float = 6 * 3600.0
    max_attempts: int = 8
    jitter: float = 0.2

    def delay(self, attempt: int, retry_after: float | None = None) -> float:
        """Delay before attempt number ``attempt + 1`` (``attempt`` starts at 1)."""
        exp = self.base_seconds * (2 ** max(0, attempt - 1))
        value = min(self.max_seconds, exp)
        if self.jitter:
            value *= 1 + random.uniform(-self.jitter, self.jitter)
        if retry_after is not None:
            value = max(value, retry_after)
        return max(1.0, value)

    def exhausted(self, attempt: int) -> bool:
        return attempt >= self.max_attempts
