"""Invariants 4 (vault identity / same-drive refusal) and 5 (locate by volume, never write to C:)."""

import os

import pytest

from tests.helpers import Env
from vaultmove.core import fsutil, vault, winapi
from vaultmove.core.config import SourceCfg, make_source_id
from vaultmove.core.errors import VaultInvalid


def test_marker_has_random_uuid(tmp_path):
    a = vault.create_vault(str(tmp_path / "v1"))
    b = vault.create_vault(str(tmp_path / "v2"))
    assert a != b and len(a) == 36
    assert vault.read_marker(str(tmp_path / "v1"))["uuid"] == a


def test_refuse_non_empty_folder_without_marker(tmp_path):
    d = tmp_path / "stuff"
    d.mkdir()
    (d / "family_photo.jpg").write_bytes(b"x")
    assert vault.inspect_destination(str(d)) == "not_empty"
    with pytest.raises(VaultInvalid):
        vault.create_vault(str(d))
    assert sorted(os.listdir(d)) == ["family_photo.jpg"]


def test_existing_vault_is_adopted(tmp_path):
    a = vault.create_vault(str(tmp_path / "v"))
    assert vault.create_vault(str(tmp_path / "v")) == a


def test_refuse_missing_destination(env):
    env.write("a.txt", b"x")
    os.rename(env.vault, env.vault + "-unplugged")
    r = env.run()
    assert r.status == "not_connected"
    assert not os.path.exists(env.vault), "nothing may be created in place of a missing vault"


def test_refuse_wrong_uuid(env):
    env.write("a.txt", b"x")
    env.cfg.vault.uuid = "00000000-0000-0000-0000-000000000000"
    r = env.run()
    assert r.status == "not_connected"
    assert not os.path.exists(os.path.join(env.vault, "data", env.sid))


def test_refuse_override_folder_that_is_another_vault(env, tmp_path):
    other = str(tmp_path / "other")
    vault.create_vault(other)
    r = env.run(vault_root=other)
    assert r.status == "refused"


@pytest.mark.skipif(not winapi.IS_WIN, reason="Windows volume APIs")
def test_same_physical_drive_refused_with_real_detection(env):
    """Temp source and temp vault really are on the same disk here."""
    env.write("a.txt", b"x")
    r = env.run(same_disk_fn=winapi.same_physical_disk)
    assert r.status == "refused"
    assert "same physical disk" in r.error
    env.cfg.vault.allow_same_drive = True
    r = env.run(same_disk_fn=winapi.same_physical_disk)
    assert r.status == "ok"
    assert any("same physical disk" in m for m in r.messages)


def test_vault_inside_source_refused(env):
    inner = os.path.join(env.src, "MyVault")
    vid = vault.create_vault(inner)
    env.cfg.vault = vault.vault_cfg_for(inner, vid)
    r = env.run()
    assert r.status == "refused"


def test_source_inside_vault_refused(env):
    inside = os.path.join(env.vault, "data", "sneaky")
    os.makedirs(inside)
    env.cfg.sources.append(SourceCfg(path=inside, id=make_source_id(inside)))
    r = env.run()
    assert r.status == "refused"


@pytest.mark.skipif(not winapi.IS_WIN, reason="Windows volume APIs")
def test_vault_cfg_records_volume_identity(env):
    v = env.cfg.vault
    assert v.volume_guid.startswith("\\\\?\\Volume{")
    assert v.volume_serial is not None
    assert v.rel_path and not v.rel_path.startswith("\\")


@pytest.mark.skipif(not winapi.IS_WIN, reason="Windows volume APIs")
def test_locate_by_volume_not_by_stale_path(env):
    env.cfg.vault.path = "Z:\\Nowhere\\VaultMove"  # stale drive letter
    assert fsutil.normroot(vault.locate_vault(env.cfg.vault)).lower() == env.vault.lower()


@pytest.mark.skipif(not winapi.IS_WIN, reason="Windows volume APIs")
def test_locate_returns_none_for_unknown_volume(env):
    env.cfg.vault.volume_guid = "\\\\?\\Volume{00000000-0000-0000-0000-000000000000}\\"
    env.cfg.vault.volume_serial = 1
    assert vault.locate_vault(env.cfg.vault) is None
    r = env.run()
    assert r.status == "not_connected"


def test_unplugged_source_folder_is_skipped_not_marked_deleted(env):
    env.write("a.txt", b"x")
    env.run()
    os.rename(env.src, env.src + "-gone")
    r = env.run()
    assert r.stats.sources_unavailable == 1
    idx = env.index()
    assert idx.current_copy(env.sid, "a.txt").gone_at is None
    idx.close()
