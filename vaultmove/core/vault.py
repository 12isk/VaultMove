"""Vault identity, layout, location and locking (invariants 4 and 5).

Layout of a vault folder (plain files, readable without VaultMove):

    <vault>/.vaultmove-vault.json     marker with the vault UUID
    <vault>/index.sqlite              index (cached locally after each run)
    <vault>/sources.json              source id -> original folder (for rebuilds)
    <vault>/log/YYYY-MM.jsonl         append-only event log
    <vault>/data/<source-id>/...      latest copy of every file
    <vault>/_versions/<run-ts>/<source-id>/...   older copies
"""

from __future__ import annotations

import json
import os
import string
import time
import uuid as uuidlib

from . import fsutil, winapi
from .errors import OverlapRefused, SameDriveRefused, VaultBusy, VaultInvalid, VaultNotConnected

MARKER = ".vaultmove-vault.json"
DATA_DIR = "data"
VERSIONS_DIR = "_versions"
LOG_DIR = "log"
DB_NAME = "index.sqlite"
LOCK_NAME = ".vaultmove.lock"
SOURCES_JSON = "sources.json"
FORMAT = 1

VAULT_ENTRIES = {MARKER.lower(), DATA_DIR, VERSIONS_DIR.lower(), LOG_DIR, DB_NAME, LOCK_NAME,
                 SOURCES_JSON, DB_NAME + "-journal", DB_NAME + "-wal", DB_NAME + "-shm"}


