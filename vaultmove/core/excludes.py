"""Exclude-glob matching (case-insensitive, Windows semantics).

* A pattern without '/' matches a file or folder *name* at any depth
  ("*.tmp", "node_modules").
* A pattern with '/' matches the path relative to the source root
  ("Projects/build/**", "**/cache/*.bin"). '**' crosses folders, '*' does not.
"""

from __future__ import annotations

import fnmatch
import re


def _translate(pat: str) -> str:
    i, out = 0, []
    n = len(pat)
    while i < n:
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        else:
            c = pat[i]
            if c == "*":
                out.append("[^/]*")
            elif c == "?":
                out.append("[^/]")
            else:
                out.append(re.escape(c))
            i += 1
    return "^" + "".join(out) + "$"


class Matcher:
    def __init__(self, patterns):
        names, paths = [], []
        for raw in patterns or []:
            p = str(raw).strip().replace("\\", "/")
            if not p or p.startswith("#"):
                continue
            while p.startswith("./"):
                p = p[2:]
            p = p.lstrip("/")
            stripped = p.rstrip("/")
            if "/" not in stripped:
                names.append(re.compile(fnmatch.translate(stripped.lower())))
            else:
                paths.append(re.compile(_translate(stripped.lower())))
        self._names = names
        self._paths = paths

    def excluded(self, rel: str, is_dir: bool = False) -> bool:
        r = rel.replace("\\", "/").lower()
        name = r.rsplit("/", 1)[-1]
        for rx in self._names:
            if rx.match(name):
                return True
        for rx in self._paths:
            if rx.match(r) or (is_dir and rx.match(r + "/")):
                return True
        return False
