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
    sel = rt.view.selectionModel()
    from PySide6.QtCore import QItemSelectionModel
    sel.select(rt.model.index(0, 0), QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
    qtbot.wait(450)  # let the action bar finish sliding in
    shot(w, "03_browse_restore")
    assert rt._selected()
    assert rt.bar.shown, "the action bar appears when something is selected"
    # Drag out is copy-only (a move would take the file out of the backup).
    from PySide6.QtCore import Qt as _Qt
    assert rt.model.supportedDragActions() == _Qt.CopyAction
    md = rt.model.mimeData([rt.model.index(0, 0)])
    assert md.urls() and os.path.isfile(md.urls()[0].toLocalFile())
    dest = os.path.join(ctrl.cfg_dir, "restored")
    rt.restore(dest)
    qtbot.waitUntil(lambda: rt._last_result is not None, timeout=15000)
    assert len(rt._last_result.restored) == 1
    assert "Restored 1" in w.toast.text()
    assert os.listdir(dest)
    qtbot.wait(300)
    shot(w, "03b_restore_toast")


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
    w.search.setText("ideas")
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


def test_wizard_start_backup_without_clicking_preview(qtbot, qapp, tmp_path, monkeypatch):
    """Clicking Start Backup directly must work: it shows the preview first, then sets up."""
    from vaultmove.app import theme
    from vaultmove.app.controller import AppController
    from vaultmove.app.dialogs import PreviewDialog
    from vaultmove.app.wizard import SetupWizard
    from vaultmove.core import vault
    theme.apply(qapp, False)
    src = tmp_path / "MyDocs"
    src.mkdir()
    (src / "a.txt").write_bytes(b"hello")
    (tmp_path / "usb").mkdir()
    c = AppController(qapp, str(tmp_path / "cfg"), enable_tray=False, enable_watch=False, enable_timer=False)
    wz = SetupWizard(c)
    wz.show()
    wz.drive.set_dest(str(tmp_path / "usb" / "VaultMove"))
    if wz.drive.cb_same.isVisible():
        wz.drive.cb_same.setChecked(True)
    wz._next()
    lst = wz.folders.list
    from PySide6.QtCore import Qt
    for i in range(lst.count()):  # never scan the real Documents folder in a test
        lst.item(i).setCheckState(Qt.Unchecked)
    wz.folders._item(str(src), True)
    wz._next()
    assert wz.btn_next.isEnabled(), "Start Backup must be clickable before a preview"
    # Free up space on without the confirmation: disabled, and the page says why.
    wz.space.sw.setChecked(True)
    assert not wz.btn_next.isEnabled() and wz.space.hint.isVisible()
    wz.space.cb.setChecked(True)
    assert wz.btn_next.isEnabled() and not wz.space.hint.isVisible()
    wz.space.sw.setChecked(False)
    shown = []
    monkeypatch.setattr(PreviewDialog, "exec", lambda self: shown.append(self) or PreviewDialog.Accepted)
    with qtbot.waitSignal(wz.finishedSetup, timeout=30000):
        wz.btn_next.click()
    assert len(shown) == 1 and shown[0].btn_start.text() == "Start Backup"
    assert c.cfg.wizard_done
    assert [s.path for s in c.cfg.sources] == [str(src)]
    assert vault.read_marker(str(tmp_path / "usb" / "VaultMove"))["uuid"] == c.cfg.vault.uuid


def test_empty_states_shortcuts_and_drop(qtbot, qapp, tmp_path):
    """macOS-skill patterns: empty states with a call to action, cheat sheet, drag folders in."""
    from PySide6.QtCore import QMimeData, QPoint, QUrl, Qt
    from PySide6.QtGui import QDropEvent
    from vaultmove.app import theme
    from vaultmove.app.controller import AppController
    from vaultmove.app.mainwindow import ShortcutSheet
    from vaultmove.core import config as cfgmod, vault
    from vaultmove.core.config import Config
    theme.apply(qapp, False)
    vdir = tmp_path / "usb" / "VaultMove"
    vdir.parent.mkdir()
    vid = vault.create_vault(str(vdir))
    cfg = Config()
    cfg.vault = vault.vault_cfg_for(str(vdir), vid, allow_same_drive=True)
    cfg.wizard_done = True
    cdir = str(tmp_path / "cfg")
    cfgmod.save(cfg, cdir)
    c = AppController(qapp, cdir, enable_tray=False, enable_watch=False, enable_timer=False)
    c.show_window()
    w = c.window
    qtbot.waitExposed(w)
    bt = w.backup_tab
    assert bt.folders_empty.isVisible() and not bt.list.isVisible()
    shot(w, "15_empty_folders")
    w.set_tab(1)
    qtbot.waitUntil(lambda: w.restore_tab.empty.isVisible(), timeout=10000)
    shot(w, "16_empty_browse")
    w.set_tab(0)
    # Drop a folder from Explorer onto the folders card.
    folder = tmp_path / "Dropped Photos"
    folder.mkdir()
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(folder))])
    ev = QDropEvent(QPoint(10, 10), Qt.CopyAction, md, Qt.LeftButton, Qt.NoModifier)
    bt.eventFilter(bt.folders_card, ev)
    assert [s.path for s in c.cfg.sources] == [str(folder)]
    assert bt.list.isVisible() and not bt.folders_empty.isVisible()
    qtbot.wait(300)
    assert "Dropped Photos" in w.toast.text()
    shot(w, "17_folder_dropped_toast")
    sheet = ShortcutSheet(w)
    sheet.show()
    qtbot.waitExposed(sheet)
    shot(sheet, "18_shortcuts")
    sheet.reject()
    w.hide()


