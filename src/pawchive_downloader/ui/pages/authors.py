"""Authors: add, remove, pause/resume, scan, intervals."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QThreadPool, QRunnable, QObject, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
)

from ...core.engine import AddAuthorResult, EngineError
from ..widgets import (
    confirm, error_box, format_bytes, format_local, format_when, item, make_table, open_path, page_header,
    selected_data, status_item,
)

USAGE_REFRESH_SECONDS = 60
from .base import Page
from ...i18n import _


class _Signals(QObject):
    done = Signal(object, object)  # result, error


class _Task(QRunnable):
    """Runs a blocking engine call off the GUI thread."""

    def __init__(self, fn, *args) -> None:
        super().__init__()
        self.fn, self.args = fn, args
        self.signals = _Signals()

    def run(self) -> None:
        try:
            self.signals.done.emit(self.fn(*self.args), None)
        except Exception as exc:  # noqa: BLE001 - shown to the user
            self.signals.done.emit(None, exc)


class AuthorsPage(Page):
    title = "Authors"

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.root.addWidget(page_header(
            _("Authors"), _("Paste a PawChive author profile URL (or any of their post URLs) to start monitoring.")))

        add_row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText(_("https://pawchive.pw/patreon/user/12345678"))
        self.url.returnPressed.connect(self._add)
        self.add_button = QPushButton(_("Add author"))
        self.add_button.setObjectName("Primary")
        self.add_button.clicked.connect(self._add)
        add_row.addWidget(self.url, 1)
        add_row.addWidget(self.add_button)
        self.root.addLayout(add_row)
        self.hint = QLabel("")
        self.hint.setObjectName("Muted")
        self.root.addWidget(self.hint)

        self.table = make_table(
            [_("Author"), _("Service"), _("Status"), _("Monitoring"), _("Interval"), _("Local size"), _("Files"),
             _("Last successful scan"), _("Last result"), _("Next scan")],
            stretch=8,
        )
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.doubleClicked.connect(lambda _: self._open_folder())
        self.root.addWidget(self.table, 1)
        self.total_label = QLabel("")
        self.total_label.setObjectName("Muted")
        self.root.addWidget(self.total_label)

        # Folder sizes are measured on disk in the background and cached.
        self._usage: dict[int, tuple[int, int]] = {}
        self._usage_at = 0.0
        self._usage_running = False

        buttons = QHBoxLayout()
        self.scan_btn = QPushButton(_("Scan now"))
        self.full_btn = QPushButton(_("Full rescan"))
        self.pause_btn = QPushButton(_("Pause"))
        self.interval_btn = QPushButton(_("Interval…"))
        self.folder_btn = QPushButton(_("Open folder"))
        self.profile_btn = QPushButton(_("Open profile"))
        self.rebuild_btn = QPushButton(_("Rebuild archive…"))
        self.rebuild_btn.setToolTip(_("Recognize all publications again and move the files to the right folders"))
        self.remove_btn = QPushButton(_("Remove"))
        self.remove_btn.setObjectName("Danger")
        for b, slot in ((self.scan_btn, self._scan), (self.full_btn, self._full), (self.pause_btn, self._toggle),
                        (self.interval_btn, self._interval), (self.folder_btn, self._open_folder),
                        (self.profile_btn, self._open_profile), (self.rebuild_btn, self._rebuild),
                        (self.remove_btn, self._remove)):
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch(1)
        self.root.addLayout(buttons)
        self._update_buttons()

    # ----------------------------------------------------------- helpers
    def _selected(self):
        ids = selected_data(self.table)
        return [a for a in (self.engine.repos.authors.get(i) for i in ids) if a]  # type: ignore[arg-type]

    def _update_buttons(self) -> None:
        selected = self._selected()
        for b in (self.scan_btn, self.full_btn, self.pause_btn, self.interval_btn, self.folder_btn,
                  self.profile_btn, self.rebuild_btn, self.remove_btn):
            b.setEnabled(bool(selected))
        if selected:
            self.pause_btn.setText(_("Resume") if not selected[0].monitoring_enabled else _("Pause"))

    # ------------------------------------------------------------ actions
    def _add(self, confirmed: bool = False) -> None:
        text = self.url.text().strip()
        if not text:
            return
        self.add_button.setEnabled(False)
        self.hint.setText(_("Contacting PawChive…"))
        task = _Task(self.engine.add_author, text, confirmed)
        task.signals.done.connect(self._added)
        QThreadPool.globalInstance().start(task)

    def _added(self, result: AddAuthorResult | None, error: Exception | None) -> None:
        self.add_button.setEnabled(True)
        if error is not None:
            self.hint.setText("")
            error_box(self, _("Cannot add author"), str(error) if isinstance(error, EngineError) else _('Unexpected error: {0}', error))
            return
        assert result is not None
        if result.already_monitored:
            self.hint.setText(result.message)
            return
        if result.needs_confirmation:
            answer = QMessageBox.question(self, _("Add author?"), result.message)
            if answer == QMessageBox.StandardButton.Yes:
                self._add(confirmed=True)
            else:
                self.hint.setText("")
            return
        self.url.clear()
        self.hint.setText(result.message)
        self.refresh()

    def _scan(self) -> None:
        for author in self._selected():
            self.engine.request_scan(author.id)
        self.hint.setText(_("Scan requested."))

    def _full(self) -> None:
        for author in self._selected():
            self.engine.request_scan(author.id, full=True)
        self.hint.setText(_("Full rescan requested."))

    def _toggle(self) -> None:
        selected = self._selected()
        if not selected:
            return
        enable = not selected[0].monitoring_enabled
        for author in selected:
            self.engine.set_monitoring(author.id, enable)
        self.refresh()

    def _interval(self) -> None:
        selected = self._selected()
        if not selected:
            return
        current = selected[0].scan_interval_min or self.engine.settings.monitor_interval_minutes
        minutes, ok = QInputDialog.getInt(
            self, _("Monitoring interval"),
            _("Minutes between scans for the selected author(s).\nUse 0 to follow the global setting."),
            current, 0, 60 * 24 * 30, 30,
        )
        if ok:
            for author in selected:
                self.engine.set_author_interval(author.id, minutes or None)
            self.refresh()

    def _open_folder(self) -> None:
        for author in self._selected()[:1]:
            open_path(self.engine.author_dir(author))

    def _open_profile(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        for author in self._selected()[:1]:
            QDesktopServices.openUrl(QUrl(author.profile_url))

    def _rebuild(self) -> None:
        from ..dialogs.rebuild import RebuildDialog

        selected = self._selected()
        if selected:
            RebuildDialog(self, self.engine, selected[0]).exec()
            self._usage_at = 0.0
            self.refresh()

    def _remove(self) -> None:
        selected = self._selected()
        if not selected:
            return
        names = ", ".join(a.name for a in selected)
        if confirm(self, _("Remove author"), _('Stop monitoring {0}?\n\nAlready archived files stay on disk; pending downloads for this author are cancelled.', names)):
            for author in selected:
                self.engine.remove_author(author.id)
            self.refresh()

    # ------------------------------------------------------- folder sizes
    def _measure_usage(self) -> dict[int, tuple[int, int]]:
        return {a.id: self.engine.author_disk_usage(a) for a in self.engine.repos.authors.all()}

    def _start_usage_scan(self, force: bool = False) -> None:
        if self._usage_running or (not force and time.monotonic() - self._usage_at < USAGE_REFRESH_SECONDS):
            return
        self._usage_running = True
        task = _Task(self._measure_usage)
        task.signals.done.connect(self._usage_done)
        QThreadPool.globalInstance().start(task)

    def _usage_done(self, result: dict[int, tuple[int, int]] | None, error: Exception | None) -> None:
        self._usage_running = False
        self._usage_at = time.monotonic()
        if result is not None:
            self._usage = result
            self._fill_usage()

    def _fill_usage(self) -> None:
        total_bytes = total_files = 0
        for row in range(self.table.rowCount()):
            cell = self.table.item(row, 0)
            if cell is None:
                continue
            usage = self._usage.get(cell.data(Qt.ItemDataRole.UserRole))
            if usage is None:
                self.table.setItem(row, 5, item("…", muted=True))
                self.table.setItem(row, 6, item("…", muted=True))
                continue
            size, files = usage
            total_bytes += size
            total_files += files
            size_cell = item(format_bytes(size))
            size_cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            size_cell.setToolTip(_('{0:,} bytes on disk', size))
            files_cell = item(f"{files:,}")
            files_cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, 5, size_cell)
            self.table.setItem(row, 6, files_cell)
        if self._usage:
            self.total_label.setText(
                _('Archive total: {0} in {1:,} files  ·  sizes measured on disk, updated every minute', format_bytes(total_bytes), total_files))

    # ------------------------------------------------------------ refresh
    def refresh(self) -> None:
        selected = set(selected_data(self.table))
        authors = self.engine.repos.authors.all()
        self.table.setRowCount(len(authors))
        default_interval = self.engine.settings.monitor_interval_minutes
        for row, a in enumerate(authors):
            self.table.setItem(row, 0, item(a.name, a.id))
            self.table.setItem(row, 1, item(f"{a.service} · {a.creator_id}", muted=True))
            status = a.status if a.monitoring_enabled else "paused"
            text = status
            if status == "idle":
                text = "ok"
            self.table.setItem(row, 2, status_item(status, text))
            self.table.item(row, 2).setToolTip(a.status_message or "")
            self.table.setItem(row, 3, item(_("On") if a.monitoring_enabled else _("Paused")))
            minutes = a.scan_interval_min or default_interval
            label = f"{minutes // 60} h" if minutes % 60 == 0 else _("{0} min", minutes)
            self.table.setItem(row, 4, item(label + ("" if a.scan_interval_min else _(" (default)")), muted=not a.scan_interval_min))
            self.table.setItem(row, 7, item(f"{format_local(a.last_success_at)}  ·  {format_when(a.last_success_at)}"))
            summary = a.last_scan_summary or {}
            self.table.setItem(row, 8, item(summary.get("message", "—"), muted=True))
            self.table.setItem(row, 9, item(format_when(a.next_scan_at, future=True) if a.monitoring_enabled else "—"))
            if a.id in selected:
                self.table.selectRow(row)
        self.table.horizontalHeader().setStretchLastSection(False)
        self._fill_usage()
        self._start_usage_scan(force=any(a.id not in self._usage for a in authors))
        self._update_buttons()
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setSortIndicatorShown(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
