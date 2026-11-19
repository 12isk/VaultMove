"""Monoline icons in the SF Symbols spirit (1.6 px strokes, round caps), painted in code.

symbol(name, size, color) -> QIcon. Icons take the current text colour so they
follow light/dark mode; call again after a theme change.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap

from . import theme

NAMES = ("search", "gear", "plus", "minus", "back", "clock", "restore", "folder", "keyboard", "drive",
         "laptop", "stop", "eye", "close", "check")


def _draw(p: QPainter, name: str, s: float):
    c = s / 2
    if name == "search":
        r = s * 0.28
        p.drawEllipse(QPointF(s * 0.43, s * 0.43), r, r)
        p.drawLine(QPointF(s * 0.63, s * 0.63), QPointF(s * 0.84, s * 0.84))
    elif name == "gear":
        p.drawEllipse(QPointF(c, c), s * 0.13, s * 0.13)
        path = QPainterPath()
        teeth = 8
        for i in range(teeth * 2):
            a = math.pi * i / teeth
            rad = s * (0.38 if i % 2 == 0 else 0.29)
            for da in (-0.17, 0.17):
                pt = QPointF(c + rad * math.cos(a + da), c + rad * math.sin(a + da))
                if i == 0 and da < 0:
                    path.moveTo(pt)
                else:
                    path.lineTo(pt)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "plus":
        p.drawLine(QPointF(c, s * 0.2), QPointF(c, s * 0.8))
        p.drawLine(QPointF(s * 0.2, c), QPointF(s * 0.8, c))
    elif name == "minus":
        p.drawLine(QPointF(s * 0.2, c), QPointF(s * 0.8, c))
    elif name == "close":
        p.drawLine(QPointF(s * 0.25, s * 0.25), QPointF(s * 0.75, s * 0.75))
        p.drawLine(QPointF(s * 0.75, s * 0.25), QPointF(s * 0.25, s * 0.75))
    elif name == "back":
        path = QPainterPath(QPointF(s * 0.62, s * 0.2))
        path.lineTo(QPointF(s * 0.32, c))
        path.lineTo(QPointF(s * 0.62, s * 0.8))
        p.drawPath(path)
    elif name == "check":
        path = QPainterPath(QPointF(s * 0.22, s * 0.52))
        path.lineTo(QPointF(s * 0.42, s * 0.72))
        path.lineTo(QPointF(s * 0.8, s * 0.3))
        p.drawPath(path)
    elif name == "clock":
        p.drawEllipse(QPointF(c, c), s * 0.36, s * 0.36)
        p.drawLine(QPointF(c, c), QPointF(c, s * 0.28))
        p.drawLine(QPointF(c, c), QPointF(s * 0.66, s * 0.6))
    elif name == "restore":
        p.drawArc(QRectF(s * 0.16, s * 0.16, s * 0.68, s * 0.68), 90 * 16, 270 * 16)
        path = QPainterPath(QPointF(s * 0.5, s * 0.04))
        path.lineTo(QPointF(s * 0.5, s * 0.28))
        path.lineTo(QPointF(s * 0.74, s * 0.16))
        p.drawPath(path)
    elif name == "folder":
        path = QPainterPath(QPointF(s * 0.12, s * 0.3))
        path.lineTo(QPointF(s * 0.4, s * 0.3))
        path.lineTo(QPointF(s * 0.48, s * 0.38))
        path.lineTo(QPointF(s * 0.88, s * 0.38))
        path.lineTo(QPointF(s * 0.88, s * 0.78))
        path.lineTo(QPointF(s * 0.12, s * 0.78))
        path.closeSubpath()
        p.drawPath(path)
    elif name == "doc":
        path = QPainterPath(QPointF(s * 0.24, s * 0.1))
        path.lineTo(QPointF(s * 0.58, s * 0.1))
        path.lineTo(QPointF(s * 0.78, s * 0.3))
        path.lineTo(QPointF(s * 0.78, s * 0.9))
        path.lineTo(QPointF(s * 0.24, s * 0.9))
        path.closeSubpath()
        p.drawPath(path)
        fold = QPainterPath(QPointF(s * 0.58, s * 0.1))
        fold.lineTo(QPointF(s * 0.58, s * 0.3))
        fold.lineTo(QPointF(s * 0.78, s * 0.3))
        p.drawPath(fold)
    elif name == "keyboard":
        p.drawRoundedRect(QRectF(s * 0.1, s * 0.28, s * 0.8, s * 0.46), s * 0.08, s * 0.08)
        for row, y in enumerate((0.42, 0.54)):
            for i in range(4):
                x = s * (0.24 + i * 0.17)
                p.drawPoint(QPointF(x, s * y))
        p.drawLine(QPointF(s * 0.32, s * 0.64), QPointF(s * 0.68, s * 0.64))
    elif name == "drive":
        p.drawRoundedRect(QRectF(s * 0.12, s * 0.32, s * 0.76, s * 0.38), s * 0.08, s * 0.08)
        p.drawPoint(QPointF(s * 0.74, s * 0.51))
    elif name == "laptop":
        p.drawRoundedRect(QRectF(s * 0.2, s * 0.22, s * 0.6, s * 0.4), s * 0.05, s * 0.05)
        p.drawLine(QPointF(s * 0.08, s * 0.74), QPointF(s * 0.92, s * 0.74))
    elif name == "stop":
        p.drawRoundedRect(QRectF(s * 0.28, s * 0.28, s * 0.44, s * 0.44), s * 0.06, s * 0.06)
    elif name == "eye":
        path = QPainterPath(QPointF(s * 0.08, c))
        path.quadTo(QPointF(c, s * 0.12), QPointF(s * 0.92, c))
        path.quadTo(QPointF(c, s * 0.88), QPointF(s * 0.08, c))
        p.drawPath(path)
        p.drawEllipse(QPointF(c, c), s * 0.12, s * 0.12)


def render(name: str, size: int = 16, color: QColor | None = None, ratio: float = 2.0) -> QPixmap:
    px = int(size * ratio)
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(color or theme.color("text"), max(1.0, px * 0.09), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    _draw(p, name, px)
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(ratio)
    return pm


def symbol(name: str, size: int = 16, color: QColor | str | None = None) -> QIcon:
    if isinstance(color, str):
        color = theme.color(color)
    icon = QIcon(render(name, size, color))
    icon.addPixmap(render(name, size, theme.color("disabled")), QIcon.Disabled)
    return icon
