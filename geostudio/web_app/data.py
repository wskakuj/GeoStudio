"""Read-only bridge from the verified GEO-MAP parser to browser coordinates.

GEO-MAP stores northing X and easting Y. The browser uses (east, -north)
to keep the same orientation as the classic geodetic Qt canvas.

No calls to GeoMap.update_field, save_as, or any editing operation occur here.
No user-uploaded map is written to disk.
"""
from __future__ import annotations

from copy import deepcopy
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

from .sheet_marks import (KINDS as SHEET_SIGNS, NUMBER as SHEET_NUMBER,
                          ROTATABLE as SHEET_ROTATABLE, primitives as sheet_primitives)
from geostudio.geomap import GeoMap
from geostudio.forest_classes import forest_class_value
from geostudio.map_layout import detect_source_compilation_scale, validated_compilation_scale, DEFAULT_SCALE
from geostudio.geometry_index import GeometryIndex
from geostudio.history import History
from geostudio.topology_edit import linked_vertex_plan
from geostudio.web_app.topology_safety import rings_overlap, rings_contact, ring_of, nearest_boundary_snap
from geostudio.web_app.geometry_6a import (polygon_of, geometry_of, visible_difference,
    shape_parts, split_simple, merge_simple, merge_multipart, rings_from_shape,
    creation_overlap)
from geostudio.interactions import find_snap, closest_point_on_edge, polygon_is_valid
from geostudio.library_render import (native_fill_color,parse_cdf,
    cdf_for_object,parse_lay_pen_styles,lay_for_code,parse_sym_primitives,
    parse_sym_line_patterns,object_sym_line_pattern,simple_point_segments,
    simple_point_circles)

MAX_MAP_BYTES = 512 * 1024 * 1024
MAX_STYLES_BYTES = 2 * 1024 * 1024
MAX_RENDER_FEATURES = 100000
MAX_SELECTED_FEATURES = 50000
MAX_BULK_EDIT_OBJECTS = 5000
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
STYLE_FORMAT = "geostudio-visual-v1"
TOPOLOGY_STACK_KEY = "__geostudio_topology_stack_v1__"
CODES = {
    "5214": "Linia obrębu",
    "5216": "Działki",
    "5220": "Użytki",
    "5230": "Użytki",
    "5310": "Budynki",
    "1246": "Graniczniki",
    "6900": "Numery oddziałów · 6900",
    "1431": "Płazowina iglasta · 1431",
    "1432": "Płazowina liściasta · 1432",
    "1461": "Bagno · 1461",
    "2613": "Oznaczenia liniowe · 2613",
    "2364": "Linia energetyczna · 2364",
    "5200": "Zrąb i granice lasów · 5200",
    "4588": "Ścieżki · 4588",
    "5219": "Lasy współwłasnościowe · 5219",
    "5741": "Gazociąg · 5741",
    "6000": "Oprawa / linie",
    "7900": "Oprawa / tekst",
}
LABEL_FIELDS = ("A1", "A2", "A3", "A4", "A5", "A6", "TX", "MP", "KR")


def _inspector_fields(obj):
    if obj.code == "5310" and obj.is_closed:
        fields = dict.fromkeys(("A1", "A2", "A4", "A5", "A6"), "")
        fields.update(obj.fields)
        return fields
    return dict(obj.fields)


def _color(value, fallback):
    return str(value).upper() if isinstance(value, str) and HEX.fullmatch(value) else fallback


def _opacity(value, fallback):
    try:
        return max(0, min(100, int(value)))
    except (ValueError, TypeError):
        return fallback


def _display_name(value: str) -> str:
    return Path(str(value).replace("\\", "/")).name[:160] or "Mapa.MAP"


