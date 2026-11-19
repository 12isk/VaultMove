"""Filesystem helpers: long paths, attributes, protected locations.

Rule used everywhere in core: paths are built by joining a normalised root
(made absolute once, when the user picks it) with names that come from
os.scandir. We never call os.path.abspath() on a full file path, because on
Windows GetFullPathName rewrites reserved names (CON, NUL, COM1...) into device
paths. All OS calls go through lp(), which adds the \\\\?\\ prefix so that paths
longer than 260 characters, trailing dots/spaces and reserved names work.
"""

from __future__ import annotations

import os
import stat

IS_WIN = os.name == "nt"

FILE_ATTRIBUTE_READONLY = 0x1
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000

IO_REPARSE_TAG_NAME_SURROGATE_BIT = 0x20000000  # symlinks, junctions, mount points
IO_REPARSE_TAG_CLOUD_MASK = 0xFFFF0FFF
IO_REPARSE_TAG_CLOUD = 0x9000001A

TMP_SUFFIX = ".vmtmp"


def normroot(path: str) -> str:
    """Normalise a user-chosen folder once (absolute, no trailing separator)."""
    p = strip_lp(os.fspath(path))
    p = os.path.normpath(os.path.abspath(p))
    if len(p) > 3:
        p = p.rstrip("\\/")
    return p


def strip_lp(p: str) -> str:
    if p.startswith("\\\\?\\UNC\\"):
        return "\\\\" + p[8:]
    if p.startswith("\\\\?\\"):
        return p[4:]
    return p


def lp(p: str) -> str:
    """Return the extended-length form of an absolute, normalised path."""
    if not IS_WIN:
        return p
    if p.startswith("\\\\?\\"):
        return p
    p = p.replace("/", "\\")
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def join(root: str, rel: str) -> str:
    if not rel:
        return root
    rel = rel.replace("/", os.sep)
    if root.endswith(os.sep):
        return root + rel
    return root + os.sep + rel


def rel_key(rel: str) -> str:
    """Case-insensitive lookup key with forward slashes (NTFS is case-insensitive)."""
    return rel.replace("\\", "/").lower()


def parent_key(key: str) -> str:
    i = key.rfind("/")
    return key[:i] if i >= 0 else ""


def attrs_of(st) -> int:
    return getattr(st, "st_file_attributes", 0) or 0


def is_link_like(st) -> bool:
    """True for symlinks, junctions and mount points (never followed)."""
    if stat.S_ISLNK(st.st_mode):
        return True
    a = attrs_of(st)
    if a & FILE_ATTRIBUTE_REPARSE_POINT:
        tag = getattr(st, "st_reparse_tag", 0) or 0
        if tag == 0:
            # Unknown tag: treat as a link to be safe (never followed).
            return True
        return bool(tag & IO_REPARSE_TAG_NAME_SURROGATE_BIT)
    return False


def is_cloud_placeholder(st) -> bool:
    """OneDrive-style files. Backed up when local, never offloaded (deleting syncs to cloud)."""
    a = attrs_of(st)
    if a & (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | FILE_ATTRIBUTE_RECALL_ON_OPEN
            | 0x00080000 | 0x00100000):  # + OneDrive pinned / unpinned
        return True
    if a & FILE_ATTRIBUTE_REPARSE_POINT:
        tag = getattr(st, "st_reparse_tag", 0) or 0
        return (tag & IO_REPARSE_TAG_CLOUD_MASK) == IO_REPARSE_TAG_CLOUD
    return False


def is_online_only(st) -> bool:
    """File content is not on this PC; reading it would trigger a download."""
    a = attrs_of(st)
    return bool(a & (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS))


