"""Shared test helpers: a temp "PC" with a source folder and a temp vault."""

from __future__ import annotations

import hashlib
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from vaultmove.core import config as cfgmod, fsutil, vault  # noqa: E402
from vaultmove.core.config import Config, SourceCfg, make_source_id  # noqa: E402
from vaultmove.core.engine import Engine  # noqa: E402
from vaultmove.core.index import Index  # noqa: E402

DAY = 86400


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: str) -> str:
    with open(fsutil.lp(path), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def not_same_disk(a, b):
    """Tests run on one disk; pretend the vault is a separate USB disk."""
    return False


class Env:
    def __init__(self, base: str):
        self.base = fsutil.normroot(base)
        self.src = os.path.join(self.base, "pc", "Documents")
        self.vault = os.path.join(self.base, "usb", "VaultMove")
        self.cfg_dir = os.path.join(self.base, "appdata")
        self.cache = os.path.join(self.cfg_dir, "cache")
        os.makedirs(self.src)
        os.makedirs(os.path.dirname(self.vault))
        vid = vault.create_vault(self.vault)
        self.cfg = Config()
        self.cfg.vault = vault.vault_cfg_for(self.vault, vid)
        self.cfg.first_use_at = time.time()
        self.cfg.low_priority = False
        self.cfg.sources = [SourceCfg(path=self.src, id=make_source_id(self.src))]
        self.logs: list[str] = []

    @property
    def sid(self) -> str:
        return self.cfg.sources[0].id

    def path(self, rel: str) -> str:
        return fsutil.join(self.src, rel)

    def write(self, rel: str, data: bytes | str, age_days: float = 0.0) -> str:
        if isinstance(data, str):
            data = data.encode("utf-8")
        p = self.path(rel)
        fsutil.makedirs(os.path.dirname(p))
        with open(fsutil.lp(p), "wb") as f:
            f.write(data)
        if age_days:
            t = time.time() - age_days * DAY
            os.utime(fsutil.lp(p), (t, t))
        return p

    def arm_offload(self, days: int = 30, recycle: str = "off"):
        o = self.cfg.offload
        o.enabled = True
        o.after_days = days
        o.recycle = recycle
        o.confirmed_at = time.time()
        o.preview_done_at = time.time()

    def engine(self, **kw) -> Engine:
        kw.setdefault("same_disk_fn", not_same_disk)
        kw.setdefault("cache_dir", self.cache)
        kw.setdefault("log", self.logs.append)
        return Engine(self.cfg, **kw)

    def run(self, **kw):
        dry = kw.pop("dry_run", False)
        return self.engine(**kw).run(dry_run=dry)

    def index(self) -> Index:
        return Index.open_vault(self.vault)

    def save_cfg(self):
        cfgmod.save(self.cfg, self.cfg_dir)

    def vault_files(self, sub: str = "") -> list[str]:
        out = []
        root = os.path.join(self.vault, sub) if sub else self.vault
        for dp, _dn, fn in os.walk(fsutil.lp(root)):
            for n in fn:
                out.append(fsutil.strip_lp(os.path.join(dp, n)))
        return out
