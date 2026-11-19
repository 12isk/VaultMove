"""Tray-app behaviour without a window: scheduling, pause, battery, drive plug-in,
single instance, start-with-Windows (against a throwaway registry key)."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
pytest.importorskip("PySide6")
pytestmark = pytest.mark.ui

from vaultmove.core import winapi  # noqa: E402


@pytest.fixture
def ctrl(qapp, env):
    from vaultmove.app.controller import AppController
    env.write("a.txt", b"hello")
    env.cfg.wizard_done = True
    env.cfg.vault.allow_same_drive = True
    env.save_cfg()
    c = AppController(qapp, env.cfg_dir, enable_tray=False, enable_watch=False, enable_timer=False)
    return c


def test_scheduled_tick_starts_backup_when_due(qtbot, ctrl):
    ctrl.cfg.last_run_at = time.time() - 2 * 3600
    with qtbot.waitSignal(ctrl.service.finished, timeout=30000) as b:
        ctrl.tick()
        assert ctrl.service.busy
    assert b.args[0]["status"] == "ok" and b.args[0]["manual"] is False
    # Not due right after a run.
    ctrl.tick()
    assert not ctrl.service.busy


def test_paused_never_runs(ctrl):
    ctrl.cfg.paused = True
    ctrl.cfg.last_run_at = None
    ctrl.tick()
    assert not ctrl.service.busy


def test_low_battery_skips_run(qtbot, ctrl, monkeypatch):
    monkeypatch.setattr(winapi, "power_status", lambda: (False, 12))
    ctrl.cfg.last_run_at = None
    ctrl.tick()
    assert not ctrl.service.busy
    monkeypatch.setattr(winapi, "power_status", lambda: (True, 12))
    with qtbot.waitSignal(ctrl.service.finished, timeout=30000):
        ctrl.tick()
        assert ctrl.service.busy


def test_clock_set_back_still_runs(qtbot, ctrl):
    ctrl.cfg.last_run_at = time.time() + 5 * 86400  # last run "in the future"
    with qtbot.waitSignal(ctrl.service.finished, timeout=30000):
        ctrl.tick()
        assert ctrl.service.busy


def test_drive_plug_in_triggers_backup(qtbot, ctrl, env):
    os.rename(env.vault, env.vault + "-unplugged")
    assert ctrl.refresh_vault() is None
    ctrl.cfg.last_run_at = time.time()  # not due by schedule
    os.rename(env.vault + "-unplugged", env.vault)
    with qtbot.waitSignal(ctrl.service.finished, timeout=30000) as b:
        ctrl._on_volumes()
        assert ctrl.service.busy
    assert b.args[0]["status"] == "ok"


def test_drive_plug_in_ignores_other_drives(ctrl):
    ctrl.cfg.last_run_at = time.time()
    assert ctrl.refresh_vault()
    ctrl._on_volumes()  # vault was already connected: some other drive appeared
    assert not ctrl.service.busy


def test_status_texts(ctrl):
    state, title, _ = ctrl.status()
    assert state == "idle"
    ctrl.cfg.paused = True
    assert ctrl.status()[0] == "paused"


@pytest.mark.skipif(not winapi.IS_WIN, reason="named mutex / pipes")
def test_single_instance(qtbot, tmp_path):
    from vaultmove.app.singleinstance import SingleInstance
    d = str(tmp_path / "cfg")
    first = SingleInstance(d)
    assert first.acquire() is True
    second = SingleInstance(d)
    assert second.acquire() is False
    with qtbot.waitSignal(first.showRequested, timeout=10000):
        assert second.notify_first()


@pytest.mark.skipif(not winapi.IS_WIN, reason="registry")
def test_start_with_windows_registry(monkeypatch):
    import winreg
    from vaultmove.app import startup
    monkeypatch.setattr(startup, "RUN_KEY", r"Software\VaultMoveTest\Run")
    try:
        startup.set_enabled(True)
        assert startup.is_enabled()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, startup.RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, startup.VALUE)
        assert "--background" in val
        startup.set_enabled(False)
        assert not startup.is_enabled()
    finally:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\VaultMoveTest\Run")
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, r"Software\VaultMoveTest")
        except OSError:
            pass


def test_device_watcher_poll_detects_mask_change(qtbot, monkeypatch):
    from vaultmove.app import devicewatch
    masks = [0b100, 0b10100]
    monkeypatch.setattr(winapi, "logical_drives_mask", lambda: masks[0])
    w = devicewatch.DeviceWatcher(poll_ms=50)
    w._debounce.setInterval(10)
    masks[0] = masks[1]
    with qtbot.waitSignal(w.volumesChanged, timeout=3000):
        pass
    w.deleteLater()
