"""UI smoke tests (pytest-qt, QT_QPA_PLATFORM=offscreen) + screenshots for review.

Screenshots go to $VAULTMOVE_SCREENSHOTS (CI uploads them as an artifact).
"""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The offscreen platform has no font database on Windows unless pointed at the fonts folder.
os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
pytest.importorskip("PySide6")
pytestmark = pytest.mark.ui

from PySide6.QtCore import QElapsedTimer, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from tests.helpers import DAY  # noqa: E402

SHOTS = os.environ.get("VAULTMOVE_SCREENSHOTS") or os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), ".pytest-tmp", "screenshots")


def shot(widget, name):
    os.makedirs(SHOTS, exist_ok=True)
    QApplication.processEvents()
    widget.grab().save(os.path.join(SHOTS, name + ".png"))


@pytest.fixture
def ctrl(qapp, env):
    from vaultmove.app import theme
    from vaultmove.app.controller import AppController
    theme.apply(qapp, False)
    for i in range(30):
        env.write(f"Projects/report_{i:02d}.docx", os.urandom(2000 + i * 300), age_days=i * 3)
    env.write("Photos/holiday.jpg", os.urandom(250_000), age_days=200)
    env.write("Notes/ideas.txt", b"ideas")
    env.cfg.wizard_done = True
    env.cfg.vault.allow_same_drive = True   # temp dirs share one disk; no offload can happen
    env.save_cfg()
    c = AppController(qapp, env.cfg_dir, enable_tray=False, enable_watch=False, enable_timer=False)
    yield c
    if c.window is not None:
        c.window.hide()
        c.window.deleteLater()


def _wait_backup(qtbot, ctrl, timeout=60000):
    with qtbot.waitSignal(ctrl.service.finished, timeout=timeout) as blocker:
        assert ctrl.backup_now()
    return blocker.args[0]


def test_window_opens_and_tabs_switch(qtbot, ctrl):
    ctrl.show_window()
    w = ctrl.window
    qtbot.waitExposed(w)
    assert w.isVisible()
    assert w.stack.currentIndex() == 0
    shot(w, "01_backup_tab_before_first_backup")
    w.set_tab(1)
    assert w.stack.currentIndex() == 1
    assert w.restore_tab is not None
    w.set_tab(0)
    assert w.stack.currentIndex() == 0
    # Closing hides (tray app); the controller survives.
    w.close()
    assert ctrl.window is w


def test_backup_runs_and_ui_stays_responsive(qtbot, ctrl):
    ctrl.show_window()
    w = ctrl.window
    qtbot.waitExposed(w)
    gaps = []
    clock = QElapsedTimer()
    clock.start()
    last = [clock.elapsed()]

    def beat():
        now = clock.elapsed()
        gaps.append(now - last[0])
        last[0] = now

    t = QTimer()
    t.setInterval(10)
    t.timeout.connect(beat)
    t.start()
    result = _wait_backup(qtbot, ctrl)
    t.stop()
    assert result["status"] == "ok", result
    assert result["stats"]["copied"] == 32
    assert max(gaps) < 500, f"UI thread blocked for {max(gaps)} ms"
    assert ctrl.cfg.last_run_status == "ok"
    w.backup_tab.collapsible.toggle.setChecked(True)
    qtbot.wait(300)
    shot(w, "02_backup_tab_after_backup")

    # Browse & Restore shows the backed-up folders.
    w.set_tab(1)
    rt = w.restore_tab
    qtbot.waitUntil(lambda: rt.model.rowCount() >= 3, timeout=10000)
    names = {rt.model.row(i)["name"] for i in range(rt.model.rowCount())}
    assert {"Projects", "Photos", "Notes"} <= names
    # Open a folder, select a file, restore it to another folder.
    for i in range(rt.model.rowCount()):
        if rt.model.row(i)["name"] == "Projects":
            rt._open(rt.model.index(i, 0))
    qtbot.waitUntil(lambda: rt.model.rowCount() == 30, timeout=10000)
    rt.view.selectRow(0) if hasattr(rt.view, "selectRow") else rt.view.setCurrentIndex(rt.model.index(0, 0))
    qtbot.wait(100)
    shot(w, "03_browse_restore")
    sel = rt.view.selectionModel()
    from PySide6.QtCore import QItemSelectionModel
    sel.select(rt.model.index(0, 0), QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
    assert rt._selected()
    dest = os.path.join(ctrl.cfg_dir, "restored")
    from PySide6.QtWidgets import QMessageBox
    msgs = []
    orig_info = QMessageBox.information
    QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(a[2]) or QMessageBox.Ok)
    try:
        rt.restore(dest)
        qtbot.waitUntil(lambda: bool(msgs), timeout=15000)
    finally:
        QMessageBox.information = orig_info
    assert "Restored 1" in msgs[0]
    assert os.listdir(dest)


