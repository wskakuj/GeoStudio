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
import base64

from geostudio.geomap import GeoMap
from geostudio.forest_classes import forest_class_value
from geostudio.geometry_index import GeometryIndex
from geostudio.history import History
from geostudio.topology_edit import linked_vertex_plan
from geostudio.web_app.topology_safety import rings_overlap, rings_contact, ring_of, nearest_boundary_snap
from geostudio.web_app.geometry_6a import (polygon_of, geometry_of, visible_difference,
    shape_parts, split_simple, merge_simple, merge_multipart, rings_from_shape)
from geostudio.interactions import find_snap, closest_point_on_edge, polygon_is_valid
from geostudio.library_render import native_fill_color

MAX_MAP_BYTES = 80 * 1024 * 1024
MAX_STYLES_BYTES = 2 * 1024 * 1024
MAX_RENDER_FEATURES = 25000
MAX_SELECTED_FEATURES = 50000
MAX_BULK_EDIT_OBJECTS = 5000
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
STYLE_FORMAT = "geostudio-visual-v1"
TOPOLOGY_STACK_KEY = "__geostudio_topology_stack_v1__"
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
        self._bulk_preview_key = ""
        self._move_preview_key = ""
        self._objects_preview_key = ""
        self._geometry_preview_key = ""

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
            self._bulk_preview_key = ""
            self._move_preview_key = ""
            self._objects_preview_key = ""
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

    def _overlay_uids(self) -> list[str]:
        record=self._styles.get(TOPOLOGY_STACK_KEY,{})
        return list(record.get("uids",[])) if isinstance(record,dict) else []

    def _raise_to_top(self, uids) -> None:
        """History-tracked precedence, without changing underlying source P."""
        order=self._overlay_uids()
        affected=set(uids)
        order=[uid for uid in order if uid not in affected]
        order.extend(uid for uid in uids if uid not in order)
        # Retain only existing unique IDs; no stale deletions or ambiguity.
        self._styles[TOPOLOGY_STACK_KEY]={"uids":order[-5000:]}

    def export_topology_metadata(self, map_bytes: bytes) -> bytes | None:
        """Companion overlay JSON; SHA bound to the exact saved MAP bytes."""
        with self._lock:
            uids=self._overlay_uids()
            if not uids:
                return None
            return json.dumps({"format":"geostudio-topology-v1",
                "sha256":sha256(map_bytes).hexdigest(),"uids":uids},
                ensure_ascii=False,indent=2).encode("utf-8")

    def import_topology_metadata(self, content: bytes, map_bytes: bytes) -> None:
        """Load saved precedence only when companion checksum and UIDs match."""
        if not content or len(content)>MAX_STYLES_BYTES:
            raise ValueError("Za duży plik topologii.")
        obj=json.loads(content)
        if (not isinstance(obj,dict) or
                set(obj)!={"format","sha256","uids"} or
                obj["format"]!="geostudio-topology-v1" or
                obj["sha256"]!=sha256(map_bytes).hexdigest() or
                not isinstance(obj["uids"],list) or len(obj["uids"])>5000):
            raise ValueError("Plik topologii nie pasuje do MAP.")
        with self._lock:
            if not self._doc:raise ValueError("Najpierw wczytaj MAP.")
            counts=Counter(o.uid for o in self._doc.objects if o.uid)
            if (len(set(obj["uids"]))!=len(obj["uids"]) or
                    any(not isinstance(uid,str) or counts.get(uid)!=1
                        for uid in obj["uids"])):
                raise ValueError("Plik topologii zawiera nieprawidłowe identyfikatory.")
            self._styles[TOPOLOGY_STACK_KEY]={"uids":obj["uids"]}

    def export_positive_copy(self, document_token: str) -> tuple[str,bytes]:
        """Windows Save As: automatically normalize all simple exterior rings.

        The original source map and undo stack stay untouched.
        """
        with self._lock:
            if self._doc is None:
                raise ValueError("Najpierw otwórz mapę.")
            if document_token!=self._document_token:
                raise RuntimeError("Nieaktualny dokument.")
            name=_display_name(self._doc.filename)
            return name[:-4]+"_GeoStudio2_kopia.MAP", self._doc.to_bytes_positive_areas()

    @staticmethod
    def _raw_p_records(doc, obj):
        """Return a contiguous native P span without stripping source metadata."""
        from geostudio.geomap import POINT_RE
        indices=[i for i in range(obj.start+1,obj.end)
                 if POINT_RE.match(doc.lines[i].rstrip(b'\r\n'))]
        if not indices or len(indices)!=len(obj.points) or (
                indices[-1]-indices[0]+1)!=len(indices):
            raise ValueError("Przeplatane rekordy P. Nie można bezpiecznie wyeksportować wycięć.")
        return doc.lines[indices[0]:indices[-1]+1]

    def export_native_cutouts(self, document_token: str) -> tuple[str,bytes,bytes]:
        """Stage 6B: native P0 contours with reversible, checksum-bound backup.

        Foreground objects remain unchanged; lower same-code polygons receive
        true boolean cutouts in a disposable MAP copy. Full occlusion is
        explicitly blocked rather than destroying an object's identity.
        """
        with self._lock:
            if self._doc is None:
                raise ValueError("Najpierw otwórz mapę.")
            if document_token!=self._document_token:
                raise RuntimeError("Nieaktualny dokument.")
            base_bytes=self._doc.to_bytes_positive_areas()
            base=GeoMap(base_bytes,filename=self._doc.filename)
            counts=Counter(o.uid for o in base.objects if o.uid)
            ordered=[uid for uid in self._overlay_uids()
                     if uid in base.by_id and counts[uid]==1]
            order_position={uid:i for i,uid in enumerate(ordered)}
            baked=GeoMap(base_bytes,filename=self._doc.filename)
            original_p={}
            expectations={}
            total_change=0
            # Establish geometric ground truth from the base BEFORE mutations.
            for obj in base.objects:
                if not obj.is_closed or not obj.uid:
                    continue
                pos=order_position.get(obj.uid,-1)
                foreground=[]
                for uid in ordered[pos+1:]:
                    upper=base.by_id[uid]
                    if upper.uid==obj.uid or upper.code!=obj.code or not upper.is_closed:
                        continue
                    if (max(p.x for p in upper.points)<min(p.x for p in obj.points) or
                        min(p.x for p in upper.points)>max(p.x for p in obj.points) or
                        max(p.y for p in upper.points)<min(p.y for p in obj.points) or
                        min(p.y for p in upper.points)>max(p.y for p in obj.points)):
                        continue
                    foreground.append(upper)
                if not foreground:
                    continue
                base_shape=geometry_of(obj)
                visible=visible_difference(base_shape,
                                          [geometry_of(other) for other in foreground])
                if base_shape.area-visible.area<.000001:
                    continue
                if counts[obj.uid]!=1:
                    raise ValueError("Wycinany obiekt nie ma unikatowego :ID.")
                if visible.is_empty or visible.area<.000001:
                    raise ValueError(
                        "Poligon jest całkowicie przykryty przez inny. "
                        "Bezpieczny eksport wstrzymano, aby zachować jego :ID.")
                rings=rings_from_shape(visible)
                original_p[obj.uid]=[
                    base64.b64encode(line).decode("ascii")
                    for line in self._raw_p_records(base,obj)]
                expectations[obj.uid]=visible
                total_change+=sum(len(ring) for ring in rings)
                if len(original_p)>500 or total_change>50000:
                    raise ValueError("Zbyt wiele wycięć do eksportu.")
                baked.replace_polygon_components(obj.uid,rings)
            baked_bytes=baked.to_bytes()
            reparsed=GeoMap(baked_bytes)
            if not reparsed.checksum_valid or reparsed.declared_lines!=len(reparsed.lines):
                raise ValueError("Niepoprawna suma kontrolna wynikowego MAP.")
            for uid,expected in expectations.items():
                observed=geometry_of(reparsed.by_id[uid])
                if expected.symmetric_difference(observed).area>max(
                        .002,expected.area*1e-5):
                    raise ValueError("Wycięcie zmieniło geometrię przy zapisie MAP.")
            for obj in base.objects:
                if obj.uid not in expectations and obj.uid and counts[obj.uid]==1:
                    old=base.by_id[obj.uid]
                    new=reparsed.by_id.get(obj.uid)
                    if (new is None or base.lines[old.start:old.end]!=
                            reparsed.lines[new.start:new.end]):
                        raise ValueError("Nieoczekiwana zmiana innego obiektu MAP.")
            metadata={
                "format":"geostudio-topology-v2",
                "sha256":sha256(baked_bytes).hexdigest(),
                "baseSha256":sha256(base_bytes).hexdigest(),
                "uids":ordered,
                "originalP":original_p,
            }
            companion=json.dumps(metadata,ensure_ascii=False,
                                 separators=(",",":")).encode("utf-8")
            if len(companion)>MAX_STYLES_BYTES:
                raise ValueError("Przekroczono limit 2 MB pliku odwracalności.")
            name=_display_name(self._doc.filename)
            return name[:-4]+"_GeoStudio2_wyciecia.MAP",baked_bytes,companion

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
            "hasReversibleMasks": bool(self._overlay_uids()),
        }

    def select_by_attributes(self, *, code: str = "", a1: str = "",
                             a2: str = "", match: str = "exact") -> dict:
        """Select full-map object IDs from source attributes, independent of viewport.

        Search has no side effects on GEO-MAP bytes, geometry or History.
        Explicitly refuse oversized results instead of silently omitting
        hundreds of matches, which could make bulk edits unsafe later.
        """
        if any(not isinstance(value, str) or len(value) > 160
               for value in (code, a1, a2, match)):
            raise ValueError("Nieprawidłowy filtr zaznaczania.")
        code, a1, a2 = code.strip(), a1.strip(), a2.strip()
        if not (code or a1 or a2):
            raise ValueError("Podaj kod lub przynajmniej jeden atrybut A1/A2.")
        if code and (not code.isascii() or not code.isdigit() or len(code) > 8):
            raise ValueError("Kod musi składać się z cyfr.")
        if match not in {"exact", "contains"}:
            raise ValueError("Nieobsługiwany sposób dopasowania.")
        norm1, norm2 = a1.casefold(), a2.casefold()
        with self._lock:
            if self._doc is None:
                raise ValueError("Najpierw otwórz mapę MAP.")
            hits = []
            for entry in self._entries:
                obj = entry.obj
                if code and obj.code != code:
                    continue
                values = obj.fields
                if a1:
                    actual = str(values.get("A1", "")).strip().casefold()
                    if (norm1 != actual if match == "exact" else norm1 not in actual):
                        continue
                if a2:
                    actual = str(values.get("A2", "")).strip().casefold()
                    if (norm2 != actual if match == "exact" else norm2 not in actual):
                        continue
                hits.append(entry.fid)
                if len(hits) > MAX_SELECTED_FEATURES:
                    raise ValueError(
                        "Wynik zawiera ponad 50 000 obiektów. Zawęź kryteria A1/A2.")
            return {
                "ids": hits, "count": len(hits),
                "revision": self._revision, "documentToken": self._document_token,
                "criteria": {"code": code, "A1": a1, "A2": a2, "match": match},
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

    def _bulk_edit_plan(self, ids: list[str], changes: dict, *,
                        document_token: str, revision: int) -> dict:
        """Preflight the entire selection before mutating any GEO-MAP bytes."""
        if self._doc is None or self._history is None:
            raise ValueError("Najpierw otwórz mapę GEO-MAP.")
        if (document_token != self._document_token or
                type(revision) is not int or revision != self._revision):
            raise RuntimeError("Mapa lub jej wersja uległy zmianie. Ponów podgląd.")
        if (not isinstance(ids, list) or not ids or
                len(ids) > MAX_BULK_EDIT_OBJECTS or
                any(not isinstance(fid, str) or len(fid) > 20 for fid in ids) or
                len(set(ids)) != len(ids)):
            raise ValueError(
                "Zaznacz od 1 do 5 000 unikalnych obiektów do edycji.")
        if (not isinstance(changes, dict) or not changes or
                set(changes) - {"A1", "A2"}):
            raise ValueError("Edycja zbiorowa obsługuje tylko wybrane pola A1/A2.")
        for field, value in changes.items():
            if (not isinstance(value, str) or len(value) > 512 or
                    any(ch in value for ch in "\r\n]")):
                raise ValueError(f"Nieprawidłowa nowa wartość pola {field}.")
            try:
                encoded = value.encode("cp1250", errors="strict")
            except UnicodeEncodeError as exc:
                raise ValueError(
                    f"Pole {field} zawiera znak spoza kodowania CP1250.") from exc
            if len(encoded) > 512:
                raise ValueError(f"Wartość pola {field} przekracza 512 bajtów.")

        edits: dict[tuple[str, str], str] = {}
        skipped: Counter = Counter()
        unchanged: Counter = Counter()
        code_counts: Counter = Counter()
        samples: list[dict] = []
        unique_ids: set[str] = set()
        for fid in ids:
            entry = self._lookup.get(fid)
            if entry is None:
                raise LookupError("Zaznaczenie zawiera nieistniejący obiekt.")
            obj = entry.obj
            if (not obj.uid or self._uid_counts.get(obj.uid) != 1 or
                    self._doc.by_id.get(obj.uid) is not obj or
                    obj.uid in unique_ids):
                raise ValueError(
                    "Zaznaczenie zawiera obiekt bez jednoznacznego :ID. "
                    "Przerwano całą operację.")
            unique_ids.add(obj.uid)
            field_changes = {}
            for field, value in changes.items():
                if field not in obj.fields:
                    skipped[field] += 1
                    continue
                old = obj.fields[field]
                if old == value:
                    unchanged[field] += 1
                    continue
                edits[(obj.uid, field)] = value
                field_changes[field] = {"before": old, "after": value}
            if field_changes:
                code_counts[obj.code] += 1
                if len(samples) < 12:
                    samples.append({
                        "id": fid, "uid": obj.uid, "code": obj.code,
                        "fields": field_changes,
                    })

        # Bind the preview to the exact selected objects, requested values,
        # document token and version; a stale browser cannot apply another plan.
        payload = {"ids": sorted(ids), "changes": changes,
                   "documentToken": document_token, "revision": revision}
        preview_key = sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        return {
            "edits": edits, "selectedIds": list(ids),
            "report": {
                "selected": len(ids), "changedObjects": sum(code_counts.values()),
                "changedFields": len(edits), "missingFields": dict(skipped),
                "alreadyEqualFields": dict(unchanged),
                "codes": dict(sorted(code_counts.items())),
                "samples": samples, "previewKey": preview_key,
                "canApply": bool(edits),
                **self._editing_status(),
            },
        }

    def preview_bulk_fields(self, ids: list[str], changes: dict, *,
                            document_token: str, revision: int) -> dict:
        with self._lock:
            report = self._bulk_edit_plan(
                ids, changes, document_token=document_token,
                revision=revision)["report"]
            # A calculated key alone does not authorize a write: the server
            # must have really issued this preview for the current map.
            self._bulk_preview_key = report["previewKey"]
            return report

    def apply_bulk_fields(self, ids: list[str], changes: dict, *,
                          document_token: str, revision: int,
                          preview_key: str) -> dict:
        with self._lock:
            plan = self._bulk_edit_plan(
                ids, changes, document_token=document_token,
                revision=revision)
            report = plan["report"]
            if (not isinstance(preview_key, str) or
                    preview_key != report["previewKey"] or
                    preview_key != self._bulk_preview_key):
                raise RuntimeError(
                    "Podgląd zmian wygasł. Sprawdź zaznaczenie i wykonaj podgląd ponownie.")
            if not report["canApply"]:
                self._bulk_preview_key = ""
                return {**self._editing_status(), "changed": False,
                        "changedObjects": 0, "changedFields": 0}
            edited_uids = {uid for uid, _ in plan["edits"]}
            untouched = sha256()
            # Fingerprint every NON-TARGET object, including same-code peers.
            # If any such record changes, History rolls back the transaction.
            for obj in self._doc.objects:
                if obj.uid not in edited_uids:
                    for line in self._doc.lines[obj.start:obj.end]:
                        untouched.update(line)
            before = untouched.digest()
            with self._history.begin(
                "Zbiorowa edycja A1/A2 ("+str(report["changedObjects"])+")",
                selection_before=tuple(edited_uids),
            ):
                self._doc.bulk_update_fields(plan["edits"])
                after_hash = sha256()
                for obj in self._doc.objects:
                    if obj.uid not in edited_uids:
                        for line in self._doc.lines[obj.start:obj.end]:
                            after_hash.update(line)
                if after_hash.digest() != before:
                    raise ValueError(
                        "Wykryto zmianę poza zaznaczeniem. Cofnięto całą edycję.")
            self._reindex(self._doc, self._doc.filename)
            self._revision += 1
            self._bulk_preview_key = ""
            return {
                **self._editing_status(), "changed": True,
                "selected": report["selected"],
                "changedObjects": report["changedObjects"],
                "changedFields": report["changedFields"],
                "missingFields": report["missingFields"],
                "affected": plan["selectedIds"],
            }

    @staticmethod
    def _point_touches_boundary(point, polygon, tolerance: float = 0.0015) -> bool:
        """Recognize shared corners AND T-junctions with no matching P record."""
        for a, b in zip(polygon.points, polygon.points[1:]):
            # A P 0 separator may terminate a distinct component.
            if a.point_type == 0:
                continue
            x, y = closest_point_on_edge(
                point.x, point.y, a.x, a.y, b.x, b.y)
            if hypot(x - point.x, y - point.y) <= tolerance:
                return True
        return False

    def _move_topology_conflicts(self, moving, dx, dy):
        """Compare old shared borders and new positive-area overlaps."""
        selected={obj.uid for obj in moving}
        codes={obj.code for obj in moving}
        conflicts=[]
        overlaps=[]
        for obj in moving:
            if len(obj.display_parts)>1:
                continue  # compound rings are translated intact; P0 has no synthetic connector
            old=ring_of(obj)
            new=ring_of(obj,dx,dy)
            # Spatial-index broad phase: no all-to-all scan over an entire MAP.
            box=(min(x for x,y in old),min(y for x,y in old),
                 max(x for x,y in old),max(y for x,y in old))
            center=((box[0]+box[2])/2,(box[1]+box[3])/2)
            radius=hypot(box[2]-box[0],box[3]-box[1])/2+.003
            nearby={}
            for cx,cy in (center,(center[0]+dx,center[1]+dy)):
                for candidate in self._index.nearby(cx,cy,radius):
                    if (candidate.uid not in selected and candidate.is_closed
                            and candidate.code==obj.code):
                        nearby[id(candidate)]=candidate
            for neighbor in nearby.values():
                fixed=ring_of(neighbor)
                # Cheap AABB screening avoids costly edge comparisons.
                def nearby(a,b,padding=0.0):
                    return (min(x for x,y in a)<=max(x for x,y in b)+padding and
                            max(x for x,y in a)>=min(x for x,y in b)-padding and
                            min(y for x,y in a)<=max(y for x,y in b)+padding and
                            max(y for x,y in a)>=min(y for x,y in b)-padding)
                if (len(conflicts)<12 and nearby(old,fixed,.002)
                        and rings_contact(old,fixed)
                        and not rings_overlap(old,fixed)):
                    conflicts.append({"movingUid":obj.uid,
                                      "stationaryUid":neighbor.uid,
                                      "code":obj.code})
                if (len(overlaps)<12 and nearby(new,fixed)
                        and rings_overlap(new,fixed)):
                    overlaps.append({"movingUid":obj.uid,
                                     "stationaryUid":neighbor.uid,
                                     "code":obj.code})
        return conflicts,overlaps

    def _move_polygon_plan(self, ids: list[str], dx: float, dy: float, *,
                           allow_detach: bool, document_token: str,
                           revision: int, snap_distance: float = 0) -> dict:
        """Validate every selected polygon and preview the exact coordinate shift.

        dx = native X (northing), dy = native Y (easting), in map units.
        """
        if self._doc is None or self._history is None:
            raise ValueError("Najpierw otwórz mapę GEO-MAP.")
        if (document_token != self._document_token or
                type(revision) is not int or revision != self._revision):
            raise RuntimeError("Mapa została zmieniona. Sprawdź przesunięcie ponownie.")
        if (not isinstance(ids, list) or not ids or
                len(ids) > MAX_BULK_EDIT_OBJECTS or
                any(not isinstance(fid, str) or len(fid) > 20 for fid in ids) or
                len(set(ids)) != len(ids)):
            raise ValueError("Wybierz od 1 do 5 000 unikalnych obiektów.")
        if (type(dx) not in (int, float) or type(dy) not in (int, float) or
                any(not isfinite(z) or abs(z) > 100000 for z in (dx, dy)) or
                type(allow_detach) is not bool or
                type(snap_distance) not in (int, float) or
                not isfinite(snap_distance) or not 0 <= snap_distance <= 2):
            raise ValueError("Nieprawidłowe przesunięcie X/Y albo opcja topologii.")
        dx, dy = round(dx, 3), round(dy, 3)
        changes: dict[str, dict[int, tuple[float, float]]] = {}
        moving = []
        samples: list[dict] = []
        codes: Counter = Counter()
        vertex_count = 0
        for fid in ids:
            entry = self._lookup.get(fid)
            if entry is None:
                raise LookupError("Zaznaczenie zawiera nieistniejący obiekt.")
            obj = entry.obj
            if (not obj.uid or self._uid_counts.get(obj.uid) != 1 or
                    self._doc.by_id.get(obj.uid) is not obj):
                raise ValueError("Obiekt bez jednoznacznego :ID. Przerwano przesuwanie.")
            if not obj.is_closed or len(obj.points) < 4:
                raise ValueError(
                    "Zaznaczenie zawiera linię lub punkt. Przesuwać można "
                    "tylko zamknięte poligony (kod " + obj.code + ").")
            vertex_count += len(obj.points)
            if vertex_count > 100000:
                raise ValueError("Zaznaczenie przekracza limit 100 000 węzłów.")
            moving.append(obj)
            codes[obj.code] += 1
        requested_dx, requested_dy = dx, dy
        snap_applied = None
        if snap_distance and (dx or dy):
            selected_uids={o.uid for o in moving}
            near_fixed={}
            for obj in moving:
                if len(obj.display_parts)>1:
                    continue  # magnetic preview for multipart is handled by the Canvas
                r=ring_of(obj)
                a,b=min(x for x,y in r),min(y for x,y in r)
                c,d=max(x for x,y in r),max(y for x,y in r)
                center=((a+c)/2+dx,(b+d)/2+dy)
                radius=hypot(c-a,d-b)/2+snap_distance+.002
                for item in self._index.nearby(*center,radius):
                    if (item.uid not in selected_uids and item.is_closed
                            and item.code==obj.code):
                        near_fixed[id(item)]=item
            fixed=list(near_fixed.values())
            # Large batch moves still work: only interactive small selections
            # request magnetic edge snapping, never all-to-all 100k vertices.
            if sum(len(obj.points) for obj in moving)>3000:
                fixed=[]
            nx,ny,distance=nearest_boundary_snap(
                moving, fixed, dx, dy, snap_distance)
            if distance is not None:
                dx,dy=nx,ny
                snap_applied={"distance":round(distance,3)}
        for obj in moving:
            shifted={}
            for index,point in enumerate(
                    obj.points if len(obj.display_parts)>1 else obj.points[:-1]):
                x,y=round(point.x+dx,3),round(point.y+dy,3)
                if not (-1e9<x<1e9 and -1e9<y<1e9):
                    raise ValueError("Przesunięcie przekracza zakres współrzędnych.")
                shifted[index]=(x,y)
            changes[obj.uid]=shifted
            if len(samples)<10:
                first=obj.points[0]
                samples.append({"uid":obj.uid,"code":obj.code,
                    "before":{"x":first.x,"y":first.y},
                    "after":{"x":shifted[0][0],"y":shifted[0][1]}})
        conflicts, overlaps = (self._move_topology_conflicts(moving,dx,dy)
                               if dx or dy else ([],[]))
        topology_blocked = bool(conflicts) and not allow_detach
        overlap_blocked = False  # cutouts are non-destructive in GeoStudio 2.0
        payload = {"ids": sorted(ids), "dx": dx, "dy": dy,
                   "allowDetach": allow_detach, "snapDistance": snap_distance,
                   "documentToken": document_token,
                   "revision": revision}
        preview_key = sha256(json.dumps(
            payload, sort_keys=True, ensure_ascii=False,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        return {
            "changes": changes,
            "selectedUids": {obj.uid for obj in moving},
            "report": {
                "selected": len(ids), "vertexCount": vertex_count,
                "codes": dict(sorted(codes.items())),
                "delta": {"x": dx, "y": dy},
                "requestedDelta": {"x": requested_dx, "y": requested_dy},
                "snapApplied": snap_applied,
                "overlapConflicts": overlaps,
                "overlapBlocked": overlap_blocked,
                "reversibleCutout": bool(overlaps),
                "samples": samples,
                "topologyConflicts": conflicts,
                "topologyBlocked": topology_blocked,
                "allowDetach": allow_detach,
                "canApply": bool(dx or dy) and not topology_blocked and not overlap_blocked,
                "previewKey": preview_key,
                **self._editing_status(),
            },
        }

    def preview_move_polygons(self, ids: list[str], dx: float, dy: float, *,
                              allow_detach: bool, document_token: str,
                              revision: int, snap_distance: float = 0) -> dict:
        with self._lock:
            report = self._move_polygon_plan(
                ids, dx, dy, allow_detach=allow_detach,
                document_token=document_token, revision=revision,
                snap_distance=snap_distance)["report"]
            self._move_preview_key = report["previewKey"]
            return report

    def apply_move_polygons(self, ids: list[str], dx: float, dy: float, *,
                            allow_detach: bool, preview_key: str,
                            document_token: str, revision: int,
                            snap_distance: float = 0) -> dict:
        with self._lock:
            plan = self._move_polygon_plan(
                ids, dx, dy, allow_detach=allow_detach,
                document_token=document_token, revision=revision,
                snap_distance=snap_distance)
            report = plan["report"]
            if (not isinstance(preview_key, str) or
                    preview_key != report["previewKey"] or
                    preview_key != self._move_preview_key):
                raise RuntimeError("Podgląd wygasł. Ponownie sprawdź przesunięcie.")
            if report["topologyBlocked"]:
                raise ValueError(
                    "Zaznaczenie ma wspólną granicę z nieruchomym "
                    "poligonem tego samego kodu. Dodaj sąsiada do zaznaczenia "
                    "lub świadomie zezwól na rozłączenie granicy.")
            if not report["canApply"]:
                self._move_preview_key = ""
                return {**self._editing_status(), "changed": False, "affected": []}

            # Fingerprint raw records of every stationary object, independent
            # of its code; this also protects overlapping different-code data.
            h = sha256()
            for obj in self._doc.objects:
                if obj.uid not in plan["selectedUids"]:
                    for line in self._doc.lines[obj.start:obj.end]:
                        h.update(line)
            before = h.digest()
            with self._history.begin(
                "Przesunięcie " + str(report["selected"]) + " poligonów",
                selection_before=tuple(plan["selectedUids"]),
            ):
                self._doc.move_polygon_vertices(plan["changes"])
                self._raise_to_top([o.uid for o in self._doc.objects
                                    if o.uid in plan["selectedUids"]])
                check = sha256()
                for obj in self._doc.objects:
                    if obj.uid not in plan["selectedUids"]:
                        for line in self._doc.lines[obj.start:obj.end]:
                            check.update(line)
                if check.digest() != before:
                    raise ValueError(
                        "Zmiana poza zaznaczeniem — cofnięto całą operację.")
            self._reindex(self._doc, self._doc.filename)
            self._revision += 1
            self._move_preview_key = ""
            self._bulk_preview_key = ""
            return {**self._editing_status(), "changed": True,
                    "affected": list(ids), "movedObjects": report["selected"],
                    "movedVertices": report["vertexCount"],
                    "delta": report["delta"],
                    "snapApplied": report["snapApplied"],
                    "topologyDetached": bool(report["topologyConflicts"])}

    def _object_operation_plan(self, payload: dict, *, document_token: str,
                               revision: int) -> dict:
        """Preflight copy/delete/create against the exact current MAP revision."""
        if self._doc is None or self._history is None:
            raise ValueError("Najpierw otwórz mapę.")
        if (document_token != self._document_token or
                type(revision) is not int or revision != self._revision):
            raise RuntimeError("Mapa zmieniła się. Otwórz podgląd ponownie.")
        if not isinstance(payload, dict):
            raise ValueError("Nieprawidłowe dane operacji.")
        action=payload.get("action")
        if action not in {"copy","delete","create"}:
            raise ValueError("Nieznany rodzaj operacji na poligonach.")
        allowed_keys={
            "copy":{"action","ids","dx","dy"},
            "delete":{"action","ids"},
            "create":{"action","code","points","fields"},
        }[action]
        if set(payload)-allowed_keys:
            raise ValueError("Nieznane pola polecenia.")
        selected=[]
        code_counts=Counter()
        coordinates=[]
        if action in {"copy","delete"}:
            ids=payload.get("ids")
            if (not isinstance(ids,list) or not ids or
                    len(ids)>(500 if action=="copy" else MAX_BULK_EDIT_OBJECTS) or
                    len(set(str(i) for i in ids))!=len(ids)):
                raise ValueError("Nieprawidłowe lub zbyt duże zaznaczenie.")
            for fid in ids:
                if not isinstance(fid,str):
                    raise ValueError("ID musi być tekstem.")
                entry=self._lookup.get(fid)
                if entry is None:
                    raise LookupError("Zaznaczenie zawiera nieistniejący obiekt.")
                obj=entry.obj
                if (not obj.uid or self._uid_counts.get(obj.uid)!=1 or
                        self._doc.by_id.get(obj.uid) is not obj):
                    raise ValueError("Brak unikatowego identyfikatora :ID.")
                if action=="copy" and (not obj.is_closed or len(obj.points)<4):
                    raise ValueError("Kopiowanie dotyczy tylko poligonów.")
                selected.append(obj)
                code_counts[obj.code]+=1
        if action=="delete" and sum(bool(o.points) for o in selected)>=sum(
                bool(o.points) for o in self._doc.objects):
            raise ValueError("Nie można usunąć wszystkich obiektów mapy.")
        if action=="copy":
            dx,dy=payload.get("dx"),payload.get("dy")
            if (type(dx) not in (int,float) or type(dy) not in (int,float) or
                    not isfinite(dx) or not isfinite(dy) or
                    abs(dx)>100000 or abs(dy)>100000):
                raise ValueError("Nieprawidłowe przesunięcie kopii.")
            dx,dy=round(dx,3),round(dy,3)
            if dx==0 and dy==0:
                raise ValueError("Kopia musi mieć inne położenie niż oryginał.")
            if sum(len(obj.points) for obj in selected)>50000:
                raise ValueError("Zbyt dużo węzłów do skopiowania.")
            # Overlapping copies are allowed: the foreground mask is derived
            # from the original intact polygons. The copy gets its own :ID.
            coordinates=[{"uid":obj.uid,"code":obj.code} for obj in selected[:10]]
        elif action=="create":
            code=payload.get("code")
            if code not in {"5216","5220","5230","5310"}:
                raise ValueError("Wybierz kod poligonu: 5216, 5220, 5230 lub 5310.")
            coords=payload.get("points")
            if not isinstance(coords,list) or not 3<=len(coords)<=500:
                raise ValueError("Poligon wymaga 3–500 punktów.")
            for point in coords:
                if (not isinstance(point,list) or len(point)!=2 or
                        any(type(v) not in (int,float) or
                            not isfinite(v) or abs(v)>=1e9 for v in point)):
                    raise ValueError("Nieprawidłowe współrzędne poligonu.")
                coordinates.append((round(point[0],3),round(point[1],3)))
            if coordinates[0]==coordinates[-1]:
                coordinates.pop()
            if len(coordinates)<3 or not polygon_is_valid(coordinates):
                raise ValueError("Poligon ma niepoprawny obrys lub za małe pole.")
            fields=payload.get("fields")
            if not isinstance(fields,dict) or set(fields)-{"A1","A2"}:
                raise ValueError("Atrybuty nowego poligonu mogą zawierać A1/A2.")
            for value in fields.values():
                if not isinstance(value,str) or any(c in value for c in "\r\n]"):
                    raise ValueError("Nieprawidłowa wartość A1 lub A2.")
                try:
                    if len(value.encode("cp1250"))>512:
                        raise ValueError("Atrybut przekracza 512 bajtów.")
                except UnicodeEncodeError as exc:
                    raise ValueError("Atrybut musi mieć kodowanie CP1250.") from exc
            xs=[p[0] for p in coordinates]
            ys=[p[1] for p in coordinates]
            center=((min(xs)+max(xs))/2,(min(ys)+max(ys))/2)
            radius=hypot(max(xs)-min(xs),max(ys)-min(ys))/2+.002
            for other in self._index.nearby(*center,radius):
                if other.is_closed and other.code==code and rings_overlap(
                        coordinates,ring_of(other)):
                    raise ValueError(
                        "Nowy poligon nakłada się na istniejący poligon tego samego kodu.")
            code_counts[code]=1
        canonical={"action":action,"payload":payload,
                   "documentToken":document_token,"revision":revision}
        preview_key=sha256(json.dumps(
            canonical,sort_keys=True,ensure_ascii=False,
            separators=(",",":")).encode("utf-8")).hexdigest()
        return {"action":action,"selected":selected,"coords":coordinates,
                "report":{"action":action,"selected":len(selected),
                          "codes":dict(sorted(code_counts.items())),
                          "vertexCount":(len(coordinates) if action=="create"
                            else sum(len(o.points) for o in selected)),
                          "previewKey":preview_key,"canApply":True,
                          **self._editing_status()}}

    def preview_object_operation(self, payload: dict, *,
                                 document_token: str, revision: int) -> dict:
        with self._lock:
            plan=self._object_operation_plan(payload,
                document_token=document_token,revision=revision)
            self._objects_preview_key=plan["report"]["previewKey"]
            return plan["report"]

    def apply_object_operation(self, payload: dict, *, preview_key: str,
                               document_token: str, revision: int) -> dict:
        with self._lock:
            plan=self._object_operation_plan(payload,
                document_token=document_token,revision=revision)
            report=plan["report"]
            if (not isinstance(preview_key,str) or
                    preview_key!=report["previewKey"] or
                    preview_key!=self._objects_preview_key):
                raise RuntimeError("Przed zatwierdzeniem wykonaj świeży podgląd.")
            action=plan["action"]
            selected=plan["selected"]
            before=b"".join(self._doc.lines)
            created=[]
            with self._history.begin(
                {"copy":"Kopiuj poligony","delete":"Usuń poligony",
                 "create":"Nowy poligon"}[action],
                selection_before=tuple(o.uid for o in selected),
            ):
                if action=="delete":
                    self._doc.delete_objects([o.uid for o in selected])
                    old=self._overlay_uids()
                    remaining=[uid for uid in old if uid not in
                               {o.uid for o in selected}]
                    self._styles[TOPOLOGY_STACK_KEY]={"uids":remaining}
                elif action=="copy":
                    created=self._doc.duplicate_polygons(
                        [o.uid for o in selected],
                        round(payload["dx"],3),round(payload["dy"],3))
                    self._raise_to_top(created)
                else:
                    created=[self._doc.append_polygon(
                        plan["coords"],code=payload["code"],
                        fields=payload["fields"])]
                    self._raise_to_top(created)
                # For append/copy, all original MAP records must survive.
                if action!="delete":
                    if not b"".join(self._doc.lines).startswith(
                            before):
                        raise ValueError(
                            "Wykryto zmianę oryginalnego rekordu. Cofnięto operację.")
            self._reindex(self._doc,self._doc.filename)
            self._revision+=1
            self._objects_preview_key=""
            self._move_preview_key=""
            self._bulk_preview_key=""
            return {**self._editing_status(),"changed":True,"action":action,
                    "affected":payload.get("ids",[]),
                    "createdUids":created,
                    "createdIds":[self._object_id[id(self._doc.by_id[uid])]
                                  for uid in created]}

    def _geometry_plan(self, operation: dict, *,
                       document_token: str, revision: int) -> dict:
        """Strict preflight for explicit native GEO-MAP geometry operations."""
        if (self._doc is None or self._history is None):
            raise ValueError("Najpierw otwórz mapę.")
        if (document_token!=self._document_token or
                type(revision) is not int or revision!=self._revision):
            raise RuntimeError("Mapa została zmieniona. Sprawdź ponownie.")
        if not isinstance(operation,dict):
            raise ValueError("Nieprawidłowe parametry geometrii.")
        action=operation.get("action")
        fields={
            "repair":{"action","ids"},
            "merge":{"action","ids"},
            "split":{"action","ids","points"},
            "create_line":{"action","code","points","fields"},
            "edit_line":{"action","ids","points"},
        }
        if action not in fields or set(operation)-fields.get(action,set()):
            raise ValueError("Nieznane lub nieobsługiwane polecenie geometrii.")
        selected=[]
        if action!="create_line":
            ids=operation.get("ids")
            if (not isinstance(ids,list) or not ids or
                    len(ids)>100 or len(ids)!=len(set(str(x) for x in ids))):
                raise ValueError("Wymagane 1–100 różnych obiektów.")
            if action in {"split","edit_line"} and len(ids)!=1:
                raise ValueError("Ta operacja wymaga dokładnie jednego obiektu.")
            if action=="merge" and len(ids)<2:
                raise ValueError("Scalenie wymaga minimum dwóch obiektów.")
            for fid in ids:
                if not isinstance(fid,str) or fid not in self._lookup:
                    raise LookupError("Nieznany identyfikator obiektu.")
                obj=self._lookup[fid].obj
                if (not obj.uid or self._uid_counts.get(obj.uid)!=1 or
                        self._doc.by_id.get(obj.uid) is not obj):
                    raise ValueError("Obiekt ma niejednoznaczne :ID.")
                selected.append(obj)
        geometry=None
        coordinates=[]
        details={}
        if action in {"repair","merge","split"}:
            for obj in selected:
                if not obj.is_closed or (action!="merge" and
                         any(p.point_type!=1 for p in obj.points)):
                    raise ValueError("Wybierz zamknięte poligony; podział i Pole + wymagają prostego obrysu.")
        if action=="repair":
            repairs=[obj.uid for obj in selected if self._doc.signed_area(
                [(p.x,p.y) for p in obj.points[:-1]])<0]
            details={"repairs":repairs}
        elif action=="merge":
            codes={obj.code for obj in selected}
            attrs={(obj.fields.get("A1",""),obj.fields.get("A2",""))
                   for obj in selected}
            if len(codes)!=1 or len(attrs)!=1:
                raise ValueError("Scalaj tylko ten sam kod i zgodne wartości A1/A2.")
            geometry=merge_multipart([geometry_of(o) for o in selected])
            rings=rings_from_shape(geometry)
            details={"beforeArea":round(sum(geometry_of(o).area
                                               for o in selected),3),
                     "afterArea":round(geometry.area,3),
                     "components":(len(geometry.geoms)
                         if geometry.geom_type=="MultiPolygon" else 1),
                     "rings":len(rings),
                     "metadataWarning":True}
        elif action=="split":
            points=operation.get("points")
            if not isinstance(points,list) or not 2<=len(points)<=500:
                raise ValueError("Narysuj linię podziału z 2–500 punktów.")
            for point in points:
                if (not isinstance(point,list) or len(point)!=2 or
                        any(type(v) not in (int,float) or
                            not isfinite(v) or abs(v)>1e9 for v in point)):
                    raise ValueError("Nieprawidłowe punkty linii podziału.")
                coordinates.append(tuple(round(v,3) for v in point))
            geometry=split_simple(polygon_of(selected[0]),coordinates)
            details={"parts":len(geometry),
                     "beforeArea":round(polygon_of(selected[0]).area,3),
                     "afterArea":round(sum(abs(self._doc.signed_area(part))
                                           for part in geometry),3),
                     "metadataWarning":True}
        if action in {"create_line","edit_line"}:
            points=operation.get("points")
            if not isinstance(points,list) or not 2<=len(points)<=500:
                raise ValueError("Linia wymaga 2–500 punktów.")
            for point in points:
                if (not isinstance(point,list) or len(point)!=2 or
                        any(type(v) not in (int,float) or
                            not isfinite(v) or abs(v)>1e9 for v in point)):
                    raise ValueError("Nieprawidłowy punkt linii.")
                coordinates.append(tuple(round(v,3) for v in point))
            from shapely.geometry import LineString
            polyline=LineString(coordinates)
            if not polyline.is_simple or polyline.length<=0.001:
                raise ValueError("Linia jest zbyt krótka lub przecina samą siebie.")
            if action=="edit_line":
                if selected[0].is_closed or selected[0].code not in {
                        "6900","6000","6301","2364","4100"}:
                    raise ValueError("Wybrany obiekt nie jest obsługiwaną linią.")
            else:
                code=operation.get("code")
                if code not in {"6900","6000","6301","2364"}:
                    raise ValueError("Wybierz kod linii 6900, 6000, 6301 lub 2364.")
                attrs=operation.get("fields")
                if not isinstance(attrs,dict) or set(attrs)-{"A1","A2"}:
                    raise ValueError("Linia obsługuje A1/A2.")
                for value in attrs.values():
                    if (not isinstance(value,str) or any(c in value for c in "\r\n]")):
                        raise ValueError("Niedozwolone znaki w atrybucie.")
                    try:
                        if len(value.encode("cp1250"))>512:
                            raise ValueError("Atrybut jest zbyt długi.")
                    except UnicodeEncodeError as e:
                        raise ValueError("Użyj polskich znaków CP1250.") from e
        allowed=(bool(details.get("repairs")) if action=="repair" else True)
        payload={"operation":operation,"documentToken":document_token,
                 "revision":revision}
        key=sha256(json.dumps(payload,sort_keys=True,
                             ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
        return {"action":action,"selected":selected,"coordinates":coordinates,
                "geometry":geometry,
                "report":{"action":action,"canApply":allowed,
                          "previewKey":key,"selected":len(selected),
                          "codes":dict(Counter(o.code for o in selected)),
                          **details,**self._editing_status()}}

    def preview_geometry_operation(self, operation: dict, *,
                                   document_token: str,revision: int) -> dict:
        with self._lock:
            plan=self._geometry_plan(operation,
                                    document_token=document_token,revision=revision)
            self._geometry_preview_key=plan["report"]["previewKey"]
            return plan["report"]

    def apply_geometry_operation(self, operation: dict, *, preview_key: str,
                                 document_token: str, revision: int) -> dict:
        with self._lock:
            plan=self._geometry_plan(operation,
                                    document_token=document_token,revision=revision)
            report=plan["report"]
            if (not report["canApply"] or not isinstance(preview_key,str) or
                    preview_key!=report["previewKey"] or
                    preview_key!=getattr(self,"_geometry_preview_key","")):
                raise RuntimeError("Podgląd jest nieaktualny lub nie ma zmian.")
            action=plan["action"]
            selected=plan["selected"]
            created=[]
            affected={obj.uid for obj in selected}
            with self._history.begin({
                "repair":"Kierunek obrysu i dodatnie pole",
                "merge":"Scalenie poligonów",
                "split":"Podział poligonu",
                "create_line":"Nowa linia",
                "edit_line":"Zmiana linii",
            }[action],selection_before=tuple(affected)):
                if action=="repair":
                    self._doc.normalize_polygon_winding(
                        report["repairs"])
                elif action=="merge":
                    keeper=selected[0].uid
                    self._doc.replace_polygon_components(
                        keeper,rings_from_shape(plan["geometry"]))
                    self._doc.delete_objects(
                        [o.uid for o in selected[1:]])
                    self._styles[TOPOLOGY_STACK_KEY]={
                        "uids":[uid for uid in self._overlay_uids()
                                if uid not in affected or uid==keeper]}
                elif action=="split":
                    original=selected[0].uid
                    pieces=plan["geometry"]
                    if len(pieces)>1:
                        for piece in pieces[1:]:
                            clone=self._doc.duplicate_polygons(
                                [original],0,0)[0]
                            self._doc.replace_simple_geometry(clone,piece)
                            created.append(clone)
                        self._doc.replace_simple_geometry(original,pieces[0])
                elif action=="create_line":
                    created=[self._doc.append_polyline(
                        plan["coordinates"],code=operation["code"],
                        fields=operation["fields"])]
                else:
                    self._doc.replace_simple_geometry(
                        selected[0].uid,plan["coordinates"],closed=False)
            self._reindex(self._doc,self._doc.filename)
            self._revision+=1
            self._geometry_preview_key=""
            self._move_preview_key=""
            self._objects_preview_key=""
            return {**self._editing_status(),"changed":True,
                    "action":action,"affected":operation.get("ids",[]),
                    "createdUids":created,
                    "createdIds":[self._object_id[id(self._doc.by_id[uid])]
                                  for uid in created]}

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

    def _feature(self, entry: _Entry, overlay_objects=()) -> dict:
        obj=entry.obj
        parts=[[[p.y,-p.x] for p in segment]
               for segment in obj.display_parts if segment]
        visible_area=obj.area_m2
        mask_count=0
        if obj.is_closed and overlay_objects:
            order=self._overlay_uids()
            at=order.index(obj.uid) if obj.uid in order else -1
            upper_ids=set(order[at+1:])
            # Same code only. Preserve unrelated codes even when geometries
            # intersect; overlays never modify the actual MAP records.
            upper=[other for other in overlay_objects
                   if other.uid in upper_ids and other.uid!=obj.uid
                   and other.code==obj.code]
            if upper:
                ax0=min(p.x for p in obj.points)
                ay0=min(p.y for p in obj.points)
                ax1=max(p.x for p in obj.points)
                ay1=max(p.y for p in obj.points)
                upper=[other for other in upper
                       if min(p.x for p in other.points)<ax1
                       and max(p.x for p in other.points)>ax0
                       and min(p.y for p in other.points)<ay1
                       and max(p.y for p in other.points)>ay0]
                if upper:
                    try:
                        base=geometry_of(obj)
                        shapes=[geometry_of(other) for other in upper]
                        result=visible_difference(base,shapes)
                        parts=shape_parts(result)
                        visible_area=round(result.area,3)
                        mask_count=len(shapes)
                    except ValueError:
                        # Multi-contour GEO-MAP geometry needs a native parser.
                        # Preserve the original rather than risk data loss.
                        pass
        return {"id":entry.fid,"code":obj.code,"layer":entry.layer,
                "grade":entry.grade,"bbox":entry.bbox,"closed":obj.is_closed,
                "geometry":parts,"style":self._style(entry),
                "labels":self._labels(entry) if parts else [],
                "baseAreaM2":obj.area_m2,
                "visibleAreaM2":visible_area,
                "reversibleCutout":mask_count>0}

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
            stack=self._overlay_uids()
            overlay=[self._doc.by_id[uid] for uid in stack
                     if uid in self._doc.by_id
                     and self._uid_counts.get(uid)==1
                     and self._doc.by_id[uid].is_closed]
            return {
                "features":[self._feature(entry,overlay) for entry in visible[:limit]],
                "limited":total>limit,"total":total,
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
