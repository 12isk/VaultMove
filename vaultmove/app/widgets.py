"""Small reusable widgets: Card, Switch, SegmentBar, Collapsible, helpers."""

from __future__ import annotations

import datetime as dt
import time

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QGraphicsDropShadowEffect, QHBoxLayout,
                               QLabel, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from . import theme
from .i18n import tr


def human_size(n) -> str:
    if n is None:
        return ""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1000 or unit == "TB":
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.1f} {unit}" if n < 100 else f"{n:.0f} {unit}"
        n /= 1000
    return ""


def human_ago(ts: float | None) -> str:
    if not ts:
        return tr("never")
    d = time.time() - ts
    if d < 0:
        return tr("just now")
    if d < 60:
        return tr("just now")
    if d < 3600:
        m = int(d // 60)
        return tr("1 minute ago") if m == 1 else tr("%1 minutes ago").replace("%1", str(m))
    if d < 86400:
        h = int(d // 3600)
        return tr("1 hour ago") if h == 1 else tr("%1 hours ago").replace("%1", str(h))
    days = int(d // 86400)
    if days == 1:
        return tr("yesterday")
    return tr("%1 days ago").replace("%1", str(days))


def fmt_datetime(ts: float | None) -> str:
    if not ts:
        return ""
    t = dt.datetime.fromtimestamp(ts)
    today = dt.date.today()
    if t.date() == today:
        return tr("Today") + t.strftime(" %H:%M")
    if t.date() == today - dt.timedelta(days=1):
        return tr("Yesterday") + t.strftime(" %H:%M")
    return t.strftime("%Y-%m-%d %H:%M")


class Card(QFrame):
    """White rounded panel with a soft shadow (theme-aware)."""

    def __init__(self, parent=None, shadow: bool = True, margins=(20, 18, 20, 18), spacing=10):
        super().__init__(parent)
        self.setObjectName("Card")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(*margins)
        self._layout.setSpacing(spacing)
        self._shadow = None
        if shadow:
            self._shadow = QGraphicsDropShadowEffect(self)
            self._shadow.setOffset(0, 2)
            self._shadow.setBlurRadius(24)
            self.refresh_theme()
            self.setGraphicsEffect(self._shadow)

    def refresh_theme(self):
        if self._shadow is not None:
            self._shadow.setColor(QColor(0, 0, 0, 90 if theme.is_dark() else 22))

    def layout(self) -> QVBoxLayout:  # type: ignore[override]
        return self._layout

    def add(self, w, stretch: int = 0):
        if isinstance(w, QWidget):
            self._layout.addWidget(w, stretch)
        else:
            self._layout.addLayout(w, stretch)
        return w


def label(text: str = "", obj: str | None = None, wrap: bool = False, parent=None) -> QLabel:
    lb = QLabel(text, parent)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


def primary_button(text: str, parent=None) -> QPushButton:
    b = QPushButton(text, parent)
    b.setObjectName("Primary")
    b.setCursor(Qt.PointingHandCursor)
    b.setFocusPolicy(Qt.TabFocus)  # focus ring for keyboard users, not after mouse clicks
    return b


def hbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(spacing)
    h.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            h.addStretch(1)
        elif isinstance(w, int):
            h.addSpacing(w)
        elif isinstance(w, QWidget):
            h.addWidget(w)
        else:
            h.addLayout(w)
    return h


class Switch(QAbstractButton):
    """iOS/macOS-style toggle. Space toggles it; it is a checkable button for accessibility."""

    def __init__(self, parent=None, accessible_name: str = ""):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        if accessible_name:
            self.setAccessibleName(accessible_name)
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self) -> QSize:
        return QSize(44, 26)

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, v: float):
        self._pos = v
        self.update()

    knob = Property(float, _get_knob, _set_knob)

    def setChecked(self, on: bool):  # noqa: N802  (no animation for programmatic changes)
        blocked = self._anim.state() == QPropertyAnimation.Running
        super().setChecked(on)
        if not blocked:
            self._anim.stop()
            self._pos = 1.0 if on else 0.0
            self.update()

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off, on = theme.color("track"), theme.color("accent")
        c = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos),
        )
        if not self.isEnabled():
            c.setAlpha(110)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 4
        x = r.x() + 2 + (r.width() - d - 4) * self._pos
        p.setBrush(QColor("#ffffff"))
        p.setPen(QPen(QColor(0, 0, 0, 30), 0.5))
        p.drawEllipse(QRectF(x, r.y() + 2, d, d))
        if self.hasFocus():
            p.setPen(QPen(theme.color("accent"), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(-0.5, -0.5, 0.5, 0.5), r.height() / 2, r.height() / 2)


class SegmentBar(QWidget):
    """Mac-style segmented control used as the tab switcher."""

    changed = Signal(int)

    def __init__(self, labels: list[str], parent=None):
        super().__init__(parent)
        self.setObjectName("SegmentBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        for i, text in enumerate(labels):
            b = QPushButton(text, self)
            b.setObjectName("Segment")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.TabFocus)
            b.setAccessibleName(text.replace("&&", "&"))
            self.group.addButton(b, i)
            lay.addWidget(b)
            self.buttons.append(b)
        self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self.changed.emit)

    def set_index(self, i: int):
        self.buttons[i].setChecked(True)


class Collapsible(QWidget):
    """A header button that shows/hides a body widget with a height animation."""

    def __init__(self, title: str, body: QWidget, parent=None, expanded_height: int = 220):
        super().__init__(parent)
        self.setObjectName("Transparent")
        self.title = title
        self.body = body
        self.expanded_height = expanded_height
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.toggle = QToolButton(self)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.RightArrow)
        self.toggle.setText(title)
        self.toggle.setAccessibleName(title)
        self.toggle.toggled.connect(self._toggled)
        lay.addWidget(self.toggle, 0, Qt.AlignLeft)
        lay.addWidget(body)
        body.setMaximumHeight(0)
        self._anim = QPropertyAnimation(body, b"maximumHeight", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)

    def _toggled(self, on: bool):
        self.toggle.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self._anim.stop()
        self._anim.setStartValue(self.body.maximumHeight())
        self._anim.setEndValue(self.expanded_height if on else 0)
        self._anim.start()


class StatusBadge(QWidget):
    """Big round status glyph next to the status title (painted, theme-aware)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "idle"
        self.progress = None
        self.setFixedSize(64, 64)

    def set_state(self, state: str, progress: float | None = None):
        self.state, self.progress = state, progress
        self.update()

    def paintEvent(self, _e):
        from .icon import paint_logo
        p = QPainter(self)
        paint_logo(p, QRectF(0, 0, self.width(), self.height()), self.state, self.progress)
