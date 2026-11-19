"""The "Back Up" page: status, drive, folders, free-up-space, live progress and log."""

from __future__ import annotations

import os
import shutil

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFileDialog, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QSpinBox, QStyle, QToolButton, QVBoxLayout, QWidget)

from ..core import fsutil, winapi
from ..core.config import SourceCfg, make_source_id
from .i18n import tr
from .symbols import render as render_symbol, symbol
from .widgets import (Card, Collapsible, EmptyState, StatusBadge, Switch, hbox, human_size, icon_button, kbd, label,
                      primary_button)


def header(symbol_name: str, text: str) -> QHBoxLayout:
    """Card title with a small monoline symbol (icon-to-label gap 6 px)."""
    from . import theme
    ic = QLabel()
    ic.setPixmap(render_symbol(symbol_name, 16, theme.color("subtext")))
    return hbox(ic, label(text, "H2"), None, spacing=6)


class BackupTab(QScrollArea):
    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName("Page")
        self.setWidget(page)
        v = QVBoxLayout(page)
        v.setContentsMargins(2, 6, 2, 6)
        v.setSpacing(16)

        # ---------------------------------------------------------- status card
        self.status_card = Card(margins=(22, 20, 22, 20))
        row = QHBoxLayout()
        row.setSpacing(18)
        self.badge = StatusBadge()
        col = QVBoxLayout()
        col.setSpacing(4)
        self.lb_title = label("", "Title")
        self.lb_title.setAccessibleName(tr("Backup status"))
        self.lb_sub = label("", "Subtle", wrap=True)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName(tr("Backup progress"))
        self.lb_current = label("", "Subtle")
        self.lb_current.setTextInteractionFlags(Qt.NoTextInteraction)
        self.lb_current.setMinimumWidth(100)
        self.lb_current.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addWidget(self.lb_title)
        col.addWidget(self.lb_sub)
        col.addSpacing(4)
        col.addWidget(self.progress)
        col.addWidget(self.lb_current)
        btns = QGridLayout()
        btns.setHorizontalSpacing(8)
        btns.setVerticalSpacing(8)
        self.btn_backup = primary_button(tr("Back Up Now"))
        self.btn_backup.setToolTip(tr("Start a backup now (Ctrl+B)"))
        self.btn_preview = QPushButton(tr("Preview…"))
        self.btn_preview.setToolTip(tr("Show what would be copied and freed, without changing anything (Ctrl+P)"))
        self.btn_stop = QPushButton(tr("Stop"))
        self.btn_stop.setIcon(symbol("stop", 14))
        self.btn_stop.setToolTip(tr("Stop the running backup (Ctrl+.)"))
        self.kbd_backup, self.kbd_preview, self.kbd_stop = kbd("Ctrl+B"), kbd("Ctrl+P"), kbd("Ctrl+.")
        for r, (b, k) in enumerate(((self.btn_backup, self.kbd_backup), (self.btn_preview, self.kbd_preview),
                                    (self.btn_stop, self.kbd_stop))):
            b.setMinimumWidth(150)
            btns.addWidget(k, r, 0, Qt.AlignRight | Qt.AlignVCenter)
            btns.addWidget(b, r, 1)
        btns.setRowStretch(3, 1)
        row.addWidget(self.badge, 0, Qt.AlignTop)
        row.addLayout(col, 1)
        row.addLayout(btns)
        self.status_card.add(row)
        v.addWidget(self.status_card)

        # ---------------------------------------------------------- drive + free space
        mid = QHBoxLayout()
        mid.setSpacing(16)
        self.pc_card = Card()
        self.pc_card.add(header("laptop", tr("This PC")))
        self.pc_box = QVBoxLayout()
        self.pc_box.setSpacing(6)
        self.pc_card.add(self.pc_box)
        self.pc_card.layout().addStretch(1)
        self._pc_rows: list = []
        mid.addWidget(self.pc_card, 1)
        self.drive_card = Card()
        self.drive_card.add(header("drive", tr("Backup drive")))
        self.lb_drive = label("", "Stat")
        self.lb_drive.setAccessibleName(tr("Backup drive name"))
        self.drive_bar = QProgressBar()
        self.drive_bar.setObjectName("Thin")
        self.drive_bar.setTextVisible(False)
        self.drive_bar.setAccessibleName(tr("Backup drive usage"))
        self.lb_drive_free = label("", "Subtle", wrap=True)
        self.btn_drive = QPushButton(tr("Change…"))
        self.drive_card.add(self.lb_drive)
        self.drive_card.add(self.drive_bar)
        self.drive_card.add(self.lb_drive_free)
        self.drive_card.layout().addStretch(1)
        self.drive_card.add(hbox(None, self.btn_drive))
        mid.addWidget(self.drive_card, 1)
        v.addLayout(mid)

        self.free_card = Card()
        self.free_card.add(header("restore", tr("Free up space")))
        self.sw_offload = Switch(accessible_name=tr("Free up space on this PC"))
        self.lb_off_a = label(tr("Remove originals not changed for"))
        self.spin_days = QSpinBox()
        self.spin_days.setRange(1, 3650)
        self.spin_days.setSuffix(" " + tr("days"))
        self.spin_days.setAccessibleName(tr("Days before freeing space"))
        self.free_card.add(hbox(self.sw_offload, 6, self.lb_off_a, self.spin_days, None))
        self.lb_off_info = label("", "Subtle", wrap=True)
        self.btn_off_preview = QPushButton(tr("Preview…"))
        row_info = hbox(self.lb_off_info, self.btn_off_preview, spacing=16)
        row_info.setStretch(0, 1)
        self.free_card.add(row_info)
        self.lb_off_info.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        v.addWidget(self.free_card)

        # ---------------------------------------------------------- folders
        self.folders_card = Card(shadow=True)
        self.btn_add = icon_button("plus", tr("Add a folder (Ctrl+N)"))
        self.btn_remove = icon_button("minus", tr("Remove the selected folder (Delete)"))
        self.folders_card.add(hbox(header("folder", tr("Folders to back up")), None,
                                   label(tr("Drop folders here"), "Caption"), 8, self.btn_add, self.btn_remove))
        self.list = QListWidget()
        self.list.setAccessibleName(tr("Folders to back up"))
        self.list.setMinimumHeight(120)
        self.list.setUniformItemSizes(True)
        self.folders_card.add(self.list)
        self.folders_empty = EmptyState("folder", tr("No folders yet"),
                                        tr("Add the folders you want to protect, or drop them here from Explorer."),
                                        tr("Add a Folder…"))
        self.folders_empty.button.clicked.connect(self.add_folder)
        self.folders_card.add(self.folders_empty)
        self.folders_card.setAcceptDrops(True)
        self.folders_card.installEventFilter(self)
        v.addWidget(self.folders_card)

        # ---------------------------------------------------------- log
        self.log = QPlainTextEdit()
        self.log.setObjectName("Log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setAccessibleName(tr("Activity log"))
        log_card = Card(shadow=False, margins=(16, 10, 16, 12))
        self.collapsible = Collapsible(tr("Activity log"), self.log, expanded_height=220)
        log_card.add(self.collapsible)
        v.addWidget(log_card)
        v.addStretch(1)

        # ---------------------------------------------------------- wiring
        self.btn_backup.clicked.connect(ctrl.backup_now)
        self.btn_stop.clicked.connect(lambda: ctrl.service.cancel("user"))
        self.btn_preview.clicked.connect(self.preview)
        self.btn_off_preview.clicked.connect(self.preview)
        self.btn_add.clicked.connect(self.add_folder)
        self.btn_remove.clicked.connect(self.remove_folder)
        self.btn_drive.clicked.connect(self.change_drive)
        self.sw_offload.toggled.connect(self._offload_toggled)
        self.spin_days.valueChanged.connect(self._days_changed)
        QShortcut(QKeySequence.Delete, self.list, activated=self.remove_folder)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=self.add_folder)
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self.preview)
        ctrl.stateChanged.connect(self.refresh)
        ctrl.progressChanged.connect(self._on_progress)
        ctrl.service.logLine.connect(self.log.appendPlainText)
        ctrl.service.previewReady.connect(self._preview_ready)
        self._expect_preview = False
        self.refresh()

    # ------------------------------------------------------------------ refresh

    def refresh(self):
        c = self.ctrl.cfg
        state, title, sub = self.ctrl.status()
        self.badge.set_state(state)
        self.lb_title.setText(title)
        self.lb_sub.setText(sub)
        busy = self.ctrl.service.busy
        self.progress.setVisible(busy)
        self.lb_current.setVisible(busy)
        self.btn_stop.setVisible(busy)
        self.kbd_stop.setVisible(busy)
        self.btn_backup.setEnabled(not busy and bool(self.ctrl.vault_root))
        self.btn_preview.setEnabled(not busy and bool(self.ctrl.vault_root))
        self.btn_off_preview.setEnabled(not busy and bool(self.ctrl.vault_root) and c.offload.enabled)
        if busy:
            self.progress.setRange(0, 0) if not c.last_scanned else self.progress.setRange(0, 1000)

        # Drive card
        root = self.ctrl.vault_root
        name = c.vault.label or ""
        if root:
            letter = os.path.splitdrive(root)[0]
            self.lb_drive.setText(f"{name} ({letter})" if name else letter)
            try:
                u = shutil.disk_usage(root)
                self.drive_bar.setRange(0, 1000)
                self.drive_bar.setValue(int(1000 * (u.total - u.free) / max(1, u.total)))
                self.lb_drive_free.setText(tr("%1 free of %2").replace("%1", human_size(u.free)).replace(
                    "%2", human_size(u.total)))
            except OSError:
                self.lb_drive_free.setText("")
            self.drive_bar.setVisible(True)
        else:
            self.lb_drive.setText(name or tr("Not connected"))
            self.drive_bar.setVisible(False)
            self.lb_drive_free.setText(tr("Connect the drive and VaultMove will back up automatically.")
                                       if c.vault.uuid else tr("No backup drive chosen yet."))

        self._refresh_pc(c)

        # Free-up-space card
        self.sw_offload.blockSignals(True)
        self.sw_offload.setChecked(c.offload_armed())
        self.sw_offload.blockSignals(False)
        self.spin_days.blockSignals(True)
        self.spin_days.setValue(c.offload.after_days)
        self.spin_days.blockSignals(False)
        if c.offload_armed():
            where = tr("They go to the Recycle Bin first.") if c.recycle_effective() else \
                tr("They are deleted permanently (the copy stays on the backup drive).")
            self.lb_off_info.setText(tr("On. Originals are removed only after their copy on the backup drive is "
                                        "verified.") + " " + where)
        else:
            self.lb_off_info.setText(tr("Off. VaultMove only copies; it never removes anything from this PC."))

        # Folders
        sel = self.list.currentRow()
        self.list.clear()
        icon = symbol("folder", 16, "accent")
        cloud_roots = fsutil.cloud_sync_roots()
        for s in c.sources:
            ok = os.path.isdir(s.path)
            text = s.path if ok else s.path + "   — " + tr("not available")
            if ok and fsutil.in_cloud_sync(fsutil.join(s.path, "x"), cloud_roots):
                if c.offload_cloud:
                    text += "   — " + tr("synced by OneDrive or another cloud service: backed up and freed")
                else:
                    text += "   — " + tr("synced by OneDrive or another cloud service: backed up, never freed")
            it = QListWidgetItem(icon, text)
            it.setData(Qt.UserRole, s.path)
            it.setToolTip(s.path)
            self.list.addItem(it)
        self.list.setVisible(bool(c.sources))
        self.folders_empty.setVisible(not c.sources)
        self.btn_remove.setVisible(bool(c.sources))
        if 0 <= sel < self.list.count():
            self.list.setCurrentRow(sel)

    def pc_drives(self, c) -> list[tuple[str, str]]:
        """(root, display name) of the drives holding the backed-up folders (system drive if none)."""
        roots = []
        for s in c.sources:
            r = os.path.splitdrive(s.path)[0] + "\\"
            if os.path.isdir(r) and r.upper() not in [x.upper() for x in roots]:
                roots.append(r)
        if not roots:
            roots = [winapi.system_drive()]
        out = []
        for r in roots:
            lab = winapi.volume_info(r).get("label") or tr("Local disk")
            out.append((r, f"{lab} ({r.rstrip(chr(92))})"))
        return out

    def _refresh_pc(self, c):
        drives = self.pc_drives(c)
        while len(self._pc_rows) < len(drives):
            name = label("", "Stat")
            bar = QProgressBar()
            bar.setObjectName("Thin")
            bar.setTextVisible(False)
            bar.setRange(0, 1000)
            free = label("", "Subtle", wrap=True)
            for w in (name, bar, free):
                self.pc_box.addWidget(w)
            self._pc_rows.append((name, bar, free))
        for i, (name, bar, free) in enumerate(self._pc_rows):
            vis = i < len(drives)
            for w in (name, bar, free):
                w.setVisible(vis)
            if not vis:
                continue
            root, disp = drives[i]
            name.setText(disp)
            name.setAccessibleName(tr("Drive on this PC"))
            bar.setAccessibleName(tr("Usage of %1").replace("%1", disp))
            try:
                u = shutil.disk_usage(root)
            except OSError:
                free.setText("")
                continue
            bar.setValue(int(1000 * (u.total - u.free) / max(1, u.total)))
            txt = tr("%1 free of %2").replace("%1", human_size(u.free)).replace("%2", human_size(u.total))
            if u.free < 0.1 * u.total:
                txt += " · " + tr("almost full")
            free.setText(txt)
            free.setObjectName("Warning" if u.free < 0.1 * u.total else "Subtle")
            free.style().unpolish(free)
            free.style().polish(free)

    def _on_progress(self, d: dict):
        if not self.progress.isVisible():
            self.refresh()
        exp = self.ctrl.cfg.last_scanned
        if exp:
            self.progress.setRange(0, 1000)
            self.progress.setValue(min(990, int(1000 * d.get("done", 0) / max(1, exp))))
        cur = d.get("current") or ""
        fm = self.lb_current.fontMetrics()
        self.lb_current.setText(fm.elidedText(cur, Qt.ElideMiddle, max(100, self.lb_current.width())))
        state, title, sub = self.ctrl.status()
        self.lb_title.setText(title)
        self.lb_sub.setText(sub)
        self.badge.set_state("running", min(0.97, d.get("done", 0) / max(1, exp)) if exp else None)

    # ------------------------------------------------------------------ actions

    def preview(self):
        if self.ctrl.service.start_preview():
            self._expect_preview = True
            self.refresh()

    def _preview_ready(self, res):
        if not self._expect_preview:
            return
        self._expect_preview = False
        self.refresh()
        if res is None:
            QMessageBox.warning(self, "VaultMove", tr("The preview could not be completed. See the activity log."))
            return
        from .dialogs import PreviewDialog
        if res.status not in ("ok", "partial"):
            QMessageBox.information(self, "VaultMove", tr("Preview not available: %1").replace("%1", res.error or res.status))
            return
        PreviewDialog(res, self).exec()

    def _offload_toggled(self, on: bool):
        c = self.ctrl.cfg
        if not on:
            c.offload.enabled = False
            self.ctrl.save()
            self.refresh()
            return
        from .dialogs import OffloadDialog
        dlg = OffloadDialog(self.ctrl, self)
        if dlg.exec() != OffloadDialog.Accepted:
            self.sw_offload.blockSignals(True)
            self.sw_offload.setChecked(False)
            self.sw_offload.blockSignals(False)
        self.refresh()

    def _days_changed(self, v: int):
        self.ctrl.cfg.offload.after_days = int(v)
        self.ctrl.save()

    def _toast(self, text: str):
        w = self.window()
        if hasattr(w, "notify"):
            w.notify(text)

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("Choose a folder to back up"), os.path.expanduser("~"))
        if d:
            self.add_paths([d])

    def add_paths(self, paths: list[str]) -> int:
        """Add folders (from the dialog or dropped from Explorer). Returns how many were added."""
        added, errors = [], []
        for d in paths:
            if not os.path.isdir(d):
                continue
            err = validate_new_source(self.ctrl.cfg, d, self.ctrl.vault_root)
            if err:
                errors.append(f"{d}: {err}")
                continue
            p = fsutil.normroot(d)
            self.ctrl.cfg.sources.append(SourceCfg(path=p, id=make_source_id(p)))
            added.append(p)
        if added:
            self.ctrl.save()
            self.refresh()
            self._toast(tr("Added “%1”").replace("%1", os.path.basename(added[0]) or added[0]) if len(added) == 1
                        else tr("Added %1 folders").replace("%1", str(len(added))))
        if errors:
            QMessageBox.warning(self, "VaultMove", "\n\n".join(errors))
        return len(added)

    # Drag folders in from Explorer: the card highlights as a drop zone (dashed accent border).
    def eventFilter(self, obj, ev):  # noqa: N802
        if obj is getattr(self, "folders_card", None):
            t = ev.type()
            if t in (QEvent.DragEnter, QEvent.DragMove):
                urls = ev.mimeData().urls() if ev.mimeData().hasUrls() else []
                if any(u.isLocalFile() and os.path.isdir(u.toLocalFile()) for u in urls):
                    ev.acceptProposedAction()
                    self._drop_highlight(True)
                    return True
            elif t == QEvent.DragLeave:
                self._drop_highlight(False)
                return True
            elif t == QEvent.Drop:
                self._drop_highlight(False)
                paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
                ev.acceptProposedAction()
                self.add_paths(paths)
                return True
        return super().eventFilter(obj, ev)

    def _drop_highlight(self, on: bool):
        self.folders_card.setObjectName("DropTarget" if on else "Card")
        self.folders_card.style().unpolish(self.folders_card)
        self.folders_card.style().polish(self.folders_card)

    def remove_folder(self):
        it = self.list.currentItem()
        if it is None or not it.data(Qt.UserRole):
            return
        path = it.data(Qt.UserRole)
        r = QMessageBox.question(self, "VaultMove",
                                 tr("Stop backing up “%1”?\n\nCopies already on the backup drive are kept and can "
                                    "still be restored.").replace("%1", path))
        if r != QMessageBox.Yes:
            return
        s = self.ctrl.cfg.find_source(path)
        if s:
            self.ctrl.cfg.sources.remove(s)
            self.ctrl.save()
            self._toast(tr("Removed “%1”; its copies stay on the backup drive").replace(
                "%1", os.path.basename(path) or path))
        self.refresh()

    def change_drive(self):
        from .wizard import SetupWizard
        w = SetupWizard(self.ctrl, self, drive_only=True)
        w.finishedSetup.connect(lambda: (self.ctrl.refresh_vault(), self.refresh()))
        w.exec()


def validate_new_source(cfg, path: str, vault_root: str | None) -> str:
    """Return an error message, or '' if the folder can be added."""
    p = fsutil.normroot(path)
    if fsutil.is_protected(p):
        return tr("This is a Windows or app-data folder. VaultMove does not back up or remove system files.")
    if len(p) <= 3 and os.path.normcase(p) == os.path.normcase(winapi.system_drive()):
        return tr("Choose specific folders rather than the whole Windows drive.")
    if cfg.find_source(p):
        return tr("This folder is already in the list.")
    for s in cfg.sources:
        if fsutil.is_within(p, s.path) or fsutil.is_within(s.path, p):
            return tr("This folder overlaps “%1”, which is already backed up.").replace("%1", s.path)
    if vault_root and (fsutil.is_within(p, vault_root) or fsutil.is_within(vault_root, p)):
        return tr("This folder contains the backup itself (or is inside it).")
    return ""
