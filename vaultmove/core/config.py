"""Settings: dataclasses persisted as JSON with atomic writes.

Location: %APPDATA%\\VaultMove, or next to the exe in portable mode, or the
directory named by VAULTMOVE_CONFIG_DIR (used by tests and the CLI).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from . import fsutil
from .errors import ConfigError

CONFIG_NAME = "config.json"
PORTABLE_FLAG = "vaultmove-portable.flag"
PORTABLE_DIR = "VaultMove-Data"

DEFAULT_EXCLUDES = [
    "Thumbs.db", "desktop.ini", ".DS_Store", "~$*", "*.tmp", "*.temp", "*.vmtmp",
    "*.crdownload", "*.partial", "*.part", "$RECYCLE.BIN", "System Volume Information",
    "__pycache__", "node_modules", ".cache", "AppData",
]

RECYCLE_AUTO_DAYS = 7


@dataclass
class SourceCfg:
    path: str
    id: str = ""
    excludes: list = field(default_factory=list)
    offload_after_days: Optional[int] = None   # None = use global setting
    offload_enabled: Optional[bool] = None     # None = use global setting
    keep_versions_days: Optional[int] = None   # None = use global setting


@dataclass
class VaultCfg:
    uuid: str = ""
    path: str = ""            # last known absolute path (e.g. E:\\VaultMove)
    rel_path: str = ""        # path inside the volume (e.g. VaultMove)
    volume_guid: str = ""     # \\?\Volume{...}\ - primary identity of the drive
    volume_serial: Optional[int] = None
    label: str = ""
    allow_same_drive: bool = False


@dataclass
class OffloadCfg:
    enabled: bool = False
    after_days: int = 30
    recycle: str = "auto"     # "auto" (on during first 7 days), "on", "off"
    confirmed_at: Optional[float] = None
    preview_done_at: Optional[float] = None


@dataclass
class Config:
    vault: VaultCfg = field(default_factory=VaultCfg)
    sources: list = field(default_factory=list)
    excludes: list = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    offload: OffloadCfg = field(default_factory=OffloadCfg)
    offload_cloud: bool = False   # opt-in: also free space in OneDrive/cloud-synced folders
    keep_versions_days: Optional[int] = None    # None = forever (thinning still applies)
    thinning: bool = True
    schedule_minutes: int = 60
    run_on_plug: bool = True
    pause_on_battery: bool = True
    battery_min_percent: int = 30
    low_priority: bool = True
    vss_enabled: bool = True
    start_with_windows: bool = False
    notify_missing_days: int = 7
    language: str = "auto"
    paused: bool = False
    wizard_done: bool = False
    first_use_at: Optional[float] = None
    last_run_at: Optional[float] = None
    last_run_status: str = ""
    last_run_error: str = ""
    last_scanned: int = 0
    last_vault_seen_at: Optional[float] = None
    last_missing_notice_at: Optional[float] = None

    # ------------------------------------------------------------------ helpers

    def recycle_effective(self, now: float | None = None) -> bool:
        mode = self.offload.recycle
        if mode == "on":
            return True
        if mode == "off":
            return False
        now = time.time() if now is None else now
        start = self.first_use_at or now
        return (now - start) < RECYCLE_AUTO_DAYS * 86400

    def offload_armed(self) -> bool:
        """Offload runs only when enabled AND confirmed AND previewed (invariant 6)."""
        o = self.offload
        return bool(o.enabled and o.confirmed_at and o.preview_done_at)

    def source_offload_days(self, src: SourceCfg) -> Optional[int]:
        if not self.offload_armed():
            return None
        if src.offload_enabled is False:
            return None
        days = src.offload_after_days if src.offload_after_days is not None else self.offload.after_days
        if days is None or days < 1:
            return None
        return int(days)

    def source_keep_days(self, src: SourceCfg) -> Optional[int]:
        return src.keep_versions_days if src.keep_versions_days is not None else self.keep_versions_days

    def find_source(self, path: str) -> Optional[SourceCfg]:
        n = os.path.normcase(fsutil.normroot(path))
        for s in self.sources:
            if os.path.normcase(s.path) == n:
                return s
        return None


def make_source_id(path: str) -> str:
    base = os.path.basename(path.rstrip("\\/")) or path[:1] or "root"
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", base).strip("_")[:40] or "root"
    digest = hashlib.sha1(os.path.normcase(path).encode("utf-8")).hexdigest()[:8]
    return f"{base}-{digest}"


# ---------------------------------------------------------------------- (de)serialisation


def _from_dict(cls, data):
    if not isinstance(data, dict):
        return cls() if cls is not SourceCfg else None
    kwargs = {}
    names = {f.name: f for f in dataclasses.fields(cls)}
    for k, v in data.items():
        if k not in names:
            continue
        if k == "vault":
            v = _from_dict(VaultCfg, v)
        elif k == "offload":
            v = _from_dict(OffloadCfg, v)
        elif k == "sources":
            v = [s for s in (_from_dict(SourceCfg, x) for x in (v or [])) if s is not None]
        kwargs[k] = v
    try:
        return cls(**kwargs)
    except TypeError as e:
        raise ConfigError(f"invalid settings: {e}") from e


def config_from_dict(data: dict) -> Config:
    cfg = _from_dict(Config, data)
    for s in cfg.sources:
        s.path = fsutil.normroot(s.path)
        if not s.id:
            s.id = make_source_id(s.path)
    return cfg


def config_to_dict(cfg: Config) -> dict:
    return dataclasses.asdict(cfg)


# ---------------------------------------------------------------------- location


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def exe_dir() -> str:
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def is_portable(argv: list | None = None) -> bool:
    argv = sys.argv if argv is None else argv
    if "--portable" in argv:
        return True
    if not is_frozen():
        return False
    d = exe_dir()
    if os.path.exists(os.path.join(d, PORTABLE_FLAG)):
        return True
    return "portable" in os.path.basename(sys.executable).lower()


def config_dir(argv: list | None = None) -> str:
    env = os.environ.get("VAULTMOVE_CONFIG_DIR")
    if env:
        return fsutil.normroot(env)
    if is_portable(argv):
        return os.path.join(exe_dir(), PORTABLE_DIR)
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "VaultMove")


def load(cdir: str) -> Config:
    path = os.path.join(cdir, CONFIG_NAME)
    if not os.path.exists(path):
        return Config()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        # Keep the broken file for inspection; never silently overwrite it.
        raise ConfigError(f"cannot read settings file {path}: {e}") from e
    return config_from_dict(data)


def save(cfg: Config, cdir: str) -> None:
    os.makedirs(cdir, exist_ok=True)
    path = os.path.join(cdir, CONFIG_NAME)
    atomic_write_text(path, json.dumps(config_to_dict(cfg), indent=2, ensure_ascii=False))


def atomic_write_text(path: str, text: str) -> None:
    tmp = path + fsutil.TMP_SUFFIX
    with open(fsutil.lp(tmp), "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(fsutil.lp(tmp), fsutil.lp(path))
