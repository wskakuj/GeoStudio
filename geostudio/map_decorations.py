"""Editable, map-anchored composition elements for GeoStudio.

These are modern overlays, not unverified writes to GEO-MAP's 5200/6000/7900
primitives. Their information and positions are saved in the existing
.geostudio.json style sidecar, and can be exported as part of a rendered scene.
"""
from __future__ import annotations

from uuid import uuid4
from math import hypot

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QBrush, QTransform
from PySide6.QtWidgets import QGraphicsItem


KINDS = {
    "north": "Znak północy",
    "title": "Tablica tytułowa wsi",
    "credits": "Metryka wykonawcy",
    "legend": "Wykaz znaków i skrótów",
}

DEFAULTS = {
    "north": {
        "title": "N", "subtitle": "", "details": "", "area": "",
    },
    "title": {
        "title": "MAPA GOSPODARCZA LASU",
        "subtitle": "WIEŚ: WPISZ NAZWĘ",
        "details": "Gmina: —    Powiat: —    Województwo: —\n"
                   "Stan na: —    Okres: —",
        "area": "Powierzchnia opracowania: — ha",
    },
    "credits": {
        "title": "WYKONAWCA OPRACOWANIA",
        "subtitle": "Nazwa pracowni",
        "details": "Adres: —\nKierownik robót: —\n"
                   "Taksatorzy: —\nOpracował: —",
        "area": "",
    },
    "legend": {
        "title": "LEGENDA MAPY",
        "subtitle": "Znaki i kolory",
        "details": "Sosna i modrzew\nŚwierk\nDąb\n"
                   "Brzoza i akacja\nGranice wydzieleń\n"
                   "Drogi i ścieżki\nLinie energetyczne",
        "area": "",
        "items": [
            {"name": "Sosna i modrzew", "color": "#BFCDA7"},
            {"name": "Świerk", "color": "#9CB7CB"},
            {"name": "Dąb", "color": "#AA9876"},
            {"name": "Brzoza i akacja", "color": "#71BEBB"},
            {"name": "Granice wydzieleń", "color": "#BA7A75"},
            {"name": "Drogi i ścieżki", "color": "#6B8B9E"},
            {"name": "Linie energetyczne", "color": "#D1BA56"},
        ],
    },
}
SIZES = {
    "north": (184, 184),
    "title": (495, 230),
    "credits": (455, 278),
    "legend": (460, 357),
}
INK = QColor("#19344C")
ACCENT = QColor("#078C91")
MUTED = QColor("#617587")


def new_decoration(kind: str, x: float, y: float) -> tuple[str, dict]:
    if kind not in KINDS:
        raise ValueError("Nieznany element oprawy mapy")
    uid = "layout:" + uuid4().hex
    result = {**DEFAULTS[kind], "kind": kind, "scale": 1.0,
              "x": round(float(x), 3), "y": round(float(y), 3)}
    if kind == "legend":
        result["items"] = [dict(entry) for entry in DEFAULTS["legend"]["items"]]
    return uid, result


