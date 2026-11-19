"""A tiny thread-safe publish/subscribe bus.

The engine publishes events from worker threads; the UI (or tests) subscribe.
Subscribers must return quickly; the Qt bridge forwards to the GUI thread.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class EventType(str, Enum):
    SCAN_STARTED = "scan.started"
    SCAN_FINISHED = "scan.finished"
    GALLERY_DISCOVERED = "gallery.discovered"
    GALLERY_EMPTY = "gallery.empty"
    GALLERY_PREVIEWS_ONLY = "gallery.previews_only"
    WORK_RECOGNIZED = "work.recognized"
    REVIEW_NEEDED = "review.needed"
    REVIEW_RESOLVED = "review.resolved"
    FILE_QUEUED = "file.queued"
    FILE_STARTED = "file.started"
    FILE_PROGRESS = "file.progress"
    FILE_COMPLETED = "file.completed"
    FILE_FAILED = "file.failed"
    RETRY_SCHEDULED = "retry.scheduled"
    QUEUE_CHANGED = "queue.changed"
    QUEUE_STATE = "queue.state"
    HOST_PAUSED = "host.paused"
    AUTH_PROBLEM = "auth.problem"
    NETWORK_ERROR = "net.error"
    DISK_PROBLEM = "disk.problem"
    SITE_STRUCTURE_CHANGED = "site.structure_changed"
    AUTHORS_CHANGED = "authors.changed"
    WORKS_CHANGED = "works.changed"


@dataclass(frozen=True)
class Event:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


Subscriber = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[Subscriber] = []

    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def publish(self, event_type: EventType, **payload: Any) -> None:
        event = Event(event_type, payload)
        with self._lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:  # a broken subscriber must not break the engine
                log.exception("Event subscriber failed for %s", event_type.value)
