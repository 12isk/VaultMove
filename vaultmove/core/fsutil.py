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
    if a & (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS | FILE_ATTRIBUTE_RECALL_ON_OPEN):
        return True
    if a & FILE_ATTRIBUTE_REPARSE_POINT:
        tag = getattr(st, "st_reparse_tag", 0) or 0
        return (tag & IO_REPARSE_TAG_CLOUD_MASK) == IO_REPARSE_TAG_CLOUD
    return False


def is_online_only(st) -> bool:
    """File content is not on this PC; reading it would trigger a download."""
    a = attrs_of(st)
    return bool(a & (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS))


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
