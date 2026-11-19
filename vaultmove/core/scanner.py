"""Source tree walker (invariant 7).

* Never follows symlinks, junctions or mount points (so no loops, no escaping
  the source tree).
* Skips protected system locations, the vault, excluded globs and *.vmtmp.
* Uses os.scandir, whose stat data on Windows comes from the directory listing
  itself (no extra syscall per file), so incremental scans of hundreds of
  thousands of files stay fast.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from . import fsutil, winapi
from .errors import Cancelled
from .excludes import Matcher


class _WithTag:
    """A stat result with the reparse tag filled in from FindFirstFileW."""

    def __init__(self, st, tag):
        self._st = st
        self.st_reparse_tag = tag

    def __getattr__(self, name):
        return getattr(self._st, name)


@dataclass
class Entry:
    rel: str            # relative path with os.sep separators, original case
    size: int
    mtime_ns: int
    attrs: int
    cloud: bool         # OneDrive-style placeholder: back up, never offload
    online_only: bool   # content not on this PC: skip (reading would download it)


@dataclass
class ScanReport:
    dir_errors: list    # (rel_dir, message)
    skipped_links: int = 0
    skipped_online_only: int = 0
    skipped_protected: int = 0


def walk(root: str, matcher: Matcher, avoid: list[str], cancel=None, report: ScanReport | None = None):
    """Yield Entry objects for every regular file under `root`."""
    report = report if report is not None else ScanReport([])
    avoid = [os.path.normcase(a).rstrip("\\/") for a in list(avoid) + fsutil.protected_roots()]
    root_nc = os.path.normcase(root).rstrip("\\/")
    # Only keep protected locations that are inside this source; comparing against
    # the others is wasted work for every folder.
    avoid = [a for a in avoid if a.startswith(root_nc + os.sep)]
    stack = [""]
    while stack:
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        rel_dir = stack.pop()
        abs_dir = fsutil.join(root, rel_dir)
        try:
            it = os.scandir(fsutil.lp(abs_dir))
        except OSError as e:
            report.dir_errors.append((rel_dir, str(e)))
            continue
        subdirs = []
        with it:
            while True:
                try:
                    entry = next(it)
                except StopIteration:
                    break
                except OSError as e:
                    report.dir_errors.append((rel_dir, str(e)))
                    break
                name = entry.name
                rel = (rel_dir + os.sep + name) if rel_dir else name
                try:
                    st = entry.stat(follow_symlinks=False)
                    if (fsutil.attrs_of(st) & fsutil.FILE_ATTRIBUTE_REPARSE_POINT
                            and not getattr(st, "st_reparse_tag", 0)):
                        # os.lstat hides non-link reparse tags; ask Windows directly.
                        fd = winapi.find_data(fsutil.join(root, rel))
                        if fd is not None and fd[1]:
                            st = _WithTag(st, fd[1])
                except OSError as e:
                    report.dir_errors.append((rel, str(e)))
                    continue
                if fsutil.is_link_like(st):
                    report.skipped_links += 1
                    continue
                is_dir = entry.is_dir(follow_symlinks=False)
                if is_dir:
                    full_nc = os.path.normcase(fsutil.join(root, rel))
                    if (name.lower() in fsutil.PROTECTED_NAMES
                            or any(full_nc == a or full_nc.startswith(a + os.sep) for a in avoid)):
                        report.skipped_protected += 1
                        continue
                    if matcher.excluded(rel, True):
                        continue
                    subdirs.append(rel)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if name.lower().endswith(fsutil.TMP_SUFFIX) or matcher.excluded(rel, False):
                    continue
                if fsutil.is_online_only(st):
                    report.skipped_online_only += 1
                    continue
                yield Entry(rel, st.st_size, st.st_mtime_ns, fsutil.attrs_of(st),
                            fsutil.is_cloud_placeholder(st), False)
        stack.extend(reversed(subdirs))
