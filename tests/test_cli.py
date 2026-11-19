"""CLI harness smoke test (M2)."""

import os
import time

from tests.helpers import DAY, sha, sha_file
from vaultmove import cli
from vaultmove.core import config as cfgmod


def test_cli_round_trip(tmp_path, capsys, monkeypatch):
    src = tmp_path / "docs"
    src.mkdir()
    f = src / "old.txt"
    f.write_bytes(b"cli content")
    t = time.time() - 100 * DAY
    os.utime(f, (t, t))
    cdir = str(tmp_path / "cfg")
    base = ["--config-dir", cdir]
    assert cli.main(base + ["init-vault", str(tmp_path / "nodrive" / "VaultMove")]) == 1  # drive absent
    (tmp_path / "usb").mkdir()
    # Same disk in tests: explicit override (the CLI never assumes it).
    assert cli.main(base + ["init-vault", str(tmp_path / "usb" / "VaultMove"), "--allow-same-drive"]) == 0
    assert cli.main(base + ["add-source", str(src)]) == 0
    assert cli.main(base + ["backup"]) == 0
    out = capsys.readouterr().out
    assert "copied 1" in out
    assert cli.main(base + ["offload", "--enable", "--days", "30"]) == 2  # needs --i-understand
    assert cli.main(base + ["offload", "--enable", "--days", "30", "--i-understand"]) == 0
    assert cli.main(base + ["preview"]) == 0
    out = capsys.readouterr().out
    # Same physical disk -> preview must not promise deletions.
    assert "Will delete from this PC: 0 files" in out
    assert cli.main(base + ["status"]) == 0
    assert cli.main(base + ["search", "old"]) == 0
    assert "old.txt" in capsys.readouterr().out
    cfg = cfgmod.load(cdir)
    sid = cfg.sources[0].id
    assert cli.main(base + ["history", sid, "old.txt"]) == 0
    assert "copy" in capsys.readouterr().out
    dest = tmp_path / "out"
    assert cli.main(base + ["restore", sid, "old.txt", "--to", str(dest)]) == 0
    assert sha_file(str(dest / "old.txt")) == sha(b"cli content")
    assert cli.main(base + ["prune", "--older-than", "365"]) == 0
    assert cli.main(base + ["rebuild-index"]) == 0
