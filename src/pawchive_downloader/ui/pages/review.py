"""Review: confirm publications the recognizer was not sure about.

Filter by author, search by keyword, select several publications and resolve
them together (assign to one work, create one work, or ignore).
"""

from __future__ import annotations

import json
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ...core.engine import EngineError
from ...recognition.normalize import normalize_key
from ..widgets import confirm, error_box, format_local, page_header
from .base import Page
from ...i18n import _

ALL_AUTHORS = -1
_SIMILAR_RE = re.compile(r"^similar title \((\d+%)\)$")
_CONFLICT_RE = re.compile(r"^conflicting (\w+) numbers$")


def translate_reason(text: str) -> str:
    """Recognition reasons are stored in English; show them in the interface language."""
    parts = []
    for part in (text or "").split("; "):
        if part.startswith("similar existing work: "):
            parts.append(_("similar existing work: {0}", translate_reason(part[len("similar existing work: "):])))
        elif m := _SIMILAR_RE.match(part):
            parts.append(_("similar title ({0})", m.group(1)))
        elif m := _CONFLICT_RE.match(part):
            parts.append(_("conflicting {0} numbers", _(m.group(1))))
        else:
            parts.append(_(part))
    return "; ".join(parts)


class ReviewPage(Page):
    title = "Review"

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.root.addWidget(page_header(
            _("Review"),
            _("These publications could not be matched to a work with enough confidence. Their files are "
            "downloaded and kept in the temporary folder until you decide. Your choice is remembered for "
            "future publications with the same title."),
        ))

        filters = QHBoxLayout()
        filters.addWidget(QLabel(_("Author:")))
        self.author_filter = QComboBox()
        self.author_filter.setMinimumWidth(220)
        self.author_filter.currentIndexChanged.connect(self._apply_filter)
        filters.addWidget(self.author_filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText(_("Search titles… (e.g. 'chapter 26' or 'spectre')"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        filters.addWidget(self.search, 1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("Muted")
        filters.addWidget(self.count_label)
        self.root.addLayout(filters)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self._show)
        ll.addWidget(self.list, 1)
        sel_row = QHBoxLayout()
        self.select_all_btn = QPushButton(_("Select all shown"))
        self.select_all_btn.clicked.connect(self.list.selectAll)
        self.select_none_btn = QPushButton(_("Clear selection"))
        self.select_none_btn.clicked.connect(self.list.clearSelection)
        sel_row.addWidget(self.select_all_btn)
        sel_row.addWidget(self.select_none_btn)
        sel_row.addStretch(1)
        ll.addLayout(sel_row)
        hint = QLabel(_("Tip: Ctrl/Shift+click to select several publications of the same author."))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        ll.addWidget(hint)
        splitter.addWidget(left)

        panel = QFrame()
        panel.setObjectName("Card")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(18, 16, 18, 16)
        self.title_label = QLabel(_("Nothing to review"))
        self.title_label.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.title_label.setWordWrap(True)
        pl.addWidget(self.title_label)
        self.reason = QLabel("")
        self.reason.setObjectName("Muted")
        self.reason.setWordWrap(True)
        pl.addWidget(self.reason)
        form = QFormLayout()
        self.parsed = QLabel("")
        self.parsed.setWordWrap(True)
        self.files = QLabel("")
        form.addRow(_("Recognized as:"), self.parsed)
        form.addRow(_("Files:"), self.files)
        pl.addLayout(form)

        pl.addWidget(QLabel(_("<b>Add to an existing work</b>")))
        self.candidates = QListWidget()
        self.candidates.setMaximumHeight(190)
        pl.addWidget(self.candidates)
        assign_row = QHBoxLayout()
        self.assign_btn = QPushButton(_("Add to selected work"))
        self.assign_btn.setObjectName("Primary")
        self.assign_btn.clicked.connect(self._assign)
        assign_row.addWidget(self.assign_btn)
        assign_row.addStretch(1)
        pl.addLayout(assign_row)

        pl.addWidget(QLabel(_("<b>…or create a new work</b>")))
        new_row = QHBoxLayout()
        self.new_title = QLineEdit()
        self.new_btn = QPushButton(_("Create work"))
        self.new_btn.clicked.connect(self._create)
        new_row.addWidget(self.new_title, 1)
        new_row.addWidget(self.new_btn)
        pl.addLayout(new_row)
        pl.addStretch(1)
        ignore_row = QHBoxLayout()
        ignore_row.addStretch(1)
        self.ignore_btn = QPushButton(_("Ignore"))
        self.ignore_btn.setObjectName("Danger")
        self.ignore_btn.clicked.connect(self._ignore)
        ignore_row.addWidget(self.ignore_btn)
        pl.addLayout(ignore_row)
        splitter.addWidget(panel)
        splitter.setSizes([440, 760])
        self.root.addWidget(splitter, 1)

        self._entries: list[dict] = []
        self._enable(False)

    # ------------------------------------------------------------------ data
    def _enable(self, on: bool) -> None:
        for w in (self.assign_btn, self.new_btn, self.ignore_btn, self.new_title, self.candidates):
            w.setEnabled(on)

    def refresh(self) -> None:
        entries = []
        authors = {}
        for review in self.engine.repos.reviews.open_requests():
            gallery = self.engine.repos.galleries.get(review.gallery_id)
            if gallery is None:
                continue
            author = authors.get(gallery.author_id) or self.engine.repos.authors.get(gallery.author_id)
            if author is None:
                continue
            authors[author.id] = author
            entries.append({
                "id": review.id, "author_id": author.id, "author": author.name, "title": gallery.title,
                "date": format_local(gallery.published_at), "search": normalize_key(gallery.title),
            })
        self._entries = entries

        # Author filter, with the number of open reviews per author.
        current = self.author_filter.currentData()
        counts: dict[int, int] = {}
        for e in entries:
            counts[e["author_id"]] = counts.get(e["author_id"], 0) + 1
        self.author_filter.blockSignals(True)
        self.author_filter.clear()
        self.author_filter.addItem(_('All authors ({0})', len(entries)), ALL_AUTHORS)
        for author in sorted(authors.values(), key=lambda a: a.name.casefold()):
            self.author_filter.addItem(f"{author.name} ({counts[author.id]})", author.id)
        index = self.author_filter.findData(current) if current is not None else 0
        self.author_filter.setCurrentIndex(index if index >= 0 else 0)
        self.author_filter.blockSignals(False)
        self._apply_filter()

    def _visible_entries(self) -> list[dict]:
        author_id = self.author_filter.currentData()
        terms = normalize_key(self.search.text()).split()
        out = []
        for e in self._entries:
            if author_id not in (None, ALL_AUTHORS) and e["author_id"] != author_id:
                continue
            if terms and not all(t in e["search"] for t in terms):
                continue
            out.append(e)
        return out

    def _apply_filter(self) -> None:
        selected = set(self._selected_ids())
        visible = self._visible_entries()
        show_author = self.author_filter.currentData() in (None, ALL_AUTHORS)
        scroll = self.list.verticalScrollBar().value()
        self.list.blockSignals(True)
        self.list.clear()
        for e in visible:
            subtitle = f"{e['author']} · {e['date']}" if show_author else e["date"]
            entry = QListWidgetItem(f"{e['title']}\n{subtitle}")
            entry.setData(Qt.ItemDataRole.UserRole, e["id"])
            entry.setData(Qt.ItemDataRole.UserRole + 1, e["author_id"])
            self.list.addItem(entry)
            if e["id"] in selected:
                entry.setSelected(True)
        self.list.blockSignals(False)
        self.list.verticalScrollBar().setValue(scroll)
        if not self.list.selectedItems() and self.list.count():
            self.list.setCurrentRow(0)
        total = len(self._entries)
        self.count_label.setText(_('{0} of {1} shown', len(visible), total) if len(visible) != total else _('{0} to review', total))
        self._show()

    def _selected_ids(self) -> list[int]:
        return [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]

    def _selected_authors(self) -> set[int]:
        return {i.data(Qt.ItemDataRole.UserRole + 1) for i in self.list.selectedItems()}

    # --------------------------------------------------------------- details
    def _show(self) -> None:
        ids = self._selected_ids()
        self.candidates.clear()
        if not ids:
            self.title_label.setText(_("Nothing to review") if not self._entries else
                                     _("No publication matches the filter") if not self.list.count() else
                                     _("Select a publication"))
            for w in (self.reason, self.parsed, self.files):
                w.setText("")
            self._enable(False)
            return
        authors = self._selected_authors()
        if len(authors) > 1:
            self.title_label.setText(_('{0} publications selected', len(ids)))
            self.reason.setText(_("The selection contains several authors. Choose one author in the filter, "
                                "or select publications of a single author."))
            self.parsed.setText("")
            self.files.setText("")
            self._enable(False)
            return
        self._enable(True)
        author_id = next(iter(authors))
        reviews = [self.engine.repos.reviews.get(i) for i in ids]
        reviews = [r for r in reviews if r]
        first = reviews[0]
        gallery = self.engine.repos.galleries.get(first.gallery_id)

        if len(reviews) == 1:
            self.title_label.setText(gallery.title if gallery else "")
            self.reason.setText(_('Why: {0}', translate_reason(first.reason)))
            parsed = (gallery.parsed_title or {}) if gallery else {}
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            bits = [_("series “{0}”", parsed.get('series') or '—')]
            for key in ("volume", "part", "chapter", "issue", "episode", "page"):
                if parsed.get(key) is not None:
                    bits.append(f"{_(key)} {parsed[key]}")
            self.parsed.setText(", ".join(bits) + _('  (confidence {0:.0%})', parsed.get('confidence', 0)))
            self.new_title.setText(first.proposed_title if not first.proposed_title.startswith("Untitled") else "")
        else:
            self.title_label.setText(_('{0} publications selected', len(reviews)))
            reasons = sorted({translate_reason(r.reason) for r in reviews})
            self.reason.setText(_("Why: ") + "; ".join(reasons[:3]) + ("…" if len(reasons) > 3 else ""))
            proposals = sorted({r.proposed_title for r in reviews})
            self.parsed.setText(", ".join(proposals[:4]) + (_(' and {0} more', len(proposals) - 4) if len(proposals) > 4 else ""))
            self.new_title.setText(proposals[0] if len(proposals) == 1 and not proposals[0].startswith("Untitled") else "")

        total_files = held = 0
        for review in reviews:
            records = self.engine.repos.files.for_gallery(review.gallery_id)
            total_files += len(records)
            held += sum(r.status == "held" for r in records)
        self.files.setText(_('{0} file(s), {1} downloaded and waiting', total_files, held))

        # Candidates suggested by the matcher first (merged over the selection), then all other works.
        scores: dict[int, tuple[float, str, str]] = {}
        for review in reviews:
            for cand in review.candidates:
                best = scores.get(cand["work_id"])
                if best is None or cand["score"] > best[0]:
                    scores[cand["work_id"]] = (cand["score"], cand["title"], translate_reason(cand["reason"]))
        for work_id, (_score, title, reason) in sorted(scores.items(), key=lambda kv: -kv[1][0]):
            entry = QListWidgetItem(f"{title}   —   {reason}")
            entry.setData(Qt.ItemDataRole.UserRole, work_id)
            self.candidates.addItem(entry)
        for work in self.engine.repos.works.for_author(author_id):
            if work.id not in scores:
                entry = QListWidgetItem(work.display_title)
                entry.setData(Qt.ItemDataRole.UserRole, work.id)
                self.candidates.addItem(entry)
        if self.candidates.count():
            self.candidates.setCurrentRow(0)
        self.assign_btn.setEnabled(self.candidates.count() > 0)
        n = len(reviews)
        self.assign_btn.setText(_("Add to selected work") if n == 1 else _('Add {0} to selected work', n))
        self.new_btn.setText(_("Create work") if n == 1 else _('Create work for {0}', n))
        self.ignore_btn.setText(_("Ignore this publication") if n == 1 else _('Ignore {0} publications', n))

    # --------------------------------------------------------------- actions
    def _assign(self) -> None:
        ids = self._selected_ids()
        selected = self.candidates.selectedItems()
        if not ids or not selected:
            return
        try:
            self.engine.resolve_reviews(ids, work_id=selected[0].data(Qt.ItemDataRole.UserRole))
        except (EngineError, OSError) as exc:
            error_box(self, _("Could not assign"), str(exc))
        self.refresh()

    def _create(self) -> None:
        ids = self._selected_ids()
        title = self.new_title.text().strip()
        if not ids:
            return
        if not title:
            error_box(self, _("Create work"), _("Enter a title for the new work."))
            return
        try:
            self.engine.resolve_reviews(ids, new_title=title)
        except (EngineError, OSError) as exc:
            error_box(self, _("Could not create work"), str(exc))
        self.refresh()

    def _ignore(self) -> None:
        ids = self._selected_ids()
        if ids and confirm(self, _("Ignore"), _('Ignore {0} publication(s)? Their files will not be archived.', len(ids))):
            self.engine.dismiss_reviews(ids)
            self.refresh()
