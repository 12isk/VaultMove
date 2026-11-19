"""VSS helper protocol and path policy, run unelevated with a fake snapshot provider.

Real snapshots need administrator rights and a UAC prompt: see MANUAL_TESTS.md.
"""

import os

import pytest

from tests.helpers import sha
from vaultmove.core import winapi
from vaultmove.helper.server import Helper, validate_path
from vaultmove.helper.shadow import FakeProvider

pytestmark = pytest.mark.skipif(not winapi.IS_WIN, reason="named pipes / drive paths")


def test_path_policy(tmp_path):
    root = str(tmp_path / "Docs")
    os.makedirs(root)
    ok = os.path.join(root, "a.txt")
    assert validate_path(ok, [root]) == ok
    for bad in [os.path.join(root, "..", "x.txt"), "C:/Windows/x", "\\\\server\\share\\x",
                "C:\\Windows\\System32\\config\\SAM", "relative.txt", root + "x\\a.txt", ok + "\x00"]:
        with pytest.raises(PermissionError):
            validate_path(bad, [root])


def test_reparse_component_refused(tmp_path):
    import _winapi
    root = str(tmp_path / "Docs")
    secret = str(tmp_path / "secret")
    os.makedirs(root)
    os.makedirs(secret)
    with open(os.path.join(secret, "s.txt"), "wb") as f:
        f.write(b"admin only")
    _winapi.CreateJunction(secret, os.path.join(root, "j"))
    h = Helper([root], FakeProvider())
    with pytest.raises(PermissionError):
        h.handle({"op": "open", "path": os.path.join(root, "j", "s.txt")})
    with pytest.raises(PermissionError):
        h.handle({"op": "nuke"})


def test_session_end_to_end_unelevated(tmp_path):
    from vaultmove.helper.client import VssSession
    root = str(tmp_path / "Docs")
    os.makedirs(root)
    p = os.path.join(root, "busy.db")
    data = os.urandom(3_000_000)
    with open(p, "wb") as f:
        f.write(data)
    s = VssSession.start([root], elevate=False, fake=True, timeout=60)
    try:
        size, mtime, chunks = s.open(p)
        assert size == len(data)
        got = b"".join(chunks)
        assert sha(got) == sha(data)
        with pytest.raises(OSError):
            s.open(str(tmp_path / "outside.txt"))
    finally:
        s.close()
