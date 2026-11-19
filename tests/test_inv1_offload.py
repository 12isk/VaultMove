"""Invariant 1: an original is deleted only after every safety check passes."""

import os
import time

import pytest

from tests.helpers import DAY, sha_file
from vaultmove.core import fsutil, winapi


def _two_runs(env):
    r1 = env.run()
    assert r1.status == "ok", r1.error
    return env.run()


def test_offload_happens_only_in_a_later_run_than_the_copy(env):
    p = env.write("old.txt", b"x" * 1000, age_days=100)
    env.arm_offload(days=30)
    r1 = env.run()
    assert r1.stats.copied == 1 and r1.stats.offloaded == 0
    assert os.path.exists(p)
    r2 = env.run()
    assert r2.stats.offloaded == 1
    assert not os.path.exists(p)


def test_a_no_copy_in_vault_means_no_delete(env):
    p = env.write("old.txt", b"data", age_days=100)
    env.run()
    idx = env.index()
    c = idx.current_copy(env.sid, "old.txt")
    os.remove(os.path.join(env.vault, c.vault_rel))
    idx.close()
    env.arm_offload(days=30)
    r = env.run()
    assert os.path.exists(p), "original must survive when the vault copy is missing"
    assert r.stats.offloaded == 0
    # The missing copy is flagged and re-made on the next run.
    r2 = env.run()
    assert r2.stats.copied == 1
    assert os.path.exists(p)


def test_b_vault_copy_rehash_mismatch_blocks_delete(env):
    p = env.write("old.txt", b"good content", age_days=100)
    env.run()
    idx = env.index()
    c = idx.current_copy(env.sid, "old.txt")
    vfile = os.path.join(env.vault, c.vault_rel)
    with open(vfile, "r+b") as f:
        f.write(b"BAD!")  # silent corruption on the backup drive, same size
    idx.close()
    env.arm_offload(days=30)
    r = env.run()
    assert os.path.exists(p)
    assert r.stats.offloaded == 0
    idx = env.index()
    assert idx.current_copy(env.sid, "old.txt").bad_at is not None
    idx.close()
    env.run()  # recopy (corrupt copy is versioned, never overwritten)
    idx = env.index()
    cur = idx.current_copy(env.sid, "old.txt")
    assert cur.bad_at is None
    assert sha_file(os.path.join(env.vault, cur.vault_rel)) == sha_file(p)
    idx.close()


def test_c_source_content_differs_with_same_size_and_mtime(env):
    p = env.write("old.txt", b"AAAA" * 100, age_days=100)
    st = os.stat(p)
    env.run()
    with open(p, "r+b") as f:
        f.write(b"BBBB")  # same size
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))  # same mtime: scan thinks unchanged
    env.arm_offload(days=30)
    r = env.run()
    assert os.path.exists(p), "source re-hash must catch the difference"
    assert r.stats.offloaded == 0


def test_d_source_changes_during_verification(env, monkeypatch):
    p = env.write("old.txt", b"data" * 10, age_days=100)
    env.run()
    env.arm_offload(days=30)
    real = winapi.LockedHandle.stat
    calls = {"n": 0}

    def flaky(self):
        calls["n"] += 1
        size, mt = real(self)
        return (size, mt + 1) if calls["n"] >= 2 else (size, mt)

    monkeypatch.setattr(winapi.LockedHandle, "stat", flaky)
    r = env.run()
    assert os.path.exists(p)
    assert r.stats.offloaded == 0


def test_d_source_size_changed_after_backup(env):
    p = env.write("old.txt", b"data", age_days=100)
    env.run()
    env.arm_offload(days=30)
    # Grow the file but keep it old: the scan copies the new version first,
    # and that new copy is only eligible in a *later* run.
    with open(p, "ab") as f:
        f.write(b"more")
    t = time.time() - 100 * DAY
    os.utime(p, (t, t))
    r = env.run()
    assert os.path.exists(p)
    assert r.stats.copied == 1 and r.stats.offloaded == 0


def test_e_young_files_are_kept(env):
    p = env.write("recent.txt", b"data", age_days=10)
    env.arm_offload(days=30)
    r = _two_runs(env)
    assert os.path.exists(p)
    assert r.stats.offloaded == 0


def test_e_future_mtime_is_kept(env):
    p = env.write("future.txt", b"data")
    t = time.time() + 400 * DAY
    os.utime(p, (t, t))
    env.arm_offload(days=1)
    _two_runs(env)
    assert os.path.exists(p)


def test_file_open_for_writing_is_not_deleted(env):
    p = env.write("old.txt", b"data", age_days=100)
    env.run()
    env.arm_offload(days=30)
    with open(p, "ab"):  # another program has it open for writing
        r = env.run()
        assert os.path.exists(p)
        assert r.stats.offloaded == 0


def test_same_physical_disk_never_offloads(env):
    p = env.write("old.txt", b"data", age_days=100)
    env.run()
    env.arm_offload(days=30)
    r = env.run(same_disk_fn=lambda a, b: None)  # unknown -> no offload
    assert os.path.exists(p)
    env.cfg.vault.allow_same_drive = True
    r = env.run(same_disk_fn=lambda a, b: True)
    assert os.path.exists(p)
    assert r.stats.offloaded == 0


def test_readonly_files_are_not_offloaded(env):
    p = env.write("ro.txt", b"data", age_days=100)
    os.chmod(p, 0o444)
    try:
        env.run()
        env.arm_offload(days=30)
        env.run()
        assert os.path.exists(p)
    finally:
        os.chmod(p, 0o666)


def test_excluded_after_backup_is_not_offloaded(env):
    p = env.write("keep.psd", b"data", age_days=100)
    env.run()
    env.arm_offload(days=30)
    env.cfg.excludes.append("*.psd")
    env.run()
    assert os.path.exists(p)


def test_offloaded_copy_matches_original_hash(env):
    p = env.write("old.bin", os.urandom(2_000_000), age_days=100)
    h = sha_file(p)
    env.arm_offload(days=30)
    _two_runs(env)
    assert not os.path.exists(p)
    idx = env.index()
    c = idx.current_copy(env.sid, "old.bin")
    assert c.offloaded_at and c.sha256 == h
    assert sha_file(os.path.join(env.vault, c.vault_rel)) == h
    idx.close()