def test_this_pc_card_shows_storage(qtbot, ctrl):
    ctrl.show_window()
    tab = ctrl.window.backup_tab
    qtbot.waitExposed(ctrl.window)
    rows = [r for r in tab._pc_rows if r[0].isVisible()]
    assert rows, "This PC card shows at least one drive"
    name, bar, free = rows[0]
    assert "(" in name.text() and ":" in name.text()
    assert "free of" in free.text()
    # The bar shows the drive's real usage (CI runners can have a nearly empty drive -> 0).
    import shutil
    root = tab.pc_drives(ctrl.cfg)[0][0]
    u = shutil.disk_usage(root)
    assert bar.value() == int(1000 * (u.total - u.free) / max(1, u.total))


def test_update_dialog_offers_newer_version(qtbot, ctrl, monkeypatch):
    from vaultmove.app import updates as upd_ui
    from vaultmove.core import update
    rel = update.Release("9.9.9", "v9.9.9", "Bug fixes", "https://github.com/x", {
        "VaultMove-Setup-9.9.9.exe": update.DOWNLOAD_PREFIX + "v9.9.9/VaultMove-Setup-9.9.9.exe",
        "SHA256SUMS.txt": update.DOWNLOAD_PREFIX + "v9.9.9/SHA256SUMS.txt"})
    monkeypatch.setattr(update, "check_latest", lambda: rel)
    monkeypatch.setattr(update, "install_mode", lambda: "installer")
    d = upd_ui.UpdateDialog(ctrl)
    d.show()
    qtbot.waitUntil(lambda: d.btn_install.isVisible(), timeout=10000)
    assert "9.9.9" in d.status.text()
    shot(d, "14_update_available")
    d.reject()
    monkeypatch.setattr(update, "check_latest", lambda: update.Release("1.0.0", "v1.0.0", "", "", {}))
    d2 = upd_ui.UpdateDialog(ctrl)
    d2.show()
    qtbot.waitUntil(lambda: "up to date" in d2.status.text(), timeout=10000)
    assert not d2.btn_install.isVisible()
    d2.reject()


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


@pytest.mark.parametrize("answer", ["no", "yes"])
def test_settings_cloud_offload_needs_warning(qtbot, ctrl, monkeypatch, answer):
    from PySide6.QtWidgets import QMessageBox
    from vaultmove.app import dialogs
    from vaultmove.core import config as cfgmod
    asked = []

    def fake_warning(*a, **k):
        asked.append(a[2])
        return QMessageBox.Yes if answer == "yes" else QMessageBox.No
    monkeypatch.setattr(dialogs.QMessageBox, "warning", fake_warning)
    ctrl.show_window()
    s = dialogs.SettingsDialog(ctrl, ctrl.window)
    assert s.cloud.currentIndex() == 0
    s.cloud.setCurrentIndex(1)
    assert len(asked) == 1 and "OneDrive" in asked[0]
    assert s.cloud.currentIndex() == (1 if answer == "yes" else 0)
    if answer == "yes":
        shot(s, "07b_settings_cloud_on")
    s._save()
    assert ctrl.cfg.offload_cloud is (answer == "yes")
    assert cfgmod.load(ctrl.cfg_dir).offload_cloud is (answer == "yes")
