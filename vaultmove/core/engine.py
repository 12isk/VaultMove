"""Backup run orchestration: scan -> copy/version -> locked files -> offload -> thin.

Threading: an Engine instance is used by one worker thread. Progress is
reported through a plain callback (the Qt layer turns it into signals);
cancellation is a threading.Event checked per file and per chunk.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from . import crashpoints, fsutil, offload, recovery, retention, vault, winapi
from .config import Config, SourceCfg
from .copier import file_chunks, hash_file, place, write_verified_tmp
from .errors import (Cancelled, ChangedDuringCopy, OverlapRefused, SameDriveRefused, SourceReadError,
                     VaultBusy, VaultFull, VaultInvalid, VaultMoveError, VaultNotConnected,
                     VaultWriteError, VerifyFailed)
from .excludes import Matcher
from .index import Copy, Index
from .scanner import ScanReport, walk

FREE_SPACE_RESERVE = 64 * 1024 * 1024
CLOUD_MSG = ("Space will not be freed in {path}: it is synced by OneDrive or another cloud service, and deleting "
             "a file there would also delete it in the cloud. It is still backed up.")
COMMIT_EVERY_OPS = 200
COMMIT_EVERY_SECONDS = 2.0


@dataclass
class Stats:
    scanned: int = 0
    unchanged: int = 0
    copied: int = 0
    copied_bytes: int = 0
    versioned: int = 0
    metadata_updated: int = 0
    locked: int = 0
    locked_copied: int = 0
    changed_during_copy: int = 0
    vanished: int = 0
    errors: int = 0
    gone_marked: int = 0
    offloaded: int = 0
    offloaded_bytes: int = 0
    offload_skipped: int = 0
    pruned: int = 0
    pruned_bytes: int = 0
    recovered: int = 0
    sources_unavailable: int = 0


@dataclass
class PlanItem:
    action: str          # 'copy' | 'delete' | 'eligible'
    path: str            # absolute original path
    size: int
    note: str = ""


@dataclass
class Plan:
    items: list = field(default_factory=list)

    def total(self, action: str) -> tuple[int, int]:
        sel = [i for i in self.items if i.action == action]
        return len(sel), sum(i.size for i in sel)


@dataclass
class RunResult:
    status: str = "ok"   # ok | partial | cancelled | not_connected | busy | refused | error
    stats: Stats = field(default_factory=Stats)
    messages: list = field(default_factory=list)
    plan: Optional[Plan] = None
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    locked_files: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"status": self.status, "stats": asdict(self.stats), "messages": self.messages[-50:],
                "error": self.error, "started_at": self.started_at, "finished_at": self.finished_at}


class Engine:
    def __init__(self, cfg: Config, *, progress: Callable[[dict], None] | None = None,
                 log: Callable[[str], None] | None = None, cancel: threading.Event | None = None,
                 cache_dir: str | None = None, vss_factory=None, manual: bool = False,
                 now: Callable[[], float] = time.time, same_disk_fn=None, vault_root: str | None = None):
        self.cfg = cfg
        self._progress = progress
        self._log = log or (lambda m: None)
        self.cancel = cancel or threading.Event()
        self.cache_dir = cache_dir
        self.vss_factory = vss_factory
        self.manual = manual
        self.now = now
        self.same_disk_fn = same_disk_fn or winapi.same_physical_disk
        self.vault_root_override = vault_root
        self._ops = 0
        self._last_commit = 0.0
        self._last_progress = 0.0
        self._run_ts = ""

    # ------------------------------------------------------------------ helpers

    def log(self, msg: str):
        self._log(msg)

    def progress(self, force: bool = False, **kw):
        if self._progress is None:
            return
        t = time.monotonic()
        if force or t - self._last_progress >= 0.1:
            self._last_progress = t
            self._progress(kw)

    def _check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled()

    def _locate(self) -> str:
        if self.vault_root_override:
            root = fsutil.normroot(self.vault_root_override)
            m = vault.read_marker(root)
            if not m:
                raise VaultNotConnected("backup drive not connected")
            if m.get("uuid") != self.cfg.vault.uuid:
                raise VaultInvalid("this folder is a different VaultMove vault")
            return root
        return vault.require_vault(self.cfg.vault)

    def _vault_alive(self, vroot: str) -> bool:
        m = vault.read_marker(vroot)
        return bool(m and m.get("uuid") == self.cfg.vault.uuid)

    def _maybe_commit(self, idx: Index, force: bool = False):
        self._ops += 1
        t = time.monotonic()
        if force or self._ops >= COMMIT_EVERY_OPS or t - self._last_commit >= COMMIT_EVERY_SECONDS:
            idx.commit()
            self._ops = 0
            self._last_commit = t

    def _unique_version_rel(self, vroot: str, sid: str, rel: str) -> str:
        n = 1
        while True:
            ts = self._run_ts if n == 1 else f"{self._run_ts}-{n}"
            vrel = os.sep.join((vault.VERSIONS_DIR, ts, sid, rel))
            if not fsutil.exists(fsutil.join(vroot, vrel)):
                return vrel
            n += 1

    def _check_space(self, vroot: str, size: int):
        try:
            free = shutil.disk_usage(fsutil.lp(vroot) if os.name == "nt" else vroot).free
        except OSError as e:
            raise VaultWriteError(e) from e
        if free < size + FREE_SPACE_RESERVE:
            raise VaultFull("not enough free space on the backup drive")

    # ------------------------------------------------------------------ public API

    def run(self, dry_run: bool = False) -> RunResult:
        res = RunResult(started_at=self.now())
        bg = self.cfg.low_priority and winapi.set_thread_background(True)
        try:
            self._run(res, dry_run)
        except VaultNotConnected as e:
            res.status, res.error = "not_connected", str(e)
        except VaultBusy as e:
            res.status, res.error = "busy", str(e)
        except (SameDriveRefused, OverlapRefused, VaultInvalid) as e:
            res.status, res.error = "refused", str(e)
        except Cancelled:
            res.status = "cancelled"
        except VaultFull as e:
            res.status, res.error = "error", str(e)
        except VaultMoveError as e:
            res.status, res.error = "error", str(e)
        finally:
            if bg:
                winapi.set_thread_background(False)
            res.finished_at = self.now()
        if res.error:
            self.log(f"Backup stopped: {res.error}")
        return res

    def preview(self) -> RunResult:
        return self.run(dry_run=True)

    def preview_new_vault(self) -> RunResult:
        """Preview before the vault exists (first-run wizard): everything is a copy."""
        res = RunResult(started_at=self.now(), plan=Plan())
        try:
            for s in self.cfg.sources:
                if not os.path.isdir(fsutil.lp(s.path)):
                    continue
                days = self._offload_days_for_preview(s)
                if days and fsutil.in_cloud_sync(fsutil.join(s.path, "x")):
                    res.messages.append(CLOUD_MSG.format(path=s.path))
                    days = None
                for e in walk(s.path, Matcher(self.cfg.excludes + s.excludes), [], self.cancel):
                    res.stats.scanned += 1
                    abs_p = fsutil.join(s.path, e.rel)
                    res.plan.items.append(PlanItem("copy", abs_p, e.size))
                    if days and self._old_enough(e.mtime_ns, days) and not e.cloud:
                        res.plan.items.append(PlanItem("eligible", abs_p, e.size, "after this backup is verified"))
                    self.progress(phase="preview", done=res.stats.scanned, current=e.rel)
        except Cancelled:
            res.status = "cancelled"
        res.finished_at = self.now()
        return res

    # ------------------------------------------------------------------ run

    def _offload_days_for_preview(self, s: SourceCfg) -> Optional[int]:
        o = self.cfg.offload
        if not o.enabled or s.offload_enabled is False:
            return None
        return s.offload_after_days if s.offload_after_days is not None else o.after_days

    def _old_enough(self, mtime_ns: int, days: int) -> bool:
        m = mtime_ns / 1e9
        now = self.now()
        return m <= now and now - m >= days * 86400

    def _run(self, res: RunResult, dry_run: bool):
        vroot = self._locate()
        sources = list(self.cfg.sources)
        warnings = vault.check_sources(vroot, sources, self.cfg.vault.allow_same_drive, self.same_disk_fn)
        for w in warnings:
            res.messages.append(w)
            self.log("Note: " + w)
        if dry_run:
            res.plan = Plan()
        with vault.VaultLock(vroot):
            idx = Index.open_vault(vroot)
            try:
                self._run_locked(res, idx, vroot, sources, dry_run)
            finally:
                try:
                    idx.close()
                except Exception:
                    pass

    def _run_locked(self, res: RunResult, idx: Index, vroot: str, sources, dry_run: bool):
        st = res.stats
        started = self.now()
        self._run_ts = time.strftime("%Y-%m-%d_%H%M%S", time.localtime(started))
        if not dry_run:
            st.recovered = recovery.recover(idx, vroot, self.log, started)
            run_id = idx.start_run(started)
            vault.write_sources_json(vroot, sources)
        else:
            run_id = None
        self._last_commit = time.monotonic()
        locked: list = []
        try:
            for s in sources:
                self._check_cancel()
                if not os.path.isdir(fsutil.lp(s.path)):
                    st.sources_unavailable += 1
                    res.messages.append(f"Folder not available, skipped: {s.path}")
                    self.log(f"Folder not available, skipped: {s.path}")
                    continue
                if not dry_run:
                    idx.upsert_source(s.id, s.path)
                self._backup_source(res, idx, vroot, s, dry_run, locked)
            if not dry_run:
                idx.commit()
            if locked and not dry_run:
                self._copy_locked(res, idx, vroot, locked)
                idx.commit()
            res.locked_files = [fsutil.join(s.path, e_rel) for s, e_rel, _ in locked]

            # Offload only runs after every copy of this run is committed.
            self._check_cancel()
            self._offload_phase(res, idx, vroot, sources, started, dry_run)
            if not dry_run:
                self._prune_phase(res, idx, vroot)
        except (Cancelled, VaultFull, VaultNotConnected, VaultWriteError) as e:
            if not dry_run:
                try:
                    idx.commit()
                except Exception:
                    try:
                        idx.rollback()
                    except Exception:
                        pass
                try:
                    self._finish(idx, run_id, "cancelled" if isinstance(e, Cancelled) else "error", res)
                except Exception:
                    pass
            raise

        if not dry_run:
            status = "ok" if (st.errors == 0 and st.locked == st.locked_copied) else "partial"
            self._finish(idx, run_id, status, res)
            res.status = status
            self._cache_index(idx)
        self.progress(force=True, phase="done", done=st.scanned, total=st.scanned)

    def _finish(self, idx: Index, run_id: int, status: str, res: RunResult):
        idx.finish_run(run_id, self.now(), status, asdict(res.stats))

    def _cache_index(self, idx: Index):
        if not self.cache_dir:
            return
        try:
            idx.backup_to(os.path.join(self.cache_dir, f"index-{self.cfg.vault.uuid}.sqlite"))
        except Exception as e:  # cache is a convenience, never fatal
            self.log(f"Could not update the local index cache: {e}")

    # ------------------------------------------------------------------ per source

    def _backup_source(self, res: RunResult, idx: Index, vroot: str, s: SourceCfg, dry_run: bool, locked: list):
        st = res.stats
        cur_map = idx.current_map(s.id)
        matcher = Matcher(self.cfg.excludes + s.excludes)
        report = ScanReport([])
        avoid = [vroot]
        self.log(f"Scanning {s.path}")
        for e in walk(s.path, matcher, avoid, self.cancel, report):
            st.scanned += 1
            key = fsutil.rel_key(e.rel)
            cur = cur_map.pop(key, None)
            if cur is not None and cur.bad_at is None and cur.size == e.size and cur.mtime_ns == e.mtime_ns:
                st.unchanged += 1
                if not dry_run and (cur.offloaded_at or cur.gone_at):
                    idx.set_offloaded(cur.id, None)
                    idx.set_gone(cur.id, None)
                    idx.add_event("present_again", s.id, e.rel)
                    self._maybe_commit(idx)
                self.progress(phase="scan", done=st.scanned, current=e.rel, copied=st.copied,
                              bytes=st.copied_bytes)
                continue
            if dry_run:
                res.plan.items.append(PlanItem("copy", fsutil.join(s.path, e.rel), e.size,
                                               "changed" if cur else "new"))
                continue
            self.progress(phase="copy", done=st.scanned, current=e.rel, copied=st.copied, bytes=st.copied_bytes)
            self._backup_file(res, idx, vroot, s, e, cur, locked)

        for rel_dir, msg in report.dir_errors:
            st.errors += 1
            self.log(f"Could not read {fsutil.join(s.path, rel_dir)}: {msg}")
        if report.skipped_links:
            self.log(f"Skipped {report.skipped_links} links/junctions in {s.path} (never followed).")
        if report.skipped_online_only:
            self.log(f"Skipped {report.skipped_online_only} online-only cloud files in {s.path}.")

        if dry_run:
            return
        # Files that disappeared from the PC (not by offload): keep the copy, record when.
        err_keys = [fsutil.rel_key(d) for d, _ in report.dir_errors]
        if "" in err_keys:
            return
        now = self.now()
        for key, cur in cur_map.items():
            if cur.offloaded_at or cur.gone_at:
                continue
            if any(key == p or key.startswith(p + "/") for p in err_keys):
                continue
            if fsutil.exists(fsutil.join(s.path, cur.rel_path)):
                continue  # still on the PC, just excluded or unreadable now
            idx.set_gone(cur.id, now)
            idx.add_event("gone", s.id, cur.rel_path)
            st.gone_marked += 1
            self._maybe_commit(idx)

    def _backup_file(self, res, idx, vroot, s, e, cur: Copy | None, locked: list):
        st = res.stats
        abs_src = fsutil.join(s.path, e.rel)
        try:
            if cur is not None and cur.bad_at is None and cur.size == e.size:
                # Same size, different mtime: compare content before copying.
                try:
                    sha, _ = hash_file(abs_src, self.cancel)
                except OSError as ex:
                    raise SourceReadError(ex) from ex
                if sha == cur.sha256:
                    idx.update_meta(cur.id, e.mtime_ns, e.rel)
                    if cur.offloaded_at or cur.gone_at:
                        idx.set_offloaded(cur.id, None)
                        idx.set_gone(cur.id, None)
                    st.metadata_updated += 1
                    self._maybe_commit(idx)
                    return
            self._store(res, idx, vroot, s, e.rel, lambda: file_chunks(abs_src), abs_src, cur, None)
        except ChangedDuringCopy:
            st.changed_during_copy += 1
            self.log(f"Changed while copying, will retry next run: {abs_src}")
        except SourceReadError as ex:
            o = ex.original
            if winapi.is_sharing_violation(o):
                st.locked += 1
                locked.append((s, e.rel, cur))
            elif isinstance(o, FileNotFoundError):
                st.vanished += 1
            else:
                st.errors += 1
                self.log(f"Could not read {abs_src}: {o}")
        except VaultWriteError as ex:
            if not self._vault_alive(vroot):
                raise VaultNotConnected("backup drive was disconnected during the backup") from ex
            st.errors += 1
            self.log(f"Could not write the copy of {abs_src}: {ex}")
        except VerifyFailed as ex:
            st.errors += 1
            self.log(f"Verification failed for {abs_src}: {ex}")

    def _store(self, res, idx: Index, vroot: str, s: SourceCfg, rel: str, chunk_factory, abs_src: str | None,
               cur: Copy | None, snap_meta: tuple | None):
        """Copy one file into the vault, versioning any previous copy (invariants 2, 3)."""
        st = res.stats
        if abs_src is not None:
            try:
                s0 = os.lstat(fsutil.lp(abs_src))
            except OSError as ex:
                raise SourceReadError(ex) from ex
            size0, mt0 = s0.st_size, s0.st_mtime_ns
        else:
            size0, mt0 = snap_meta
        self._check_space(vroot, size0)
        data_rel = os.sep.join((vault.DATA_DIR, s.id, rel))
        final = fsutil.join(vroot, data_rel)

        def on_bytes(n):
            st.copied_bytes += n
            self.progress(phase="copy", done=st.scanned, current=rel, copied=st.copied, bytes=st.copied_bytes)

        tmp, sha, n = write_verified_tmp(chunk_factory(), final, mt0, cancel=self.cancel, on_bytes=on_bytes)
        if abs_src is not None:
            try:
                s1 = os.lstat(fsutil.lp(abs_src))
            except OSError:
                s1 = None
            if s1 is None or (s1.st_size, s1.st_mtime_ns) != (size0, mt0) or n != size0:
                fsutil.remove_quiet(tmp)
                raise ChangedDuringCopy(abs_src)
        elif n != size0:
            fsutil.remove_quiet(tmp)
            raise ChangedDuringCopy(rel)

        ts = self.now()
        if cur is None:
            if fsutil.exists(final):
                self._move_untracked_aside(idx, vroot, s, rel, final, ts)
            place(tmp, final)
            crashpoints.crash("after_replace")
            idx.insert_copy(s.id, rel, n, mt0, sha, data_rel, ts)
            idx.add_event("copy", s.id, rel, {"sha256": sha, "size": n, "vault": data_rel})
            st.copied += 1
            self._maybe_commit(idx)
            return

        # Changed file: journal, move old copy to _versions, place new copy.
        old_final = fsutil.join(vroot, cur.vault_rel)
        vrel = self._unique_version_rel(vroot, s.id, rel)
        old_exists = fsutil.isfile(old_final)
        payload = {"source_id": s.id, "rel": rel, "data_rel": data_rel, "tmp_rel": data_rel + fsutil.TMP_SUFFIX,
                   "old_vault_rel": cur.vault_rel, "version_rel": vrel, "old_copy_id": cur.id,
                   "old_existed": old_exists, "sha": sha, "size": n, "mtime_ns": mt0, "ts": ts}
        pid = idx.add_pending("store", payload)
        idx.commit()
        crashpoints.crash("after_journal")
        try:
            if old_exists:
                vfull = fsutil.join(vroot, vrel)
                fsutil.makedirs(os.path.dirname(vfull))
                os.replace(fsutil.lp(old_final), fsutil.lp(vfull))
            else:
                self.log(f"WARNING: previous copy of {rel} was missing from the vault")
            crashpoints.crash("after_version_move")
            if fsutil.exists(final):
                self._move_untracked_aside(idx, vroot, s, rel, final, ts)
            place(tmp, final)
        except OSError as ex:
            raise VaultWriteError(ex) from ex
        crashpoints.crash("after_replace")
        recovery.apply_store(idx, payload, version_present=old_exists)
        idx.remove_pending(pid)
        st.copied += 1
        st.versioned += 1 if old_exists else 0
        self._maybe_commit(idx)

    def _move_untracked_aside(self, idx: Index, vroot: str, s: SourceCfg, rel: str, final: str, ts: float):
        """A file sits where a new copy must go but the index doesn't know it (e.g. crash
        before a batch commit). Never overwrite: keep it as a recovered older version."""
        try:
            sha, n = hash_file(final)
            mt = os.lstat(fsutil.lp(final)).st_mtime_ns
        except OSError as ex:
            raise VaultWriteError(ex) from ex
        vrel = self._unique_version_rel(vroot, s.id, rel)
        vfull = fsutil.join(vroot, vrel)
        fsutil.makedirs(os.path.dirname(vfull))
        os.replace(fsutil.lp(final), fsutil.lp(vfull))
        idx.insert_copy(s.id, rel, n, mt, sha, vrel, valid_from=min(mt / 1e9, ts), is_current=False, valid_to=ts)
        idx.add_event("recovered_untracked", s.id, rel, {"vault": vrel, "sha256": sha})

    # ------------------------------------------------------------------ locked files (VSS)

    def _copy_locked(self, res: RunResult, idx: Index, vroot: str, locked: list):
        st = res.stats
        session = None
        if self.cfg.vss_enabled and self.vss_factory is not None and self.manual:
            try:
                session = self.vss_factory([s.path for s in self.cfg.sources])
            except Exception as e:
                self.log(f"Open-file backup unavailable: {e}")
                session = None
        if session is None:
            msg = (f"{len(locked)} file(s) were in use and were skipped; they will be retried next run."
                   + ("" if self.manual else " Use Back Up Now to copy them with a snapshot."))
            res.messages.append(msg)
            self.log(msg)
            return
        try:
            for s, rel, cur in locked:
                self._check_cancel()
                abs_src = fsutil.join(s.path, rel)
                try:
                    size, mtime_ns, chunks = session.open(abs_src)
                    if cur is not None and cur.size == size and cur.mtime_ns == mtime_ns and cur.bad_at is None:
                        st.locked_copied += 1
                        continue
                    self._store(res, idx, vroot, s, rel, lambda: chunks, None, cur, (size, mtime_ns))
                    st.locked_copied += 1
                except (VaultFull, VaultNotConnected, Cancelled):
                    raise
                except Exception as e:
                    self.log(f"Could not copy open file {abs_src} from snapshot: {e}")
        finally:
            try:
                session.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ offload

    def _offload_phase(self, res: RunResult, idx: Index, vroot: str, sources, started: float, dry_run: bool):
        st = res.stats
        armed = self.cfg.offload_armed()
        if dry_run:
            # The preview lists what *would* be deleted (offload need not be armed yet).
            for s in sources:
                days = self._offload_days_for_preview(s)
                if not days or not os.path.isdir(fsutil.lp(s.path)):
                    continue
                if fsutil.in_cloud_sync(fsutil.join(s.path, "x")):
                    res.messages.append(CLOUD_MSG.format(path=s.path))
                    continue
                if self.same_disk_fn(vroot, s.path) is not False:
                    res.messages.append(f"Space will not be freed in {s.path}: the backup drive is not "
                                        "confirmed to be a different physical disk.")
                    continue
                cutoff = int((self.now() - days * 86400) * 1e9)
                for c in idx.offload_candidates(s.id, cutoff, started):
                    p = fsutil.join(s.path, c.rel_path)
                    d = offload.check_source_state(p, c, days, self.now())
                    if d.ok:
                        res.plan.items.append(PlanItem("delete", p, c.size, "verified copy on backup drive"))
                to_copy = [i for i in res.plan.items if i.action == "copy" and fsutil.is_within(i.path, s.path)]
                for it in to_copy:
                    try:
                        st_ = os.lstat(fsutil.lp(it.path))
                    except OSError:
                        continue
                    if self._old_enough(st_.st_mtime_ns, days) and not fsutil.is_cloud_placeholder(st_):
                        res.plan.items.append(PlanItem("eligible", it.path, it.size,
                                                       "after this backup is verified"))
            return
        if not armed:
            return
        recycle = self.cfg.recycle_effective(self.now())
        for s in sources:
            days = self.cfg.source_offload_days(s)
            if not days or not os.path.isdir(fsutil.lp(s.path)):
                continue
            if fsutil.in_cloud_sync(fsutil.join(s.path, "x")):
                self.log(CLOUD_MSG.format(path=s.path))
                continue
            same = self.same_disk_fn(vroot, s.path)
            if same is not False:
                self.log(f"Not freeing space in {s.path}: the backup drive is not confirmed to be a "
                         "different physical disk.")
                continue
            matcher = Matcher(self.cfg.excludes + s.excludes)
            cutoff = int((self.now() - days * 86400) * 1e9)
            for c in idx.offload_candidates(s.id, cutoff, started):
                self._check_cancel()
                if matcher.excluded(c.rel_path):
                    continue
                if not self._vault_alive(vroot):
                    raise VaultNotConnected("backup drive was disconnected")
                self.progress(phase="offload", current=c.rel_path, done=st.offloaded)
                d = offload.offload_one(idx, vroot, s, c, days=days, now=self.now(), recycle=recycle,
                                        log=self.log, cancel=self.cancel)
                if d.ok:
                    st.offloaded += 1
                    st.offloaded_bytes += c.size
                    self.log(f"Freed {fsutil.join(s.path, c.rel_path)} ({d.reason}); copy kept on the backup drive.")
                else:
                    st.offload_skipped += 1

    # ------------------------------------------------------------------ retention

    def _prune_phase(self, res: RunResult, idx: Index, vroot: str):
        by_id = {s.id: s for s in self.cfg.sources}

        def keep_for(sid):
            s = by_id.get(sid)
            return self.cfg.source_keep_days(s) if s else self.cfg.keep_versions_days

        doomed = retention.plan_prune(idx, keep_for, self.cfg.thinning, self.now())
        if doomed:
            self.progress(force=True, phase="prune", total=len(doomed))
            n, b = retention.prune(idx, vroot, doomed, self.now(), self.log, self.cancel)
            res.stats.pruned += n
            res.stats.pruned_bytes += b


def delete_old_versions(cfg: Config, older_than_days: float, log=print, vault_root: str | None = None) -> tuple[int, int]:
    """Manual 'delete old versions' (never touches the latest copy of any file)."""
    vroot = fsutil.normroot(vault_root) if vault_root else vault.require_vault(cfg.vault)
    with vault.VaultLock(vroot):
        idx = Index.open_vault(vroot)
        try:
            now = time.time()
            doomed = retention.plan_prune(idx, lambda sid: None, False, now, older_than_days=older_than_days)
            return retention.prune(idx, vroot, doomed, now, log)
        finally:
            idx.close()
