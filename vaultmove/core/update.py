"""In-app updates from GitHub Releases. Network is used ONLY when the user clicks
"Check for Updates": there are no background checks and no telemetry.

Flow: fetch the latest release → pick the asset for this install type → download
over HTTPS to a .part file while hashing → compare with SHA256SUMS.txt from the
same release → hand over to the installer (silent in-place upgrade) or to the new
portable exe, then the running app quits.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from .. import UPDATE_REPO, __version__
from . import config as cfgmod
from .errors import Cancelled, VaultMoveError

API_LATEST = f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{UPDATE_REPO}/releases/download/"
USER_AGENT = "VaultMove-updater"   # generic: no user, machine or account details are ever sent
MAX_DOWNLOAD = 400 * 1024 * 1024
CHUNK = 256 * 1024


class UpdateError(VaultMoveError):
    pass


@dataclass
class Release:
    version: str
    tag: str
    notes: str
    page_url: str
    assets: dict          # name -> download url

    def asset_for(self, mode: str) -> Optional[tuple[str, str]]:
        pat = {"installer": r"^VaultMove-Setup-[\d.]+\.exe$", "portable": r"^VaultMove-Portable-[\d.]+\.exe$"}.get(mode)
        if not pat:
            return None
        for name, url in self.assets.items():
            if re.match(pat, name):
                return name, url
        return None


def parse_version(s: str) -> tuple:
    m = re.match(r"^\s*[vV]?(\d+)\.(\d+)\.(\d+)", s or "")
    if not m:
        raise UpdateError(f"not a version: {s!r}")
    return tuple(int(x) for x in m.groups())


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def install_mode() -> str:
    """'installer' (installed with the Setup), 'portable', or 'source' (running from Python)."""
    if not cfgmod.is_frozen():
        return "source"
    return "portable" if cfgmod.is_portable() else "installer"


def _open(url: str, timeout: float = 30):
    if not url.startswith("https://"):
        raise UpdateError("refusing a non-HTTPS URL")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())


def _get(url: str) -> bytes:
    with _open(url) as r:
        return r.read(2 * 1024 * 1024)


def check_latest(fetch: Callable[[str], bytes] = _get) -> Release:
    import urllib.error
    try:
        data = json.loads(fetch(API_LATEST).decode("utf-8"))
    except UpdateError:
        raise
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError("no release has been published yet") from e
        raise UpdateError(f"GitHub answered HTTP {e.code}") from e
    except Exception as e:
        raise UpdateError(f"could not reach GitHub: {e}") from e
    tag = data.get("tag_name") or ""
    version = ".".join(str(x) for x in parse_version(tag))
    assets = {}
    for a in data.get("assets") or []:
        name, url = a.get("name") or "", a.get("browser_download_url") or ""
        # Only files published in this repository's releases are ever downloaded.
        if url.startswith(DOWNLOAD_PREFIX) and re.fullmatch(r"[A-Za-z0-9._-]+", name):
            assets[name] = url
    return Release(version, tag, (data.get("body") or "").strip(), data.get("html_url") or "", assets)


def expected_sha256(rel: Release, name: str, fetch: Callable[[str], bytes] = _get) -> str:
    url = rel.assets.get("SHA256SUMS.txt")
    if not url:
        raise UpdateError("the release has no SHA256SUMS.txt; refusing to install an unverified file")
    for line in fetch(url).decode("utf-8", "replace").splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[1].lstrip("*") == name and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            return parts[0].lower()
    raise UpdateError(f"no checksum for {name} in SHA256SUMS.txt")


def download_verified(url: str, dest: str, sha256: str, *, progress=None, cancel=None,
                      opener=_open) -> str:
    """Download to dest + '.part', verify SHA-256, then rename to dest. Returns dest."""
    if not url.startswith(DOWNLOAD_PREFIX):
        raise UpdateError("refusing to download from outside this app's GitHub releases")
    part = dest + ".part"
    h = hashlib.sha256()
    n = 0
    try:
        with opener(url, 120) as r, open(part, "wb") as out:
            total = int(r.headers.get("Content-Length") or 0) if getattr(r, "headers", None) else 0
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                b = r.read(CHUNK)
                if not b:
                    break
                n += len(b)
                if n > MAX_DOWNLOAD:
                    raise UpdateError("download is unexpectedly large")
                h.update(b)
                out.write(b)
                if progress:
                    progress(n, total)
            out.flush()
            os.fsync(out.fileno())
        if h.hexdigest() != sha256.lower():
            raise UpdateError("the downloaded file does not match its published checksum; it was deleted")
        if os.path.exists(dest):
            os.remove(dest)
        os.replace(part, dest)
        return dest
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise


def download_dir(mode: str) -> str:
    if mode == "portable":
        return os.path.dirname(os.path.abspath(sys.executable))   # next to the current exe (e.g. on the USB stick)
    d = os.path.join(tempfile.gettempdir(), "VaultMove-update")
    os.makedirs(d, exist_ok=True)
    return d


_DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def launch_installer(setup_path: str) -> None:
    """Silent in-place upgrade. The installer restarts VaultMove when it is done."""
    subprocess.Popen([setup_path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     close_fds=True, creationflags=_DETACHED if os.name == "nt" else 0)


def launch_portable(new_exe: str) -> None:
    """Start the new portable exe; it waits for this process to exit, then removes the old exe."""
    subprocess.Popen([new_exe, "--after-update", str(os.getpid()), os.path.abspath(sys.executable)],
                     close_fds=True, creationflags=_DETACHED if os.name == "nt" else 0)


def wait_for_pid(pid: int, timeout: float = 60) -> bool:
    if os.name != "nt":
        return True
    SYNCHRONIZE = 0x00100000
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
    if not h:
        return True  # already gone
    try:
        return k32.WaitForSingleObject(ctypes.c_void_p(h), int(timeout * 1000)) == 0
    finally:
        k32.CloseHandle(ctypes.c_void_p(h))


def finish_portable_update(old_pid: int, old_exe: str, current_exe: str | None = None) -> bool:
    """Run by the NEW portable exe: wait for the old one to quit, then delete it.

    Only ever deletes a file named VaultMove-Portable-*.exe in the same folder as
    the new exe, and never the running exe itself.
    """
    current_exe = os.path.abspath(current_exe or sys.executable)
    old_exe = os.path.abspath(old_exe)
    if os.path.normcase(old_exe) == os.path.normcase(current_exe):
        return False
    if os.path.normcase(os.path.dirname(old_exe)) != os.path.normcase(os.path.dirname(current_exe)):
        return False
    if not re.fullmatch(r"(?i)VaultMove-Portable-[\d.]+\.exe", os.path.basename(old_exe)):
        return False
    wait_for_pid(old_pid)
    for _ in range(20):
        try:
            os.remove(old_exe)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            time.sleep(0.5)
    return False
