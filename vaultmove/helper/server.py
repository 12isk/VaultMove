"""The elevated side. Started as: VaultMove.exe --vss-helper --pipe N --key HEX --roots HEXJSON"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from multiprocessing.connection import Client

from .shadow import FakeProvider, WmiShadowProvider

IDLE_TIMEOUT = 600
MAX_READ = 4 << 20
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
PATH_RX = re.compile(r"^[A-Za-z]:\\")


def _within(child: str, parent: str) -> bool:
    c = os.path.normcase(child).rstrip("\\")
    p = os.path.normcase(parent).rstrip("\\")
    return c == p or c.startswith(p + "\\")


def validate_path(path, roots: list[str]) -> str:
    """Return the path if the helper may serve it, else raise PermissionError."""
    if not isinstance(path, str) or "\x00" in path or len(path) > 32000:
        raise PermissionError("invalid path")
    if path.startswith("\\\\") or not PATH_RX.match(path):
        raise PermissionError("only local drive paths are allowed")
    if os.path.normpath(path) != path or "/" in path:
        raise PermissionError("path must be normalised (no '..', no '/')")
    if not any(_within(path, r) for r in roots):
        raise PermissionError("path is outside the backup folders")
    return path


def no_reparse_components(device: str, rel: str) -> None:
    """Inside the (read-only) snapshot, no component of the path may be a link."""
    parts = [p for p in rel.split("\\") if p]
    cur = device
    for part in parts:
        cur = cur + "\\" + part
        st = os.lstat(cur)
        if getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
            raise PermissionError("path goes through a link inside the snapshot")


class Helper:
    def __init__(self, roots: list[str], provider):
        self.roots = [os.path.normpath(r) for r in roots]
        self.provider = provider
        self.snaps: dict[str, tuple[str, str]] = {}
        self.files: dict[int, object] = {}
        self._next = 1

    def snapshot_for(self, volume: str) -> str:
        if volume not in self.snaps:
            self.snaps[volume] = self.provider.create(volume)
        return self.snaps[volume][1]

    def handle(self, req: dict):
        op = req.get("op")
        if op == "open":
            path = validate_path(req.get("path"), self.roots)
            volume = path[:3].upper()
            device = self.snapshot_for(volume)
            rel = path[3:]
            no_reparse_components(device, rel)
            full = device + "\\" + rel
            f = open(full, "rb")
            st = os.fstat(f.fileno())
            hid = self._next
            self._next += 1
            self.files[hid] = f
            return {"ok": True, "h": hid, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
        if op == "read":
            f = self.files[int(req["h"])]
            return f.read(max(1, min(int(req.get("n", 1 << 20)), MAX_READ)))
        if op == "close":
            f = self.files.pop(int(req["h"]), None)
            if f:
                f.close()
            return {"ok": True}
        raise PermissionError("unknown operation")

    def cleanup(self):
        for f in self.files.values():
            try:
                f.close()
            except OSError:
                pass
        self.files.clear()
        for sid, _dev in self.snaps.values():
            try:
                self.provider.delete(sid)
            except Exception:
                pass
        self.snaps.clear()


def serve(conn, helper: Helper):
    try:
        while conn.poll(IDLE_TIMEOUT):
            try:
                raw = conn.recv_bytes(65536)
            except (EOFError, OSError):
                break
            try:
                req = json.loads(raw.decode("utf-8"))
                if req.get("op") == "quit":
                    break
                out = helper.handle(req)
                if isinstance(out, bytes):
                    conn.send_bytes(b"D" + out)
                else:
                    conn.send_bytes(b"J" + json.dumps(out).encode("utf-8"))
            except Exception as e:
                conn.send_bytes(b"J" + json.dumps({"ok": False, "error": f"{e.__class__.__name__}: {e}"}).encode())
    finally:
        helper.cleanup()
        try:
            conn.close()
        except OSError:
            pass


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="vaultmove-vss-helper")
    p.add_argument("--vss-helper", action="store_true")
    p.add_argument("--pipe", required=True)
    p.add_argument("--key", required=True)
    p.add_argument("--roots", required=True)
    p.add_argument("--fake-snapshot", action="store_true")
    a = p.parse_args(argv if argv is not None else sys.argv[1:])
    if not re.fullmatch(r"VaultMove-vss-[0-9a-f]{16}", a.pipe):
        return 2
    roots = json.loads(bytes.fromhex(a.roots).decode("utf-8"))
    provider = FakeProvider() if a.fake_snapshot else WmiShadowProvider()
    conn = Client("\\\\.\\pipe\\" + a.pipe, family="AF_PIPE", authkey=bytes.fromhex(a.key))
    serve(conn, Helper(roots, provider))
    return 0
