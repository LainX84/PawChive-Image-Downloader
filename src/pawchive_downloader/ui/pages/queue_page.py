"""Download queue: active, waiting, retrying, on hold and failed downloads."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QMenu, QProgressBar, QPushButton, QToolButton, QVBoxLayout,
    QWidget,
)

from ...i18n import _
from ...storage.db import from_db_time
from ..icons import icon
from ..pause_controls import PauseButton, pause_state_text
from ..theme import color
from ..widgets import (
    Banner, format_bytes, format_duration, format_speed, format_when, item, make_table, page_header, selected_data,
    status_item,
)
from .base import Page

# (key, label, statuses shown)
FILTERS = (
    ("all", "All", None),
    ("active", "Active", ("active",)),
    ("pending", "Pending", ("waiting",)),
    ("retrying", "Incomplete / retrying", ("backoff",)),
    ("on_hold", "On hold", ("on_hold",)),
    ("failed", "Failed", ("failed", "paused")),
)
HOLDABLE = ("active", "waiting", "backoff", "failed", "paused")
MOVABLE = ("waiting", "backoff", "on_hold", "failed", "paused")
STATUS_LABELS = {"backoff": "retrying", "waiting": "pending", "paused": "needs action", "on_hold": "paused by you",
                 "active": "downloading", "failed": "failed"}
SUMMARY_NAMES = (("active", "{0} downloading"), ("waiting", "{0} pending"), ("backoff", "{0} retrying"),
                 ("on_hold", "{0} on hold"), ("failed", "{0} failed"), ("paused", "{0} need action"))
COLUMNS = ("File", "Work", "Author", "Status", "Progress", "Size", "Speed", "Time left", "Attempts", "Next try",
           "Last error")


class QueuePage(Page):
    title = "Queue"

    def __init__(self, engine) -> None:  # type: ignore[no-untyped-def]
        super().__init__(engine)
        self.root.addWidget(page_header(
            _("Download queue"),
            _("Files are downloaded into the temporary folder as .part files, verified with SHA-256 and only then "
              "moved into the archive. Interrupted or paused downloads continue where they stopped."),
        ))
        self.paused_banner = Banner()
        self.root.addWidget(self.paused_banner)
        top = QHBoxLayout()
        self.filter = QComboBox()
        for key, label, _statuses in FILTERS:
            self.filter.addItem(_(label), key)
        self.filter.currentIndexChanged.connect(self.refresh)
        top.addWidget(QLabel(_("Show:")))
        top.addWidget(self.filter)
        top.addStretch(1)
        self.speed = QLabel("")
        self.speed.setObjectName("SpeedLabel")
        top.addWidget(self.speed)
        self.summary = QLabel("")
        self.summary.setObjectName("Muted")
        top.addWidget(self.summary)
        self.root.addLayout(top)

        self.table = make_table([_(c) for c in COLUMNS], stretch=10)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._buttons)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.root.addWidget(self.table, 1)
        self._statuses: dict[int, str] = {}

        bar = QHBoxLayout()
        self.pause_btn = PauseButton(engine, self.refresh, object_name="Primary")
        self.hold_btn = QPushButton(_("Pause selected"))
        self.hold_btn.setToolTip(_("Put the selected files on hold; the other files keep downloading."))
        self.release_btn = QPushButton(_("Resume selected"))
        self.top_btn = QPushButton(_("Move to top"))
        self.top_btn.setToolTip(_("Download the selected files before all the others"))
        self.retry_btn = QToolButton()
        self.retry_btn.setObjectName("Plain")
        self.retry_btn.setText(_("Retry"))
        self.retry_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.retry_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        retry_menu = QMenu(self.retry_btn)
        self.retry_selected_action = retry_menu.addAction(_("Retry selected now"), self._retry)
        retry_menu.addAction(_("Retry all failed"), self._retry_all)
        self.resume_hosts_action = retry_menu.addAction(_("Resume paused file servers"), self._resume_hosts)
        retry_menu.aboutToShow.connect(self._retry_menu_state)
        self.retry_btn.setMenu(retry_menu)
        self.hold_btn.clicked.connect(self._hold)
        self.release_btn.clicked.connect(self._release)
        self.top_btn.clicked.connect(self._to_top)
        for button, name in ((self.hold_btn, "pause"), (self.release_btn, "play"), (self.top_btn, "top")):
            button.setIconSize(QSize(16, 16))
            button.setProperty("icon_name", name)
        self.retry_btn.setIconSize(QSize(16, 16))
        for b in (self.pause_btn, self.hold_btn, self.release_btn, self.top_btn, self.retry_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        self.root.addLayout(bar)
        self._buttons()

    # -------------------------------------------------------------- selection
    def _selected_statuses(self) -> list[str]:
        return [self._statuses.get(fid, "") for fid in selected_data(self.table)]  # type: ignore[arg-type]

    def _buttons(self) -> None:
        statuses = self._selected_statuses()
        self.hold_btn.setEnabled(any(s in HOLDABLE for s in statuses))
        self.release_btn.setEnabled("on_hold" in statuses)
        self.top_btn.setEnabled(any(s in MOVABLE for s in statuses))
        for button in (self.hold_btn, self.release_btn, self.top_btn):
            tone = color("text") if button.isEnabled() else color("disabled_text")
            button.setIcon(icon(button.property("icon_name"), tone, 16))
        self.retry_btn.setIcon(icon("retry", color("text"), 16))
        self.pause_btn.sync()
        if self.engine.downloads.paused:
            self.paused_banner.show_message(
                _("<b>Downloads are paused</b> — {0}. Partial .part files are kept and continue where they "
                  "stopped when you resume. Monitoring keeps finding new publications meanwhile.",
                  pause_state_text(self.engine)))
        else:
            self.paused_banner.show_message(None)

    def _retry_menu_state(self) -> None:
        self.retry_selected_action.setEnabled(bool(selected_data(self.table)))
        self.resume_hosts_action.setEnabled(bool(self.engine.http.paused_hosts()))

    # ---------------------------------------------------------------- actions
    def _for_selected(self, action) -> None:  # type: ignore[no-untyped-def]
        for file_id in selected_data(self.table):
            action(file_id)
        self.refresh()

    def _hold(self) -> None:
        self._for_selected(self.engine.hold_file)

    def _release(self) -> None:
        self._for_selected(self.engine.release_file)

    def _to_top(self) -> None:
        # Reverse, so the first selected row ends up first.
        for file_id in reversed(selected_data(self.table)):
            self.engine.move_to_top(file_id)  # type: ignore[arg-type]
        self.refresh()

    def _to_bottom(self) -> None:
        self._for_selected(self.engine.move_to_bottom)

    def _retry(self) -> None:
        self._for_selected(self.engine.retry_file)

    def _retry_all(self) -> None:
        self.engine.retry_all_failed()
        self.refresh()

    def _resume_hosts(self) -> None:
        self.engine.resume_all_hosts()
        self.refresh()

    def _context_menu(self, pos: QPoint) -> None:
        if self.table.itemAt(pos) is None:
            return
        statuses = self._selected_statuses()
        menu = QMenu(self)
        if any(s in HOLDABLE for s in statuses):
            menu.addAction(icon("pause", color("text"), 16), _("Pause"), self._hold)
        if "on_hold" in statuses:
            menu.addAction(icon("play", color("text"), 16), _("Resume"), self._release)
        if any(s in MOVABLE for s in statuses):
            menu.addAction(icon("top", color("text"), 16), _("Move to top"), self._to_top)
            menu.addAction(_("Move to bottom"), self._to_bottom)
        menu.addSeparator()
        menu.addAction(icon("retry", color("text"), 16), _("Retry now"), self._retry)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ---------------------------------------------------------------- refresh
    def refresh(self) -> None:
        key = self.filter.currentData()
        wanted = next((statuses for k, _label, statuses in FILTERS if k == key), None)
        downloads = self.engine.downloads
        progress = downloads.progress()
        speeds = downloads.speeds()
        rows = [r for r in self.engine.repos.queue.all_with_files() if wanted is None or r["status"] in wanted]
        selected = set(selected_data(self.table))
        self._statuses = {}
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            file_id, status = r["file_id"], r["status"]
            self._statuses[file_id] = status
            self.table.setItem(i, 0, item(r["target_name"], file_id))
            self.table.setItem(i, 1, item(r["work_title"] or _("(awaiting review)"), muted=not r["work_title"]))
            self.table.setItem(i, 2, item(r["author_name"]))
            label = _(STATUS_LABELS.get(status, status))
            if r["error_class"] == "unavailable" and status not in ("on_hold", "active"):
                label = _("original not available")
            done, total = progress.get(file_id, (r["bytes_done"], r["bytes_total"]))
            status_cell = status_item(status, label)
            if done and status != "active":
                status_cell.setToolTip(_("Partial file kept: {0}. The download continues from here.",
                                         format_bytes(done)))
            self.table.setItem(i, 3, status_cell)
            self.table.setCellWidget(i, 4, _progress_bar(done, total))
            size = f"{format_bytes(done)} / {format_bytes(total)}" if total else (format_bytes(done) if done else "—")
            self.table.setItem(i, 5, item(size, muted=status != "active"))
            if status == "active":
                self.table.setItem(i, 6, item(format_speed(speeds.get(file_id))))
                eta = downloads.eta_seconds(file_id)
                self.table.setItem(i, 7, item(format_duration(eta) if eta is not None else "…", muted=True))
            else:
                self.table.setItem(i, 6, item("—", muted=True))
                self.table.setItem(i, 7, item("—", muted=True))
            self.table.setItem(i, 8, item(r["attempts"]))
            nxt = from_db_time(r["next_attempt_at"])
            if status in ("backoff", "waiting"):
                when = _("paused") if downloads.paused else format_when(nxt, future=True)
            else:
                when = "—"
            self.table.setItem(i, 9, item(when, muted=True))
            self.table.setItem(i, 10, item(r["last_error"] or "", muted=True))
            if file_id in selected:
                self.table.selectRow(i)
        self.table.setColumnWidth(4, 140)
        counts = self.engine.repos.queue.counts()
        self.summary.setText(" · ".join(_(text, counts[k]) for k, text in SUMMARY_NAMES if counts.get(k))
                             or _("Queue is empty"))
        total_speed = downloads.total_speed()
        if speeds and not downloads.paused:
            eta = downloads.total_eta_seconds()
            text = "↓ " + format_speed(total_speed)
            if downloads.limiter.rate:
                text += " " + _("(limit {0})", format_speed(downloads.limiter.rate))
            if eta is not None:
                text += "  ·  " + _("{0} left", format_duration(eta))
            self.speed.setText(text + "   ")
        else:
            self.speed.setText("")
        self._buttons()


def _progress_bar(done: int, total: int | None) -> QWidget:
    bar = QProgressBar()
    bar.setTextVisible(False)
    bar.setFixedHeight(8)
    bar.setRange(0, 1000)
    bar.setValue(int(1000 * done / total) if total else 0)
    bar.setToolTip(f"{format_bytes(done)} / {format_bytes(total)}" + (f"  ({100 * done / total:.0f}%)" if total else ""))
    holder = QWidget()
    holder.setStyleSheet("background: transparent;")
    lay = QVBoxLayout(holder)
    lay.setContentsMargins(8, 0, 8, 0)
    lay.addWidget(bar)
    return holder
