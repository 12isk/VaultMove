"""Run one backup in a separate process (used by crash tests with VAULTMOVE_CRASHPOINT).

Usage: python tests/child_run.py <config_dir>
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from vaultmove.core import config as cfgmod  # noqa: E402
from vaultmove.core.engine import Engine  # noqa: E402


def main():
    cdir = sys.argv[1]
    cfg = cfgmod.load(cdir)
    r = Engine(cfg, same_disk_fn=lambda a, b: False, cache_dir=os.path.join(cdir, "cache")).run()
    print(r.status)
    sys.exit(0 if r.status in ("ok", "partial") else 3)


if __name__ == "__main__":
    main()
