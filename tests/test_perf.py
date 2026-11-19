"""Incremental no-change scan of a >=200k-file tree must finish in under 60 s.

Enabled with VAULTMOVE_PERF=1 (CI runs it). The tree is real files on disk;
the index is seeded directly (copying 200k files first would only measure the
disk, not the incremental scan).
"""

import os
import time

import pytest

from vaultmove.core import fsutil

N_FILES = int(os.environ.get("VAULTMOVE_PERF_FILES", "200000"))
PER_DIR = 200


@pytest.mark.perf
def test_incremental_scan_200k(env):
    t0 = time.perf_counter()
    n_dirs = (N_FILES + PER_DIR - 1) // PER_DIR
    made = 0
    for d in range(n_dirs):
        dp = os.path.join(env.src, f"g{d // 50:03d}", f"d{d:05d}")
        os.makedirs(dp)
        for i in range(PER_DIR):
            if made >= N_FILES:
                break
            with open(os.path.join(dp, f"f{i:03d}.txt"), "wb") as f:
                f.write(b"x")
            made += 1
    gen = time.perf_counter() - t0

    idx = env.index()
    sid = env.sid
    rows = []
    for dp, _dn, fn in os.walk(env.src):
        for n in fn:
            full = os.path.join(dp, n)
            st = os.stat(full)
            rel = full[len(env.src) + 1:]
            key = fsutil.rel_key(rel)
            rows.append((sid, rel, key, fsutil.parent_key(key), st.st_size, st.st_mtime_ns, "0" * 64,
                         "data" + os.sep + sid + os.sep + rel, time.time() - 10))
    idx.begin()
    idx.db.executemany("INSERT INTO copies(source_id, rel_path, rel_key, parent_key, size, mtime_ns, sha256, "
                       "vault_rel, valid_from) VALUES(?,?,?,?,?,?,?,?,?)", rows)
    idx.commit()
    idx.close()

    t1 = time.perf_counter()
    r = env.run()
    scan = time.perf_counter() - t1
    print(f"\n{made} files generated in {gen:.1f}s; incremental no-change run: {scan:.1f}s")
    assert r.status == "ok", r.error
    assert r.stats.unchanged == made and r.stats.copied == 0
    assert scan < 60, f"incremental scan took {scan:.1f}s"
