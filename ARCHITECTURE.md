# VaultMove architecture

```
run_vaultmove.py            entry point (PyInstaller script)
vaultmove/
  core/                     pure Python, standard library only, no Qt
    engine.py               one backup run: scan → copy/version → locked files → offload → thin
    scanner.py              os.scandir walker (no link following, protected paths, excludes)
    copier.py               SHA-256, verified .vmtmp writes, atomic place()
    offload.py              the deletion checks (SAFETY.md invariant 1)
    recovery.py             write-ahead journal roll-forward / roll-back after a crash
    retention.py            version thinning + manual pruning
    restore.py              verified restore, never overwrites (".restored" suffix)
    rebuild.py              rebuild the index from the plain files in the vault
    index.py                SQLite index on the vault + append-only JSONL log
    catalog.py              read side: browse as of a date, search, file history
    vault.py                marker/UUID, layout, locate by volume GUID, lock, same-disk checks
    config.py               settings dataclasses, JSON, portable mode
    winapi.py, fsutil.py    ctypes Win32 calls, \\?\ long paths, attributes
    crashpoints.py          fault-injection hooks for the crash tests
  cli.py                    command-line harness (M2)
  app/                      PySide6 Widgets UI
    main.py                 args, single instance, logging, --selftest
    controller.py           owns settings, tray, scheduler, drive watcher, engine service
    service.py              thin layer UI ↔ engine (signals, cancellation, restore jobs)
    workers.py              QThreadPool tasks
    tray.py, devicewatch.py, singleinstance.py, startup.py
    mainwindow.py, backup_tab.py, restore_tab.py, timeline.py, wizard.py, dialogs.py
    theme.py, widgets.py, icon.py, i18n.py (+ i18n/vaultmove_fr.ts)
  helper/                   elevated VSS helper (server.py) and its unelevated client (client.py)
packaging/                  PyInstaller spec, Inno Setup script, icon renderer, size report, signing
tests/                      pytest (core, crash, faults, perf, VSS protocol, CLI, UI smoke)
tools/                      translation extraction / .ts generation
```

## Vault layout (plain files, readable without VaultMove)

```
<drive>\VaultMove\
  .vaultmove-vault.json          {"uuid": ..., "format": 1}
  index.sqlite                   index (a copy is cached in %APPDATA%\VaultMove\cache after each run)
  sources.json                   source id -> original folder
  log\2026-11.jsonl              append-only event log
  data\<source-id>\<path>        latest copy of each file (mtime preserved)
  _versions\<run time>\<source-id>\<path>   older copies
```

A source id is `<folder name>-<8 hex of the path hash>`, e.g. `Documents-1a2b3c4d`.

## Index

* `copies`: one row per stored blob. `is_current=1` marks the latest copy of a path (unique index); it is never
  pruned. Columns `valid_from`/`valid_to`/`gone_at` give each copy a time interval, which is what the timeline
  queries ("folder as of time T"). `offloaded_at` = removed from the PC by VaultMove; `gone_at` = deleted by the
  user; `keep_local` = restored to its original place, so it is not freed again straight away; `bad_at` = failed
  re-verification, so it is copied again.
* `events`: append-only (triggers abort UPDATE/DELETE), mirrored to `log/*.jsonl`.
* `pending`: write-ahead journal for multi-step operations (`store` for versioning a changed file, `offload` for
  deleting an original). Recovery runs at the start of each run.
* `runs`: one row per run; finished runs are the points of the timeline.

SQLite runs with `journal_mode=TRUNCATE`, `synchronous=FULL`. New-file inserts are batched (every 200 files or 2 s);
if a crash loses a batch, the next run finds the untracked vault file and keeps it as a recovered version rather
than overwriting it. Changed files are journalled individually before anything moves.

## Threading model

* One process owns the tray, scheduler, drive watcher and engine. The main window is created on first open and only
  hidden on close. The Browse & Restore tab is built on first use.
* Every engine call (backup, preview, restore, browse query, search, history) runs on `QThreadPool`. Results and
  progress come back through queued Qt signals. Each worker opens its own SQLite connection.
* Progress is throttled to 10 updates per second. Cancellation is a `threading.Event` checked per file and per 1 MB
  chunk.
* The backup worker thread runs with `THREAD_MODE_BACKGROUND_BEGIN` (low CPU + I/O priority) when "low priority" is
  on.
* A vault-wide lock (`msvcrt.locking` on `.vaultmove.lock`, released by the OS if the process dies) prevents two
  processes or threads from running on the same vault. A named mutex + authenticated pipe keeps one UI instance per
  settings folder (no QtNetwork).

## Triggers

* Schedule: a 60 s timer checks `last_run_at + interval` (wall-clock comparison, so sleep and clock changes are
  handled). Battery below the threshold skips runs and stops a running one.
* Drive plug-in: a hidden native top-level window receives `WM_DEVICECHANGE`/`WM_POWERBROADCAST`; a 5 s
  `GetLogicalDrives()` poll is the fallback. A run starts only when the vault itself (GUID + UUID) appears.
* Resume from sleep triggers a check 20 s later.

## Open files (VSS)

`helper/client.py` creates a named pipe with a fresh 256-bit key and starts `VaultMove.exe --vss-helper` through UAC
(`ShellExecuteW runas`). The elevated helper connects back (it cannot accept unelevated clients itself; this way
the unelevated app owns the pipe). Both sides authenticate with HMAC (`multiprocessing.connection` authkey). Only
JSON and raw bytes go over the pipe, never pickle. The helper creates a shadow copy with
`Win32_ShadowCopy.Create` via PowerShell. It serves read-only access to files under the backup folders given on its
command line, refuses any path whose components are reparse points inside the snapshot, deletes the snapshots, and
exits on quit, disconnect or 10 idle minutes. Bytes read from the snapshot go through the same verified `.vmtmp`
path as any copy.

## Updates (`core/update.py`, `app/updates.py`)

The only code that uses the network, and only after the user clicks **Check for Updates**: no background checks.
It sends a single `GET https://api.github.com/repos/<UPDATE_REPO>/releases/latest` with a generic User-Agent.

1. Only assets whose URL starts with `https://github.com/<UPDATE_REPO>/releases/download/` are considered.
2. The asset for this install type (`VaultMove-Setup-*.exe` or `VaultMove-Portable-*.exe`) is streamed to
   `.part` while hashing. It is refused unless it matches `SHA256SUMS.txt` from the same release.
3. Installed copies: the Setup runs with `/VERYSILENT /CLOSEAPPLICATIONS` (same AppId, so it's an in-place upgrade),
   and its `[Run] Check: WizardSilent` entry restarts VaultMove. Portable copies: the new exe is saved next to the old
   one and started with `--after-update <pid> <old exe>`. It waits for the old process to exit (it holds the
   single-instance mutex), then deletes only a `VaultMove-Portable-*.exe` in its own folder.
4. On start, a frozen VaultMove with start-with-Windows on rewrites the Run entry to its own path.

Limit: the checksum comes from the same GitHub release, so it protects against corrupted or swapped downloads but not
against someone who controls the GitHub account. Code signing (see README) would close that gap.

## Extending later (out of scope for v1)

Encryption or cloud targets would sit between `copier.write_verified_tmp` (bytes in) and the vault directory
(bytes out): a storage backend interface exposing `write_verified`, `place`, `move_to_version`, `read`. The safety
logic in `offload.py` only needs "re-hash the stored copy now", which a backend can provide, so it would not change.
