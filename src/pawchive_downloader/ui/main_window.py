"""Main window: grouped sidebar navigation, pages, status bar and tray icon."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QSizePolicy, QStackedWidget, QStatusBar, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from ..config.settings import SettingsStore
from ..core.engine import Engine
from ..core.events import Event, EventType
from ..i18n import _
from ..version import APP_NAME, __version__
from .icons import app_icon, icon
from .pages.about import AboutPage
from .pages.authors import AuthorsPage
from .pages.dashboard import DashboardPage
from .pages.logs_page import LogsPage
from .pages.queue_page import QueuePage
from .pages.review import ReviewPage
from .pages.settings_page import SettingsPage
from .pages.works import WorksPage
from .pause_controls import PauseButton, pause_state_text
from .qt_bridge import EventBridge
from .theme import apply_theme, color
from .tray import TrayController
from .widgets import format_bytes, format_duration, format_speed

# Sections of the sidebar: (title, [(page title, icon), ...])
SECTIONS = (
    ("Overview", (("Dashboard", "dashboard"),)),
    ("Library", (("Authors", "authors"), ("Works", "works"), ("Review", "review"))),
    ("Downloads", (("Queue", "queue"), ("Activity log", "log"))),
    ("Application", (("Settings", "settings"), ("About", "about"))),
)
PAGE_ROLE = Qt.ItemDataRole.UserRole
ICON_ROLE = Qt.ItemDataRole.UserRole + 1


class MainWindow(QMainWindow):
    def __init__(self, engine: Engine, store: SettingsStore, export_diagnostics: Callable[[Path], Path]) -> None:
        super().__init__()
        self.engine = engine
        self.store = store
        self._quitting = False
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1320, 840)
        self.setMinimumSize(QSize(1000, 640))

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(232)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 0, 0, 12)
        title = QLabel("PawChive")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Image Downloader")
        subtitle.setObjectName("AppSubtitle")
        side.addWidget(title)
        side.addWidget(subtitle)

        self.nav = QTreeWidget()
        self.nav.setHeaderHidden(True)
        self.nav.setRootIsDecorated(False)
        self.nav.setIndentation(0)
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nav.setExpandsOnDoubleClick(False)
        side.addWidget(self.nav, 1)

        self.pause_toggle = PauseButton(engine, self._pause_changed)
        self.pause_toggle.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        side.addWidget(self.pause_toggle)
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self.pause_toggle.toggle)
        self.footer = QLabel(f"v{__version__}")
        self.footer.setObjectName("AppSubtitle")
        side.addWidget(self.footer)
        layout.addWidget(sidebar)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.pages = [
            DashboardPage(engine), AuthorsPage(engine), WorksPage(engine), ReviewPage(engine), QueuePage(engine),
            LogsPage(engine), SettingsPage(engine, store, export_diagnostics), AboutPage(engine),
        ]
        by_title = {page.title: page for page in self.pages}
        self._page_items: dict[str, QTreeWidgetItem] = {}
        self._sections: list[QTreeWidgetItem] = []
        for page in self.pages:
            self.stack.addWidget(page)
        for section, entries in SECTIONS:
            header = QTreeWidgetItem([_(section).upper()])
            header.setFlags(Qt.ItemFlag.ItemIsEnabled)
            header.setData(0, PAGE_ROLE, None)
            font = header.font(0)
            font.setPointSizeF(max(7.0, font.pointSizeF() - 2))
            font.setBold(True)
            font.setLetterSpacing(font.SpacingType.PercentageSpacing, 108)
            header.setFont(0, font)
            self.nav.addTopLevelItem(header)
            self._sections.append(header)
            for page_title, icon_name in entries:
                if page_title not in by_title:
                    continue
                child = QTreeWidgetItem([_(page_title)])
                child.setData(0, PAGE_ROLE, page_title)
                child.setData(0, ICON_ROLE, icon_name)
                child.setSizeHint(0, QSize(0, 34))
                header.addChild(child)
                self._page_items[page_title] = child
            header.setExpanded(True)
        self.nav.itemClicked.connect(self._item_clicked)
        self.nav.currentItemChanged.connect(self._current_changed)
        self._style_navigation()

        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.speed_label = QLabel("")
        self.speed_label.setObjectName("SpeedLabel")
        self.status_label = QLabel("")
        self.status.addPermanentWidget(self.speed_label)
        self.status.addPermanentWidget(self.status_label)

        self.tray = TrayController(self, engine, self.bring_to_front, self.show_work, self.quit_application)
        QApplication.instance().setQuitOnLastWindowClosed(not self.tray.available)  # type: ignore[union-attr]

        self.bridge = EventBridge(engine.events)
        self.bridge.event.connect(self._on_event)
        self._dirty = True
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self.show_page("Dashboard")
        self._follow_system_theme()

    # ------------------------------------------------------------ navigation
    def current_page(self):  # type: ignore[no-untyped-def]
        return self.pages[self.stack.currentIndex()]

    def show_page(self, title: str) -> None:
        item = self._page_items.get(title)
        if item is not None:
            item.parent().setExpanded(True)
            self.nav.setCurrentItem(item)

    def show_work(self, work_id: int) -> None:
        self.bring_to_front()
        works = next(p for p in self.pages if p.title == "Works")
        works.select_work(work_id)  # type: ignore[attr-defined]
        self.show_page("Works")

    def _item_clicked(self, item: QTreeWidgetItem) -> None:
        if item.data(0, PAGE_ROLE) is None:  # section header: expand / collapse
            item.setExpanded(not item.isExpanded())
            self._style_navigation()

    def _current_changed(self, current: QTreeWidgetItem | None, previous: QTreeWidgetItem | None) -> None:
        if current is None or current.data(0, PAGE_ROLE) is None:
            if previous is not None and previous.data(0, PAGE_ROLE) is not None:
                self.nav.blockSignals(True)
                self.nav.setCurrentItem(previous)
                self.nav.blockSignals(False)
            return
        for index, page in enumerate(self.pages):
            if page.title == current.data(0, PAGE_ROLE):
                self.stack.setCurrentIndex(index)
                page.refresh()
        self._style_navigation()

    def _style_navigation(self) -> None:
        """Icons and section arrows in the colours of the current theme."""
        current = self.nav.currentItem()
        for header in self._sections:
            header.setIcon(0, icon("chevron_down" if header.isExpanded() else "chevron_right", color("section"), 14))
            header.setForeground(0, QColor(color("section")))
            for i in range(header.childCount()):
                child = header.child(i)
                active = child is current
                child.setIcon(0, icon(child.data(0, ICON_ROLE), color("accent") if active else color("text_muted")))

    def set_review_count(self, count: int) -> None:
        item = self._page_items.get("Review")
        if item is not None:
            item.setText(0, _("Review") + (f"   ({count})" if count else ""))

    # ------------------------------------------------------------------ theme
    def apply_theme(self, mode: str) -> None:
        apply_theme(QApplication.instance(), mode)
        self._style_navigation()
        self.pause_toggle.sync()
        for page in self.pages:
            page.refresh()

    def _follow_system_theme(self) -> None:
        hints = QApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(
                lambda _scheme: self.apply_theme("system") if self.engine.settings.theme == "system" else None)

    # ---------------------------------------------------------------- events
    def _pause_changed(self) -> None:
        self._dirty = True
        self.tray.update_tooltip()

    def _on_event(self, event: Event) -> None:
        self.tray.on_event(event)
        if event.type is EventType.FILE_PROGRESS:
            return  # the timer refreshes progress bars
        self._dirty = True
        messages = {
            EventType.SCAN_STARTED: lambda p: _("Scanning {0}…", p.get("name")),
            EventType.SCAN_FINISHED: lambda p: f"{p.get('name')}: {p.get('message')}",
            EventType.FILE_COMPLETED: lambda p: _("Archived {0}", p.get("path")),
            EventType.REVIEW_NEEDED: lambda p: _("Needs review: {0}", p.get("title")),
            EventType.HOST_PAUSED: lambda p: _("Paused requests to {0}: {1}", p.get("host"), p.get("reason")),
            EventType.AUTH_PROBLEM: lambda p: str(p.get("message")),
            EventType.SITE_STRUCTURE_CHANGED: lambda p: _("PawChive's format changed: {0}", p.get("message")),
            EventType.DISK_PROBLEM: lambda p: _("Storage problem: {0}", p.get("message")),
            EventType.QUEUE_STATE: lambda p: (_("Downloads paused: {0}", pause_state_text(self.engine))
                                              if p.get("paused") else _("Downloads resumed")),
        }
        if event.type in messages:
            self.status.showMessage(messages[event.type](event.payload), 8000)
        if event.type is EventType.QUEUE_STATE:
            self.pause_toggle.sync()

    def _tick(self) -> None:
        downloads = self.engine.downloads
        downloads.check_pause_expired()
        page = self.current_page()
        if self._dirty or page.title in ("Dashboard", "Queue"):
            self._dirty = False
            if self.isVisible():
                page.refresh()
        self.pause_toggle.sync()
        self.set_review_count(self.engine.repos.reviews.count_open())
        active = len(downloads.active_ids())
        scanning = self.engine.scheduler.current_author if self.engine.scheduler else None
        free = self.engine.disk_free()
        if active and not downloads.paused:
            eta = downloads.total_eta_seconds()
            limit = downloads.limiter.rate
            text = "↓ " + format_speed(downloads.total_speed())
            if limit:
                text += " / " + format_speed(limit)
            if eta is not None:
                text += "  ·  " + _("{0} left", format_duration(eta))
            self.speed_label.setText(text)
        else:
            self.speed_label.setText("")
        parts = [
            _("Scanning…") if scanning else _("Idle"),
            _("{0} downloading", active) if active else "",
            _("Downloads paused") if downloads.paused else "",
            _("{0} free", format_bytes(free)) if free is not None else "",
        ]
        self.status_label.setText("   ·   ".join(p for p in parts if p))
        self.tray.update_tooltip()

    # -------------------------------------------------------------- lifetime
    def bring_to_front(self) -> None:
        self.showNormal() if self.isMinimized() else self.show()
        self.raise_()
        self.activateWindow()

    def request_restart(self) -> None:
        """Quit and start again (used after changing the language)."""
        QApplication.instance().setProperty("restart_requested", True)  # type: ignore[union-attr]
        self.quit_application()

    def quit_application(self) -> None:
        self._quitting = True
        self.close()
        QApplication.instance().quit()  # type: ignore[union-attr]

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        if not self._quitting and self.tray.available and self.engine.settings.minimize_to_tray:
            event.ignore()
            self.hide()
            self.tray.still_running_notice()
            return
        self.timer.stop()
        self.bridge.close()
        self.tray.hide()
        super().closeEvent(event)
        QApplication.instance().quit()  # type: ignore[union-attr]