class DecorationItem(QGraphicsItem):
    """Movable professional-looking map furniture, editable on double-click."""

    def __init__(self, uid: str, data: dict, scale: float, *, on_move, on_edit, on_resize=None):
        super().__init__()
        self.uid = uid
        self.layout_data = data
        self._on_move = on_move
        self._on_edit = on_edit
        self._on_resize = on_resize
        self._drag_origin = QPointF()
        self._resizing = False
        self._base_scale = max(0.01, float(scale))
        self._width, self._height = SIZES[data["kind"]]
        if data["kind"] == "legend":
            rows = data.get("items")
            if isinstance(rows, list):
                self._height = max(self._height, 124 + 24 * min(len(rows), 100))
        self.setData(0, "geostudio-decoration")
        self.setToolTip("Przeciągnij, aby przesunąć • dwuklik, aby edytować • "
                        + KINDS[data["kind"]])
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsFocusable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setZValue(1800)
        # GEO-MAP scene and view swap/geodetically mirror source axes.
        # Counter-transform local coordinates once so text is upright on
        # the default map while remaining in map space and image exports.
        self.setTransform(QTransform(0, -self._base_scale, -self._base_scale, 0, 0, 0))
        self.setScale(float(data.get("scale", 1.0)))
        self.setPos(float(data["x"]), -float(data["y"]))

    def boundingRect(self):
        return QRectF(-3, -3, self._width + 6, self._height + 6)

    @staticmethod
    def _font(size: int, *, bold=False):
        font = QFont("Segoe UI")
        font.setPixelSize(size)
        font.setBold(bold)
        return font

    def _text(self, painter, text, x, y, w, h, *, size=15, bold=False,
              color=INK, align=None):
        painter.setPen(color)
        painter.setFont(self._font(size, bold=bold))
        painter.drawText(QRectF(x, y, w, h),
                         (Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap)
                         if align is None else align, str(text))

    def _panel(self, painter):
        painter.setPen(QPen(ACCENT, 2))
        painter.drawLine(12, 31, self._width - 12, 31)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing, True)
        kind = self.layout_data["kind"]
        if kind == "north":
            self._paint_north(painter)
        else:
            self._paint_content(painter)
        if self.isSelected():
            painter.setPen(QPen(ACCENT, 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(QRectF(0, 0, self._width, self._height))
            painter.setPen(QPen(INK, 1.5))
            painter.setBrush(QBrush(QColor("#FFFFFF")))
            painter.drawRect(QRectF(self._width - 11, self._height - 11, 11, 11))

    def _paint_content(self, painter):
        self._panel(painter)
        title = self.layout_data.get("title", "")
        subtitle = self.layout_data.get("subtitle", "")
        details = self.layout_data.get("details", "")
        area = self.layout_data.get("area", "")
        self._text(painter, title, 13, 0, self._width - 25, 29,
                   size=21, bold=True)
        self._text(painter, subtitle, 14, 45, self._width - 28, 38,
                   size=17, bold=True)
        if kind == "legend":
            self._paint_legend_rows(painter, details)
        else:
            self._text(painter, details, 14, 93,
                       self._width - 28,
                       (96 if kind == "title" else 153),
                       size=14, color=MUTED,
                       align=Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap)
        if area:
            self._text(painter, area, 14, self._height - 35,
                       self._width - 30, 27,
                       size=13, bold=True, color=ACCENT)

    def _paint_north(self, painter):
        """N E S W wind rose without background."""
        cx, cy = 92, 91
        painter.setPen(QPen(INK, 1.8))
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            tip = QPointF(cx + dx * 56, cy + dy * 56)
            side_x, side_y = -dy, dx
            base = QPointF(cx + dx * 10, cy + dy * 10)
            left = QPointF(base.x() + side_x * 11, base.y() + side_y * 11)
            right = QPointF(base.x() - side_x * 11, base.y() - side_y * 11)
            wedge = QPainterPath(tip)
            wedge.lineTo(left)
            wedge.lineTo(QPointF(cx, cy))
            wedge.lineTo(right)
            wedge.closeSubpath()
            painter.setBrush(QBrush(INK if dy < 0 or dx > 0
                                   else QColor("#C6D8DC")))
            painter.drawPath(wedge)
        for letter, r in (
            ("N", (73, 0, 38, 28)), ("E", (154, 73, 28, 36)),
            ("S", (74, 154, 36, 28)), ("W", (0, 73, 31, 36)),
        ):
            self._text(painter, letter, *r, size=22, bold=True,
                       color=INK, align=Qt.AlignCenter)

    def _paint_legend_rows(self, painter, details):
        entries = self.layout_data.get("items")
        if not isinstance(entries, list):
            palette = ("#BFCDA7", "#9CB7CB", "#AA9876", "#71BEBB",
                       "#BA7A75", "#6B8B9E", "#D1BA56")
            entries = [{"name": name.strip(), "color": palette[i % len(palette)]}
                       for i, name in enumerate(str(details).splitlines()) if name.strip()]
        available = max(0, int((self._height - 124) / 24))
        for idx, entry in enumerate(entries[:available]):
            name = str(entry.get("name", ""))[:150]
            color = QColor(str(entry.get("color", "#91ABA7")))
            if not color.isValid():
                color = ACCENT
            y = 95 + 24 * idx
            painter.setPen(QPen(color.darker(115), 1))
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(QRectF(15, y + 4, 34, 14), 2, 2)
            self._text(painter, name, 63, y, self._width - 76, 22,
                       size=13, color=INK)

    def mousePressEvent(self, event):
        self.setSelected(True)
        self._drag_origin = QPointF(self.pos())
        corner = QRectF(self._width - 19, self._height - 19, 25, 25)
        self._resizing = corner.contains(event.pos())
        if self._resizing:
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            p = event.scenePos()
            distance = hypot(p.x() - self.pos().x(), p.y() - self.pos().y())
            baseline = hypot(self._width, self._height) * self._base_scale
            self.setScale(max(0.25, min(8.0, distance / max(baseline, .0001))))
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            if self._on_resize:
                self._on_resize(self.uid, round(self.scale(), 4))
            event.accept()
            return
        super().mouseReleaseEvent(event)
        pos = self.pos()
        if (abs(pos.x() - self._drag_origin.x()) +
                abs(pos.y() - self._drag_origin.y())) > 0.00001:
            self._on_move(self.uid, round(pos.x(), 3), round(-pos.y(), 3))

    def mouseDoubleClickEvent(self, event):
        self._on_edit(self.uid)
        event.accept()