def cloud_sync_roots() -> list[str]:
    """Folders kept in sync by OneDrive or another cloud provider.

    Deleting a file in one of these deletes it in the cloud and on every other
    synced device, so VaultMove never frees space there. Sources: the OneDrive
    environment variables, OneDrive's account folders, and every sync root that
    a provider has registered with Windows (Dropbox, Google Drive, iCloud...).
    """
    roots = []
    for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        v = os.environ.get(var)
        if v:
            roots.append(v)
    if IS_WIN:
        import winreg

        def values(hive, path, want=None):
            out = []
            try:
                with winreg.OpenKey(hive, path) as k:
                    i = 0
                    while True:
                        try:
                            name, val, typ = winreg.EnumValue(k, i)
                        except OSError:
                            break
                        i += 1
                        if typ in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and isinstance(val, str) \
                                and (want is None or name == want):
                            out.append(os.path.expandvars(val))
            except OSError:
                pass
            return out

        def subkeys(hive, path):
            out = []
            try:
                with winreg.OpenKey(hive, path) as k:
                    i = 0
                    while True:
                        try:
                            out.append(winreg.EnumKey(k, i))
                        except OSError:
                            break
                        i += 1
            except OSError:
                pass
            return out

        acc = r"Software\Microsoft\OneDrive\Accounts"
        for a in subkeys(winreg.HKEY_CURRENT_USER, acc):
            roots += values(winreg.HKEY_CURRENT_USER, acc + "\\" + a, "UserFolder")
        srm = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\SyncRootManager"
        for prov in subkeys(winreg.HKEY_LOCAL_MACHINE, srm):
            roots += values(winreg.HKEY_LOCAL_MACHINE, srm + "\\" + prov + "\\UserSyncRoots")
    out = []
    for r in roots:
        if r and len(r) > 3 and os.path.isabs(r):
            try:
                out.append(normroot(r))
            except (OSError, ValueError):
                pass
    return sorted(set(out))


FILE_ATTRIBUTE_PINNED = 0x00080000
FILE_ATTRIBUTE_UNPINNED = 0x00100000


def _has_cloud_tag(path: str) -> bool:
    """Ask Windows directly (os.lstat hides cloud reparse points; see winapi.find_data)."""
    from . import winapi
    fd = winapi.find_data(path)
    if fd is None:
        return False
    attrs, tag = fd
    if attrs & (FILE_ATTRIBUTE_PINNED | FILE_ATTRIBUTE_UNPINNED | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
                | FILE_ATTRIBUTE_RECALL_ON_OPEN):
        return True
    return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT) and (tag & IO_REPARSE_TAG_CLOUD_MASK) == IO_REPARSE_TAG_CLOUD


def in_cloud_sync(path: str, roots: list[str] | None = None) -> bool:
    """True if `path` is inside a cloud-synced folder (registered root, or any
    parent folder carrying a cloud-files reparse tag)."""
    roots = cloud_sync_roots() if roots is None else roots
    if any(is_within(path, r) for r in roots):
        return True
    if _has_cloud_tag(strip_lp(path)):
        return True
    d = os.path.dirname(strip_lp(path))
    while d and len(d) > 3:
        if _has_cloud_tag(d):
            return True
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    return False


def exists(p: str) -> bool:
    try:
        os.lstat(lp(p))
        return True
    except OSError:
        return False


def isfile(p: str) -> bool:
    try:
        return stat.S_ISREG(os.lstat(lp(p)).st_mode)
    except OSError:
        return False


def makedirs(p: str) -> None:
    os.makedirs(lp(p), exist_ok=True)


def remove_quiet(p: str) -> None:
    try:
        os.remove(lp(p))
    except OSError:
        pass


def is_within(child: str, parent: str) -> bool:
    c = os.path.normcase(strip_lp(child)).rstrip("\\/")
    p = os.path.normcase(strip_lp(parent)).rstrip("\\/")
    return c == p or c.startswith(p + os.sep)


def protected_roots() -> list[str]:
    """Locations VaultMove must never back up, offload or write into."""
    env = os.environ
    roots = []
    for var in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData"):
        v = env.get(var)
        if v:
            roots.append(v)
    sysdrive = env.get("SystemDrive", "C:")
    roots += [
        sysdrive + "\\$Recycle.Bin",
        sysdrive + "\\System Volume Information",
        sysdrive + "\\Recovery",
        sysdrive + "\\$WinREAgent",
        sysdrive + "\\pagefile.sys",
        sysdrive + "\\hiberfil.sys",
        sysdrive + "\\swapfile.sys",
    ]
    for var in ("LOCALAPPDATA", "APPDATA"):
        v = env.get(var)
        if v:
            roots.append(v)
    up = env.get("USERPROFILE")
    if up:
        roots.append(os.path.join(up, "AppData"))
    out = []
    for r in roots:
        try:
            out.append(normroot(r))
        except (OSError, ValueError):
            pass
    return sorted(set(out))


PROTECTED_NAMES = {"$recycle.bin", "system volume information", "$winreagent", "config.msi"}


def is_protected(path: str, extra: list[str] | None = None) -> bool:
    for r in protected_roots() + list(extra or []):
        if is_within(path, r):
            return True
    return os.path.basename(path).lower() in PROTECTED_NAMES
