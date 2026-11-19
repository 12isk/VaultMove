"""The unelevated side: owns the pipe, launches the helper through UAC, reads files."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
from multiprocessing.connection import Client, Listener

from ..core import winapi

ACCEPT_TIMEOUT = 120


def helper_command() -> tuple[str, list[str]]:
    """(executable, leading args) that start the helper in this installation."""
    if getattr(sys, "frozen", False):
        return sys.executable, ["--vss-helper"]
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__main__.py")
    return sys.executable, [script]


class VssSession:
    def __init__(self, conn, listener):
        self.conn = conn
        self.listener = listener
        self._lock = threading.Lock()

    @classmethod
    def start(cls, roots: list[str], elevate: bool = True, fake: bool = False,
              timeout: float = ACCEPT_TIMEOUT) -> "VssSession":
        key = secrets.token_bytes(32)
        name = "VaultMove-vss-" + secrets.token_hex(8)
        addr = "\\\\.\\pipe\\" + name
        listener = Listener(addr, family="AF_PIPE", authkey=key)
        got: dict = {}

        def accept():
            try:
                got["conn"] = listener.accept()
            except Exception as e:
                got["error"] = e

        th = threading.Thread(target=accept, daemon=True)
        th.start()
        exe, lead = helper_command()
        args = lead + ["--pipe", name, "--key", key.hex(),
                       "--roots", json.dumps(list(roots)).encode("utf-8").hex()]
        if fake:
            args.append("--fake-snapshot")
        if elevate:
            ok = winapi.shell_execute_runas(exe, subprocess.list2cmdline(args))
            if not ok:
                cls._unblock(addr, listener, th)
                raise PermissionError("administrator permission was not granted")
        else:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            subprocess.Popen([exe] + args, creationflags=flags)
        th.join(timeout)
        if "conn" not in got:
            cls._unblock(addr, listener, th)
            raise TimeoutError("the snapshot helper did not start")
        return cls(got["conn"], listener)

    @staticmethod
    def _unblock(addr, listener, th):
        if th.is_alive():
            try:
                Client(addr, family="AF_PIPE", authkey=b"x").close()
            except Exception:
                pass
            th.join(5)
        try:
            listener.close()
        except Exception:
            pass

    def _call(self, req: dict):
        with self._lock:
            self.conn.send_bytes(json.dumps(req).encode("utf-8"))
            raw = self.conn.recv_bytes()
        if raw[:1] == b"D":
            return raw[1:]
        out = json.loads(raw[1:].decode("utf-8"))
        if not out.get("ok"):
            raise OSError(out.get("error", "helper error"))
        return out

    def open(self, path: str):
        """Returns (size, mtime_ns, chunk iterator) for `path` as it is in the snapshot."""
        r = self._call({"op": "open", "path": path})
        h = r["h"]

        def chunks():
            try:
                while True:
                    b = self._call({"op": "read", "h": h, "n": 1 << 20})
                    if not b:
                        return
                    yield b
            finally:
                try:
                    self._call({"op": "close", "h": h})
                except Exception:
                    pass

        return r["size"], r["mtime_ns"], chunks()

    def close(self):
        try:
            with self._lock:
                self.conn.send_bytes(b'{"op": "quit"}')
        except Exception:
            pass
        try:
            self.conn.close()
        finally:
            try:
                self.listener.close()
            except Exception:
                pass


def session_factory(roots: list[str]) -> VssSession:
    if not winapi.IS_WIN:
        raise RuntimeError("open-file backup needs Windows")
    return VssSession.start(roots, elevate=True)
