"""Thin ctypes wrappers around the Win32 calls the engine needs.

Every function degrades gracefully off Windows (returns None / uses a portable
fallback) so the engine stays importable and testable everywhere, but the
shipped product targets Windows 10/11 only.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import string
import threading

IS_WIN = os.name == "nt"

if IS_WIN:
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                             ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                                    ctypes.c_void_p]
    k32.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    k32.GetVolumeNameForVolumeMountPointW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    k32.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                                          ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
    k32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
    k32.GetLogicalDrives.restype = wintypes.DWORD
    k32.GetCurrentThread.restype = wintypes.HANDLE
    k32.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
    k32.CreateMutexW.restype = wintypes.HANDLE
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]

    class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    k32.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(BY_HANDLE_FILE_INFORMATION)]

    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", ctypes.c_ubyte),
            ("BatteryFlag", ctypes.c_ubyte),
            ("BatteryLifePercent", ctypes.c_ubyte),
            ("SystemStatusFlag", ctypes.c_ubyte),
            ("BatteryLifeTime", wintypes.DWORD),
            ("BatteryFullLifeTime", wintypes.DWORD),
        ]

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", ctypes.c_void_p),
            ("pTo", ctypes.c_void_p),
            ("fFlags", ctypes.c_ushort),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]


GENERIC_READ = 0x80000000
DELETE = 0x00010000
FILE_READ_ATTRIBUTES = 0x80
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
FILE_SHARE_DELETE = 0x4
OPEN_EXISTING = 3
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
ERROR_SHARING_VIOLATION = 32
ERROR_LOCK_VIOLATION = 33
ERROR_DISK_FULL = 112
ERROR_HANDLE_DISK_FULL = 39

DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6

_EPOCH_AS_FILETIME = 116444736000000000


def _filetime_ns(ft) -> int:
    v = (ft.dwHighDateTime << 32) | ft.dwLowDateTime
    return (v - _EPOCH_AS_FILETIME) * 100


# --------------------------------------------------------------------------- volumes


def volume_mount_point(path: str) -> str | None:
    """'E:\\VaultMove' -> 'E:\\'."""
    if not IS_WIN:
        return None
    from .fsutil import strip_lp
    buf = ctypes.create_unicode_buffer(1024)
    if not k32.GetVolumePathNameW(strip_lp(path), buf, 1024):
        return None
    return buf.value


def volume_guid(path: str) -> str | None:
    """'E:\\x' -> '\\\\?\\Volume{...}\\' (stable across drive letter changes)."""
    if not IS_WIN:
        return None
    mp = volume_mount_point(path)
    if not mp:
        return None
    buf = ctypes.create_unicode_buffer(128)
    if not k32.GetVolumeNameForVolumeMountPointW(mp, buf, 128):
        return None
    return buf.value


def volume_info(path: str) -> dict:
    """Serial number, label and filesystem of the volume holding `path`."""
    info = {"serial": None, "label": "", "fs": "", "mount": None}
    if not IS_WIN:
        try:
            info["serial"] = os.stat(path).st_dev
        except OSError:
            pass
        return info
    mp = volume_mount_point(path)
    if not mp:
        return info
    label = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    serial = wintypes.DWORD()
    maxlen = wintypes.DWORD()
    flags = wintypes.DWORD()
    if k32.GetVolumeInformationW(mp, label, 261, ctypes.byref(serial), ctypes.byref(maxlen),
                                 ctypes.byref(flags), fs, 261):
        info.update(serial=int(serial.value), label=label.value, fs=fs.value)
    info["mount"] = mp
    return info


def disk_numbers(path: str) -> set[int] | None:
    """Physical disk numbers backing the volume of `path` (None if unknown)."""
    if not IS_WIN:
        return None
    guid = volume_guid(path)
    mp = volume_mount_point(path)
    if guid:
        dev = guid.rstrip("\\")
    elif mp:
        dev = "\\\\.\\" + mp.rstrip("\\")
    else:
        return None
    h = k32.CreateFileW(dev, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
    if h in (None, INVALID_HANDLE_VALUE):
        return None
    try:
        ret = wintypes.DWORD()
        buf = ctypes.create_string_buffer(8 + 24 * 32)
        # IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS
        if k32.DeviceIoControl(h, 0x00560000, None, 0, buf, len(buf), ctypes.byref(ret), None):
            raw = buf.raw
            n = int.from_bytes(raw[0:4], "little")
            return {int.from_bytes(raw[8 + 24 * i: 12 + 24 * i], "little") for i in range(min(n, 32))}
        sdn = (ctypes.c_ulong * 3)()
        # IOCTL_STORAGE_GET_DEVICE_NUMBER
        if k32.DeviceIoControl(h, 0x002D1080, None, 0, sdn, ctypes.sizeof(sdn), ctypes.byref(ret), None):
            return {int(sdn[1])}
        return None
    finally:
        k32.CloseHandle(h)


def same_physical_disk(a: str, b: str) -> bool | None:
    """True/False when known; None when Windows cannot tell us."""
    if not IS_WIN:
        try:
            return os.stat(a).st_dev == os.stat(b).st_dev
        except OSError:
            return None
    ga, gb = volume_guid(a), volume_guid(b)
    if ga and gb and ga.lower() == gb.lower():
        return True
    da, db = disk_numbers(a), disk_numbers(b)
    if da is None or db is None:
        return None
    return bool(da & db)


def drive_type(root: str) -> int:
    if not IS_WIN:
        return DRIVE_FIXED
    return int(k32.GetDriveTypeW(root))


def logical_drives_mask() -> int:
    if not IS_WIN:
        return 0
    return int(k32.GetLogicalDrives())


def list_drives() -> list[dict]:
    """All mounted drive letters with type, label and free/total bytes."""
    out = []
    if not IS_WIN:
        return out
    mask = logical_drives_mask()
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask & (1 << i):
            continue
        root = f"{letter}:\\"
        t = drive_type(root)
        if t in (DRIVE_CDROM, 0, 1):
            continue
        d = {"root": root, "letter": letter, "type": t, "label": "", "free": None, "total": None,
             "guid": None, "serial": None}
        try:
            u = shutil.disk_usage(root)
            d["free"], d["total"] = u.free, u.total
        except OSError:
            continue  # card reader with no card, etc.
        vi = volume_info(root)
        d["label"], d["serial"] = vi["label"], vi["serial"]
        d["guid"] = volume_guid(root)
        out.append(d)
    return out


def system_drive() -> str:
    return (os.environ.get("SystemDrive") or "C:").rstrip("\\") + "\\"


# --------------------------------------------------------------------------- power / priority


def power_status() -> tuple[bool | None, int | None]:
    """(on_ac_power, battery_percent). None = unknown / no battery."""
    if not IS_WIN:
        return None, None
    s = SYSTEM_POWER_STATUS()
    if not k32.GetSystemPowerStatus(ctypes.byref(s)):
        return None, None
    on_ac = {0: False, 1: True}.get(s.ACLineStatus)
    pct = None if s.BatteryLifePercent == 255 or s.BatteryFlag & 128 else int(s.BatteryLifePercent)
    return on_ac, pct


_bg = threading.local()


def set_thread_background(enable: bool) -> bool:
    """Lower (or restore) CPU and I/O priority of the calling thread."""
    if not IS_WIN:
        return False
    mode = 0x00010000 if enable else 0x00020000  # THREAD_MODE_BACKGROUND_BEGIN / END
    if enable == getattr(_bg, "on", False):
        return True
    ok = bool(k32.SetThreadPriority(k32.GetCurrentThread(), mode))
    if ok:
        _bg.on = enable
    return ok


# --------------------------------------------------------------------------- guarded file handles


class LockedHandle:
    """A Windows file handle opened with read+delete access, denying writers.

    While it is open no other process can modify the file, so what we hash is
    exactly what we delete. Off Windows it wraps a normal file object.
    """

    def __init__(self, path: str, want_delete: bool):
        self.path = path
        self._h = None
        self._f = None
        if IS_WIN:
            access = GENERIC_READ | (DELETE if want_delete else 0)
            h = k32.CreateFileW(path, access, FILE_SHARE_READ, None, OPEN_EXISTING,
                                FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_SEQUENTIAL_SCAN, None)
            if h in (None, INVALID_HANDLE_VALUE):
                err = ctypes.get_last_error()
                raise ctypes.WinError(err)
            self._h = h
        else:
            self._f = open(path, "rb")

    def stat(self) -> tuple[int, int]:
        """(size, mtime_ns) of the open file."""
        if self._f is not None:
            st = os.fstat(self._f.fileno())
            return st.st_size, st.st_mtime_ns
        info = BY_HANDLE_FILE_INFORMATION()
        if not k32.GetFileInformationByHandle(self._h, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        size = (info.nFileSizeHigh << 32) | info.nFileSizeLow
        return size, _filetime_ns(info.ftLastWriteTime)

    def chunks(self, size: int = 1 << 20):
        if self._f is not None:
            self._f.seek(0)
            while True:
                b = self._f.read(size)
                if not b:
                    return
                yield b
        buf = ctypes.create_string_buffer(size)
        got = wintypes.DWORD()
        # Rewind: SetFilePointerEx to 0
        k32.SetFilePointerEx(self._h, ctypes.c_longlong(0), None, 0)
        while True:
            if not k32.ReadFile(self._h, buf, size, ctypes.byref(got), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if got.value == 0:
                return
            yield buf.raw[: got.value]

    def delete_on_close(self) -> None:
        """Mark the file for deletion; it disappears when the handle closes."""
        if self._f is not None:
            os.remove(self.path)
            return

        # Prefer POSIX semantics (Win10 1709+): the name disappears immediately even
        # if another reader still has the file open.
        flags = wintypes.DWORD(0x1 | 0x2)  # FILE_DISPOSITION_FLAG_DELETE | POSIX_SEMANTICS
        if k32.SetFileInformationByHandle(self._h, 21, ctypes.byref(flags), ctypes.sizeof(flags)):
            return

        class FILE_DISPOSITION_INFO(ctypes.Structure):
            _fields_ = [("DeleteFile", wintypes.BOOLEAN)]

        info = FILE_DISPOSITION_INFO(True)
        if not k32.SetFileInformationByHandle(self._h, 4, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if self._h is not None:
            k32.CloseHandle(self._h)
            self._h = None
        if self._f is not None:
            self._f.close()
            self._f = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


if IS_WIN:
    k32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong, ctypes.c_void_p, wintypes.DWORD]


# --------------------------------------------------------------------------- recycle bin

RECYCLE_MAX_PATH = 259


def send_to_recycle_bin(path: str) -> None:
    """Move one file to the Recycle Bin via SHFileOperationW (no extra dependency).

    `path` must be a plain (non \\\\?\\) path shorter than MAX_PATH; the shell API
    does not support extended-length paths. Raises OSError on failure.
    """
    from .fsutil import strip_lp
    p = strip_lp(path)
    if not IS_WIN:
        raise OSError("Recycle Bin is only available on Windows")
    if len(p) > RECYCLE_MAX_PATH:
        raise OSError("path too long for the Recycle Bin")
    buf = ctypes.create_unicode_buffer(p + "\0\0")
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = 3  # FO_DELETE
    op.pFrom = ctypes.cast(buf, ctypes.c_void_p)
    op.pTo = None
    # FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_NOCONFIRMMKDIR
    op.fFlags = 0x40 | 0x10 | 0x4 | 0x400 | 0x200
    rc = shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted:
        raise OSError(f"SHFileOperation failed with code {rc:#x}")
    if os.path.lexists(p):
        raise OSError("file still present after Recycle Bin operation")


# --------------------------------------------------------------------------- misc


def create_named_mutex(name: str):
    """Returns (handle, already_existed)."""
    if not IS_WIN:
        return None, False
    h = k32.CreateMutexW(None, False, name)
    err = ctypes.get_last_error()
    return h, err == 183  # ERROR_ALREADY_EXISTS


def shell_execute_runas(exe: str, params: str) -> bool:
    """Start `exe` elevated (UAC prompt). Returns False if refused/cancelled."""
    if not IS_WIN:
        return False
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    rc = shell32.ShellExecuteW(None, "runas", exe, params, None, 0)
    return (rc or 0) > 32


def is_sharing_violation(e: BaseException) -> bool:
    return getattr(e, "winerror", None) in (ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION)


def is_disk_full(e: BaseException) -> bool:
    import errno
    return getattr(e, "winerror", None) in (ERROR_DISK_FULL, ERROR_HANDLE_DISK_FULL) or \
        getattr(e, "errno", None) == errno.ENOSPC
