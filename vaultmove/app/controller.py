"""The single owner of settings, tray, scheduler, drive watcher and engine service.

The main window is created lazily (first time it is opened) to keep idle
memory low; closing it only hides it.
"""

from __future__ import annotations

import logging
import os
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from ..core import config as cfgmod, vault, winapi
from ..core.config import Config
from ..core.errors import ConfigError
from . import startup
from .i18n import tr
from .service import BackupService
from .tray import Tray
from .widgets import human_ago, human_size

log = logging.getLogger("vaultmove")

TICK_MS = 60_000


class AppController(QObject):
    stateChanged = Signal()
    progressChanged = Signal(dict)

    def __init__(self, app: QApplication, cfg_dir: str, *, portable: bool = False, theme_mgr=None,
                 enable_tray: bool = True, enable_watch: bool = True, enable_timer: bool = True):
        super().__init__()
        self.app = app
        self.cfg_dir = cfg_dir
        self.cache_dir = os.path.join(cfg_dir, "cache")
        self.portable = portable
        self.theme_mgr = theme_mgr
        self.cfg_error = ""
        try:
            self.cfg = cfgmod.load(cfg_dir)
        except ConfigError as e:
            # Never overwrite a settings file we could not read.
            self.cfg = Config()
            self.cfg_error = str(e)
        if self.cfg.first_use_at is None:
            self.cfg.first_use_at = time.time()
            self.save()
        if self.cfg.start_with_windows and cfgmod.is_frozen():
            # Keep the Run entry pointing at this exe (a portable update changes its name).
            try:
                startup.set_enabled(True, portable)
            except OSError:
                pass
        self.window = None
        self.vault_root: str | None = None
        self.last_result: dict | None = None
        self.progress_info: dict = {}
        self._quitting = False
        self._plug_pending = False

        self.service = BackupService(self)
        self.service.progress.connect(self._on_progress)
        self.service.finished.connect(self._on_finished)
        self.service.busyChanged.connect(lambda _b: self.update_status())

        self.tray = None
        if enable_tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = Tray(self)
            self.tray.show()

        self.watch = None
        if enable_watch:
            from .devicewatch import DeviceWatcher
            self.watch = DeviceWatcher()
            self.watch.volumesChanged.connect(self._on_volumes)
            self.watch.resumed.connect(lambda: QTimer.singleShot(20_000, self.tick))
            self.watch.powerChanged.connect(self._check_power_midrun)

        self.timer = QTimer(self)
        self.timer.setInterval(TICK_MS)
        self.timer.timeout.connect(self.tick)
        if enable_timer:
            self.timer.start()
            QTimer.singleShot(4000, self.tick)
        self.refresh_vault()

    # ------------------------------------------------------------------ settings

    def save(self):
        if self.cfg_error:
            return
        try:
            cfgmod.save(self.cfg, self.cfg_dir)
        except OSError as e:
            log.error("cannot save settings: %s", e)

    def set_start_with_windows(self, on: bool):
        self.cfg.start_with_windows = on
        try:
            startup.set_enabled(on, self.portable)
        except OSError as e:
            log.error("start with Windows: %s", e)
        self.save()

    # ------------------------------------------------------------------ status

    def refresh_vault(self) -> str | None:
        root = vault.locate_vault(self.cfg.vault) if self.cfg.vault.uuid else None
        if root:
            self.cfg.last_vault_seen_at = time.time()
        self.vault_root = root
        self.update_status()
        return root

    def status(self) -> tuple[str, str, str]:
        """(state, title, subtitle) for the tray and the status card."""
        c = self.cfg
        if self.service.busy:
            p = self.progress_info
            phase = p.get("phase", "")
            if phase == "offload":
                title = tr("Freeing up space…")
            elif phase == "preview":
                title = tr("Preparing preview…")
            else:
                title = tr("Backing up…")
            sub = tr("%1 files checked, %2 copied").replace("%1", f"{p.get('done', 0):,}").replace(
                "%2", human_size(p.get("bytes", 0)))
            return "running", title, sub
        if not c.wizard_done or not c.vault.uuid:
            return "missing", tr("Set up VaultMove"), tr("Choose a backup drive to get started.")
        last = (tr("Last backup: %1").replace("%1", human_ago(c.last_run_at))) if c.last_run_at else \
            tr("Not backed up yet")
        if c.paused:
            return "paused", tr("Backups paused"), last
        if not self.vault_root:
            return "missing", tr("Backup drive not connected"), \
                tr("Connect “%1” to back up.").replace("%1", c.vault.label or c.vault.path) + "  " + last
        if c.last_run_status == "error":
            return "error", tr("Last backup needs attention"), c.last_run_error or ""
        if not c.last_run_at:
            return "idle", tr("Ready to back up"), tr("Your first backup will start soon.")
        nxt = max(0, (c.last_run_at + c.schedule_minutes * 60) - time.time())
        sub = tr("Next backup in %1 min").replace("%1", str(int(nxt // 60) + 1)) if nxt else tr("Next backup soon")
        return "idle", tr("Backed up %1").replace("%1", human_ago(c.last_run_at)), sub

    def update_status(self):
        state, title, sub = self.status()
        if self.tray is not None:
            prog = None
            if state == "running":
                exp = max(1, self.cfg.last_scanned)
                prog = min(0.97, self.progress_info.get("done", 0) / exp)
            self.tray.set_state(state, title + ("\n" + sub if sub else ""), prog)
        self.stateChanged.emit()

    # ------------------------------------------------------------------ scheduling

    def power_ok(self) -> bool:
        if not self.cfg.pause_on_battery:
            return True
        on_ac, pct = winapi.power_status()
        return not (on_ac is False and pct is not None and pct < self.cfg.battery_min_percent)

    def _check_power_midrun(self):
        if self.service.busy and not self.power_ok():
            self.service.cancel("battery")

    def tick(self):
        root = self.refresh_vault()
        self._check_power_midrun()
        c = self.cfg
        if not c.wizard_done or c.paused or self.service.busy:
            return
        now = time.time()
        if not root:
            seen = c.last_vault_seen_at or c.last_run_at
            if seen and c.notify_missing_days and now - seen > c.notify_missing_days * 86400 and self.tray:
                if not c.last_missing_notice_at or now - c.last_missing_notice_at > 86400:
                    days = int((now - seen) // 86400)
                    self.tray.notify("missing", tr("Backup drive not connected"),
                                     tr("Your files haven't been backed up for %1 days. Connect your backup "
                                        "drive.").replace("%1", str(days)), "warning")
                    c.last_missing_notice_at = now
                    self.save()
            return
        due = c.last_run_at is None or now - c.last_run_at >= c.schedule_minutes * 60 or now < c.last_run_at
        if (due or self._plug_pending) and self.power_ok():
            self._plug_pending = False
            self.service.start_backup(manual=False)

    def _on_volumes(self):
        was = self.vault_root
        root = self.refresh_vault()
        if root and not was and self.cfg.run_on_plug and self.cfg.wizard_done and not self.cfg.paused:
            log.info("backup drive connected at %s", root)
            self._plug_pending = True
            if not self.service.busy and self.power_ok():
                self._plug_pending = False
                self.service.start_backup(manual=False)

    # ------------------------------------------------------------------ actions

    def backup_now(self) -> bool:
        if not self.cfg.wizard_done:
            self.show_window()
            return False
        if not self.refresh_vault():
            if self.tray:
                self.tray.notify("nodrive", tr("Backup drive not connected"),
                                 tr("Connect your backup drive, then try again."), "warning")
            return False
        return self.service.start_backup(manual=True)

    def toggle_pause(self):
        self.cfg.paused = not self.cfg.paused
        if self.cfg.paused and self.service.busy:
            self.service.cancel("paused")
        self.save()
        self.update_status()

    def _on_progress(self, d: dict):
        self.progress_info = d
        self.progressChanged.emit(d)
        if self.tray is not None:
            exp = max(1, self.cfg.last_scanned)
            frac = min(0.97, d.get("done", 0) / exp)
            state, title, sub = self.status()
            self.tray.set_state("running", title + "\n" + sub, frac)

    def _on_finished(self, d: dict):
        self.last_result = d
        self.progress_info = {}
        c = self.cfg
        st = d.get("stats") or {}
        status = d.get("status")
        if status in ("ok", "partial", "error", "refused"):
            c.last_run_at = d.get("finished_at") or time.time()
            c.last_run_status = "error" if status in ("error", "refused") else status
            c.last_run_error = d.get("error", "")
            if st.get("scanned"):
                c.last_scanned = st["scanned"]
            self.save()
        self.refresh_vault()
        window_up = self.window is not None and self.window.isVisible()
        if window_up and status in ("ok", "partial") and d.get("manual"):
            # Window open: a quiet in-window toast instead of a system notification.
            msg = tr("Backup complete: %1 files copied (%2).").replace("%1", str(st.get("copied", 0))).replace(
                "%2", human_size(st.get("copied_bytes", 0)))
            if st.get("offloaded"):
                msg += " " + tr("%1 freed on this PC.").replace("%1", human_size(st.get("offloaded_bytes", 0)))
            self.window.notify(msg)
        if self.tray is not None:
            if status in ("ok", "partial"):
                if d.get("manual") and not window_up:
                    msg = tr("%1 files copied (%2).").replace("%1", str(st.get("copied", 0))).replace(
                        "%2", human_size(st.get("copied_bytes", 0)))
                    if st.get("offloaded"):
                        msg += " " + tr("%1 freed on this PC.").replace("%1", human_size(st.get("offloaded_bytes", 0)))
                    self.tray.notify("done", tr("Backup complete"), msg)
                elif st.get("offloaded"):
                    self.tray.notify("freed", tr("Space freed"),
                                     tr("%1 freed on this PC. Copies are safe on your backup drive.").replace(
                                         "%1", human_size(st.get("offloaded_bytes", 0))), min_interval=3600)
                if st.get("locked", 0) > st.get("locked_copied", 0) and not d.get("manual"):
                    self.tray.notify("locked", tr("Some files were in use"),
                                     tr("%1 open files were skipped. Click Back Up Now to copy them using a "
                                        "snapshot.").replace("%1", str(st["locked"] - st.get("locked_copied", 0))),
                                     min_interval=86400)
            elif status in ("error", "refused"):
                self.tray.notify("error", tr("Backup needs attention"), d.get("error", ""), "error",
                                 min_interval=3600)
        if self._quitting:
            self.app.quit()
            return
        if self._plug_pending:
            QTimer.singleShot(1000, self.tick)

    # ------------------------------------------------------------------ windows

    def show_window(self, tab: int | None = None):
        if not self.cfg.wizard_done:
            self.show_wizard()
            return
        if self.window is None:
            from .mainwindow import MainWindow
            self.window = MainWindow(self)
        if tab is not None:
            self.window.set_tab(tab)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def show_wizard(self):
        from .wizard import SetupWizard
        if getattr(self, "_wizard", None) is not None and self._wizard.isVisible():
            self._wizard.raise_()
            self._wizard.activateWindow()
            return
        self._wizard = SetupWizard(self)
        self._wizard.finishedSetup.connect(self._after_wizard)
        self._wizard.show()
        self._wizard.raise_()
        self._wizard.activateWindow()

    def _after_wizard(self):
        self._wizard = None
        self.refresh_vault()
        self.show_window()
        self.backup_now()

    def quit(self):
        if self.service.busy:
            r = QMessageBox.question(None, "VaultMove",
                                     tr("A backup is running. Stop it and quit? Nothing will be lost; it "
                                        "continues next time."))
            if r != QMessageBox.Yes:
                return
            self._quitting = True
            self.service.cancel("quit")
            QTimer.singleShot(15_000, self.app.quit)
            return
        self.app.quit()

    def shutdown(self):
        if self.tray is not None:
            self.tray.hide()
