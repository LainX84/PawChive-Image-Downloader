"""Dashboard: totals, last cycle and current activity."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget, QFrame

from ..widgets import (
    Banner, StatCard, format_bytes, format_duration, format_local, format_speed, format_when, item, make_table,
    page_header,
)
from ..pause_controls import pause_state_text
from .base import Page
from ...i18n import _


class DashboardPage(Page):
    title = "Dashboard"

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.root.addWidget(page_header(_("Dashboard"), _("Everything PawChive Image Downloader is doing, at a glance.")))
        self.banner = Banner(danger=True)
        self.review_banner = Banner()
        self.root.addWidget(self.banner)
        self.root.addWidget(self.review_banner)

        grid = QGridLayout()
        grid.setSpacing(12)
        self.cards = {
            "monitored": StatCard(_("Monitored authors"), "accent"),
            "galleries": StatCard(_("Discovered galleries")),
            "images": StatCard(_("Downloaded images"), "success"),
            "works": StatCard(_("Recognized works")),
            "pending": StatCard(_("Pending downloads")),
            "failed": StatCard(_("Failed / unavailable"), "danger"),
            "reviews": StatCard(_("Waiting for review"), "warning"),
            "bytes": StatCard(_("Archive size")),
        }
        for index, card in enumerate(self.cards.values()):
            grid.addWidget(card, index // 4, index % 4)
        self.root.addLayout(grid)

        info = QFrame()
        info.setObjectName("Card")
        info_layout = QHBoxLayout(info)
        info_layout.setContentsMargins(16, 12, 16, 12)
        self.last_cycle = QLabel()
        self.queue_state = QLabel()
        self.queue_state.setObjectName("Muted")
        info_layout.addWidget(self.last_cycle, 1)
        info_layout.addWidget(self.queue_state)
        self.scan_all = QPushButton(_("Scan all now"))
        self.scan_all.setObjectName("Primary")
        self.scan_all.clicked.connect(self._scan_all)
        info_layout.addWidget(self.scan_all)
        self.root.addWidget(info)

        activity_title = QLabel(_("Current activity"))
        activity_title.setStyleSheet("font-weight: 600; font-size: 14px;")
        self.root.addWidget(activity_title)
        self.activity = make_table([_("File"), _("Work"), _("Author"), _("Progress"), _("Size"), _("Speed"), _("Time left")], stretch=0)
        self.root.addWidget(self.activity, 1)

        recent_title = QLabel(_("Recent scans"))
        recent_title.setStyleSheet("font-weight: 600; font-size: 14px;")
        self.root.addWidget(recent_title)
        self.recent = make_table([_("Author"), _("Finished"), _("Result"), _("Details")], stretch=3)
        self.recent.setMaximumHeight(200)
        self.root.addWidget(self.recent)

    def _scan_all(self) -> None:
        for author in self.engine.repos.authors.all():
            if author.monitoring_enabled:
                self.engine.request_scan(author.id)

    def refresh(self) -> None:
        stats = self.engine.dashboard()
        for key, card in self.cards.items():
            value = stats.get(key, 0)
            card.set(format_bytes(value) if key == "bytes" else f"{value:,}")  # type: ignore[arg-type]
        reviews = int(stats.get("reviews", 0))  # type: ignore[arg-type]
        self.review_banner.show_message(
            _('{0} publication(s) could not be matched to a work with enough confidence. Open the Review page to confirm them.', reviews) if reviews else None
        )
        problems = []
        if stats.get("downloads_paused"):
            problems.append(_("Downloads are paused. {0}", pause_state_text(self.engine)).strip())
        for host, (until, reason) in (stats.get("paused_hosts") or {}).items():  # type: ignore[union-attr]
            from datetime import datetime, timezone
            problems.append(_("Requests to {0} are paused ({1}); resuming {2}.", host, reason, format_when(datetime.fromtimestamp(until, timezone.utc), future=True)))
        if self.engine.session and self.engine.session.expired:
            problems.append(_("PawChive asked for authentication. Update your session cookies in Settings."))
        self.banner.show_message("\n".join(problems) if problems else None)

        last = stats.get("last_success")
        self.last_cycle.setText(_('Last successful monitoring cycle: <b>{0}</b>  ({1})', format_local(last), format_when(last)))  # type: ignore[arg-type]
        counts = self.engine.repos.queue.counts()
        self.queue_state.setText(
            _('Queue: {0} active · {1} waiting · {2} retrying · {3} failed', counts.get('active', 0), counts.get('waiting', 0), counts.get('backoff', 0), counts.get('failed', 0))
            + (_(' · {0} on hold', counts['on_hold']) if counts.get("on_hold") else "") + "   "
        )

        progress = self.engine.downloads.progress()
        speeds = self.engine.downloads.speeds()
        rows = [r for r in self.engine.repos.queue.all_with_files() if r["file_id"] in progress]
        self.activity.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            done, total = progress.get(row["file_id"], (0, None))
            self.activity.setItem(row_index, 0, item(row["target_name"], row["file_id"]))
            self.activity.setItem(row_index, 1, item(row["work_title"] or _("(awaiting review)"), muted=not row["work_title"]))
            self.activity.setItem(row_index, 2, item(row["author_name"]))
            bar = QProgressBar()
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setRange(0, 1000)
            bar.setValue(int(1000 * done / total) if total else 0)
            holder = QWidget()
            holder.setStyleSheet("background: transparent;")
            lay = QVBoxLayout(holder)
            lay.setContentsMargins(8, 0, 8, 0)
            lay.addWidget(bar)
            self.activity.setCellWidget(row_index, 3, holder)
            self.activity.setItem(row_index, 4, item(f"{format_bytes(done)} / {format_bytes(total)}"))
            self.activity.setItem(row_index, 5, item(format_speed(speeds.get(row["file_id"]))))
            eta = self.engine.downloads.eta_seconds(row["file_id"])
            self.activity.setItem(row_index, 6, item(format_duration(eta) if eta is not None else "…", muted=True))
        self.activity.setColumnWidth(3, 220)

        scans = self.engine.repos.scans.recent(8)
        self.recent.setRowCount(len(scans))
        from ...storage.db import from_db_time
        from ..widgets import status_item

        for i, scan in enumerate(scans):
            self.recent.setItem(i, 0, item(scan["author_name"] or "—"))
            self.recent.setItem(i, 1, item(format_local(from_db_time(scan["finished_at"])) if scan["finished_at"] else _("running…")))
            result = scan["result"] or "scanning"
            self.recent.setItem(i, 2, status_item(result))
            self.recent.setItem(i, 3, item(scan["message"] or "", muted=True))
