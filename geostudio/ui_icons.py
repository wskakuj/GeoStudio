"""Crisp monochrome vector pictograms for GeoStudio's native Qt controls.

No image files, font dependencies or emoji: each icon is rendered as basic
QPainter strokes and is readable on both Windows light/dark themes.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

ALIASES = {
    "▣": "folder", "▤": "save", "⤢": "fit", "▦": "image",
    "▧": "image", "↗": "export", "⟳": "compass", "◎": "select",
    "✥": "hand", "⬡": "polygon", "◇": "vertices", "✎": "label",
    "✓": "check", "↶": "undo", "⌖": "snap", "A": "labels",
    "⌕": "search", "?": "help",
}


def draw_icon(name: str, color: str) -> QIcon:
    """Return a high-DPI QIcon with a consistent 1.8-unit stroke."""
    name = ALIASES.get(name, name)
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2.0)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # QPainter already honours QPixmap.devicePixelRatio() on HiDPI targets.
    # Scaling again clipped half of each icon (the short broken strokes
    # visible on Windows). Draw the 24×24 design in logical coordinates.

    pen = QPen(QColor(color))
    pen.setWidthF(1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    def line(x1, y1, x2, y2):
        painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def poly(*points, close=False):
        path = QPainterPath(QPointF(*points[0]))
        for point in points[1:]:
            path.lineTo(*point)
        if close:
            path.closeSubpath()
        painter.drawPath(path)

    def box(x, y, w, h, radius=2):
        painter.drawRoundedRect(QRectF(x, y, w, h), radius, radius)

    def circle(x, y, r):
        painter.drawEllipse(QPointF(x, y), r, r)

    if name == "folder":
        poly((3, 8), (9, 8), (11, 10), (21, 10), (21, 19), (3, 19), close=True)
        line(3, 13, 21, 13)
    elif name == "save":
        poly((5, 3), (17, 3), (21, 7), (21, 21), (4, 21), (4, 3), close=True)
        box(8, 4, 8, 5, 0.6)
        box(8, 14, 9, 7, 0.8)
    elif name == "fit":
        poly((9, 3), (3, 3), (3, 9))
        poly((15, 3), (21, 3), (21, 9))
        poly((3, 15), (3, 21), (9, 21))
        poly((15, 21), (21, 21), (21, 15))
        box(8, 8, 8, 8, 0.8)
    elif name == "image":
        box(3, 5, 18, 15, 1.5)
        circle(8, 10, 1.3)
        poly((5, 18), (11, 12), (15, 16), (18, 13), (21, 17))
    elif name == "export":
        poly((12, 4), (21, 4), (21, 13))
        line(21, 4, 10, 15)
        poly((18, 15), (18, 21), (4, 21), (4, 7), (10, 7))
    elif name == "compass":
        circle(12, 12, 9)
        poly((10, 10), (17, 6), (14, 14), (7, 18), close=True)
        line(12, 2, 12, 4)
    elif name == "select":
        poly((5, 3), (5, 19), (10, 14), (14, 21), (17, 19), (13, 12), (20, 11), close=True)
    elif name == "hand":
        poly((8, 20), (5, 15), (5, 12), (7, 11), (10, 14),
             (10, 5), (12, 4), (14, 6), (14, 11), (15, 8),
             (17, 8), (18, 11), (19, 10), (21, 12), (20, 17), (17, 21), close=True)
    elif name == "polygon":
        poly((5, 9), (11, 4), (20, 8), (19, 18), (8, 21), close=True)
        for x, y in [(5, 9), (11, 4), (20, 8), (19, 18), (8, 21)]:
            circle(x, y, 1.25)
    elif name == "vertices":
        poly((4, 18), (10, 5), (20, 10), (17, 20), close=True)
        for x, y in [(4, 18), (10, 5), (20, 10), (17, 20)]:
            painter.drawRect(QRectF(x - 1.6, y - 1.6, 3.2, 3.2))
    elif name == "label" or name == "labels":
        box(3, 4, 18, 16)
        line(7, 10, 17, 10)
        line(7, 14, 14, 14)
    elif name == "check":
        poly((3, 12), (9, 18), (21, 5))
    elif name == "undo":
        poly((9, 5), (4, 10), (9, 15))
        poly((4, 10), (14, 10), (19, 14), (19, 19))
    elif name == "snap":
        circle(12, 12, 5)
        circle(12, 12, 1.6)
        line(12, 2, 12, 5)
        line(12, 19, 12, 22)
        line(2, 12, 5, 12)
        line(19, 12, 22, 12)
    elif name == "layers":
        poly((3, 9), (12, 4), (21, 9), (12, 14), close=True)
        poly((3, 13), (12, 18), (21, 13))
        poly((3, 17), (12, 22), (21, 17))
    elif name == "properties":
        box(4, 3, 16, 18, 1.2)
        line(8, 8, 16, 8)
        line(8, 12, 16, 12)
        line(8, 16, 13, 16)
    elif name == "search":
        circle(10, 10, 6)
        line(14.5, 14.5, 21, 21)
    elif name == "help":
        circle(12, 12, 9)
        poly((9, 9), (10, 7), (14, 7), (16, 9), (16, 11), (12, 14), (12, 16))
        circle(12, 19, 0.4)
    elif name == "more":
        circle(5, 12, 1)
        circle(12, 12, 1)
        circle(19, 12, 1)
    elif name == "eye":
        poly((2, 12), (7, 7), (12, 6), (17, 7), (22, 12),
             (17, 17), (12, 18), (7, 17), close=True)
        circle(12, 12, 3)
    elif name == "filter":
        poly((3, 5), (21, 5), (14, 13), (14, 20), (10, 18), (10, 13), close=True)
    else:
        # Unknown semantic icons still remain a clearly visible neutral glyph.
        box(5, 5, 14, 14, 3)
        line(8, 12, 16, 12)
    painter.end()
    return QIcon(pixmap)
