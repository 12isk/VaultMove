# VaultMove

Automatic, versioned backup of your folders to an external drive for Windows 10/11, with an optional extra:
once a file is safely backed up, verified and old enough, VaultMove can remove the original to free space on
the PC.

* Native window (PySide6 / Qt Widgets). No browser, no web server, no network access, no telemetry.
* Backups are plain files on the drive (`VaultMove\data\...`), readable even without VaultMove.
* Safety rules and the tests that enforce them: [SAFETY.md](SAFETY.md). Design: [ARCHITECTURE.md](ARCHITECTURE.md).
  What still needs a human: [MANUAL_TESTS.md](MANUAL_TESTS.md).

## Download (built by GitHub Actions)

Open the repository's **Actions** tab → latest successful **build** run → **Artifacts**:

* `VaultMove-Setup-x.y.z`: per-user installer (no admin needed). Start menu entry, optional "start with Windows",
  clean uninstall that never touches your backup drive.
* `VaultMove-Portable-x.y.z`: a single exe. Settings are kept in `VaultMove-Data\` next to the exe, so it runs
  from a USB stick. Open-file backup still works if you accept the admin prompt, and is skipped otherwise.
* `screenshots`: what every screen looks like (light, dark, French), captured during the tests.

The job summary of each run shows the exact sizes. In a local build of 1.0.0: **57.5 MB installed** and
**24.5 MB portable**. Idle in the tray: about 30 MB private memory (64 MB working set, including shared Qt DLLs).

### SmartScreen warning

The exes are not code-signed yet, so Windows shows "Windows protected your PC" the first time. Click **More info**
→ **Run anyway**. To remove the warning, buy a code-signing certificate and add two repository secrets:

* `WINDOWS_CERT_PFX_BASE64`: the `.pfx` file, base64 encoded (`[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx"))`)
* `WINDOWS_CERT_PASSWORD`: its password

The workflow signs the exes and the installer automatically when those secrets exist (`packaging/sign.ps1`). An EV
certificate removes the warning immediately; a standard OV certificate builds reputation over time.

## Using it

1. Plug in your backup drive and start VaultMove. A 3-step wizard asks for the drive, the folders and whether to
   free up space. A preview is always shown first.
2. Close the window: VaultMove stays in the notification area. It backs up every hour, whenever the drive is
   plugged in, and when you click **Back Up Now**.
3. **Browse & Restore**: pick a folder, slide the timeline on the right to a date, select files, click **Restore**.
   Restores never overwrite: an existing file is kept and the restored one gets `.restored` in its name. Every
   restored file is hash-checked against the backup.

## Run from source (no build tools needed)

Python 3.11+ only; no compiler, Node, Visual Studio or Docker.

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python -m pip install -r requirements.txt
```

```bash
.venv\Scripts\python run_vaultmove.py
```

Options: `--background` (tray only), `--portable` (settings next to the program), `--config-dir DIR` (separate
test settings), `--theme light|dark`. Without a compiled `.qm`, the French translation is read straight from
`vaultmove/app/i18n/vaultmove_fr.ts`.

Command-line harness (same engine, no UI):

```bash
.venv\Scripts\python -m vaultmove.cli --config-dir C:\vmtest-cfg init-vault E:\VaultMove
```

Other commands: `add-source`, `status`, `preview`, `backup`, `offload --enable --days 60 --i-understand`, `search`,
`history`, `restore`, `prune --older-than 365`, `rebuild-index`.

## Tests

```bash
.venv\Scripts\python -m pip install -r requirements-dev.txt
```

```bash
.venv\Scripts\python -m pytest
```

UI tests run offscreen (`QT_QPA_PLATFORM=offscreen`). The 200k-file performance test runs with
`VAULTMOVE_PERF=1`. Screenshots go to `.pytest-tmp\screenshots`, or to `VAULTMOVE_SCREENSHOTS` if set.

## How CI builds it

`.github/workflows/build.yml` on `windows-latest`:

1. installs the pinned `requirements*.txt`, compiles `vaultmove_fr.ts` → `.qm` with `pyside6-lrelease`, renders
   the icon (`packaging/make_icon.py`);
2. runs all tests, including crash injection, the real Recycle Bin and the 200k-file performance test, and uploads
   screenshots;
3. builds `dist\VaultMove\` (onedir, for the installer) and `VaultMove-Portable-x.y.z.exe` (onefile) with
   `packaging/vaultmove.spec`. Only QtCore/QtGui/QtWidgets are bundled, every other Qt module is excluded, unused
   Qt plugins, translations and the 20 MB software-OpenGL DLL are stripped, and UPX is not used (antivirus false
   positives);
4. starts both frozen exes with `--selftest`, which opens every window and runs a real backup;
5. signs (only if certificate secrets exist), builds the Inno Setup installer, prints the size report, uploads the
   artifacts.

To release: bump `__version__` in `vaultmove/__init__.py`, add a `CHANGELOG.md` entry, push a tag `v1.0.1`.

## Translations

UI strings go through `tr()`. After changing strings, run `python tools/make_ts.py` (fill in the French table in
that file). `tests/test_translations.py` fails if a string is untranslated or the `.ts` file is stale.
