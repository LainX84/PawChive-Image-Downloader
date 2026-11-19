"""Live log view (already redacted)."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit

from ...diagnostics.logging_setup import memory_handler
from ..theme import color
from ..widgets import item, make_table, page_header
from .base import Page
from ...i18n import _

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


class LogsPage(Page):
    title = "Activity log"  # navigation key, translated for display

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.root.addWidget(page_header(_("Activity log"), _("Recent events. Cookies and tokens are always masked.")))
        bar = QHBoxLayout()
        self.level = QComboBox()
        self.level.addItems(["INFO", "WARNING", "ERROR"])
        self.level.currentIndexChanged.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Filter…"))
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(QLabel(_("Level:")))
        bar.addWidget(self.level)
        bar.addWidget(self.search, 1)
        self.root.addLayout(bar)
        self.table = make_table([_("Time"), _("Level"), _("Component"), _("Message")], stretch=3)
        self.root.addWidget(self.table, 1)

    def refresh(self) -> None:
        handler = memory_handler()
        records = handler.snapshot() if handler else []
        minimum = _LEVELS[self.level.currentText()]
        needle = self.search.text().strip().lower()
        rows = [r for r in reversed(records) if _LEVELS.get(r[1], 0) >= minimum and (not needle or needle in r[3].lower())][:1000]
        self.table.setRowCount(len(rows))
        for i, (created, level, logger, message) in enumerate(rows):
            self.table.setItem(i, 0, item(datetime.fromtimestamp(created).strftime("%H:%M:%S"), muted=True))
            lvl = item(level)
            lvl.setForeground(QColor(color("danger") if level in ("ERROR", "CRITICAL") else color("warning") if level == "WARNING" else color("text_muted")))
            self.table.setItem(i, 1, lvl)
            self.table.setItem(i, 2, item(logger, muted=True))
            self.table.setItem(i, 3, item(message))
