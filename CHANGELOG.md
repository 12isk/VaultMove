# Changelog

## 1.1.1

* **Free space in OneDrive folders (opt-in).** New setting *Cloud folders (OneDrive…)* in Settings:
  * *Back up only, never free space* (default, same as before);
  * *Back up and free space (also deletes from the cloud)*, which asks for confirmation first: a freed file is
    also deleted from OneDrive online and from your other devices, so the backup drive holds the only copy.
  Online-only files (not on this PC) are never freed, and every other safety check still applies.
  The folder list shows which setting is in effect for each cloud folder.

## 1.1.0

* **Check for Updates** (Settings): downloads the new version from this project's GitHub Releases, verifies its
  SHA-256 checksum, and upgrades in place (installed or portable). Settings and backups are kept. VaultMove only
  goes online when you click the button.
* **This PC** card on the Back Up page: used and free space of the drive(s) holding your backed-up folders.
* **New look**, following the macOS design skill:
  * a 52 px top bar with search always visible (Ctrl+F) and a settings gear;
  * Apple's type scale and colours, 8 px cards, hairline edges, monoline icons;
  * keyboard hints next to the actions and a shortcut cheat sheet (Ctrl+/);
  * toasts for confirmations and proper empty states;
  * a floating action bar that appears when files are selected;
  * new shortcuts: Ctrl+R, Ctrl+Shift+R, Ctrl+I, Ctrl+N, Ctrl+P, Ctrl+.;
  * drag folders in from Explorer, drag files out (copy only, so a drag can never move a file out of the backup);
  * a page-slide transition.
  The standard Windows title bar is kept.
* **Safety:** files in a OneDrive folder could be freed (sent to the Recycle Bin), which also removes them from
  OneDrive. Cause: Windows disguises OneDrive placeholders from apps that don't opt in, so the folder looked
  ordinary. VaultMove now opts in and never frees space in any cloud-synced folder (still backs it up).
* Setup wizard: Start Backup works without clicking Preview first (it shows the preview, then starts).

## 1.0.0 (unreleased)

First version.

* Versioned backup of chosen folders to an external drive, identified by volume GUID + vault UUID.
* Incremental scan (size + mtime, hash on mismatch); 200k unchanged files in ~5 s on an SSD.
* Older copies kept in `_versions/`, thinned to all of the last 24 h, daily for a month, weekly after.
* Optional "free up space" (offload): off by default, needs confirmation and a preview, verifies both the original
  and the copy before deleting, Recycle Bin during the first week.
* Crash-safe: verified `.vmtmp` writes, write-ahead journal, recovery on next run; append-only event log.
* Browse & Restore with a timeline, search across all versions, "Where Is It?" history, verified restore that never
  overwrites.
* Tray app: scheduled runs, run on drive plug-in, pause on low battery, low-priority I/O, start with Windows.
* Open-file backup through an elevated VSS helper (manual Back Up Now only).
* English and French. Light and dark themes following Windows.
* CLI harness (`python -m vaultmove.cli`).
* GitHub Actions: tests, 200k-file performance test, screenshots, PyInstaller onedir + onefile, Inno Setup
  installer, size report, optional code signing.
