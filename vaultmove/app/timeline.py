"""Vertical timeline along the right edge: scrub through backup dates.

Points are thinned like versions (every run in the last 24 h, one per day for
a month, one per week after) so a year of hourly runs stays usable.
Keyboard: Up/Down, PageUp/PageDown, Home (= Now), End (= oldest).
"""

from __future__ import annotations

import datetime as dt
import time

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..core.retention import bucket
from . import theme
from .i18n import tr

NOW = 0.0


def thin_times(times: list[float], now: float | None = None) -> list[float]:
    now = time.time() if now is None else now
    seen, out = set(), []
    for t in sorted(times, reverse=True):
        b = bucket(t, now, int(t * 1000))
        if b in seen:
            continue
        seen.add(b)
        out.append(t)
    return out


class Timeline(QWidget):
    currentChanged = Signal(float)   # NOW (0.0) or a timestamp

    def __init__(self, parent=None):
        super().__init__(parent)
        self.times: list[float] = [NOW]
        self.index = 0
        self._marker = 0.0
        self._drag = False
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.setAccessibleName(tr("Timeline"))
        self.setToolTip(tr("Scrub to see your files as they were. Up/Down keys move between backups."))
        self._anim = QPropertyAnimation(self, b"marker", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._emit = QTimer(self)
        self._emit.setSingleShot(True)
        self._emit.setInterval(160)
        self._emit.timeout.connect(lambda: self.currentChanged.emit(self.current()))

    def sizeHint(self) -> QSize:
        return QSize(160, 400)

    def _get_marker(self):
        return self._marker

    def _set_marker(self, v):
        self._marker = v
        self.update()

    marker = Property(float, _get_marker, _set_marker)

    def set_times(self, times: list[float]):
        cur = self.current()
        self.times = [NOW] + thin_times([t for t in times if t])
        self.index = self.times.index(cur) if cur in self.times else 0
        self._marker = self._y(self.index)
        self._describe()
        self.update()

    def current(self) -> float:
        return self.times[self.index] if self.times else NOW

    def set_index(self, i: int, animate: bool = True):
        i = max(0, min(len(self.times) - 1, i))
        if i == self.index:
            return
        self.index = i
        self._anim.stop()
        if animate:
            self._anim.setStartValue(self._marker)
            self._anim.setEndValue(self._y(i))
            self._anim.start()
        else:
            self._marker = self._y(i)
        self._describe()
        self.update()
        self._emit.start()

    def _describe(self):
        self.setAccessibleDescription(self.label_for(self.current()))

    def label_for(self, t: float) -> str:
        if t == NOW:
            return tr("Now")
        d = dt.datetime.fromtimestamp(t)
        today = dt.date.today()
        if d.date() == today:
            return tr("Today") + d.strftime(" %H:%M")
        if d.date() == today - dt.timedelta(days=1):
            return tr("Yesterday") + d.strftime(" %H:%M")
        if d.year == today.year:
            return d.strftime("%d %b %H:%M")
        return d.strftime("%d %b %Y")

    # ------------------------------------------------------------------ geometry

    def _line_x(self) -> float:
        return self.width() - 22.0

    def _y(self, i: int) -> float:
        top, bottom = 24.0, 24.0
        n = len(self.times)
        if n <= 1:
            return top
        return top + i * (self.height() - top - bottom) / (n - 1)

    def _index_at(self, y: float) -> int:
        best, bd = 0, 1e9
        for i in range(len(self.times)):
            d = abs(self._y(i) - y)
            if d < bd:
                best, bd = i, d
        return best

    def resizeEvent(self, e):  # noqa: N802
        self._marker = self._y(self.index)
        super().resizeEvent(e)

    # ------------------------------------------------------------------ painting

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x = self._line_x()
        p.setPen(QPen(theme.color("track"), 2))
        p.drawLine(int(x), int(self._y(0)), int(x), int(self._y(len(self.times) - 1)))
        fm = QFontMetrics(self.font())
        last_label_y = -100.0
        sub = theme.color("subtext")
        for i, tm in enumerate(self.times):
            y = self._y(i)
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color("tertext"))
            p.drawEllipse(QRectF(x - 3, y - 3, 6, 6))
            if abs(y - last_label_y) >= fm.height() + 4 and abs(y - self._marker) > fm.height():
                p.setPen(sub)
                txt = self.label_for(tm) if tm == NOW else dt.datetime.fromtimestamp(tm).strftime("%d %b")
                p.drawText(QRectF(0, y - fm.height() / 2, x - 12, fm.height()), Qt.AlignRight | Qt.AlignVCenter,
                           txt)
                last_label_y = y
        # Selected marker + pill
        y = self._marker
        acc = theme.color("accent")
        p.setPen(Qt.NoPen)
        p.setBrush(acc)
        p.drawEllipse(QRectF(x - 7, y - 7, 14, 14))
        txt = self.label_for(self.current())
        w = fm.horizontalAdvance(txt) + 16
        pill = QRectF(max(2, x - 14 - w), y - fm.height() / 2 - 4, w, fm.height() + 8)
        p.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
        p.setPen(QColor("#ffffff"))
        p.drawText(pill, Qt.AlignCenter, txt)
        if self.hasFocus():
            p.setPen(QPen(acc, 1, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(1, 1, self.width() - 2, self.height() - 2), 12, 12)

    # ------------------------------------------------------------------ input

    def mousePressEvent(self, e):  # noqa: N802
        self._drag = True
        self.set_index(self._index_at(e.position().y()))

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag:
            self.set_index(self._index_at(e.position().y()), animate=False)

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._drag = False

    def wheelEvent(self, e):  # noqa: N802
        self.set_index(self.index + (1 if e.angleDelta().y() < 0 else -1))

    def keyPressEvent(self, e):  # noqa: N802
        k = e.key()
        step = {Qt.Key_Down: 1, Qt.Key_Up: -1, Qt.Key_PageDown: 5, Qt.Key_PageUp: -5}.get(k)
        if step:
            self.set_index(self.index + step)
        elif k == Qt.Key_Home:
            self.set_index(0)
        elif k == Qt.Key_End:
            self.set_index(len(self.times) - 1)
        else:
            super().keyPressEvent(e)
