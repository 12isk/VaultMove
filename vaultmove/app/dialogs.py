"""Dialogs: Preview, turn on Free-up-space, Settings, file history."""

from __future__ import annotations

import datetime as dt
import os
import time

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
                               QSpinBox, QTableView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import catalog, vault
from .i18n import LANGUAGES, N_, tr
from .widgets import Card, fmt_datetime, hbox, human_size, label, primary_button
from .workers import run_async


# ---------------------------------------------------------------------------------------------- preview


class PlanModel(QAbstractTableModel):
    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.all = items
        self.rows = items
        self.names = {"copy": tr("Copy to backup"), "delete": tr("Free on this PC"),
                      "eligible": tr("Free on a later run")}

    def set_filter(self, action: str | None):
        self.beginResetModel()
        self.rows = [i for i in self.all if action is None or i.action == action]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 3

    def headerData(self, s, o, role=Qt.DisplayRole):  # noqa: N802
        if role == Qt.DisplayRole and o == Qt.Horizontal:
            return [tr("Action"), tr("File"), tr("Size")][s]
        return None

    def data(self, idx, role=Qt.DisplayRole):
        it = self.rows[idx.row()]
        if role == Qt.DisplayRole:
            return [self.names.get(it.action, it.action), it.path, human_size(it.size)][idx.column()]
        if role == Qt.TextAlignmentRole and idx.column() == 2:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ToolTipRole:
            return it.path + (f"\n{it.note}" if it.note else "")
        return None


