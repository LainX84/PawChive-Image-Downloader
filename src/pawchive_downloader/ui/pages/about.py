"""About: the project, its author, license, disclaimer and credits."""

from __future__ import annotations

import platform
import sys

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from ...i18n import _
from ...legal import DISCLAIMER, MIT_LICENSE, THIRD_PARTY
from ...version import APP_NAME, AUTHOR, COPYRIGHT, GITHUB_PROFILE_URL, ISSUES_URL, RELEASES_URL, REPOSITORY_URL, __version__
from ..icons import app_icon_pixmap
from ..theme import color
from ..widgets import page_header
from .base import Page


def _card(title: str | None = None) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("Card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(22, 18, 22, 18)
    layout.setSpacing(8)
    if title:
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(heading)
    return card, layout


def _text(text: str, muted: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setOpenExternalLinks(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    if muted:
        label.setObjectName("Muted")
    return label


class AboutPage(Page):
    title = "About"

    def __init__(self, engine) -> None:  # type: ignore[no-untyped-def]
        super().__init__(engine)
        self.root.addWidget(page_header(_("About")))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        col = QVBoxLayout(body)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(12)
        self._links: list[QLabel] = []

        # Identity ---------------------------------------------------------
        card, layout = _card()
        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(app_icon_pixmap(72))
        logo.setFixedSize(76, 76)
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        name_box = QVBoxLayout()
        name = QLabel(f"<span style='font-size:20px; font-weight:600'>{APP_NAME}</span>")
        name_box.addWidget(name)
        name_box.addWidget(QLabel(_("Version {0}", __version__)))
        name_box.addWidget(_text(_("Monitors PawChive authors, downloads original-resolution files, recognizes the "
                                   "artwork each publication belongs to and keeps an incremental, consistent local "
                                   "archive.")))
        head.addLayout(name_box, 1)
        layout.addLayout(head)
        buttons = QHBoxLayout()
        for label, url in ((_("GitHub repository"), REPOSITORY_URL), (_("Report a problem"), ISSUES_URL),
                           (_("Releases"), RELEASES_URL)):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        col.addWidget(card)

        # About us ---------------------------------------------------------
        card, layout = _card(_("About us"))
        self._about = _text("")
        layout.addWidget(self._about)
        self._links.append(self._about)
        col.addWidget(card)

        # License ----------------------------------------------------------
        card, layout = _card(_("License"))
        layout.addWidget(_text(_("{0}. Released under the MIT License: you may use, copy, modify and distribute "
                                 "the software freely, as long as the copyright notice and the license are kept. "
                                 "It comes without any warranty.", COPYRIGHT)))
        row = QHBoxLayout()
        show = QPushButton(_("Read the full license"))
        show.clicked.connect(self._show_license)
        row.addWidget(show)
        row.addStretch(1)
        layout.addLayout(row)
        col.addWidget(card)

        # Disclaimer -------------------------------------------------------
        card, layout = _card(_("Disclaimer"))
        for paragraph in DISCLAIMER:
            layout.addWidget(_text(_(paragraph)))
        col.addWidget(card)

        # Credits ----------------------------------------------------------
        card, layout = _card(_("Credits and third-party software"))
        layout.addWidget(_text(_("PawChive Image Downloader is built with these open-source components. Each one "
                                 "belongs to its authors and is distributed under its own license:"), muted=True))
        self._credits = _text("")
        layout.addWidget(self._credits)
        self._links.append(self._credits)
        layout.addWidget(_text(_("The archived content is downloaded from PawChive (pawchive.pw), which mirrors "
                                 "publications of the original platforms. The rights to every downloaded file "
                                 "remain with its creator."), muted=True))
        tech = QLabel(_("Python {0} · PySide6 {1} · {2} {3}", sys.version.split()[0], pyside_version,
                        platform.system(), platform.release()))
        tech.setObjectName("Muted")
        layout.addWidget(tech)
        col.addWidget(card)

        col.addStretch(1)
        scroll.setWidget(body)
        self.root.addWidget(scroll, 1)
        self.refresh()

    def refresh(self) -> None:
        link = color("link")
        self._about.setText(_(
            "PawChive Image Downloader is developed and maintained by <b>{0}</b> as a free, open-source project. "
            "Ideas, bug reports and pull requests are welcome on GitHub.<br><br>"
            "Developer: <a style='color:{1}' href='{2}'>{0} on GitHub</a><br>"
            "Project: <a style='color:{1}' href='{3}'>{3}</a>",
            AUTHOR, link, GITHUB_PROFILE_URL, REPOSITORY_URL))
        rows = "".join(
            f"<tr><td style='padding:2px 14px 2px 0'><a style='color:{link}' href='{url}'>{name}</a></td>"
            f"<td style='padding:2px 0'>{license_name}</td></tr>" for name, license_name, url in THIRD_PARTY)
        self._credits.setText(f"<table>{rows}</table>")

    def _show_license(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(_("MIT License"))
        dialog.resize(620, 480)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit(MIT_LICENSE)
        text.setReadOnly(True)
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
