"""Common base class for main-window pages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QVBoxLayout, QWidget

if TYPE_CHECKING:
    from ...core.engine import Engine


class Page(QWidget):
    title = ""

    def __init__(self, engine: "Engine") -> None:
        super().__init__()
        self.engine = engine
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(28, 22, 28, 22)
        self.root.setSpacing(14)

    def refresh(self) -> None:
        """Reload the page from the database. Called when it becomes visible
        and periodically while relevant events arrive."""
