"""The "Browse & Restore" page: a folder as it was on a chosen date, search, restore."""

from __future__ import annotations

import os
import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLineEdit,
                               QMessageBox, QPushButton, QStyle, QStyledItemDelegate, QToolButton, QTreeView,
                               QVBoxLayout, QWidget)

from ..core import catalog
from . import theme
from .i18n import N_, tr
from .timeline import NOW, Timeline
from .widgets import Card, fmt_datetime, hbox, human_size, label, primary_button
from .workers import run_async

BATCH = 400
STATUS_TEXT = {catalog.STATUS_LOCAL: N_("On this PC"), catalog.STATUS_VAULT_ONLY: N_("Backup drive only"),
               catalog.STATUS_OLDER: N_("Older version")}


class FileModel(QAbstractTableModel):
    """Flat list with lazy fetching, so folders with 100k entries stay fast."""

    COLS = ("Name", "Status", "Size", "Modified")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all: list[dict] = []
        self._shown = 0
        st = QStyle.SP_DirIcon
        self._dir_icon = parent.style().standardIcon(st) if parent else None
        self._file_icon = parent.style().standardIcon(QStyle.SP_FileIcon) if parent else None
        self._status_names = {k: tr(v) for k, v in STATUS_TEXT.items()}
        self._cols = [tr("Name"), tr("Status"), tr("Size"), tr("Modified")]

    def set_rows(self, rows: list[dict]):
        self.beginResetModel()
        self._all = rows
        self._shown = min(BATCH, len(rows))
        self.endResetModel()

    def row(self, r: int) -> dict:
        return self._all[r]

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else self._shown

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 4

    def canFetchMore(self, parent=QModelIndex()):  # noqa: N802
        return not parent.isValid() and self._shown < len(self._all)

    def fetchMore(self, parent=QModelIndex()):  # noqa: N802
        n = min(BATCH, len(self._all) - self._shown)
        if n <= 0:
            return
        self.beginInsertRows(QModelIndex(), self._shown, self._shown + n - 1)
        self._shown += n
        self.endInsertRows()

    def headerData(self, s, o, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and o == Qt.Horizontal:
            return self._cols[s]
        return None

    def data(self, idx, role=Qt.DisplayRole):
        r = self._all[idx.row()]
        col = idx.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return r["name"]
            if col == 1:
                return self._status_names.get(r.get("status"), "") if r["kind"] == "file" else ""
            if col == 2:
                return human_size(r["copy"].size) if r["kind"] == "file" else ""
            if col == 3:
                return fmt_datetime(r["copy"].mtime_ns / 1e9) if r["kind"] == "file" else ""
        if role == Qt.DecorationRole and col == 0:
            return self._dir_icon if r["kind"] == "dir" else self._file_icon
        if role == Qt.UserRole:
            return r.get("status")
        if role == Qt.ToolTipRole and r["kind"] == "file":
            return r["copy"].rel_path
        if role == Qt.TextAlignmentRole and col == 2:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.AccessibleTextRole and col == 0:
            st = self._status_names.get(r.get("status"), "")
            return f"{r['name']}, {st}" if st else r["name"]
        return None


class BadgeDelegate(QStyledItemDelegate):
    def paint(self, p: QPainter, opt, idx):
        status = idx.data(Qt.UserRole)
        text = idx.data(Qt.DisplayRole)
        if not text:
            super().paint(p, opt, idx)
            return
        self.initStyleOption(opt, idx)
        opt.text = ""
        style = opt.widget.style() if opt.widget else None
        if style:
            style.drawControl(QStyle.CE_ItemViewItem, opt, p, opt.widget)
        t = theme.tokens()
        bg, fg = {catalog.STATUS_LOCAL: ("badge_local_bg", "badge_local_fg"),
                  catalog.STATUS_VAULT_ONLY: ("badge_vault_bg", "badge_vault_fg")}.get(
            status, ("badge_old_bg", "badge_old_fg"))
        fm = opt.fontMetrics
        w = fm.horizontalAdvance(text) + 18
        h = fm.height() + 6
        r = QRectF(opt.rect.x() + 4, opt.rect.y() + (opt.rect.height() - h) / 2, w, h)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t[bg]))
        p.drawRoundedRect(r, h / 2, h / 2)
        p.setPen(QColor(t[fg]))
        p.drawText(r, Qt.AlignCenter, text)
        p.restore()