def test_timeline_and_search(qtbot, ctrl, env):
    ctrl.show_window()
    w = ctrl.window
    _wait_backup(qtbot, ctrl)
    p = env.path("Notes/ideas.txt")
    with open(p, "wb") as f:
        f.write(b"ideas, second version")
    time.sleep(0.05)
    _wait_backup(qtbot, ctrl)
    w.set_tab(1)
    rt = w.restore_tab
    qtbot.waitUntil(lambda: len(rt.timeline.times) >= 3, timeout=10000)
    rt.timeline.setFocus()
    rt.timeline.set_index(len(rt.timeline.times) - 1)  # oldest backup
    qtbot.wait(400)
    rt.search.setText("ideas")
    qtbot.waitUntil(lambda: rt.model.rowCount() == 2, timeout=10000)
    statuses = {rt.model.row(i)["status"] for i in range(2)}
    assert statuses == {"local", "older"}
    shot(w, "04_search_all_versions")


def test_dark_mode_and_dialogs(qtbot, ctrl, qapp):
    from vaultmove.app import theme
    from vaultmove.app.dialogs import HistoryDialog, PreviewDialog, SettingsDialog
    from vaultmove.app.wizard import SetupWizard
    _wait_backup(qtbot, ctrl)
    theme.apply(qapp, True)
    ctrl.show_window()
    w = ctrl.window
    qtbot.waitExposed(w)
    w._theme_changed(True)
    shot(w, "05_backup_tab_dark")
    w.set_tab(1)
    qtbot.waitUntil(lambda: w.restore_tab.model.rowCount() >= 3, timeout=10000)
    shot(w, "06_browse_restore_dark")
    theme.apply(qapp, False)
    w._theme_changed(False)

    s = SettingsDialog(ctrl, w)
    s.show()
    qtbot.waitExposed(s)
    shot(s, "07_settings")
    s.reject()

    from vaultmove.core.engine import Engine
    res = Engine(ctrl.cfg, same_disk_fn=lambda a, b: False).preview()
    pd = PreviewDialog(res, w)
    pd.show()
    shot(pd, "08_preview")
    pd.reject()

    sid = ctrl.cfg.sources[0].id
    hd = HistoryDialog(ctrl, sid, os.path.join("Notes", "ideas.txt"), w)
    hd.show()
    qtbot.waitUntil(lambda: hd.tree.topLevelItemCount() >= 1, timeout=10000)
    shot(hd, "09_history")
    hd.reject()


def test_wizard_pages(qtbot, qapp, tmp_path, monkeypatch):
    from vaultmove.app import theme
    from vaultmove.app.controller import AppController
    from vaultmove.app.wizard import SetupWizard
    theme.apply(qapp, False)
    cdir = str(tmp_path / "cfg")
    c = AppController(qapp, cdir, enable_tray=False, enable_watch=False, enable_timer=False)
    wz = SetupWizard(c)
    wz.show()
    qtbot.waitExposed(wz)
    shot(wz, "10_wizard_1_drive")
    usb = tmp_path / "usb"
    usb.mkdir()
    wz.drive.set_dest(str(usb / "VaultMove"))
    if wz.drive.cb_same.isVisible():
        wz.drive.cb_same.setChecked(True)
    assert wz.btn_next.isEnabled()
    wz._next()
    shot(wz, "11_wizard_2_folders")
    wz._next()
    wz.space.sw.setChecked(True)
    qtbot.wait(250)
    shot(wz, "12_wizard_3_free_space")
    assert not wz.btn_next.isEnabled()  # preview + confirmation required first
    wz.reject()


def test_french_ui(qtbot, qapp, env):
    from vaultmove.app import theme
    from vaultmove.app.controller import AppController
    from vaultmove.app.i18n import I18N_DIR, TsTranslator
    t = TsTranslator(os.path.join(I18N_DIR, "vaultmove_fr.ts"))
    qapp.installTranslator(t)
    try:
        theme.apply(qapp, False)
        env.cfg.wizard_done = True
        env.save_cfg()
        c = AppController(qapp, env.cfg_dir, enable_tray=False, enable_watch=False, enable_timer=False)
        c.show_window()
        w = c.window
        qtbot.waitExposed(w)
        assert w.backup_tab.btn_backup.text() == "Sauvegarder maintenant"
        shot(w, "13_backup_tab_french")
        w.hide()
        w.deleteLater()
    finally:
        qapp.removeTranslator(t)


def test_icon_renders_all_states(qapp):
    from vaultmove.app import icon
    os.makedirs(SHOTS, exist_ok=True)
    for st in icon.STATES:
        img = icon.render(128, st, 0.4 if st == "running" else None)
        assert not img.isNull()
        img.save(os.path.join(SHOTS, f"icon_{st}.png"))
