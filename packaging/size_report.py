"""Markdown size report for the CI job summary."""

import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")


def mb(n):
    return f"{n / 1_000_000:.1f} MB"


def tree_size(d):
    total, files = 0, []
    for dp, _dn, fn in os.walk(d):
        for n in fn:
            p = os.path.join(dp, n)
            s = os.path.getsize(p)
            total += s
            files.append((s, os.path.relpath(p, d)))
    return total, sorted(files, reverse=True)


def main():
    out = ["## VaultMove build sizes", "", "| Artifact | Size |", "|---|---|"]
    onedir = os.path.join(DIST, "VaultMove")
    top = []
    if os.path.isdir(onedir):
        total, top = tree_size(onedir)
        out.append(f"| Installed size (onedir payload, `dist/VaultMove/`) | **{mb(total)}** |")
    for pat, label in (("VaultMove-Setup-*.exe", "Installer"), ("VaultMove-Portable-*.exe", "Portable exe")):
        for p in glob.glob(os.path.join(DIST, pat)):
            out.append(f"| {label} `{os.path.basename(p)}` | **{mb(os.path.getsize(p))}** |")
    if top:
        out += ["", "<details><summary>Largest files in the installed folder</summary>", "",
                "| File | Size |", "|---|---|"]
        out += [f"| `{n}` | {mb(s)} |" for s, n in top[:20]]
        out += ["", "</details>"]
    print("\n".join(out))


if __name__ == "__main__":
    sys.exit(main())
