"""Editable, map-anchored composition elements for GeoStudio.

These are modern overlays, not unverified writes to GEO-MAP's 5200/6000/7900
primitives. Their information and positions are saved in the existing
.geostudio.json style sidecar, and can be exported as part of a rendered scene.
"""
from __future__ import annotations

from uuid import uuid4
from math import hypot, ceil

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QBrush, QTransform
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
                columns = max(1, ceil(len(rows) / 15))
                self._width = max(self._width, 365 * columns + 25)
                self._height = max(150, 115 + 24 * min(len(rows), 15))
        elif data["kind"] in {"title", "credits"}:
            # Height must include ALL of the long editable description,
            # even after the user enters several lines and zooms the page.
            detail_lines = self._wrapped_details(str(data.get("details", "")),
                                                 self._width - 30)
            self._height = max(
                self._height,
                103 + 23 * len(detail_lines) +
                (44 if str(data.get("area", "")).strip() else 15))
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

    def shape(self):
        """Hit-test only painted content + resizing handle, never empty layout.

        The old giant boundingRect() caused neighbouring transparent objects
        to intercept each other's clicks. It must remain large for painting,
        but the Qt mouse-pick shape must stay tight to actual content.
        """
        hit = QPainterPath()
        kind = self.layout_data["kind"]
        if kind == "north":
            hit.addEllipse(QRectF(28, 28, 128, 128))
            for r in (QRectF(73, 0, 38, 29), QRectF(154, 73, 30, 37),
                      QRectF(74, 154, 36, 30), QRectF(0, 73, 32, 37)):
                hit.addRect(r)
        else:
            def add_text(text, x, y, font_size, *, limit=None):
                if not str(text).strip():
                    return
                metric = QFontMetricsF(self._font(font_size, bold=True))
                lines = str(text).splitlines()
                for idx, line in enumerate(lines):
                    if not line.strip():
                        continue
                    w = min(metric.horizontalAdvance(line) + 14,
                            limit or self._width - x - 12)
                    h = metric.height() + 5
                    hit.addRect(QRectF(x, y + idx * h, w, h))
            add_text(self.layout_data.get("title", ""), 13, 0, 21)
            add_text(self.layout_data.get("subtitle", ""), 14, 45, 17)
            if kind == "legend":
                rows = self.layout_data.get("items", [])
                if not isinstance(rows, list):
                    rows = [{"name": x} for x in str(
                        self.layout_data.get("details", "")).splitlines()]
                for idx, entry in enumerate(rows[:100]):
                    col, row = divmod(idx, 15)
                    x = 15 + col * 365
                    y = 95 + row * 24
                    hit.addRect(QRectF(x, y + 2, 36, 18))
                    add_text(entry.get("name", ""), x + 50, y, 13,
                             limit=286)
            else:
                add_text(self.layout_data.get("details", ""), 14, 93, 14)
            if self.layout_data.get("area"):
                add_text(self.layout_data["area"], 14, self._height - 35, 13)
        # The selection/resize handle must be accessible only when selected.
        if self.isSelected():
            hit.addRect(QRectF(self._width - 18, self._height - 18, 21, 21))
        return hit

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

    @staticmethod
    def _wrapped_details(details: str, width: float) -> list[str]:
        """Wrap editable description text to a real font-measured width.

        The original QRectF + word-wrap call silently omitted body text in
        some Qt/Windows paint configurations. Lines are now explicitly laid
        out and drawn by baseline, including hard line breaks and long names.
        """
        font = DecorationItem._font(14)
        metrics = QFontMetricsF(font)
        usable_width = max(45.0, float(width))
        result = []
        for original in details.splitlines():
            if not original.strip():
                result.append("")
                continue
            line = ""
            for word in original.split():
                proposed = word if not line else line + " " + word
                if line and metrics.horizontalAdvance(proposed) > usable_width:
                    result.append(line)
                    line = word
                else:
                    line = proposed
                # Also handle extremely long unbroken words/cadastral IDs.
                while line and metrics.horizontalAdvance(line) > usable_width:
                    end = len(line) - 1
                    while end > 1 and metrics.horizontalAdvance(line[:end]) > usable_width:
                        end -= 1
                    result.append(line[:max(1, end)])
                    line = line[max(1, end):]
            if line:
                result.append(line)
        return result

    def _paint_details(self, painter, details):
        """Draw each requested line, rather than relying on a clipped block."""
        lines = self._wrapped_details(details, self._width - 30)
        painter.setFont(self._font(14))
        painter.setPen(MUTED)
        metrics = QFontMetricsF(painter.font())
        y = 98.0 + metrics.ascent()
        for line in lines:
            if line:
                painter.drawText(QPointF(14.0, y), line)
            y += 23.0

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
            self._paint_details(painter, details)
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
        for idx, entry in enumerate(entries[:100]):
            column, row = divmod(idx, 15)
            left = 15 + column * 365
            y = 95 + row * 24
            name = str(entry.get("name", ""))[:150]
            color = QColor(str(entry.get("color", "#91ABA7")))
            if not color.isValid():
                color = ACCENT
            painter.setPen(QPen(color.darker(115), 1))
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(QRectF(left, y + 4, 34, 14), 2, 2)
            self._text(painter, name, left + 50, y, 290, 22,
                       size=13, color=INK)

    def mousePressEvent(self, event):
        # Qt moves all selected movable items as a group. The user expects
        # each nearby annotation to move independently, never as a group.
        if self.scene() is not None:
            self.scene().clearSelection()
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
