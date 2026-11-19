"""Application look: calm light and dark themes with one accent colour.

Colours live in :data:`PALETTES`; :func:`apply_theme` builds the stylesheet for
the chosen mode ("system", "dark" or "light") and installs it. Widgets that
paint their own colours ask :func:`color` at paint/refresh time, so switching
theme while the application runs needs no restart.
"""

from __future__ import annotations

PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "accent": "#8b7cf6", "accent_hover": "#a194ff", "bg": "#14161b", "surface": "#1c1f26",
        "surface_2": "#242832", "border": "#2e3340", "text": "#e7e9ee", "text_muted": "#9aa1b2",
        "success": "#4cc38a", "warning": "#f0b44c", "danger": "#ef6a6a", "info": "#5aa9f0",
        "hover": "#20242c", "banner_bg": "#2a2333", "banner_border": "#4a3d66", "danger_bg": "#33232a",
        "danger_border": "#66404b", "disabled_text": "#5c6273", "disabled_border": "#262a33",
        "on_accent": "#0e0e14", "alternate": "#1f222a", "list_line": "#23262f", "selection": "#2d2a45",
        "progress_bg": "#303544", "indicator_border": "#4a5063", "indeterminate": "#5a4fa0", "scroll": "#353a47",
        "link": "#a194ff", "section": "#7d8497",
    },
    "light": {
        "accent": "#6d5ce8", "accent_hover": "#5a48da", "bg": "#f4f5f8", "surface": "#ffffff",
        "surface_2": "#eef0f5", "border": "#d9dce5", "text": "#1d2030", "text_muted": "#646b7e",
        "success": "#1f9d63", "warning": "#b7791f", "danger": "#d64545", "info": "#2f7fd1",
        "hover": "#e8eaf1", "banner_bg": "#f0edff", "banner_border": "#cfc6fb", "danger_bg": "#fdecec",
        "danger_border": "#f2bcbc", "disabled_text": "#a5abba", "disabled_border": "#e3e5ec",
        "on_accent": "#ffffff", "alternate": "#f8f9fb", "list_line": "#eceef3", "selection": "#e6e1ff",
        "progress_bg": "#e1e4ec", "indicator_border": "#b9bfcd", "indeterminate": "#b3a9f5", "scroll": "#c9cdd8",
        "link": "#5a48da", "section": "#8a90a2",
    },
}
THEME_MODES = ("system", "light", "dark")

_STATUS_ROLES = {
    "idle": "success", "ok": "success", "complete": "success", "active": "info", "scanning": "info",
    "downloading": "info", "queued": "text_muted", "waiting": "text_muted", "pending": "text_muted",
    "held": "warning", "awaiting_review": "warning", "awaiting_full": "warning", "backoff": "warning",
    "paused": "warning", "on_hold": "text_muted", "blocked": "danger", "error": "danger", "failed": "danger",
    "unavailable": "warning", "not_found": "danger", "partial": "warning", "empty": "text_muted",
    "duplicate": "text_muted", "auth": "danger",
}

_current = "dark"


def current_mode() -> str:
    """The effective palette: "dark" or "light"."""
    return _current


def color(name: str) -> str:
    return PALETTES[_current][name]


def status_color(status: str) -> str:
    return color(_STATUS_ROLES.get(status, "text_muted"))


def system_prefers_dark() -> bool:
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Light:
            return False
        if scheme == Qt.ColorScheme.Dark:
            return True
        palette = QGuiApplication.palette()
        return palette.window().color().lightness() < 128
    except Exception:  # noqa: BLE001 - no GUI yet
        return True


def effective_mode(mode: str) -> str:
    if mode in ("dark", "light"):
        return mode
    return "dark" if system_prefers_dark() else "light"


def _arrow_files(mode: str) -> dict[str, str]:
    """Small arrow images for combo and spin boxes, painted in the theme colour."""
    import tempfile
    from pathlib import Path

    from .icons import icon

    folder = Path(tempfile.gettempdir()) / "pawchive-downloader-ui"
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, glyph in (("down", "chevron_down"), ("up", "chevron_up")):
        path = folder / f"{name}-{mode}.png"
        icon(glyph, PALETTES[mode]["text_muted"], 12).pixmap(12, 12).save(str(path))
        out[name] = path.as_posix()
    return out


