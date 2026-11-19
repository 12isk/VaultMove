"""Thin service layer between the Qt UI and the engine.

One backup (or preview) at a time, on the thread pool. Engine callbacks run on
the worker thread and are forwarded as Qt signals (queued to the UI thread).
"""

from __future__ import annotations

import logging
import os
import threading
import time

from PySide6.QtCore import QObject, Signal

from ..core import catalog, config as cfgmod, vault
from ..core.engine import Engine, delete_old_versions
from ..core.restore import restore_many
from .workers import run_async

log = logging.getLogger("vaultmove")


class _Relay(QObject):
    progress = Signal(dict)


class BackupService(QObject):
    started = Signal(bool)          # manual?
    progress = Signal(dict)
    logLine = Signal(str)
    finished = Signal(dict)         # RunResult.to_dict() + {"manual", "dry_run"}
    previewReady = Signal(object)   # RunResult with .plan
    busyChanged = Signal(bool)

    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self._cancel: threading.Event | None = None
        self._busy = False
        self.cancel_reason = ""
        self._relays: set = set()

    @property
    def busy(self) -> bool:
        return self._busy

    def _set_busy(self, b: bool):
        self._busy = b
        self.busyChanged.emit(b)

    def _emit_log(self, msg: str):
        log.info(msg)
        self.logLine.emit(time.strftime("%H:%M:%S  ") + msg)

    def _engine(self, cancel, manual: bool) -> Engine:
        from ..helper import client as vss_client
        return Engine(self.ctrl.cfg, progress=self.progress.emit, log=self._emit_log, cancel=cancel,
                      cache_dir=self.ctrl.cache_dir, manual=manual,
                      vss_factory=vss_client.session_factory if self.ctrl.cfg.vss_enabled else None)

    # ------------------------------------------------------------------ backup / preview

    def start_backup(self, manual: bool = False) -> bool:
        if self._busy:
            return False
        self._cancel = threading.Event()
        self.cancel_reason = ""
        self._set_busy(True)
        self.started.emit(manual)
        self._emit_log("Back Up Now" if manual else "Scheduled backup started")
        eng = self._engine(self._cancel, manual)

        def done(res):
            d = res.to_dict()
            d.update(manual=manual, dry_run=False, cancel_reason=self.cancel_reason,
                     locked_files=res.locked_files[:50])
            self._set_busy(False)
            self.finished.emit(d)

        def failed(msg):
            self._set_busy(False)
            self._emit_log("Unexpected error: " + msg.splitlines()[0])
            log.error(msg)
            self.finished.emit({"status": "error", "error": msg.splitlines()[0], "stats": {},
                                "manual": manual, "dry_run": False, "messages": []})

        run_async(eng.run, done, failed)
        return True

    def start_preview(self, new_vault: bool = False) -> bool:
        if self._busy:
            return False
        self._cancel = threading.Event()
        self._set_busy(True)
        self._emit_log("Preview started (nothing will be changed)")
        eng = self._engine(self._cancel, False)
        fn = eng.preview_new_vault if new_vault else eng.preview

        def done(res):
            self._set_busy(False)
            self.previewReady.emit(res)

        def failed(msg):
            self._set_busy(False)
            self._emit_log("Preview failed: " + msg.splitlines()[0])
            self.previewReady.emit(None)

        run_async(fn, done, failed)
        return True

    def cancel(self, reason: str = ""):
        if self._cancel is not None:
            self.cancel_reason = reason
            self._cancel.set()

    # ------------------------------------------------------------------ catalog / restore

    def open_catalog(self):
        return catalog.open_catalog(self.ctrl.cfg, self.ctrl.cache_dir)

    def restore(self, copy_ids: list[int], folder_prefixes: list[tuple], t: float, dest_root: str | None,
                on_done, on_error, on_progress=None):
        """Restore copies (by id) and whole folders [(source_id, folder_key)] as of time t."""

        def work(progress=None):
            root = vault.locate_vault(self.ctrl.cfg.vault)
            if not root:
                raise RuntimeError("backup drive not connected")
            from ..core.index import Index
            idx = Index.open_vault(root)
            try:
                copies = [c for c in (idx.get_copy(i) for i in copy_ids) if c is not None]
                for sid, key in folder_prefixes:
                    copies += list(idx.copies_asof(t, sid, key))
                base = ""
                if dest_root and len(folder_prefixes) == 1 and not copy_ids:
                    k = folder_prefixes[0][1]
                    base = k.rsplit("/", 1)[0] if "/" in k else ""
                elif dest_root and copies:
                    parents = {c.parent_key for c in copies}
                    if len(parents) == 1:
                        base = parents.pop()
                names = {s.id: os.path.basename(s.path) or s.id for s in self.ctrl.cfg.sources}
                return restore_many(idx, root, copies, dest_root=dest_root, base_key=base, source_names=names,
                                    progress=progress)
            finally:
                idx.close()

        relay = _Relay()
        if on_progress:
            relay.progress.connect(on_progress)
        self._relays.add(relay)

        def done(r):
            self._relays.discard(relay)
            on_done(r)

        def err(m):
            self._relays.discard(relay)
            on_error(m)

        return run_async(lambda: work(relay.progress.emit), done, err)

    def delete_old_versions(self, days: float, on_done, on_error):
        cfg = self.ctrl.cfg
        return run_async(lambda: delete_old_versions(cfg, days, log=self._emit_log), on_done, on_error)
