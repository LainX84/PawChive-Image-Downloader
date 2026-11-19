"""Reusable widgets and formatting helpers."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..i18n import _
from .theme import color, status_color


def format_bytes(value: int | None) -> str:
    if not value:
        return "0 B" if value == 0 else "—"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def format_when(value: datetime | None, future: bool = False) -> str:
    if value is None:
        return "—"
    now = datetime.now(timezone.utc)
    delta = (value - now).total_seconds() if future else (now - value).total_seconds()
    if delta < 0:
        return _("now") if future else _("just now")
    return _("in {0}", format_duration(delta)) if future else _("{0} ago", format_duration(delta))


def format_duration(seconds: float | None) -> str:
    """Compact duration: 45s, 12 min, 1.5 h, 3 d."""
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return _("{0} min", int(seconds // 60))
    if seconds < 86400:
        return f"{seconds / 3600:.1f} h".replace(".0 h", " h")
    return _("{0} d", int(seconds // 86400))


def format_speed(bytes_per_second: float | None) -> str:
    if not bytes_per_second:
        return "—"
    return f"{format_bytes(int(bytes_per_second))}/s"


def format_local(value: datetime | None) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M") if value else "—"


def open_path(path: Path) -> None:
    """Open a folder or file with the system's default application."""
    if not path.exists():
        path = path.parent if path.parent.exists() else path
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])  # noqa: S603,S607
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def page_header(title: str, subtitle: str = "") -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 8)
    layout.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("PageTitle")
    layout.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("PageSubtitle")
        s.setWordWrap(True)
        layout.addWidget(s)
    return box


class StatCard(QFrame):
    def __init__(self, label: str, tone: str | None = None) -> None:
        super().__init__()
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(2)
        self.value = QLabel("0")
        self.value.setObjectName("StatValue")
        if tone:  # coloured by the stylesheet, so it follows the theme
            self.value.setProperty("tone", tone)
        caption = QLabel(label)
        caption.setObjectName("StatLabel")
        layout.addWidget(self.value)
        layout.addWidget(caption)

    def set(self, value: object) -> None:
        self.value.setText(str(value))


class Banner(QFrame):
    def __init__(self, danger: bool = False) -> None:
        super().__init__()
        self.setObjectName("BannerDanger" if danger else "Banner")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self.label = QLabel()
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self.hide()

    def show_message(self, text: str | None) -> None:
        if text:
            self.label.setText(text)
            self.show()
        else:
            self.hide()


def status_item(status: str, text: str | None = None) -> QTableWidgetItem:
    item = QTableWidgetItem(f"●  {text or _(status.replace('_', ' '))}")
    item.setForeground(QColor(status_color(status)))
    return item


def make_table(headers: list[str], stretch: int | None = None) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.verticalHeader().setDefaultSectionSize(34)
    header = table.horizontalHeader()
    header.setHighlightSections(False)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    if stretch is not None:
        header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    return table


class SortItem(QTableWidgetItem):
    """Table cell that sorts by a hidden key (numbers, dates, sizes) instead of its text."""

    def __init__(self, text: str, key: object) -> None:
        super().__init__(text)
        self.sort_key = key

    def __lt__(self, other: QTableWidgetItem) -> bool:  # type: ignore[override]
        other_key = getattr(other, "sort_key", None)
        if other_key is None:
            return super().__lt__(other)
        try:
            return self.sort_key < other_key  # type: ignore[operator]
        except TypeError:
            return str(self.sort_key) < str(other_key)


def item(text: object, data: object = None, muted: bool = False, sort_key: object = None) -> QTableWidgetItem:
    label = "" if text is None else str(text)
    cell = SortItem(label, sort_key) if sort_key is not None else QTableWidgetItem(label)
    if data is not None:
        cell.setData(Qt.ItemDataRole.UserRole, data)
    if muted:
        cell.setForeground(QColor(color('text_muted')))
    return cell


def selected_data(table: QTableWidget) -> list[object]:
    rows = sorted({index.row() for index in table.selectedIndexes()})
    out = []
    for row in rows:
        cell = table.item(row, 0)
        if cell is not None:
            out.append(cell.data(Qt.ItemDataRole.UserRole))
    return out


def error_box(parent: QWidget, title: str, message: str) -> None:
    QMessageBox.warning(parent, title, message)


def confirm(parent: QWidget, title: str, message: str) -> bool:
    return QMessageBox.question(parent, title, message) == QMessageBox.StandardButton.Yes
