"""One VaultMove per settings folder.

A named mutex decides who is first. The first instance listens on an
authenticated named pipe (stdlib multiprocessing.connection, no QtNetwork);
a second launch sends "show" and exits, raising the existing window.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
from multiprocessing.connection import Client, Listener

from PySide6.QtCore import QObject, Signal

from ..core import winapi


def _ident(cfg_dir: str) -> str:
    user = os.environ.get("USERNAME", "")
    return hashlib.sha1((user + "|" + os.path.normcase(cfg_dir)).encode()).hexdigest()[:16]


def _key(cfg_dir: str) -> bytes:
    os.makedirs(cfg_dir, exist_ok=True)
    p = os.path.join(cfg_dir, "ipc.key")
    try:
        with open(p, "rb") as f:
            k = f.read()
        if len(k) == 32:
            return k
    except OSError:
        pass
    k = secrets.token_bytes(32)
    with open(p, "wb") as f:
        f.write(k)
    return k


class SingleInstance(QObject):
    showRequested = Signal()

    def __init__(self, cfg_dir: str):
        super().__init__()
        self.cfg_dir = cfg_dir
        self.ident = _ident(cfg_dir)
        self.addr = "\\\\.\\pipe\\VaultMove-ipc-" + self.ident
        self._mutex = None
        self._listener = None

    def acquire(self) -> bool:
        """True if we are the first instance."""
        if not winapi.IS_WIN:
            return True
        h, existed = winapi.create_named_mutex("Local\\VaultMove-" + self.ident)
        self._mutex = h
        if existed:
            return False
        self._listener = Listener(self.addr, family="AF_PIPE", authkey=_key(self.cfg_dir))
        threading.Thread(target=self._serve, daemon=True, name="vaultmove-ipc").start()
        return True

    def _serve(self):
        while True:
            try:
                conn = self._listener.accept()
            except Exception:
                if self._listener is None:
                    return
                time.sleep(0.2)
                continue
            try:
                if conn.poll(2) and conn.recv_bytes(64) == b"show":
                    self.showRequested.emit()
            except Exception:
                pass
            finally:
                conn.close()

    def notify_first(self) -> bool:
        for _ in range(20):
            try:
                c = Client(self.addr, family="AF_PIPE", authkey=_key(self.cfg_dir))
                c.send_bytes(b"show")
                c.close()
                return True
            except Exception:
                time.sleep(0.25)
        return False
