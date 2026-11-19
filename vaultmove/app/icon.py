"""Original VaultMove icon, painted with QPainter (no image assets needed).

A rounded blue tile, a white circular arrow sweeping around it, and a round
vault door with a three-spoke handle in the middle. The same painter makes the
multi-resolution .ico in CI (packaging/make_icon.py) and the live tray states.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

STATES = ("idle", "running", "missing", "error", "paused")


def paint_logo(p: QPainter, rect: QRectF, state: str = "idle", progress: float | None = None):
    p.save()
    p.setRenderHint(QPainter.Antialiasing, True)
    s = min(rect.width(), rect.height())
    x0, y0 = rect.x() + (rect.width() - s) / 2, rect.y() + (rect.height() - s) / 2
    tile = QRectF(x0 + s * 0.04, y0 + s * 0.04, s * 0.92, s * 0.92)
    g = QLinearGradient(tile.topLeft(), tile.bottomRight())
    if state == "missing" or state == "paused":
        g.setColorAt(0, QColor("#a1a1a8"))
        g.setColorAt(1, QColor("#6b6b72"))
    else:
        g.setColorAt(0, QColor("#47a6ff"))
        g.setColorAt(1, QColor("#0a6cf0"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(g))
    p.drawRoundedRect(tile, s * 0.23, s * 0.23)

    c = QPointF(x0 + s / 2, y0 + s / 2)
    r = s * 0.31
    w = max(1.4, s * 0.075)
    white = QColor("#ffffff")
    start_deg, span_deg = 115.0, -290.0  # clockwise sweep
    arc_rect = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
    if state == "running" and progress is not None:
        faint = QColor(255, 255, 255, 95)
        p.setPen(QPen(faint, w, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(arc_rect, int(start_deg * 16), int(span_deg * 16))
        p.setPen(QPen(white, w, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(arc_rect, int(start_deg * 16), int(span_deg * max(0.02, min(1.0, progress)) * 16))
    else:
        p.setPen(QPen(white, w, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(arc_rect, int(start_deg * 16), int(span_deg * 16))
        # Arrow head at the end of the sweep, pointing along the clockwise tangent.
        th = math.radians(start_deg + span_deg)
        end = QPointF(c.x() + r * math.cos(th), c.y() - r * math.sin(th))
        tangent = QPointF(math.sin(th), math.cos(th))        # clockwise direction in screen coords
        normal = QPointF(math.cos(th), -math.sin(th))        # radial outward
        hl, hw = s * 0.13, s * 0.10
        tip = end + tangent * hl * 0.75
        back = end - tangent * hl * 0.25
        head = QPainterPath()
        head.moveTo(tip)
        head.lineTo(back + normal * hw)
        head.lineTo(back - normal * hw)
        head.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(white)
        p.drawPath(head)

    # Vault door.
    dr = s * 0.17
    p.setPen(Qt.NoPen)
    p.setBrush(white)
    p.drawEllipse(c, dr, dr)
    blue = QColor("#0a6cf0") if state not in ("missing", "paused") else QColor("#6b6b72")
    p.setPen(QPen(blue, max(1.0, s * 0.028)))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(c, dr * 0.66, dr * 0.66)
    if s >= 24:
        for k in range(3):
            a = math.radians(90 + k * 120)
            p.drawLine(c, QPointF(c.x() + dr * 0.66 * math.cos(a), c.y() - dr * 0.66 * math.sin(a)))
    p.setPen(Qt.NoPen)
    p.setBrush(blue)
    p.drawEllipse(c, dr * 0.2, dr * 0.2)

    if state == "error":
        br = s * 0.2
        bc = QPointF(x0 + s - br * 1.05, y0 + br * 1.05)
        p.setBrush(QColor("#ff3b30"))
        p.setPen(QPen(QColor("#ffffff"), max(1.0, s * 0.03)))
        p.drawEllipse(bc, br, br)
        p.setPen(QPen(QColor("#ffffff"), max(1.2, s * 0.05), Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(bc.x(), bc.y() - br * 0.5), QPointF(bc.x(), bc.y() + br * 0.1))
        p.drawPoint(QPointF(bc.x(), bc.y() + br * 0.5))
    elif state == "paused":
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        bw, bh = s * 0.05, s * 0.16
        bx, by = x0 + s * 0.74, y0 + s * 0.08
        p.drawRoundedRect(QRectF(bx, by, bw, bh), bw / 2, bw / 2)
        p.drawRoundedRect(QRectF(bx + bw * 1.8, by, bw, bh), bw / 2, bw / 2)
    p.restore()


def render(size: int, state: str = "idle", progress: float | None = None) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    paint_logo(p, QRectF(0, 0, size, size), state, progress)
    p.end()
    return img


def make_icon(state: str = "idle", progress: float | None = None) -> QIcon:
    icon = QIcon()
    for sz in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        icon.addPixmap(QPixmap.fromImage(render(sz, state, progress)))
    return icon
