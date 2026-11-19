"""Hashing and verified, atomic copies (invariant 2).

A copy is written to "<final>.vmtmp", flushed and fsync'ed, read back and
hashed, and only then renamed into place with os.replace by the caller. A
crash at any moment leaves either nothing or a *.vmtmp file, which is never
treated as a valid copy.
"""

from __future__ import annotations

import hashlib
import os

from . import crashpoints, fsutil, winapi
from .errors import Cancelled, SourceReadError, VaultFull, VaultWriteError, VerifyFailed

CHUNK = 1 << 20


def open_read(path: str):
    """Open for reading. On Windows via CreateFileW so that a sharing violation keeps
    its winerror (the CRT open() reports every failure as a bare EACCES)."""
    if not winapi.IS_WIN:
        return open(fsutil.lp(path), "rb")
    import ctypes
    import msvcrt
    h = winapi.k32.CreateFileW(fsutil.lp(path), winapi.GENERIC_READ,
                               winapi.FILE_SHARE_READ | winapi.FILE_SHARE_WRITE | winapi.FILE_SHARE_DELETE,
                               None, winapi.OPEN_EXISTING, winapi.FILE_FLAG_SEQUENTIAL_SCAN, None)
    if h in (None, winapi.INVALID_HANDLE_VALUE):
        err = ctypes.get_last_error()
        e = ctypes.WinError(err)
        if err == 2 or err == 3:
            raise FileNotFoundError(e.errno, e.strerror, path)
        raise e
    fd = msvcrt.open_osfhandle(h, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    return os.fdopen(fd, "rb")


def hash_file(path: str, cancel=None) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open_read(path) as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
            n += len(b)
            if cancel is not None and cancel.is_set():
                raise Cancelled()
    return h.hexdigest(), n


def file_chunks(path: str):
    """Read a source file in chunks; errors are wrapped as SourceReadError."""
    try:
        f = open_read(path)
    except OSError as e:
        raise SourceReadError(e) from e
    with f:
        while True:
            try:
                b = f.read(CHUNK)
            except OSError as e:
                if isinstance(e, PermissionError) and not getattr(e, "winerror", None):
                    e.winerror = winapi.ERROR_LOCK_VIOLATION  # byte-range lock (e.g. Outlook .pst)
                raise SourceReadError(e) from e
            if not b:
                return
            yield b


def write_verified_tmp(chunks, final_path: str, mtime_ns: int | None, *, cancel=None,
                       on_bytes=None, expected_sha: str | None = None,
                       write_hook=None) -> tuple[str, str, int]:
    """Write `chunks` to final_path + '.vmtmp', verify by re-reading. Returns (tmp, sha, size).

    The caller is responsible for os.replace(tmp, final) once any old copy has
    been moved out of the way. On any failure the tmp file is removed.
    """
    tmp = final_path + fsutil.TMP_SUFFIX
    try:
        fsutil.makedirs(os.path.dirname(final_path))
    except OSError as e:
        raise VaultWriteError(e) from e
    h = hashlib.sha256()
    n = 0
    try:
        try:
            out = open(fsutil.lp(tmp), "wb")
        except OSError as e:
            raise VaultWriteError(e) from e
        with out:
            first = True
            for chunk in chunks:
                try:
                    if write_hook is not None:
                        write_hook(chunk)
                    out.write(chunk)
                except OSError as e:
                    if winapi.is_disk_full(e):
                        raise VaultFull("backup drive is full") from e
                    raise VaultWriteError(e) from e
                h.update(chunk)
                n += len(chunk)
                if on_bytes is not None:
                    on_bytes(len(chunk))
                if first:
                    crashpoints.crash("mid_copy")
                    first = False
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
            try:
                out.flush()
                os.fsync(out.fileno())
            except OSError as e:
                if winapi.is_disk_full(e):
                    raise VaultFull("backup drive is full") from e
                raise VaultWriteError(e) from e
        sha = h.hexdigest()
        try:
            vsha, vn = hash_file(tmp)
        except OSError as e:
            raise VaultWriteError(e) from e
        if vsha != sha or vn != n:
            raise VerifyFailed(f"read-back verification failed for {final_path}")
        if expected_sha is not None and sha != expected_sha:
            raise VerifyFailed(f"content hash mismatch for {final_path}")
        if mtime_ns is not None:
            try:
                os.utime(fsutil.lp(tmp), ns=(mtime_ns, mtime_ns))
            except OSError as e:
                raise VaultWriteError(e) from e
        crashpoints.crash("after_tmp_verified")
        return tmp, sha, n
    except BaseException:
        fsutil.remove_quiet(tmp)
        raise


def place(tmp: str, final: str) -> None:
    """Atomically move a verified tmp into place. Refuses to overwrite anything."""
    if fsutil.exists(final):
        raise VaultWriteError(FileExistsError(f"refusing to overwrite {final}"))
    try:
        os.replace(fsutil.lp(tmp), fsutil.lp(final))
    except OSError as e:
        raise VaultWriteError(e) from e
