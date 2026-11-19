"""List every string passed to tr("...") or N_("...") in vaultmove/app (used by tests and make_ts.py)."""

from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "vaultmove", "app")


def extract() -> list[str]:
    found: list[str] = []
    seen = set()
    for name in sorted(os.listdir(APP)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(APP, name), encoding="utf-8") as f:
            tree = ast.parse(f.read(), name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("tr", "N_"):
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    s = node.args[0].value
                    if s not in seen:
                        seen.add(s)
                        found.append(s)
    return found


if __name__ == "__main__":
    for s in extract():
        sys.stdout.write(repr(s) + "\n")
