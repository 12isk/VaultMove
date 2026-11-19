"""Read-side helpers for browsing, searching and "where did my file go?".

Works against the live vault index when the drive is connected, or the local
cached copy (read-only, browse only) when it is not.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from . import fsutil, vault
from .index import Copy, Index

STATUS_LOCAL = "local"          # On this PC (and backed up)
STATUS_VAULT_ONLY = "vault"     # Backup drive only (offloaded or deleted from PC)
STATUS_OLDER = "older"          # An older version


@dataclass
class Listing:
    folders: list   # [(name, key)]
    files: list     # [(Copy, status)]


def cache_path(cache_dir: str, vault_uuid: str) -> str:
    return os.path.join(cache_dir, f"index-{vault_uuid}.sqlite")


def open_catalog(cfg, cache_dir: str) -> tuple[Optional[Index], Optional[str]]:
    """(index, vault_root). vault_root is None when browsing the local cache."""
    vroot = vault.locate_vault(cfg.vault)
    if vroot and os.path.exists(fsutil.join(vroot, vault.DB_NAME)):
        return Index.open_vault(vroot), vroot
    cp = cache_path(cache_dir, cfg.vault.uuid) if cfg.vault.uuid else ""
    if cp and os.path.exists(cp):
        return Index(cp, readonly=True), None
    return None, vroot


def status_of(c: Copy) -> str:
    if not c.is_current:
        return STATUS_OLDER
    if c.offloaded_at or c.gone_at:
        return STATUS_VAULT_ONLY
    return STATUS_LOCAL


def list_folder(idx: Index, source_id: str, folder_key: str, t: float) -> Listing:
    names = idx.subdirs_asof(source_id, folder_key, t)
    folders = []
    for n in names:
        key = (folder_key + "/" + n) if folder_key else n
        folders.append((idx.dir_display_name(source_id, key), key))
    files = []
    for c in idx.list_dir_asof(source_id, folder_key, t):
        files.append((c, status_of(c)))
    return Listing(folders, files)


def history(idx: Index, source_id: str, rel_path: str) -> dict:
    """Everything known about one file: versions and the append-only event trail."""
    copies = idx.copies_of(source_id, rel_path, include_pruned=True)
    events = []
    for ts, kind, detail in idx.events_for(source_id, rel_path):
        events.append({"ts": ts, "kind": kind, "detail": json.loads(detail) if detail else {}})
    return {"copies": copies, "events": events}


def where_is(idx: Index, source_id: str, rel_path: str) -> str:
    """One human sentence answering 'where did my file go?'."""
    cur = idx.current_copy(source_id, rel_path)
    if cur is None:
        return "VaultMove has no copy of this file."
    if cur.offloaded_at:
        return (f"Removed from this PC to free space; the verified copy is on the backup drive at "
                f"{cur.vault_rel}.")
    if cur.gone_at:
        return f"Deleted from this PC; the last copy is on the backup drive at {cur.vault_rel}."
    return f"On this PC, backed up at {cur.vault_rel}."
