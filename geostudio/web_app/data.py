"""Read-only bridge from the verified GEO-MAP parser to browser coordinates.

GEO-MAP stores northing X and easting Y. The browser uses (east, -north)
to keep the same orientation as the classic geodetic Qt canvas.

No calls to GeoMap.update_field, save_as, or any editing operation occur here.
No user-uploaded map is written to disk.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import isfinite, hypot
from pathlib import Path
from threading import RLock
from secrets import token_hex
import json
import re

from geostudio.geomap import GeoMap
from geostudio.forest_classes import forest_class_value
from geostudio.geometry_index import GeometryIndex
from geostudio.history import History
from geostudio.topology_edit import linked_vertex_moves
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


class _WebHistoryTarget:
    """Qt-free adapter for the original GEO-MAP transaction engine."""

    def __init__(self, workspace):
        self.workspace = workspace

    @property
    def lines(self):
        return self.workspace._doc.lines

    @property
    def visual_styles(self):
        return self.workspace._styles

    @property
    def label_positions(self):
        return self.workspace._label_positions

    def reparse(self):
        self.workspace._doc._parse()
        self.workspace._reindex(self.workspace._doc, self.workspace._doc.filename)


class PreviewWorkspace:
    """One original MAP with a disposable working copy held exclusively in RAM."""

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
        self._history: History | None = None
        self._revision = 0
        self._document_token = ""

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

        with self._lock:
            self._revision = 0
            self._document_token = token_hex(16)
            self._reindex(doc, name)
            self._styles = {}
            self._label_positions = {}
            self._history = History(_WebHistoryTarget(self))
            return self.metadata()

    def _reindex(self, doc: GeoMap, name: str) -> dict:
        """Refresh object references after an attribute edit or history action."""
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
            "readOnly": True,  # uploaded source is never changed on disk
            "editingEnabled": True,
            "renderer": "HTML Canvas 2D — editable in-memory copy",
        }
        with self._lock:
            self._doc = doc
            self._entries = tuple(entries)
            self._lookup = {entry.fid: entry for entry in entries}
            self._object_id = {id(entry.obj): entry.fid for entry in entries}
            self._index = index
            self._bounds = extent
            self._meta = metadata
        return dict(metadata)

    def _editing_status(self) -> dict:
        history = self._history
        return {
            "dirty": bool(history and history.is_dirty),
            "canUndo": bool(history and history.can_undo),
            "canRedo": bool(history and history.can_redo),
            "undoLabel": history.next_undo_label if history else "",
            "redoLabel": history.next_redo_label if history else "",
            "revision": self._revision,
            "documentToken": self._document_token,
        }

    def editing_status(self) -> dict:
        with self._lock:
            return self._editing_status()

    def edit_fields(self, fid: str, changes: dict, *,
                    document_token: str, revision: int) -> dict:
        """Edit existing fields only. Preserve all unrelated MAP source bytes."""
        with self._lock:
            if self._doc is None or self._history is None:
                raise ValueError("Najpierw otwórz plik MAP.")
            if (document_token != self._document_token or
                    type(revision) is not int or revision != self._revision):
                raise RuntimeError("Mapa została zmieniona. Odśwież wybrany obiekt.")
            entry = self._lookup.get(fid)
            if entry is None or not entry.obj.uid:
                raise LookupError("Nie znaleziono edytowalnego obiektu z ID.")
            if (not isinstance(changes, dict) or not changes or
                    len(changes) > len(LABEL_FIELDS)):
                raise ValueError("Podaj zmiany w znanych atrybutach.")
            edits = {}
            for field, value in changes.items():
                if field not in LABEL_FIELDS or field not in entry.obj.fields:
                    raise ValueError(f"Pole {field} nie istnieje lub nie jest edytowalne.")
                if (not isinstance(value, str) or len(value) > 512 or
                        any(ch in value for ch in "\r\n]")):
                    raise ValueError(f"Nieprawidłowa wartość pola {field}.")
                try:
                    if len(value.encode("cp1250", errors="strict")) > 512:
                        raise ValueError("Zbyt długa wartość atrybutu.")
                except UnicodeEncodeError as exc:
                    raise ValueError(
                        "Ten znak nie jest obsługiwany przez kodowanie GEO-MAP CP1250."
                    ) from exc
                if entry.obj.fields[field] != value:
                    edits[(entry.obj.uid, field)] = value
            if not edits:
                return {**self._editing_status(), "changed": False, "object": self.details(fid)}
            with self._history.begin(
                "Atrybuty obiektu " + entry.obj.code,
                selection_before=(entry.obj.uid,),
            ):
                self._doc.bulk_update_fields(edits)
            self._reindex(self._doc, self._doc.filename)
            self._revision += 1
            return {**self._editing_status(), "changed": True, "object": self.details(fid)}

    def move_vertex(self, fid: str, index: int, x: float, y: float,
                    *, shared: bool, document_token: str, revision: int) -> dict:
        """Move a polygon corner in an in-memory copy in one undoable transaction.

        Coordinates are native GEO-MAP northing X / easting Y, not browser
        pixel coordinates. Shared mode touches coincident SAME-CODE vertices
        only; other codes stay byte-identical. Validation of all affected
        closed rings is delegated to the original GeoMap edit engine.
        """
        with self._lock:
            if self._doc is None or self._history is None:
                raise ValueError("Najpierw otwórz mapę.")
            if (document_token != self._document_token or
                    type(revision) is not int or revision != self._revision):
                raise RuntimeError("Dokument zmienił się od rozpoczęcia edycji.")
            if (type(index) is not int or type(shared) is not bool or
                    type(x) not in (int, float) or type(y) not in (int, float) or
                    not all(isfinite(z) and -1e9 < z < 1e9 for z in (x, y))):
                raise ValueError("Nieprawidłowe współrzędne lub indeks węzła.")
            entry = self._lookup.get(fid)
            if entry is None:
                raise LookupError("Nie znaleziono wskazanego obiektu.")
            obj = entry.obj
            if not obj.uid or not obj.is_closed or len(obj.points) < 4:
                raise ValueError("Można przesuwać tylko węzły zamkniętych poligonów z ID.")
            if not 0 <= index < len(obj.points) - 1:
                raise ValueError("Węzeł poza zakresem poligonu.")
            # Match the source precision: sending higher precision from a
            # zoomed Canvas must not alter unrelated source coordinates.
            x, y = round(x, 3), round(y, 3)
            old = obj.points[index]
            if hypot(old.x - x, old.y - y) < 0.0005:
                return {**self._editing_status(), "changed": False,
                        "affected": [], "object": self.details(fid)}
            changes = (linked_vertex_moves(self._doc, obj.uid, index, x, y)
                       if shared else {obj.uid: {index: (x, y)}})
            with self._history.begin(
                "Przesunięcie węzła " + obj.code,
                selection_before=(obj.uid,),
            ):
                self._doc.move_polygon_vertices(changes)
            self._reindex(self._doc, self._doc.filename)
            self._revision += 1
            return {**self._editing_status(), "changed": True,
                    "affected": list(changes), "object": self.details(fid)}

    def step_history(self, direction: str, *, document_token: str,
                     revision: int) -> dict:
        with self._lock:
            if self._history is None:
                raise ValueError("Najpierw otwórz mapę.")
            if (document_token != self._document_token or
                    type(revision) is not int or revision != self._revision):
                raise RuntimeError("Nieaktualny dokument lub jego wersja.")
            if direction == "undo":
                item = self._history.undo()
            elif direction == "redo":
                item = self._history.redo()
            else:
                raise ValueError("Nieznana operacja historii.")
            if item is not None:
                self._revision += 1
            return {**self._editing_status(), "changed": item is not None}

    def export_copy(self, document_token: str) -> tuple[str, bytes]:
        """Return a valid MAP download; never write it on the server."""
        with self._lock:
            if self._doc is None:
                raise ValueError("Najpierw otwórz mapę.")
            if document_token != self._document_token:
                raise RuntimeError("Nieaktualny dokument.")
            basename = _display_name(self._doc.filename)
            return basename[:-4] + "_GeoStudio2_kopia.MAP", self._doc.to_bytes()

    def metadata(self) -> dict:
        with self._lock:
            return {**self._meta, **self._editing_status()}

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
                "worldTextHeight": _sheet_text_height(obj.fields) if is_sheet else None,
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
                "editableFields": [key for key in LABEL_FIELDS if key in obj.fields]
                                  if obj.uid else [],
                "revision": self._revision,
                "documentToken": self._document_token,
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


def _sheet_text_height(fields):
    """GEO-MAP sheet annotations use their A1 height in map units."""
    raw = str(fields.get("A1", "12")).replace(",", ".")
    try:
        n = float(raw)
        return min(2000., max(1., n)) if isfinite(n) and n > 0 else 12.
    except (TypeError, ValueError):
        return 12.


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
