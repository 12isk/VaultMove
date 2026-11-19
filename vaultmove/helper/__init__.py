"""Elevated Volume Shadow Copy helper (open-file backup).

The UI process never runs elevated. When a manual backup meets files that are
in use, it starts this helper through UAC. The helper:

* connects back to a named pipe owned by the unelevated app, with mutual HMAC
  authentication (multiprocessing.connection authkey, a fresh 256-bit key per
  session passed on the elevated command line);
* exchanges only JSON and raw bytes (never pickle);
* exposes exactly: open a file from a snapshot (read-only), read, close, quit;
* only serves paths under the backup source folders given at launch, and
  refuses any path whose components are reparse points inside the snapshot;
* creates/deletes snapshots with the built-in Win32_ShadowCopy WMI class via
  PowerShell (no SDK), deletes them on exit, and exits after 10 idle minutes.
"""
