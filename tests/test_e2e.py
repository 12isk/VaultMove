"""End-to-end on temp folders: backup, modify, version, offload, restore, hash-compare."""

import os
import time

from tests.helpers import DAY, sha, sha_file
from vaultmove.core import fsutil
from vaultmove.core.restore import restore_many


def test_full_cycle(env, tmp_path):
    a = env.write("notes/a.txt", b"version one", age_days=90)
    env.write("photos/p.jpg", os.urandom(300_000), age_days=90)
    env.write("new.txt", b"fresh")

    r1 = env.run()
    assert r1.status == "ok", r1.error
    assert r1.stats.copied == 3

    # Unchanged second run: nothing copied.
    r2 = env.run()
    assert r2.stats.copied == 0 and r2.stats.unchanged == 3

    # Modify -> new version, old one kept in _versions.
    with open(a, "wb") as f:
        f.write(b"version two, longer")
    t = time.time() - 60 * DAY
    os.utime(a, (t, t))
    r3 = env.run()
    assert r3.stats.copied == 1 and r3.stats.versioned == 1
    idx = env.index()
    copies = idx.copies_of(env.sid, "notes/a.txt".replace("/", os.sep))
    assert [c.sha256 for c in copies] == [sha(b"version two, longer"), sha(b"version one")]
    old = copies[1]
    assert old.vault_rel.startswith("_versions")
    assert sha_file(os.path.join(env.vault, old.vault_rel)) == sha(b"version one")
    idx.close()

    # Offload (armed): the two 90/60-day-old files are freed, the fresh one stays.
    env.arm_offload(days=30)
    r4 = env.run()
    assert r4.stats.offloaded == 2, env.logs
    assert not os.path.exists(a)
    assert os.path.exists(env.path("new.txt"))

    # Restore the offloaded file to its original place; hash must match.
    idx = env.index()
    cur = idx.current_copy(env.sid, "notes" + os.sep + "a.txt")
    assert cur.offloaded_at is not None
    res = restore_many(idx, env.vault, [cur], dest_root=None)
    assert res.restored and not res.failed
    assert sha_file(a) == sha(b"version two, longer")
    # Restored file is not immediately offloaded again.
    idx.close()
    r5 = env.run()
    assert os.path.exists(a)
    assert r5.stats.offloaded == 0

    # Restore the older version into another folder.
    idx = env.index()
    old = idx.copies_of(env.sid, "notes" + os.sep + "a.txt")[1]
    dest = str(tmp_path / "restore_here")
    res = restore_many(idx, env.vault, [old], dest_root=dest, base_key="notes")
    assert not res.failed
    assert sha_file(os.path.join(dest, "a.txt")) == sha(b"version one")

    # "Everything as of" the first run.
    t1 = r1.finished_at + 0.001
    all_then = list(idx.copies_asof(t1))
    assert len(all_then) == 3
    dest2 = str(tmp_path / "asof")
    res = restore_many(idx, env.vault, all_then, dest_root=dest2)
    assert len(res.restored) == 3
    assert sha_file(os.path.join(dest2, "notes", "a.txt")) == sha(b"version one")
    idx.close()


def test_restore_never_overwrites(env):
    p = env.write("doc.txt", b"original")
    env.run()
    with open(p, "wb") as f:
        f.write(b"local edit not yet backed up")
    idx = env.index()
    cur = idx.current_copy(env.sid, "doc.txt")
    res = restore_many(idx, env.vault, [cur], dest_root=None)
    idx.close()
    assert res.restored
    target = res.restored[0][1]
    assert target.endswith("doc.restored.txt")
    with open(p, "rb") as f:
        assert f.read() == b"local edit not yet backed up"
    assert sha_file(target) == sha(b"original")
