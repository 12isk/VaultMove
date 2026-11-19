"""Command-line harness for the engine (M2). No Qt.

    python -m vaultmove.cli init-vault E:\\VaultMove
    python -m vaultmove.cli add-source "C:\\Users\\me\\Documents"
    python -m vaultmove.cli preview
    python -m vaultmove.cli backup
    python -m vaultmove.cli offload --enable --days 60 --i-understand
    python -m vaultmove.cli search report
    python -m vaultmove.cli history <source-id> <relative\\path>
    python -m vaultmove.cli restore <source-id> <relative\\path> [--to DIR] [--as-of 2026-01-31]
    python -m vaultmove.cli prune --older-than 365
    python -m vaultmove.cli rebuild-index
    python -m vaultmove.cli status

Use --config-dir to keep test settings away from your real ones.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time

from . import __version__
from .core import catalog, config as cfgmod, fsutil, vault
from .core.config import SourceCfg, make_source_id
from .core.engine import Engine, delete_old_versions
from .core.errors import VaultMoveError
from .core.rebuild import rebuild_index
from .core.restore import restore_many


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def _load(args):
    cdir = args.config_dir or cfgmod.config_dir()
    return cfgmod.load(cdir), cdir


def _engine(cfg, cdir, args, **kw):
    def prog(d):
        if args.verbose and d.get("current"):
            print(f"  [{d.get('phase')}] {d.get('current')}", flush=True)
    return Engine(cfg, cache_dir=os.path.join(cdir, "cache"), log=lambda m: print(m, flush=True),
                  progress=prog, **kw)


def cmd_init_vault(args):
    cfg, cdir = _load(args)
    state = vault.inspect_destination(args.path)
    if state == "not_empty":
        print(f"Refused: {args.path} is not empty and is not a VaultMove vault.")
        return 2
    vid = vault.create_vault(args.path)
    cfg.vault = vault.vault_cfg_for(args.path, vid, allow_same_drive=args.allow_same_drive)
    if cfg.first_use_at is None:
        cfg.first_use_at = time.time()
    cfgmod.save(cfg, cdir)
    print(f"Vault ready at {cfg.vault.path} (uuid {vid}, volume {cfg.vault.volume_guid or '?'}).")
    return 0


def cmd_add_source(args):
    cfg, cdir = _load(args)
    p = fsutil.normroot(args.path)
    if not os.path.isdir(p):
        print(f"Not a folder: {p}")
        return 2
    if fsutil.is_protected(p):
        print(f"Refused: {p} is a protected system or app-data location.")
        return 2
    if cfg.find_source(p):
        print("Already in the list.")
        return 0
    cfg.sources.append(SourceCfg(path=p, id=make_source_id(p)))
    cfgmod.save(cfg, cdir)
    print(f"Added {p}")
    return 0


def cmd_remove_source(args):
    cfg, cdir = _load(args)
    s = cfg.find_source(args.path)
    if not s:
        print("Not in the list.")
        return 2
    cfg.sources.remove(s)
    cfgmod.save(cfg, cdir)
    print(f"Removed {s.path} (its copies stay in the vault).")
    return 0


def cmd_status(args):
    cfg, cdir = _load(args)
    print(f"VaultMove {__version__}  settings: {cdir}")
    root = vault.locate_vault(cfg.vault)
    print(f"Vault: {cfg.vault.path or '(none)'}  connected: {'yes at ' + root if root else 'no'}")
    for s in cfg.sources:
        print(f"  source {s.id}: {s.path}")
    o = cfg.offload
    print(f"Free up space: {'on' if cfg.offload_armed() else 'off'} (after {o.after_days} days, "
          f"recycle bin: {'yes' if cfg.recycle_effective() else 'no'})")
    idx, _ = catalog.open_catalog(cfg, os.path.join(cdir, "cache"))
    if idx:
        st = idx.stats()
        print(f"Index: {st['files']} files ({human(st['bytes'])}), {st['versions']} older versions "
              f"({human(st['version_bytes'])}), {st['offloaded']} on backup drive only")
        idx.close()
    return 0


def _print_plan(res):
    for action, label in (("copy", "Will copy"), ("delete", "Will delete from this PC"),
                          ("eligible", "Will be freed on a later run")):
        n, b = res.plan.total(action)
        print(f"{label}: {n} files, {human(b)}")
    for it in res.plan.items:
        if it.action == "delete":
            print(f"  DELETE  {it.path}  ({human(it.size)})")


def cmd_preview(args):
    cfg, cdir = _load(args)
    res = _engine(cfg, cdir, args).preview()
    if res.status not in ("ok", "partial"):
        print(f"Preview failed: {res.status} {res.error}")
        return 1
    _print_plan(res)
    cfg.offload.preview_done_at = time.time()
    cfgmod.save(cfg, cdir)
    return 0


def cmd_backup(args):
    cfg, cdir = _load(args)
    res = _engine(cfg, cdir, args, manual=True).run()
    s = res.stats
    print(f"Result: {res.status}. Scanned {s.scanned}, copied {s.copied} ({human(s.copied_bytes)}), "
          f"versions {s.versioned}, unchanged {s.unchanged}, freed {s.offloaded} ({human(s.offloaded_bytes)}), "
          f"locked {s.locked}, errors {s.errors}.")
    for m in res.messages:
        print("  " + m)
    cfg.last_run_at, cfg.last_run_status = res.finished_at, res.status
    cfgmod.save(cfg, cdir)
    return 0 if res.status in ("ok", "partial") else 1


def cmd_offload(args):
    cfg, cdir = _load(args)
    o = cfg.offload
    if args.disable:
        o.enabled = False
        cfgmod.save(cfg, cdir)
        print("Free up space: off")
        return 0
    if args.days:
        o.after_days = args.days
    if args.recycle:
        o.recycle = args.recycle
    if args.enable:
        if not args.i_understand:
            print("Freeing space deletes originals after a verified copy exists on the backup drive.\n"
                  "Re-run with --i-understand to confirm, then run 'preview' once.")
            return 2
        o.enabled = True
        o.confirmed_at = time.time()
    cfgmod.save(cfg, cdir)
    print(f"Free up space: {'armed' if cfg.offload_armed() else 'needs preview' if o.enabled else 'off'}, "
          f"after {o.after_days} days")
    return 0


def _source_id(cfg, idx, value):
    if value in idx.sources():
        return value
    s = cfg.find_source(value) if os.path.isabs(value) else None
    return s.id if s else value


def cmd_search(args):
    cfg, cdir = _load(args)
    idx, _ = catalog.open_catalog(cfg, os.path.join(cdir, "cache"))
    if not idx:
        print("No index available.")
        return 1
    for c in idx.search(args.term, args.limit):
        when = dt.datetime.fromtimestamp(c.valid_from).strftime("%Y-%m-%d %H:%M")
        print(f"{c.source_id}  {c.rel_path}  {human(c.size)}  {when}  [{catalog.status_of(c)}]")
    idx.close()
    return 0


def cmd_history(args):
    cfg, cdir = _load(args)
    idx, _ = catalog.open_catalog(cfg, os.path.join(cdir, "cache"))
    if not idx:
        print("No index available.")
        return 1
    sid = _source_id(cfg, idx, args.source)
    print(catalog.where_is(idx, sid, args.path))
    h = catalog.history(idx, sid, args.path)
    for c in h["copies"]:
        state = "latest" if c.is_current else ("pruned" if c.pruned_at else "older")
        print(f"  copy {c.id}: {state}  {human(c.size)}  sha256 {c.sha256[:12]}…  at {c.vault_rel}")
    for e in h["events"]:
        when = dt.datetime.fromtimestamp(e["ts"]).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {when}  {e['kind']}  {e['detail'] or ''}")
    idx.close()
    return 0


def cmd_restore(args):
    cfg, cdir = _load(args)
    root = vault.locate_vault(cfg.vault)
    if not root:
        print("Backup drive not connected.")
        return 1
    from .core.index import Index
    idx = Index.open_vault(root)
    try:
        sid = _source_id(cfg, idx, args.source)
        key = fsutil.rel_key(args.path)
        t = time.time() + 1
        if args.as_of:
            t = dt.datetime.fromisoformat(args.as_of).timestamp()
        copies = list(idx.copies_asof(t, sid, key))
        if not copies:
            print("Nothing found for that path and date.")
            return 1
        res = restore_many(idx, root, copies, dest_root=args.to, base_key=key if args.to else "",
                           progress=None)
        for cid, target in res.restored:
            print(f"Restored (hash verified): {target}")
        for cid, target, why in res.skipped:
            print(f"Skipped ({why}): {target}")
        for cid, target, why in res.failed:
            print(f"FAILED: {target}: {why}")
        return 0 if not res.failed else 1
    finally:
        idx.close()


def cmd_prune(args):
    cfg, _ = _load(args)
    n, b = delete_old_versions(cfg, args.older_than, log=print)
    print(f"Deleted {n} old versions ({human(b)}). Latest copies are never deleted.")
    return 0


def cmd_rebuild(args):
    cfg, _ = _load(args)
    root = vault.require_vault(cfg.vault)
    with vault.VaultLock(root):
        rebuild_index(root, log=print)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="vaultmove", description="VaultMove command line")
    p.add_argument("--config-dir")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init-vault"); s.add_argument("path"); s.add_argument("--allow-same-drive", action="store_true")
    s.set_defaults(fn=cmd_init_vault)
    s = sub.add_parser("add-source"); s.add_argument("path"); s.set_defaults(fn=cmd_add_source)
    s = sub.add_parser("remove-source"); s.add_argument("path"); s.set_defaults(fn=cmd_remove_source)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("preview").set_defaults(fn=cmd_preview)
    sub.add_parser("backup").set_defaults(fn=cmd_backup)
    s = sub.add_parser("offload")
    s.add_argument("--enable", action="store_true"); s.add_argument("--disable", action="store_true")
    s.add_argument("--days", type=int); s.add_argument("--recycle", choices=["auto", "on", "off"])
    s.add_argument("--i-understand", action="store_true"); s.set_defaults(fn=cmd_offload)
    s = sub.add_parser("search"); s.add_argument("term"); s.add_argument("--limit", type=int, default=100)
    s.set_defaults(fn=cmd_search)
    s = sub.add_parser("history"); s.add_argument("source"); s.add_argument("path"); s.set_defaults(fn=cmd_history)
    s = sub.add_parser("restore"); s.add_argument("source"); s.add_argument("path")
    s.add_argument("--to"); s.add_argument("--as-of"); s.set_defaults(fn=cmd_restore)
    s = sub.add_parser("prune"); s.add_argument("--older-than", type=float, required=True)
    s.set_defaults(fn=cmd_prune)
    sub.add_parser("rebuild-index").set_defaults(fn=cmd_rebuild)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except VaultMoveError as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
