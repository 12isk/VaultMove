"""'Check for Updates' dialog. The only place VaultMove ever goes online, and only on click."""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout

from .. import __version__
from ..core import update
from .i18n import tr
from .screens import fit_to_screen
from .widgets import hbox, human_size, label, primary_button
from .workers import run_async


class _Relay(QObject):
    progress = Signal(int, int)


class UpdateDialog(QDialog):
    def __init__(self, ctrl, parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.rel = None
        self.mode = update.install_mode()
        self._cancel = threading.Event()
        self.setWindowTitle(tr("Check for Updates"))
        fit_to_screen(self, 560, 400, center=False)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 16)
        v.setSpacing(10)
        v.addWidget(label(tr("VaultMove updates"), "Title"))
        v.addWidget(label(tr("You are using version %1.").replace("%1", __version__), "Subtle"))
        self.status = label(tr("Checking GitHub for a newer version…"), wrap=True)
        self.status.setAccessibleName(tr("Update status"))
        v.addWidget(self.status)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setAccessibleName(tr("What's new"))
        self.notes.hide()
        v.addWidget(self.notes, 1)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.hide()
        v.addWidget(self.bar)
        v.addWidget(label(tr("VaultMove only contacts GitHub when you click Check for Updates. The download is "
                             "checked against its published SHA-256 checksum before anything is installed. Your "
                             "settings and backups are kept."), "Subtle", wrap=True))
        self.btn_page = QPushButton(tr("Open Release Page"))
        self.btn_page.hide()
        self.btn_close = QPushButton(tr("Close"))
        self.btn_install = primary_button(tr("Download and Install"))
        self.btn_install.hide()
        v.addLayout(hbox(self.btn_page, None, self.btn_close, self.btn_install))
        self.btn_close.clicked.connect(self.reject)
        self.btn_install.clicked.connect(self._install)
        self.btn_page.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.rel.page_url)))
        QTimer.singleShot(0, self._check)

    def _check(self):
        run_async(update.check_latest, self._checked, self._failed)

    def _failed(self, m):
        self.bar.hide()
        self.status.setText(tr("Could not check for updates: %1").replace("%1", m.splitlines()[0]))

    def _checked(self, rel):
        self.rel = rel
        if rel.page_url:
            self.btn_page.show()
        if not update.is_newer(rel.version):
            self.status.setText(tr("VaultMove is up to date (latest version: %1).").replace("%1", rel.version))
            return
        self.status.setText(tr("Version %1 is available.").replace("%1", rel.version))
        if rel.notes:
            self.notes.setPlainText(rel.notes)
            self.notes.show()
        if self.mode == "source":
            self.status.setText(self.status.text() + " " + tr("You are running from source: update with git pull."))
            return
        if rel.asset_for(self.mode) is None or "SHA256SUMS.txt" not in rel.assets:
            self.status.setText(self.status.text() + " " + tr("This release has no download for your version yet."))
            return
        self.btn_install.show()
        self.btn_install.setDefault(True)

    def _install(self):
        if self.ctrl.service.busy:
            self.status.setText(tr("A backup is running. Install the update when it has finished."))
            return
        name, url = self.rel.asset_for(self.mode)
        dest = os.path.join(update.download_dir(self.mode), name)
        self.btn_install.setEnabled(False)
        self.bar.show()
        self.bar.setRange(0, 0)
        self.status.setText(tr("Downloading %1…").replace("%1", name))
        relay = _Relay(self)
        relay.progress.connect(self._progress)
        self._relay = relay
        rel, cancel = self.rel, self._cancel

        def work():
            sha = update.expected_sha256(rel, name)
            return update.download_verified(url, dest, sha, cancel=cancel,
                                            progress=lambda n, t: relay.progress.emit(n, t))

        run_async(work, self._downloaded, self._dl_failed)

    def _progress(self, n, total):
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(1000 * n / total))
        self.status.setText(tr("Downloading… %1").replace("%1", human_size(n) + (f" / {human_size(total)}" if total else "")))

    def _dl_failed(self, m):
        self.bar.hide()
        self.btn_install.setEnabled(True)
        self.status.setText(tr("The update could not be installed: %1").replace("%1", m.splitlines()[0]))

    def _downloaded(self, path):
        if self.ctrl.service.busy:
            self._dl_failed(tr("a backup started; try again when it has finished"))
            return
        self.status.setText(tr("Verified. Installing and restarting VaultMove…"))
        try:
            if self.mode == "portable":
                update.launch_portable(path)
            else:
                update.launch_installer(path)
        except OSError as e:
            self._dl_failed(str(e))
            return
        self.ctrl._quitting = True
        QTimer.singleShot(300, self.ctrl.app.quit)
        self.accept()

    def reject(self):
        self._cancel.set()
        super().reject()
