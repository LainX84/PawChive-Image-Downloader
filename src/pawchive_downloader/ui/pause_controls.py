"""Pause / resume controls shared by the sidebar, the Queue page and the tray menu."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from PySide6.QtCore import QDateTime, Qt, QTime
from PySide6.QtWidgets import (
    QDateTimeEdit, QDialog, QDialogButtonBox, QLabel, QMenu, QToolButton, QVBoxLayout, QWidget,
)

from ..i18n import _
from .icons import icon
from .theme import color
from .widgets import format_when

DURATIONS = ((15, "15 minutes"), (30, "30 minutes"), (60, "1 hour"), (180, "3 hours"), (480, "8 hours"))


def toggle_text(paused: bool) -> str:
    return _("Resume downloads") if paused else _("Pause downloads")


def pause_state_text(engine) -> str:  # type: ignore[no-untyped-def]
    """'Paused by you · resumes at 23:00 (in 2 h)' style description."""
    downloads = engine.downloads
    if not downloads.paused:
        return ""
    reason = _(downloads.pause_reason or "Paused by you")
    until = downloads.paused_until
    if until is None:
        return reason
    local = until.astimezone()
    stamp = local.strftime("%H:%M") if local.date() == datetime.now().astimezone().date() \
        else local.strftime("%Y-%m-%d %H:%M")
    return _("{0} · resumes at {1} ({2})", reason, stamp, format_when(until, future=True))


class PauseUntilDialog(QDialog):
    """Pick the date and time when downloads should resume."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Pause downloads until…"))
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_("Downloads resume automatically at:")))
        self.edit = QDateTimeEdit()
        self.edit.setCalendarPopup(True)
        self.edit.setDisplayFormat("yyyy-MM-dd  HH:mm")
        start = QDateTime.currentDateTime().addSecs(3600)
        start.setTime(QTime(start.time().hour(), 0))
        self.edit.setDateTime(start)
        self.edit.setMinimumDateTime(QDateTime.currentDateTime())
        layout.addWidget(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_("Pause"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def until(self) -> datetime:
        return self.edit.dateTime().toPython().astimezone()  # local time with offset


def populate_pause_menu(menu: QMenu, engine, on_change: Callable[[], None], parent: QWidget | None) -> None:  # type: ignore[no-untyped-def]
    """Fill *menu* with pause/resume actions (rebuilt each time it opens)."""
    menu.clear()
    downloads = engine.downloads
    if downloads.paused:
        state = menu.addAction(pause_state_text(engine))
        state.setEnabled(False)
        menu.addAction(icon("play", color("text")), _("Resume now"), lambda: _set(engine, on_change, False))
        menu.addSeparator()
    else:
        menu.addAction(icon("pause", color("text")), _("Pause until resumed"),
                       lambda: _set(engine, on_change, True))
    for minutes, label in DURATIONS:
        menu.addAction(icon("clock", color("text_muted")), _("Pause for {0}", _(label)),
                       lambda m=minutes: _set(engine, on_change, True, timedelta(minutes=m)))
    menu.addAction(_("Pause until…"), lambda: _ask_until(engine, on_change, parent))


def _set(engine, on_change, paused: bool, duration: timedelta | None = None) -> None:  # type: ignore[no-untyped-def]
    until = datetime.now().astimezone() + duration if duration else None
    engine.downloads.set_paused(paused, until=until)
    on_change()


def _ask_until(engine, on_change, parent) -> None:  # type: ignore[no-untyped-def]
    dialog = PauseUntilDialog(parent)
    if dialog.exec() == QDialog.DialogCode.Accepted:
        engine.downloads.set_paused(True, until=dialog.until())
        on_change()


class PauseButton(QToolButton):
    """Click: pause / resume. Arrow: pause for a while or until a time."""

    def __init__(self, engine, on_change: Callable[[], None] | None = None, object_name: str = "PauseToggle") -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.engine = engine
        self._on_change = on_change or (lambda: None)
        self.setObjectName(object_name)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.menu_ = QMenu(self)
        self.menu_.aboutToShow.connect(lambda: populate_pause_menu(self.menu_, engine, self._changed, self))
        self.setMenu(self.menu_)
        self.clicked.connect(self.toggle)
        self.sync()

    def toggle(self) -> None:
        self.engine.downloads.set_paused(not self.engine.downloads.paused)
        self._changed()

    def _changed(self) -> None:
        self.sync()
        self._on_change()

    def sync(self) -> None:
        paused = self.engine.downloads.paused
        self.setText(toggle_text(paused))
        if self.objectName() == "Primary":
            tone = color("on_accent")
        else:
            tone = color("warning") if paused else color("text")
        self.setIcon(icon("play" if paused else "pause", tone))
        self.setToolTip(pause_state_text(self.engine) if paused else
                        _("Stop every download now (Ctrl+P). Partial files are kept and resume later. "
                          "Use the arrow to pause for a while."))
        if self.property("paused") != paused:
            self.setProperty("paused", paused)
            self.style().unpolish(self)
            self.style().polish(self)
