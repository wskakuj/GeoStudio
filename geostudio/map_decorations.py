"""Editable, map-anchored composition elements for GeoStudio.

These are modern overlays, not unverified writes to GEO-MAP's 5200/6000/7900
primitives. Their information and positions are saved in the existing
.geostudio.json style sidecar, and can be exported as part of a rendered scene.
"""
from __future__ import annotations

from uuid import uuid4

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
        "area": "Symbole i opisy można edytować dwuklikiem.",
    },
}
SIZES = {
    "north": (132, 180),
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
    return uid, {**DEFAULTS[kind], "kind": kind,
                 "x": round(float(x), 3), "y": round(float(y), 3)}


class DecorationItem(QGraphicsItem):
    """Movable professional-looking map furniture, editable on double-click."""

    def __init__(self, uid: str, data: dict, scale: float, *, on_move, on_edit):
        super().__init__()
        self.uid = uid
        self.data = data
        self._on_move = on_move
        self._on_edit = on_edit
        self._drag_origin = QPointF()
        self._width, self._height = SIZES[data["kind"]]
        self.setData(0, "geostudio-decoration")
        self.setToolTip("Przeciągnij, aby przesunąć • dwuklik, aby edytować • "
                        + KINDS[data["kind"]])
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsFocusable, True)
        self.setZValue(1800)
        # GEO-MAP scene and view swap/geodetically mirror source axes.
        # Counter-transform local coordinates once so text is upright on
        # the default map while remaining in map space and image exports.
        scale = max(0.01, float(scale))
        self.setTransform(QTransform(0, -scale, -scale, 0, 0, 0))
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
        painter.setBrush(QBrush(QColor(255, 255, 255, 247)))
        painter.setPen(QPen(QColor("#B9CED7"), 1.25))
        painter.drawRoundedRect(QRectF(0, 0, self._width, self._height), 13, 13)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(ACCENT))
        painter.drawRoundedRect(QRectF(0, 0, 7, self._height), 3, 3)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing, True)
        kind = self.data["kind"]
        if kind == "north":
            self._paint_north(painter)
            return
        self._panel(painter)
        title = self.data.get("title", "")
        subtitle = self.data.get("subtitle", "")
        details = self.data.get("details", "")
        area = self.data.get("area", "")
        self._text(painter, "GEOSTUDIO  /  OPRAWA MAPY", 24, 13,
                   self._width - 42, 18, size=10, bold=True, color=ACCENT)
        self._text(painter, title, 24, 38, self._width - 44, 52,
                   size=21, bold=True)
        painter.setPen(QPen(QColor("#D8E5E9"), 1))
        painter.drawLine(24, 96, self._width - 24, 96)
        self._text(painter, subtitle, 24, 103, self._width - 48, 40,
                   size=17, bold=True)
        if kind == "legend":
            self._paint_legend_rows(painter, details)
        else:
            self._text(painter, details, 24, 147,
                       self._width - 48,
                       (68 if kind == "title" else 99),
                       size=14, color=MUTED,
                       align=Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap)
        if area:
            self._text(painter, area, 24, self._height - 38,
                       self._width - 45, 27,
                       size=13, bold=True, color=ACCENT)

    def _paint_north(self, painter):
        painter.setPen(QPen(QColor("#C7D8DF"), 1.3))
        painter.setBrush(QBrush(QColor(255, 255, 255, 240)))
        painter.drawRoundedRect(QRectF(5, 5, 122, 170), 15, 15)
        self._text(painter, self.data.get("title") or "N", 31, 10, 72, 35,
                   size=28, bold=True, align=Qt.AlignCenter)
        up = QPainterPath(QPointF(66, 43))
        up.lineTo(34, 124)
        up.lineTo(66, 109)
        up.closeSubpath()
        painter.setPen(QPen(INK, 2))
        painter.setBrush(QBrush(INK))
        painter.drawPath(up)
        down = QPainterPath(QPointF(66, 43))
        down.lineTo(99, 124)
        down.lineTo(66, 109)
        down.closeSubpath()
        painter.setBrush(QBrush(QColor("#D2E2E7")))
        painter.drawPath(down)
        painter.setPen(QPen(ACCENT, 2))
        painter.drawLine(35, 140, 97, 140)
        self._text(painter, "PÓŁNOC", 19, 145, 94, 18,
                   size=11, bold=True, color=ACCENT, align=Qt.AlignCenter)

    def _paint_legend_rows(self, painter, details):
        entries = [entry.strip() for entry in str(details).splitlines()
                   if entry.strip()][:7]
        colors = ("#BFCDA7", "#9CB7CB", "#AA9876", "#71BEBB",
                  "#BA7A75", "#6B8B9E", "#D1BA56")
        for idx, name in enumerate(entries):
            y = 151 + 25 * idx
            painter.setPen(QPen(QColor("#D6E1E5"), 1))
            painter.setBrush(QBrush(QColor(colors[idx])))
            painter.drawRoundedRect(QRectF(25, y + 4, 31, 15), 3, 3)
            self._text(painter, name, 67, y, self._width - 93, 23,
                       size=13, color=INK)

    def mousePressEvent(self, event):
        self._drag_origin = QPointF(self.pos())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        pos = self.pos()
        if (abs(pos.x() - self._drag_origin.x()) +
                abs(pos.y() - self._drag_origin.y())) > 0.00001:
            self._on_move(self.uid, round(pos.x(), 3), round(-pos.y(), 3))

    def mouseDoubleClickEvent(self, event):
        self._on_edit(self.uid)
        event.accept()
