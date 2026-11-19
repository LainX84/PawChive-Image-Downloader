"""Background scheduler: author scans and gallery rechecks."""

from __future__ import annotations

import logging
import queue
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.engine import Engine

log = logging.getLogger(__name__)

TICK_SECONDS = 30


class Scheduler:
    """Runs one scan at a time on its own thread.

    Manual "scan now" requests are served first; then authors whose
    ``next_scan_at`` is due; then due gallery rechecks.
    """

    def __init__(self, engine: "Engine") -> None:
        self.engine = engine
        self._requests: "queue.Queue[tuple[int, bool]]" = queue.Queue()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.current_author: int | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="scheduler", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def wake(self) -> None:
        self._wake.set()

    def request_scan(self, author_id: int, full: bool = False) -> None:
        self._requests.put((author_id, full))
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # keep scheduling even after an unexpected bug
                log.exception("Scheduler tick failed")
            self._wake.wait(TICK_SECONDS)
            self._wake.clear()

    def tick(self) -> None:
        """One scheduling round (also used directly by tests)."""
        engine = self.engine
        # 1. manual requests
        while not self._stop.is_set():
            try:
                author_id, full = self._requests.get_nowait()
            except queue.Empty:
                break
            self._scan(author_id, full, manual=True)
        # 2. due authors
        for author in engine.repos.authors.due(engine.clock()):
            if self._stop.is_set() or not self._requests.empty():
                return  # serve manual requests first on the next round
            self._scan(author.id, None, manual=False)
        # 3. due rechecks (empty / previews-only galleries)
        for gallery in engine.repos.galleries.due_rechecks(engine.clock(), limit=10):
            if self._stop.is_set() or not self._requests.empty():
                return
            engine.recheck_gallery(gallery)

    def _scan(self, author_id: int, full: bool | None, manual: bool) -> None:
        self.current_author = author_id
        try:
            self.engine.scan_author(author_id, full=full, manual=manual)
        finally:
            self.current_author = None
