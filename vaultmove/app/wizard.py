"""First-run wizard (3 steps): backup drive, folders, free up space (+ mandatory preview)."""

from __future__ import annotations

import copy
import os
import time

from PySide6.QtCore import QStandardPaths, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem,
                               QMessageBox, QPushButton, QSpinBox, QStackedWidget, QStyle, QVBoxLayout, QWidget)

from ..core import fsutil, vault, winapi
from ..core.config import SourceCfg, make_source_id
from ..core.engine import Engine
from ..core.errors import VaultMoveError
from . import icon as icons
from .backup_tab import validate_new_source
from .i18n import tr
from .widgets import Card, Switch, hbox, human_size, label, primary_button
from .workers import run_async


class StepDots(QWidget):
    def __init__(self, n, parent=None):
        super().__init__(parent)
        self.n, self.i = n, 0
        self.setFixedHeight(14)
        self.setMinimumWidth(16 * n)

    def set_step(self, i):
        self.i = i
        self.update()

    def paintEvent(self, _e):
        from PySide6.QtGui import QColor, QPainter
        from . import theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for k in range(self.n):
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color("accent") if k == self.i else theme.color("track"))
            p.drawEllipse(4 + k * 18, 2, 10, 10)


class DrivePage(QWidget):
    changed = Signal()

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.dest = ""
        self.state = ""
        self.same_disk = None
        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.addWidget(label(tr("Choose your backup drive"), "Title"))
        v.addWidget(label(tr("Use an external drive (USB disk or SSD). VaultMove recognises it by its identity, "
                             "not its drive letter, and never writes backups anywhere else."), "Subtle", wrap=True))
        self.list = QListWidget()
        self.list.setAccessibleName(tr("Available drives"))
        self.list.setMinimumHeight(150)
        card = Card(shadow=False, margins=(8, 8, 8, 8))
        card.add(self.list)
        v.addWidget(card, 1)
        self.btn_folder = QPushButton(tr("Choose a Folder…"))
        self.btn_refresh = QPushButton(tr("Refresh"))
        v.addLayout(hbox(self.btn_refresh, None, self.btn_folder))
        self.lb_state = label("", wrap=True)
        v.addWidget(self.lb_state)
        self.cb_same = QCheckBox(tr("Use it anyway (not recommended: a disk failure would lose both copies)"))
        self.cb_same.hide()
        v.addWidget(self.cb_same)
        self.list.currentItemChanged.connect(self._picked)
        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_folder.clicked.connect(self._choose_folder)
        self.cb_same.toggled.connect(lambda _b: self.changed.emit())
        self.refresh()

    def refresh(self):
        self.list.clear()
        sysd = os.path.normcase(winapi.system_drive())
        drives = winapi.list_drives()
        icon = self.style().standardIcon(QStyle.SP_DriveHDIcon)
        for d in sorted(drives, key=lambda d: (os.path.normcase(d["root"]) == sysd, d["type"] != winapi.DRIVE_REMOVABLE)):
            name = d["label"] or (tr("USB drive") if d["type"] == winapi.DRIVE_REMOVABLE else tr("Local disk"))
            text = f"{name} ({d['letter']}:)   —   " + tr("%1 free of %2").replace("%1", human_size(d["free"])).replace(
                "%2", human_size(d["total"]))
            if os.path.normcase(d["root"]) == sysd:
                text += "   · " + tr("Windows drive")
            if d["type"] == winapi.DRIVE_REMOVABLE:
                text += "   · " + tr("removable")
            it = QListWidgetItem(icon, text)
            it.setData(Qt.UserRole, os.path.join(d["root"], "VaultMove"))
            if d["type"] == winapi.DRIVE_REMOTE:
                it.setFlags(Qt.NoItemFlags)
                it.setText(text + "   · " + tr("network drives are not supported"))
            self.list.addItem(it)
        if not drives:
            it = QListWidgetItem(tr("No drives found. Connect your backup drive and click Refresh."))
            it.setFlags(Qt.NoItemFlags)
            self.list.addItem(it)

    def _picked(self, it, _prev=None):
        if it is not None and it.data(Qt.UserRole):
            self.set_dest(it.data(Qt.UserRole))

    def _choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("Choose the backup folder"))
        if d:
            self.set_dest(d)

    def set_dest(self, path: str):
        self.dest = fsutil.normroot(path)
        self.state = vault.inspect_destination(self.dest)
        others = [s.path for s in self.ctrl.cfg.sources] or [os.path.expanduser("~")]
        sames = [winapi.same_physical_disk(os.path.dirname(self.dest) if self.state == "new" else self.dest, o)
                 for o in others if os.path.isdir(o)]
        self.same_disk = True if any(s is True for s in sames) else (None if any(s is None for s in sames) else False)
        msg = {
            "new": tr("A new backup will be created in %1."),
            "vault": tr("An existing VaultMove backup was found in %1. It will be used and nothing in it is deleted."),
            "not_empty": tr("%1 already contains other files. Choose an empty folder or a whole drive."),
            "missing": tr("%1 cannot be reached."),
            "parent_missing": tr("%1 cannot be reached."),
        }[self.state].replace("%1", self.dest)
        self.lb_state.setObjectName("Danger" if self.state in ("not_empty", "missing", "parent_missing") else "")
        if self.same_disk:
            msg += "\n" + tr("Warning: this is the same physical disk as your files. If that disk fails, the backup "
                             "is lost too, and VaultMove will never free up space on it.")
            self.lb_state.setObjectName("Warning")
        self.lb_state.setText(msg)
        self.lb_state.style().unpolish(self.lb_state)
        self.lb_state.style().polish(self.lb_state)
        self.cb_same.setVisible(bool(self.same_disk))
        self.cb_same.setChecked(False)
        self.changed.emit()

    def ok(self) -> bool:
        return bool(self.dest) and self.state in ("new", "vault") and (not self.same_disk or self.cb_same.isChecked())