def read_marker(root: str) -> dict | None:
    p = fsutil.join(root, MARKER)
    try:
        with open(fsutil.lp(p), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("uuid"):
            return data
    except (OSError, ValueError):
        pass
    return None


def inspect_destination(root: str) -> str:
    """'missing' | 'parent_missing' | 'new' | 'vault' | 'not_empty'."""
    root = fsutil.normroot(root)
    if read_marker(root):
        return "vault"
    if not os.path.exists(fsutil.lp(root)):
        parent = os.path.dirname(root)
        return "new" if os.path.isdir(fsutil.lp(parent)) else "parent_missing"
    if not os.path.isdir(fsutil.lp(root)):
        return "not_empty"
    try:
        with os.scandir(fsutil.lp(root)) as it:
            for _ in it:
                return "not_empty"
    except OSError:
        return "missing"
    return "new"


def create_vault(root: str) -> str:
    """Create (or adopt) a vault at `root`. Returns its UUID.

    Refuses a non-empty folder that has no marker: we never mix backup data
    into an unrelated folder.
    """
    root = fsutil.normroot(root)
    state = inspect_destination(root)
    if state == "vault":
        return read_marker(root)["uuid"]
    if state == "not_empty":
        raise VaultInvalid(f"{root} is not empty and is not a VaultMove vault")
    if state in ("missing", "parent_missing"):
        raise VaultNotConnected(f"{root} is not reachable")
    fsutil.makedirs(root)
    vid = str(uuidlib.uuid4())
    marker = {"app": "VaultMove", "format": FORMAT, "uuid": vid, "created_at": time.time()}
    tmp = fsutil.join(root, MARKER + fsutil.TMP_SUFFIX)
    with open(fsutil.lp(tmp), "w", encoding="utf-8") as f:
        json.dump(marker, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(fsutil.lp(tmp), fsutil.lp(fsutil.join(root, MARKER)))
    for d in (DATA_DIR, VERSIONS_DIR, LOG_DIR):
        fsutil.makedirs(fsutil.join(root, d))
    return vid


def vault_cfg_for(root: str, vid: str, allow_same_drive: bool = False):
    """Build a VaultCfg describing where the vault lives, by volume identity."""
    from .config import VaultCfg
    root = fsutil.normroot(root)
    mp = winapi.volume_mount_point(root)
    rel = ""
    if mp and fsutil.is_within(root, mp):
        rel = root[len(mp.rstrip("\\")):].lstrip("\\")
    info = winapi.volume_info(root)
    return VaultCfg(uuid=vid, path=root, rel_path=rel, volume_guid=winapi.volume_guid(root) or "",
                    volume_serial=info.get("serial"), label=info.get("label") or "",
                    allow_same_drive=allow_same_drive)


def _candidates(vcfg) -> list[str]:
    cands = []
    if winapi.IS_WIN and vcfg.volume_guid:
        mask = winapi.logical_drives_mask()
        for i, letter in enumerate(string.ascii_uppercase):
            if mask & (1 << i):
                root = f"{letter}:\\"
                g = winapi.volume_guid(root)
                if g and g.lower() == vcfg.volume_guid.lower():
                    cands.append(fsutil.join(f"{letter}:", vcfg.rel_path) if vcfg.rel_path else root)
        # Drive letter changed and GUID differs (e.g. some USB enclosures): fall back to a
        # letter scan, but only accept a marker with the right UUID *and* serial.
        if not cands and vcfg.volume_serial is not None:
            for i, letter in enumerate(string.ascii_uppercase):
                if mask & (1 << i):
                    root = f"{letter}:\\"
                    if winapi.drive_type(root) not in (winapi.DRIVE_FIXED, winapi.DRIVE_REMOVABLE):
                        continue
                    info = winapi.volume_info(root)
                    if info.get("serial") == vcfg.volume_serial:
                        cands.append(fsutil.join(f"{letter}:", vcfg.rel_path) if vcfg.rel_path else root)
    elif vcfg.path:
        cands.append(vcfg.path)
    return cands


def locate_vault(vcfg) -> str | None:
    """Find the connected vault by volume identity + marker UUID; None if absent.

    Never falls back to "the folder path on C:" - if the drive is not there,
    the answer is None and nothing is written.
    """
    if not vcfg or not vcfg.uuid:
        return None
    for c in _candidates(vcfg):
        m = read_marker(c)
        if m and m.get("uuid") == vcfg.uuid:
            return fsutil.normroot(c)
    return None


def require_vault(vcfg) -> str:
    root = locate_vault(vcfg)
    if not root:
        raise VaultNotConnected("backup drive not connected")
    return root


def check_sources(vault_root: str, sources, allow_same_drive: bool, same_fn=None) -> list[str]:
    """Validate vault/source relationships. Returns warnings; raises on refusal."""
    same_fn = same_fn or winapi.same_physical_disk
    warnings = []
    for s in sources:
        if fsutil.is_within(vault_root, s.path):
            raise OverlapRefused(f"the backup folder is inside the source {s.path}")
        if fsutil.is_within(s.path, vault_root):
            raise OverlapRefused(f"the source {s.path} is inside the backup folder")
        if not os.path.isdir(fsutil.lp(s.path)):
            continue  # unplugged source drive: skipped later, not an error
        same = same_fn(vault_root, s.path)
        if same and not allow_same_drive:
            raise SameDriveRefused(
                f"the backup drive is the same physical disk as {s.path}; a disk failure would lose both")
        if same:
            warnings.append(f"same physical disk as {s.path} (override active)")
        elif same is None:
            warnings.append(f"could not determine whether {s.path} is on the backup disk")
    return warnings


class VaultLock:
    """Exclusive, crash-safe lock on the vault (released by the OS on process death)."""

    def __init__(self, root: str):
        self.path = fsutil.join(root, LOCK_NAME)
        self.fd = None

    def acquire(self):
        fd = os.open(fsutil.lp(self.path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, 0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise VaultBusy("another VaultMove process is using this backup drive")
        self.fd = fd
        return self

    def release(self):
        if self.fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt
                os.lseek(self.fd, 0, 0)
                try:
                    msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
        finally:
            os.close(self.fd)
            self.fd = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


def write_sources_json(root: str, sources) -> None:
    from .config import atomic_write_text
    data = {s.id: {"path": s.path} for s in sources}
    p = fsutil.join(root, SOURCES_JSON)
    try:
        old = {}
        with open(fsutil.lp(p), "r", encoding="utf-8") as f:
            old = json.load(f)
        old.update(data)  # keep removed sources: their copies are still in the vault
        data = old
    except (OSError, ValueError):
        pass
    atomic_write_text(p, json.dumps(data, indent=2, ensure_ascii=False))


def read_sources_json(root: str) -> dict:
    try:
        with open(fsutil.lp(fsutil.join(root, SOURCES_JSON)), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}
