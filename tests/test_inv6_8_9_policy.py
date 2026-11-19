"""Invariants 6 (offload off by default, confirmed + previewed), 8 (Recycle Bin), 9 (log)."""

import json
import os
import sqlite3
import time

import pytest

from tests.helpers import DAY
from vaultmove.core import offload, winapi
from vaultmove.core.config import Config


def test_offload_off_by_default():
    c = Config()
    assert c.offload.enabled is False
    assert c.offload_armed() is False


@pytest.mark.parametrize("confirmed,previewed", [(False, False), (True, False), (False, True)])
def test_offload_needs_confirmation_and_preview(env, confirmed, previewed):
    p = env.write("old.txt", b"data", age_days=100)
    env.cfg.offload.enabled = True
    env.cfg.offload.after_days = 30
    env.cfg.offload.confirmed_at = time.time() if confirmed else None
    env.cfg.offload.preview_done_at = time.time() if previewed else None
    env.run()
    env.run()
    assert os.path.exists(p)


def test_preview_lists_exactly_what_the_run_deletes(env):
    keep = env.write("young.txt", b"y", age_days=1)
    old1 = env.write("a/old1.txt", b"o1", age_days=100)
    old2 = env.write("old2.txt", b"o2" * 50, age_days=100)
    env.run()
    new = env.write("brand_new.txt", b"n", age_days=200)
    env.cfg.offload.enabled = True
    env.cfg.offload.after_days = 30
    env.cfg.offload.recycle = "off"
    prev = env.run(dry_run=True)
    assert prev.status == "ok"
    deletes = sorted(i.path for i in prev.plan.items if i.action == "delete")
    copies = sorted(i.path for i in prev.plan.items if i.action == "copy")
    eligible = sorted(i.path for i in prev.plan.items if i.action == "eligible")
    assert deletes == sorted([old1, old2])
    assert copies == [new]
    assert eligible == [new]
    n, b = prev.plan.total("delete")
    assert n == 2 and b == 2 + 100
    # The dry run itself changed nothing.
    assert all(os.path.exists(p) for p in (keep, old1, old2, new))
    # Arm and run: exactly the previewed files go.
    env.arm_offload(days=30)
    r = env.run()
    gone = sorted(p for p in (keep, old1, old2, new) if not os.path.exists(p))
    assert gone == deletes


def test_preview_on_a_new_vault_copies_everything(env):
    env.write("a.txt", b"1", age_days=100)
    env.write("b.txt", b"22")
    env.cfg.offload.enabled = True
    r = env.engine().preview_new_vault()
    assert r.plan.total("copy") == (2, 3)
    assert r.plan.total("delete") == (0, 0)
    assert r.plan.total("eligible")[0] == 1


def test_recycle_default_on_during_first_7_days():
    c = Config()
    now = time.time()
    c.first_use_at = now - 2 * DAY
    assert c.recycle_effective(now) is True
    c.first_use_at = now - 8 * DAY
    assert c.recycle_effective(now) is False
    c.offload.recycle = "on"
    assert c.recycle_effective(now) is True
    c.offload.recycle = "off"
    c.first_use_at = now
    assert c.recycle_effective(now) is False


def test_offload_uses_recycle_bin_when_enabled(env, monkeypatch):
    p = env.write("old.txt", b"data", age_days=100)
    sent = []

    def fake_recycle(path):
        sent.append(path)
        os.remove(path)

    monkeypatch.setattr(winapi, "send_to_recycle_bin", fake_recycle)
    env.run()
    env.arm_offload(days=30, recycle="auto")  # first_use_at is now -> recycle on
    r = env.run()
    assert sent == [p]
    assert r.stats.offloaded == 1
    idx = env.index()
    ev = [json.loads(d) for ts, k, d in idx.events_for(env.sid, "old.txt") if k == "offload"]
    idx.close()
    assert ev and ev[0]["method"] == "recycle"


def test_recycle_failure_keeps_original(env, monkeypatch):
    p = env.write("old.txt", b"data", age_days=100)

    def broken(path):
        raise OSError("recycle bin unavailable")

    monkeypatch.setattr(winapi, "send_to_recycle_bin", broken)
    env.run()
    env.arm_offload(days=30, recycle="on")
    r = env.run()
    assert os.path.exists(p)
    assert r.stats.offloaded == 0
    idx = env.index()
    assert idx.list_pending() == []
    idx.close()


@pytest.mark.skipif(os.environ.get("VAULTMOVE_REAL_RECYCLE") != "1", reason="touches the real Recycle Bin (CI only)")
def test_real_recycle_bin(tmp_path):
    p = tmp_path / "vaultmove-recycle-test.txt"
    p.write_bytes(b"recycle me")
    winapi.send_to_recycle_bin(str(p))
    assert not p.exists()


def test_every_copy_version_and_delete_is_logged(env):
    p = env.write("f.txt", b"v1", age_days=100)
    env.run()
    with open(p, "wb") as f:
        f.write(b"v2 longer")
    t = time.time() - 100 * DAY
    os.utime(p, (t, t))
    env.run()
    env.arm_offload(days=30)
    env.run()
    assert not os.path.exists(p)
    idx = env.index()
    kinds = [k for ts, k, d in idx.events_for(env.sid, "f.txt")]
    idx.close()
    assert kinds.count("copy") == 2
    assert "version" in kinds and "offload" in kinds
    lines = []
    for name in os.listdir(os.path.join(env.vault, "log")):
        with open(os.path.join(env.vault, "log", name), encoding="utf-8") as f:
            lines += [json.loads(x) for x in f if x.strip()]
    off = [x for x in lines if x["kind"] == "offload"]
    assert off and off[0]["path"] == "f.txt"
    assert off[0]["detail"]["vault"].startswith("data")  # "where did my file go?"


def test_events_are_append_only(env):
    env.write("f.txt", b"x")
    env.run()
    idx = env.index()
    with pytest.raises(sqlite3.DatabaseError):
        idx.db.execute("UPDATE events SET kind='x'")
    with pytest.raises(sqlite3.DatabaseError):
        idx.db.execute("DELETE FROM events")
    idx.close()
