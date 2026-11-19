"""Rebuild the index by scanning the vault (if index.sqlite is lost or corrupt).

The vault is plain files, so the index can be reconstructed:
  data/<sid>/<rel>                 -> current copies
  _versions/<ts>[-n]/<sid>/<rel>   -> older versions (valid until <ts>)
  log/*.jsonl                      -> replayed for offload state
"""

from __future__ import annotations

import json
import os
import time

from . import fsutil
from .copier import hash_file
from .errors import Cancelled
from .index import Index, JsonlLog
from .vault import DATA_DIR, DB_NAME, LOG_DIR, VERSIONS_DIR, read_sources_json


def _walk_files(root: str):
    stack = [""]
    while stack:
        rel_dir = stack.pop()
        try:
            it = os.scandir(fsutil.lp(fsutil.join(root, rel_dir)))
        except OSError:
            continue
        with it:
            for e in it:
                rel = (rel_dir + os.sep + e.name) if rel_dir else e.name
                if e.is_dir(follow_symlinks=False):
                    stack.append(rel)
                elif e.is_file(follow_symlinks=False):
                    yield rel, e.stat(follow_symlinks=False)


def _parse_ts(name: str) -> float | None:
    base = name.split("-")[0:3]
    try:
        stamp = "-".join(base)
        return time.mktime(time.strptime(stamp, "%Y-%m-%d_%H%M%S"))
    except ValueError:
        return None


def rebuild_index(vroot: str, progress=None, cancel=None, log=print) -> dict:
    db = fsutil.join(vroot, DB_NAME)
    if os.path.exists(db):
        os.replace(db, db + f".broken-{int(time.time())}")
    for suffix in ("-journal", "-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.replace(db + suffix, db + suffix + f".broken-{int(time.time())}")
    idx = Index(db, JsonlLog(vroot))
    stats = {"current": 0, "versions": 0, "tmp_removed": 0, "offloaded": 0}
    now = time.time()
    try:
        for sid, info in read_sources_json(vroot).items():
            idx.upsert_source(sid, info.get("path", ""))
        idx.commit()
        sources = idx.sources()

        data_root = fsutil.join(vroot, DATA_DIR)
        try:
            sids = [e.name for e in os.scandir(fsutil.lp(data_root)) if e.is_dir()]
        except OSError:
            sids = []
        for sid in sids:
            if sid not in sources:
                idx.upsert_source(sid, "")
            for rel, st in _walk_files(fsutil.join(data_root, sid)):
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                full = fsutil.join(fsutil.join(data_root, sid), rel)
                if rel.lower().endswith(fsutil.TMP_SUFFIX):
                    fsutil.remove_quiet(full)
                    stats["tmp_removed"] += 1
                    continue
                sha, n = hash_file(full)
                idx.insert_copy(sid, rel, n, st.st_mtime_ns, sha, DATA_DIR + os.sep + sid + os.sep + rel,
                                valid_from=st.st_mtime_ns / 1e9)
                stats["current"] += 1
                if progress and stats["current"] % 200 == 0:
                    progress({"phase": "rebuild", "done": stats["current"], "current": rel})
                    idx.commit()
        idx.commit()

        vers_root = fsutil.join(vroot, VERSIONS_DIR)
        try:
            tsdirs = sorted(e.name for e in os.scandir(fsutil.lp(vers_root)) if e.is_dir())
        except OSError:
            tsdirs = []
        for tsd in tsdirs:
            t = _parse_ts(tsd) or now
            for sid_entry in os.scandir(fsutil.lp(fsutil.join(vers_root, tsd))):
                if not sid_entry.is_dir():
                    continue
                sid = sid_entry.name
                if sid not in idx.sources():
                    idx.upsert_source(sid, "")
                base = fsutil.join(fsutil.join(vers_root, tsd), sid)
                for rel, st in _walk_files(base):
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    full = fsutil.join(base, rel)
                    if rel.lower().endswith(fsutil.TMP_SUFFIX):
                        fsutil.remove_quiet(full)
                        stats["tmp_removed"] += 1
                        continue
                    sha, n = hash_file(full)
                    vf = min(st.st_mtime_ns / 1e9, t)
                    idx.insert_copy(sid, rel, n, st.st_mtime_ns, sha,
                                    VERSIONS_DIR + os.sep + tsd + os.sep + sid + os.sep + rel,
                                    valid_from=vf, is_current=False, valid_to=t)
                    stats["versions"] += 1
            idx.commit()

        # Replay offload events from the append-only log.
        log_dir = fsutil.join(vroot, LOG_DIR)
        try:
            names = sorted(n for n in os.listdir(fsutil.lp(log_dir)) if n.endswith(".jsonl"))
        except OSError:
            names = []
        offloaded = {}
        for name in names:
            with open(fsutil.lp(fsutil.join(log_dir, name)), "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("kind") == "offload" and rec.get("path"):
                        offloaded[(rec.get("source"), fsutil.rel_key(rec["path"]))] = rec
        for (sid, key), rec in offloaded.items():
            c = idx.db.execute("SELECT id, sha256, rel_path FROM copies WHERE source_id=? AND rel_key=? "
                               "AND is_current=1", (sid, key)).fetchone()
            if not c:
                continue
            sha = (rec.get("detail") or {}).get("sha256")
            root = idx.sources().get(sid, "")
            if sha == c[1] and root and not fsutil.exists(fsutil.join(root, c[2])):
                idx.set_offloaded(c[0], rec.get("ts", now))
                stats["offloaded"] += 1
        idx.add_event("index_rebuilt", detail=stats)
        idx.commit()
    finally:
        idx.close()
    log(f"Index rebuilt: {stats}")
    return stats