class RestoreTab(QWidget):
    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.setObjectName("Page")
        self.source_id: str | None = None
        self.folder_key = ""
        self.folder_names: list[str] = []   # original-case names for the breadcrumb
        self.t = NOW
        self._gen = 0
        self._search_mode = False

        v = QVBoxLayout(self)
        v.setContentsMargins(2, 6, 2, 6)
        v.setSpacing(12)

        self.source = QComboBox()
        self.source.setAccessibleName(tr("Backed-up folder"))
        self.source.setMinimumWidth(240)
        self.btn_up = QToolButton()
        self.btn_up.setText("↑")
        self.btn_up.setToolTip(tr("Up one folder (Backspace)"))
        self.btn_up.setAccessibleName(tr("Up one folder"))
        self.crumb = label("", "H2")
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search all versions…"))
        self.search.setAccessibleName(tr("Search all versions"))
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(240)
        v.addLayout(hbox(self.source, self.btn_up, 6, self.crumb, None, self.search))

        self.banner = label("", "Warning", wrap=True)
        self.banner.hide()
        v.addWidget(self.banner)

        body = QHBoxLayout()
        body.setSpacing(14)
        self.model = FileModel(self)
        self.view = QTreeView()
        self.view.setModel(self.model)
        self.view.setRootIsDecorated(False)
        self.view.setUniformRowHeights(True)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setAccessibleName(tr("Files"))
        self.view.setItemDelegateForColumn(1, BadgeDelegate(self.view))
        h = self.view.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 150), (2, 90), (3, 140)):
            h.setSectionResizeMode(c, QHeaderView.Interactive)
            h.resizeSection(c, w)
        card = Card(shadow=False, margins=(10, 8, 10, 8))
        card.add(self.view)
        self.empty = label("", "Subtle")
        self.empty.setAlignment(Qt.AlignCenter)
        card.add(self.empty)
        body.addWidget(card, 1)
        self.timeline = Timeline()
        body.addWidget(self.timeline)
        v.addLayout(body, 1)

        self.info = label("", "Subtle")
        self.btn_history = QPushButton(tr("Where Is It?"))
        self.btn_history.setToolTip(tr("Show the history of the selected file"))
        self.btn_restore_to = QPushButton(tr("Restore To…"))
        self.btn_restore = primary_button(tr("Restore"))
        self.btn_restore.setToolTip(tr("Put the selected items back where they were (existing files are never "
                                       "overwritten)"))
        v.addLayout(hbox(self.info, None, self.btn_history, self.btn_restore_to, self.btn_restore))

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(300)
        self._search_timer.timeout.connect(self._run_search)
        self.search.textChanged.connect(lambda _t: self._search_timer.start())
        self.source.currentIndexChanged.connect(self._source_changed)
        self.btn_up.clicked.connect(self.go_up)
        self.view.doubleClicked.connect(self._open)
        self.view.activated.connect(self._open)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._update_buttons())
        self.timeline.currentChanged.connect(self._time_changed)
        self.btn_restore.clicked.connect(lambda: self.restore(None))
        self.btn_restore_to.clicked.connect(self._restore_to)
        self.btn_history.clicked.connect(self._history)
        QShortcut(QKeySequence(Qt.Key_Backspace), self.view, activated=self.go_up)
        QShortcut(QKeySequence("Alt+Up"), self, activated=self.go_up)
        QShortcut(QKeySequence.Find, self, activated=self.search.setFocus)
        self._update_buttons()

    # ------------------------------------------------------------------ loading

    def activated(self):
        self.source.blockSignals(True)
        cur = self.source_id
        self.source.clear()
        for s in self.ctrl.cfg.sources:
            self.source.addItem(os.path.basename(s.path) or s.path, s.id)
        if cur:
            i = self.source.findData(cur)
            if i >= 0:
                self.source.setCurrentIndex(i)
        self.source.blockSignals(False)
        self.source_id = self.source.currentData()
        self._load_timeline()
        self.reload()

    def _query_time(self) -> float:
        return time.time() + 1 if self.t == NOW else self.t + 0.001

    def _load_timeline(self):
        def work():
            idx, root = self.ctrl.service.open_catalog()
            if idx is None:
                return None, None
            try:
                return idx.snapshot_times(), root
            finally:
                idx.close()

        def done(r):
            times, root = r
            if times is not None:
                self.timeline.set_times(times)
            self._set_banner(root, times is not None)

        run_async(work, done, lambda m: self._set_banner(None, False))

    def _set_banner(self, root, have_index):
        if not have_index:
            self.banner.setText(tr("No backup index found yet. Connect your backup drive and run a backup."))
            self.banner.show()
        elif not root:
            self.banner.setText(tr("The backup drive is not connected: you are browsing the saved index. "
                                   "Connect the drive to restore."))
            self.banner.show()
        else:
            self.banner.hide()
        self._live = bool(root)
        self._update_buttons()

    def reload(self):
        if self._search_mode:
            self._run_search()
            return
        self._gen += 1
        gen, sid, key, t = self._gen, self.source_id, self.folder_key, self._query_time()
        self._set_crumb()
        if not sid:
            self.model.set_rows([])
            self._show_empty(tr("Add a folder on the Back Up page first."))
            return

        def work():
            idx, _root = self.ctrl.service.open_catalog()
            if idx is None:
                return gen, []
            try:
                lst = catalog.list_folder(idx, sid, key, t)
            finally:
                idx.close()
            rows = [{"kind": "dir", "name": n, "key": k} for n, k in lst.folders]
            rows += [{"kind": "file", "name": c.rel_path.replace("\\", "/").rsplit("/", 1)[-1], "copy": c,
                      "status": st} for c, st in lst.files]
            return gen, rows

        run_async(work, self._loaded, lambda m: self._show_empty(m.splitlines()[0]))

    def _loaded(self, r):
        gen, rows = r
        if gen != self._gen:
            return  # stale result (user moved on)
        self.model.set_rows(rows)
        self._show_empty("" if rows else tr("Nothing was backed up in this folder at that time."))
        self._update_buttons()

    def _show_empty(self, text):
        self.empty.setText(text)
        self.empty.setVisible(bool(text))

    def _set_crumb(self):
        name = self.source.currentText()
        if self._search_mode:
            self.crumb.setText(tr("Search results"))
        elif self.folder_key:
            self.crumb.setText("  ›  ".join([name] + self.folder_names))
        else:
            self.crumb.setText(name)
        self.btn_up.setEnabled(bool(self.folder_key) and not self._search_mode)

    def _run_search(self):
        term = self.search.text().strip()
        self._search_mode = bool(term)
        self.timeline.setEnabled(not self._search_mode)
        if not term:
            self.reload()
            return
        self._gen += 1
        gen = self._gen
        self._set_crumb()

        def work():
            idx, _root = self.ctrl.service.open_catalog()
            if idx is None:
                return gen, []
            try:
                rows = []
                for c in idx.search(term, 1000):
                    label_ = c.rel_path
                    if not c.is_current:
                        label_ += "   (" + fmt_datetime(c.valid_from) + ")"
                    rows.append({"kind": "file", "name": label_, "copy": c, "status": catalog.status_of(c)})
                return gen, rows
            finally:
                idx.close()

        run_async(work, self._loaded, lambda m: self._show_empty(m.splitlines()[0]))

    # ------------------------------------------------------------------ navigation

    def _source_changed(self, _i):
        self.source_id = self.source.currentData()
        self.folder_key = ""
        self.folder_names = []
        self.reload()

    def _time_changed(self, t):
        self.t = t
        self.reload()

    def _open(self, idx):
        r = self.model.row(idx.row())
        if r["kind"] == "dir":
            self.folder_key = r["key"]
            self.folder_names.append(r["name"])
            self.reload()

    def go_up(self):
        if self._search_mode or not self.folder_key:
            return
        self.folder_key = self.folder_key.rsplit("/", 1)[0] if "/" in self.folder_key else ""
        if self.folder_names:
            self.folder_names.pop()
        self.reload()

    # ------------------------------------------------------------------ restore

    def _selected(self):
        rows = sorted({i.row() for i in self.view.selectionModel().selectedRows()})
        return [self.model.row(r) for r in rows]

    def _update_buttons(self):
        sel = self._selected() if hasattr(self, "view") else []
        live = getattr(self, "_live", False)
        busy_ok = True
        self.btn_restore.setEnabled(bool(sel) and live and busy_ok)
        self.btn_restore_to.setEnabled(bool(sel) and live and busy_ok)
        self.btn_history.setEnabled(len(sel) == 1 and sel[0]["kind"] == "file")
        files = [r for r in sel if r["kind"] == "file"]
        if sel:
            size = sum(r["copy"].size for r in files)
            self.info.setText(tr("%1 selected").replace("%1", str(len(sel))) + (f" · {human_size(size)}" if files else ""))
        else:
            self.info.setText("")

    def _restore_to(self):
        d = QFileDialog.getExistingDirectory(self, tr("Restore to which folder?"), os.path.expanduser("~"))
        if d:
            self.restore(d)

    def restore(self, dest: str | None):
        sel = self._selected()
        if not sel:
            return
        ids = [r["copy"].id for r in sel if r["kind"] == "file"]
        folders = [(self.source_id, r["key"]) for r in sel if r["kind"] == "dir"]
        self.btn_restore.setEnabled(False)
        self.btn_restore_to.setEnabled(False)
        self.info.setText(tr("Restoring…"))

        def prog(d):
            self.info.setText(tr("Restoring… %1 of %2").replace("%1", str(d.get("done", 0))).replace(
                "%2", str(d.get("total", 0))))

        def done(res):
            self._update_buttons()
            msg = tr("Restored %1 items (%2). Every file was checked against its backup.").replace(
                "%1", str(len(res.restored))).replace("%2", human_size(res.bytes))
            if res.skipped:
                msg += "\n" + tr("%1 were already identical and were left as they are.").replace(
                    "%1", str(len(res.skipped)))
            renamed = [t for _c, t in res.restored if ".restored" in os.path.basename(t)]
            if renamed:
                msg += "\n" + tr("%1 were saved with “.restored” in the name because a file with the same name "
                                 "already existed.").replace("%1", str(len(renamed)))
            if res.failed:
                msg += "\n\n" + tr("%1 could not be restored:").replace("%1", str(len(res.failed))) + "\n" + \
                    "\n".join(f"• {t or ''}: {why}" for _c, t, why in res.failed[:10])
                QMessageBox.warning(self, "VaultMove", msg)
            else:
                QMessageBox.information(self, "VaultMove", msg)
            self.reload()

        def err(m):
            self._update_buttons()
            QMessageBox.warning(self, "VaultMove", tr("Restore failed: %1").replace("%1", m.splitlines()[0]))

        self.ctrl.service.restore(ids, folders, self._query_time(), dest, done, err, prog)

    def _history(self):
        sel = self._selected()
        if len(sel) != 1 or sel[0]["kind"] != "file":
            return
        from .dialogs import HistoryDialog
        c = sel[0]["copy"]
        HistoryDialog(self.ctrl, c.source_id, c.rel_path, self).exec()
