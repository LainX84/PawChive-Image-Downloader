"""Persistent download queue and worker pool."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from ..core.events import EventBus, EventType
from ..i18n import _
from ..site.errors import DownloadCancelled, HostPaused, RateLimited
from ..site.http import HttpClient
from ..storage.db import from_db_time, to_db_time, utcnow
from ..storage.repositories import FileRecord, QueueItem, Repositories
from .downloader import FileDownloader
from .retry import ErrorClass, RetryPolicy, classify
from .throttle import BandwidthLimiter, SpeedMeter

log = logging.getLogger(__name__)

FinalizeCallback = Callable[[FileRecord, Path], None]
HostProblemCallback = Callable[[str, float, str], None]

# Queue status for files the user put on hold; they are skipped until resumed.
ON_HOLD = "on_hold"
USER_PAUSE_REASON = "Paused by you"


class _CancelToken:
    """Set when either the whole manager stops or this one transfer must stop."""

    def __init__(self, *events: threading.Event) -> None:
        self._events = events

    def is_set(self) -> bool:
        return any(event.is_set() for event in self._events)


class DownloadManager:
    def __init__(
        self,
        repos: Repositories,
        client: HttpClient,
        events: EventBus,
        finalize: FinalizeCallback,
        on_host_problem: HostProblemCallback,
        policy: RetryPolicy,
        max_concurrent: int = 2,
        max_per_host: int = 1,
        unavailable_recheck: timedelta = timedelta(hours=48),
        max_unavailable_rechecks: int = 10,
        clock: Callable[[], datetime] = utcnow,
        speed_limit_bytes: int = 0,
    ) -> None:
        self.repos = repos
        self.client = client
        self.events = events
        self.finalize = finalize
        self.on_host_problem = on_host_problem
        self.policy = policy
        self.max_concurrent = max_concurrent
        self.max_per_host = max_per_host
        self.unavailable_recheck = unavailable_recheck
        self.max_unavailable_rechecks = max_unavailable_rechecks
        self.clock = clock
        self.limiter = BandwidthLimiter(speed_limit_bytes)
        self.downloader = FileDownloader(client, limiter=self.limiter)

        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._cancel = threading.Event()
        self._active: dict[int, str] = {}  # file_id -> host
        self._progress: dict[int, tuple[int, int | None]] = {}
        self._meters: dict[int, SpeedMeter] = {}
        self._file_cancel: dict[int, threading.Event] = {}  # file_id -> stop this transfer
        self._hold_requested: set[int] = set()  # active files to put on hold once they stop
        self._threads: list[threading.Thread] = []
        self._paused = self.repos.state.get("downloads_paused") == "1"
        self._pause_reason: str | None = (self.repos.state.get("downloads_pause_reason") or USER_PAUSE_REASON) \
            if self._paused else None
        until = self.repos.state.get("downloads_paused_until") if self._paused else None
        self._paused_until: datetime | None = from_db_time(until) if until else None

    # ----------------------------------------------------------- lifecycle
    def start(self) -> None:
        self._stop.clear()
        self._cancel.clear()
        for index in range(self.max_concurrent):
            thread = threading.Thread(target=self._worker, name=f"download-{index + 1}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._cancel.set()  # active transfers stop between chunks; .part files are kept
        self._wake.set()
        deadline = time.monotonic() + timeout
        for thread in self._threads:
            thread.join(max(0.1, deadline - time.monotonic()))
        self._threads.clear()

    def wake(self) -> None:
        self._wake.set()

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def pause_reason(self) -> str | None:
        return self._pause_reason

    @property
    def paused_until(self) -> datetime | None:
        """When a timed pause ends by itself (``None``: until resumed by hand)."""
        return self._paused_until

    def set_speed_limit(self, bytes_per_second: int) -> None:
        self.limiter.set_rate(bytes_per_second)

    def check_pause_expired(self) -> bool:
        """Resume automatically once a timed pause is over. Returns True if it resumed."""
        until = self._paused_until
        if self._paused and until is not None and self.clock() >= until:
            log.info("Timed pause is over: resuming downloads")
            self.set_paused(False)
            return True
        return False

    def set_paused(self, paused: bool, reason: str | None = None, until: datetime | None = None) -> None:
        """Pause or resume the whole queue.

        Pausing also stops the transfers in progress between two chunks; their
        ``.part`` files are kept and resume with an HTTP Range request later.
        With *until*, downloads resume by themselves at that time.
        """
        if paused:
            reason = reason or USER_PAUSE_REASON
        self._paused = paused
        self._pause_reason = reason if paused else None
        self._paused_until = until if paused else None
        self.repos.state.set("downloads_paused", "1" if paused else "0")
        self.repos.state.set("downloads_pause_reason", reason or "")
        self.repos.state.set("downloads_paused_until", to_db_time(until) if paused and until else "")
        if paused:
            with self._lock:
                for event in self._file_cancel.values():
                    event.set()
        self.events.publish(EventType.QUEUE_STATE, paused=paused, reason=reason, until=self._paused_until)
        if not paused:
            self.wake()

    # ------------------------------------------------------- per-file hold
    def hold(self, file_id: int) -> bool:
        """Put one file on hold. An active transfer stops and keeps its ``.part`` file."""
        with self._lock:
            if file_id in self._active:
                self._hold_requested.add(file_id)
                event = self._file_cancel.get(file_id)
                if event is not None:
                    event.set()
                return True
        item = self.repos.queue.get(file_id)
        if item is None or item.status not in ("waiting", "backoff", "failed", "paused"):
            return False
        self.repos.queue.update(file_id, status=ON_HOLD)
        self.repos.files.update(file_id, status="queued")
        self.events.publish(EventType.QUEUE_CHANGED)
        return True

    def release_hold(self, file_id: int) -> bool:
        """Resume a file put on hold; it keeps its attempts and partial data."""
        with self._lock:
            self._hold_requested.discard(file_id)
        item = self.repos.queue.get(file_id)
        if item is None or item.status != ON_HOLD:
            return False
        self.repos.queue.update(file_id, status="waiting", next_attempt_at=self.clock())
        self.repos.files.update(file_id, status="queued")
        self.events.publish(EventType.QUEUE_CHANGED)
        self.wake()
        return True

    def progress(self) -> dict[int, tuple[int, int | None]]:
        with self._lock:
            return dict(self._progress)

    def speeds(self) -> dict[int, float]:
        """Current speed (bytes/s) of each active transfer."""
        with self._lock:
            return {file_id: meter.speed() for file_id, meter in self._meters.items()}

    def total_speed(self) -> float:
        return sum(self.speeds().values())

    def eta_seconds(self, file_id: int) -> float | None:
        with self._lock:
            done, total = self._progress.get(file_id, (0, None))
            meter = self._meters.get(file_id)
            speed = meter.speed() if meter else 0.0
        if not total or speed <= 0:
            return None
        return max(0.0, (total - done) / speed)

    def total_eta_seconds(self) -> float | None:
        """Time left for the transfers in progress (only those with a known size)."""
        with self._lock:
            remaining = sum(max(0, t - d) for d, t in self._progress.values() if t)
        speed = self.total_speed()
        return remaining / speed if speed > 0 and remaining else None

    # ---------------------------------------------------------- ordering
    def move_to_top(self, file_id: int) -> bool:
        """Download this file before every other waiting file."""
        item = self.repos.queue.get(file_id)
        if item is None or item.status == "active":
            return False
        _low, top = self.repos.queue.priority_bounds()
        fields: dict[str, object] = {"priority": top + 1}
        if item.status in ("waiting", "backoff", ON_HOLD):
            fields.update(status="waiting", next_attempt_at=self.clock())
            self.repos.files.update(file_id, status="queued")
        self.repos.queue.update(file_id, **fields)
        self.events.publish(EventType.QUEUE_CHANGED)
        self.wake()
        return True

    def move_to_bottom(self, file_id: int) -> bool:
        item = self.repos.queue.get(file_id)
        if item is None or item.status == "active":
            return False
        low, _high = self.repos.queue.priority_bounds()
        self.repos.queue.update(file_id, priority=low - 1)
        self.events.publish(EventType.QUEUE_CHANGED)
        return True

    def active_ids(self) -> list[int]:
        with self._lock:
            return list(self._active)

    # -------------------------------------------------------------- claiming
    def _claim(self) -> QueueItem | None:
        self.check_pause_expired()
        if self._paused:
            return None
        now = self.clock()
        paused_hosts = self.client.paused_hosts()
        with self._lock:
            if len(self._active) >= self.max_concurrent:
                return None
            per_host: dict[str, int] = {}
            for host in self._active.values():
                per_host[host] = per_host.get(host, 0) + 1
            for item in self.repos.queue.ready(now, limit=100):
                if item.file_id in self._active:
                    continue
                if item.host in paused_hosts:
                    continue
                if per_host.get(item.host, 0) >= self.max_per_host:
                    continue
                self._active[item.file_id] = item.host
                self._file_cancel[item.file_id] = threading.Event()
                self._meters[item.file_id] = SpeedMeter()
                self._progress[item.file_id] = (item.bytes_done, item.bytes_total)
                self.repos.queue.update(item.file_id, status="active")
                self.repos.files.update(item.file_id, status="downloading")
                return item
        return None

    def _release(self, file_id: int) -> None:
        with self._lock:
            self._active.pop(file_id, None)
            self._progress.pop(file_id, None)
            self._file_cancel.pop(file_id, None)
            self._meters.pop(file_id, None)
            self._hold_requested.discard(file_id)

    # --------------------------------------------------------------- workers
    def _worker(self) -> None:
        while not self._stop.is_set():
            item = self._claim()
            if item is None:
                self._wake.wait(timeout=5 if self._paused_until else 15)
                self._wake.clear()
                continue
            try:
                self.process(item)
            except Exception:  # never let a worker die
                log.exception("Unexpected error while processing file %s", item.file_id)
                self._release(item.file_id)

    def run_pending(self, max_items: int | None = None) -> int:
        """Synchronously process ready items (used by tests and the CLI)."""
        done = 0
        while max_items is None or done < max_items:
            item = self._claim()
            if item is None:
                break
            self.process(item)
            done += 1
        return done

    # ------------------------------------------------------------ processing
    def process(self, item: QueueItem) -> None:
        record = self.repos.files.get(item.file_id)
        if record is None:
            self.repos.queue.remove(item.file_id)
            self._release(item.file_id)
            return
        part = Path(item.temp_path)
        last_flush = [0.0, item.bytes_done]

        def on_progress(done: int, total: int | None) -> None:
            with self._lock:
                self._progress[item.file_id] = (done, total)
                meter = self._meters.get(item.file_id)
                if meter is not None:
                    meter.add(done)
            now_t = time.monotonic()
            if now_t - last_flush[0] > 2.0 or done - last_flush[1] > 4 * 1024 * 1024:
                last_flush[0], last_flush[1] = now_t, done
                self.repos.queue.update(item.file_id, bytes_done=done, bytes_total=total)
                self.events.publish(EventType.FILE_PROGRESS, file_id=item.file_id, done=done, total=total)

        with self._lock:
            file_cancel = self._file_cancel.setdefault(item.file_id, threading.Event())
        if self._paused:  # paused between claim and start
            file_cancel.set()
        cancel = _CancelToken(self._cancel, file_cancel)
        self.events.publish(EventType.FILE_STARTED, file_id=item.file_id, name=record.target_name)
        try:
            if cancel.is_set():
                raise DownloadCancelled("download paused before it started")
            result = self.downloader.download(
                record.source_url, part, record.sha256, record.extension, on_progress, cancel
            )
            self.finalize(record, result.path)
            self.repos.queue.remove(item.file_id)
            log.info("Downloaded %s (%d bytes, resumed from %d)", record.target_name, result.size, result.resumed_from)
        except BaseException as exc:  # noqa: BLE001 - classified below
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            self._handle_failure(item, record, part, exc)
        finally:
            self._release(item.file_id)
            self.events.publish(EventType.QUEUE_CHANGED)

    def _handle_failure(self, item: QueueItem, record: FileRecord, part: Path, exc: BaseException) -> None:
        kind = classify(exc)
        now = self.clock()
        attempts = item.attempts + (0 if kind in (ErrorClass.CANCELLED, ErrorClass.RATE_LIMITED, ErrorClass.BLOCKED) else 1)
        bytes_done = part.stat().st_size if part.exists() else 0
        message = str(exc) or exc.__class__.__name__
        common = {"attempts": attempts, "error_class": kind.value, "last_error": message[:500], "bytes_done": bytes_done}

        if kind is ErrorClass.CANCELLED:
            with self._lock:
                held = item.file_id in self._hold_requested
            common.pop("last_error")  # stopping on purpose is not an error
            common.pop("error_class")
            self.repos.queue.update(item.file_id, status=ON_HOLD if held else "waiting", **common)
            self.repos.files.update(item.file_id, status="queued")
            return

        if kind is ErrorClass.RATE_LIMITED:
            retry_after = getattr(exc, "retry_after", None)
            if isinstance(exc, HostPaused):
                wait = max(1.0, exc.until - time.time())
            else:
                wait = self.policy.delay(max(1, item.attempts), retry_after if isinstance(exc, RateLimited) else None)
                self.on_host_problem(item.host, wait, "rate limited (HTTP 429)")
            self.repos.queue.update(item.file_id, status="waiting", next_attempt_at=now + timedelta(seconds=wait), **common)
            self.repos.files.update(item.file_id, status="queued")
            return

        if kind is ErrorClass.BLOCKED:
            self.on_host_problem(item.host, -1, message)
            self.repos.queue.update(item.file_id, status="waiting", next_attempt_at=now + timedelta(minutes=5), **common)
            self.repos.files.update(item.file_id, status="queued")
            return

        if kind is ErrorClass.AUTH:
            self.repos.queue.update(item.file_id, status="paused", **common)
            self.repos.files.update(item.file_id, status="failed")
            self.events.publish(EventType.AUTH_PROBLEM, message=_("A file requires an authenticated session. "
                                "Configure cookies in Settings, then retry the file."), file_id=item.file_id)
            return

        if kind is ErrorClass.DISK:
            self.repos.queue.update(item.file_id, status="waiting", **common)
            self.repos.files.update(item.file_id, status="queued")
            self.set_paused(True, f"Local storage problem: {message}")
            self.events.publish(EventType.DISK_PROBLEM, message=message)
            return

        if kind is ErrorClass.UNAVAILABLE:
            if attempts > self.max_unavailable_rechecks:
                self.repos.queue.update(item.file_id, status="failed", **common)
                self.repos.files.update(item.file_id, status="unavailable")
            else:
                self.repos.queue.update(item.file_id, status="backoff",
                                        next_attempt_at=now + self.unavailable_recheck, **common)
                self.repos.files.update(item.file_id, status="unavailable")
            self.events.publish(EventType.FILE_FAILED, file_id=item.file_id, name=record.target_name,
                                error="original file not available on the server", retry=True)
            return

        if kind in (ErrorClass.TRANSIENT, ErrorClass.INTEGRITY) and not self.policy.exhausted(attempts):
            delay = self.policy.delay(attempts)
            self.repos.queue.update(item.file_id, status="backoff", next_attempt_at=now + timedelta(seconds=delay), **common)
            self.repos.files.update(item.file_id, status="queued")
            log.warning("Download of %s failed (%s); retry %d in %.0fs", record.target_name, message, attempts, delay)
            self.events.publish(EventType.RETRY_SCHEDULED, file_id=item.file_id, name=record.target_name,
                                attempt=attempts, delay=delay, error=message)
            return

        # Permanent, structural, or retries exhausted.
        self.repos.queue.update(item.file_id, status="failed", **common)
        self.repos.files.update(item.file_id, status="failed")
        log.error("Download of %s failed permanently: %s", record.target_name, message)
        self.events.publish(EventType.FILE_FAILED, file_id=item.file_id, name=record.target_name, error=message, retry=False)
        if kind is ErrorClass.STRUCTURE:
            self.events.publish(EventType.SITE_STRUCTURE_CHANGED, message=message)

    # ----------------------------------------------------------- manual ops
    def retry(self, file_id: int) -> bool:
        item = self.repos.queue.get(file_id)
        if item is None:
            return False
        self.repos.queue.update(file_id, status="waiting", next_attempt_at=self.clock(), attempts=0, error_class=None)
        self.repos.files.update(file_id, status="queued")
        self.wake()
        return True
