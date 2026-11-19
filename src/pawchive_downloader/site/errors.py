"""Exception hierarchy for everything that talks to PawChive."""

from __future__ import annotations


class PawChiveError(Exception):
    """Base class for website-related errors."""


class InvalidUrl(PawChiveError):
    """The text is not a supported PawChive URL."""


class UnsupportedUrl(InvalidUrl):
    """A valid PawChive URL of a kind the application does not archive."""


class NetworkError(PawChiveError):
    """Connection problem, timeout, or an interrupted transfer (temporary)."""


class ServerError(PawChiveError):
    """HTTP 5xx (temporary)."""

    def __init__(self, status: int, message: str = "") -> None:
        super().__init__(message or f"server error HTTP {status}")
        self.status = status


class RateLimited(PawChiveError):
    """HTTP 429. ``retry_after`` is in seconds when the server provided it."""

    def __init__(self, retry_after: float | None, host: str = "") -> None:
        super().__init__(f"rate limited by {host or 'server'}" + (f", retry after {retry_after:.0f}s" if retry_after else ""))
        self.retry_after = retry_after
        self.host = host


class AccessBlocked(PawChiveError):
    """HTTP 403 or an anti-bot challenge page. Never retried aggressively."""

    def __init__(self, host: str, detail: str = "") -> None:
        super().__init__(f"access to {host} is blocked" + (f": {detail}" if detail else ""))
        self.host = host


class AuthRequired(PawChiveError):
    """HTTP 401: the resource needs a (valid) authenticated session."""

    def __init__(self, url: str = "") -> None:
        super().__init__("authentication required or session expired")
        self.url = url


class NotFound(PawChiveError):
    """HTTP 404."""

    def __init__(self, url: str = "") -> None:
        super().__init__(f"not found: {url}" if url else "not found")
        self.url = url


class HttpError(PawChiveError):
    """Any other unexpected HTTP status."""

    def __init__(self, status: int, url: str = "") -> None:
        super().__init__(f"unexpected HTTP {status} for {url}")
        self.status = status


class HostPaused(PawChiveError):
    """Requests to this host are paused after a block or rate limit."""

    def __init__(self, host: str, until: float, reason: str) -> None:
        super().__init__(f"{host} paused: {reason}")
        self.host = host
        self.until = until
        self.reason = reason


class SiteStructureChanged(PawChiveError):
    """The response no longer has the structure this version understands."""


class IntegrityError(PawChiveError):
    """A downloaded file failed verification (hash, size, signature, type)."""


class IncompleteDownload(NetworkError):
    """The transfer ended before all bytes arrived; the .part file is kept."""


class DownloadCancelled(PawChiveError):
    """The download was stopped on request; the .part file is kept."""
