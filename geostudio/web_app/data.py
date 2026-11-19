"""Read-only bridge from the verified GEO-MAP parser to browser coordinates.

GEO-MAP stores northing X and easting Y. The browser uses (east, -north)
to keep the same orientation as the classic geodetic Qt canvas.

No calls to GeoMap.update_field, save_as, or any editing operation occur here.
No user-uploaded map is written to disk.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from threading import RLock
import json
import re

from geostudio.geomap import GeoMap
from geostudio.forest_classes import forest_class_value
from geostudio.geometry_index import GeometryIndex
from geostudio.library_render import native_fill_color

MAX_MAP_BYTES = 80 * 1024 * 1024
MAX_STYLES_BYTES = 2 * 1024 * 1024
MAX_RENDER_FEATURES = 25000
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
STYLE_FORMAT = "geostudio-visual-v1"
CODES = {
    "5216": "Działki",
    "5220": "Użytki",
    "5230": "Użytki",
    "5310": "Budynki",
    "1246": "Graniczniki",
    "6900": "Linie",
    "6000": "Oprawa / linie",
    "7900": "Oprawa / tekst",
}
DEFAULT_COLORS = {
    "5216": "#7F9BC8",
    "5220": "#87AD9F",
    "5230": "#5C9F8B",
    "5310": "#C48F73",
    "1246": "#D6A45F",
    "6900": "#64748B",
}
LABEL_FIELDS = ("A1", "A2", "A3", "A4", "A5", "A6", "TX", "MP", "KR")


def _color(value, fallback):
    return str(value).upper() if isinstance(value, str) and HEX.fullmatch(value) else fallback


def _opacity(value, fallback):
    try:
        return max(0, min(100, int(value)))
    except (ValueError, TypeError):
        return fallback


def _display_name(value: str) -> str:
    return Path(str(value).replace("\\", "/")).name[:160] or "Mapa.MAP"


@dataclass(frozen=True)
class _Entry:
    fid: str
    obj: object
    layer: str
    grade: str | None
    bbox: tuple[float, float, float, float]  # east_min, south_min, east_max, south_max


class PreviewWorkspace:
    """Exactly one immutable uploaded source map plus optional visual sidecar."""

    def __init__(self):
        self._lock = RLock()
        self._doc: GeoMap | None = None
        self._entries: tuple[_Entry, ...] = ()
        self._lookup: dict[str, _Entry] = {}
        self._object_id: dict[int, str] = {}
        self._index: GeometryIndex | None = None
        self._styles: dict[str, dict] = {}
        self._label_positions: dict[str, dict] = {}
        self._bounds: list[float] | None = None
        self._meta: dict = {"loaded": False}

    def load_map(self, content: bytes, filename: str) -> dict:
        if not content or len(content) > MAX_MAP_BYTES:
            raise ValueError("Plik MAP jest pusty lub przekracza limit 80 MB.")
        name = _display_name(filename)
        if not name.lower().endswith(".map"):
            raise ValueError("Wybierz plik z rozszerzeniem .MAP.")
        doc = GeoMap(content, filename=name)
        if not doc.objects:
            raise ValueError("Brak obiektów GEO-MAP w podanym pliku.")
        if not any(obj.points for obj in doc.objects):
            raise ValueError("Plik nie zawiera geometrii do wyświetlenia.")

        entries: list[_Entry] = []
        layer_counts = Counter()
        codes = Counter()
        forest = Counter()
        for ix, obj in enumerate(doc.objects):
            if not obj.points:
                continue
            xs = [p.x for p in obj.points]
            ys = [p.y for p in obj.points]
            grade = forest_class_value(obj)
            layer = "Użytki Leśne" if grade else CODES.get(obj.code, "Kod " + obj.code)
            fid = "f" + str(ix)
            bbox = (min(ys), -max(xs), max(ys), -min(xs))
            entries.append(_Entry(fid, obj, layer, grade, bbox))
            layer_counts[layer] += 1
            codes[obj.code] += 1
            if grade:
                forest[grade] += 1
        extent = [
            min(entry.bbox[0] for entry in entries),
            min(entry.bbox[1] for entry in entries),
            max(entry.bbox[2] for entry in entries),
            max(entry.bbox[3] for entry in entries),
        ]
        index = GeometryIndex((entry.obj for entry in entries), hide_connectors=True)
        metadata = {
            "loaded": True,
            "name": name,
            "objectCount": len(entries),
            "vertexCount": sum(len(e.obj.points) for e in entries),
            "checksumValid": doc.checksum_valid,
            "bounds": extent,
            "layers": [{"name": key, "count": n} for key, n in sorted(layer_counts.items())],
            "codes": dict(codes),
            "forestClasses": dict(sorted(forest.items())),
            "readOnly": True,
            "renderer": "HTML Canvas 2D — preview",
        }
        with self._lock:
            self._doc = doc
            self._entries = tuple(entries)
            self._lookup = {entry.fid: entry for entry in entries}
            self._object_id = {id(entry.obj): entry.fid for entry in entries}
            self._index = index
            self._styles = {}
            self._label_positions = {}
            self._bounds = extent
            self._meta = metadata
        return dict(metadata)

    def metadata(self) -> dict:
        with self._lock:
            return dict(self._meta)

    def set_visual_sidecar(self, content: bytes) -> dict:
        """Accept a user-selected GeoStudio JSON as read-only visual input."""
        if not content or len(content) > MAX_STYLES_BYTES:
            raise ValueError("Plik stylów jest pusty lub przekracza limit 2 MB.")
        with self._lock:
            if not self._doc:
                raise ValueError("Najpierw otwórz mapę .MAP.")
        try:
            payload = json.loads(content)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Niepoprawny format JSON stylów.") from exc
        if not isinstance(payload, dict) or payload.get("format") != STYLE_FORMAT:
            raise ValueError("Nieznany format stylów GeoStudio.")
        raw = payload.get("objects", {})
        styles = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(key, str) and isinstance(value, dict):
                    styles[key[:220]] = value
        pos = payload.get("labels", {})
        labels = pos if isinstance(pos, dict) else {}
        with self._lock:
            self._styles = styles
            self._label_positions = labels
        return {"loaded": True, "styleCount": len(styles), "labelPositions": len(labels)}

    def _style(self, entry: _Entry) -> dict:
        """Approximate the classic scene_builder styling WITHOUT inventing fills.

        A missing style is NOT an instruction to fill the polygon.
        GEO-MAP's own COLORREF controls line color; third style token can
        explicitly specify a native fill. 5230 forest and 5200 compass
        triangles are the documented fallback exceptions.
        """
        obj = entry.obj
        code_style = self._styles.get("code:" + obj.code, {})
        item_style = self._styles.get(obj.uid, {}) if obj.uid else {}
        border = "#" + "".join(f"{c:02X}" for c in obj.colorref)
        native = native_fill_color(obj.style)
        land_use = obj.fields.get("A1", "").strip().casefold()
        force = (code_style.get("force_fill") is True
                 and "fill" in code_style)
        fill_color = None
        opacity = 0

        if obj.code == "5230" and land_use in {"dr", "droga"}:
            # Road class is never a filled land-use area, even with a code
            # styling override (same rule as the original PySide6 window).
            pass
        elif force:
            fill_color = _color(code_style["fill"], border)
            opacity = _opacity(code_style.get("opacity", 100), 100)
        elif "fill" in item_style:
            fill_color = _color(item_style["fill"], border)
            opacity = _opacity(item_style.get("opacity", 100), 100)
        elif "fill" in code_style:
            fill_color = _color(code_style["fill"], border)
            opacity = _opacity(code_style.get("opacity", 100), 100)
        elif obj.code == "5230" and land_use.startswith("ls"):
            fill_color = "#3D9A62"
            opacity = _opacity(code_style.get("opacity", 40), 40)
        elif native:
            fill_color = "#" + "".join(f"{c:02X}" for c in native)
            opacity = _opacity(code_style.get("opacity", 100), 100)
        elif obj.code == "5200" and len(obj.points) == 4 and obj.fields.get("FA") == "0":
            # Black quarters of the native north arrow; not its border
            # boxes / sample swatches on a sheet.
            fill_color = "#111111"
            opacity = 100

        stroke = _color(code_style.get("stroke"), border)
        width = min(12, max(.5, float(code_style.get("stroke_width", 1.0)))) \
            if _valid_number(code_style.get("stroke_width", 1.0)) else 1.0
        no_baseline = (obj.code in {"6900", "7900", "6000", "6301"}
                       and bool(obj.fields.get("TX")))
        return {
            "fill": fill_color or border,
            "opacity": opacity / 100,
            "hasFill": fill_color is not None,
            "stroke": stroke,
            "strokeWidth": width,
            "drawStroke": not no_baseline,
            "pointSize": 1.0,
        }

    def _labels(self, entry: _Entry) -> list[dict]:
        obj = entry.obj
        code_config = self._styles.get("labels:code:" + obj.code, {})
        overrides = code_config.get("fields") if isinstance(code_config, dict) else None
        if isinstance(overrides, dict) and overrides:
            fields = [key for key in LABEL_FIELDS
                      if isinstance(overrides.get(key), dict)
                      and overrides[key].get("visible")]
        elif obj.code == "5310":
            fields = ["A1", "A2"]
        elif obj.code in {"5216", "5220", "5230"}:
            fields = ["A2"]
        elif obj.code in {"7900", "6900", "6000"}:
            fields = ["TX"]
        else:
            fields = []
        pos = self._label_positions.get(obj.uid, {}) if obj.uid else {}
        center = _label_anchor(obj)
        result = []
        for i, field in enumerate(fields):
            value = obj.fields.get(field, "").replace("||", "\n").strip()
            if not value:
                continue
            style = overrides.get(field, {}) if isinstance(overrides, dict) else {}
            location = pos.get(field) if isinstance(pos, dict) else None
            if (isinstance(location, (list, tuple)) and len(location) == 2
                and all(_valid_number(c) for c in location)):
                northing, easting = float(location[0]), float(location[1])
                east, south = easting, -northing
            else:
                east, south = center[1], -center[0]
            is_building = obj.code == "5310"
            is_sheet = obj.code in {"7900", "6900", "6000", "6301"}
            is_forest = obj.code in {"5220", "5230"}
            palette = ("#CC202C" if is_building else
                       "#111111" if is_sheet else
                       "#35753A" if is_forest else
                       "#4A5056" if obj.code == "5216" else "#58686F")
            base_size = (16 if is_building else 24 if is_sheet else
                         11 if is_forest else 12)
            # The old Qt engine draws separate A1 / A2 lines for buildings;
            # keep manual A2 "|" line breaks from the actual MAP.
            formatted = value.replace("|", "\n") if is_building and field == "A2" else value
            result.append({
                "field": field, "text": formatted[:220],
                "x": east, "y": south,
                "offset": (i - (len(fields) - 1) / 2) * base_size * .80,
                "color": _color(style.get("color"), palette),
                "size": max(8, min(36, _int(style.get("size"), base_size))),
                "fontFamily": str(style.get(
                    "font", "Times New Roman" if is_sheet and obj.code in {"7900","6900"}
                    else "Segoe UI"))[:80],
                "bold": bool(style.get("bold", is_building or obj.code in {"7900","6900"})),
            })
        return result

    def _feature(self, entry: _Entry) -> dict:
        obj = entry.obj
        parts = [
            [[p.y, -p.x] for p in segment] for segment in obj.display_parts
            if segment
        ]
        return {
            "id": entry.fid, "code": obj.code, "layer": entry.layer,
            "grade": entry.grade, "bbox": entry.bbox, "closed": obj.is_closed,
            "geometry": parts, "style": self._style(entry),
            "labels": self._labels(entry),
        }

    def viewport(self, bounds: tuple[float, float, float, float],
                 limit: int = MAX_RENDER_FEATURES) -> dict:
        """Query only the visible spatial region; never serialize all map data."""
        west, south, east, north = bounds
        if not all(isfinite(v) for v in bounds) or west > east or south > north:
            raise ValueError("Nieprawidłowy obszar widoku.")
        limit = max(1, min(MAX_RENDER_FEATURES, int(limit)))
        with self._lock:
            if self._index is None or self._bounds is None:
                return {"features": [], "limited": False, "total": 0}
            area = self._bounds
            if not _intersects(area, bounds):
                return {"features": [], "limited": False, "total": 0}
            # Never allow a huge zoom-out request to make GeometryIndex
            # iterate over millions of empty tiles far beyond the source MAP.
            clipped = (max(west, area[0]), max(south, area[1]),
                       min(east, area[2]), min(north, area[3]))
            w, s, e, n = clipped
            radius = max(e - w, n - s) / 2
            candidates = self._index.nearby(-(s + n) / 2,
                                            (w + e) / 2, radius)
            ids = {id(item) for item in candidates}
            visible = [entry for entry in self._entries
                       if id(entry.obj) in ids and _intersects(entry.bbox, clipped)]
            total = len(visible)
            return {
                "features": [self._feature(entry) for entry in visible[:limit]],
                "limited": total > limit, "total": total,
            }

    def details(self, fid: str) -> dict:
        with self._lock:
            try:
                entry = self._lookup[fid]
            except KeyError as exc:
                raise LookupError("Nie znaleziono obiektu.") from exc
            obj = entry.obj
            return {
                "id": fid, "sourceUid": obj.uid, "code": obj.code,
                "layer": entry.layer, "grade": entry.grade,
                "fields": dict(obj.fields),
                "pointCount": len(obj.points),
                "points": [{"x": p.x, "y": p.y, "type": p.point_type}
                           for p in obj.points[:500]],
                "areaM2": obj.area_m2,
                "closed": obj.is_closed,
                "geometryTruncated": len(obj.points) > 500,
            }


def _label_anchor(obj):
    """Match PySide6's centroid rather than an arbitrary bounding-box centre."""
    points = obj.points[:-1] if obj.is_closed else obj.points
    if not points:
        return (0.0, 0.0)
    if not obj.is_closed or len(points) < 3:
        return (sum(p.x for p in points) / len(points),
                sum(p.y for p in points) / len(points))
    x0, y0 = points[0].x, points[0].y
    area2 = cx = cy = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        ax, ay = point.x - x0, point.y - y0
        bx, by = next_point.x - x0, next_point.y - y0
        cross = ax * by - bx * ay
        area2 += cross
        cx += (ax + bx) * cross
        cy += (ay + by) * cross
    if abs(area2) < 1e-10:
        return (sum(p.x for p in points) / len(points),
                sum(p.y for p in points) / len(points))
    return (x0 + cx / (3 * area2), y0 + cy / (3 * area2))


def _valid_number(value):
    try:
        return isfinite(float(value))
    except (ValueError, TypeError):
        return False


def _int(value, default):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _intersects(a, b):
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]