class FoldersPage(QWidget):
    changed = Signal()
    KNOWN = ((QStandardPaths.DocumentsLocation, True), (QStandardPaths.PicturesLocation, True),
             (QStandardPaths.DesktopLocation, True), (QStandardPaths.MoviesLocation, False),
             (QStandardPaths.MusicLocation, False), (QStandardPaths.DownloadLocation, False))

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.addWidget(label(tr("Choose what to back up"), "Title"))
        v.addWidget(label(tr("You can change this later on the Back Up page."), "Subtle"))
        self.list = QListWidget()
        self.list.setAccessibleName(tr("Folders to back up"))
        card = Card(shadow=False, margins=(8, 8, 8, 8))
        card.add(self.list)
        v.addWidget(card, 1)
        self.btn_add = QPushButton(tr("Add a Folder…"))
        v.addLayout(hbox(None, self.btn_add))
        self.btn_add.clicked.connect(self._add)
        self.list.itemChanged.connect(lambda _i: self.changed.emit())
        seen = set()
        existing = [s.path for s in ctrl.cfg.sources]
        for loc, default in self.KNOWN:
            p = QStandardPaths.writableLocation(loc)
            if p and os.path.isdir(p) and os.path.normcase(p) not in seen:
                seen.add(os.path.normcase(p))
                self._item(fsutil.normroot(p), default or not existing and default)
        for p in existing:
            if os.path.normcase(p) not in seen:
                self._item(p, True)

    def _item(self, path, checked):
        it = QListWidgetItem(self.style().standardIcon(QStyle.SP_DirIcon), path)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        it.setData(Qt.UserRole, path)
        self.list.addItem(it)

    def _add(self):
        d = QFileDialog.getExistingDirectory(self, tr("Choose a folder to back up"), os.path.expanduser("~"))
        if not d:
            return
        tmp = copy.deepcopy(self.ctrl.cfg)
        tmp.sources = [SourceCfg(path=p, id=make_source_id(p)) for p in self.paths()]
        err = validate_new_source(tmp, d, None)
        if err:
            QMessageBox.warning(self, "VaultMove", err)
            return
        self._item(fsutil.normroot(d), True)
        self.changed.emit()

    def paths(self) -> list[str]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def ok(self) -> bool:
        return bool(self.paths())


