"""Forwards engine events (from worker threads) to the Qt GUI thread."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..core.events import Event, EventBus


class EventBridge(QObject):
    event = Signal(object)

    def __init__(self, bus: EventBus) -> None:
        super().__init__()
        self._unsubscribe = bus.subscribe(self._forward)

    def _forward(self, event: Event) -> None:
        # Emitting from another thread queues the call to the GUI thread.
        self.event.emit(event)

    def close(self) -> None:
        self._unsubscribe()
