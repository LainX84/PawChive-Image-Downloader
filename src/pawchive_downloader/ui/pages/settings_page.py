"""Settings: folders, monitoring, requests, retries, session and logging."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from ...auth.session import CredentialStoreUnavailable
from ...config.paths import validate_paths
from ...config.relocate import FOLDER_SETTINGS, PENDING_KEY, plan_relocation
from ...config.settings import Settings, SettingsStore
from ...diagnostics.logging_setup import set_level
from ...i18n import LANGUAGES, language as current_language, resolve_language
from ..widgets import Banner, error_box, open_path, page_header
from .base import Page
from ...i18n import _

RESTART_FIELDS = {"archive_dir", "temp_dir", "database_dir", "logs_dir", "max_concurrent_downloads",
                  "max_downloads_per_host", "base_url"}


class PathEdit(QWidget):
    def __init__(self, value: str) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(value)
        browse = QPushButton(_("Browse…"))
        browse.clicked.connect(self._browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(browse)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, _("Choose folder"), self.edit.text())
        if folder:
            self.edit.setText(folder)

    def text(self) -> str:
        return self.edit.text().strip()


class SettingsPage(Page):
    title = "Settings"

    def __init__(self, engine, store: SettingsStore, export_diagnostics) -> None:
        super().__init__(engine)
        self.store = store
        self.export_diagnostics = export_diagnostics
        self.root.addWidget(page_header(_("Settings"), _("Folder and concurrency changes take effect after a restart.")))
        self.banner = Banner(danger=True)
        self.root.addWidget(self.banner)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(12)
        s = engine.settings

        # Interface -----------------------------------------------------
        box = QGroupBox(_("Interface"))
        form = QFormLayout(box)
        self.language = QComboBox()
        self.language.addItem(_("System language"), "system")
        for code, name in LANGUAGES.items():
            self.language.addItem(name, code)
        self.language.setCurrentIndex(max(0, self.language.findData(s.language)))
        self.theme = QComboBox()
        for code, label in (("system", "Follow the system"), ("light", "Light"), ("dark", "Dark")):
            self.theme.addItem(_(label), code)
        self.theme.setCurrentIndex(max(0, self.theme.findData(s.theme)))
        self.theme.currentIndexChanged.connect(self._preview_theme)
        self.to_tray = QCheckBox(_("Keep running in the notification area when the window is closed"))
        self.to_tray.setChecked(s.minimize_to_tray)
        self.notify = QCheckBox(_("Show a notification when a work receives new pages"))
        self.notify.setChecked(s.notify_new_pages)
        if not QSystemTrayIcon.isSystemTrayAvailable():
            for check in (self.to_tray, self.notify):
                check.setEnabled(False)
                check.setToolTip(_("This desktop has no notification area."))
        form.addRow(_("Language"), self.language)
        form.addRow(_("Theme"), self.theme)
        form.addRow("", self.to_tray)
        form.addRow("", self.notify)
        col.addWidget(box)

        # Folders -------------------------------------------------------
        box = QGroupBox(_("Folders"))
        form = QFormLayout(box)
        base_row = QWidget()
        base_layout = QHBoxLayout(base_row)
        base_layout.setContentsMargins(0, 0, 0, 0)
        self.base = PathEdit(str(Path(s.archive_dir).parent))
        fill = QPushButton(_("Use for all"))
        fill.setToolTip(_("Set Archive, Temp, Database and Logs inside this folder"))
        fill.clicked.connect(self._fill_from_base)
        base_layout.addWidget(self.base, 1)
        base_layout.addWidget(fill)
        form.addRow(_("Data folder"), base_row)
        self.archive = PathEdit(s.archive_dir)
        self.temp = PathEdit(s.temp_dir)
        self.database = PathEdit(s.database_dir)
        self.logs = PathEdit(s.logs_dir)
        form.addRow(_("Archive (completed files)"), self.archive)
        form.addRow(_("Temporary downloads"), self.temp)
        form.addRow(_("Database"), self.database)
        form.addRow(_("Logs"), self.logs)
        col.addWidget(box)

        # Monitoring ----------------------------------------------------
        box = QGroupBox(_("Monitoring"))
        form = QFormLayout(box)
        self.interval = QSpinBox()
        self.interval.setRange(30, 60 * 24 * 7)
        self.interval.setSuffix(_(" min"))
        self.interval.setValue(s.monitor_interval_minutes)
        self.startup = QCheckBox(_("Scan all monitored authors when the application starts"))
        self.startup.setChecked(s.scan_on_startup)
        self.full_days = QSpinBox()
        self.full_days.setRange(0, 365)
        self.full_days.setSuffix(_(" days"))
        self.full_days.setSpecialValueText(_("never"))
        self.full_days.setValue(s.full_rescan_days)
        self.empty_recheck = QSpinBox()
        self.empty_recheck.setRange(1, 24 * 60)
        self.empty_recheck.setSuffix(_(" h"))
        self.empty_recheck.setValue(s.empty_gallery_recheck_hours)
        self.previews_recheck = QSpinBox()
        self.previews_recheck.setRange(1, 24 * 60)
        self.previews_recheck.setSuffix(_(" h"))
        self.previews_recheck.setValue(s.previews_only_recheck_hours)
        self.max_rechecks = QSpinBox()
        self.max_rechecks.setRange(0, 100)
        self.max_rechecks.setValue(s.max_rechecks)
        form.addRow(_("Default interval between scans"), self.interval)
        form.addRow("", self.startup)
        form.addRow(_("Full rescan every"), self.full_days)
        form.addRow(_("Recheck empty galleries after"), self.empty_recheck)
        form.addRow(_("Recheck previews-only galleries after"), self.previews_recheck)
        form.addRow(_("Maximum rechecks per gallery"), self.max_rechecks)
        col.addWidget(box)

        # Requests ------------------------------------------------------
        box = QGroupBox(_("Requests and retries"))
        form = QFormLayout(box)
        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.5, 60)
        self.delay.setSingleStep(0.5)
        self.delay.setSuffix(_(" s"))
        self.delay.setValue(s.request_delay_seconds)
        self.concurrent = QSpinBox()
        self.concurrent.setRange(1, 4)
        self.concurrent.setValue(s.max_concurrent_downloads)
        self.per_host = QSpinBox()
        self.per_host.setRange(1, 4)
        self.per_host.setValue(s.max_downloads_per_host)
        self.retry_base = QSpinBox()
        self.retry_base.setRange(5, 3600)
        self.retry_base.setSuffix(_(" s"))
        self.retry_base.setValue(s.retry_base_seconds)
        self.retry_max = QSpinBox()
        self.retry_max.setRange(60, 7 * 24 * 3600)
        self.retry_max.setSuffix(_(" s"))
        self.retry_max.setValue(s.retry_max_seconds)
        self.attempts = QSpinBox()
        self.attempts.setRange(1, 50)
        self.attempts.setValue(s.max_download_attempts)
        self.blocked_pause = QSpinBox()
        self.blocked_pause.setRange(5, 24 * 60)
        self.blocked_pause.setSuffix(_(" min"))
        self.blocked_pause.setValue(s.blocked_pause_minutes)
        form.addRow(_("Delay between website requests"), self.delay)
        form.addRow(_("Maximum concurrent downloads"), self.concurrent)
        form.addRow(_("Maximum downloads per file server"), self.per_host)
        form.addRow(_("First retry after"), self.retry_base)
        form.addRow(_("Longest retry interval"), self.retry_max)
        form.addRow(_("Maximum attempts per file"), self.attempts)
        form.addRow(_("Pause after access is blocked"), self.blocked_pause)
        self.speed_limit = QSpinBox()
        self.speed_limit.setRange(0, 1024 * 1024)
        self.speed_limit.setSingleStep(256)
        self.speed_limit.setSuffix(" KB/s")
        self.speed_limit.setSpecialValueText(_("Unlimited"))
        self.speed_limit.setValue(s.max_download_speed_kbps)
        self.speed_limit.setToolTip(_("Total speed of all downloads together. Applied immediately."))
        form.addRow(_("Download speed limit"), self.speed_limit)
        col.addWidget(box)

        # Recognition ---------------------------------------------------
        box = QGroupBox(_("Artwork recognition"))
        form = QFormLayout(box)
        self.min_conf = QDoubleSpinBox()
        self.min_conf.setRange(0.0, 1.0)
        self.min_conf.setSingleStep(0.05)
        self.min_conf.setValue(s.auto_create_min_confidence)
        self.similarity = QDoubleSpinBox()
        self.similarity.setRange(0.5, 1.0)
        self.similarity.setSingleStep(0.05)
        self.similarity.setValue(s.similarity_review_threshold)
        form.addRow(_("Ask me below this confidence"), self.min_conf)
        form.addRow(_("Treat titles as similar above"), self.similarity)
        col.addWidget(box)

        # Session -------------------------------------------------------
        box = QGroupBox(_("Authentication (optional)"))
        layout = QVBoxLayout(box)
        note = QLabel(
            _("PawChive content is public, so no login is needed. Only use this if the site starts asking for an "
            "authenticated session. Cookies are stored in your operating system's credential store, never in "
            "files or logs. Use a separate browser profile for PawChive: never paste cookies of your main browser.")
        )
        note.setWordWrap(True)
        note.setObjectName("Muted")
        layout.addWidget(note)
        self.session_state = QLabel("")
        layout.addWidget(self.session_state)
        self.cookies = QPlainTextEdit()
        self.cookies.setPlaceholderText(_("name=value; name2=value2   — or paste a Netscape cookies.txt export"))
        self.cookies.setMaximumHeight(80)
        layout.addWidget(self.cookies)
        row = QHBoxLayout()
        save_cookies = QPushButton(_("Save session"))
        clear_cookies = QPushButton(_("Clear session"))
        save_cookies.clicked.connect(self._save_cookies)
        clear_cookies.clicked.connect(self._clear_cookies)
        row.addWidget(save_cookies)
        row.addWidget(clear_cookies)
        row.addStretch(1)
        layout.addLayout(row)
        col.addWidget(box)

        # Logging -------------------------------------------------------
        box = QGroupBox(_("Logging and maintenance"))
        form = QFormLayout(box)
        self.level = QComboBox()
        self.level.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.level.setCurrentText(s.log_level)
        self.backups = QSpinBox()
        self.backups.setRange(1, 60)
        self.backups.setValue(s.database_backups_to_keep)
        form.addRow(_("Log verbosity"), self.level)
        form.addRow(_("Database backups to keep"), self.backups)
        tools = QHBoxLayout()
        export = QPushButton(_("Export diagnostics…"))
        export.clicked.connect(self._export)
        open_logs = QPushButton(_("Open logs folder"))
        open_logs.clicked.connect(lambda: open_path(Path(self.engine.settings.logs_dir)))
        clean = QPushButton(_("Delete orphaned .part files"))
        clean.clicked.connect(self._clean)
        tools.addWidget(export)
        tools.addWidget(open_logs)
        tools.addWidget(clean)
        tools.addStretch(1)
        form.addRow(tools)
        col.addWidget(box)
        col.addStretch(1)
        for spin in body.findChildren(QSpinBox) + body.findChildren(QDoubleSpinBox) + [self.level, self.language, self.theme]:
            spin.setMaximumWidth(220)
        scroll.setWidget(body)
        self.root.addWidget(scroll, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        save = QPushButton(_("Save settings"))
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        actions.addWidget(save)
        self.root.addLayout(actions)

    def _preview_theme(self) -> None:
        window = self.window()
        if hasattr(window, "apply_theme"):
            window.apply_theme(self.theme.currentData())

    def _fill_from_base(self) -> None:
        base = Path(self.base.text())
        self.archive.edit.setText(str(base / "Archive"))
        self.temp.edit.setText(str(base / "Temp"))
        self.database.edit.setText(str(base / "Database"))
        self.logs.edit.setText(str(base / "Logs"))

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        session = self.engine.session
        if session is None:
            self.session_state.setText(_("Session storage unavailable."))
        elif not session.secure_store_available():
            self.session_state.setText(_("⚠ No secure credential store found on this system: sessions cannot be saved."))
        elif session.expired:
            self.session_state.setText(_("⚠ PawChive rejected the session: it has expired or is invalid. Paste new cookies."))
        else:
            self.session_state.setText(_("Session configured ✓") if session.has_session() else _("No session configured (not needed for public content)."))

    def _collect(self) -> Settings:
        current = self.engine.settings
        values = {f.name: getattr(current, f.name) for f in fields(Settings)}
        values["extra"] = dict(current.extra)
        values.update(
            archive_dir=self.archive.text(), temp_dir=self.temp.text(), database_dir=self.database.text(),
            logs_dir=self.logs.text(), monitor_interval_minutes=self.interval.value(),
            scan_on_startup=self.startup.isChecked(), full_rescan_days=self.full_days.value(),
            empty_gallery_recheck_hours=self.empty_recheck.value(),
            previews_only_recheck_hours=self.previews_recheck.value(), max_rechecks=self.max_rechecks.value(),
            request_delay_seconds=self.delay.value(), max_concurrent_downloads=self.concurrent.value(),
            max_downloads_per_host=self.per_host.value(), retry_base_seconds=self.retry_base.value(),
            retry_max_seconds=self.retry_max.value(), max_download_attempts=self.attempts.value(),
            blocked_pause_minutes=self.blocked_pause.value(), auto_create_min_confidence=self.min_conf.value(),
            similarity_review_threshold=self.similarity.value(), log_level=self.level.currentText(),
            database_backups_to_keep=self.backups.value(),
            max_download_speed_kbps=self.speed_limit.value(), language=self.language.currentData(),
            theme=self.theme.currentData(), minimize_to_tray=self.to_tray.isChecked(),
            notify_new_pages=self.notify.isChecked(),
        )
        return Settings(**values)

    def _save(self) -> None:
        new = self._collect().resolved()
        problems = validate_paths(new)
        if problems:
            self.banner.show_message(_("Cannot save:\n") + "\n".join(f"• {p.setting.replace('_', ' ')}: {p.path} {p.message}" for p in problems))
            return
        self.banner.show_message(None)
        old = self.engine.settings
        needs_restart = any(getattr(old, name) != getattr(new, name) for name in RESTART_FIELDS)
        pairs = plan_relocation({k: getattr(old, k) for k in FOLDER_SETTINGS},
                                {k: getattr(new, k) for k in FOLDER_SETTINGS})
        if pairs:
            answer = QMessageBox.question(
                self, _("Move existing data?"),
                _("The folders changed. Move the existing data to the new folders?\n\n")
                + "\n".join(f"{a}\n   → {b}" for a, b in pairs)
                + _("\n\nThe move happens when the application starts next time (open files cannot be moved). "
                "Choose No to start with empty folders instead."),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Yes:
                new.extra[PENDING_KEY] = [list(p) for p in pairs]
        self.store.save(new)
        # Apply what is safe to change while running.
        for f in fields(Settings):
            if f.name not in RESTART_FIELDS:
                setattr(old, f.name, getattr(new, f.name))
        self.engine.http._api_throttle.min_interval = new.request_delay_seconds
        self.engine.http._file_throttle.min_interval = new.request_delay_seconds / 2
        self.engine.downloads.policy.base_seconds = new.retry_base_seconds
        self.engine.downloads.policy.max_seconds = new.retry_max_seconds
        self.engine.downloads.policy.max_attempts = new.max_download_attempts
        set_level(new.log_level)
        self.engine.downloads.set_speed_limit(new.max_download_speed_kbps * 1024)
        window = self.window()
        if hasattr(window, "apply_theme"):
            window.apply_theme(new.theme)
        if resolve_language(new.language) != current_language():
            answer = QMessageBox.question(
                self, _("Settings saved"),
                _("The language changes after a restart. Restart the application now?\n\n"
                  "Downloads stop safely and continue after the restart."))
            if answer == QMessageBox.StandardButton.Yes and hasattr(window, "request_restart"):
                window.request_restart()
            return
        if new.extra.get(PENDING_KEY):
            QMessageBox.information(self, _("Settings saved"),
                                    _("Settings saved. Close and reopen the application: the data will be moved "
                                    "to the new folders at startup."))
        else:
            QMessageBox.information(self, _("Settings saved"), _("Settings saved.") + (
                _("\n\nRestart the application to apply the new folders or download limits.") if needs_restart else ""))

    def _save_cookies(self) -> None:
        if self.engine.session is None:
            return
        try:
            count = self.engine.session.set_cookies(self.cookies.toPlainText())
        except (ValueError, CredentialStoreUnavailable) as exc:
            error_box(self, _("Session not saved"), str(exc))
            return
        self.cookies.clear()
        QMessageBox.information(self, _("Session saved"), _('{0} cookie(s) stored securely.', count))
        self.refresh()

    def _clear_cookies(self) -> None:
        if self.engine.session:
            self.engine.session.clear()
        self.refresh()

    def _export(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, _("Save diagnostics to"))
        if folder:
            path = self.export_diagnostics(Path(folder))
            QMessageBox.information(self, _("Diagnostics exported"),
                                    _('Saved to:\n{0}\n\nThe file contains logs and statistics only — no cookies.', path))

    def _clean(self) -> None:
        removed = self.engine.clear_temp_orphans()
        QMessageBox.information(self, _("Temporary files"), _('{0} orphaned partial file(s) deleted.', removed))