class SpacePage(QWidget):
    changed = Signal()

    def __init__(self, wizard, parent=None):
        super().__init__(parent)
        self.wiz = wizard
        self.previewed = False
        v = QVBoxLayout(self)
        v.setSpacing(10)
        v.addWidget(label(tr("Free up space?"), "Title"))
        v.addWidget(label(tr("Optional. VaultMove can remove old files from this PC once a verified copy is on the "
                             "backup drive. It is off unless you turn it on here."), "Subtle", wrap=True))
        self.sw = Switch(accessible_name=tr("Free up space on this PC"))
        self.days = QSpinBox()
        self.days.setRange(1, 3650)
        self.days.setValue(90)
        self.days.setSuffix(" " + tr("days"))
        self.days.setAccessibleName(tr("Days before freeing space"))
        v.addLayout(hbox(self.sw, 6, label(tr("Free up space for files not changed for")), self.days, None))
        self.cb = QCheckBox(tr("I understand that originals will be removed from this PC after their copy is "
                               "verified on the backup drive (Recycle Bin during the first week)."))
        v.addWidget(self.cb)
        self.btn_preview = QPushButton(tr("Preview…"))
        v.addLayout(hbox(self.btn_preview, None))
        self.summary = label(tr("A preview is always shown before anything real happens."), "Subtle", wrap=True)
        v.addWidget(self.summary)
        v.addStretch(1)
        self.sw.toggled.connect(self._toggle)
        self.cb.toggled.connect(lambda _b: self.changed.emit())
        self.days.valueChanged.connect(lambda _v: self._invalidate())
        self.btn_preview.clicked.connect(self.preview)
        self._toggle(False)

    def _toggle(self, on):
        self.days.setEnabled(on)
        self.cb.setVisible(on)
        self._invalidate()

    def _invalidate(self):
        self.previewed = False
        self.changed.emit()

    def preview(self):
        cfg = self.wiz.draft_config(offload_preview=True)
        dest, state = self.wiz.drive.dest, self.wiz.drive.state
        self.btn_preview.setEnabled(False)
        self.summary.setText(tr("Preparing preview…"))

        def work():
            if state == "vault":
                m = vault.read_marker(dest)
                cfg.vault.uuid = m["uuid"]
                same = (lambda a, b: winapi.same_physical_disk(a, b))
                return Engine(cfg, vault_root=dest, same_disk_fn=same).preview()
            return Engine(cfg).preview_new_vault()

        run_async(work, self._done, self._err)

    def _err(self, m):
        self.btn_preview.setEnabled(True)
        self.summary.setText(m.splitlines()[0])

    def _done(self, res):
        self.btn_preview.setEnabled(True)
        from .dialogs import PreviewDialog
        PreviewDialog(res, self).exec()
        c = res.plan.total("copy")
        d = res.plan.total("delete")
        e = res.plan.total("eligible")
        txt = tr("First backup: %1 files (%2).").replace("%1", f"{c[0]:,}").replace("%2", human_size(c[1]))
        if self.sw.isChecked():
            txt += " " + tr("Space freed: %1 now, %2 after the copies are verified on a later run.").replace(
                "%1", human_size(d[1])).replace("%2", human_size(e[1]))
        self.summary.setText(txt)
        self.previewed = True
        self.changed.emit()

    def ok(self) -> bool:
        return self.previewed and (not self.sw.isChecked() or self.cb.isChecked())


