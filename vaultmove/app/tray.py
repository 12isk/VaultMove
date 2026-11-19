"""System tray icon: live status, menu, notifications (Qt balloons/toasts, no extra deps)."""

from __future__ import annotations

import time

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import icon as icons
from .i18n import tr


class Tray(QSystemTrayIcon):
    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self._state = None
        self._progress_bucket = None
        self._last_notice: dict[str, float] = {}
        self._icons = {s: icons.make_icon(s) for s in icons.STATES}
        self.menu = QMenu()
        self.act_status = QAction("", self.menu)
        self.act_status.setEnabled(False)
        self.act_backup = QAction(tr("Back Up Now"), self.menu)
        self.act_open = QAction(tr("Open VaultMove"), self.menu)
        self.act_pause = QAction(tr("Pause Backups"), self.menu)
        self.act_browse = QAction(tr("Browse Backups"), self.menu)
        self.act_quit = QAction(tr("Quit VaultMove"), self.menu)
        for a in (self.act_status, None, self.act_backup, self.act_open, self.act_browse, self.act_pause, None,
                  self.act_quit):
            if a is None:
                self.menu.addSeparator()
            else:
                self.menu.addAction(a)
        self.act_backup.triggered.connect(lambda: ctrl.backup_now())
        self.act_open.triggered.connect(lambda: ctrl.show_window())
        self.act_browse.triggered.connect(lambda: ctrl.show_window(tab=1))
        self.act_pause.triggered.connect(lambda: ctrl.toggle_pause())
        self.act_quit.triggered.connect(lambda: ctrl.quit())
        self.setContextMenu(self.menu)
        self.activated.connect(self._activated)
        self.set_state("idle", tr("VaultMove"))

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.ctrl.show_window()

    def set_state(self, state: str, text: str, progress: float | None = None):
        """state: idle | running | missing | error | paused"""
        bucket = None if progress is None else int(progress * 12)
        if state != self._state or (state == "running" and bucket != self._progress_bucket):
            if state == "running" and progress is not None:
                self.setIcon(icons.make_icon("running", bucket / 12))
            else:
                self.setIcon(self._icons.get(state, self._icons["idle"]))
            self._state = state
            self._progress_bucket = bucket
        self.setToolTip("VaultMove\n" + text)
        self.act_status.setText(text)
        self.act_backup.setEnabled(state != "running")
        self.act_pause.setText(tr("Resume Backups") if self.ctrl.cfg.paused else tr("Pause Backups"))

    def notify(self, key: str, title: str, message: str, level: str = "info", min_interval: float = 0):
        """Show a notification unless the same kind was shown within min_interval seconds."""
        now = time.time()
        if min_interval and now - self._last_notice.get(key, 0) < min_interval:
            return False
        self._last_notice[key] = now
        icon = {"info": QSystemTrayIcon.Information, "warning": QSystemTrayIcon.Warning,
                "error": QSystemTrayIcon.Critical}[level]
        if self.supportsMessages() and self.isVisible():
            self.showMessage(title, message, icon, 6000)
        return True
