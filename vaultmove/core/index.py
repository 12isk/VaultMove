"""SQLite index stored on the vault, plus the append-only JSONL log.

Every stored blob (current copy or older version) is one row of `copies`.
The row with is_current=1 for a (source, path) is the latest copy and is never
pruned. `events` is append-only (enforced by triggers). `pending` is the
write-ahead journal for multi-step filesystem operations (see recovery.py).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Iterable, Optional

from . import fsutil
from .vault import DB_NAME, LOG_DIR

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, path TEXT NOT NULL, added_at REAL);
CREATE TABLE IF NOT EXISTS copies(
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    rel_key TEXT NOT NULL,
    parent_key TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    vault_rel TEXT NOT NULL,
    valid_from REAL NOT NULL,
    valid_to REAL,
    gone_at REAL,
    offloaded_at REAL,
    keep_local INTEGER NOT NULL DEFAULT 0,
    bad_at REAL,
    is_current INTEGER NOT NULL DEFAULT 1,
    pruned_at REAL,
    run_id INTEGER
);
CREATE INDEX IF NOT EXISTS copies_key ON copies(source_id, rel_key);
CREATE INDEX IF NOT EXISTS copies_parent ON copies(source_id, parent_key);
CREATE UNIQUE INDEX IF NOT EXISTS copies_one_current ON copies(source_id, rel_key) WHERE is_current = 1;
CREATE TABLE IF NOT EXISTS pending(id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL,
                                   created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, ts REAL NOT NULL, run_id INTEGER,
                                  kind TEXT NOT NULL, source_id TEXT, rel_key TEXT, rel_path TEXT,
                                  detail TEXT);
CREATE INDEX IF NOT EXISTS events_key ON events(source_id, rel_key);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, started_at REAL NOT NULL, finished_at REAL,
                                status TEXT, stats TEXT);
CREATE TRIGGER IF NOT EXISTS events_append_only_u BEFORE UPDATE ON events
    BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS events_append_only_d BEFORE DELETE ON events
    BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;
"""

COPY_COLS = ("id, source_id, rel_path, rel_key, parent_key, size, mtime_ns, sha256, vault_rel, "
             "valid_from, valid_to, gone_at, offloaded_at, keep_local, bad_at, is_current, pruned_at, run_id")


@dataclass
class Copy:
    id: int
    source_id: str
    rel_path: str
    rel_key: str
    parent_key: str
    size: int
    mtime_ns: int
    sha256: str
    vault_rel: str
    valid_from: float
    valid_to: Optional[float]
    gone_at: Optional[float]
    offloaded_at: Optional[float]
    keep_local: int
    bad_at: Optional[float]
    is_current: int
    pruned_at: Optional[float]
    run_id: Optional[int]


def _copy(row) -> Copy:
    return Copy(*row)