class SetupWizard(QDialog):
    finishedSetup = Signal()

    def __init__(self, ctrl, parent=None, drive_only: bool = False):
        super().__init__(parent)
        self.ctrl = ctrl
        self.drive_only = drive_only
        self.setWindowTitle(tr("Set up VaultMove") if not drive_only else tr("Change backup drive"))
        self.setWindowIcon(icons.make_icon())
        self.resize(720, 560)
        v = QVBoxLayout(self)
        v.setContentsMargins(26, 20, 26, 18)
        v.setSpacing(14)
        self.stack = QStackedWidget()
        self.drive = DrivePage(ctrl)
        self.stack.addWidget(self.drive)
        self.pages = [self.drive]
        if not drive_only:
            self.folders = FoldersPage(ctrl)
            self.space = SpacePage(self)
            self.stack.addWidget(self.folders)
            self.stack.addWidget(self.space)
            self.pages += [self.folders, self.space]
        self.dots = StepDots(len(self.pages))
        v.addLayout(hbox(self.dots, None))
        v.addWidget(self.stack, 1)
        self.btn_back = QPushButton(tr("Back"))
        self.btn_cancel = QPushButton(tr("Cancel"))
        self.btn_next = primary_button(tr("Continue"))
        v.addLayout(hbox(self.btn_back, None, self.btn_cancel, self.btn_next))
        self.btn_back.clicked.connect(lambda: self._go(-1))
        self.btn_next.clicked.connect(self._next)
        self.btn_cancel.clicked.connect(self.reject)
        for p in self.pages:
            p.changed.connect(self._update)
        if ctrl.watch is not None:
            ctrl.watch.volumesChanged.connect(self.drive.refresh)
        self._update()

    def _go(self, d):
        i = self.stack.currentIndex() + d
        if 0 <= i < len(self.pages):
            self.stack.setCurrentIndex(i)
            self.dots.set_step(i)
            self._update()

    def _update(self):
        i = self.stack.currentIndex()
        last = i == len(self.pages) - 1
        self.btn_back.setVisible(i > 0)
        self.btn_next.setText(tr("Start Backup") if last and not self.drive_only else
                              tr("Use This Drive") if last else tr("Continue"))
        self.btn_next.setEnabled(self.pages[i].ok())

    def _next(self):
        if self.stack.currentIndex() < len(self.pages) - 1:
            self._go(1)
        else:
            self._finish()

    def draft_config(self, offload_preview: bool = False):
        cfg = copy.deepcopy(self.ctrl.cfg)
        if not self.drive_only:
            cfg.sources = [SourceCfg(path=p, id=make_source_id(p)) for p in self.folders.paths()]
            cfg.offload.enabled = self.space.sw.isChecked()
            cfg.offload.after_days = self.space.days.value()
            if offload_preview:
                cfg.offload.confirmed_at = None
        cfg.vault.allow_same_drive = bool(self.drive.same_disk and self.drive.cb_same.isChecked())
        return cfg

    def _finish(self):
        dest = self.drive.dest
        try:
            vid = vault.create_vault(dest)
        except VaultMoveError as e:
            QMessageBox.warning(self, "VaultMove", str(e))
            return
        cfg = self.draft_config()
        old_uuid = self.ctrl.cfg.vault.uuid
        if self.drive_only and old_uuid and old_uuid != vid:
            r = QMessageBox.question(self, "VaultMove", tr(
                "Future backups will go to the new drive. The old backup drive is left untouched and can still be "
                "browsed by choosing it again here."))
            if r != QMessageBox.Yes:
                return
        cfg.vault = vault.vault_cfg_for(dest, vid, allow_same_drive=cfg.vault.allow_same_drive)
        if not self.drive_only:
            now = time.time()
            if cfg.offload.enabled:
                cfg.offload.confirmed_at = now
                cfg.offload.preview_done_at = now
            cfg.wizard_done = True
        self.ctrl.cfg = cfg
        self.ctrl.save()
        self.accept()
        self.finishedSetup.emit()
