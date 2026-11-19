"""In-app updater: no network in tests (fetch/opener are injected)."""

import hashlib
import io
import json
import os
import threading

import pytest

from vaultmove import UPDATE_REPO
from vaultmove.core import update
from vaultmove.core.errors import Cancelled

PREFIX = f"https://github.com/{UPDATE_REPO}/releases/download/v9.9.9/"


def fake_release(extra_assets=()):
    assets = [{"name": n, "browser_download_url": PREFIX + n}
              for n in ("VaultMove-Setup-9.9.9.exe", "VaultMove-Portable-9.9.9.exe", "SHA256SUMS.txt")]
    assets += list(extra_assets)
    return json.dumps({"tag_name": "v9.9.9", "body": "Notes", "html_url": "https://github.com/x", "assets": assets}).encode()


def test_versions():
    assert update.parse_version("v1.10.2") == (1, 10, 2)
    assert update.is_newer("1.1.0", "1.0.9")
    assert update.is_newer("v2.0.0", "1.99.99")
    assert not update.is_newer("1.1.0", "1.1.0")
    assert not update.is_newer("1.0.0", "1.1.0")
    with pytest.raises(update.UpdateError):
        update.parse_version("latest")


def test_check_latest_keeps_only_this_repos_release_assets():
    evil = [{"name": "VaultMove-Setup-9.9.9b.exe", "browser_download_url": "https://evil.example/x.exe"},
            {"name": "../../x.exe", "browser_download_url": PREFIX + "../../x.exe"}]
    rel = update.check_latest(fetch=lambda url: fake_release(evil))
    assert rel.version == "9.9.9"
    assert set(rel.assets) == {"VaultMove-Setup-9.9.9.exe", "VaultMove-Portable-9.9.9.exe", "SHA256SUMS.txt"}
    assert rel.asset_for("installer")[0] == "VaultMove-Setup-9.9.9.exe"
    assert rel.asset_for("portable")[0] == "VaultMove-Portable-9.9.9.exe"
    assert rel.asset_for("source") is None


def test_check_latest_network_error_is_reported():
    def boom(url):
        raise OSError("no route to host")
    with pytest.raises(update.UpdateError):
        update.check_latest(fetch=boom)


def test_no_release_yet_is_explained():
    import urllib.error

    def not_found(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    with pytest.raises(update.UpdateError, match="no release has been published yet"):
        update.check_latest(fetch=not_found)


def test_expected_sha256():
    rel = update.check_latest(fetch=lambda url: fake_release())
    sums = ("a" * 64 + "  VaultMove-Setup-9.9.9.exe\n" + "b" * 64 + " *VaultMove-Portable-9.9.9.exe\n").encode()
    assert update.expected_sha256(rel, "VaultMove-Setup-9.9.9.exe", fetch=lambda u: sums) == "a" * 64
    assert update.expected_sha256(rel, "VaultMove-Portable-9.9.9.exe", fetch=lambda u: sums) == "b" * 64
    with pytest.raises(update.UpdateError):
        update.expected_sha256(rel, "other.exe", fetch=lambda u: sums)
    rel.assets.pop("SHA256SUMS.txt")
    with pytest.raises(update.UpdateError):
        update.expected_sha256(rel, "VaultMove-Setup-9.9.9.exe", fetch=lambda u: sums)


class _Resp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_download_verified_ok_and_tampered(tmp_path):
    data = os.urandom(700_000)
    good = hashlib.sha256(data).hexdigest()
    dest = str(tmp_path / "VaultMove-Setup-9.9.9.exe")
    seen = []
    p = update.download_verified(PREFIX + "VaultMove-Setup-9.9.9.exe", dest, good,
                                 opener=lambda u, t: _Resp(data), progress=lambda n, t: seen.append((n, t)))
    assert open(p, "rb").read() == data and seen[-1] == (len(data), len(data))
    os.remove(dest)
    with pytest.raises(update.UpdateError):
        update.download_verified(PREFIX + "VaultMove-Setup-9.9.9.exe", dest, "0" * 64, opener=lambda u, t: _Resp(data))
    assert not os.path.exists(dest) and not os.path.exists(dest + ".part")


def test_download_refuses_foreign_urls_and_can_be_cancelled(tmp_path):
    dest = str(tmp_path / "x.exe")
    with pytest.raises(update.UpdateError):
        update.download_verified("https://evil.example/x.exe", dest, "0" * 64, opener=lambda u, t: _Resp(b"x"))
    ev = threading.Event()
    ev.set()
    with pytest.raises(Cancelled):
        update.download_verified(PREFIX + "x.exe", dest, "0" * 64, cancel=ev, opener=lambda u, t: _Resp(b"x" * 10))
    assert not os.path.exists(dest + ".part")
    with pytest.raises(update.UpdateError):
        update._open("http://github.com/plain-http")


def test_finish_portable_update_only_deletes_the_old_vaultmove_exe(tmp_path):
    new = tmp_path / "VaultMove-Portable-1.1.0.exe"
    old = tmp_path / "VaultMove-Portable-1.0.0.exe"
    other = tmp_path / "important.exe"
    elsewhere = tmp_path / "sub" / "VaultMove-Portable-0.9.0.exe"
    elsewhere.parent.mkdir()
    for f in (new, old, other, elsewhere):
        f.write_bytes(b"x")
    dead_pid = 0x7FFFFFF0  # not a running process
    assert update.finish_portable_update(dead_pid, str(other), str(new)) is False
    assert update.finish_portable_update(dead_pid, str(elsewhere), str(new)) is False
    assert update.finish_portable_update(dead_pid, str(new), str(new)) is False
    assert other.exists() and elsewhere.exists() and new.exists()
    assert update.finish_portable_update(dead_pid, str(old), str(new)) is True
    assert not old.exists()


def test_install_mode_from_source():
    assert update.install_mode() == "source"
