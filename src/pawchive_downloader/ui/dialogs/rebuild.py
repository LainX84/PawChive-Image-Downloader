"""Rebuild an author's archive: confirm similar names, preview, run."""

from __future__ import annotations

from difflib import SequenceMatcher

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QGridLayout, QGroupBox, QLabel, QListWidget,
    QMessageBox, QProgressBar, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)
from ...i18n import _


class _Signals(QObject):
    progress = Signal(str)
    done = Signal(object, object)


class _RebuildTask(QRunnable):
    def __init__(self, engine, author_id: int, series_map: dict[str, str]) -> None:
        super().__init__()
        self.engine, self.author_id, self.series_map = engine, author_id, series_map
        self.signals = _Signals()

    def run(self) -> None:
        try:
            stats = self.engine.rebuild_author(self.author_id, self.signals.progress.emit, self.series_map)
            self.signals.done.emit(stats, None)
        except Exception as exc:  # noqa: BLE001 - reported to the user
            self.signals.done.emit(None, exc)


class RebuildDialog(QDialog):
    def __init__(self, parent, engine, author) -> None:
        super().__init__(parent)
        self.engine, self.author = engine, author
        self.setWindowTitle(_('Rebuild archive — {0}', author.name))
        self.resize(980, 680)
        layout = QVBoxLayout(self)
        intro = QLabel(
            _("Recognition runs again on every publication of this author, oldest first, with the current rules. "
            "Archived files are moved to their correct folders — <b>nothing is downloaded again</b> and no file "
            "is deleted. Previous review decisions and work names of this author are discarded."))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.similar_box = QGroupBox(_("Similar names — tick the ones that are the same artwork (for example a typo)"))
        self.similar_layout = QGridLayout(self.similar_box)
        self.similar_layout.setColumnStretch(0, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(self.similar_box)
        scroll.setMaximumHeight(210)
        layout.addWidget(scroll)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        self.works_label = QLabel(_("<b>Resulting works</b>"))
        ll.addWidget(self.works_label)
        self.works = QListWidget()
        ll.addWidget(self.works)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.review_label = QLabel(_("<b>Will need review</b>"))
        rl.addWidget(self.review_label)
        self.review = QListWidget()
        rl.addWidget(self.review)
        splitter.addWidget(left)
        splitter.addWidget(right)
        layout.addWidget(splitter, 1)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setFixedHeight(8)
        self.bar.setTextVisible(False)
        self.bar.hide()
        layout.addWidget(self.status)
        layout.addWidget(self.bar)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(_("Rebuild archive"))
        self.buttons.accepted.connect(self._run)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._rows: list[tuple[QCheckBox, QComboBox, dict]] = []
        preview = self.engine.preview_rebuild(author.id)
        for row, entry in enumerate(preview["similar"]):
            check = QCheckBox(_('“{0}” ({1} posts)  and  “{2}” ({3} posts) are the same artwork', entry['name'], entry['count'], entry['other_name'], entry['other_count']))
            check.setProperty("label", _("“{0}” ({1} posts)", entry["name"], entry["count"]))
            combo = QComboBox()
            names = [entry["name"], entry["other_name"]]
            if entry["other_count"] > entry["count"]:
                names.reverse()
            combo.addItems([_("use name: {0}", n) for n in names])
            combo.setProperty("names", names)
            combo.setMinimumWidth(320)
            combo.setEnabled(False)
            check.toggled.connect(combo.setEnabled)
            # Obvious typos (nearly identical names, both used many times) start ticked;
            # the user still sees and confirms them before anything happens.
            if (SequenceMatcher(None, entry["key"], entry["other_key"]).ratio() >= 0.9
                    and entry["count"] >= 5 and entry["other_count"] >= 5):
                check.setChecked(True)
                combo.setEnabled(True)
            check.toggled.connect(self._update_preview)
            combo.currentIndexChanged.connect(self._update_preview)
            self.similar_layout.addWidget(check, row, 0)
            self.similar_layout.addWidget(combo, row, 1)
            self._rows.append((check, combo, entry))
        if not self._rows:
            self.similar_layout.addWidget(QLabel(_("No similar names found.")), 0, 0)
        self._last_preview = preview
        self._update_preview() if any(c.isChecked() for c, _w, _p in self._rows) else self._show(preview)

    def series_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for check, combo, entry in self._rows:
            if check.isChecked():
                name = combo.property("names")[combo.currentIndex()]
                mapping[entry["key"]] = name
                mapping[entry["other_key"]] = name
        return mapping

    def _update_preview(self) -> None:
        self._last_preview = self.engine.preview_rebuild(self.author.id, self.series_map())
        self._show(self._last_preview)

    def _show(self, preview) -> None:
        self.works.clear()
        for title, count in preview["works"]:
            self.works.addItem(f"{count:5}   {title}")
        self.review.clear()
        self.review.addItems(preview["review"])
        self.works_label.setText(_('<b>Resulting works ({0})</b> — files per work', len(preview['works'])))
        self.review_label.setText(_('<b>Will need review ({0})</b>', len(preview['review'])))

    def _run(self) -> None:
        merged = [(c.property("label"), combo.property("names")[combo.currentIndex()])
                  for c, combo, _row in self._rows if c.isChecked()]
        reviews = len(self._last_preview["review"])
        works = len(self._last_preview["works"])
        lines = [_("Reorganize the whole archive of {0} now?", self.author.name), "",
                 _("• {0} works will be created", works),
                 _("• {0} publication(s) will wait in Review (their files are kept in Temp/Incomplete until you decide)", reviews)]
        if merged:
            lines += ["", _("Treated as the same artwork:")] + [f"• {a}  →  {name}" for a, name in merged]
        else:
            lines += ["", _("No similar names were marked as the same artwork.")]
        box = QMessageBox(QMessageBox.Icon.Question, _("Rebuild archive"), "\n".join(lines),
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, self)
        if reviews > 50:
            box.setIcon(QMessageBox.Icon.Warning)
            box.setInformativeText(_("{0} publications in Review is a lot: usually it means that a similar "
                                     "name (a typo) above should be ticked as the same artwork.", reviews))
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        self.buttons.setEnabled(False)
        self.similar_box.setEnabled(False)
        self.bar.show()
        self.status.setText(_("Pausing downloads…"))
        task = _RebuildTask(self.engine, self.author.id, self.series_map())
        task.signals.progress.connect(self.status.setText)
        task.signals.done.connect(self._done)
        QThreadPool.globalInstance().start(task)

    def _done(self, stats, error) -> None:
        self.bar.hide()
        self.buttons.setEnabled(True)
        if error is not None:
            QMessageBox.warning(self, _("Rebuild failed"),
                                _('{0}\n\nNo file was deleted. Files not yet filed are in Temp/Incomplete and are filed again by running the rebuild once more.', error))
            return
        QMessageBox.information(
            self, _("Archive rebuilt"),
            _('{0} publications filed into {1} works ({2} files in the archive). {3} publication(s) wait in Review.', stats['galleries'], stats['works'], stats['files'], stats['review']))
        self.accept()
