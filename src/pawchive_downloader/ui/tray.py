"""Notification-area (system tray) icon, its menu and desktop notifications."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..core.events import Event, EventType
from ..i18n import _
from ..version import APP_NAME
from .icons import app_icon, icon
from .pause_controls import pause_state_text, populate_pause_menu, toggle_text
from .theme import color
from .widgets import format_speed

NOTIFY_DELAY_MS = 8000  # pages published together arrive in a burst: wait, then notify once


class TrayController(QObject):
    """Owns the tray icon. ``available`` is False on desktops without a tray."""

    def __init__(self, window, engine, show_window: Callable[[], None], show_work: Callable[[int], None],  # type: ignore[no-untyped-def]
                 quit_app: Callable[[], None]) -> None:
        super().__init__(window)
        self.window = window
        self.engine = engine
        self.show_window = show_window
        self.show_work = show_work
        self.quit_app = quit_app
        self.available = QSystemTrayIcon.isSystemTrayAvailable()
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.menu = QMenu()
        self.menu.aboutToShow.connect(self._build_menu)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self.tray.messageClicked.connect(self._message_clicked)
        self._pending: dict[int, dict] = {}  # work_id -> {"title", "pages": [...], "count"}
        self._last_work: int | None = None
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.timeout.connect(self._flush)
        self._told_still_running = False
        if self.available:
            self.tray.show()
        self.update_tooltip()

    # ------------------------------------------------------------------ menu
    def _build_menu(self) -> None:
        self.menu.clear()
        self.menu.addAction(app_icon(), _("Show {0}", APP_NAME), self.show_window)
        self.menu.addSeparator()
        paused = self.engine.downloads.paused
        self.menu.addAction(icon("play" if paused else "pause", color("text")), toggle_text(paused), self._toggle)
        timed = self.menu.addMenu(icon("clock", color("text")), _("Pause for a while"))
        populate_pause_menu(timed, self.engine, self.update_tooltip, None)
        self.menu.addAction(_("Scan all authors now"), self._scan_all)
        self.menu.addSeparator()
        self.menu.addAction(_("Quit"), self.quit_app)

    def _toggle(self) -> None:
        self.engine.downloads.set_paused(not self.engine.downloads.paused)
        self.update_tooltip()

    def _scan_all(self) -> None:
        for author in self.engine.repos.authors.all():
            if author.monitoring_enabled:
                self.engine.request_scan(author.id)

    def _activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def update_tooltip(self) -> None:
        downloads = self.engine.downloads
        lines = [APP_NAME]
        if downloads.paused:
            lines.append(_("Downloads paused") + " — " + pause_state_text(self.engine))
        else:
            active = len(downloads.active_ids())
            if active:
                lines.append(_("{0} downloading · {1}", active, format_speed(downloads.total_speed())))
        self.tray.setToolTip("\n".join(lines))

    # --------------------------------------------------------- notifications
    def on_event(self, event: Event) -> None:
        if event.type is not EventType.FILE_COMPLETED or not event.payload.get("fresh"):
            return
        if not self.engine.settings.notify_new_pages or not self.available:
            return
        work_id = event.payload.get("work_id")
        if work_id is None:
            return
        entry = self._pending.setdefault(work_id, {"title": event.payload.get("work_title") or "", "pages": [],
                                                   "count": 0})
        entry["count"] += 1
        if event.payload.get("page") is not None:
            entry["pages"].append(event.payload["page"])
        self._flush_timer.start(NOTIFY_DELAY_MS)

    def _flush(self) -> None:
        pending, self._pending = self._pending, {}
        if not pending:
            return
        if len(pending) == 1:
            work_id, entry = next(iter(pending.items()))
            pages = sorted(set(entry["pages"]))
            if pages:
                shown = ", ".join(str(p) for p in pages[:8]) + ("…" if len(pages) > 8 else "")
                body = (_("New page {0}", shown) if entry["count"] == 1
                        else _("{0} new files · pages {1}", entry["count"], shown))
            else:
                body = _("{0} new file(s)", entry["count"])
            self._last_work = work_id
            self.tray.showMessage(entry["title"], body, app_icon(), 8000)
        else:
            total = sum(e["count"] for e in pending.values())
            titles = sorted(pending.values(), key=lambda e: -e["count"])
            body = "\n".join(f"• {e['title']} (+{e['count']})" for e in titles[:5])
            if len(titles) > 5:
                body += "\n" + _("…and {0} more", len(titles) - 5)
            self._last_work = None
            self.tray.showMessage(_("{0} new files in {1} works", total, len(pending)), body, app_icon(), 10000)

    def _message_clicked(self) -> None:
        if self._last_work is not None:
            self.show_work(self._last_work)
        else:
            self.show_window()

    def still_running_notice(self) -> None:
        """Shown once when the window is closed but the application keeps working."""
        if self._told_still_running or not self.available:
            return
        self._told_still_running = True
        self.tray.showMessage(APP_NAME, _("Still running in the notification area. Right-click the icon to "
                                          "pause downloads or quit."), app_icon(), 6000)

    def hide(self) -> None:
        self.tray.hide()