class PreviewDialog(QDialog):
    def __init__(self, res, parent=None, accept_text: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Preview"))
        self.resize(860, 560)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(12)
        v.addWidget(label(tr("Nothing has been changed. This is what the next backup would do:"), "H2", wrap=True))
        plan = res.plan
        stats = QHBoxLayout()
        for action, title in (("copy", tr("Will be copied")), ("delete", tr("Will be freed on this PC")),
                              ("eligible", tr("Freed after this backup is verified"))):
            n, b = plan.total(action)
            c = Card(shadow=False, margins=(14, 10, 14, 10), spacing=2)
            c.add(label(title, "Subtle"))
            c.add(label(human_size(b), "Stat"))
            c.add(label(tr("%1 files").replace("%1", f"{n:,}"), "Subtle"))
            stats.addWidget(c)
        v.addLayout(stats)
        for m in res.messages:
            v.addWidget(label(m, "Warning", wrap=True))
        self.filter = QComboBox()
        self.filter.addItem(tr("Everything"), None)
        self.filter.addItem(tr("Files freed on this PC"), "delete")
        self.filter.addItem(tr("Files copied"), "copy")
        self.filter.addItem(tr("Freed on a later run"), "eligible")
        self.filter.setAccessibleName(tr("Show"))
        v.addLayout(hbox(label(tr("Show:")), self.filter, None))
        self.model = PlanModel(plan.items, self)
        self.view = QTableView()
        self.view.setModel(self.model)
        self.view.setAccessibleName(tr("Planned actions"))
        self.view.verticalHeader().hide()
        self.view.setShowGrid(False)
        self.view.setSelectionBehavior(QTableView.SelectRows)
        h = self.view.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        card = Card(shadow=False, margins=(8, 8, 8, 8))
        card.add(self.view)
        v.addWidget(card, 1)
        self.filter.currentIndexChanged.connect(lambda _i: self.model.set_filter(self.filter.currentData()))
        if plan.total("delete")[0]:
            self.filter.setCurrentIndex(1)
        if accept_text:
            self.btn_start = primary_button(accept_text)
            self.btn_start.setFocusPolicy(Qt.StrongFocus)
            back = QPushButton(tr("Back"))
            back.clicked.connect(self.reject)
            self.btn_start.clicked.connect(self.accept)
            v.addLayout(hbox(None, back, self.btn_start))
            self.btn_start.setDefault(True)
        else:
            bb = QDialogButtonBox(QDialogButtonBox.Close)
            bb.rejected.connect(self.reject)
            bb.accepted.connect(self.accept)
            v.addWidget(bb)


# ---------------------------------------------------------------------------------------------- offload


class OffloadDialog(QDialog):
    """Turning on Free-up-space: explicit confirmation + a Preview that must be seen first."""

    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.previewed = False
        self._was_enabled = ctrl.cfg.offload.enabled
        self.setWindowTitle(tr("Free up space on this PC"))
        self.resize(560, 380)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 16)
        v.setSpacing(12)
        v.addWidget(label(tr("Free up space on this PC"), "Title"))
        v.addWidget(label(tr(
            "VaultMove can remove files from this PC once they are safely on your backup drive. Before removing "
            "a file it re-reads both the original and the copy and checks they are identical. The backup drive "
            "then holds the only copy, so keep it safe."), wrap=True))
        self.days = QSpinBox()
        self.days.setRange(1, 3650)
        self.days.setValue(ctrl.cfg.offload.after_days)
        self.days.setSuffix(" " + tr("days"))
        self.days.setAccessibleName(tr("Days before freeing space"))
        v.addLayout(hbox(label(tr("Only files not changed for at least")), self.days, None))
        rec = tr("During your first week, removed files go to the Recycle Bin.") if ctrl.cfg.recycle_effective() \
            else tr("Removed files are deleted permanently from this PC (Settings → Recycle Bin to change).")
        v.addWidget(label(rec, "Subtle", wrap=True))
        self.cb = QCheckBox(tr("I understand that originals will be removed from this PC after their copy is "
                               "verified on the backup drive."))
        self.cb.setAccessibleName(tr("Confirm"))
        v.addWidget(self.cb)
        self.lb_prev = label(tr("Step 1: look at the preview. Step 2: confirm and turn on."), "Subtle", wrap=True)
        v.addWidget(self.lb_prev)
        v.addStretch(1)
        self.btn_preview = QPushButton(tr("Preview…"))
        self.btn_on = primary_button(tr("Turn On"))
        self.btn_cancel = QPushButton(tr("Cancel"))
        v.addLayout(hbox(self.btn_preview, None, self.btn_cancel, self.btn_on))
        self.btn_on.setEnabled(False)
        self.btn_preview.clicked.connect(self._preview)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_on.clicked.connect(self._turn_on)
        self.cb.toggled.connect(self._update)
        self.days.valueChanged.connect(lambda _v: self._invalidate())
        ctrl.service.previewReady.connect(self._preview_ready)
        self.btn_preview.setEnabled(bool(ctrl.vault_root))
        if not ctrl.vault_root:
            self.lb_prev.setText(tr("Connect your backup drive to see the preview."))

    def _invalidate(self):
        self.previewed = False
        self._update()

    def _update(self):
        self.btn_on.setEnabled(self.previewed and self.cb.isChecked())

    def _preview(self):
        o = self.ctrl.cfg.offload
        o.enabled = True          # enabled-but-not-confirmed: previews only, never deletes
        o.confirmed_at = None
        o.after_days = self.days.value()
        self._waiting = True
        if not self.ctrl.service.start_preview():
            QMessageBox.information(self, "VaultMove", tr("A backup is running. Try again when it has finished."))
            return
        self.btn_preview.setEnabled(False)
        self.lb_prev.setText(tr("Preparing preview…"))

    def _preview_ready(self, res):
        if not getattr(self, "_waiting", False):
            return
        self._waiting = False
        self.btn_preview.setEnabled(True)
        if res is None or res.status not in ("ok", "partial"):
            self.lb_prev.setText(tr("The preview could not be completed. See the activity log."))
            return
        PreviewDialog(res, self).exec()
        n, b = res.plan.total("delete")
        n2, b2 = res.plan.total("eligible")
        self.lb_prev.setText(tr("Preview done: %1 files (%2) would be freed now, %3 more (%4) after this backup.")
                             .replace("%1", f"{n:,}").replace("%2", human_size(b))
                             .replace("%3", f"{n2:,}").replace("%4", human_size(b2)))
        self.previewed = True
        self._update()

    def _turn_on(self):
        o = self.ctrl.cfg.offload
        now = time.time()
        o.enabled = True
        o.after_days = self.days.value()
        o.confirmed_at = now
        o.preview_done_at = now
        self.ctrl.save()
        self.accept()

    def reject(self):
        o = self.ctrl.cfg.offload
        if not (o.confirmed_at and o.preview_done_at):
            o.enabled = False
        else:
            o.enabled = self._was_enabled
        self.ctrl.save()
        super().reject()

    def done(self, r):
        try:
            self.ctrl.service.previewReady.disconnect(self._preview_ready)
        except (RuntimeError, TypeError):
            pass
        super().done(r)


# ---------------------------------------------------------------------------------------------- settings

SCHEDULES = [(15, N_("Every 15 minutes")), (30, N_("Every 30 minutes")), (60, N_("Every hour")),
             (120, N_("Every 2 hours")), (240, N_("Every 4 hours")), (720, N_("Every 12 hours")),
             (1440, N_("Once a day"))]
KEEP = [(None, N_("Forever (thinned over time)")), (365, N_("1 year")), (180, N_("6 months")), (90, N_("3 months")),
        (30, N_("1 month"))]
RECYCLE = (("auto", N_("Recycle Bin during the first week")), ("on", N_("Always use the Recycle Bin")),
           ("off", N_("Delete permanently (copy stays on the backup drive)")))


