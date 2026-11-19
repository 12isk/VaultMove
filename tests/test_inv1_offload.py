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


def test_onedrive_folder_is_backed_up_but_never_offloaded(env, monkeypatch):
    """Regression: files in a OneDrive folder without placeholder attributes were freed,
    which also deletes them in the cloud. Registered sync folders are now off-limits."""
    p = env.write("Desktop shortcut.lnk", b"lnk", age_days=100)
    monkeypatch.setenv("OneDrive", env.src)
    env.arm_offload(days=30)
    r1 = env.run()
    assert r1.stats.copied == 1
    prev = env.run(dry_run=True)
    assert prev.plan.total("delete") == (0, 0)
    assert any("cloud" in m for m in prev.messages)
    env.run()
    env.run()
    assert os.path.exists(p)
    idx = env.index()
    assert idx.current_copy(env.sid, "Desktop shortcut.lnk").offloaded_at is None
    idx.close()


def test_registered_sync_root_parent_blocks_offload(env, monkeypatch):
    p = env.write("photo.jpg", b"jpg", age_days=100)
    parent = os.path.dirname(env.src)  # e.g. a Dropbox/Google Drive root above the source
    monkeypatch.setattr(fsutil, "cloud_sync_roots", lambda: [parent])
    env.arm_offload(days=30)
    env.run()
    env.run()
    assert os.path.exists(p)


def _onedrive_folders():
    home = os.path.expanduser("~")
    out = []
    try:
        for n in os.listdir(home):
            p = os.path.join(home, n)
            if n.lower().startswith("onedrive") and os.path.isdir(p):
                out.append(p)
    except OSError:
        pass
    return out


@pytest.mark.skipif(not _onedrive_folders(), reason="no OneDrive folder on this machine")
def test_real_onedrive_folders_are_detected_even_without_the_env_var(monkeypatch):
    """Regression: a OneDrive folder whose account is signed out is not in the registry and
    Windows disguises its placeholders; it must still be detected (via the exposed cloud tags)."""
    for v in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(fsutil, "cloud_sync_roots", lambda: [])
    for od in _onedrive_folders():
        if fsutil._has_cloud_tag(od):  # an actual sync root (not just a folder named OneDrive)
            sub = [os.path.join(od, n) for n in os.listdir(od) if os.path.isdir(os.path.join(od, n))]
            assert fsutil.in_cloud_sync(os.path.join(od, "x.lnk"))
            for s in sub[:3]:
                assert fsutil.in_cloud_sync(os.path.join(s, "x.lnk")), s
    assert not fsutil.in_cloud_sync(os.path.join(os.environ.get("SystemDrive", "C:") + "\\", "NotCloud", "x"))


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


# ---------------------------------------------------------------- opt-in: free space in cloud folders


def test_offload_cloud_is_off_by_default_and_old_settings_load():
    from vaultmove.core.config import Config, config_from_dict
    assert Config().offload_cloud is False
    assert config_from_dict({"schedule_minutes": 60}).offload_cloud is False   # 1.1.0 file without the key


def test_cloud_folder_is_freed_when_opted_in(env, monkeypatch):
    p = env.write("Desktop shortcut.lnk", b"lnk" * 100, age_days=100)
    h = sha_file(p)
    monkeypatch.setenv("OneDrive", env.src)
    env.cfg.offload_cloud = True
    env.arm_offload(days=30)
    r1 = env.run()
    assert r1.stats.copied == 1 and r1.stats.offloaded == 0   # never in the run that made the copy
    assert os.path.exists(p)
    r2 = env.run()
    assert r2.stats.offloaded == 1
    assert not os.path.exists(p)
    idx = env.index()
    c = idx.current_copy(env.sid, "Desktop shortcut.lnk")
    assert c.offloaded_at and c.sha256 == h
    assert sha_file(os.path.join(env.vault, c.vault_rel)) == h
    idx.close()


def test_cloud_folder_not_freed_with_default_setting(env, monkeypatch):
    p = env.write("photo.jpg", b"jpg", age_days=100)
    monkeypatch.setenv("OneDrive", env.src)
    assert env.cfg.offload_cloud is False
    env.arm_offload(days=30)
    _two_runs(env)
    env.run()
    assert os.path.exists(p)


def test_online_only_file_is_never_freed_even_when_opted_in(env, monkeypatch):
    from vaultmove.core import offload
    p = env.write("big.mov", b"m" * 5000, age_days=100)
    monkeypatch.setenv("OneDrive", env.src)
    env.cfg.offload_cloud = True
    env.arm_offload(days=30)
    assert env.run().stats.copied == 1
    # The file becomes online-only (OneDrive "Free up space") after it was backed up.
    monkeypatch.setattr(fsutil, "is_online_only", lambda st: True)
    prev = env.run(dry_run=True)
    assert prev.plan.total("delete") == (0, 0)
    r = env.run()
    assert r.stats.offloaded == 0
    assert os.path.exists(p)
    idx = env.index()
    c = idx.current_copy(env.sid, "big.mov")
    assert c.offloaded_at is None
    idx.close()
    # And the check itself refuses it, independent of the scanner.
    d = offload.check_source_state(p, c, 30, time.time(), allow_cloud=True)
    assert not d.ok and "online-only" in d.reason


def test_preview_lists_cloud_file_for_delete_only_when_opted_in(env, monkeypatch):
    p = env.write("notes.txt", b"notes", age_days=100)
    monkeypatch.setenv("OneDrive", env.src)
    env.arm_offload(days=30)
    env.run()
    off = env.run(dry_run=True)
    assert off.plan.total("delete") == (0, 0)
    assert any("cloud" in m for m in off.messages)
    env.cfg.offload_cloud = True
    on = env.run(dry_run=True)
    assert [i.path for i in on.plan.items if i.action == "delete"] == [p]
    assert not any("cloud" in m for m in on.messages)


def test_new_vault_preview_marks_cloud_files_eligible_only_when_opted_in(env, monkeypatch):
    p = env.write("old.txt", b"old", age_days=100)
    monkeypatch.setenv("OneDrive", env.src)
    env.arm_offload(days=30)
    off = env.engine().preview_new_vault()
    assert not [i for i in off.plan.items if i.action == "eligible"]
    env.cfg.offload_cloud = True
    on = env.engine().preview_new_vault()
    assert [i.path for i in on.plan.items if i.action == "eligible"] == [p]
