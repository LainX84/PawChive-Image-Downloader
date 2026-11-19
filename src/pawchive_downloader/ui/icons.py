"""Small line icons painted with QPainter.

Drawing the icons (instead of using text symbols) keeps them the same size on
every platform and font, so the navigation stays aligned, and lets them follow
the current theme colour.
"""

from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

_LOGICAL = 18  # icon size in logical pixels


def _pen(color: QColor, scale: float, width: float = 1.6) -> QPen:
    pen = QPen(color, width * scale)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _draw(name: str, p: QPainter, s: float, color: QColor) -> None:  # noqa: C901 - one branch per icon
    """Draw icon *name* in an 18×18 box scaled by *s*."""
    p.setPen(_pen(color, s))
    p.setBrush(Qt.BrushStyle.NoBrush)

    def r(x: float, y: float, w: float, h: float) -> QRectF:
        return QRectF(x * s, y * s, w * s, h * s)

    def pt(x: float, y: float) -> QPointF:
        return QPointF(x * s, y * s)

    if name == "dashboard":
        for x, y, w, h in ((2.5, 2.5, 5.5, 7), (10, 2.5, 5.5, 4), (2.5, 11.5, 5.5, 4), (10, 8.5, 5.5, 7)):
            p.drawRoundedRect(r(x, y, w, h), 1.4 * s, 1.4 * s)
    elif name == "authors":
        p.drawEllipse(r(6, 2.5, 6, 6))
        path = QPainterPath(pt(3, 15.5))
        path.cubicTo(pt(3.5, 11), pt(14.5, 11), pt(15, 15.5))
        p.drawPath(path)
    elif name == "works":
        p.drawRoundedRect(r(3, 2.5, 9, 13), 1.2 * s, 1.2 * s)
        p.drawLine(pt(14.5, 4.5), pt(14.5, 15.5))
        p.drawLine(pt(6, 6.5), pt(9, 6.5))
    elif name == "review":
        p.drawEllipse(r(2.5, 2.5, 13, 13))
        p.drawPolyline([pt(6, 9.2), pt(8.2, 11.4), pt(12.2, 6.8)])
    elif name == "queue":
        p.drawLine(pt(9, 2.5), pt(9, 11))
        p.drawPolyline([pt(5.5, 7.8), pt(9, 11.3), pt(12.5, 7.8)])
        p.drawPolyline([pt(3, 12), pt(3, 15.5), pt(15, 15.5), pt(15, 12)])
    elif name == "log":
        for y, w in ((4, 12), (7.5, 9), (11, 12), (14.5, 7)):
            p.drawLine(pt(3, y), pt(3 + w, y))
    elif name == "settings":
        center = pt(9, 9)
        teeth = QPainterPath()
        for i in range(16):
            angle = math.pi * 2 * i / 16
            radius = 7.0 if i % 2 == 0 else 5.4
            q = QPointF(center.x() + math.cos(angle) * radius * s, center.y() + math.sin(angle) * radius * s)
            teeth.moveTo(q) if i == 0 else teeth.lineTo(q)
        teeth.closeSubpath()
        p.drawPath(teeth)
        p.drawEllipse(center, 2.2 * s, 2.2 * s)
    elif name == "about":
        p.drawEllipse(r(2.5, 2.5, 13, 13))
        p.drawLine(pt(9, 8.2), pt(9, 12.5))
        p.setBrush(QBrush(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(pt(9, 5.6), 1.0 * s, 1.0 * s)
    elif name == "pause":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        p.drawRoundedRect(r(4.5, 3.5, 3, 11), 1 * s, 1 * s)
        p.drawRoundedRect(r(10.5, 3.5, 3, 11), 1 * s, 1 * s)
    elif name == "play":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        path = QPainterPath(pt(5, 3.2))
        path.lineTo(pt(14.5, 9))
        path.lineTo(pt(5, 14.8))
        path.closeSubpath()
        p.drawPath(path)
    elif name == "clock":
        p.drawEllipse(r(2.5, 2.5, 13, 13))
        p.drawPolyline([pt(9, 5.5), pt(9, 9), pt(11.5, 10.5)])
    elif name == "chevron_down":
        p.drawPolyline([pt(5, 7), pt(9, 11), pt(13, 7)])
    elif name == "chevron_up":
        p.drawPolyline([pt(5, 11), pt(9, 7), pt(13, 11)])
    elif name == "chevron_right":
        p.drawPolyline([pt(7, 5), pt(11, 9), pt(7, 13)])
    elif name == "top":
        p.drawLine(pt(3.5, 3), pt(14.5, 3))
        p.drawLine(pt(9, 6), pt(9, 15.5))
        p.drawPolyline([pt(5.5, 9.5), pt(9, 6), pt(12.5, 9.5)])
    elif name == "retry":
        p.drawArc(r(3, 3, 12, 12), 40 * 16, 290 * 16)
        p.drawPolyline([pt(14.2, 3), pt(14.2, 6.6), pt(10.6, 6.6)])
    else:
        p.drawEllipse(r(5, 5, 8, 8))


@lru_cache(maxsize=256)
def icon(name: str, color: str, size: int = _LOGICAL) -> QIcon:
    """A crisp icon (rendered at 1×, 2× and 3×) in the given colour."""
    result = QIcon()
    for factor in (1, 2, 3):
        px = QPixmap(size * factor, size * factor)
        px.fill(Qt.GlobalColor.transparent)
        painter = QPainter(px)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _draw(name, painter, size * factor / _LOGICAL, QColor(color))
        painter.end()
        px.setDevicePixelRatio(factor)
        result.addPixmap(px)
    return result


# ------------------------------------------------------------------ app icon
def app_icon_pixmap(size: int = 256) -> QPixmap:
    """The application icon: a white paw print on a violet rounded square."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    u = size / 64.0
    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor("#a194ff"))
    gradient.setColorAt(1.0, QColor("#5b46d6"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(gradient))
    p.drawRoundedRect(QRectF(2 * u, 2 * u, 60 * u, 60 * u), 14 * u, 14 * u)
    p.setBrush(QBrush(QColor("#ffffff")))
    # main pad
    pad = QPainterPath()
    pad.moveTo(32 * u, 30 * u)
    pad.cubicTo(41 * u, 30 * u, 49 * u, 42 * u, 46 * u, 48 * u)
    pad.cubicTo(43.5 * u, 53 * u, 37 * u, 50 * u, 32 * u, 50 * u)
    pad.cubicTo(27 * u, 50 * u, 20.5 * u, 53 * u, 18 * u, 48 * u)
    pad.cubicTo(15 * u, 42 * u, 23 * u, 30 * u, 32 * u, 30 * u)
    p.drawPath(pad)
    # toes
    for cx, cy, rx, ry, angle in ((17, 28, 4.6, 6.0, -25), (26, 18.5, 4.8, 6.4, -8),
                                  (38, 18.5, 4.8, 6.4, 8), (47, 28, 4.6, 6.0, 25)):
        p.save()
        p.translate(cx * u, cy * u)
        p.rotate(angle)
        p.drawEllipse(QPointF(0, 0), rx * u, ry * u)
        p.restore()
    p.end()
    return px


def app_icon() -> QIcon:
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        result.addPixmap(app_icon_pixmap(size))
    return result
