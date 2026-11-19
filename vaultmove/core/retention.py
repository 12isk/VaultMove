"""Version thinning: hourly for 24 h, daily for a month, weekly after.

Only older versions (is_current=0) are ever considered. The latest copy of a
file is never pruned, even if the original was deleted or offloaded.
Prune order: commit pruned_at in the index first, then delete the file; a
crash in between only leaves an unreferenced file (wasted space, no loss).
"""

from __future__ import annotations

import datetime as _dt
import os
import time

from . import crashpoints, fsutil
from .vault import VERSIONS_DIR

HOUR = 3600
DAY = 86400


def bucket(ts: float, now: float, cid: int = 0):
    """Thinning bucket. Every version younger than 24 h is kept (its own bucket):
    runs are hourly, so this is 'hourly for 24 h' without ever thinning away a
    version that a manual Back Up Now made a few minutes ago."""
    age = now - ts
    if age < DAY:
        return ("all", cid)
    if age < 31 * DAY:
        return ("d", time.strftime("%Y-%m-%d", time.localtime(ts)))
    y, w, _ = _dt.date.fromtimestamp(ts).isocalendar()
    return ("w", y, w)


def plan_prune(idx, keep_days_for, thinning: bool, now: float, older_than_days: float | None = None):
    """Return the list of non-current copies to prune.

    keep_days_for(source_id) -> Optional[int]: versions whose end is older are pruned.
    older_than_days: manual "delete old versions" (overrides keep_days).
    """
    out = []
    for (sid, _key), olds in idx.non_current_by_file().items():
        keep_days = older_than_days if older_than_days is not None else keep_days_for(sid)
        olds.sort(key=lambda c: (c.valid_to or c.valid_from, c.id), reverse=True)
        seen = set()
        for c in olds:
            if c.is_current:
                continue
            t = c.valid_to or c.valid_from
            if keep_days is not None and now - t > keep_days * DAY:
                out.append(c)
                continue
            if older_than_days is not None or not thinning:
                continue
            b = bucket(t, now, c.id)
            if b in seen:
                out.append(c)
            else:
                seen.add(b)
    return out


def prune(idx, vroot: str, copies, now: float, log, cancel=None, batch: int = 200) -> tuple[int, int]:
    n_files = n_bytes = 0
    for i in range(0, len(copies), batch):
        chunk = []
        for c in copies[i:i + batch]:
            fresh = idx.get_copy(c.id)
            if fresh is None or fresh.is_current or fresh.pruned_at is not None:
                continue
            idx.set_pruned(fresh.id, now)
            idx.add_event("prune", fresh.source_id, fresh.rel_path, {"vault": fresh.vault_rel,
                                                                     "sha256": fresh.sha256})
            chunk.append(fresh)
        idx.commit()
        crashpoints.crash("mid_prune")
        for c in chunk:
            # Paranoia: never delete a file still referenced by a live index row.
            still = idx.db.execute("SELECT COUNT(*) FROM copies WHERE vault_rel=? AND pruned_at IS NULL",
                                   (c.vault_rel,)).fetchone()[0]
            if still:
                continue
            p = fsutil.join(vroot, c.vault_rel)
            try:
                os.remove(fsutil.lp(p))
                n_files += 1
                n_bytes += c.size
            except FileNotFoundError:
                pass
            except OSError as e:
                log(f"Could not delete old version {c.vault_rel}: {e}")
            _remove_empty_parents(vroot, os.path.dirname(p))
        if cancel is not None and cancel.is_set():
            break
    return n_files, n_bytes


def _remove_empty_parents(vroot: str, d: str):
    stop = os.path.normcase(fsutil.join(vroot, VERSIONS_DIR))
    while os.path.normcase(d).startswith(stop + os.sep):
        try:
            os.rmdir(fsutil.lp(d))
        except OSError:
            return
        d = os.path.dirname(d)
