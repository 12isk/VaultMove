"""Fault-injection hooks used by the crash tests.

When the environment variable VAULTMOVE_CRASHPOINT equals a crash point name,
the process is terminated immediately with os._exit (no cleanup, no finally
blocks, no flush), which is as close to a power cut as a test can get.
In normal use the variable is unset and crash() is a cheap no-op.
"""

import os

_TARGET = os.environ.get("VAULTMOVE_CRASHPOINT", "")
_SKIP = int(os.environ.get("VAULTMOVE_CRASHPOINT_SKIP", "0") or 0)
_hits = 0

POINTS = (
    "mid_copy",              # inside the chunk loop writing a .vmtmp
    "after_tmp_verified",    # tmp written and verified, not yet placed
    "after_journal",         # pending op committed, nothing moved yet
    "after_version_move",    # old copy moved to _versions, new not placed
    "after_replace",         # new copy placed, index not yet updated
    "before_delete",         # offload journal committed, original still there
    "after_delete",          # original deleted, index not yet updated
    "mid_prune",             # prune committed in index, file not yet deleted
)


def crash(name: str) -> None:
    global _hits
    if _TARGET and name == _TARGET:
        if _hits >= _SKIP:
            os._exit(99)
        _hits += 1
