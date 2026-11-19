"""Works / Archive: browse, inspect, rename, merge and correct assignments."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPushButton, QRadioButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

import time

from ...archive.naming import _natural_key
from ...core.engine import EngineError
from ..widgets import (
    Banner, confirm, error_box, format_bytes, item, make_table, open_path, page_header, selected_data, status_item,
)
from .base import Page
from ...i18n import _

_PREVIEWABLE = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}


class ReassignDialog(QDialog):
    """Pick an existing work or type a title for a new one."""

    def __init__(self, parent, works, current_id: int | None, title: str, allow_remember: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Move gallery to another work"))
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_('Publication: <b>{0}</b>', title)))
        self.existing = QRadioButton(_("Existing work"))
        self.combo = QComboBox()
        for w in works:
            if w.id != current_id:
                self.combo.addItem(w.display_title, w.id)
        self.new = QRadioButton(_("New work"))
        self.name = QLineEdit()
        self.name.setPlaceholderText(_("Title of the new work, e.g. 'Isla: Origins - Chapter 2'"))
        self.existing.setChecked(self.combo.count() > 0)
        self.new.setChecked(self.combo.count() == 0)
        self.existing.setEnabled(self.combo.count() > 0)
        form = QFormLayout()
        form.addRow(self.existing, self.combo)
        form.addRow(self.new, self.name)
        layout.addLayout(form)
        self.remember = QCheckBox(_("Also use this work for future publications with the same title"))
        self.remember.setVisible(allow_remember)
        layout.addWidget(self.remember)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def choice(self) -> tuple[int | None, str | None, bool]:
        if self.existing.isChecked():
            return self.combo.currentData(), None, self.remember.isChecked()
        return None, self.name.text().strip(), self.remember.isChecked()


class SplitSketchesDialog(QDialog):
    """Lists sketch/WIP publications filed together with finished pages.
    Everything is checked; untick anything that is not really a sketch."""

    def __init__(self, parent, engine, mixes) -> None:
        super().__init__(parent)
        self.setWindowTitle(_("Separate sketches from finished pages"))
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        text = QLabel(
            _("These publications look like sketches, WIPs or line art but are filed together with the "
            "finished pages. Checked publications will be moved (files included) into a separate "
            "'… - Sketches' work next to the original. Untick anything that is not a sketch."))
        text.setWordWrap(True)
        layout.addWidget(text)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([_("Publication"), _("Files")])
        from PySide6.QtWidgets import QHeaderView
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setStretchLastSection(False)
        for work, galleries in mixes:
            author = engine.repos.authors.get(work.author_id)
            parent_item = QTreeWidgetItem([f"{work.display_title}   ({author.name if author else ''})", ""])
            parent_item.setData(0, Qt.ItemDataRole.UserRole, work.id)
            parent_item.setFlags(parent_item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            parent_item.setCheckState(0, Qt.CheckState.Checked)
            self.tree.addTopLevelItem(parent_item)
            for gallery in galleries:
                files = len(engine.repos.files.for_gallery(gallery.id))
                child = QTreeWidgetItem([gallery.title, str(files)])
                child.setData(0, Qt.ItemDataRole.UserRole, gallery.id)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked)
                parent_item.addChild(child)
            parent_item.setExpanded(True)
        layout.addWidget(self.tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_("Move checked"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selection(self) -> list[tuple[int, list[int]]]:
        out = []
        for i in range(self.tree.topLevelItemCount()):
            parent_item = self.tree.topLevelItem(i)
            ids = [parent_item.child(j).data(0, Qt.ItemDataRole.UserRole) for j in range(parent_item.childCount())
                   if parent_item.child(j).checkState(0) == Qt.CheckState.Checked]
            if ids:
                out.append((parent_item.data(0, Qt.ItemDataRole.UserRole), ids))
        return out


class WorksPage(Page):
    title = "Works"

    def __init__(self, engine) -> None:
        super().__init__(engine)
        self.root.addWidget(page_header(_("Works"), _("Recognized artworks grouped by author. Pages are ordered by page number.")))
        self.mix_banner = Banner()
        self.mix_fix_btn = QPushButton(_("Review and fix…"))
        self.mix_fix_btn.setObjectName("Primary")
        self.mix_fix_btn.clicked.connect(lambda: self._split_sketches(all_works=True))
        self.mix_banner.layout().addWidget(self.mix_fix_btn)
        self.root.addWidget(self.mix_banner)
        self._mixes_checked_at = 0.0
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([_("Work"), _("Files")])
        header = self.tree.header()
        header.setStretchLastSection(False)
        from PySide6.QtWidgets import QHeaderView
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.tree.itemSelectionChanged.connect(self._show_work)
        splitter.addWidget(self.tree)

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(12, 0, 0, 0)
        self.work_title = QLabel(_("Select a work"))
        self.work_title.setObjectName("PageTitle")
        self.work_title.setStyleSheet("font-size: 17px;")
        self.work_info = QLabel("")
        self.work_info.setObjectName("Muted")
        self.work_info.setWordWrap(True)
        rl.addWidget(self.work_title)
        rl.addWidget(self.work_info)
        buttons = QHBoxLayout()
        self.open_btn = QPushButton(_("Open folder"))
        self.rename_btn = QPushButton(_("Rename…"))
        self.merge_btn = QPushButton(_("Merge into…"))
        self.move_btn = QPushButton(_("Move gallery…"))
        self.move_btn.setToolTip(_("Move the publications of the selected files to another work"))
        self.split_btn = QPushButton(_("Split sketches…"))
        self.split_btn.setToolTip(_("Move sketch / WIP / line-art publications of this work into a separate work"))
        for b, slot in ((self.open_btn, self._open), (self.rename_btn, self._rename),
                        (self.merge_btn, self._merge), (self.move_btn, self._move_gallery),
                        (self.split_btn, lambda: self._split_sketches(all_works=False))):
            b.clicked.connect(slot)
            buttons.addWidget(b)
        buttons.addStretch(1)
        rl.addLayout(buttons)

        inner = QSplitter(Qt.Orientation.Vertical)
        self.files = make_table([_("Page"), _("File"), _("Type"), _("Size"), _("Status"), _("Published"), _("Publication")], stretch=6)
        self.files.setSortingEnabled(True)
        self.files.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.files.horizontalHeader().setSortIndicatorShown(True)
        self.files.horizontalHeader().setToolTip(_("Click a column header to sort; click again to reverse"))
        from PySide6.QtWidgets import QAbstractItemView
        self.files.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.files.itemSelectionChanged.connect(self._preview)
        self.files.doubleClicked.connect(lambda _: self._open_file())
        inner.addWidget(self.files)
        self.preview = QLabel(_("No preview"))
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setObjectName("Card")
        self.preview.setMinimumHeight(180)
        inner.addWidget(self.preview)
        inner.setSizes([420, 260])
        rl.addWidget(inner, 1)
        splitter.addWidget(right)
        splitter.setSizes([380, 860])
        self.root.addWidget(splitter, 1)
        self._work_id: int | None = None
        self._set_buttons()

    def select_work(self, work_id: int) -> None:
        """Open *work_id* (used by notifications)."""
        self._work_id = work_id
        self.refresh()

    # ------------------------------------------------------------- tree
    def _check_mixes(self, force: bool = False) -> None:
        if not force and time.monotonic() - self._mixes_checked_at < 30:
            return
        self._mixes_checked_at = time.monotonic()
        mixes = self.engine.find_variant_mixes()
        count = sum(len(g) for _w, g in mixes)
        self.mix_banner.show_message(
            _("{0} work(s) contain {1} sketch / WIP publication(s) filed together with the finished pages. Recent versions keep them in a separate '… - Sketches' work.", len(mixes), count) if mixes else None)

    def refresh(self) -> None:
        self._check_mixes()
        current = self._work_id
        self.tree.blockSignals(True)
        self.tree.clear()
        select_item = None
        for author in self.engine.repos.authors.all():
            works = self.engine.repos.works.for_author(author.id)
            parent = QTreeWidgetItem([author.name, str(len(works))])
            parent.setData(0, Qt.ItemDataRole.UserRole, None)
            font = parent.font(0)
            font.setBold(True)
            parent.setFont(0, font)
            self.tree.addTopLevelItem(parent)
            for work in works:
                stats = self.engine.repos.works.stats(work.id)
                child = QTreeWidgetItem([work.display_title, f"{stats['complete']}/{stats['total']}"])
                child.setToolTip(0, work.display_title)
                child.setData(0, Qt.ItemDataRole.UserRole, work.id)
                if not work.user_confirmed and work.confidence < 1.0:
                    child.setToolTip(0, _('Recognized automatically (confidence {0:.0%})', work.confidence))
                parent.addChild(child)
                if work.id == current:
                    select_item = child
            parent.setExpanded(True)
        self.tree.blockSignals(False)
        if select_item is not None:
            select_item.setSelected(True)
            self._show_work()
        elif current is not None:
            self._work_id = None
            self._show_work()

    def _selected_work_id(self) -> int | None:
        items = self.tree.selectedItems()
        return items[0].data(0, Qt.ItemDataRole.UserRole) if items else None

    def _set_buttons(self) -> None:
        has = self._work_id is not None
        for b in (self.open_btn, self.rename_btn, self.merge_btn, self.split_btn):
            b.setEnabled(has)
        self.move_btn.setEnabled(has and bool(selected_data(self.files)))

    def _show_work(self) -> None:
        work_id = self._selected_work_id() if self.tree.selectedItems() else self._work_id
        self._work_id = work_id
        self.files.setRowCount(0)
        self.preview.setPixmap(QPixmap())
        self.preview.setText(_("No preview"))
        work = self.engine.repos.works.get(work_id) if work_id else None
        if work is None:
            self.work_title.setText(_("Select a work"))
            self.work_info.setText("")
            self._set_buttons()
            return
        stats = self.engine.repos.works.stats(work.id)
        self.work_title.setText(work.display_title)
        how = _("confirmed by you") if work.user_confirmed else _("recognized automatically ({0:.0%})", work.confidence)
        self.work_info.setText(
            _('Folder: {0}\n{1} of {2} files archived · {3} · {4}', self.engine.work_dir(work), stats['complete'], stats['total'], format_bytes(stats['bytes']), how)
        )
        records = [f for f in self.engine.repos.files.for_work(work.id) if f.status not in ("duplicate", "skipped")]
        galleries = {}
        header = self.files.horizontalHeader()
        sort_column, sort_order = header.sortIndicatorSection(), header.sortIndicatorOrder()
        self.files.setSortingEnabled(False)  # fill first, then sort once
        self.files.setRowCount(len(records))
        for row, f in enumerate(records):
            gallery = galleries.setdefault(f.gallery_id, self.engine.repos.galleries.get(f.gallery_id))
            published = gallery.published_at if gallery else None
            stamp = published.timestamp() if published else 0.0
            name = f.local_path.rsplit("/", 1)[-1] if f.local_path else f.target_name
            page = f.page_number if f.page_number is not None else 10**9
            # Ties are broken by publication date and position, so related pages stay together.
            self.files.setItem(row, 0, item(f.page_number if f.page_number is not None else "—", f.id,
                                            sort_key=(page, stamp, f.position)))
            self.files.setItem(row, 1, item(name, sort_key=_natural_key(name)))
            self.files.setItem(row, 2, item(f.extension.upper(), muted=True))
            self.files.setItem(row, 3, item(format_bytes(f.size_bytes), sort_key=(f.size_bytes or 0,)))
            self.files.setItem(row, 4, status_item(f.status))
            self.files.setItem(row, 5, item(published.astimezone().strftime("%Y-%m-%d") if published else "—",
                                            muted=True, sort_key=(stamp, f.position)))
            title = gallery.title.strip() if gallery else ""
            self.files.setItem(row, 6, item(title, muted=True, sort_key=(_natural_key(title), stamp, page, f.position)))
        self.files.setSortingEnabled(True)
        self.files.sortByColumn(sort_column, sort_order)
        self._set_buttons()

    def _selected_file(self):
        ids = selected_data(self.files)
        return self.engine.repos.files.get(ids[0]) if ids else None  # type: ignore[arg-type]

    def _preview(self) -> None:
        self._set_buttons()
        record = self._selected_file()
        if record is None or record.status != "complete" or not record.local_path:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(_("No preview"))
            return
        if record.extension.lower() not in _PREVIEWABLE:
            self.preview.setPixmap(QPixmap())
            self.preview.setText(_('{0} file — double-click to open', record.extension.upper()))
            return
        pixmap = QPixmap(str(self.engine.absolute(record.local_path)))
        if pixmap.isNull():
            self.preview.setText(_("Preview not available"))
            return
        target = self.preview.size()
        self.preview.setPixmap(pixmap.scaled(target.width() - 16, target.height() - 16,
                                             Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
        self.preview.setToolTip(_('{0} × {1} px (original)', pixmap.width(), pixmap.height()))

    # ---------------------------------------------------------- actions
    def _open(self) -> None:
        work = self.engine.repos.works.get(self._work_id) if self._work_id else None
        if work:
            open_path(self.engine.work_dir(work))

    def _open_file(self) -> None:
        record = self._selected_file()
        if record and record.local_path:
            open_path(self.engine.absolute(record.local_path))

    def _rename(self) -> None:
        work = self.engine.repos.works.get(self._work_id) if self._work_id else None
        if not work:
            return
        name, ok = QInputDialog.getText(self, _("Rename work"), _("New title (also renames the archive folder):"),
                                        text=work.display_title)
        if ok and name.strip():
            try:
                self.engine.rename_work(work.id, name.strip())
            except (EngineError, OSError) as exc:
                error_box(self, _("Rename failed"), str(exc))
            self.refresh()

    def _merge(self) -> None:
        work = self.engine.repos.works.get(self._work_id) if self._work_id else None
        if not work:
            return
        others = [w for w in self.engine.repos.works.for_author(work.author_id) if w.id != work.id]
        if not others:
            error_box(self, _("Merge"), _("This author has no other work to merge into."))
            return
        titles = [w.display_title for w in others]
        choice, ok = QInputDialog.getItem(self, _("Merge works"), _("Move all files of '{0}' into:", work.display_title),
                                          titles, 0, False)
        if not ok:
            return
        target = others[titles.index(choice)]
        if confirm(self, _("Merge works"), _("Merge '{0}' into '{1}'?\n\nFiles are moved (never overwritten) and future publications with the old title will go to the target work.", work.display_title, target.display_title)):
            try:
                merged = self.engine.merge_works(work.id, target.id)
                self._work_id = merged.id
            except (EngineError, OSError) as exc:
                error_box(self, _("Merge failed"), str(exc))
            self.refresh()

    def _move_gallery(self) -> None:
        records = [self.engine.repos.files.get(i) for i in selected_data(self.files)]
        gallery_ids = list(dict.fromkeys(r.gallery_id for r in records if r))
        galleries = [g for g in (self.engine.repos.galleries.get(i) for i in gallery_ids) if g]
        if not galleries:
            return
        works = self.engine.repos.works.for_author(galleries[0].author_id)
        label = galleries[0].title if len(galleries) == 1 else _("{0} publications", len(galleries))
        dialog = ReassignDialog(self, works, galleries[0].work_id, label)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        work_id, title, remember = dialog.choice()
        try:
            target = self.engine.reassign_galleries([g.id for g in galleries], work_id, title, remember)
            if target:
                self._work_id = target.id
        except (EngineError, OSError) as exc:
            error_box(self, _("Move failed"), str(exc))
        self.refresh()

    def _split_sketches(self, all_works: bool) -> None:
        mixes = self.engine.find_variant_mixes()
        if not all_works:
            mixes = [(w, g) for w, g in mixes if w.id == self._work_id]
        if not mixes:
            QMessageBox.information(self, _("Split sketches"), _("No sketch / WIP publications were found "
                                    "among the finished pages") + ("." if all_works else _(" of this work.")))
            return
        dialog = SplitSketchesDialog(self, self.engine, mixes)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        moved = 0
        try:
            for work_id, gallery_ids in dialog.selection():
                target = self.engine.split_sketches(work_id, gallery_ids)
                moved += len(gallery_ids)
                if target and not all_works:
                    self._work_id = work_id
        except (EngineError, OSError) as exc:
            error_box(self, _("Split failed"), str(exc))
        self._check_mixes(force=True)
        self.refresh()
        if moved:
            QMessageBox.information(self, _("Split sketches"), _("{0} publication(s) moved to their '… - Sketches' work.", moved))