def build_stylesheet(mode: str, arrows: dict[str, str] | None = None) -> str:
    p = PALETTES[mode]
    extra = ""
    if arrows:
        extra = f"""
QComboBox::drop-down {{{{ border: none; width: 24px; subcontrol-origin: padding; subcontrol-position: center right; }}}}
QComboBox::down-arrow {{{{ image: url("{arrows['down']}"); width: 12px; height: 12px; }}}}
QSpinBox, QDoubleSpinBox {{{{ padding-right: 22px; }}}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{{{ subcontrol-origin: border; subcontrol-position: top right;
    width: 20px; border: none; background: transparent; }}}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{{{ subcontrol-origin: border; subcontrol-position: bottom right;
    width: 20px; border: none; background: transparent; }}}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{{{ image: url("{arrows['up']}"); width: 10px; height: 10px; }}}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{{{ image: url("{arrows['down']}"); width: 10px; height: 10px; }}}}
QDateTimeEdit {{{{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 6px 8px; }}}}
""".replace("{{{{", "{{").replace("}}}}", "}}").replace("{{", "{").replace("}}", "}")
    main = f"""
* {{ font-size: 13px; }}
QWidget {{ background: {p['bg']}; color: {p['text']}; }}
QMainWindow::separator {{ background: {p['border']}; width: 1px; }}
#Sidebar {{ background: {p['surface']}; border-right: 1px solid {p['border']}; }}
#AppTitle {{ font-size: 15px; font-weight: 600; padding: 18px 16px 4px 16px; background: transparent; }}
#AppSubtitle {{ color: {p['text_muted']}; padding: 0 16px 14px 16px; font-size: 11px; background: transparent; }}
#PageTitle {{ font-size: 20px; font-weight: 600; background: transparent; }}
#PageSubtitle {{ color: {p['text_muted']}; background: transparent; }}
#Card {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 12px; }}
#Card QLabel {{ background: transparent; }}
#StatValue {{ font-size: 26px; font-weight: 600; }}
#StatLabel {{ color: {p['text_muted']}; font-size: 12px; }}
#Muted {{ color: {p['text_muted']}; background: transparent; }}
#Banner {{ background: {p['banner_bg']}; border: 1px solid {p['banner_border']}; border-radius: 10px; padding: 10px 12px; }}
#Banner QLabel {{ background: transparent; }}
#BannerDanger {{ background: {p['danger_bg']}; border: 1px solid {p['danger_border']}; border-radius: 10px; padding: 10px 12px; }}
#BannerDanger QLabel {{ background: transparent; }}
QPushButton {{ background: {p['surface_2']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {p['accent']}; }}
QPushButton:disabled {{ color: {p['disabled_text']}; border-color: {p['disabled_border']}; }}
QPushButton#Primary {{ background: {p['accent']}; border: none; color: {p['on_accent']}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {p['accent_hover']}; }}
QPushButton#Danger {{ color: {p['danger']}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 6px 8px;
    selection-background-color: {p['accent']}; selection-color: {p['on_accent']}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {p['accent']}; }}
QComboBox QAbstractItemView {{ background: {p['surface']}; border: 1px solid {p['border']}; selection-background-color: {p['surface_2']}; }}
QTableWidget, QTreeWidget, QListWidget {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px;
    gridline-color: transparent; alternate-background-color: {p['alternate']}; outline: 0; }}
QTableWidget::item, QTreeWidget::item {{ padding: 6px; border: none; }}
QListWidget::item {{ padding: 8px 10px; border-bottom: 1px solid {p['list_line']}; }}
QTableWidget::item:selected, QTreeWidget::item:selected, QListWidget::item:selected {{ background: {p['selection']}; color: {p['text']}; }}
QHeaderView::section {{ background: {p['surface']}; color: {p['text_muted']}; border: none; border-bottom: 1px solid {p['border']};
    padding: 8px 6px; font-weight: 600; font-size: 12px; }}
QTableCornerButton::section {{ background: {p['surface']}; border: none; }}
QProgressBar {{ background: {p['progress_bg']}; border: none; border-radius: 4px; }}
QProgressBar::chunk {{ background: {p['accent']}; border-radius: 4px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {p['text_muted']}; padding: 8px 14px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {p['text']}; border-bottom: 2px solid {p['accent']}; }}
QGroupBox {{ border: 1px solid {p['border']}; border-radius: 10px; margin-top: 14px; padding: 14px 12px 10px 12px; background: {p['surface']}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {p['text_muted']}; background: {p['bg']}; }}
QGroupBox QLabel, QGroupBox QCheckBox {{ background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {p['border']}; background: {p['surface_2']}; }}
QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}
QTreeView::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 1px solid {p['indicator_border']}; background: {p['surface_2']}; }}
QTreeView::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}
QTreeView::indicator:indeterminate {{ background: {p['indeterminate']}; border-color: {p['accent']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['scroll']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['scroll']}; border-radius: 4px; min-width: 30px; }}
QStatusBar {{ background: {p['surface']}; color: {p['text_muted']}; border-top: 1px solid {p['border']}; }}
QStatusBar QLabel {{ background: transparent; color: {p['text_muted']}; }}
QSplitter::handle {{ background: {p['bg']}; }}
QToolTip {{ background: {p['surface_2']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 6px; }}
QMenu {{ background: {p['surface']}; border: 1px solid {p['border']}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p['surface_2']}; }}
QScrollArea {{ border: none; }}
#Sidebar QTreeWidget {{ background: transparent; border: none; outline: 0; }}
#Sidebar QTreeWidget::item {{ border: none; padding: 7px 6px; margin: 1px 8px; border-radius: 8px; color: {p['text_muted']}; }}
#Sidebar QTreeWidget::item:selected {{ background: {p['surface_2']}; color: {p['text']}; }}
#Sidebar QTreeWidget::item:hover:!selected {{ background: {p['hover']}; }}
#Sidebar QTreeWidget::branch {{ background: transparent; border: none; image: none; }}
#Sidebar QToolButton#PauseToggle {{ margin: 0 12px 10px 12px; background: {p['surface_2']}; border: 1px solid {p['border']};
    border-radius: 8px; padding: 7px 10px; color: {p['text']}; }}
#Sidebar QToolButton#PauseToggle:hover {{ border-color: {p['accent']}; }}
#Sidebar QToolButton#PauseToggle[paused="true"] {{ color: {p['warning']}; border-color: {p['warning']}; }}
#Sidebar QToolButton#PauseToggle::menu-button {{ border: none; width: 22px; }}
#StatValue[tone="accent"] {{ color: {p['accent']}; }}
#StatValue[tone="success"] {{ color: {p['success']}; }}
#StatValue[tone="danger"] {{ color: {p['danger']}; }}
#StatValue[tone="warning"] {{ color: {p['warning']}; }}
QToolButton#Primary {{ background: {p['accent']}; border: none; color: {p['on_accent']}; font-weight: 600;
    border-radius: 8px; padding: 7px 12px; }}
QToolButton#Primary:hover {{ background: {p['accent_hover']}; }}
QToolButton#Primary::menu-button {{ border: none; width: 22px; }}
QToolButton#Plain {{ background: {p['surface_2']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 7px 12px; }}
QToolButton#Plain:hover {{ border-color: {p['accent']}; }}
QToolButton#Plain::menu-indicator {{ subcontrol-position: right center; right: 6px; }}
QToolButton#Plain[popupMode="2"] {{ padding-right: 22px; }}
#SectionHeader {{ color: {p['section']}; }}
#ErrorText {{ color: {p['danger']}; background: transparent; }}
#SpeedLabel {{ color: {p['text']}; background: transparent; font-weight: 600; }}
"""
    return main + extra


def apply_theme(app, mode: str) -> str:  # type: ignore[no-untyped-def]
    """Install the stylesheet for *mode* on *app*; return the effective palette name."""
    global _current
    _current = effective_mode(mode)
    try:
        arrows = _arrow_files(_current)
    except OSError:
        arrows = None
    app.setStyleSheet(build_stylesheet(_current, arrows))
    return _current


# Backwards-compatible stylesheet (dark) for tools that only need a default look.
STYLESHEET = build_stylesheet("dark")
