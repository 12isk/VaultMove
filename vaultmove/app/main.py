"""Entry point.

    VaultMove.exe                 open the window (or the setup wizard)
    VaultMove.exe --background    tray only (used by "Start with Windows")
    VaultMove.exe --portable      keep settings next to the exe
    VaultMove.exe --vss-helper …  elevated snapshot helper (started by VaultMove itself)
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys


def _setup_logging(cfg_dir: str):
    d = os.path.join(cfg_dir, "logs")
    os.makedirs(d, exist_ok=True)
    h = logging.handlers.RotatingFileHandler(os.path.join(d, "vaultmove.log"), maxBytes=2_000_000, backupCount=3,
                                             encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    lg = logging.getLogger("vaultmove")
    lg.setLevel(logging.INFO)
    lg.addHandler(h)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--vss-helper" in argv:
        from ..helper.server import main as helper_main
        return helper_main(argv)
    if "--selftest" in argv:
        return selftest(argv[argv.index("--selftest") + 1])

    p = argparse.ArgumentParser(prog="VaultMove")
    p.add_argument("--background", action="store_true")
    p.add_argument("--portable", action="store_true")
    p.add_argument("--config-dir")
    p.add_argument("--theme", choices=["light", "dark"])
    p.add_argument("--after-update", nargs=2, metavar=("OLD_PID", "OLD_EXE"))
    args, _rest = p.parse_known_args(argv)
    if args.after_update:
        # New portable exe: wait for the old one to quit (it holds the single-instance
        # mutex), then remove it. Settings live next to the exe and are shared.
        from ..core.update import finish_portable_update
        try:
            finish_portable_update(int(args.after_update[0]), args.after_update[1])
        except Exception:
            pass

    from ..core import config as cfgmod
    if args.config_dir:
        os.environ["VAULTMOVE_CONFIG_DIR"] = args.config_dir
    cfg_dir = cfgmod.config_dir(["--portable"] if args.portable else None)
    os.makedirs(cfg_dir, exist_ok=True)
    _setup_logging(cfg_dir)

    if os.name == "nt":
        try:  # own taskbar identity instead of python.exe's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VaultMove.Backup")
        except Exception:
            pass

    from PySide6.QtWidgets import QApplication

    from . import i18n, theme
    from .controller import AppController
    from .icon import make_icon
    from .singleinstance import SingleInstance

    app = QApplication(sys.argv[:1])
    app.setApplicationName("VaultMove")
    app.setOrganizationName("VaultMove")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_icon())

    inst = SingleInstance(cfg_dir)
    if not inst.acquire():
        inst.notify_first()
        return 0

    try:
        lang = cfgmod.load(cfg_dir).language
    except Exception:
        lang = "auto"
    i18n.install(app, lang)
    tm = theme.ThemeManager(app, {"light": False, "dark": True}.get(args.theme))
    ctrl = AppController(app, cfg_dir, portable=cfgmod.is_portable(["--portable"] if args.portable else None),
                         theme_mgr=tm)
    inst.showRequested.connect(ctrl.show_window)
    if ctrl.cfg_error:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "VaultMove", ctrl.cfg_error + "\n\nVaultMove will not change this file. "
                             "Fix or remove it, then restart VaultMove.")
    if not args.background or not ctrl.cfg.wizard_done:
        ctrl.show_window()
    rc = app.exec()
    ctrl.shutdown()
    return rc


def selftest(out_path: str) -> int:
    """Used by CI on the frozen exe: build every window against a throwaway
    config and vault, run one tiny backup, write a report, exit."""
    import tempfile
    import time
    import traceback
    lines = []
    try:
        from PySide6 import __version__ as pyside_version
        from PySide6.QtWidgets import QApplication

        from ..core import config as cfgmod, vault
        from ..core.config import Config, SourceCfg, make_source_id
        from . import i18n, theme
        from .controller import AppController
        from .dialogs import SettingsDialog
        from .wizard import SetupWizard

        tmp = tempfile.mkdtemp(prefix="vaultmove-selftest-")
        cdir, src, vdir = (os.path.join(tmp, n) for n in ("cfg", "src", "vault"))
        os.makedirs(src)
        with open(os.path.join(src, "hello.txt"), "w") as f:
            f.write("hello")
        vid = vault.create_vault(vdir)
        cfg = Config()
        cfg.vault = vault.vault_cfg_for(vdir, vid, allow_same_drive=True)
        cfg.sources = [SourceCfg(path=src, id=make_source_id(src))]
        cfg.wizard_done = True
        cfgmod.save(cfg, cdir)
        app = QApplication(sys.argv[:1])
        tr_obj = i18n.install(app, "fr")
        lines.append(f"pyside {pyside_version}; french loaded: {tr_obj is not None} "
                     f"({type(tr_obj).__name__ if tr_obj else '-'})")
        theme.ThemeManager(app)
        ctrl = AppController(app, cdir, enable_tray=False, enable_watch=False, enable_timer=False)
        ctrl.show_window()
        ctrl.window.set_tab(1)
        SetupWizard(ctrl).show()
        SettingsDialog(ctrl).show()
        done = {}
        ctrl.service.finished.connect(lambda d: done.update(d))
        ctrl.backup_now()
        t0 = time.time()
        while not done and time.time() - t0 < 60:
            app.processEvents()
            time.sleep(0.02)
        lines.append(f"backup: {done.get('status')} copied={(done.get('stats') or {}).get('copied')}")
        # The updater needs TLS in the bundle (no network is used here).
        import ssl
        import urllib.request  # noqa: F401
        from ..core import update
        ctx = ssl.create_default_context()
        certs = len(ctx.get_ca_certs()) + len(ssl.enum_certificates("ROOT"))
        lines.append(f"updater: {ssl.OPENSSL_VERSION}; root certs: {certs}; mode: {update.install_mode()}")
        ok = done.get("status") == "ok" and certs > 0
        lines.append("RESULT " + ("OK" if ok else "FAIL"))
    except Exception:
        lines.append(traceback.format_exc())
        lines.append("RESULT FAIL")
        ok = False
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
