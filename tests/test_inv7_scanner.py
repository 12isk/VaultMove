"""Invariant 7: never touch system folders / the vault / excludes; no link following;
long paths, Unicode, emoji and reserved names."""

import os
import subprocess

import pytest

from tests.helpers import sha, sha_file
from vaultmove.core import fsutil, winapi
from vaultmove.core.excludes import Matcher
from vaultmove.core.restore import restore_many
from vaultmove.core.scanner import walk


def _rels(root, patterns=()):
    return sorted(e.rel.replace("\\", "/") for e in walk(root, Matcher(patterns), []))


def test_exclude_globs(tmp_path):
    root = str(tmp_path)
    for rel in ["a.txt", "b.tmp", "node_modules/x.js", "Proj/build/out.o", "Proj/src/main.c",
                "deep/x/cache/c.bin", "~$doc.docx", "Thumbs.db"]:
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, "wb").close()
    got = _rels(root, ["*.tmp", "node_modules", "proj/build/**", "**/cache/*.bin", "~$*", "thumbs.db"])
    assert got == ["Proj/src/main.c", "a.txt"]


def test_protected_folder_inside_source_is_skipped(tmp_path, monkeypatch):
    root = str(tmp_path)
    fake_windows = os.path.join(root, "Windows")
    os.makedirs(fake_windows)
    open(os.path.join(fake_windows, "kernel.dll"), "wb").close()
    open(os.path.join(root, "mine.txt"), "wb").close()
    monkeypatch.setenv("SystemRoot", fake_windows)
    assert _rels(root) == ["mine.txt"]


def test_recycle_bin_and_svi_names_skipped(tmp_path):
    root = str(tmp_path)
    for d in ("$RECYCLE.BIN", "System Volume Information"):
        os.makedirs(os.path.join(root, d))
        open(os.path.join(root, d, "x"), "wb").close()
    assert _rels(root) == []


def test_vault_inside_tree_is_skipped(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "v"))
    open(os.path.join(root, "v", "copy.bin"), "wb").close()
    open(os.path.join(root, "real.txt"), "wb").close()
    got = sorted(e.rel for e in walk(root, Matcher([]), [os.path.join(root, "v")]))
    assert got == ["real.txt"]


@pytest.mark.skipif(not winapi.IS_WIN, reason="junctions are Windows-only")
def test_junctions_and_loops_are_not_followed(tmp_path):
    import _winapi
    root = str(tmp_path / "src")
    outside = str(tmp_path / "outside")
    os.makedirs(os.path.join(root, "sub"))
    os.makedirs(outside)
    open(os.path.join(outside, "secret.txt"), "wb").close()
    open(os.path.join(root, "sub", "f.txt"), "wb").close()
    _winapi.CreateJunction(outside, os.path.join(root, "escape"))
    _winapi.CreateJunction(root, os.path.join(root, "sub", "loop"))  # loop back to the root
    assert _rels(root) == ["sub/f.txt"]


def test_symlink_not_followed(tmp_path):
    root = str(tmp_path / "src")
    os.makedirs(root)
    target = tmp_path / "t.txt"
    target.write_bytes(b"x")
    try:
        os.symlink(str(target), os.path.join(root, "link.txt"))
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted (needs Developer Mode on Windows)")
    assert _rels(root) == []


def test_long_paths_over_260(env, tmp_path):
    rel = os.path.join(*(["d" * 50] * 7), "long_file_name_" + "x" * 40 + ".txt")
    full = env.path(rel)
    assert len(full) > 300
    env.write(rel, b"deep content")
    r = env.run()
    assert r.status == "ok" and r.stats.copied == 1
    idx = env.index()
    c = idx.current_copy(env.sid, rel)
    assert sha_file(os.path.join(env.vault, c.vault_rel)) == sha(b"deep content")
    os.remove(fsutil.lp(full))
    res = restore_many(idx, env.vault, [c], dest_root=None)
    idx.close()
    assert res.restored and not res.failed
    assert sha_file(full) == sha(b"deep content")


def test_unicode_and_emoji_names(env):
    names = ["résumé.docx", "日本語/ファイル.txt", "emoji_😀🎉.txt", "Ελληνικά.md", "mixed Ünï 𝔘.txt"]
    for n in names:
        env.write(n, n.encode("utf-8"))
    r = env.run()
    assert r.stats.copied == len(names)
    idx = env.index()
    for n in names:
        c = idx.current_copy(env.sid, n.replace("/", os.sep))
        assert c is not None, n
        assert sha_file(os.path.join(env.vault, c.vault_rel)) == sha(n.encode("utf-8"))
    idx.close()


@pytest.mark.skipif(not winapi.IS_WIN, reason="reserved names are a Windows concept")
def test_reserved_and_odd_names(env):
    # These can only be created through \\?\ paths; Explorer can't even delete them.
    odd = ["CON.txt", "nul", "aux.log", "trailing.dot.", "trailing space "]
    for n in odd:
        env.write(n, n.encode())
    r = env.run()
    assert r.stats.copied == len(odd), env.logs
    idx = env.index()
    for n in odd:
        c = idx.current_copy(env.sid, n)
        assert c is not None, n
        assert sha_file(os.path.join(env.vault, c.vault_rel)) == sha(n.encode())
    idx.close()


def test_case_only_rename_is_a_new_state_of_same_file(env):
    p = env.write("Report.TXT", b"x")
    env.run()
    os.rename(p, env.path("report.txt"))
    with open(env.path("report.txt"), "ab") as f:
        f.write(b"y")
    r = env.run()
    assert r.status == "ok"
    idx = env.index()
    cs = idx.copies_of(env.sid, "report.txt")
    idx.close()
    assert len(cs) == 2 and cs[0].rel_path == "report.txt"
