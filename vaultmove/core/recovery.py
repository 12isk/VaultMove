"""Crash recovery for journalled multi-step operations.

Before any step that moves an existing vault copy or deletes an original, the
engine commits a row in `pending` describing the whole operation. If the
process dies part-way, the next run inspects the filesystem and either rolls
the operation forward (finish it) or back (undo it). In no state is data lost:
the old copy is always either in data/ or in _versions/, and an original is
only deleted after its verified copy is committed in the index.
"""

from __future__ import annotations

import os

from . import fsutil
from .copier import hash_file


def apply_store(idx, p: dict, version_present: bool) -> int:
    """Index update for a completed store operation (one transaction with the caller's commit)."""
    if p.get("old_copy_id"):
        idx.retire_copy(p["old_copy_id"], p["version_rel"] if version_present else None, p["ts"])
        idx.add_event("version", p["source_id"], p["rel"],
                      {"from": p["old_vault_rel"], "to": p["version_rel"] if version_present else None},
                      ts=p["ts"])
    cid = idx.insert_copy(p["source_id"], p["rel"], p["size"], p["mtime_ns"], p["sha"], p["data_rel"], p["ts"])
    idx.add_event("copy", p["source_id"], p["rel"], {"sha256": p["sha"], "size": p["size"],
                                                     "vault": p["data_rel"]}, ts=p["ts"])
    return cid


def _sha_matches(path: str, sha: str) -> bool:
    try:
        return fsutil.isfile(path) and hash_file(path)[0] == sha
    except OSError:
        return False


def recover_store(idx, vroot: str, pid: int, p: dict, log) -> str:
    tmp = fsutil.join(vroot, p["tmp_rel"])
    final = fsutil.join(vroot, p["data_rel"])
    ver = fsutil.join(vroot, p["version_rel"])
    old = fsutil.join(vroot, p["old_vault_rel"])
    ver_exists = fsutil.isfile(ver)
    final_exists = fsutil.isfile(final)

    if final_exists and (ver_exists or not p.get("old_existed", True)) and _sha_matches(final, p["sha"]):
        fsutil.remove_quiet(tmp)
        apply_store(idx, p, ver_exists)
        idx.remove_pending(pid)
        idx.add_event("recovered", p["source_id"], p["rel"], {"op": "store", "action": "roll_forward"})
        idx.commit()
        log(f"Recovered interrupted copy of {p['rel']} (completed).")
        return "forward"

    if ver_exists and not final_exists:
        if _sha_matches(tmp, p["sha"]):
            os.replace(fsutil.lp(tmp), fsutil.lp(final))
            apply_store(idx, p, True)
            idx.remove_pending(pid)
            idx.add_event("recovered", p["source_id"], p["rel"], {"op": "store", "action": "roll_forward"})
            idx.commit()
            log(f"Recovered interrupted copy of {p['rel']} (completed).")
            return "forward"
        # New copy unusable: put the old copy back where the index expects it.
        if not fsutil.exists(old):
            fsutil.makedirs(os.path.dirname(old))
            os.replace(fsutil.lp(ver), fsutil.lp(old))
        fsutil.remove_quiet(tmp)
        idx.remove_pending(pid)
        idx.add_event("recovered", p["source_id"], p["rel"], {"op": "store", "action": "roll_back"})
        idx.commit()
        log(f"Recovered interrupted copy of {p['rel']} (undone, will copy again).")
        return "back"

    fsutil.remove_quiet(tmp)
    idx.remove_pending(pid)
    idx.add_event("recovered", p["source_id"], p["rel"], {"op": "store", "action": "discard"})
    idx.commit()
    return "back"


def recover_offload(idx, pid: int, p: dict, log, now: float) -> str:
    src = p["abs_src"]
    if not fsutil.exists(src):
        c = idx.get_copy(p["copy_id"])
        if c is not None and c.offloaded_at is None:
            idx.set_offloaded(c.id, now)
        idx.add_event("offload", p["source_id"], p["rel"],
                      {"method": p["method"], "vault": p["vault_rel"], "sha256": p["sha"], "recovered": True})
        idx.remove_pending(pid)
        idx.commit()
        log(f"Recovered interrupted offload of {p['rel']} (original was already removed; copy is in the vault).")
        return "forward"
    idx.remove_pending(pid)
    idx.add_event("recovered", p["source_id"], p["rel"], {"op": "offload", "action": "kept_original"})
    idx.commit()
    return "back"


def recover(idx, vroot: str, log, now: float) -> int:
    n = 0
    for pid, kind, payload in idx.list_pending():
        if kind == "store":
            recover_store(idx, vroot, pid, payload, log)
        elif kind == "offload":
            recover_offload(idx, pid, payload, log, now)
        else:
            idx.remove_pending(pid)
            idx.commit()
        n += 1
    return n
