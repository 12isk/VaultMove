"""Main window: 52 px top bar (app, tab switcher, search, settings), pages, toasts.

Layout per the macOS design skill: no sidebar (only two destinations), sparse
top bar for global actions with search always visible, content centre stage.
The real Windows title bar is kept (the project spec forbids faked chrome).
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt
from PySide6.QtGui import QAction, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QSizePolicy,
                               QStackedWidget, QVBoxLayout, QWidget)

from . import icon as icons
from . import theme
from .backup_tab import BackupTab
from .i18n import N_, tr
from .symbols import symbol
from .widgets import Card, EmptyState, SegmentBar, Toast, icon_button, kbd, label, refresh_symbols

SHORTCUTS = [
    (N_("General"), [("Ctrl+B", N_("Back Up Now")), ("Ctrl+.", N_("Stop the running backup")),
                      ("Ctrl+1", N_("Back Up page")), ("Ctrl+2", N_("Browse && Restore page")),
                      ("Ctrl+F", N_("Search all versions")), ("Ctrl+,", N_("Settings")),
                      ("Ctrl+/", N_("Keyboard shortcuts")), ("Ctrl+W", N_("Close the window (keeps running)"))]),
    (N_("Back Up"), [("Ctrl+N", N_("Add a folder")), ("Delete", N_("Remove the selected folder")),
                     ("Ctrl+P", N_("Preview"))]),
    (N_("Browse && Restore"), [("Enter", N_("Open folder")), ("Backspace", N_("Up one folder")),
                               ("Ctrl+R", N_("Restore")), ("Ctrl+Shift+R", N_("Restore To…")),
                               ("Ctrl+I", N_("Where Is It?")), ("Up / Down", N_("Move along the timeline")),
                               ("Esc", N_("Clear the search"))]),
]


class ShortcutSheet(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Keyboard shortcuts"))
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(14)
        v.addWidget(label(tr("Keyboard shortcuts"), "Title"))
        for group, items in SHORTCUTS:
            card = Card(shadow=False, margins=(16, 12, 16, 12), spacing=6)
            card.add(label(tr(group).replace("&&", "&"), "H2"))
            grid = QGridLayout()
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(6)
            for i, (keys, what) in enumerate(items):
                grid.addWidget(label(tr(what).replace("&&", "&")), i, 0)
                grid.addWidget(kbd(keys), i, 1, Qt.AlignRight)
            card.add(grid)
            v.addWidget(card)


class TopBar(QWidget):
    def __init__(self, win):
        super().__init__(win)
        self.setObjectName("TopBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(52)
        h = QHBoxLayout(self)
        h.setContentsMargins(18, 0, 14, 0)
        h.setSpacing(8)
        logo = QLabel(self)
        logo.setPixmap(QPixmap.fromImage(icons.render(64)).scaled(22, 22, Qt.KeepAspectRatio,
                                                                  Qt.SmoothTransformation))
        logo.setAccessibleName("VaultMove")
        name = label("VaultMove", "AppName")
        self.tabs = SegmentBar([tr("Back Up"), tr("Browse && Restore")], self)
        self.search = QLineEdit(self)
        self.search.setObjectName("Search")
        self.search.setPlaceholderText(tr("Search all versions") + "   Ctrl+F")
        self.search.setAccessibleName(tr("Search all versions"))
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(260)
        self._search_icon = self.search.addAction(symbol("search", 14, "subtext"), QLineEdit.LeadingPosition)
        self.btn_settings = icon_button("gear", tr("Settings (Ctrl+,)"), self)
        h.addWidget(logo)
        h.addWidget(name)
        h.addStretch(1)
        self.tabs.setSizePolicy(self.tabs.sizePolicy().horizontalPolicy(), QSizePolicy.Fixed)
        h.addWidget(self.tabs, 0, Qt.AlignVCenter)
        h.addStretch(1)
        h.addWidget(self.search)
        h.addWidget(self.btn_settings)

    def refresh_theme(self):
        self._search_icon.setIcon(symbol("search", 14, "subtext"))


class MainWindow(QMainWindow):
    def __init__(self, ctrl):
        super().__init__()
        self.ctrl = ctrl
        self.setWindowTitle("VaultMove")
        self.setWindowIcon(icons.make_icon())
        self.resize(1060, 740)
        self.setMinimumSize(860, 580)
        self._told_tray = False

        central = QWidget(self)
        central.setObjectName("Page")
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.top = TopBar(self)
        self.tabs = self.top.tabs
        self.search = self.top.search
        v.addWidget(self.top)

        body = QWidget(central)
        body.setObjectName("Page")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(20, 16, 20, 16)
        self.stack = QStackedWidget(body)
        self.backup_tab = BackupTab(ctrl, self)
        self.stack.addWidget(self.backup_tab)
        self.restore_tab = None  # created on first use (keeps startup light)
        self._restore_holder = QWidget(self)
        self.stack.addWidget(self._restore_holder)
        bl.addWidget(self.stack)
        v.addWidget(body, 1)
        self.setCentralWidget(central)
        self.toast = Toast(central)
        # Start with focus on the page itself, so no focus ring is drawn until the user presses Tab.
        central.setFocusPolicy(Qt.ClickFocus)
        self._central = central

        self.tabs.changed.connect(self.set_tab)
        self.top.btn_settings.clicked.connect(self.open_settings)
        self.search.textChanged.connect(self._search_changed)
        QShortcut(QKeySequence("Ctrl+1"), self, activated=lambda: self.set_tab(0))
        QShortcut(QKeySequence("Ctrl+2"), self, activated=lambda: self.set_tab(1))
        QShortcut(QKeySequence("Ctrl+,"), self, activated=self.open_settings)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=ctrl.backup_now)
        QShortcut(QKeySequence("Ctrl+."), self, activated=lambda: ctrl.service.cancel("user"))
        QShortcut(QKeySequence("Ctrl+W"), self, activated=self.close)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.focus_search)
        QShortcut(QKeySequence("Ctrl+/"), self, activated=self.show_shortcuts)
        QShortcut(QKeySequence(Qt.Key_Escape), self.search, activated=self.search.clear)
        if ctrl.theme_mgr is not None:
            ctrl.theme_mgr.changed.connect(self._theme_changed)

    # ------------------------------------------------------------------ navigation

    def set_tab(self, i: int):
        if i == 1 and self.restore_tab is None:
            from .restore_tab import RestoreTab
            self.restore_tab = RestoreTab(self.ctrl, self)
            self.stack.removeWidget(self._restore_holder)
            self._restore_holder.deleteLater()
            self.stack.insertWidget(1, self.restore_tab)
        changed = self.stack.currentIndex() != i
        self.tabs.set_index(i)
        self.stack.setCurrentIndex(i)
        if changed:
            self._slide_in(self.stack.currentWidget(), 1 if i == 1 else -1)
        if i == 1:
            self.restore_tab.activated()

    def _slide_in(self, w: QWidget, direction: int):
        """Every state change gets a transition: the new page glides in 24 px."""
        end = w.pos()
        a = QPropertyAnimation(w, b"pos", w)
        a.setStartValue(QPoint(end.x() + 24 * direction, end.y()))
        a.setEndValue(end)
        a.setDuration(theme.NORMAL)
        a.setEasingCurve(QEasingCurve.OutQuad)
        a.start(QPropertyAnimation.DeleteWhenStopped)

    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def _search_changed(self, text: str):
        if text.strip() and self.stack.currentIndex() != 1:
            self.set_tab(1)
        if self.restore_tab is not None:
            self.restore_tab.set_query(text)

    def show_shortcuts(self):
        ShortcutSheet(self).exec()

    def notify(self, text: str):
        """In-window toast (the tray balloon is used when the window is hidden)."""
        if self.isVisible():
            self.toast.show_message(text)

    def open_settings(self):
        from .dialogs import SettingsDialog
        if SettingsDialog(self.ctrl, self).exec():
            self.notify(tr("Settings saved"))
        self.backup_tab.refresh()

    def _theme_changed(self, _dark):
        for c in self.findChildren(Card):
            c.refresh_theme()
        for e in self.findChildren(EmptyState):
            e.refresh_theme()
        self.top.refresh_theme()
        refresh_symbols(self)
        if self.restore_tab is not None:
            self.restore_tab.model.refresh_icons()
            self.restore_tab.activated()
        self.backup_tab.refresh()
        self.update()

    def showEvent(self, e):  # noqa: N802
        super().showEvent(e)
        self._central.setFocus(Qt.OtherFocusReason)

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
