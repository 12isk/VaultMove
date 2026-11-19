"""Invariant 2 (atomic verified copies) and 3 (changed files are versioned, never overwritten)."""

import os
import time

import pytest

from tests.helpers import DAY, sha, sha_file
from vaultmove.core import copier, fsutil
from vaultmove.core.errors import VaultWriteError, VerifyFailed


def test_tmp_removed_when_write_fails(tmp_path):
    final = str(tmp_path / "out.bin")

    def boom(chunk):
        raise OSError(5, "I/O error")

    with pytest.raises(VaultWriteError):
        copier.write_verified_tmp(iter([b"abc"]), final, None, write_hook=boom)
    assert not os.path.exists(final + ".vmtmp")
    assert not os.path.exists(final)


def test_tmp_removed_when_readback_differs(tmp_path, monkeypatch):
    final = str(tmp_path / "out.bin")
    monkeypatch.setattr(copier, "hash_file", lambda p, cancel=None: ("0" * 64, 3))
    with pytest.raises(VerifyFailed):
        copier.write_verified_tmp(iter([b"abc"]), final, None)
    assert not os.path.exists(final + ".vmtmp")


def test_place_refuses_to_overwrite(tmp_path):
    final = str(tmp_path / "out.bin")
    tmp, _, _ = copier.write_verified_tmp(iter([b"new"]), final, None)
    with open(final, "wb") as f:
        f.write(b"existing")
    with pytest.raises(VaultWriteError):
        copier.place(tmp, final)
    with open(final, "rb") as f:
        assert f.read() == b"existing"


def test_vault_never_contains_tmp_after_success(env):
    for i in range(20):
        env.write(f"d/f{i}.txt", os.urandom(1000))
    env.run()
    assert not [p for p in env.vault_files() if p.endswith(".vmtmp")]


def test_vmtmp_files_in_source_are_ignored(env):
    env.write("a.txt.vmtmp", b"half written")
    r = env.run()
    assert r.stats.scanned == 0


def test_changed_file_moves_old_copy_to_versions(env):
    p = env.write("report.txt", b"v1")
    env.run()
    for content in (b"v2-longer", b"v3-even-longer"):
        time.sleep(0.01)
        with open(p, "wb") as f:
            f.write(content)
        env.run()
    idx = env.index()
    copies = idx.copies_of(env.sid, "report.txt")
    idx.close()
    assert [c.sha256 for c in copies] == [sha(b"v3-even-longer"), sha(b"v2-longer"), sha(b"v1")]
    for c in copies:
        assert sha_file(os.path.join(env.vault, c.vault_rel)) == c.sha256
    assert copies[0].vault_rel.startswith("data")
    assert all(c.vault_rel.startswith("_versions") for c in copies[1:])


def test_same_size_change_detected_by_hash(env):
    p = env.write("same.txt", b"AAAA")
    env.run()
    with open(p, "wb") as f:
        f.write(b"BBBB")
    t = time.time() + 5
    os.utime(p, (t, t))
    r = env.run()
    assert r.stats.copied == 1 and r.stats.versioned == 1


def test_touch_without_change_only_updates_metadata(env):
    p = env.write("same.txt", b"AAAA")
    env.run()
    t = time.time() - 3 * DAY
    os.utime(p, (t, t))
    r = env.run()
    assert r.stats.copied == 0 and r.stats.metadata_updated == 1


def test_clock_going_backwards_never_overwrites_versions(env):
    """Two runs with the same timestamp (clock reset) must not collide in _versions."""
    p = env.write("f.txt", b"one")
    fixed = time.time()
    env.run(now=lambda: fixed)
    for content in (b"two!", b"three"):
        with open(p, "wb") as f:
            f.write(content)
        env.run(now=lambda: fixed)
    idx = env.index()
    copies = idx.copies_of(env.sid, "f.txt")
    idx.close()
    assert len(copies) == 3
    rels = {c.vault_rel for c in copies}
    assert len(rels) == 3
    for c in copies:
        assert sha_file(os.path.join(env.vault, c.vault_rel)) == c.sha256


def test_untracked_file_in_vault_is_kept_not_overwritten(env):
    """A vault file the index doesn't know (crash before commit) is versioned, not overwritten."""
    env.write("x.txt", b"new content")
    target = os.path.join(env.vault, "data", env.sid, "x.txt")
    os.makedirs(os.path.dirname(target))
    with open(target, "wb") as f:
        f.write(b"orphan from an earlier crash")
    env.run()
    idx = env.index()
    copies = idx.copies_of(env.sid, "x.txt")
    idx.close()
    assert {c.sha256 for c in copies} == {sha(b"new content"), sha(b"orphan from an earlier crash")}
