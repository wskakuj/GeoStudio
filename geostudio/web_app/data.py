"""Read-only bridge from the verified GEO-MAP parser to browser coordinates.

GEO-MAP stores northing X and easting Y. The browser uses (east, -north)
to keep the same orientation as the classic geodetic Qt canvas.

No calls to GeoMap.update_field, save_as, or any editing operation occur here.
No user-uploaded map is written to disk.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
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
from geostudio.topology_edit import linked_vertex_plan
from geostudio.interactions import find_snap, closest_point_on_edge
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
        self._uid_counts: Counter = Counter()
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
            self._uid_counts = Counter(obj.uid for obj in doc.objects if obj.uid)
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
            if (self._uid_counts.get(entry.obj.uid) != 1 or
                    self._doc.by_id.get(entry.obj.uid) is not entry.obj):
                raise ValueError(
                    "Niejednoznaczny identyfikator :ID. "
                    "Nie można bezpiecznie edytować atrybutów tego obiektu.")
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

    @staticmethod
    def _foreign_code_digest(doc: GeoMap, edited_code: str) -> bytes:
        """Fingerprint every unedited-code record including native P lines.

        Used inside the atomic History transaction. A mismatch raises and
        History rolls back the WHOLE edit, rather than exporting damaged MAP.
        """
        digest = sha256()
        for record in doc.objects:
            if record.code == edited_code:
                continue
            digest.update(b"\\x00" + record.code.encode("ascii", "replace"))
            for raw in doc.lines[record.start:record.end]:
                digest.update(raw)
        return digest.digest()

    def move_vertex(self, fid: str, index: int, x: float, y: float,
                    *, shared: bool, document_token: str, revision: int,
                    snap_radius: float = 0) -> dict:
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
            if obj.uid and (self._uid_counts.get(obj.uid) != 1 or
                            self._doc.by_id.get(obj.uid) is not obj):
                # GEO-MAP IDs can appear more than once in malformed/merged
                # source maps. by_id would point to the LAST occurrence,
                # possibly a 5220 despite a selected 5310. Never guess.
                raise ValueError(
                    "Niejednoznaczny identyfikator :ID obiektu. "
                    "Edycja węzła została zablokowana, aby nie zmienić innego kodu.")
            if not obj.uid or not obj.is_closed or len(obj.points) < 4:
                raise ValueError("Można przesuwać tylko węzły zamkniętych poligonów z ID.")
            if not 0 <= index < len(obj.points) - 1:
                raise ValueError("Węzeł poza zakresem poligonu.")
            if (type(snap_radius) not in (int, float) or
                    not isfinite(snap_radius) or not 0 <= snap_radius <= 50):
                raise ValueError("Nieprawidłowy promień przyciągania.")
            snapped = None
            if snap_radius > 0:
                candidates = self._index.nearby(x, y, snap_radius)
                if shared:
                    # A linked neighbor must MOVE with this corner, so its
                    # OLD edge must never behave as a snap target. That
                    # otherwise pins a T-junction to the stationary edge.
                    linked_at_start = linked_vertex_plan(
                        self._doc, obj.uid, index,
                        obj.points[index].x, obj.points[index].y)
                    moving_uids = set(linked_at_start.moves)
                    candidates = [
                        item for item in candidates
                        if item.code == obj.code and item.uid not in moving_uids
                    ]
                snapped = find_snap(x, y, candidates, snap_radius,
                                    exclude_uid=obj.uid, hide_connectors=True)
                if snapped:
                    x, y = snapped.x, snapped.y
            # Match the source precision: sending higher precision from a
            # zoomed Canvas must not alter unrelated source coordinates.
            x, y = round(x, 3), round(y, 3)
            old = obj.points[index]
            if hypot(old.x - x, old.y - y) < 0.0005:
                return {**self._editing_status(), "changed": False,
                        "affected": [], "object": self.details(fid)}
            plan = (linked_vertex_plan(self._doc, obj.uid, index, x, y)
                    if shared else None)
            changes = plan.moves if plan else {obj.uid: {index: (x, y)}}
            insertions = plan.inserts if plan else {}
            # Defense in depth: never trust an input ID or the planner's
            # resulting UID dictionary without resolving each exact object.
            for uid in changes:
                linked = self._doc.by_id.get(uid)
                if (self._uid_counts.get(uid) != 1 or linked is None or
                        linked.code != obj.code):
                    raise ValueError(
                        "Zablokowano zmianę: wspólne węzły mogą dotyczyć "
                        "wyłącznie jednoznacznych obiektów kodu " + obj.code + ".")
            foreign_before = self._foreign_code_digest(self._doc, obj.code)
            with self._history.begin(
                "Przesunięcie węzła " + obj.code,
                selection_before=(obj.uid,),
            ):
                # A neighboring 5310 may share an edge but have NO P record
                # exactly where the selected 5310 corner touches it.
                # Insert the missing native P at that old border coordinate,
                # then move both vertices. Undo reverses insertion + motion.
                for uid, (segment, corner) in insertions.items():
                    self._doc.insert_polygon_vertex(uid, segment, *corner)
                self._doc.move_polygon_vertices(changes)
                if self._foreign_code_digest(self._doc, obj.code) != foreign_before:
                    raise ValueError(
                        "Przerwano edycję: wykryto zmianę rekordu innego kodu. "
                        "Wszystkie współrzędne zostały przywrócone.")
            self._reindex(self._doc, self._doc.filename)
            self._revision += 1
            return {**self._editing_status(), "changed": True,
                    "affected": list(changes),
                    "insertedSameCodeVertices": len(insertions),
                    "affectedObjects": [
                        {"uid": uid, "code": obj.code} for uid in changes
                    ],
                    "sourceCode": obj.code,
                    "foreignCodesProtected": True,
                    "object": self.details(fid),
                    "snap": ({"kind": snapped.kind, "code": snapped.code,
                              "uid": snapped.uid, "x": x, "y": y}
                             if snapped else None)}

    def insert_vertex(self, fid: str, segment_index: int, x: float, y: float,
                      *, shared: bool, document_token: str, revision: int,
                      edge_radius: float = 0.0) -> dict:
        """Insert a P record on the selected polygon edge (double click).

        If shared topology is requested, split precisely coincident edges of
        OTHER SAME-CODE closed polygons in the SAME transaction. 5220 or any
        unrelated code must stay byte-identical. No vertex is invented off
        the selected edge; only its orthogonal projection can be inserted.
        """
        with self._lock:
            if self._doc is None or self._history is None:
                raise ValueError("Najpierw otwórz mapę.")
            if (document_token != self._document_token or
                    type(revision) is not int or revision != self._revision):
                raise RuntimeError("Dokument zmienił się od rozpoczęcia edycji.")
            if (type(segment_index) is not int or type(shared) is not bool or
                    type(x) not in (int, float) or type(y) not in (int, float) or
                    type(edge_radius) not in (int, float) or
                    not all(isfinite(v) for v in (x, y, edge_radius)) or
                    not (-1e9 < x < 1e9 and -1e9 < y < 1e9) or
                    not 0 <= edge_radius <= 50):
                raise ValueError("Nieprawidłowy punkt lub promień wstawienia.")
            entry = self._lookup.get(fid)
            if entry is None:
                raise LookupError("Nie znaleziono obiektu.")
            obj = entry.obj
            if (not obj.uid or self._uid_counts.get(obj.uid) != 1 or
                    self._doc.by_id.get(obj.uid) is not obj):
                raise ValueError("Niejednoznaczny lub brakujący :ID poligonu.")
            if not obj.is_closed or len(obj.points) < 4:
                raise ValueError("Dwuklik działa tylko na zamkniętych poligonach.")
            if not 0 <= segment_index < len(obj.points) - 1:
                raise ValueError("Wskazana krawędź nie należy do poligonu.")
            a, b = obj.points[segment_index:segment_index + 2]
            if a.point_type == 0:
                raise ValueError("Nie wolno dodawać punktu na ukrytym łączniku P 0.")
            px, py = closest_point_on_edge(x, y, a.x, a.y, b.x, b.y)
            if hypot(px - x, py - y) > max(0.002, edge_radius):
                raise ValueError("Kliknij bezpośrednio na krawędzi poligonu.")
            px, py = round(px, 3), round(py, 3)
            # Native precision is 1 mm. Avoid splitting at endpoints or
            # creating duplicate P records that are nearly coincident.
            if min(hypot(px - a.x, py - a.y),
                   hypot(px - b.x, py - b.y)) < 0.006:
                raise ValueError("Kliknięto zbyt blisko istniejącego węzła.")
            neighbors = []
            if shared:
                # This checks the SOURCE geometry, not potentially altered
                # indexes. One candidate edge per neighbor or abort.
                for other in self._doc.objects:
                    if (other is obj or other.code != obj.code or
                            not other.is_closed or not other.uid):
                        continue
                    candidates = []
                    already_present = any(
                        hypot(p.x - px, p.y - py) <= .0015
                        for p in other.points[:-1])
                    if already_present:
                        continue
                    for i, (oa, ob) in enumerate(zip(
                            other.points, other.points[1:])):
                        if oa.point_type == 0:
                            continue
                        ex, ey = closest_point_on_edge(
                            px, py, oa.x, oa.y, ob.x, ob.y)
                        if (hypot(px - ex, py - ey) <= .0015 and
                                hypot(ex - oa.x, ey - oa.y) >= .006 and
                                hypot(ex - ob.x, ey - ob.y) >= .006):
                            candidates.append(i)
                    if len(candidates) > 1:
                        raise ValueError(
                            "Niejednoznaczna krawędź wspólna kodu " + obj.code)
                    if candidates:
                        if (self._uid_counts.get(other.uid) != 1 or
                                self._doc.by_id.get(other.uid) is not other):
                            raise ValueError(
                                "Niejednoznaczny identyfikator sąsiedniego poligonu.")
                        neighbors.append((other.uid, candidates[0]))
            foreign_before = self._foreign_code_digest(self._doc, obj.code)
            with self._history.begin(
                "Dodanie węzła " + obj.code,
                selection_before=(obj.uid,),
            ):
                self._doc.insert_polygon_vertex(
                    obj.uid, segment_index, px, py)
                for uid, edge_index in neighbors:
                    self._doc.insert_polygon_vertex(uid, edge_index, px, py)
                if self._foreign_code_digest(self._doc, obj.code) != foreign_before:
                    raise ValueError(
                        "Wykryto zmianę innego kodu. Operację w całości cofnięto.")
            self._reindex(self._doc, self._doc.filename)
            self._revision += 1
            uids = [obj.uid] + [uid for uid, _ in neighbors]
            return {
                **self._editing_status(), "changed": True,
                "sourceCode": obj.code, "foreignCodesProtected": True,
                "insertedVertexIndex": segment_index + 1,
                "insertedSameCodeVertices": len(neighbors),
                "newVertex": {"x": px, "y": py},
                "affected": uids,
                "affectedObjects": [
                    {"uid": uid, "code": obj.code} for uid in uids],
                "object": self.details(fid),
            }

    def delete_vertex(self, fid: str, index: int, *,
                      shared: bool, document_token: str, revision: int) -> dict:
        """Remove selected native P vertex, protecting other codes and topology.

        Shared mode removes matching vertices of SAME-CODE polygons, never
        foreign codes. If another same-code edge has a T-junction at this
        coordinate but NO explicit vertex, reject it as ambiguous.
        """
        with self._lock:
            if self._doc is None or self._history is None:
                raise ValueError("Najpierw otwórz mapę.")
            if (document_token != self._document_token or
                    type(revision) is not int or revision != self._revision):
                raise RuntimeError("Dokument zmienił się od rozpoczęcia usuwania.")
            if type(index) is not int or type(shared) is not bool:
                raise ValueError("Nieprawidłowy numer węzła lub tryb topologii.")
            entry = self._lookup.get(fid)
            if entry is None:
                raise LookupError("Nie znaleziono wskazanego poligonu.")
            obj = entry.obj
            if (not obj.uid or self._uid_counts.get(obj.uid) != 1 or
                    self._doc.by_id.get(obj.uid) is not obj):
                raise ValueError("Niejednoznaczny identyfikator :ID obiektu.")
            if not obj.is_closed or not 0 <= index < len(obj.points) - 1:
                raise ValueError("Wskaż istniejący węzeł zamkniętego poligonu.")
            if len(obj.points) <= 4:
                raise ValueError("Nie można usunąć węzła z poligonu trójkątnego.")
            selected = obj.points[index]
            removals: dict[str, set[int]] = {obj.uid: {index}}
            if shared:
                for other in self._doc.objects:
                    if (other is obj or other.code != obj.code or
                            not other.is_closed):
                        continue
                    matching = [
                        i for i, point in enumerate(other.points[:-1])
                        if hypot(point.x - selected.x,
                                 point.y - selected.y) <= .0015]
                    if len(matching) > 1:
                        raise ValueError("Wspólny węzeł występuje wielokrotnie.")
                    if matching:
                        if (not other.uid or self._uid_counts.get(other.uid) != 1 or
                                self._doc.by_id.get(other.uid) is not other):
                            raise ValueError("Niejednoznaczny identyfikator sąsiada.")
                        removals[other.uid] = {matching[0]}
                        continue
                    # A junction to an edge without its own P must not be
                    # silently altered by shortening the source contour.
                    for oa, ob in zip(other.points, other.points[1:]):
                        if oa.point_type == 0:
                            continue
                        cx, cy = closest_point_on_edge(
                            selected.x, selected.y, oa.x, oa.y, ob.x, ob.y)
                        if (hypot(cx - selected.x, cy - selected.y) <= .0015 and
                                min(hypot(cx - oa.x, cy - oa.y),
                                    hypot(cx - ob.x, cy - ob.y)) > .005):
                            raise ValueError(
                                "Sąsiedni poligon tego samego kodu ma wspólną "
                                "krawędź bez węzła. Dodaj najpierw jego punkt "
                                "lub wyłącz tryb wspólnych węzłów.")
            for uid in removals:
                candidate = self._doc.by_id.get(uid)
                if (candidate is None or candidate.code != obj.code or
                        self._uid_counts.get(uid) != 1):
                    raise ValueError("Próba zmiany obiektu o innym kodzie została zablokowana.")
            foreign_before = self._foreign_code_digest(self._doc, obj.code)
            with self._history.begin(
                "Usunięcie węzła " + obj.code, selection_before=(obj.uid,)
            ):
                self._doc.delete_polygon_vertices(removals)
                if self._foreign_code_digest(self._doc, obj.code) != foreign_before:
                    raise ValueError("Wykryto zmianę obiektu innego kodu. Cofnięto operację.")
            self._reindex(self._doc, self._doc.filename)
            self._revision += 1
            return {
                **self._editing_status(), "changed": True,
                "sourceCode": obj.code, "foreignCodesProtected": True,
                "removedSameCodeVertices": len(removals) - 1,
                "affected": list(removals),
                "affectedObjects": [
                    {"uid": uid, "code": obj.code} for uid in removals
                ],
                "object": self.details(fid),
            }

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