class SettingsDialog(QDialog):
    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        c = ctrl.cfg
        self.setWindowTitle(tr("Settings"))
        self.resize(620, 640)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 14)
        v.setSpacing(12)
        v.addWidget(label(tr("Settings"), "Title"))
        card = Card(shadow=False)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.schedule = QComboBox()
        for m, t in SCHEDULES:
            self.schedule.addItem(tr(t), m)
        self.schedule.setCurrentIndex(max(0, self.schedule.findData(c.schedule_minutes)))
        form.addRow(tr("Back up:"), self.schedule)
        self.plug = QCheckBox(tr("Back up when the backup drive is connected"))
        self.plug.setChecked(c.run_on_plug)
        form.addRow("", self.plug)
        self.startup = QCheckBox(tr("Start VaultMove with Windows"))
        self.startup.setChecked(c.start_with_windows)
        form.addRow("", self.startup)
        self.battery = QCheckBox(tr("Pause on battery below"))
        self.battery.setChecked(c.pause_on_battery)
        self.battery_pct = QSpinBox()
        self.battery_pct.setRange(5, 100)
        self.battery_pct.setSuffix(" %")
        self.battery_pct.setValue(c.battery_min_percent)
        self.battery_pct.setAccessibleName(tr("Battery threshold"))
        w = QWidget()
        w.setLayout(hbox(self.battery, self.battery_pct, None))
        form.addRow(tr("Power:"), w)
        self.lowprio = QCheckBox(tr("Run at low priority so the PC stays responsive"))
        self.lowprio.setChecked(c.low_priority)
        form.addRow("", self.lowprio)
        self.vss = QCheckBox(tr("Copy files that are open (asks for administrator permission on Back Up Now)"))
        self.vss.setChecked(c.vss_enabled)
        form.addRow(tr("Open files:"), self.vss)
        self.keep = QComboBox()
        for d, t in KEEP:
            self.keep.addItem(tr(t), d)
        self.keep.setCurrentIndex(max(0, self.keep.findData(c.keep_versions_days)))
        form.addRow(tr("Keep older versions:"), self.keep)
        self.recycle = QComboBox()
        for val, t in RECYCLE:
            self.recycle.addItem(tr(t), val)
        self.recycle.setCurrentIndex(max(0, self.recycle.findData(c.offload.recycle)))
        form.addRow(tr("Freed files:"), self.recycle)
        self.lang = QComboBox()
        self.lang.addItem(tr("Same as Windows"), "auto")
        for k, n in LANGUAGES.items():
            self.lang.addItem(n, k)
        self.lang.setCurrentIndex(max(0, self.lang.findData(c.language)))
        form.addRow(tr("Language:"), self.lang)
        self.same = QCheckBox(tr("Allow a backup drive on the same disk as my files (not recommended)"))
        self.same.setChecked(c.vault.allow_same_drive)
        form.addRow(tr("Safety:"), self.same)
        card.add(form)
        v.addWidget(card)

        v.addWidget(label(tr("Never back up (one pattern per line, e.g. *.iso or Projects/build/**):"), "Subtle"))
        self.excl = QPlainTextEdit("\n".join(c.excludes))
        self.excl.setAccessibleName(tr("Exclusions"))
        self.excl.setMaximumHeight(110)
        v.addWidget(self.excl)

        self.btn_prune = QPushButton(tr("Delete Old Versions…"))
        self.btn_rebuild = QPushButton(tr("Rebuild Index…"))
        self.btn_logs = QPushButton(tr("Open Log Folder"))
        v.addLayout(hbox(self.btn_prune, self.btn_rebuild, self.btn_logs, None))
        self.btn_prune.clicked.connect(self._prune)
        self.btn_rebuild.clicked.connect(self._rebuild)
        self.btn_logs.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(os.path.join(ctrl.cfg_dir, "logs"))))
        v.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _save(self):
        c = self.ctrl.cfg
        if self.same.isChecked() and not c.vault.allow_same_drive:
            r = QMessageBox.warning(self, "VaultMove", tr(
                "A backup on the same disk as your files does not protect you if that disk fails, and VaultMove "
                "will never free up space on it. Allow it anyway?"), QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        c.schedule_minutes = self.schedule.currentData()
        c.run_on_plug = self.plug.isChecked()
        c.pause_on_battery = self.battery.isChecked()
        c.battery_min_percent = self.battery_pct.value()
        c.low_priority = self.lowprio.isChecked()
        c.vss_enabled = self.vss.isChecked()
        c.keep_versions_days = self.keep.currentData()
        c.offload.recycle = self.recycle.currentData()
        lang_changed = c.language != self.lang.currentData()
        c.language = self.lang.currentData()
        c.vault.allow_same_drive = self.same.isChecked()
        c.excludes = [x.strip() for x in self.excl.toPlainText().splitlines() if x.strip()]
        if self.startup.isChecked() != c.start_with_windows:
            self.ctrl.set_start_with_windows(self.startup.isChecked())
        self.ctrl.save()
        self.ctrl.update_status()
        if lang_changed:
            QMessageBox.information(self, "VaultMove", tr("The new language is used after VaultMove restarts."))
        self.accept()

    def _prune(self):
        if not self.ctrl.vault_root or self.ctrl.service.busy:
            QMessageBox.information(self, "VaultMove", tr("Connect the backup drive and wait for any backup to finish."))
            return
        days, ok = QInputDialog.getInt(self, tr("Delete Old Versions"),
                                       tr("Delete older versions last changed more than this many days ago.\n"
                                          "The latest copy of every file is always kept."), 365, 0, 36500)
        if not ok:
            return
        self.btn_prune.setEnabled(False)

        def done(r):
            self.btn_prune.setEnabled(True)
            QMessageBox.information(self, "VaultMove", tr("Deleted %1 old versions (%2).").replace(
                "%1", str(r[0])).replace("%2", human_size(r[1])))

        def err(m):
            self.btn_prune.setEnabled(True)
            QMessageBox.warning(self, "VaultMove", m.splitlines()[0])

        self.ctrl.service.delete_old_versions(days, done, err)

    def _rebuild(self):
        root = self.ctrl.vault_root
        if not root or self.ctrl.service.busy:
            QMessageBox.information(self, "VaultMove", tr("Connect the backup drive and wait for any backup to finish."))
            return
        r = QMessageBox.question(self, "VaultMove", tr(
            "Rebuild the index by reading every file on the backup drive? This can take a long time. The old index "
            "is kept as a .broken file."))
        if r != QMessageBox.Yes:
            return
        from ..core.rebuild import rebuild_index
        self.btn_rebuild.setEnabled(False)

        def work():
            with vault.VaultLock(root):
                return rebuild_index(root, log=self.ctrl.service._emit_log)

        def done(stats):
            self.btn_rebuild.setEnabled(True)
            QMessageBox.information(self, "VaultMove", tr("Index rebuilt: %1 files, %2 older versions.").replace(
                "%1", str(stats["current"])).replace("%2", str(stats["versions"])))

        run_async(work, done, lambda m: (self.btn_rebuild.setEnabled(True),
                                         QMessageBox.warning(self, "VaultMove", m.splitlines()[0])))


# ---------------------------------------------------------------------------------------------- history


KIND_NAMES = {"copy": N_("Backed up"), "version": N_("Older copy kept"),
              "offload": N_("Removed from this PC (copy verified)"), "restore": N_("Restored"),
              "gone": N_("Deleted on this PC"), "present_again": N_("Back on this PC"),
              "prune": N_("Old version deleted"), "vault_copy_bad": N_("Backup copy failed verification"),
              "recovered": N_("Recovered after an interruption"), "recovered_untracked": N_("Recovered file kept")}


class HistoryDialog(QDialog):
    """'Where did my file go?' - versions and the full event trail of one file."""

    def __init__(self, ctrl, source_id: str, rel_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("File history"))
        self.resize(760, 520)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 14)
        v.addWidget(label(os.path.basename(rel_path), "Title"))
        self.where = label(tr("Loading…"), wrap=True)
        v.addWidget(self.where)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("When"), tr("What"), tr("Details")])
        self.tree.setRootIsDecorated(False)
        self.tree.setAccessibleName(tr("File history"))
        card = Card(shadow=False, margins=(8, 8, 8, 8))
        card.add(self.tree)
        v.addWidget(card, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        def work():
            idx, _root = ctrl.service.open_catalog()
            if idx is None:
                return None
            try:
                return catalog.where_is(idx, source_id, rel_path), catalog.history(idx, source_id, rel_path)
            finally:
                idx.close()

        run_async(work, self._loaded, lambda m: self.where.setText(m.splitlines()[0]))

    def _loaded(self, r):
        if r is None:
            self.where.setText(tr("The index is not available. Connect your backup drive."))
            return
        where, h = r
        self.where.setText(where)
        for e in h["events"]:
            d = e["detail"] or {}
            detail = d.get("vault") or d.get("to") or d.get("original") or ""
            if d.get("method"):
                detail = (tr("Recycle Bin") if d["method"] == "recycle" else tr("deleted")) + " · " + detail
            QTreeWidgetItem(self.tree, [fmt_datetime(e["ts"]), tr(KIND_NAMES.get(e["kind"], e["kind"])), detail])
        for i in range(3):
            self.tree.resizeColumnToContents(i)
