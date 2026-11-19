"""Window sizing and display changes.

Two problems this solves:

* Windows sizes were fixed in logical pixels (1060 x 740 for the main window), which is taller than a
  1920 x 1080 screen at 150 % (1280 x 720 logical). Windows are now fitted to the screen they open on.
* When the display turns off (sleep, lid, monitor power-save) Windows can remove the monitor; Qt then moves
  windows to a 96-DPI placeholder screen. When the display comes back Windows may not send a DPI change to
  the window (from its point of view the DPI never changed), so the window stays drawn at 100 % and looks
  too small. ScreenWatcher re-attaches every visible window to its real screen, re-applies the theme so
  fonts are re-resolved, and keeps the window inside the screen.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QRect, QTimer
from PySide6.QtWidgets import QApplication, QWidget


def _screen_for(w: QWidget):
    app = QApplication.instance()
    s = None
    try:
        s = app.screenAt(w.frameGeometry().center())
    except Exception:
        s = None
    return s or (w.screen() if w.screen() in app.screens() else None) or app.primaryScreen()


def fit_rect(want_w: int, want_h: int, avail: QRect, frac: float = 0.92) -> tuple[int, int]:
    """Size that fits `avail` (leaving room for the title bar), never above what was asked for."""
    return (max(1, min(want_w, int(avail.width() * frac))),
            max(1, min(want_h, int(avail.height() * frac) - 32)))


def fit_to_screen(w: QWidget, want_w: int, want_h: int, center: bool = True):
    """Resize a window to (want_w, want_h) or less so it fits its screen, and centre it there."""
    s = _screen_for(w)
    if s is None:
        w.resize(want_w, want_h)
        return
    avail = s.availableGeometry()
    ww, hh = fit_rect(want_w, want_h, avail)
    mw, mh = w.minimumWidth(), w.minimumHeight()
    if mw > ww or mh > hh:  # a minimum larger than the screen would push the window off it
        w.setMinimumSize(min(mw, ww), min(mh, hh))
    w.resize(ww, hh)
    if center:
        fg = w.frameGeometry()
        fg.moveCenter(avail.center())
        w.move(max(avail.left(), fg.left()), max(avail.top(), fg.top()))


def clamp_rect(frame: QRect, avail: QRect) -> tuple[int, int, int, int]:
    """(x, y, w, h) of a frame moved/shrunk so it sits inside `avail`."""
    w = min(frame.width(), avail.width())
    h = min(frame.height(), avail.height())
    x = min(max(frame.left(), avail.left()), avail.right() + 1 - w)
    y = min(max(frame.top(), avail.top()), avail.bottom() + 1 - h)
    return x, y, w, h


def keep_on_screen(w: QWidget, screen=None):
    if w.isMaximized() or w.isFullScreen() or w.isMinimized():
        return
    s = screen or _screen_for(w)
    if s is None:
        return
    avail = s.availableGeometry()
    fg = w.frameGeometry()
    x, y, fw, fh = clamp_rect(fg, avail)
    if (fw, fh) != (fg.width(), fg.height()):
        dw, dh = fg.width() - w.width(), fg.height() - w.height()   # title bar and borders
        w.resize(max(w.minimumWidth(), fw - dw), max(w.minimumHeight(), fh - dh))
    if (x, y) != (fg.left(), fg.top()):
        w.move(x, y)


class ScreenWatcher(QObject):
    """Re-fits visible windows after a display is added/removed or changes scale."""

    def __init__(self, app: QApplication, reapply=None):
        super().__init__(app)
        self.app = app
        self.reapply = reapply
        self.fixes = 0
        self._timer = QTimer(self, singleShot=True, interval=400, timeout=self.fix)
        # Windows reports a returning display in stages; check again a little later.
        self._late = QTimer(self, singleShot=True, interval=2500, timeout=self.fix)
        app.screenAdded.connect(self._added)
        app.screenRemoved.connect(lambda *_: self.schedule())
        app.primaryScreenChanged.connect(lambda *_: self.schedule())
        for s in app.screens():
            self._watch(s)
        app.installEventFilter(self)

    def _watch(self, s):
        s.logicalDotsPerInchChanged.connect(lambda *_: self.schedule())
        s.geometryChanged.connect(lambda *_: self.schedule())
        s.availableGeometryChanged.connect(lambda *_: self.schedule())

    def _added(self, s):
        self._watch(s)
        self.schedule()

    def schedule(self):
        self._timer.start()
        self._late.start()

    def eventFilter(self, obj, ev):
        # Safety net: a window coming back to the front with a stale scale is fixed right away.
        try:
            t = ev.type()
            if t in (QEvent.WindowActivate, QEvent.Show) and isinstance(obj, QWidget) and obj.isWindow():
                if self._stale(obj):
                    self.schedule()
        except Exception:
            pass
        return False

    def _stale(self, w: QWidget) -> bool:
        h = w.windowHandle()
        if h is None:
            return False
        cur = h.screen()
        if cur is None or cur not in self.app.screens():
            return True
        return abs(w.devicePixelRatioF() - cur.devicePixelRatio()) > 0.01

    def fix(self):
        self.fixes += 1
        screens = self.app.screens()
        changed = False
        for w in self.app.topLevelWidgets():
            if not w.isVisible() or not w.isWindow():
                continue
            h = w.windowHandle()
            if h is None:
                continue
            target = _screen_for(w)
            if target is None:
                continue
            if h.screen() not in screens or h.screen() != target or self._stale(w):
                h.setScreen(target)
                changed = True
            keep_on_screen(w, target)
        if self.reapply is not None:
            self.reapply()   # re-polishes every widget, so fonts and metrics follow the new scale
        for w in self.app.topLevelWidgets():
            if w.isVisible():
                lay = w.layout()
                if lay is not None:
                    lay.invalidate()
                    lay.activate()
                w.updateGeometry()
                w.update()
        return changed
