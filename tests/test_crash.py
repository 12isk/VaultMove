"""Fault injection: kill the process (os._exit, no cleanup) at every crash point,
then verify that the next run recovers and no data is lost."""

import os
import subprocess
import sys
import time

import pytest

from tests.helpers import DAY, ROOT, sha, sha_file
from vaultmove.core import fsutil
from vaultmove.core.restore import restore_many

CHILD = os.path.join(ROOT, "tests", "child_run.py")


def run_child(env, point, skip=0):
    env.save_cfg()
    e = dict(os.environ, VAULTMOVE_CRASHPOINT=point, VAULTMOVE_CRASHPOINT_SKIP=str(skip))
    r = subprocess.run([sys.executable, CHILD, env.cfg_dir], env=e, capture_output=True, timeout=180)
    return r.returncode, r.stdout.decode(errors="replace") + r.stderr.decode(errors="replace")


def assert_consistent(env):
    """Every live index row points at a vault file with the recorded hash; no journal left."""
    idx = env.index()
    try:
        assert idx.list_pending() == []
        rows = idx.db.execute("SELECT vault_rel, sha256, is_current FROM copies WHERE pruned_at IS NULL "
                              "AND bad_at IS NULL").fetchall()
        for vrel, h, _cur in rows:
            p = os.path.join(env.vault, vrel)
            assert os.path.isfile(p), f"index points at missing {vrel}"
            assert sha_file(p) == h, f"hash mismatch for {vrel}"
        currents = idx.db.execute("SELECT source_id, rel_key, COUNT(*) FROM copies WHERE is_current=1 "
                                  "GROUP BY source_id, rel_key HAVING COUNT(*) > 1").fetchall()
        assert currents == []
    finally:
        idx.close()
    data_tmp = [p for p in env.vault_files("data") if p.endswith(".vmtmp")]
    return data_tmp


STORE_POINTS = ["mid_copy", "after_tmp_verified", "after_journal", "after_version_move", "after_replace"]


@pytest.mark.parametrize("point", STORE_POINTS)
def test_crash_while_versioning_a_changed_file(env, point):
    p = env.write("doc.txt", b"version 1")
    assert env.run().status == "ok"
    with open(p, "wb") as f:
        f.write(b"version 2 is longer")
    code, out = run_child(env, point)
    assert code == 99, out
    # Right after the crash the old version is still reachable somewhere in the vault.
    hashes = {sha_file(x) for x in env.vault_files() if not x.endswith((".vmtmp", ".sqlite", ".json",
                                                                         ".jsonl", ".lock", "-journal"))}
    assert sha(b"version 1") in hashes
    # Next normal run recovers.
    r = env.run()
    assert r.status == "ok", r.error
    assert assert_consistent(env) == []
    idx = env.index()
    cs = idx.copies_of(env.sid, "doc.txt")
    idx.close()
    assert cs[0].is_current and cs[0].sha256 == sha(b"version 2 is longer")
    assert sha(b"version 1") in {c.sha256 for c in cs[1:]}


@pytest.mark.parametrize("point", ["mid_copy", "after_tmp_verified", "after_replace"])
def test_crash_while_copying_new_files(env, point):
    for i in range(5):
        env.write(f"f{i}.bin", os.urandom(5000))
    code, out = run_child(env, point, skip=2)
    assert code == 99, out
    r = env.run()
    assert r.status == "ok"
    assert assert_consistent(env) == []
    idx = env.index()
    for i in range(5):
        c = idx.current_copy(env.sid, f"f{i}.bin")
        assert c is not None and c.sha256 == sha_file(env.path(f"f{i}.bin"))
    idx.close()


def test_crash_before_delete_keeps_original(env):
    p = env.write("old.txt", b"precious", age_days=100)
    env.run()
    env.arm_offload(days=30)
    code, out = run_child(env, "before_delete")
    assert code == 99, out
    assert os.path.exists(p)
    r = env.run()
    assert r.status == "ok"
    assert_consistent(env)
    assert not os.path.exists(p)  # offloaded properly on the recovery run
    idx = env.index()
    assert idx.current_copy(env.sid, "old.txt").offloaded_at is not None
    idx.close()


def test_crash_after_delete_is_recorded_and_restorable(env):
    p = env.write("old.txt", b"precious", age_days=100)
    env.run()
    env.arm_offload(days=30)
    code, out = run_child(env, "after_delete")
    assert code == 99, out
    assert not os.path.exists(p)
    r = env.run()
    assert r.status == "ok"
    assert_consistent(env)
    idx = env.index()
    c = idx.current_copy(env.sid, "old.txt")
    assert c.offloaded_at is not None
    kinds = [k for _, k, _ in idx.events_for(env.sid, "old.txt")]
    assert "offload" in kinds
    res = restore_many(idx, env.vault, [c], dest_root=None)
    idx.close()
    assert res.restored
    assert sha_file(p) == sha(b"precious")


def test_crash_mid_prune(env):
    p = env.write("f.txt", b"1")
    env.run()
    for c in (b"22", b"333"):
        with open(p, "wb") as f:
            f.write(c)
        env.run()
    env.cfg.keep_versions_days = 0
    code, out = run_child(env, "mid_prune")
    assert code == 99, out
    r = env.run()
    assert r.status == "ok"
    assert_consistent(env)
    idx = env.index()
    cur = idx.current_copy(env.sid, "f.txt")
    idx.close()
    assert cur.sha256 == sha(b"333")
    assert sha_file(os.path.join(env.vault, cur.vault_rel)) == sha(b"333")
