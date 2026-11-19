"""File changed during copy, locked file, vault full, vault unplugged mid-run,
two instances racing, clock changes."""

import ctypes
import errno
import os
import threading
import time

import pytest

from tests.helpers import DAY, sha, sha_file
from tests.test_crash import assert_consistent
from vaultmove.core import copier, engine as engmod, vault, winapi
from vaultmove.core.errors import VaultWriteError


def test_file_changed_during_copy(env, monkeypatch):
    p = env.write("growing.log", b"a" * 100_000)
    real = copier.file_chunks

    def chunks_then_modify(path):
        for c in real(path):
            yield c
        with open(path, "ab") as f:
            f.write(b"appended while copying")

    monkeypatch.setattr(engmod, "file_chunks", chunks_then_modify)
    r = env.run()
    assert r.stats.changed_during_copy == 1 and r.stats.copied == 0
    assert not [x for x in env.vault_files() if x.endswith(".vmtmp")]
    idx = env.index()
    assert idx.current_copy(env.sid, "growing.log") is None
    idx.close()
    monkeypatch.setattr(engmod, "file_chunks", real)
    r = env.run()
    assert r.stats.copied == 1
    assert_consistent(env)


@pytest.mark.skipif(not winapi.IS_WIN, reason="Windows share modes")
def test_locked_file_is_skipped_and_retried(env):
    p = env.write("outlook.pst", b"mailbox")
    env.write("ok.txt", b"fine")
    k32 = winapi.k32
    h = k32.CreateFileW(p, winapi.GENERIC_READ, 0, None, winapi.OPEN_EXISTING, 0, None)  # share 0: exclusive
    assert h not in (None, winapi.INVALID_HANDLE_VALUE)
    try:
        r = env.run()
        assert r.stats.locked == 1 and r.stats.copied == 1
        assert r.status == "partial"
        assert any("in use" in m for m in r.messages)
    finally:
        k32.CloseHandle(h)
    r = env.run()
    assert r.stats.copied == 1 and r.status == "ok"


def test_locked_file_copied_through_snapshot_session(env):
    """VSS path with a fake snapshot provider (real VSS needs admin: see MANUAL_TESTS.md)."""
    p = env.write("busy.db", b"database pages")

    class FakeSession:
        def open(self, path):
            st = os.stat(path)
            return st.st_size, st.st_mtime_ns, iter([open(path, "rb").read()])

        def close(self):
            pass

    real = copier.file_chunks

    def locked(path):
        if path.endswith("busy.db"):
            e = PermissionError(13, "sharing violation")
            e.winerror = 32
            raise engmod.SourceReadError(e)
        yield from real(path)

    import vaultmove.core.engine as E
    orig = E.file_chunks
    E.file_chunks = locked
    try:
        r = env.run(vss_factory=lambda roots: FakeSession(), manual=True)
    finally:
        E.file_chunks = orig
    assert r.stats.locked == 1 and r.stats.locked_copied == 1, env.logs
    assert r.status == "ok"
    idx = env.index()
    assert idx.current_copy(env.sid, "busy.db").sha256 == sha(b"database pages")
    idx.close()


def test_scheduled_run_never_starts_vss(env):
    env.write("x.txt", b"1")
    called = []
    e = env.engine(vss_factory=lambda roots: called.append(1), manual=False)
    e._copy_locked(engmod.RunResult(), None, env.vault, [(env.cfg.sources[0], "x.txt", None)])
    assert called == []


def test_vault_full_by_free_space_check(env, monkeypatch):
    p = env.write("big.bin", b"x" * 1000, age_days=100)
    env.arm_offload(days=30)

    class U:
        free = 1024
        total = 10 ** 9
        used = 0

    monkeypatch.setattr(engmod.shutil, "disk_usage", lambda p: U)
    r = env.run()
    assert r.status == "error" and "space" in r.error
    assert os.path.exists(p)


def test_vault_full_during_write(env, monkeypatch):
    for i in range(3):
        env.write(f"f{i}.bin", os.urandom(10_000), age_days=100)
    env.arm_offload(days=30)
    real = copier.write_verified_tmp
    calls = {"n": 0}

    def full(chunks, final, mtime, **kw):
        calls["n"] += 1
        if calls["n"] >= 2:
            def hook(c):
                raise OSError(errno.ENOSPC, "No space left on device")
            kw["write_hook"] = hook
        return real(chunks, final, mtime, **kw)

    monkeypatch.setattr(engmod, "write_verified_tmp", full)
    r = env.run()
    assert r.status == "error" and "full" in r.error
    assert r.stats.offloaded == 0
    assert all(os.path.exists(env.path(f"f{i}.bin")) for i in range(3))
    assert not [x for x in env.vault_files() if x.endswith(".vmtmp")]
    monkeypatch.setattr(engmod, "write_verified_tmp", real)
    r = env.run()
    assert r.status == "ok" and r.stats.copied == 2
    assert_consistent(env)


def test_vault_unplugged_mid_run(env, monkeypatch):
    for i in range(10):
        env.write(f"f{i}.bin", os.urandom(2000), age_days=100)
    env.arm_offload(days=30)
    real = copier.write_verified_tmp
    calls = {"n": 0}

    def unplug(chunks, final, mtime, **kw):
        calls["n"] += 1
        if calls["n"] > 4:
            monkeypatch.setattr(vault, "read_marker", lambda root: None)  # drive gone
            raise VaultWriteError(OSError(21, "The device is not ready"))
        return real(chunks, final, mtime, **kw)

    real_marker = vault.read_marker
    monkeypatch.setattr(engmod, "write_verified_tmp", unplug)
    r = env.run()
    assert r.status == "not_connected"
    assert r.stats.offloaded == 0
    assert all(os.path.exists(env.path(f"f{i}.bin")) for i in range(10))
    # Replug.
    monkeypatch.setattr(vault, "read_marker", real_marker)
    monkeypatch.setattr(engmod, "write_verified_tmp", real)
    r = env.run()
    assert r.status == "ok"
    assert_consistent(env)
    idx = env.index()
    assert idx.stats()["files"] == 10
    idx.close()


def test_two_instances_racing(env):
    env.write("a.txt", b"x")
    with vault.VaultLock(env.vault):
        r = env.run()
        assert r.status == "busy"
    assert env.run().status == "ok"


def test_two_threads_racing(env):
    for i in range(200):
        env.write(f"d/f{i}.bin", os.urandom(4000))
    results = []
    barrier = threading.Barrier(2)

    def go():
        barrier.wait()
        results.append(env.run().status)

    ts = [threading.Thread(target=go) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(120)
    assert sorted(results) in (["busy", "ok"], ["ok", "ok"])
    assert_consistent(env)


def test_clock_set_backwards_keeps_young_files(env):
    p = env.write("f.txt", b"x", age_days=5)
    env.arm_offload(days=3)
    past = time.time() - 30 * DAY  # clock reset to a month ago: file looks like it's from the future
    env.run(now=lambda: past)
    r = env.run(now=lambda: past + 60)
    assert os.path.exists(p)
    assert r.status == "ok"


def test_cancel_mid_run_is_clean(env):
    for i in range(50):
        env.write(f"f{i}.bin", os.urandom(2000))
    ev = threading.Event()
    n = {"c": 0}

    def prog(d):
        n["c"] += 1
        if n["c"] > 3:
            ev.set()

    r = env.engine(cancel=ev, progress=prog).run()
    assert r.status == "cancelled"
    assert_consistent(env)
    r = env.run()
    assert r.status == "ok"
    idx = env.index()
    assert idx.stats()["files"] == 50
    idx.close()
