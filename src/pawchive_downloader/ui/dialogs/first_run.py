"""First-time setup: choose where everything is stored."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from ...config.paths import check_writable_dir
from ...config.settings import Settings, default_base_dir
from ...i18n import _


class FirstRunDialog(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(_("Welcome to PawChive Image Downloader"))
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        title = QLabel(_("<span style='font-size:18px; font-weight:600'>Welcome!</span>"))
        layout.addWidget(title)
        text = QLabel(
            _("Choose a folder for the application's data. It will contain:<br>"
            "• <b>Archive</b> — your organized downloads<br>"
            "• <b>Temp</b> — partial and pending downloads<br>"
            "• <b>Database</b> and <b>Logs</b><br><br>"
            "Every folder can be changed individually later in Settings.")
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        row = QHBoxLayout()
        self.path = QLineEdit(str(default_base_dir()))
        browse = QPushButton(_("Browse…"))
        browse.clicked.connect(self._browse)
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        layout.addLayout(row)
        self.preview = QLabel("")
        self.preview.setObjectName("Muted")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)
        self.path.textChanged.connect(self._update_preview)
        self._update_preview()
        self.error = QLabel("")
        self.error.setObjectName("ErrorText")
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_("Start"))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, _("Choose data folder"), self.path.text())
        if folder:
            self.path.setText(str(Path(folder)))

    def _update_preview(self) -> None:
        base = Path(self.path.text().strip() or ".")
        self.preview.setText(_("These folders will be used:\n") + "\n".join(
            f"   {base / name}" for name in ("Archive", "Temp", "Database", "Logs")))

    def _accept(self) -> None:
        reason = check_writable_dir(Path(self.path.text().strip()))
        if reason:
            self.error.setText(_('This folder {0}.', reason))
            return
        self.accept()

    def settings(self) -> Settings:
        base = Path(self.path.text().strip())
        return Settings(
            archive_dir=str(base / "Archive"), temp_dir=str(base / "Temp"),
            database_dir=str(base / "Database"), logs_dir=str(base / "Logs"),
        )
