"""Main window: header with segmented tab switcher, Back Up and Browse & Restore pages."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QStackedWidget, QToolButton, QVBoxLayout, QWidget

from . import icon as icons
from .backup_tab import BackupTab
from .i18n import tr
from .widgets import Card, SegmentBar


class MainWindow(QMainWindow):
    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self.setWindowTitle("VaultMove")
        self.setWindowIcon(icons.make_icon())
        self.resize(1040, 720)
        self.setMinimumSize(820, 560)
        self._told_tray = False

        central = QWidget(self)
        central.setObjectName("Page")
        v = QVBoxLayout(central)
        v.setContentsMargins(24, 14, 24, 18)
        v.setSpacing(12)

        head = QHBoxLayout()
        logo = QLabel(self)
        logo.setPixmap(QPixmap.fromImage(icons.render(64)).scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setAccessibleName("VaultMove")
        name = QLabel("VaultMove", self)
        name.setObjectName("AppName")
        self.tabs = SegmentBar([tr("Back Up"), tr("Browse && Restore")], self)
        self.tabs.changed.connect(self.set_tab)
        self.btn_settings = QToolButton(self)
        self.btn_settings.setText(tr("Settings"))
        self.btn_settings.setAccessibleName(tr("Settings"))
        self.btn_settings.setToolTip(tr("Settings (Ctrl+,)"))
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.clicked.connect(self.open_settings)
        head.addWidget(logo)
        head.addSpacing(6)
        head.addWidget(name)
        head.addStretch(1)
        head.addWidget(self.tabs)
        head.addStretch(1)
        head.addWidget(self.btn_settings)
        v.addLayout(head)

        self.stack = QStackedWidget(self)
        self.backup_tab = BackupTab(ctrl, self)
        self.stack.addWidget(self.backup_tab)
        self.restore_tab = None  # created on first use (keeps startup light)
        self._restore_holder = QWidget(self)
        self.stack.addWidget(self._restore_holder)
        v.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        QShortcut(QKeySequence("Ctrl+1"), self, activated=lambda: self.set_tab(0))
        QShortcut(QKeySequence("Ctrl+2"), self, activated=lambda: self.set_tab(1))
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self.open_settings)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=ctrl.backup_now)
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self.close)
        if ctrl.theme_mgr is not None:
            ctrl.theme_mgr.changed.connect(self._theme_changed)

    def set_tab(self, i: int):
        if i == 1 and self.restore_tab is None:
            from .restore_tab import RestoreTab
            self.restore_tab = RestoreTab(self.ctrl, self)
            self.stack.removeWidget(self._restore_holder)
            self._restore_holder.deleteLater()
            self.stack.insertWidget(1, self.restore_tab)
        self.tabs.set_index(i)
        self.stack.setCurrentIndex(i)
        if i == 1:
            self.restore_tab.activated()

    def open_settings(self):
        from .dialogs import SettingsDialog
        SettingsDialog(self.ctrl, self).exec()
        self.backup_tab.refresh()

    def _theme_changed(self, _dark):
        for c in self.findChildren(Card):
            c.refresh_theme()
        self.update()

    def closeEvent(self, e):  # noqa: N802
        # Closing hides to the tray; backups keep running.
        if self.ctrl.tray is not None and not self.ctrl._quitting:
            e.ignore()
            self.hide()
            if not self._told_tray:
                self._told_tray = True
                self.ctrl.tray.notify("tray", tr("VaultMove is still running"),
                                      tr("Backups continue in the background. Find VaultMove in the "
                                         "notification area."), min_interval=7 * 86400)
        else:
            e.accept()
