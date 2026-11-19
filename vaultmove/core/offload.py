"""Offload: delete originals that are safely in the vault (invariants 1, 6, 8).

An original is deleted only if ALL of these hold at the moment of deletion:
  (a) the index has a committed current copy, made in an earlier run;
  (b) that vault copy, re-hashed now, equals the recorded hash and size;
  (c) the source, re-hashed now through a handle that denies writers, equals it too;
  (d) the source size and mtime equal the recorded ones before, during and after hashing;
  (e) the source mtime is older than offload_after_days (and not in the future).
Plus: not a link or cloud placeholder, not protected, not excluded, vault not on the
same physical disk, offload armed (enabled + confirmed + previewed).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from . import crashpoints, fsutil, winapi
from .copier import hash_file


@dataclass
class OffloadDecision:
    ok: bool
    reason: str = ""


def check_source_state(abs_src: str, c, days: int, now: float) -> OffloadDecision:
    try:
        st = os.lstat(fsutil.lp(abs_src))
    except FileNotFoundError:
        return OffloadDecision(False, "original no longer exists")
    except OSError as e:
        return OffloadDecision(False, f"cannot read original: {e}")
    if fsutil.is_link_like(st):
        return OffloadDecision(False, "is a link")
    if fsutil.is_cloud_placeholder(st) or fsutil.in_cloud_sync(abs_src):
        return OffloadDecision(False, "cloud-synced file (deleting would delete it in the cloud)")
    if fsutil.attrs_of(st) & (fsutil.FILE_ATTRIBUTE_READONLY | fsutil.FILE_ATTRIBUTE_SYSTEM):
        return OffloadDecision(False, "read-only or system file")
    if (st.st_size, st.st_mtime_ns) != (c.size, c.mtime_ns):
        return OffloadDecision(False, "changed since it was backed up")
    mtime = st.st_mtime_ns / 1e9
    if mtime > now:
        return OffloadDecision(False, "modification time is in the future (clock change?)")
    if now - mtime < days * 86400:
        return OffloadDecision(False, "not old enough")
    return OffloadDecision(True)


def verify_vault_copy(vroot: str, c) -> OffloadDecision:
    vfile = fsutil.join(vroot, c.vault_rel)
    if not fsutil.isfile(vfile):
        return OffloadDecision(False, "vault copy missing")
    try:
        sha, n = hash_file(vfile)
    except OSError as e:
        return OffloadDecision(False, f"cannot read vault copy: {e}")
    if sha != c.sha256 or n != c.size:
        return OffloadDecision(False, "vault copy does not match its recorded hash")
    return OffloadDecision(True)


def offload_one(idx, vroot: str, src_cfg, c, *, days: int, now: float, recycle: bool,
                log, cancel=None) -> OffloadDecision:
    abs_src = fsutil.join(src_cfg.path, c.rel_path)

    d = check_source_state(abs_src, c, days, now)
    if not d.ok:
        return d
    if fsutil.is_protected(abs_src):
        return OffloadDecision(False, "protected location")
    if recycle and len(abs_src) > winapi.RECYCLE_MAX_PATH:
        return OffloadDecision(False, "path too long for the Recycle Bin")

    v = verify_vault_copy(vroot, c)  # (a) + (b)
    if not v.ok:
        if "match" in v.reason or "missing" in v.reason:
            idx.set_bad(c.id, now)
            idx.add_event("vault_copy_bad", c.source_id, c.rel_path, {"reason": v.reason})
            idx.commit()
            log(f"WARNING: {v.reason} for {c.rel_path}; it will be copied again.")
        return v

    try:
        h = winapi.LockedHandle(fsutil.lp(abs_src), want_delete=not recycle)
    except OSError as e:
        return OffloadDecision(False, f"in use or not accessible ({e.__class__.__name__})")
    pid = None
    try:
        s1 = h.stat()                                           # (d) before
        if s1 != (c.size, c.mtime_ns):
            return OffloadDecision(False, "changed since it was backed up")
        hh = hashlib.sha256()
        n = 0
        for chunk in h.chunks():                                # (c)
            hh.update(chunk)
            n += len(chunk)
            if cancel is not None and cancel.is_set():
                return OffloadDecision(False, "cancelled")
        if hh.hexdigest() != c.sha256 or n != c.size:
            return OffloadDecision(False, "content differs from the backup")
        if h.stat() != s1:                                      # (d) after
            return OffloadDecision(False, "changed while verifying")
        method = "recycle" if recycle else "delete"
        pid = idx.add_pending("offload", {"copy_id": c.id, "abs_src": abs_src, "method": method,
                                          "source_id": c.source_id, "rel": c.rel_path,
                                          "vault_rel": c.vault_rel, "sha": c.sha256})
        idx.commit()
        crashpoints.crash("before_delete")
        if not recycle:
            h.delete_on_close()
    except OSError as e:
        if pid is not None:
            idx.remove_pending(pid)
            idx.commit()
        return OffloadDecision(False, f"could not delete: {e}")
    finally:
        h.close()

    if recycle:
        try:
            st = os.lstat(fsutil.lp(abs_src))
            if (st.st_size, st.st_mtime_ns) != (c.size, c.mtime_ns):
                idx.remove_pending(pid)
                idx.commit()
                return OffloadDecision(False, "changed while verifying")
            winapi.send_to_recycle_bin(abs_src)
        except OSError as e:
            idx.remove_pending(pid)
            idx.commit()
            return OffloadDecision(False, f"could not move to Recycle Bin: {e}")
    crashpoints.crash("after_delete")

    if fsutil.exists(abs_src):
        idx.remove_pending(pid)
        idx.commit()
        return OffloadDecision(False, "original still present after delete")
    idx.set_offloaded(c.id, now)
    idx.add_event("offload", c.source_id, c.rel_path,
                  {"method": method, "vault": c.vault_rel, "sha256": c.sha256, "size": c.size,
                   "original": abs_src})
    idx.remove_pending(pid)
    idx.commit()
    return OffloadDecision(True, method)
