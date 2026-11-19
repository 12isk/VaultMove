# Manual tests

Automated tests cover the engine, crash recovery, the UI (offscreen) and the frozen exe's self-test. The items
below need real hardware, a real desktop session or administrator rights, and were **not** run automatically.
Run them on a fresh Windows 11 VM (or PC) with a USB drive.

## What is verified and what is not

| Area | Status |
|---|---|
| Core engine, invariants, crash injection, faults, e2e, CLI | Automated; passing locally (Windows 11, Python 3.11) and in CI |
| 200k-file incremental scan | Automated; 5.1 s locally on an SSD (limit 60 s) |
| UI windows, tabs, backup from UI, restore from UI, timeline, search, French | Automated offscreen + screenshots |
| Frozen onedir and onefile exes start, show windows, load French, run a backup | Automated (`--selftest`), run locally and in CI |
| Inno Setup installer build | **CI only** (not built locally) |
| Installer install / uninstall | **Manual** (below) |
| Real USB plug/unplug (`WM_DEVICECHANGE`) | **Manual** (the polling fallback is automated) |
| Tray icon, menu, balloon notifications on a real desktop | **Manual** |
| Real VSS snapshot through UAC | **Manual** (protocol and path policy are automated with a fake snapshot) |
| Recycle Bin with a real file | CI only (`VAULTMOVE_REAL_RECYCLE=1`) |
| Symlink not followed | Skipped without Developer Mode; junctions always tested |
| Start with Windows after a real sign-in | **Manual** (registry value itself is automated) |
| Sleep / resume, battery threshold on a laptop | **Manual** (logic automated with a fake power status) |
| High DPI 150 %/200 %, text scaling, screen reader names | **Manual** |
| Code signing | Not done (no certificate yet) |

## Checklist

Prepare: a test folder `C:\VMTest` with a few files, including one file older than 30 days. Make one with
PowerShell: `(Get-Item C:\VMTest\old.txt).LastWriteTime = (Get-Date).AddDays(-90)`. Note its SHA-256:
`Get-FileHash C:\VMTest\old.txt`.

1. **Install**: run `VaultMove-Setup-x.y.z.exe`. SmartScreen: "More info" → "Run anyway". No admin prompt (per-user
   install). Keep "Start VaultMove when I sign in" ticked. VaultMove opens the setup wizard.
2. **Wizard**: step 1 lists your USB drive first and shows free space. Pick it. A folder on `C:` shows the
   same-disk warning and requires the extra tick. Step 2: untick the defaults, add `C:\VMTest`. Step 3: turn on
   "Free up space", 30 days. **Start Backup stays disabled** until you click Preview and tick the confirmation. The
   preview lists `old.txt` under "Freed after this backup is verified" and nothing under "Will be freed".
3. **First backup**: starts automatically. The tray icon shows progress. `E:\VaultMove\data\<id>\` contains your
   files. `old.txt` is still on the PC (it is only freed on a later run).
4. **Tray**: close the window. A notification says VaultMove is still running. Right-click the tray icon: Back Up
   Now, Open VaultMove, Browse Backups, Pause/Resume, Quit all work. Left-click opens the window.
5. **Offload**: click Back Up Now again. `old.txt` disappears from `C:\VMTest` and is in the Recycle Bin (first
   week). In Browse & Restore it shows "Backup drive only". "Where Is It?" says it was removed after verification
   and names its vault path.
6. **Versioning**: edit a file in `C:\VMTest`, Back Up Now. `_versions\<time>\...` holds the old copy. In Browse &
   Restore, move the timeline to the previous backup: the old content is listed.
7. **Unplug / replug**: safely remove the USB drive. The status says "Backup drive not connected" and nothing is
   written to C:. Change a file, plug the drive back in: within ~10 s a backup starts by itself. Also try a
   different drive letter (Disk Management → change letter): it is still recognised.
8. **Restore an offloaded file**: select `old.txt`, Restore. It returns to `C:\VMTest\old.txt`. `Get-FileHash`
   matches the value noted at the start. It is not freed again on the next run.
9. **No overwrite**: restore a file that still exists locally with different content. You get
   `name.restored.ext` next to it; the local file is unchanged.
10. **Open file (VSS)**: open a file so it is locked, e.g. an Outlook `.pst` or a SQLite DB held open. A scheduled
    run reports it as skipped. Back Up Now: a UAC prompt appears; accept it, and the file is copied from a snapshot.
    Decline it, and the file is skipped with a clear message. Afterwards, `vssadmin list shadows` (admin) shows no
    leftover VaultMove snapshot.
11. **Start with Windows**: sign out and in. VaultMove starts in the tray with no window.
12. **Single instance**: start VaultMove again from the Start menu. The existing window comes forward; no second
    tray icon.
13. **Portable**: copy `VaultMove-Portable-x.y.z.exe` to a USB stick and run it. Settings appear in
    `VaultMove-Data\` next to the exe, not in `%APPDATA%`.
14. **Display**: set Windows scaling to 150 % and 200 % and switch light/dark mode while VaultMove is open: text is
    crisp and the theme follows. Tab through the Back Up page and the wizard with the keyboard only. Narrator reads
    the button and list names.
15. **Laptop**: unplug the charger below the battery threshold (Settings). Scheduled backups pause; plugging back in
    resumes them. Sleep and wake: a backup check happens within a minute.
16. **Uninstall**: Settings → Apps → VaultMove → Uninstall. Choose whether to keep settings. The backup drive is
    untouched, and the Run entry is gone (`reg query HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).
17. **Language**: Settings → Language → Français, restart. All texts are French, including standard buttons.
18. **In-app update (installed)**: with 1.1.0 installed and a newer release published, go to Settings → Check for
    Updates. It shows the new version and notes. Click Download and Install: VaultMove closes, upgrades silently and
    reopens. Settings → version shows the new number; backups and folders are unchanged. Start a backup first:
    installing is refused while it runs.
19. **In-app update (portable)**: same from `VaultMove-Portable-1.1.0.exe` on a USB stick. The new exe appears
    next to it, starts, and the old exe is removed. `VaultMove-Data` is kept.
20. **This PC card**: the Back Up page shows the drive(s) of your folders with free space; fill a drive above 90 %
    and the text turns orange ("almost full").
