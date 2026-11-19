"""Restore files from the vault, with hash verification and no silent overwrite."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import fsutil
from .copier import file_chunks, hash_file, place, write_verified_tmp
from .errors import Cancelled, VaultMoveError, VerifyFailed


@dataclass
class RestoreResult:
    restored: list = field(default_factory=list)     # (copy_id, target)
    skipped: list = field(default_factory=list)      # (copy_id, target, reason)
    failed: list = field(default_factory=list)       # (copy_id, target, reason)
    bytes: int = 0


def suffixed(target: str) -> str:
    """report.docx -> report.restored.docx -> report.restored-2.docx ..."""
    d, name = os.path.split(target)
    stem, ext = os.path.splitext(name)
    if not stem:
        stem, ext = name, ""
    i = 1
    while True:
        tag = ".restored" if i == 1 else f".restored-{i}"
        cand = os.path.join(d, stem + tag + ext)
        if not fsutil.exists(cand):
            return cand
        i += 1


def restore_copy(idx, vroot: str, c, target: str, *, on_conflict: str = "suffix", cancel=None,
                 on_bytes=None) -> tuple[str, str]:
    """Restore one copy to `target`. Returns (status, final_target).

    on_conflict: 'suffix' (keep both), 'skip'. Never overwrites an existing file.
    """
    src = fsutil.join(vroot, c.vault_rel)
    if not fsutil.isfile(src):
        raise VaultMoveError(f"vault copy missing: {c.vault_rel}")
    if fsutil.exists(target):
        try:
            if fsutil.isfile(target) and hash_file(target)[0] == c.sha256:
                return "identical", target
        except OSError:
            pass
        if on_conflict == "skip":
            return "exists", target
        target = suffixed(target)
    tmp, sha, n = write_verified_tmp(file_chunks(src), target, c.mtime_ns, cancel=cancel,
                                     on_bytes=on_bytes, expected_sha=c.sha256)
    if fsutil.exists(target):  # appeared meanwhile
        target = suffixed(target)
    place(tmp, target)
    # Verify the file actually in place, after the rename.
    vsha, vn = hash_file(target)
    if vsha != c.sha256 or vn != c.size:
        raise VerifyFailed(f"restored file does not match the backup: {target}")
    return "restored", target


def original_target(idx, c, sources: dict) -> str | None:
    root = sources.get(c.source_id)
    if not root:
        return None
    return fsutil.join(root, c.rel_path)


def restore_many(idx, vroot: str, copies, *, dest_root: str | None, base_key: str = "",
                 source_names: dict | None = None, on_conflict: str = "suffix", cancel=None,
                 progress=None, now: float = 0.0) -> RestoreResult:
    """Restore copies either to their original place (dest_root=None) or under dest_root.

    With dest_root, the folder structure below `base_key` is preserved; when
    restoring several sources, each goes under a sub-folder named after it.
    """
    res = RestoreResult()
    sources = idx.sources()
    copies = list(copies)
    multi = len({c.source_id for c in copies}) > 1
    for i, c in enumerate(copies):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if dest_root is None:
            target = original_target(idx, c, sources)
            if target is None:
                res.failed.append((c.id, None, "original folder unknown"))
                continue
        else:
            rel = c.rel_path.replace("\\", "/")
            if base_key and c.rel_key.startswith(base_key + "/"):
                rel = rel[len(base_key) + 1:]
            elif base_key and c.rel_key == base_key:
                rel = rel.rsplit("/", 1)[-1]
            if multi:
                label = (source_names or {}).get(c.source_id) or c.source_id
                rel = label + "/" + rel
            target = fsutil.join(fsutil.normroot(dest_root), rel)
        try:
            status, final = restore_copy(idx, vroot, c, target, on_conflict=on_conflict, cancel=cancel)
        except Cancelled:
            raise
        except (OSError, VaultMoveError) as e:
            res.failed.append((c.id, target, str(e)))
            continue
        if status == "restored":
            res.restored.append((c.id, final))
            res.bytes += c.size
            if dest_root is None and c.is_current and os.path.normcase(final) == os.path.normcase(target):
                # Back on the PC at its original place: don't offload it again right away.
                idx.set_keep_local(c.id, True)
            idx.add_event("restore", c.source_id, c.rel_path, {"to": final, "sha256": c.sha256,
                                                               "copy_id": c.id})
        else:
            res.skipped.append((c.id, final, status))
        if progress is not None:
            progress({"phase": "restore", "done": i + 1, "total": len(copies), "current": c.rel_path})
    try:
        idx.commit()
    except Exception:
        pass
    return res
