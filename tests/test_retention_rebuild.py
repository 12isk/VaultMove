"""Version thinning, manual pruning, index rebuild."""

import os
import time

from tests.helpers import DAY, sha, sha_file
from tests.test_crash import assert_consistent
from vaultmove.core import retention
from vaultmove.core.engine import delete_old_versions
from vaultmove.core.rebuild import rebuild_index


def _fake_versions(idx, sid, ages_days, now):
    """Insert a current copy plus non-current versions ending `ages_days` ago."""
    cid = idx.insert_copy(sid, "f.txt", 1, 1, "c" * 64, "data/x/f.txt", now - 1)
    ids = []
    for i, a in enumerate(ages_days):
        t = now - a * DAY
        ids.append(idx.insert_copy(sid, "f.txt", 1, 1, f"{i:064d}", f"_versions/{i}/f.txt", t - 10,
                                   is_current=False, valid_to=t))
    idx.commit()
    return cid, ids


def test_thinning_schedule(env):
    now = time.time()
    idx = env.index()
    # 3 in the last day, 2 on the same day 10 days ago, 2 in the same week 100 days ago.
    ages = [0.1, 0.2, 0.3, 10.00, 10.01, 100.0, 100.5]
    cid, ids = _fake_versions(idx, env.sid, ages, now)
    doomed = {c.id for c in retention.plan_prune(idx, lambda s: None, True, now)}
    idx.close()
    assert ids[0] not in doomed and ids[1] not in doomed and ids[2] not in doomed  # all < 24 h kept
    assert len(doomed & {ids[3], ids[4]}) == 1        # one per day
    assert len(doomed & {ids[5], ids[6]}) == 1        # one per week
    assert cid not in doomed


def test_latest_copy_is_never_pruned(env):
    p = env.write("f.txt", b"1", age_days=100)
    env.run()
    env.arm_offload(days=30)
    env.run()
    assert not os.path.exists(p)
    env.cfg.keep_versions_days = 0
    env.run()
    n, _ = delete_old_versions(env.cfg, older_than_days=0, vault_root=env.vault)
    idx = env.index()
    cur = idx.current_copy(env.sid, "f.txt")
    idx.close()
    assert cur is not None and cur.pruned_at is None
    assert sha_file(os.path.join(env.vault, cur.vault_rel)) == sha(b"1")


def test_manual_delete_old_versions(env):
    p = env.write("f.txt", b"1")
    env.run()
    for c in (b"22", b"333"):
        with open(p, "wb") as f:
            f.write(c)
        env.run()
    n, b = delete_old_versions(env.cfg, older_than_days=-1, vault_root=env.vault)
    assert n == 2 and b == 3
    assert_consistent(env)
    idx = env.index()
    assert [c.sha256 for c in idx.copies_of(env.sid, "f.txt")] == [sha(b"333")]
    idx.close()


def test_rebuild_index_from_vault(env):
    a = env.write("a.txt", b"one", age_days=100)
    env.write("sub/b.txt", b"bee")
    env.run()
    with open(env.path("sub/b.txt"), "wb") as f:
        f.write(b"bee v2")
    env.run()
    env.arm_offload(days=30)
    env.run()
    assert not os.path.exists(a)
    os.remove(os.path.join(env.vault, "index.sqlite"))
    stats = rebuild_index(env.vault, log=lambda m: None)
    assert stats["current"] == 2 and stats["versions"] == 1 and stats["offloaded"] == 1
    idx = env.index()
    assert idx.current_copy(env.sid, "a.txt").offloaded_at is not None
    assert len(idx.copies_of(env.sid, os.path.join("sub", "b.txt"))) == 2
    assert idx.sources()[env.sid] == env.src
    idx.close()
    # And the engine keeps working on the rebuilt index.
    r = env.run()
    assert r.status == "ok" and r.stats.copied == 0
    assert_consistent(env)
