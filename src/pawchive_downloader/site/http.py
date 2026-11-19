"""HTTP client with polite request scheduling.

Responsibilities:

* per-host minimum delay between requests (throttling);
* host pauses after HTTP 429 / 403 / challenge pages (never evaded);
* translation of HTTP outcomes into the typed errors of :mod:`.errors`;
* sending optional session cookies only to the PawChive site and its file nodes.
"""

from __future__ import annotations

import email.utils
import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit

import httpx

from .errors import (
    AccessBlocked,
    AuthRequired,
    HostPaused,
    HttpError,
    NetworkError,
    NotFound,
    RateLimited,
    ServerError,
    SiteStructureChanged,
)
from .urls import is_site_host

log = logging.getLogger(__name__)

CHALLENGE_MARKERS = ("cf-chl", "challenge-platform", "Just a moment...", "Attention Required!", "cf_captcha")


def parse_retry_after(value: str | None, now: float | None = None) -> float | None:
    """Parse a Retry-After header (seconds or HTTP date) into seconds."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    current = now if now is not None else time.time()
    return max(0.0, when.timestamp() - current)


class HostThrottle:
    """Enforces a minimum interval between requests to the same host."""

    def __init__(
        self,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_slot: dict[str, float] = {}

    def wait(self, host: str, interval: float | None = None) -> None:
        gap = self.min_interval if interval is None else interval
        with self._lock:
            now = self._clock()
            slot = max(now, self._next_slot.get(host, 0.0))
            self._next_slot[host] = slot + gap
        delay = slot - now
        if delay > 0:
            self._sleep(delay)


class HttpClient:
    """Thin, thread-safe wrapper around :class:`httpx.Client`."""

    def __init__(
        self,
        base_url: str,
        user_agent: str,
        request_delay: float = 1.5,
        timeout: float = 30.0,
        cookie_provider: Callable[[], str | None] | None = None,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        file_request_delay: float | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._cookie_provider = cookie_provider
        self._clock = clock
        self._api_throttle = HostThrottle(request_delay, sleep=sleep)
        # File nodes serve static, cacheable files; a smaller gap is enough.
        self._file_throttle = HostThrottle(
            file_request_delay if file_request_delay is not None else max(0.0, request_delay / 2), sleep=sleep
        )
        self._pause_lock = threading.Lock()
        self._paused: dict[str, tuple[float, str]] = {}
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "application/json, */*;q=0.5"},
            timeout=httpx.Timeout(timeout, connect=min(15.0, timeout)),
            follow_redirects=False,
            transport=transport,
        )

    # ------------------------------------------------------------------ pauses
    def pause_host(self, host: str, until: float, reason: str) -> None:
        with self._pause_lock:
            current = self._paused.get(host)
            if current is None or current[0] < until:
                self._paused[host] = (until, reason)
        log.warning("Pausing requests to %s until %s: %s", host, time.strftime("%H:%M:%S", time.localtime(until)), reason)

    def resume_host(self, host: str) -> None:
        with self._pause_lock:
            self._paused.pop(host, None)

    def paused_hosts(self) -> dict[str, tuple[float, str]]:
        now = self._clock()
        with self._pause_lock:
            for host in [h for h, (u, _) in self._paused.items() if u <= now]:
                del self._paused[host]
            return dict(self._paused)

    def check_host(self, host: str) -> None:
        paused = self.paused_hosts().get(host)
        if paused:
            raise HostPaused(host, paused[0], paused[1])

    # ----------------------------------------------------------------- helpers
    def _headers_for(self, url: str, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(extra or {})
        if self._cookie_provider and is_site_host(urlsplit(url).hostname, self.base_url):
            cookie = self._cookie_provider()
            if cookie:
                headers["Cookie"] = cookie
        return headers

    def _raise_for_status(self, response: httpx.Response, url: str, body_preview: str = "") -> None:
        status = response.status_code
        host = urlsplit(url).hostname or ""
        if status < 300:
            return
        if status == 429:
            retry = parse_retry_after(response.headers.get("Retry-After"), self._clock())
            raise RateLimited(retry, host)
        if status == 401:
            raise AuthRequired(url)
        if status == 403:
            detail = "anti-bot challenge" if self._looks_like_challenge(response, body_preview) else "HTTP 403"
            raise AccessBlocked(host, detail)
        if status == 404 or status == 410:
            raise NotFound(url)
        if 500 <= status < 600:
            raise ServerError(status)
        if 300 <= status < 400:
            raise SiteStructureChanged(f"unexpected redirect ({status}) from {url} to {response.headers.get('Location')}")
        raise HttpError(status, url)

    @staticmethod
    def _looks_like_challenge(response: httpx.Response, body_preview: str) -> bool:
        if response.headers.get("cf-mitigated", "").lower() == "challenge":
            return True
        return any(marker in body_preview for marker in CHALLENGE_MARKERS)

    # -------------------------------------------------------------------- API
    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        host = urlsplit(url).hostname or ""
        self.check_host(host)
        self._api_throttle.wait(host)
        try:
            response = self._client.get(url, params=params, headers=self._headers_for(url))
        except httpx.TimeoutException as exc:
            raise NetworkError(f"timeout contacting {host}") from exc
        except httpx.TransportError as exc:
            raise NetworkError(f"network error contacting {host}: {exc.__class__.__name__}") from exc
        preview = response.text[:2000] if response.status_code >= 400 or "json" not in response.headers.get("content-type", "") else ""
        if response.status_code == 400:
            raise SiteStructureChanged(f"API rejected the request {response.request.url}: {preview[:200]}")
        self._raise_for_status(response, url, preview)
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            if self._looks_like_challenge(response, preview):
                raise AccessBlocked(host, "anti-bot challenge page instead of data")
            raise SiteStructureChanged(f"expected JSON from {url}, got {content_type or 'no content type'}")
        try:
            return response.json()
        except ValueError as exc:
            raise SiteStructureChanged(f"invalid JSON from {url}") from exc

    # ------------------------------------------------------------------ files
    @contextmanager
    def stream_file(self, url: str, headers: dict[str, str] | None = None) -> Iterator[httpx.Response]:
        """Open a streaming GET. The caller iterates ``response.iter_bytes()``.

        Error statuses are raised before yielding; transport errors during
        iteration surface as :class:`httpx.TransportError` subclasses and must
        be handled by the caller (see :mod:`..downloads.downloader`).
        """
        host = urlsplit(url).hostname or ""
        if not is_site_host(host, self.base_url):
            raise SiteStructureChanged(f"refusing to download from foreign host {host!r}")
        self.check_host(host)
        self._file_throttle.wait(host)
        request = self._client.build_request("GET", url, headers=self._headers_for(url, headers))
        try:
            response = self._client.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise NetworkError(f"timeout contacting {host}") from exc
        except httpx.TransportError as exc:
            raise NetworkError(f"network error contacting {host}: {exc.__class__.__name__}") from exc
        try:
            if response.status_code >= 300 and response.status_code != 416:
                preview = ""
                if response.status_code == 403:
                    try:
                        preview = response.read()[:2000].decode("utf-8", "replace")
                    except httpx.HTTPError:
                        preview = ""
                self._raise_for_status(response, url, preview)
            yield response
        finally:
            response.close()

    def close(self) -> None:
        self._client.close()