class JsonlLog:
    """Append-only human-readable log on the vault (one JSON object per line)."""

    def __init__(self, vault_root: str):
        self.dir = fsutil.join(vault_root, LOG_DIR)
        self._buf: list[str] = []

    def add(self, rec: dict) -> None:
        self._buf.append(json.dumps(rec, ensure_ascii=False))

    def flush(self) -> None:
        if not self._buf:
            return
        fsutil.makedirs(self.dir)
        name = time.strftime("%Y-%m", time.localtime()) + ".jsonl"
        p = fsutil.join(self.dir, name)
        with open(fsutil.lp(p), "a", encoding="utf-8") as f:
            f.write("\n".join(self._buf) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._buf.clear()

    def discard(self) -> None:
        self._buf.clear()


class Index:
    def __init__(self, db_path: str, log: JsonlLog | None = None, readonly: bool = False):
        self.path = db_path
        self.log = log
        self.readonly = readonly
        self._lock = threading.RLock()
        if readonly:
            uri = "file:" + db_path.replace("\\", "/") + "?mode=ro"
            self.db = sqlite3.connect(uri, uri=True, timeout=30, isolation_level=None,
                                      check_same_thread=False)
        else:
            self.db = sqlite3.connect(db_path, timeout=30, isolation_level=None, check_same_thread=False)
            self.db.execute("PRAGMA journal_mode=TRUNCATE")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript(SCHEMA)
            cur = self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
            if not cur:
                self.db.execute("INSERT INTO meta(key, value) VALUES('schema', ?)", (str(SCHEMA_VERSION),))
        self._in_tx = False
        self._events_pending: list[dict] = []
        self.run_id: Optional[int] = None

    @classmethod
    def open_vault(cls, vault_root: str) -> "Index":
        return cls(fsutil.join(vault_root, DB_NAME), JsonlLog(vault_root))

    def close(self):
        try:
            if self._in_tx:
                self.rollback()
        finally:
            self.db.close()

    # ------------------------------------------------------------------ transactions

    def begin(self):
        with self._lock:
            if not self._in_tx:
                self.db.execute("BEGIN IMMEDIATE")
                self._in_tx = True

    def commit(self):
        with self._lock:
            if self._in_tx:
                self.db.execute("COMMIT")
                self._in_tx = False
            if self.log is not None and self._events_pending:
                for e in self._events_pending:
                    self.log.add(e)
                self._events_pending.clear()
                try:
                    self.log.flush()
                except OSError:
                    pass  # the DB events table is authoritative

    def rollback(self):
        with self._lock:
            if self._in_tx:
                self.db.execute("ROLLBACK")
                self._in_tx = False
            self._events_pending.clear()

    @property
    def in_tx(self) -> bool:
        return self._in_tx

    # ------------------------------------------------------------------ sources / runs

    def upsert_source(self, sid: str, path: str):
        self.begin()
        self.db.execute("INSERT INTO sources(id, path, added_at) VALUES(?,?,?) "
                        "ON CONFLICT(id) DO UPDATE SET path=excluded.path", (sid, path, time.time()))

    def sources(self) -> dict:
        return {r[0]: r[1] for r in self.db.execute("SELECT id, path FROM sources")}

    def start_run(self, ts: float) -> int:
        self.begin()
        cur = self.db.execute("INSERT INTO runs(started_at, status) VALUES(?, 'running')", (ts,))
        self.run_id = cur.lastrowid
        self.commit()
        return self.run_id

    def finish_run(self, run_id: int, ts: float, status: str, stats: dict):
        self.begin()
        self.db.execute("UPDATE runs SET finished_at=?, status=?, stats=? WHERE id=?",
                        (ts, status, json.dumps(stats), run_id))
        self.commit()

    def runs(self, limit: int = 5000) -> list[tuple]:
        return self.db.execute("SELECT id, started_at, finished_at, status, stats FROM runs "
                               "ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()

    def snapshot_times(self) -> list[float]:
        """Distinct points in time the timeline can show (finished runs, newest first)."""
        rows = self.db.execute("SELECT finished_at FROM runs WHERE finished_at IS NOT NULL "
                               "AND status IN ('ok','partial') ORDER BY finished_at DESC").fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------ events

    def add_event(self, kind: str, source_id: str | None = None, rel_path: str | None = None,
                  detail: dict | None = None, ts: float | None = None):
        ts = time.time() if ts is None else ts
        self.begin()
        key = fsutil.rel_key(rel_path) if rel_path else None
        self.db.execute("INSERT INTO events(ts, run_id, kind, source_id, rel_key, rel_path, detail) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (ts, self.run_id, kind, source_id, key, rel_path,
                         json.dumps(detail, ensure_ascii=False) if detail else None))
        self._events_pending.append({"ts": ts, "run": self.run_id, "kind": kind, "source": source_id,
                                     "path": rel_path, **({"detail": detail} if detail else {})})

    def events_for(self, source_id: str, rel_path: str) -> list[tuple]:
        return self.db.execute("SELECT ts, kind, detail FROM events WHERE source_id=? AND rel_key=? "
                               "ORDER BY id", (source_id, fsutil.rel_key(rel_path))).fetchall()

    # ------------------------------------------------------------------ pending journal

    def add_pending(self, kind: str, payload: dict) -> int:
        self.begin()
        cur = self.db.execute("INSERT INTO pending(kind, payload, created_at) VALUES(?,?,?)",
                              (kind, json.dumps(payload, ensure_ascii=False), time.time()))
        return cur.lastrowid

    def remove_pending(self, pid: int):
        self.begin()
        self.db.execute("DELETE FROM pending WHERE id=?", (pid,))

    def list_pending(self) -> list[tuple[int, str, dict]]:
        return [(r[0], r[1], json.loads(r[2]))
                for r in self.db.execute("SELECT id, kind, payload FROM pending ORDER BY id")]

    # ------------------------------------------------------------------ copies

    def current_map(self, source_id: str) -> dict:
        rows = self.db.execute(f"SELECT {COPY_COLS} FROM copies WHERE source_id=? AND is_current=1",
                               (source_id,))
        return {r[3]: _copy(r) for r in rows}

    def get_copy(self, cid: int) -> Copy | None:
        r = self.db.execute(f"SELECT {COPY_COLS} FROM copies WHERE id=?", (cid,)).fetchone()
        return _copy(r) if r else None

    def current_copy(self, source_id: str, rel_path: str) -> Copy | None:
        r = self.db.execute(f"SELECT {COPY_COLS} FROM copies WHERE source_id=? AND rel_key=? AND is_current=1",
                            (source_id, fsutil.rel_key(rel_path))).fetchone()
        return _copy(r) if r else None

    def copies_of(self, source_id: str, rel_path: str, include_pruned: bool = False) -> list[Copy]:
        q = f"SELECT {COPY_COLS} FROM copies WHERE source_id=? AND rel_key=?"
        if not include_pruned:
            q += " AND pruned_at IS NULL"
        q += " ORDER BY valid_from DESC, id DESC"
        return [_copy(r) for r in self.db.execute(q, (source_id, fsutil.rel_key(rel_path)))]

    def insert_copy(self, source_id: str, rel_path: str, size: int, mtime_ns: int, sha: str,
                    vault_rel: str, valid_from: float, is_current: bool = True,
                    valid_to: float | None = None) -> int:
        self.begin()
        key = fsutil.rel_key(rel_path)
        cur = self.db.execute(
            "INSERT INTO copies(source_id, rel_path, rel_key, parent_key, size, mtime_ns, sha256, vault_rel, "
            "valid_from, valid_to, is_current, run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (source_id, rel_path, key, fsutil.parent_key(key), size, mtime_ns, sha, vault_rel,
             valid_from, valid_to, 1 if is_current else 0, self.run_id))
        return cur.lastrowid

    def retire_copy(self, cid: int, version_rel: str | None, ts: float):
        """The current copy becomes an older version (moved into _versions)."""
        self.begin()
        if version_rel is None:
            self.db.execute("UPDATE copies SET is_current=0, valid_to=?, bad_at=COALESCE(bad_at, ?) WHERE id=?",
                            (ts, ts, cid))
        else:
            self.db.execute("UPDATE copies SET is_current=0, valid_to=?, vault_rel=? WHERE id=?",
                            (ts, version_rel, cid))

    def update_meta(self, cid: int, mtime_ns: int, rel_path: str):
        self.begin()
        self.db.execute("UPDATE copies SET mtime_ns=?, rel_path=? WHERE id=?", (mtime_ns, rel_path, cid))

    def set_offloaded(self, cid: int, ts: float | None):
        self.begin()
        self.db.execute("UPDATE copies SET offloaded_at=? WHERE id=?", (ts, cid))

    def set_gone(self, cid: int, ts: float | None):
        self.begin()
        self.db.execute("UPDATE copies SET gone_at=? WHERE id=?", (ts, cid))

    def set_keep_local(self, cid: int, keep: bool):
        self.begin()
        self.db.execute("UPDATE copies SET keep_local=? WHERE id=?", (1 if keep else 0, cid))

    def set_bad(self, cid: int, ts: float):
        self.begin()
        self.db.execute("UPDATE copies SET bad_at=? WHERE id=?", (ts, cid))

    def set_pruned(self, cid: int, ts: float):
        self.begin()
        self.db.execute("UPDATE copies SET pruned_at=? WHERE id=? AND is_current=0", (ts, cid))

    def offload_candidates(self, source_id: str, mtime_before_ns: int, copied_before: float) -> list[Copy]:
        rows = self.db.execute(
            f"SELECT {COPY_COLS} FROM copies WHERE source_id=? AND is_current=1 AND offloaded_at IS NULL "
            "AND gone_at IS NULL AND keep_local=0 AND bad_at IS NULL AND pruned_at IS NULL "
            "AND mtime_ns < ? AND valid_from < ?", (source_id, mtime_before_ns, copied_before))
        return [_copy(r) for r in rows]

    def non_current_by_file(self) -> dict:
        """{(source_id, rel_key): [Copy...]} for files that have older versions."""
        out: dict = {}
        rows = self.db.execute(f"SELECT {COPY_COLS} FROM copies WHERE pruned_at IS NULL AND is_current=0")
        for r in rows:
            c = _copy(r)
            out.setdefault((c.source_id, c.rel_key), []).append(c)
        return out

    def stats(self) -> dict:
        r = self.db.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM copies WHERE is_current=1").fetchone()
        v = self.db.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM copies WHERE is_current=0 "
                            "AND pruned_at IS NULL").fetchone()
        o = self.db.execute("SELECT COUNT(*), COALESCE(SUM(size),0) FROM copies WHERE is_current=1 "
                            "AND offloaded_at IS NOT NULL").fetchone()
        return {"files": r[0], "bytes": r[1], "versions": v[0], "version_bytes": v[1],
                "offloaded": o[0], "offloaded_bytes": o[1]}

    # ------------------------------------------------------------------ browse queries

    _ASOF = ("pruned_at IS NULL AND valid_from <= :t AND (valid_to IS NULL OR valid_to > :t) "
             "AND (gone_at IS NULL OR gone_at > :t)")

    def list_dir_asof(self, source_id: str, parent: str, t: float) -> list[Copy]:
        q = f"SELECT {COPY_COLS} FROM copies WHERE source_id=:s AND parent_key=:p AND {self._ASOF} ORDER BY rel_key"
        return [_copy(r) for r in self.db.execute(q, {"s": source_id, "p": parent, "t": t})]

    def subdirs_asof(self, source_id: str, parent: str, t: float) -> list[str]:
        """Names of the immediate sub-folders of `parent` that held files at time t."""
        if parent:
            like = parent.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"
            q = (f"SELECT DISTINCT parent_key FROM copies WHERE source_id=:s AND parent_key LIKE :l ESCAPE '\\' "
                 f"AND {self._ASOF}")
            rows = self.db.execute(q, {"s": source_id, "l": like, "t": t})
            plen = len(parent) + 1
        else:
            q = f"SELECT DISTINCT parent_key FROM copies WHERE source_id=:s AND parent_key <> '' AND {self._ASOF}"
            rows = self.db.execute(q, {"s": source_id, "t": t})
            plen = 0
        names = set()
        for (pk,) in rows:
            names.add(pk[plen:].split("/", 1)[0])
        names.discard("")
        return sorted(names)

    def dir_display_name(self, source_id: str, dir_key: str) -> str:
        """Original-case name of a folder, from any file beneath it."""
        like = dir_key.replace("%", "\\%").replace("_", "\\_") + "/%"
        r = self.db.execute("SELECT rel_path FROM copies WHERE source_id=? AND rel_key LIKE ? ESCAPE '\\' LIMIT 1",
                            (source_id, like)).fetchone()
        if not r:
            return dir_key.rsplit("/", 1)[-1]
        parts = r[0].replace("\\", "/").split("/")
        depth = dir_key.count("/")
        return parts[depth] if depth < len(parts) else dir_key.rsplit("/", 1)[-1]

    def copies_asof(self, t: float, source_id: str | None = None, prefix: str = "") -> Iterable[Copy]:
        q = f"SELECT {COPY_COLS} FROM copies WHERE {self._ASOF}"
        params = {"t": t}
        if source_id:
            q += " AND source_id=:s"
            params["s"] = source_id
        if prefix:
            q += " AND (rel_key = :p OR rel_key LIKE :l ESCAPE '\\')"
            params["p"] = prefix
            params["l"] = prefix.replace("%", "\\%").replace("_", "\\_") + "/%"
        for r in self.db.execute(q, params):
            yield _copy(r)

    def search(self, term: str, limit: int = 500) -> list[Copy]:
        like = "%" + term.lower().replace("%", "\\%").replace("_", "\\_") + "%"
        q = (f"SELECT {COPY_COLS} FROM copies WHERE pruned_at IS NULL AND rel_key LIKE ? ESCAPE '\\' "
             "ORDER BY is_current DESC, valid_from DESC LIMIT ?")
        return [_copy(r) for r in self.db.execute(q, (like, limit))]

    # ------------------------------------------------------------------ maintenance

    def backup_to(self, dest_path: str) -> None:
        """Consistent copy of the DB (used for the local cache)."""
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        tmp = dest_path + fsutil.TMP_SUFFIX
        if os.path.exists(tmp):
            os.remove(tmp)
        dst = sqlite3.connect(tmp)
        try:
            self.db.backup(dst)
        finally:
            dst.close()
        os.replace(tmp, dest_path)