def _web_forest_class_value(obj) -> str | None:
    """GEO-MAP browser classification: Ls grades from 5220 or 5230 A2/A1.

    Keep the classic Qt scene builder's old classifier unchanged. A2 holds
    the bonitation grade (LsVI), A1 may hold only generic Ls.
    """
    if obj.code not in {"5220", "5230"}:
        return None
    for field in ("A2", "A1"):
        value = re.sub(r"\s+", "", str(obj.fields.get(field, "") or ""))
        if re.fullmatch(r"Ls(?:[IVX]+[a-d]?)?", value, re.IGNORECASE):
            suffix = value[2:]
            roman = re.match(r"[ivx]*", suffix, re.IGNORECASE).group(0)
            return "Ls" + roman.upper() + suffix[len(roman):].lower()
    return None



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
        self._entry_by_objid: dict[int, _Entry] = {}
        self._uid_counts: Counter = Counter()
        self._index: GeometryIndex | None = None
        self._styles: dict[str, dict] = {}
        self._label_positions: dict[str, dict] = {}
        self._source_compilation_scale = DEFAULT_SCALE
        self.map_epsg = None
        self._raster_map_key = ""
        self._loaded_map_sha = ""
        self._carto_cdf={}
        self._carto_lay={}
        self._carto_sym={}
        self._carto_patterns={}
        self._carto_loaded={}
        self._carto_match_cache={}
        self._bounds: list[float] | None = None
        self._meta: dict = {"loaded": False}
        self._history: History | None = None
        self._revision = 0
        self._document_token = ""
        self._bulk_preview_key = ""
        self._replace_preview_key = ""
        self._move_preview_key = ""
        self._objects_preview_key = ""
        self._geometry_preview_key = ""
        self._generated_export = None

    def load_map(self, content: bytes, filename: str, *, epsg=None) -> dict:
        if not content or len(content) > MAX_MAP_BYTES:
            raise ValueError("Plik MAP jest pusty lub przekracza limit 512 MB.")
        name = _display_name(filename)
        if not name.lower().endswith(".map"):
            raise ValueError("Wybierz plik z rozszerzeniem .MAP.")
        doc = GeoMap(content, filename=name)
        if not doc.objects:
            raise ValueError("Brak obiektów GEO-MAP w podanym pliku.")
        if not any(obj.points for obj in doc.objects):
            raise ValueError("Plik nie zawiera geometrii do wyświetlenia.")

        with self._lock:
            self.map_epsg = epsg
            self._generated_export = None
            self._revision = 0
            self._document_token = token_hex(16)
            self._bulk_preview_key = ""
            self._move_preview_key = ""
            self._objects_preview_key = ""
            self._reindex(doc, name)
            self._source_compilation_scale=detect_source_compilation_scale(doc.objects)
            # Appended 5310 records and attribute changes preserve the map identity.
            reference = next((o for o in doc.objects if o.points and str(o.code) != "5310"),
                             next(o for o in doc.objects if o.points))
            anchor = [(p.x, p.y) for p in reference.points[:3]]
            self._raster_map_key = sha256(repr((name.casefold(), reference.code, anchor)).encode()).hexdigest()
            self._loaded_map_sha=sha256(content).hexdigest()
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
        land_use_counts = Counter()
        land_use_labels = {}
        for ix, obj in enumerate(doc.objects):
            if not obj.points:
                continue
            xs = [p.x for p in obj.points]
            ys = [p.y for p in obj.points]
            grade = _web_forest_class_value(obj)
            layer = "Użytki Leśne" if grade else CODES.get(obj.code, "Kod " + obj.code)
            fid = "f" + str(ix)
            bbox = (min(ys), -max(xs), max(ys), -min(xs))
            entries.append(_Entry(fid, obj, layer, grade, bbox))
            layer_counts[layer] += 1
            codes[obj.code] += 1
            if grade:
                forest[grade] += 1
            if layer == "Użytki":
                # In this GEO-MAP workflow, the detailed bonitation
                # class is stored in A2 (e.g. RV, PsIV, RVI).
                # A1 may only carry the general use category.
                # Group spelling variants case-insensitively.
                value = str(obj.fields.get("A2", "") or "").strip()
                key = value.casefold()
                land_use_counts[key] += 1
                land_use_labels.setdefault(key, value or "(bez A2)")
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
            "landUseClasses": [
                {"key": key, "label": land_use_labels[key], "count": amount}
                for key, amount in sorted(land_use_counts.items(),
                                          key=lambda item: item[0])
            ],
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
            self._entry_by_objid = {id(entry.obj): entry for entry in entries}
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

    def _import_baked_metadata(self, metadata: dict, map_bytes: bytes) -> None:
        """Restore original P records from SHA-bound native cutout MAP."""
        expected={"format","sha256","baseSha256","uids","originalP"}
        if (set(metadata)!=expected or
                metadata.get("format")!="geostudio-topology-v2" or
                metadata.get("sha256")!=sha256(map_bytes).hexdigest() or
                not isinstance(metadata.get("uids"),list) or
                not isinstance(metadata.get("originalP"),dict) or
                len(metadata["uids"])>5000 or len(metadata["originalP"])>500):
            raise ValueError("Plik topologii 6B nie pasuje do MAP.")
        from geostudio.geomap import POINT_RE
        with self._lock:
            if self._doc is None:
                raise ValueError("Najpierw wczytaj MAP.")
            if sha256(b"".join(self._doc.lines)).hexdigest()!=metadata["sha256"]:
                raise ValueError("Plik topologii dotyczy innego MAP.")
            document=GeoMap(map_bytes,filename=self._doc.filename)
            if not document.checksum_valid:
                raise ValueError("Nieprawidłowy CHK mapy.")
            counts=Counter(o.uid for o in document.objects if o.uid)
            order=metadata["uids"]
            if (len(set(str(uid) for uid in order))!=len(order) or
                    any(not isinstance(uid,str) or counts[uid]!=1 for uid in order)):
                raise ValueError("Nieprawidłowe identyfikatory w topologii.")
            for uid,saved in metadata["originalP"].items():
                if (not isinstance(uid,str) or counts[uid]!=1 or
                        not isinstance(saved,list) or
                        not 4<=len(saved)<=50000):
                    raise ValueError("Uszkodzony zapis oryginalnego poligonu.")
                obj=document.by_id[uid]
                self._raw_p_records(document,obj)
                positions=[i for i in range(obj.start+1,obj.end)
                           if POINT_RE.match(document.lines[i].rstrip(b'\r\n'))]
                recovered=[]
                for encoded in saved:
                    if not isinstance(encoded,str) or len(encoded)>3000:
                        raise ValueError("Zbyt duży rekord konturu.")
                    try:
                        raw=base64.b64decode(encoded,validate=True)
                    except (ValueError,base64.binascii.Error) as exc:
                        raise ValueError("Błędny zapis Base64 konturu.") from exc
                    if (len(raw)>2000 or
                            not raw.endswith((b'\r\n',b'\n')) or
                            not POINT_RE.match(raw.rstrip(b'\r\n'))):
                        raise ValueError("Niedozwolony rekord P w topologii.")
                    recovered.append(raw)
                document.lines[positions[0]:positions[-1]+1]=recovered
                document._parse()
            restored=document.to_bytes()
            if sha256(restored).hexdigest()!=metadata.get("baseSha256"):
                raise ValueError("Nie udało się bezpiecznie odtworzyć źródłowych konturów.")
            self._reindex(GeoMap(restored,filename=document.filename),
                          document.filename)
            self._styles[TOPOLOGY_STACK_KEY]={"uids":list(order)}
            self._history=History(_WebHistoryTarget(self))
            self._revision=0

    def import_topology_metadata(self, content: bytes, map_bytes: bytes) -> None:
        """Load saved precedence only when companion checksum and UIDs match."""
        if not content or len(content)>MAX_STYLES_BYTES:
            raise ValueError("Za duży plik topologii.")
        obj=json.loads(content)
        if isinstance(obj,dict) and obj.get("format")=="geostudio-topology-v2":
            self._import_baked_metadata(obj,map_bytes)
            return
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

    def import_topology_for_open_map(self, content: bytes) -> dict:
        """Browser-selected reversible MAP companion, never an arbitrary path."""
        with self._lock:
            if self._doc is None or self._history is None:
                raise ValueError("Najpierw wczytaj towarzyszący plik MAP.")
            if self._history.is_dirty:
                raise RuntimeError(
                    "Nie można zaimportować topologii po rozpoczęciu edycji. "
                    "Otwórz ponownie MAP, a potem jego JSON.")
            map_bytes=self._doc.to_bytes()
            self.import_topology_metadata(content,map_bytes)
            return {**self.metadata(),"topologyImported":True}

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

    def _require_edit(self,document_token: str,revision: int) -> None:
        if self._doc is None or self._history is None:
            raise ValueError("Najpierw otwórz mapę.")
        if (document_token!=self._document_token or
                type(revision) is not int or revision!=self._revision):
            raise RuntimeError("Dokument zmienił się podczas edycji.")

    def _visual_user_styles(self) -> dict:
        """Exclude reversible topology; that has its own checksum-bound JSON."""
        return {k:v for k,v in self._styles.items() if k!=TOPOLOGY_STACK_KEY}

    def _current_compilation_scale(self) -> int:
        style=self._styles.get("cartography:compilation_scale")
        value=style.get("denominator") if isinstance(style,dict) else None
        return validated_compilation_scale(
            value,default=self._source_compilation_scale)

    def export_visual_sidecar(self, map_bytes: bytes) -> bytes | None:
        """SHA-bound optional sidecar for independently movable labels."""
        with self._lock:
            styles=self._visual_user_styles()
            if not self._label_positions and not styles:return None
            payload={
                "format":STYLE_FORMAT,
                "sha256":sha256(map_bytes).hexdigest(),
                "objects":styles,
                "labels":self._label_positions
            }
            raw=json.dumps(payload,ensure_ascii=False,
                           separators=(",",":")).encode("utf-8")
            if len(raw)>MAX_STYLES_BYTES:
                raise ValueError("Konfiguracja etykiet przekracza limit 2 MB.")
            return raw

    def move_label(self,fid: str,field: str,x: float,y: float,
                   *,document_token: str,revision: int) -> dict:
        """Undoable label move in native (X,Y); never touch MAP P lines."""
        with self._lock:
            self._require_edit(document_token,revision)
            if field not in LABEL_FIELDS:
                raise ValueError("Niedozwolone pole etykiety.")
            entry=self._lookup.get(fid)
            if entry is None:
                raise LookupError(fid)
            obj=entry.obj
            if not obj.uid or self._uid_counts.get(obj.uid)!=1:
                raise ValueError("Nie można przesunąć etykiety bez unikalnego ID.")
            if not obj.fields.get(field,"").strip():
                raise ValueError("Wybrana etykieta nie ma tekstu.")
            if (type(x) not in (int,float) or type(y) not in (int,float)
                    or not all(isfinite(z) and abs(z)<1e9 for z in (x,y))):
                raise ValueError("Nieprawidłowe współrzędne etykiety.")
            point=[round(x,3),round(y,3)]
            existing=self._label_positions.get(obj.uid,{})
            if existing.get(field)==point:
                return {**self._editing_status(),"changed":False}
            before=self._doc.to_bytes()
            with self._history.begin(
                "Przesunięcie etykiety "+field+" ("+obj.code+")",
                selection_before=(obj.uid,)
            ):
                self._label_positions.setdefault(obj.uid,{})[field]=point
                # Dla 5310 zapisujemy też natywny rekord L, żeby pozycja
                # przetrwała samo zapisanie MAP (bez pliku towarzyszącego).
                if obj.code == "5310" and field in ("A1", "A2"):
                    base = _label_anchor(obj)
                    self._doc.set_label_offset(
                        obj.uid, 2 if field == "A1" else 3,
                        round(point[0] - base[0], 3),
                        round(point[1] - base[1], 3))
            after=self._doc.to_bytes()
            if after!=before:
                # Wolno zmienić wyłącznie rekordy etykiet (L), nigdy geometrię.
                old_lines=before.splitlines(keepends=True)
                new_lines=after.splitlines(keepends=True)
                if len(old_lines)!=len(new_lines):
                    raise ValueError("Naruszono geometrię MAP podczas przesuwania etykiety.")
                for index,(a,b) in enumerate(zip(old_lines,new_lines)):
                    if a==b:
                        continue
                    # Wolno zmienić rekord etykiety oraz nagłówek pliku
                    # (;# ...), który niesie licznik zmian. Geometria nie.
                    if a.startswith(b"L ") or a.startswith(b";#"):
                        continue
                    raise ValueError("Naruszono geometrię MAP podczas przesuwania etykiety.")
            # Przesunięcie napisu na drugą stronę kotwicy zmienia kierunek
            # wysięgnika: 69 (w prawo) <-> 133 (w lewo).
            self._sync_leader_direction(obj, field, point)
            self._revision+=1
            return {**self._editing_status(),"changed":True,
                    "fid":fid,"field":field,"point":point}

    def _label_inside(self, obj, point) -> bool:
        """Czy punkt (północ, wschód) leży w obrysie obiektu."""
        if not obj.is_closed:
            return True
        try:
            from shapely.geometry import Point
            return bool(geometry_of(obj).contains(
                Point(float(point[0]), float(point[1]))))
        except Exception:
            return True

    def _sync_leader_direction(self, obj, field: str, point) -> None:
        """Ustawia bit wysięgnika zgodnie ze stroną, po której stoi napis."""
        from ..geomap import parse_label_record
        slot = 2 if field == "A1" else 3 if field == "A2" else None
        if slot is None or self._doc is None:
            return
        for raw in self._doc.lines[obj.start:obj.end]:
            record = parse_label_record(raw)
            if not record or record["slot"] != slot or not record["leader"]:
                continue
            anchor = record["anchor"]
            if not anchor:
                return
            # Kotwica w pliku jest względna — do porównania dodajemy bazę.
            base = _label_anchor(obj)
            # point = [northing, easting]; kotwica = (northing, easting).
            label_easting = float(point[1])
            anchor_easting = base[1] + float(anchor[1])
            if abs(label_easting - anchor_easting) < 1e-6:
                return
            prefer_left = label_easting < anchor_easting
            if (record["leader"] == "left") == prefer_left:
                return
            self._doc.set_label_leader(obj.uid, slot, True, anchor, prefer_left)
            return

    def auto_layout_5310_labels(self, scope: str = "all", scale: int = 5000,
                                ids=None, *, document_token=None,
                                revision=None) -> dict:
        """Automatycznie układa etykiety A1/A2 dla poligonów 5310.

        Jedna atomowa operacja w historii — Ctrl+Z cofa całe ułożenie.
        """
        with self._lock:
            if self._doc is None:
                raise ValueError("Najpierw otwórz mapę GEO-MAP.")
            self._require_edit(document_token, revision)
            if scope not in ("all", "selected"):
                raise ValueError("Zakres musi być 'all' albo 'selected'.")
            if type(scale) is not int or not 100 <= scale <= 1_000_000:
                raise ValueError("Skala opracowania musi mieć mianownik 100–1000000.")
            from .label_layout import auto_layout_5310_labels as engine
            wanted = set(ids or []) if scope == "selected" else None
            if scope == "selected" and not wanted:
                raise ValueError("Zaznacz poligony 5310, które mają zostać ułożone.")
            prepared = []
            for entry in self._entries:
                obj = entry.obj
                if obj.code != "5310" or not obj.is_closed:
                    continue
                if wanted is not None and entry.fid not in wanted:
                    continue
                try:
                    shape = geometry_of(obj)
                except ValueError:
                    continue
                if shape is None or shape.is_empty:
                    continue
                prepared.append((obj.uid, shape, _label_anchor(obj),
                                 str(obj.fields.get("A1", "") or ""),
                                 str(obj.fields.get("A2", "") or "")))
            if not prepared:
                return {**self._editing_status(), "changed": False,
                        "stats": {"objects": 0, "inside": 0, "leaders": 0}}
            result = engine(prepared, scale=scale)
            if not result["changes"]:
                return {**self._editing_status(), "changed": False,
                        "stats": result["stats"]}
            with self._history.begin(
                    "Ułożenie etykiet A1/A2 (" + str(len(result["changes"])) +
                    " obiektów)",
                    selection_before=tuple(change["uid"]
                                           for change in result["changes"])):
                # Rekordy L piszemy bez ponownego parsowania po każdym wpisie
                # (to było 84 pełne parsowania mapy = kilkanaście sekund).
                for change in result["changes"]:
                    for field, spec in change["labels"].items():
                        slot = 2 if field == "A1" else 3
                        self._doc.set_label_offset(change["uid"], slot,
                                                   spec["dx"], spec["dy"],
                                                   reparse=False)
                        flags = int(spec["flags"])
                        if flags & (64 | 128):
                            self._doc.set_label_leader(
                                change["uid"], slot, True, spec.get("anchor"),
                                prefer_left=bool(flags & 128), reparse=False)
                        else:
                            self._doc.set_label_leader(change["uid"], slot, False,
                                                       reparse=False)
                self._doc._parse()
                # Ręcznie przeciągnięte etykiety (plik towarzyszący) mają
                # pierwszeństwo nad rekordem L — po auto-układaniu je czyścimy,
                # inaczej wynik silnika byłby niewidoczny.
                for change in result["changes"]:
                    self._label_positions.pop(change["uid"], None)
            self._reindex(self._doc, self._doc.filename)
            self._revision += 1
            return {**self._editing_status(), "changed": True,
                    "stats": result["stats"]}

    def reset_label_leaders(self, ids=None, *, document_token=None,
                            revision=None) -> dict:
        """Zeruje wysięgniki: czyści bity 64/128, kotwice i przesunięcia.

        Jedna operacja w historii, więc Ctrl+Z cofa całość. ``ids`` puste
        oznacza całą mapę (wszystkie obiekty z rekordami L).
        """
        with self._lock:
            if self._doc is None:
                raise ValueError("Najpierw otwórz mapę GEO-MAP.")
            self._require_edit(document_token, revision)
            from ..geomap import parse_label_record
            wanted = None
            if ids:
                wanted = set(ids)
            targets = []
            for entry in self._entries:
                if entry.obj.code != "5310":
                    continue
                if wanted is not None and entry.fid not in wanted:
                    continue
                records = [parse_label_record(line) for line in
                           self._doc.lines[entry.obj.start:entry.obj.end]]
                if any(record and (record["leader"] or record["anchor"])
                       for record in records):
                    targets.append(entry.obj)
            if not targets:
                return {**self._editing_status(), "changed": False, "reset": 0}
            with self._history.begin(
                    "Reset wysięgników (" + str(len(targets)) + " obiektów)",
                    selection_before=tuple(obj.uid for obj in targets)):
                for obj in targets:
                    for slot in (2, 3):
                        self._doc.set_label_leader(obj.uid, slot, False)
                    self._label_positions.pop(obj.uid, None)
            self._reindex(self._doc, self._doc.filename)
            self._revision += 1
            return {**self._editing_status(), "changed": True,
                    "reset": len(targets)}

    def select_by_code(self, code: str, bbox=None, limit: int = 5000) -> dict:
        """Zwraca ID obiektów o danym kodzie (opcjonalnie w prostokącie).

        ``bbox`` to ``[west, south, east, north]`` w jednostkach mapy.
        Służy przyciskom z sekcji „Blok”: zaznacz wszystkie o kodzie albo
        tylko te w wybranym fragmencie mapy.
        """
        with self._lock:
            if self._index is None or self._doc is None:
                raise ValueError("Najpierw otwórz mapę GEO-MAP.")
            if not isinstance(code, str) or not code.strip() or len(code) > 8:
                raise ValueError("Podaj kod obiektu, np. 5310.")
            code = code.strip()
            if not code.isdigit():
                raise ValueError("Kod obiektu składa się z cyfr.")
            area = None
            if bbox is not None:
                if (not isinstance(bbox, (list, tuple)) or len(bbox) != 4
                        or not all(_valid_number(value) for value in bbox)):
                    raise ValueError("Nieprawidłowy prostokąt zaznaczania.")
                west, south, east, north = (float(value) for value in bbox)
                if west > east:
                    west, east = east, west
                if south > north:
                    south, north = north, south
                area = (west, south, east, north)
            limit = max(1, min(MAX_BULK_EDIT_OBJECTS, int(limit)))
            ids: list[str] = []
            for entry in self._entries:
                if entry.obj.code != code:
                    continue
                if area is not None and not _intersects(entry.bbox, area):
                    continue
                ids.append(entry.fid)
                if len(ids) >= limit:
                    break
            return {"code": code, "ids": ids, "count": len(ids),
                    "limited": len(ids) >= limit, "bbox": list(area) if area else None}

    def set_label_leader(self, fid: str, slot: int, enabled: bool,
                         anchor=None, prefer_left=None, *,
                         document_token=None, revision=None) -> dict:
        """Włącza/wyłącza wysięgnik etykiety A1 (slot 2) lub A2 (slot 3).

        Zapis idzie do natywnego rekordu L, więc trafia też do pliku MAP.
        """
        with self._lock:
            if self._doc is None:
                raise ValueError("Najpierw otwórz mapę GEO-MAP.")
            self._require_edit(document_token, revision)
            entry = self._lookup.get(fid)
            if entry is None:
                raise LookupError(fid)
            obj = entry.obj
            if not obj.uid or self._uid_counts.get(obj.uid) != 1:
                raise ValueError("Wysięgnik wymaga unikalnego ID obiektu.")
            if slot not in (2, 3):
                raise ValueError("Wysięgnik dotyczy tylko etykiet A1 i A2.")
            if type(enabled) is not bool:
                raise ValueError("Opcja wysięgnika musi być true/false.")
            point = None
            if anchor is not None:
                if (not isinstance(anchor, (list, tuple)) or len(anchor) != 2
                        or not all(_valid_number(value) for value in anchor)):
                    raise ValueError("Nieprawidłowy punkt zaczepienia.")
                point = (round(float(anchor[0]), 3), round(float(anchor[1]), 3))
            if enabled and point is None:
                point = self._leader_default_anchor(obj)
            if enabled and point is not None:
                # Do pliku zapisujemy różnicę wobec punktu bazowego poligonu.
                base = _label_anchor(obj)
                point = (round(float(point[0]) - base[0], 3),
                         round(float(point[1]) - base[1], 3))
            before = self._doc.to_bytes()
            with self._history.begin(
                ("Włącz" if enabled else "Wyłącz") + " wysięgnik " +
                ("A1" if slot == 2 else "A2"),
                selection_before=(obj.uid,),
            ):
                changed = self._doc.set_label_leader(
                    obj.uid, slot, enabled, point, prefer_left)
            if not changed:
                return {**self._editing_status(), "changed": False}
            self._reindex(self._doc, self._doc.filename)
            self._revision += 1
            return {**self._editing_status(), "changed": True,
                    "fid": fid, "slot": slot, "enabled": enabled,
                    "anchor": list(point) if point else None}

    def _leader_default_anchor(self, obj) -> tuple[float, float]:
        """Punkt zaczepienia w środku poligonu (albo średnia wierzchołków)."""
        try:
            from shapely.geometry import Point
            shape = geometry_of(obj)
            if shape is not None and shape.is_valid and not shape.is_empty:
                inside = shape.representative_point()
                return (round(inside.y, 3), round(inside.x, 3))
        except Exception:
            pass
        points = obj.points or []
        if not points:
            return (0.0, 0.0)
        return (round(sum(p.x for p in points) / len(points), 3),
                round(sum(p.y for p in points) / len(points), 3))

    @staticmethod
    def _validate_sheet_items(items):
        if not isinstance(items,list) or len(items)>100:
            raise ValueError("Arkusz może zawierać do 100 elementów.")
        ids=set()
        for item in items:
            if (not isinstance(item,dict) or set(item)-{"runs","angle"}!={"id","kind","x","y","w","h","text"}
                    or item["kind"] not in ("title","credits","compass","symbols","species",SHEET_NUMBER,*SHEET_SIGNS)
                    or not isinstance(item["id"],str) or len(item["id"])>80 or item["id"] in ids
                    or not isinstance(item["text"],str) or len(item["text"])>1500
                    or len(item["text"].splitlines())>16
                    or (item["kind"]=="compartment" and (type(item.get("fontSize",12)) not in (int,float) or not 6<=item.get("fontSize",12)<=72))
                    or not all(type(item[k]) in (float,int) and isfinite(item[k]) and abs(item[k])<1e9
                               for k in ("x","y","w","h"))
                    or min(item["w"],item["h"])<=0):
                raise ValueError("Nieprawidłowy element arkusza.")
            if "angle" in item:
                angle=item["angle"]
                if (item["kind"] not in SHEET_ROTATABLE or type(angle) not in (int,float)
                        or not isfinite(angle) or not -360<=angle<=360):
                    raise ValueError("Obrót dotyczy tylko zrębu, bagna, linii energetycznej i gazociągu.")
            if item["kind"]==SHEET_NUMBER and not re.fullmatch(r"[\w./ -]{1,24}",item["text"]):
                raise ValueError("Numer oddziału musi mieć od 1 do 24 znaków.")
            runs=item.get("runs",[])
            if not isinstance(runs,list) or len(runs)>1500:
                raise ValueError("Nieprawidłowe formatowanie tekstu.")
            end=0
            for run in runs:
                if (not isinstance(run,dict) or type(run.get("start")) is not int
                        or type(run.get("end")) is not int or not end<=run["start"]<run["end"]<=3000):
                    raise ValueError("Nieprawidłowy zakres tekstu.")
                st=run.get("style")
                if (not isinstance(st,dict) or set(st)-{"family","size","bold","italic"}
                        or st.get("family","Arial") not in ("Arial","Times New Roman","Georgia","Verdana","Courier New","Calibri","Cambria","Tahoma","Trebuchet MS","Palatino Linotype","Garamond","Century Gothic","Franklin Gothic Medium","Book Antiqua")
                        or type(st.get("size",12)) is not int or not 4<=st.get("size",12)<=144
                        or any(type(st[k]) is not bool for k in ("bold","italic") if k in st)):
                    raise ValueError("Nieprawidłowa czcionka.")
                end=run["end"]
            ids.add(item["id"])
        return items

    def _live_sheet_items(self):
        record=self._styles.get("cartography:sheet",{})
        groups=record.get("groups",{})
        items=[]
        for item in record.get("items",[]):
            if item["kind"] in (*SHEET_SIGNS,SHEET_NUMBER):
                ids=groups.get(item["id"],[])
                parts=sheet_primitives(item)
                if not isinstance(ids,list) or len(ids)!=len(parts):
                    continue
                for uid,(code,pts,filled,_,fields) in zip(ids,parts):
                    obj=self._doc.by_id.get(uid)
                    if not obj or obj.code!=code or any(obj.fields.get(k)!=v for k,v in fields.items()):
                        break
                    actual=[(p.x,p.y) for p in obj.points]
                    coords=[(round(x,3),round(y,3)) for x,y in pts]
                    if filled:
                        if not obj.is_closed:break
                        actual=actual[:-1]
                    if actual!=coords and not (filled and actual==[coords[0],*coords[:0:-1]]):
                        break
                else:
                    items.append(item)
            else:
                items.append(item)
        return items

    def set_sheet_items(self, items, *, document_token, revision):
        with self._lock:
            self._require_edit(document_token,revision)
            self._validate_sheet_items(items)
            old={i["id"]:i for i in self._live_sheet_items()}
            record=self._styles.get("cartography:sheet",{})
            groups={k:v for k,v in record.get("groups",{}).items() if k in old}
            ids={i["id"] for i in items}
            with self._history.begin("Elementy arkusza"):
                for key in set(groups)-ids:
                    self._doc.delete_objects(groups.pop(key))
                for item in items:
                    key=item["id"]
                    if item["kind"] not in (*SHEET_SIGNS,SHEET_NUMBER) or old.get(key)==item:continue
                    if key in groups and all(old[key].get(field)==item.get(field)
                            for field in ("kind","x","y","w","h","text")):
                        continue
                    parts=sheet_primitives(item)
                    if key in groups:
                        if old[key]["kind"]!=item["kind"]:raise ValueError("Nie można zmienić rodzaju znaku.")
                        for uid,(_,points,filled,_,fields) in zip(groups[key],parts):
                            self._doc.replace_simple_geometry(uid,points,closed=filled)
                            for field,value in fields.items():
                                self._doc.update_field(uid,field,value)
                    else:
                        groups[key]=[]
                        for code,points,filled,color,fields in parts:
                            pen=int.from_bytes(bytes.fromhex(color[1:]),"little")
                            append=self._doc.append_polygon if filled else self._doc.append_polyline
                            groups[key].append(append(points,code=code,fields=fields,pen=pen,fill=pen if filled else 0))
                if items:self._styles["cartography:sheet"]={"items":items,"groups":groups}
                else:self._styles.pop("cartography:sheet",None)
            self._reindex(self._doc,self._doc.filename)
            self._revision+=1
            return self._editing_status()

    def set_compilation_scale(self, denominator: int,
                              *,document_token: str,revision: int) -> dict:
        with self._lock:
            self._require_edit(document_token,revision)
            if type(denominator) is not int or not (
                    100<=denominator<=1_000_000):
                raise ValueError("Skala opracowania musi mieć mianownik 100–1000000.")
            if self._current_compilation_scale()==denominator:
                return {**self._editing_status(),"changed":False}
            with self._history.begin("Skala opracowania 1:"+str(denominator)):
                self._styles["cartography:compilation_scale"]={
                    "denominator":denominator}
            self._revision+=1
            return {**self._editing_status(),"changed":True}

    def set_label_settings(self, code: str, field: str, properties: dict,
                           *,document_token: str,revision: int) -> dict:
        """One-field, one-code presentation settings with safe validation."""
        with self._lock:
            self._require_edit(document_token,revision)
            if (not re.fullmatch(r"[0-9]{4}",str(code)) or
                    code not in {entry.obj.code for entry in self._entries} or
                    field not in LABEL_FIELDS or not isinstance(properties,dict) or
                    set(properties)-{"visible","size","color","bold"}):
                raise ValueError("Nieprawidłowe ustawienia etykiety kodu.")
            visible=properties.get("visible",True)
            size=properties.get("size",16)
            bold=properties.get("bold",False)
            color=properties.get("color","#4A5056")
            if (type(visible) is not bool or type(bold) is not bool or
                    type(size) is not int or not 8<=size<=36 or
                    not isinstance(color,str) or not HEX.fullmatch(color)):
                raise ValueError("Nieprawidłowy rozmiar, kolor lub widoczność.")
            key="labels:code:"+code
            old=self._styles.get(key,{})
            fields=old.get("fields",{}) if isinstance(old,dict) else {}
            new_spec={"visible":visible,"size":size,"color":color,"bold":bold}
            if fields.get(field)==new_spec:
                return {**self._editing_status(),"changed":False}
            with self._history.begin("Wygląd etykiety "+code+" / "+field):
                current=self._styles.get(key,{})
                updated=dict(current.get("fields",{}))
                updated[field]=new_spec
                self._styles[key]={**current,"fields":updated}
            self._revision+=1
            return {**self._editing_status(),"changed":True}

    def _editing_status(self) -> dict:
        history = self._history
        return {
            "sheetItems": self._live_sheet_items(),
            "dirty": bool(history and history.is_dirty),
            "canUndo": bool(history and history.can_undo),
            "canRedo": bool(history and history.can_redo),
            "undoLabel": history.next_undo_label if history else "",
            "redoLabel": history.next_redo_label if history else "",
            "revision": self._revision,
            "documentToken": self._document_token,
            "hasReversibleMasks": bool(self._overlay_uids()),
            "hasVisualStyles":bool(
                self._label_positions or self._visual_user_styles()),
            "compilationScale":self._current_compilation_scale(),
            "sheetGroups":dict(self._styles.get("cartography:sheet",{}).get("groups",{})),
            "sourceCompilationScale":self._source_compilation_scale,
        }

    def find_objects(self, *,code: str = "", field: str = "*",
                     value: str = "", match: str = "contains",
                     limit: int = 120) -> dict:
        """Search the WHOLE map, including objects outside the viewport.

        No mutation, no saved searches, no automatic selection of ambiguous
        duplicate identifiers; results carry index-backed feature IDs and
        native UIDs separately. Reporting a truncated result is explicit.
        """
        if any(not isinstance(x,str) or len(x)>160
               for x in (code,field,value,match)):
            raise ValueError("Nieprawidłowe kryteria wyszukiwania.")
        code=code.strip()
        value=value.strip()
        valid_fields=set(LABEL_FIELDS)|{"*","ID"}
        if (code and not re.fullmatch(r"[0-9]{4}",code)) or field not in valid_fields:
            raise ValueError("Podaj czterocyfrowy kod lub prawidłowe pole.")
        if not code and not value:
            raise ValueError("Podaj kod albo szukaną wartość/ID.")
        if match not in {"contains","exact"}:
            raise ValueError("Wybierz dopasowanie dokładne lub fragment tekstu.")
        if type(limit) is not int or not 1<=limit<=250:
            raise ValueError("Nieprawidłowy limit wyników.")
        pattern=value.casefold()
        with self._lock:
            if self._doc is None:raise ValueError("Najpierw otwórz MAP.")
            total=0
            result=[]
            for entry in self._entries:
                obj=entry.obj
                if code and obj.code!=code:continue
                if value:
                    if field=="*":
                        haystacks=[obj.code,obj.uid or "",*obj.fields.values()]
                    elif field=="ID":
                        haystacks=[obj.uid or ""]
                    else:
                        haystacks=[obj.fields.get(field,"")]
                    if not any((h.strip().casefold()==pattern if match=="exact"
                                else pattern in h.strip().casefold())
                               for h in haystacks):
                        continue
                total+=1
                if len(result)<limit:
                    result.append({
                        "id":entry.fid,"uid":obj.uid or "",
                        "code":obj.code,"layer":entry.layer,
                        "bbox":list(entry.bbox),
                        "A1":str(obj.fields.get("A1",""))[:140],
                        "A2":str(obj.fields.get("A2",""))[:140],
                        "TX":str(obj.fields.get("TX",""))[:140],
                    })
            return {"results":result,"count":total,"truncated":total>limit,
                    "limit":limit,"documentToken":self._document_token,
                    "revision":self._revision}

    def _replace_phrase_plan(self, operation: dict, *,
                             document_token: str, revision: int) -> dict:
        """Validate the full replacement batch, with no in-place mutation."""
        self._require_edit(document_token,revision)
        if not isinstance(operation,dict) or set(operation)!={
                "field","needle","replacement","caseSensitive",
                "scope","ids","code"}:
            raise ValueError("Niepoprawny plan zamiany.")
        field=operation["field"]
        needle=operation["needle"]
        replacement=operation["replacement"]
        sensitive=operation["caseSensitive"]
        scope=operation["scope"]
        ids=operation["ids"]
        code=operation["code"]
        if (field not in LABEL_FIELDS or not isinstance(needle,str)
            or not 0<len(needle)<=160 or not isinstance(replacement,str)
            or len(replacement)>512 or type(sensitive) is not bool
            or scope not in {"selection","all"}
            or not isinstance(code,str) or (code and
                re.fullmatch(r"[0-9]{4}",code) is None)
            or not isinstance(ids,list) or len(ids)>MAX_BULK_EDIT_OBJECTS
            or any(not isinstance(v,str) or len(v)>25 for v in ids)
            or len(ids)!=len(set(ids))):
            raise ValueError("Uzupełnij pole, frazę i zakres zamiany.")
        if any(ch in replacement for ch in "\r\n]"):
            raise ValueError("Zamiennik nie może zawierać ] ani nowych linii.")
        if scope=="selection" and not ids:
            raise ValueError("Wybierz obiekty albo ustaw zakres: cała mapa.")
        if scope=="all" and ids:
            raise ValueError("Dla całej mapy nie przesyłaj zaznaczenia.")
        try:
            replacement.encode("cp1250",errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError("Zamiennik zawiera znaki spoza kodowania CP1250.") from exc
        pattern=re.compile(re.escape(needle),0 if sensitive else re.IGNORECASE)
        chosen=[]
        if scope=="selection":
            for fid in ids:
                entry=self._lookup.get(fid)
                if entry is None:raise LookupError("Nieznany obiekt w zaznaczeniu.")
                chosen.append(entry)
        else:
            chosen=self._entries
        pending={}
        samples=[]
        affected=[]
        occurrences=0
        scanned=0
        for entry in chosen:
            obj=entry.obj
            if code and obj.code!=code:continue
            scanned+=1
            old=obj.fields.get(field)
            if old is None:continue
            newer,count=pattern.subn(lambda _match:replacement,old)
            if not count or newer==old:continue
            if (not obj.uid or self._uid_counts.get(obj.uid)!=1
                    or self._doc.by_id.get(obj.uid) is not obj):
                raise ValueError("Pasujący obiekt ma niejednoznaczne :ID; całość anulowana.")
            if any(ch in newer for ch in "\r\n]"):
                raise ValueError("Zamiana utworzyłaby niedozwoloną wartość pola.")
            try:
                encoded=newer.encode("cp1250",errors="strict")
            except UnicodeEncodeError as exc:
                raise ValueError("Zamiana dałaby znaki spoza kodowania CP1250.") from exc
            if len(newer)>512 or len(encoded)>512:
                raise ValueError("Wynik zamiany przekracza limit 512 bajtów GEO-MAP.")
            pending[(obj.uid,field)]=newer
            affected.append(entry.fid)
            occurrences+=count
            if len(affected)>MAX_BULK_EDIT_OBJECTS:
                raise ValueError("Ponad 5 000 pasujących obiektów. Zawęź kod lub zakres.")
            if len(samples)<16:
                samples.append({"id":entry.fid,"uid":obj.uid,
                    "code":obj.code,"before":old,"after":newer,"count":count})
        payload={"operation":operation,"documentToken":document_token,
                 "revision":revision}
        key=sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,
                             separators=(",",":")).encode("utf-8")).hexdigest()
        return {"pending":pending,"affected":affected,
                "report":{**self._editing_status(),"previewKey":key,
                          "changedObjects":len(affected),
                          "changedFields":len(pending),
                          "occurrences":occurrences,
                          "scanned":scanned,"examples":samples,
                          "canApply":bool(pending)}}

    def preview_replace_phrase(self, operation: dict, *,
                               document_token: str, revision: int) -> dict:
        with self._lock:
            report=self._replace_phrase_plan(
                operation,document_token=document_token,revision=revision)["report"]
            self._replace_preview_key=report["previewKey"]
            return report

    def apply_replace_phrase(self, operation: dict, *,
                             document_token: str, revision: int,
                             preview_key: str) -> dict:
        with self._lock:
            plan=self._replace_phrase_plan(
                operation,document_token=document_token,revision=revision)
            report=plan["report"]
            if (not isinstance(preview_key,str) or
                    not self._replace_preview_key or
                    preview_key!=report["previewKey"] or
                    preview_key!=self._replace_preview_key):
                raise RuntimeError("Podgląd wygasł. Sprawdź ponownie zamianę.")
            self._replace_preview_key=""
            if not plan["pending"]:
                return {**self._editing_status(),"changed":False}
            modified={uid for uid,field in plan["pending"]}
            untouched=sha256()
            for obj in self._doc.objects:
                if obj.uid not in modified:
                    for line in self._doc.lines[obj.start:obj.end]:
                        untouched.update(line)
            before=untouched.digest()
            with self._history.begin(
                "Zamiana frazy w "+operation["field"]+" ("+
                str(report["changedObjects"])+" obiektów)",
                selection_before=tuple(modified)
            ):
                self._doc.bulk_update_fields(plan["pending"])
                after=sha256()
                for obj in self._doc.objects:
                    if obj.uid not in modified:
                        for line in self._doc.lines[obj.start:obj.end]:
                            after.update(line)
                if after.digest()!=before:
                    raise ValueError("Zamiana naruszyła obcy obiekt; operację cofnięto.")
            self._reindex(self._doc,self._doc.filename)
            self._revision+=1
            return {**self._editing_status(),"changed":True,
                    "changedObjects":report["changedObjects"],
                    "changedFields":report["changedFields"],
                    "occurrences":report["occurrences"],
                    "affected":plan["affected"]}

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

    def topology_audit(self, document_token: str, revision: int,
                       limit: int = 600, *, code: str | None = None) -> dict:
        """Read-only, revision-bound audit of the current working MAP."""
        from .topology_audit import inspect_topology
        with self._lock:
            if self._doc is None:
                raise ValueError("Najpierw otwórz mapę.")
            if document_token != self._document_token or (
                    type(revision) is not int or revision != self._revision):
                raise RuntimeError("Mapa zmieniła się. Uruchom analizę ponownie.")
            # All geometries belong to the same snapshot; no routine here
            # can mutate native P coordinates, styles or history.
            return inspect_topology(
                (self._entries if code is None else tuple(
                    entry for entry in self._entries if entry.obj.code == code)),
                document_token=self._document_token,
                revision=self._revision, limit=limit)


    def edit_fields(self, fid: str, changes: dict, *,
                    document_token: str, revision: int) -> dict:
        """Edit descriptive fields on the selected object."""
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
            fields = _inspector_fields(entry.obj)
            edits = {}
            for field, value in changes.items():
                if field not in LABEL_FIELDS or field not in fields:
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
                if fields[field] != value:
                    edits[(entry.obj.uid, field)] = value
            if not edits:
                return {**self._editing_status(), "changed": False, "object": self.details(fid)}
            with self._history.begin(
                "Atrybuty obiektu " + entry.obj.code,
                selection_before=(entry.obj.uid,),
            ):
                existing = {key: value for key, value in edits.items() if key[1] in entry.obj.fields}
                self._doc.bulk_update_fields(existing)
                for (uid, field), value in edits.items():
                    if field not in entry.obj.fields:
                        self._doc.update_field(uid, field, value)
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
            if not obj.is_closed or len(obj.display_parts)>1:
                continue  # open lines/points have no area topology; multipart moves intact
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
        """Validate points, open lines and polygons for the exact coordinate shift.

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
            if not obj.points:
                raise ValueError("Zaznaczenie zawiera obiekt bez geometrii.")
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
                if not obj.is_closed or len(obj.display_parts)>1:
                    continue  # magnet works only on polygon boundaries
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
            if (sum(len(obj.points) for obj in moving)>3000 or
                    any(len(obj.display_parts)>1 for obj in moving)):
                # The legacy ring-based snap assumes one contiguous contour.
                # Canvas magnetic nodes work per displayed part instead.
                fixed=[]
            nx,ny,distance=nearest_boundary_snap(
                [obj for obj in moving if obj.is_closed], fixed, dx, dy, snap_distance)
            if distance is not None:
                dx,dy=nx,ny
                snap_applied={"distance":round(distance,3)}
        for obj in moving:
            shifted={}
            for index,point in enumerate(obj.points):
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
                "Przesunięcie " + str(report["selected"]) + " obiektów",
                selection_before=tuple(plan["selectedUids"]),
            ):
                self._doc.translate_objects(plan["changes"])
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
            "create":{"action","code","points","fields","clipRasterOverlap"},
        }[action]
        if set(payload)-allowed_keys:
            raise ValueError("Nieznane pola polecenia.")
        selected=[]
        adjusted={}
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
            # The drawing cursor is snapped to the edge but the MAP format
            # stores P records on a 1 mm grid. Rounding a projected point
            # on a diagonal can create a sub-millimetre intersection.
            from shapely.geometry import Polygon
            from shapely.errors import GEOSException
            candidate=Polygon(coordinates)
            if not candidate.is_valid or candidate.is_empty:
                raise ValueError("Poligon ma niepoprawny obrys lub za małe pole.")
            obstacles=[]
            for other in self._index.nearby(*center,radius):
                if not other.is_closed or other.code!=code:
                    continue
                try:
                    existing=geometry_of(other)
                    overlap=creation_overlap(candidate,existing)
                    if overlap and code=='5310' and payload.get('clipRasterOverlap') is True:
                        obstacles.append(existing)
                        continue
                except (ValueError,GEOSException):
                    # Keep the previous conservative check for malformed
                    # legacy records which cannot be converted to GEOS.
                    overlap=rings_overlap(coordinates,ring_of(other))
                if overlap:
                    raise ValueError(
                        "Nowy poligon nakłada się na istniejący poligon tego samego kodu.")
            if obstacles:
                from shapely.ops import unary_union
                free=candidate.difference(unary_union(obstacles))
                if free.is_empty or free.area < .000001:
                    raise ValueError("Całe zaznaczenie zajmuje już istniejący 5310.")
                if free.geom_type!="Polygon" or free.interiors:
                    raise ValueError("Po odjęciu istniejących 5310 powstają osobne części lub otwór. Zmień zaznaczenie.")
                coordinates=[(round(x,3),round(y,3)) for x,y in list(free.simplify(0).exterior.coords)[:-1]]
                fitted=Polygon(coordinates)
                if (len(coordinates)>500 or not fitted.is_valid or not polygon_is_valid(coordinates)
                        or any(creation_overlap(fitted,g) for g in obstacles)):
                    raise ValueError("Nie można dopasować obrysu w dokładności MAP. Popraw węzły.")
                adjusted={"adjustedPoints":coordinates}
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
                          "previewKey":preview_key,"canApply":True,**adjusted,
                          **self._editing_status()}}

    def fit_trace_outline(self, points, *, document_token: str, revision: int) -> dict:
        """Read-only draft fit, independent of the edit preview/commit key."""
        with self._lock:
            plan = self._object_operation_plan(
                {"action": "create", "code": "5310", "fields": {},
                 "clipRasterOverlap": True, "points": points},
                document_token=document_token, revision=revision)
            return {"points": plan["coords"], "clipped": "adjustedPoints" in plan["report"]}

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
            if len(codes)!=1:
                raise ValueError("Scalane poligony muszą mieć ten sam kod.")
            geometry=merge_multipart([geometry_of(o) for o in selected])
            rings=rings_from_shape(geometry,
                prefer_anchor=(selected[0].points[0].x,selected[0].points[0].y))
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
                        "5214","6900","6000","6301","2364","4100"}:
                    raise ValueError("Wybrany obiekt nie jest obsługiwaną linią.")
            else:
                code=operation.get("code")
                if code not in {"5214","6900","6000","6301","2364"}:
                    raise ValueError("Wybierz kod linii 5214, 6900, 6000, 6301 lub 2364.")
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
                    anchor=selected[0].points[0]
                    self._doc.replace_polygon_components(
                        keeper,rings_from_shape(plan["geometry"],
                          prefer_anchor=(anchor.x,anchor.y)))
                    # GEO-MAP requires explicit L 1/2/3 placements for
                    # showing A1/A2 labels. Keep source entries when possible.
                    self._doc.ensure_native_label_records(
                        keeper,[o.uid for o in selected[1:]])
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
                        fields=operation["fields"],
                        pen=0xFF0000 if operation["code"]=="5214" else 8553090)]
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
                    snap_radius: float = 0, follow=None) -> dict:
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
            bends = []
            if follow is not None:
                if (not isinstance(follow, dict) or type(follow.get("step")) is not int
                        or follow["step"] not in (-1, 1)
                        or not isinstance(follow.get("points"), list)
                        or not 1 <= len(follow["points"]) <= 200):
                    raise ValueError("Nieprawidłowy przebieg granicy.")
                for point in follow["points"]:
                    if (not isinstance(point, list) or len(point) != 2
                            or any(type(v) not in (int, float) or not isfinite(v) or abs(v)>=1e9 for v in point)):
                        raise ValueError("Nieprawidłowe współrzędne załamania.")
                    bends.append(tuple(round(v, 3) for v in point))
                other_end = obj.points[(index + follow["step"]) % (len(obj.points)-1)]
                fixed = (other_end.x, other_end.y)
                snap_radius = 0
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
            if not bends and hypot(old.x - x, old.y - y) < 0.0005:
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
                if hypot(old.x-x,old.y-y)>=.0005:
                    self._doc.move_polygon_vertices(changes)
                if bends:
                    start, end = fixed, (x, y)
                    if follow["step"] == 1:
                        start, end = end, start
                        bends.reverse()
                    updates = []
                    for target in self._doc.objects:
                        if target.uid != obj.uid and not shared:
                            continue
                        if not target.is_closed or target.code != obj.code:
                            continue
                        pts = [(p.x,p.y) for p in target.points]
                        for seg, pair in enumerate(zip(pts,pts[1:])):
                            if pair == (start,end) or pair == (end,start):
                                if not target.uid or self._uid_counts.get(target.uid) != 1:
                                    raise ValueError("Niejednoznaczna wspólna granica.")
                                updates.append((target.uid,seg,bends if pair==(start,end) else bends[::-1]))
                    if not any(uid==obj.uid for uid,_,_ in updates):
                        raise ValueError("Nie znaleziono dopasowywanego boku.")
                    for uid,seg,path in reversed(updates):
                        self._doc.insert_polygon_edge_path(uid,seg,path)
                        changes.setdefault(uid,{})
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

    def mark_saved(self) -> None:
        """The current document and its sidecars reached the disk."""
        with self._lock:
            if self._history is None or self._doc is None:
                raise ValueError("Brak dokumentu do oznaczenia jako zapisany.")
            self._history.mark_saved()

    def mark_recovered_unsaved(self) -> None:
        """Recovered session has not been saved as a new MAP by the user."""
        with self._lock:
            if self._history is None or self._doc is None:
                raise ValueError("Brak dokumentu do oznaczenia po odzyskaniu.")
            self._history.mark_recovered_unsaved()

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



    def store_generated_export(self, document_token: str, revision: int,
                               filename: str, extension: str,
                               content: bytes) -> str:
        """One-use, bounded browser-generated image buffer for native Save As."""
        valid={"png","jpg","tif","dxf","pdf"}
        if (extension not in valid or not isinstance(filename,str)
                or len(filename)>140 or filename in {".",".."}
                or any(ch in filename for ch in "/\\\0\r\n")
                or not filename.lower().endswith("."+extension)):
            raise ValueError("Nieprawidłowa nazwa lub format eksportu.")
        if not isinstance(content,bytes) or not 0<len(content)<=120*1024*1024:
            raise ValueError("Pusty lub zbyt duży eksport (maks. 120 MB).")
        with self._lock:
            if self._doc is None:
                raise ValueError("Najpierw otwórz mapę.")
            if document_token!=self._document_token or revision!=self._revision:
                raise RuntimeError("Zmieniła się mapa podczas eksportu.")
            ticket=token_hex(20)
            self._generated_export=(ticket,filename,extension,content)
            return ticket

    def generated_export(self, ticket: str, *, consume: bool = False):
        with self._lock:
            item=self._generated_export
            if (not isinstance(ticket,str) or not item or
                    item[0]!=ticket):
                raise LookupError("Eksport wygasł. Utwórz go ponownie.")
            if consume:
                self._generated_export=None
            return item[1:]

    def export_vector_pdf(self, document_token: str, options: dict) -> tuple[str, bytes]:
        """Render edited visible MAP geometry as a vector print sheet."""
        from geostudio.web_app.print_layout import render_vector_pdf, _setup
        if not isinstance(options,dict):
            raise ValueError("Brak parametrów arkusza.")
        _setup(options)  # Reject impossible paper / scale before indexing.
        with self._lock:
            if self._doc is None:
                raise ValueError("Najpierw otwórz mapę.")
            if document_token != self._document_token:
                raise RuntimeError("Nieaktualny dokument.")
            bounds=tuple(options["bounds"])
            page=self.viewport(bounds,limit=MAX_RENDER_FEATURES)
            if page["limited"] or page["total"]>85000:
                raise ValueError("Za dużo obiektów do pojedynczego PDF; zawęź widok.")
            hidden_uses=options.get("hiddenLandUses", [])
            if (not isinstance(hidden_uses,list) or len(hidden_uses)>2000 or
                    not all(isinstance(key,str) and len(key)<=120
                            for key in hidden_uses)):
                raise ValueError("Nieprawidłowe filtrowanie klas użytków.")
            hidden_set=set(hidden_uses)
            hidden_forest=options.get("hiddenForestClasses", [])
            if (not isinstance(hidden_forest,list) or len(hidden_forest)>2000 or
                    not all(isinstance(grade,str) and len(grade)<=120
                            for grade in hidden_forest)):
                raise ValueError("Nieprawidłowe filtrowanie klas leśnych.")
            forest_set=set(hidden_forest)
            visible=options.get("visibleLayers")
            if visible is not None:
                if (not isinstance(visible,list) or len(visible)>300 or
                    not all(type(x) is str and len(x)<120 for x in visible)):
                    raise ValueError("Nieprawidłowa lista widocznych warstw.")
                chosen=set(visible)
                features=[f for f in page["features"] if f["layer"] in chosen]
            else:
                features=page["features"]
            if hidden_set:
                features=[f for f in features if not (
                    f["layer"]=="Użytki" and f["landUse"] in hidden_set)]
            if forest_set:
                features=[f for f in features if not (
                    f["layer"]=="Użytki Leśne" and f["grade"] in forest_set)]
            data=render_vector_pdf(features,options)
            base=_display_name(self._doc.filename)
            return base[:-4]+"_arkusz_wektorowy.pdf", data

    def export_dxf(self, document_token: str, bounds=None) -> tuple[str, bytes]:
        """Editable R2010 DXF with native X/Y, geometry/description layers.

        Preserve G#### geometry layers for backward compatibility. Label
        entities are separated as G####_A1/A2/TX and respect saved positions.
        True-colour and lineweights are approximations of screen styling;
        unknown GEO-MAP symbols and patterns are not claimed to round-trip.
        """
        import io
        import ezdxf

        with self._lock:
            if self._doc is None:
                raise ValueError("Najpierw otwórz mapę.")
            if document_token != self._document_token:
                raise RuntimeError("Nieaktualny dokument.")
            if bounds is not None:
                if (not isinstance(bounds,(list,tuple)) or len(bounds)!=4 or
                    any(type(x) not in (float,int) or not isfinite(x)
                        for x in bounds) or
                    bounds[2]<=bounds[0] or bounds[3]<=bounds[1]):
                    raise ValueError("Niepoprawny prostokąt eksportu DXF.")
                bounds=tuple(bounds)
            dxf=ezdxf.new("R2010")
            dxf.header["$INSUNITS"]=6  # metres
            dxf.header["$MEASUREMENT"]=1
            model=dxf.modelspace()
            if "GEOSTUDIO" not in dxf.appids:
                dxf.appids.new("GEOSTUDIO")

            def palette(style, kind="stroke"):
                color=str(style.get(kind,"#4A5056"))
                try:
                    return int(color.lstrip("#"),16) if len(color)==7 else 0x4A5056
                except ValueError:
                    return 0x4A5056

            def stroke_weight(style):
                # Physical DXF lineweights are hundredths of a millimetre.
                # Existing user stroke widths are screen pixels, so only an
                # approximate 96DPI-to-mm conversion is possible.
                chosen=int(round(float(style.get("strokeWidth",1)) * 25))
                valid=(5,9,13,15,18,20,25,30,35,40,50,53,60,70,80,
                       90,100,106,120,140,158,200,211)
                return min(valid,key=lambda item:abs(item-chosen))

            def layer(name, color=0x4A5056, weight=25):
                if name not in dxf.layers:
                    dxf.layers.new(name=name)
                    dxf.layers.get(name).dxf.true_color=color
                    dxf.layers.get(name).dxf.lineweight=weight
                return name

            def xdata(entity,obj):
                if obj.uid:
                    entity.set_xdata("GEOSTUDIO",[
                        (1000,"UID:"+str(obj.uid)[:230]),
                        (1000,"CODE:"+obj.code)])
            entries=self._entry_by_objid

            def within_export(entry):
                # Keep the entire native CAD object if it intersects the
                # chosen region. Never corrupt its P topology by clipping.
                return bounds is None or (
                    entry is not None and _intersects(entry.bbox,bounds))

            # Solid hatches for supported single-ring filled polygons.
            # Multiple contours/holes remain geometry-only to avoid
            # fabricating topology that may be misread by CAD.
            for obj in self._doc.objects:
                entry=entries.get(id(obj))
                if not entry or not obj.points or not obj.is_closed or not within_export(entry):
                    continue
                style=self._style(entry)
                parts=[part for part in obj.display_parts if len(part)>=4]
                if (obj.code=="5214" or len(parts)!=1 or
                    not style.get("hasFill") or style.get("opacity",0)<=0):
                    continue
                name=layer("G"+obj.code+"_FILL",palette(style,"fill"))
                hatch=model.add_hatch(dxfattribs={"layer":name})
                rgb=palette(style,"fill")
                hatch.set_solid_fill(color=7,rgb=(
                    (rgb>>16)&255,(rgb>>8)&255,rgb&255))
                points=parts[0]
                closed=(points[0].x==points[-1].x and
                        points[0].y==points[-1].y)
                hatch.paths.add_polyline_path(
                    [(point.x,point.y) for point in (
                        points[:-1] if closed else points)],
                    is_closed=True)
                xdata(hatch,obj)

            for obj in self._doc.objects:
                if not obj.points:
                    continue
                entry=entries.get(id(obj))
                if not within_export(entry):
                    continue
                style=self._style(entry) if entry else {}
                base=layer("G"+obj.code,palette(style),stroke_weight(style))
                rgb=palette(style)
                attrs={"layer":base,"true_color":rgb,
                       "lineweight":stroke_weight(style)}
                for part in obj.display_parts:
                    if not part:continue
                    if len(part)==1:
                        entity=model.add_point((part[0].x,part[0].y),
                                               dxfattribs=attrs)
                    else:
                        closed=(len(part)>=4 and
                                part[0].x==part[-1].x and
                                part[0].y==part[-1].y)
                        vertices=part[:-1] if closed else part
                        entity=model.add_lwpolyline(
                            [(point.x,point.y) for point in vertices],
                            close=closed,dxfattribs=attrs)
                    xdata(entity,obj)
                positions={
                    item["field"]: item for item in self._labels(entry)
                } if entry else {}
                for index,field in enumerate(("A1","A2","TX")):
                    value=str(obj.fields.get(field,"")).strip()
                    if not value:continue
                    text_layer=layer("G"+obj.code+"_"+field,rgb)
                    location=positions.get(field)
                    if location:
                        # Web label x=easting, y=-northing.
                        position=(-float(location["y"]),float(location["x"]))
                        size=max(1.,min(8.,float(location["size"])*.18))
                        fill_color=palette({"stroke":location["color"]})
                    else:
                        position=(obj.points[0].x,
                                  obj.points[0].y-index*3.)
                        size=2.5;fill_color=rgb
                    # Keep A1 and A2 as separate, editable TEXT entities.
                    for i,line in enumerate(value.replace("||","\n").splitlines()[:6]):
                        if not line:continue
                        entity=model.add_text(
                            line[:200],dxfattribs={
                                "layer":text_layer,"height":size,
                                "true_color":fill_color,
                                "insert":(position[0],position[1]-i*size*1.2)})
                        xdata(entity,obj)
            stream=io.StringIO()
            dxf.write(stream)
            name=_display_name(self._doc.filename)
            return name[:-4]+"_GeoStudio2.dxf",stream.getvalue().encode("utf-8")

    def reprojected_copy(self, source, target, document_token, revision):
        from geostudio.coordinates import MODERN_EPSG, transform_label_positions, transform_map_copy
        with self._lock:
            self._require_edit(document_token, revision)
            if type(source) is not int or type(target) is not int or source not in MODERN_EPSG or target not in MODERN_EPSG:
                raise ValueError("Wybierz źródłowy i docelowy układ MAP.")
            if source == target:
                raise ValueError("Wybierz inny układ docelowy.")
            # Edits update native records in memory; serialize their current checksum.
            if self._revision == 0 and not self._doc.checksum_valid:
                raise ValueError("Suma kontrolna źródłowej MAP jest niezgodna.")
            source_doc = GeoMap(self._doc.to_bytes())
            converted = transform_map_copy(source_doc, source, target)
            result = PreviewWorkspace()
            name = Path(self._doc.filename).stem + f"_EPSG{target}.MAP"
            result.load_map(converted.to_bytes(), name, epsg=target)
            result._styles = deepcopy(self._styles)
            result._label_positions = transform_label_positions(self._label_positions, source, target)
            for attr in ("_carto_loaded", "_carto_cdf", "_carto_lay", "_carto_sym", "_carto_patterns"):
                setattr(result, attr, deepcopy(getattr(self, attr)))
            return result

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
            return {**self._meta, **self._editing_status(),
                'mapEPSG': self.map_epsg, 'rasterMapKey': self._raster_map_key, 'cartographicLibraries':dict(self._carto_loaded)}

    def set_cartographic_library(self, filename: str, content: bytes) -> dict:
        """Load one local CP1250 GEO-MAP library without writing to disk."""
        if (not isinstance(filename,str) or
                not re.fullmatch(r"[^/\\\r\n]{1,140}\.(?:LAY|CDF|SYM)",
                                 filename,re.IGNORECASE) or
                not isinstance(content,bytes) or
                not 0<len(content)<=8*1024*1024):
            raise ValueError("Wybierz bibliotekę LAY/CDF/SYM (max 8 MB).")
        kind=filename.rsplit(".",1)[1].upper()
        if kind=="LAY":
            parsed=parse_lay_pen_styles(content)
            if len(parsed)>10000:raise ValueError("Za wiele wpisów LAY.")
        elif kind=="CDF":
            parsed=parse_cdf(content)
            if len(parsed)>10000:raise ValueError("Za wiele wpisów CDF.")
        else:
            primitives=parse_sym_primitives(content)
            patterns=parse_sym_line_patterns(content)
            if len(primitives)>15000 or len(patterns)>5000:
                raise ValueError("Za wiele definicji SYM.")
            parsed=primitives
        if not parsed:
            raise ValueError("Nie rozpoznano obsługiwanych definicji "+kind)
        with self._lock:
            if kind=="LAY":self._carto_lay=parsed
            elif kind=="CDF":self._carto_cdf=parsed
            else:
                self._carto_sym=parsed
                self._carto_patterns=patterns
            self._carto_loaded[kind]={"filename":filename,
                                      "definitions":len(parsed)}
            self._carto_match_cache.clear()
            return {"loaded":True,"kind":kind,"definitions":len(parsed),
                    "libraries":dict(self._carto_loaded)}

    def cartography_status(self) -> dict:
        with self._lock:
            return {"libraries":dict(self._carto_loaded),
                    "loaded":bool(self._carto_loaded)}

    def cartography_catalog(self, limit: int = 150) -> dict:
        """Report actual per-code rendering, not assumed GEO-MAP parity.

        Library selectors can also depend on A1/A2: the representative
        style is explicitly marked as a sample object, not a code-wide
        override. This endpoint never mutates the map or its libraries.
        """
        limit = max(1, min(250, int(limit)))
        with self._lock:
            if self._doc is None:
                raise ValueError("Najpierw otwórz mapę.")
            counts: Counter[str] = Counter()
            samples: dict[str, _Entry] = {}
            for entry in self._entries:
                code = entry.obj.code
                counts[code] += 1
                samples.setdefault(code, entry)
            items = []
            for code in sorted(samples, key=lambda key: (-counts[key], key))[:limit]:
                entry = samples[code]
                obj = entry.obj
                style = self._style(entry)
                notes = []
                if style["hatch"] > 8:
                    notes.append("CDF: wzór kreskowania poza obsługiwanym zakresem 0–8")
                primitives = self._carto_sym.get(code, ())
                unknown = sorted({p.kind for p in primitives if p.kind not in {"L", "A"}})
                if unknown:
                    if unknown == ["O"] and style["dash"]:
                        notes.append("SYM: makro O użyte do kreski; inne efekty O nie są interpretowane")
                    else:
                        notes.append("SYM: częściowo lub wcale nierenderowane instrukcje " +
                                     ", ".join(unknown))
                if any(p.kind == "A" for p in primitives) and not style["symbolCircles"]:
                    notes.append("SYM: łuk nie jest pełnym okręgiem i wymaga weryfikacji")
                lay = lay_for_code(self._carto_lay, code)
                if lay and (lay.line_id not in {"2.008"} and
                            not style["dash"]):
                    notes.append("LAY: wzór " + lay.line_id + " wymaga interpretacji")
                items.append({
                    "code": code, "layer": entry.layer, "count": counts[code],
                    "a1": obj.fields.get("A1", "")[:80],
                    "a2": obj.fields.get("A2", "")[:80],
                    "style": style, "notes": notes,
                })
            return {
                "libraries": dict(self._carto_loaded),
                "totalCodes": len(samples),
                "totalObjects": len(self._entries),
                "items": items,
                "sampleOnly": True,
            }

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
        expected=payload.get("sha256")
        if expected is not None and expected!=self._loaded_map_sha:
            raise ValueError("Plik etykiet i stylów nie pasuje do otwartego MAP.")
        raw = payload.get("objects", {})
        styles = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(key, str) and isinstance(value, dict):
                    styles[key[:220]] = value
        if "cartography:sheet" in styles:
            sheet=styles["cartography:sheet"]
            self._validate_sheet_items(sheet.get("items"))
            groups=sheet.get("groups",{})
            if (not isinstance(groups,dict) or len(groups)>100 or
                    any(not isinstance(ids,list) or len(ids)>10 or
                        any(not isinstance(uid,str) for uid in ids) for ids in groups.values())):
                raise ValueError("Nieprawidłowe obiekty oznaczeń arkusza.")
        pos = payload.get("labels", {})
        labels={}
        if isinstance(pos,dict) and len(pos)<=50000:
            known={obj.uid for obj in self._doc.objects if obj.uid}
            for uid,coords in pos.items():
                if (uid not in known or not isinstance(coords,dict) or
                        len(coords)>len(LABEL_FIELDS)):continue
                kept={}
                for field,xy in coords.items():
                    if (field in LABEL_FIELDS and isinstance(xy,list)
                            and len(xy)==2 and all(
                                type(v) in (int,float) and isfinite(v)
                                and abs(v)<1e9 for v in xy)):
                        kept[field]=[round(xy[0],3),round(xy[1],3)]
                if kept:labels[uid]=kept
        with self._lock:
            # Preserve the separately checked 6A/6B dynamic overlay stack.
            topology=self._styles.get(TOPOLOGY_STACK_KEY)
            self._styles={**styles}
            if topology is not None:
                self._styles[TOPOLOGY_STACK_KEY]=topology
            self._label_positions = labels
        return {"loaded": True, "styleCount": len(styles), "labelPositions": len(labels),
                "compilationScale":self._current_compilation_scale()}

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
        cache_key=(obj.code,obj.fields.get("A1",""),obj.fields.get("A2",""))
        if cache_key not in self._carto_match_cache:
            self._carto_match_cache[cache_key]=cdf_for_object(
                self._carto_cdf,*cache_key)
        cdf=self._carto_match_cache[cache_key]
        lay=lay_for_code(self._carto_lay,obj.code)
        # CDF override > LAY line colour > MAP native COLORREF. LAY's
        # numeric word is a Windows BGR COLORREF, not an HTML RGB string.
        # Ignore zero (often a "default pen" marker) and bad values.
        lay_rgb=(tuple((lay.colorref>>shift)&255 for shift in (0,8,16))
                 if lay and 0<lay.colorref<=0xFFFFFF else None)
        border_rgb=(cdf.border if cdf and cdf.border!=(0,0,0)
                    else lay_rgb if lay_rgb else obj.colorref)
        border = "#" + "".join(f"{c:02X}" for c in border_rgb)
        native = native_fill_color(obj.style)
        land_use = obj.fields.get("A1", "").strip().casefold()
        force = (code_style.get("force_fill") is True
                 and "fill" in code_style)
        fill_color = None
        opacity = 0

        if obj.code == "5214":
            # An administrative precinct boundary is a LINE, never
            # a filled area, regardless of any CDF/native fill token.
            pass
        elif obj.code == "5230" and land_use in {"dr", "droga"}:
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
        elif cdf:
            fill_color = "#" + "".join(f"{c:02X}" for c in cdf.fill)
            opacity = _opacity(code_style.get("opacity", 100), 100)
        elif obj.code == "5200" and len(obj.points) == 4 and obj.fields.get("FA") == "0":
            # Black quarters of the native north arrow; not its border
            # boxes / sample swatches on a sheet.
            fill_color = "#111111"
            opacity = 100

        stroke = _color(code_style.get("stroke"), "#FF0000" if obj.code == "5310" else "#0000FF" if obj.code == "5214" else border)
        width_default=(3. if obj.code == "5310" else 2. if obj.code == "5214" else max(.8,min(3.,cdf.width)) if cdf and cdf.width>0
                       else 1.)
        width = min(12, max(.5, float(code_style.get(
            "stroke_width",width_default)))) \
            if _valid_number(code_style.get("stroke_width",width_default)) else width_default
        sym_dash=object_sym_line_pattern(self._carto_sym,
                                         self._carto_patterns,obj.code)
        dash=[max(.5,sym_dash[0]*3),max(.5,sym_dash[1]*3)] if sym_dash else (
            [6,4] if sym_dash is None and lay and lay.line_id.endswith(".008")
            else [])
        if obj.code=="5214":
            dash=[8,4]
        symbols=self._carto_sym.get(obj.code,[]) if len(obj.points)==1 else []
        segments=simple_point_segments(symbols)[:64]
        circles=simple_point_circles(symbols)[:32]
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
            "dash": dash,
            "hatch": (cdf.hatch if cdf and not native and
                      not (obj.code=="5230" and land_use.startswith("ls"))
                      and not force and "fill" not in item_style and
                      "fill" not in code_style else 0),
            "symbolSegments": segments,
            "symbolCircles": circles,
            # Stage 8 diagnostics: loaded definitions can be unrelated to the
            # codes in this viewport. Tell the user about real matches rather
            # than claiming the map's appearance has changed.
            "libraryMatches": [
                kind for kind,matched in (
                    ("CDF",cdf is not None),
                    ("LAY",lay is not None),
                    ("SYM",sym_dash is not None or bool(symbols))
                ) if matched
            ],
            "libraryApplied": [
                kind for kind,applied in (
                    ("CDF",cdf is not None and (
                        cdf.border!=(0,0,0) or cdf.width>0 or
                        (fill_color is not None and not native))),
                    ("LAY",lay is not None and (lay_rgb is not None or
                     (sym_dash is None and lay.line_id.endswith(".008")))),
                    ("SYM",sym_dash is not None or bool(segments) or bool(circles))
                ) if applied
            ],
        }

    def outline_settings(self, code: str) -> dict:
        """One global stroke preset for all current/future objects of a code."""
        if not re.fullmatch(r"[0-9]{4}", str(code)):
            raise ValueError("Kod obrysu musi mieć cztery cyfry.")
        with self._lock:
            if self._doc is None:
                raise ValueError("Najpierw otwórz mapę.")
            entry=next((e for e in self._entries if e.obj.code==code),None)
            if entry is None and code not in {"5214","5216","5220","5230","5310"}:
                raise ValueError("Kod nie występuje w otwartej mapie.")
            saved=self._styles.get("code:"+code,{})
            style=self._style(entry) if entry else {
                "stroke":saved.get("stroke","#FF0000" if code=="5310" else "#4A5056"),
                "strokeWidth":saved.get("stroke_width",3. if code=="5310" else 1.)
            }
            return {
                "code":code,"stroke":style["stroke"],
                "strokeWidth":style["strokeWidth"],
                "custom":("stroke" in saved or "stroke_width" in saved)
            }

    def set_outline_settings(self, code: str, stroke: str,
                             width: float, *, reset: bool=False,
                             document_token: str, revision: int) -> dict:
        """Undoable visual-only code style; never change original MAP."""
        with self._lock:
            self._require_edit(document_token,revision)
            if (not re.fullmatch(r"[0-9]{4}",str(code)) or
                    (code not in {"5214","5216","5220","5230","5310"} and
                     code not in {e.obj.code for e in self._entries})):
                raise ValueError("Nieprawidłowy kod obrysu.")
            if type(reset) is not bool:
                raise ValueError("Nieprawidłowy tryb przywracania stylu.")
            if not reset and (
                    type(stroke) is not str or not HEX.fullmatch(stroke) or
                    type(width) not in (float,int) or not isfinite(width) or
                    not .5<=width<=12):
                raise ValueError("Wybierz kolor #RRGGBB i grubość 0,5–12 px.")
            key="code:"+code
            old=dict(self._styles.get(key,{}))
            new=dict(old)
            if reset:
                new.pop("stroke",None)
                new.pop("stroke_width",None)
            else:
                new["stroke"]=stroke.upper()
                new["stroke_width"]=round(float(width),2)
            if new==old:
                return {**self._editing_status(),"changed":False}
            with self._history.begin("Obrys kodu "+code):
                if new:self._styles[key]=new
                else:self._styles.pop(key,None)
            self._revision+=1
            return {**self._editing_status(),"changed":True,
                    "code":code}

    def label_settings(self,code: str) -> dict:
        if not re.fullmatch(r"[0-9]{4}",str(code)):
            raise ValueError("Kod etykiety musi mieć cztery cyfry.")
        with self._lock:
            if self._doc is None:raise ValueError("Najpierw otwórz mapę.")
            spec=self._styles.get("labels:code:"+code,{})
            return {"code":code,"fields":dict(spec.get("fields",{}))
                if isinstance(spec,dict) else {}}

    def _labels(self, entry: _Entry) -> list[dict]:
        obj = entry.obj
        if obj.code=="6900":
            groups=self._styles.get("cartography:sheet",{}).get("groups",{})
            if any(obj.uid in ids for ids in groups.values()) and any(
                    i["kind"]==SHEET_NUMBER and obj.uid in groups.get(i["id"],[]) for i in self._live_sheet_items()):
                return []
        code_config = self._styles.get("labels:code:" + obj.code, {})
        overrides = code_config.get("fields") if isinstance(code_config, dict) else None
        if obj.code == "5310":
            fields = ["A1", "A2"]
        elif obj.code in {"5216", "5220", "5230"}:
            fields = ["A2"]
        elif obj.code in {"7900", "6900", "6000"}:
            fields = ["TX"]
        else:
            fields = []
        # Each native field remains INDEPENDENT. A style override for A1
        # cannot implicitly hide A2. Explicitly enabled extra fields are
        # supported without changing the normal default for each code.
        if isinstance(overrides,dict):
            explicit_extras=[
                key for key, config in overrides.items()
                if (key in LABEL_FIELDS and key not in fields and
                    isinstance(config,dict) and config.get("visible") is True)]
            if explicit_extras:
                # Legacy editor semantics: declaring an entirely new
                # attribute set replaces the defaults. Existing sidecars
                # that explicitly selected only A3 continue to work.
                fields=[key for key in LABEL_FIELDS if
                        isinstance(overrides.get(key),dict) and
                        overrides[key].get("visible") is True]
            else:
                # Merely styling A1 does not accidentally hide native A2.
                fields=[key for key in fields if not (
                        isinstance(overrides.get(key),dict) and
                        overrides[key].get("visible") is False)]
        pos = self._label_positions.get(obj.uid, {}) if obj.uid else {}
        center = _label_anchor(obj)
        # Natywne rekordy L 2/L 3 niosą własny wysięgnik (bity 64/128 flagi
        # i punkt zaczepienia). Slot 2 to A1, slot 3 to A2.
        leaders = {}
        natives = {}
        if self._doc is not None and obj.uid:
            from ..geomap import label_records
            # Punkt zaczepienia w rekordzie L jest WZGLĘDNY wobec punktu
            # bazowego poligonu (tego samego, co pozycja napisu). Wcześniej
            # brałem go jako współrzędne świata — stąd linie lecące do (0,0).
            natives = label_records(self._doc.lines[obj.start:obj.end])
            for slot, record in natives.items():
                if not record.get("leader"):
                    continue
                offset = record.get("anchor") or (0.0, 0.0)
                anchor_x = center[0] + float(offset[0])
                anchor_y = center[1] + float(offset[1])
                leaders[slot] = {"direction": record["leader"],
                                 "x": anchor_y, "y": -anchor_x}
        result = []
        for i, field in enumerate(fields):
            value = obj.fields.get(field, "").replace("||", "\n").strip()
            if not value:
                continue
            style = overrides.get(field, {}) if isinstance(overrides, dict) else {}
            location = pos.get(field) if isinstance(pos, dict) else None
            if obj.code == "5310" and field in ("A1", "A2"):
                native = natives.get(2 if field == "A1" else 3)
                if native and (native.get("dx") or native.get("dy")):
                    candidate = [center[0] + native["dx"],
                                 center[1] + native["dy"]]
                    # Przy wysięgniku napis CELOWO leży poza poligonem, więc
                    # test „wewnątrz" dotyczy tylko etykiet bez wysięgnika.
                    if native.get("leader") or self._label_inside(obj, candidate):
                        location = candidate
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
            leader = leaders.get(2 if field == "A1" else 3 if field == "A2" else 0)
            result.append({
                "field": field, "text": formatted[:220],
                "leader": leader,
                "x": east, "y": south,
                "offset": (0 if location else
                    (i - (len(fields) - 1)/2)*base_size*.80),
                "manuallyPlaced":bool(location),
                "color": _color(style.get("color"), palette),
                "size": max(8, min(36, _int(style.get("size"), base_size))),
                "fontFamily": str(style.get(
                    "font", "Times New Roman" if is_sheet and obj.code in {"7900","6900"}
                    else "Segoe UI"))[:80],
                "bold": bool(style.get("bold", is_building or obj.code in {"7900","6900"})),
                "worldTextHeight": _sheet_text_height(obj.fields) if is_sheet else None,
            })
        return result

    def _feature(self, entry: _Entry, overlay_objects=(),
                 overlay_rank=None) -> dict:
        obj=entry.obj
        parts=[[[p.y,-p.x] for p in segment]
               for segment in obj.display_parts if segment]
        visible_area=obj.area_m2
        mask_count=0
        if obj.is_closed and overlay_objects:
            rank=overlay_rank
            if rank is None:
                rank={uid:i for i,uid in enumerate(self._overlay_uids())}
            at=rank.get(id(obj),-1)
            # Only later objects of exactly the SAME code can mask this
            # object, and stationary foreign-code lines remain protected.
            upper=[other for other in overlay_objects
                   if other is not obj and other.code==obj.code
                   and rank.get(id(other),-1)>at]
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
                "grade":entry.grade,
                "landUse": (str(obj.fields.get("A2", "") or "").strip().casefold()
                            if entry.layer == "Użytki" else None),
                "bbox":entry.bbox,"closed":obj.is_closed,
                "geometry":parts,"style":self._style(entry),
                "labels":self._labels(entry) if parts else [],
                "baseAreaM2":obj.area_m2,
                "visibleAreaM2":visible_area,
                "reversibleCutout":mask_count>0}

    def viewport(self, bounds: tuple[float, float, float, float],
                 limit: int = MAX_RENDER_FEATURES, offset: int = 0) -> dict:
        """Query only the visible spatial region; never serialize all map data."""
        west, south, east, north = bounds
        if not all(isfinite(v) for v in bounds) or west > east or south > north:
            raise ValueError("Nieprawidłowy obszar widoku.")
        limit = max(1, min(MAX_RENDER_FEATURES, int(limit)))
        if type(offset) is not int or offset < 0 or offset > 10000000:
            raise ValueError("Nieprawidłowy indeks partii geometrii.")
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
            # A complete-map request uses the already indexed list. Do not
            # approximate a wide rectangle with a centre/radius query:
            # that can omit narrow corners of a cadastral sheet.
            full_map=(tuple(clipped)==tuple(area))
            if full_map:
                visible=list(self._entries)
                ids=set()
            else:
                radius=max(e-w,n-s)/2
                candidates=self._index.nearby(-(s+n)/2,(w+e)/2,radius)
                ids={id(item) for item in candidates}
            if full_map:
                pass
            elif len(ids)*3<len(self._entries):
                # Small local pans on 100k-object MAP should not scan every
                # source object. Preserve original order by feature index.
                visible=sorted(
                    (entry for key in ids
                     if (entry:=self._entry_by_objid.get(key)) is not None
                     and _intersects(entry.bbox,clipped)),
                    key=lambda entry:int(entry.fid[1:]))
            else:
                visible=[entry for entry in self._entries
                         if id(entry.obj) in ids
                         and _intersects(entry.bbox,clipped)]
            total=len(visible)
            stack=self._overlay_uids()
            overlay_by_code={}
            rank={}
            for index,uid in enumerate(stack):
                obj=self._doc.by_id.get(uid)
                if obj is None or not obj.is_closed:
                    continue
                # Klucz po tożsamości obiektu, nie po uid: mapy po wielu
                # zapisach mają powtórzone uid-y i wtedy CAŁY stos był
                # pomijany, więc przesunięty poligon nie wycinał sąsiada.
                rank[id(obj)]=index
                overlay_by_code.setdefault(obj.code,[]).append(obj)
            return {
                "features":[self._feature(entry,
                    overlay_by_code.get(entry.obj.code,()),rank)
                    for entry in visible[offset:offset + limit]],
                "limited":total>offset+limit,"total":total,
            }

    def details(self, fid: str) -> dict:
        with self._lock:
            try:
                entry = self._lookup[fid]
            except KeyError as exc:
                raise LookupError("Nie znaleziono obiektu.") from exc
            obj = entry.obj
            fields = _inspector_fields(obj)
            return {
                "id": fid, "sourceUid": obj.uid, "code": obj.code,
                "layer": entry.layer, "grade": entry.grade,
                "fields": fields,
                "pointCount": len(obj.points),
                "points": [{"x": p.x, "y": p.y, "type": p.point_type}
                           for p in obj.points[:500]],
                "areaM2": obj.area_m2,
                "closed": obj.is_closed,
                "geometryTruncated": len(obj.points) > 500,
                "editableFields": [key for key in LABEL_FIELDS if key in fields]
                                  if obj.uid else [],
                "revision": self._revision,
                "documentToken": self._document_token,
            }


def _label_anchor(obj):
    """Match PySide6's centroid rather than an arbitrary bounding-box centre."""
    if obj.is_closed and len(obj.display_parts)>1:
        try:
            shape=geometry_of(obj)
            components=(list(shape.geoms) if shape.geom_type=="MultiPolygon"
                        else [shape])
            largest=max(components,key=lambda p:p.area)
            anchor=largest.representative_point()
            return anchor.x,anchor.y
        except ValueError:
            pass
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
