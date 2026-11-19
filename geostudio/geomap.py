"""Conservative, lossless-as-possible reader/editor for observed GEO-MAP v8 text files.

Never execute source file contents. The parser retains unknown records as bytes.
Byte-exact no-op save is supported; edited output is experimental until verified
by opening it with a licensed GEO-MAP installation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections import Counter
import hashlib
import re
import uuid

HEADER_RE = re.compile(rb"N=\[\s*\d+\]\s+CHK=\[[0-9a-fA-F]{32}\]")
STAR_RE = re.compile(rb"^\*(\d{4})\s+(.+?)\s*$")
POINT_RE = re.compile(rb"^P\s+(\d+)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)(.*)$")
FIELD_RE = re.compile(rb"^:([A-Za-z0-9]+)\[(.*)\](?:\r?\n)?$")
EXT_RE = re.compile(rb"^;# EXT\s+\S+\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)")


def decode(data: bytes) -> str:
    # Some original datasets contain undefined cp1250 bytes; don't destroy them.
    return data.decode("cp1250", errors="replace")


@dataclass(slots=True)
class GeoPoint:
    x: float
    y: float
    label: str = ""
    point_type: int = 1  # GEO-MAP P 0 ends a component; P 1 draws its contour


@dataclass(slots=True)
class GeoObject:
    code: str
    style: str
    start: int
    end: int
    uid: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    points: list[GeoPoint] = field(default_factory=list)

    @property
    def is_closed(self) -> bool:
        return len(self.points) >= 4 and abs(self.points[0].x-self.points[-1].x)<1e-7 and abs(self.points[0].y-self.points[-1].y)<1e-7

    @property
    def display_parts(self) -> list[list[GeoPoint]]:
        """Separate visible components at P 0 terminators (no connector to next P 1).

        A closing P 0 remains the endpoint of the preceding contour. Never
        change the underlying P records or their sequence.
        """
        parts: list[list[GeoPoint]] = []
        current: list[GeoPoint] = []
        for point in self.points:
            current.append(point)
            if point.point_type == 0:
                if len(current) >= 2:
                    parts.append(current)
                current = []
        if current:
            parts.append(current)
        return parts

    @property
    def area_m2(self) -> float | None:
        if not self.is_closed:
            return None
        pts = self.points
        # Translate to local origin to reduce catastrophic cancellation.
        x0, y0 = pts[0].x, pts[0].y
        total = sum((a.x-x0)*(b.y-y0)-(b.x-x0)*(a.y-y0) for a,b in zip(pts,pts[1:]))
        return abs(total)/2

    @property
    def colorref(self) -> tuple[int,int,int]:
        try: n = int(self.style.split()[0]); return (n & 255,(n>>8)&255,(n>>16)&255)
        except (IndexError,ValueError): return (55,73,97)


class GeoMap:
    """Stores source bytes per line; existing unrelated records remain unchanged."""
    def __init__(self, source: bytes, *, filename: str = ""):
        self.filename = filename
        self.lines: list[bytes] = source.splitlines(keepends=True)
        self.objects: list[GeoObject] = []
        self.by_id: dict[str, GeoObject] = {}
        self._parse()

    @classmethod
    def open(cls, path: str | Path) -> "GeoMap":
        p=Path(path)
        return cls(p.read_bytes(),filename=str(p))

    def _parse(self):
        self.objects=[]; self.by_id={}
        obj: GeoObject | None=None
        for i, original in enumerate(self.lines):
            line=original.rstrip(b'\r\n')
            star=STAR_RE.match(line)
            if star:
                if obj is not None: obj.end=i
                obj=GeoObject(decode(star.group(1)),decode(star.group(2)),i,len(self.lines))
                self.objects.append(obj)
                continue
            if obj is None: continue
            field_match=FIELD_RE.match(line)
            if field_match:
                k=decode(field_match.group(1)); val=decode(field_match.group(2))
                obj.fields[k]=val
                if k=='ID': obj.uid=val; self.by_id[obj.uid]=obj
                continue
            point=POINT_RE.match(line)
            if point:
                label=decode(point.group(4)).strip()
                if label.startswith(','): label=label[1:].strip()
                obj.points.append(GeoPoint(float(point.group(2)),float(point.group(3)),label,int(point.group(1))))

    @property
    def checksum_valid(self) -> bool:
        if not self.lines: return False
        m=re.search(rb"CHK=\[([0-9a-fA-F]{32})\]",self.lines[0])
        if not m: return False
        return hashlib.md5(b''.join(self.lines[1:])).hexdigest().lower()==m.group(1).decode().lower()

    @property
    def declared_lines(self) -> int | None:
        if not self.lines: return None
        m=re.search(rb"N=\[\s*(\d+)\]",self.lines[0])
        return int(m.group(1)) if m else None

    @property
    def declared_extent(self) -> tuple[float,float,float,float] | None:
        if len(self.lines)<2: return None
        m=EXT_RE.match(self.lines[1])
        return tuple(float(x) for x in m.groups()) if m else None

    def summary(self):
        all_pts=[p for o in self.objects for p in o.points]
        ext=(min(p.x for p in all_pts),min(p.y for p in all_pts),max(p.x for p in all_pts),max(p.y for p in all_pts)) if all_pts else None
        return {"filename": self.filename, "lines":len(self.lines),"declared_lines":self.declared_lines,
                "checksum_valid":self.checksum_valid,"objects":len(self.objects),
                "vertices":len(all_pts), "closed_polygons":sum(o.is_closed for o in self.objects),
                "codes":dict(Counter(o.code for o in self.objects).most_common()),
                "extent":ext,"declared_extent":self.declared_extent}

    def update_field(self, uid: str, key: str, value: str):
        if key not in {'A1','A2','A3','A4','A5','A6','TX','MP','KR'}:
            raise ValueError('Only known editable attributes are supported')
        if any(c in value for c in '\r\n]'):
            raise ValueError('Field values may not include newlines or closing brackets')
        if uid not in self.by_id: raise KeyError(uid)
        obj=self.by_id[uid]
        replacement=(f':{key}[{value}]\r\n').encode('cp1250',errors='strict')
        for i in range(obj.start+1,obj.end):
            if self.lines[i].startswith(f':{key}['.encode()):
                orig=self.lines[i]
                eol=b'\r\n' if orig.endswith(b'\r\n') else b'\n' if orig.endswith(b'\n') else b''
                self.lines[i]=replacement.rstrip(b'\r\n')+eol
                self._parse(); return
        insertion=obj.start+1
        for i in range(obj.start+1,obj.end):
            if self.lines[i].startswith(b'P '): insertion=i;break
        self.lines.insert(insertion,replacement)
        self._parse()

    def bulk_update_fields(self, values: dict[tuple[str, str], str]):
        """Apply multiple existing-attribute changes atomically, with one parse.

        Only replaces fields that already exist: a substring-replacement
        command never creates new attributes and never touches unrelated
        GEO-MAP records. Validation and cp1250 encoding are completed before
        modifying source lines.
        """
        allowed = {'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'TX', 'MP', 'KR'}
        pending: dict[int, bytes] = {}
        for (uid, field), value in values.items():
            if field not in allowed or not isinstance(value, str):
                raise ValueError('Unsupported replacement field')
            if any(c in value for c in '\r\n]'):
                raise ValueError('Replacement may not contain newlines or closing brackets')
            obj = self.by_id[uid]
            prefix = f':{field}['.encode('ascii')
            found = False
            for line_no in range(obj.start + 1, obj.end):
                original = self.lines[line_no]
                if not original.startswith(prefix):
                    continue
                eol = (b'\r\n' if original.endswith(b'\r\n') else
                       b'\n' if original.endswith(b'\n') else b'')
                pending[line_no] = prefix + value.encode('cp1250', errors='strict') + b']' + eol
                found = True
                break
            if not found:
                raise ValueError('Attribute does not exist in GEO-MAP record')
        for line_no, content in pending.items():
            self.lines[line_no] = content
        if pending:
            self._parse()

    def move_polygon_vertices(self, changes: dict[str, dict[int, tuple[float, float]]], *, reparse: bool = True):
        """Move one or more polygon vertices atomically with only ONE parse.

        Validate every resulting ring before touching raw MAP lines. Unrelated
        source bytes, native per-vertex flags and line endings remain unchanged.
        A closed ring's last duplicate is moved with its first vertex.
        """
        from math import isfinite
        from .interactions import polygon_is_valid
        pending: dict[int, bytes] = {}
        for uid, replacements in changes.items():
            obj = self.by_id[uid]
            if not obj.is_closed:
                raise ValueError('Only closed polygons can be edited')
            size = len(obj.points) - 1
            coords = [(p.x, p.y) for p in obj.points[:-1]]
            for index, value in replacements.items():
                if not 0 <= index < size:
                    raise IndexError('Vertex outside polygon')
                x, y = value
                if not (isfinite(x) and isfinite(y) and -1e9 < x < 1e9 and -1e9 < y < 1e9):
                    raise ValueError('Invalid coordinates')
                coords[index] = (x, y)
            if not polygon_is_valid(coords):
                raise ValueError('Polygon must have three distinct non-collinear vertices')
            # In topology mode collapsing an existing distinct corner onto
            # another vertex would create a zero-length edge. Even though the
            # signed area might stay nonzero, do not silently corrupt a ring.
            before = [(p.x, p.y) for p in obj.points[:-1]]
            if len(set(before)) == len(before) and len(set(coords)) < len(coords):
                raise ValueError('The edit would collapse two distinct polygon vertices')
            records = [(i, POINT_RE.match(raw.rstrip(b'\r\n')))
                       for i, raw in enumerate(self.lines[obj.start+1:obj.end], obj.start+1)]
            records = [(i, match) for i, match in records if match]
            if len(records) != len(obj.points):
                raise ValueError('Unexpected P record count; refusing to edit')
            expanded = dict(replacements)
            if 0 in replacements:
                expanded[size] = replacements[0]
            for index, (x, y) in expanded.items():
                line_no, match = records[index]
                original = self.lines[line_no]
                eol = b'\r\n' if original.endswith(b'\r\n') else (
                    b'\n' if original.endswith(b'\n') else b'')
                prefix = original[:match.start(2)]
                suffix = match.group(4)
                pending[line_no] = (prefix + f'{x:.3f}'.encode() + b'   ' +
                                    f'{y:.3f}'.encode() + suffix + eol)
        for line_no, replacement in pending.items():
            self.lines[line_no] = replacement
        if pending:
            if reparse:
                self._parse()
            else:
                # Fast UI path: these edits change only existing P coordinates,
                # so keep all original GeoObject instances and update the
                # affected points in place. Undo/redo may still reparse fully.
                for uid, replacements in changes.items():
                    obj = self.by_id[uid]
                    for index, (x, y) in replacements.items():
                        obj.points[index].x = round(x, 3)
                        obj.points[index].y = round(y, 3)
                        if index == 0:
                            obj.points[-1].x = round(x, 3)
                            obj.points[-1].y = round(y, 3)

    def move_polygon_vertex(self, uid: str, vertex_index: int, x: float, y: float):
        """Move one polygon vertex, preserving the original P record format."""
        self.move_polygon_vertices({uid: {vertex_index: (x, y)}})

    def insert_polygon_vertex(self, uid: str, segment_index: int, x: float, y: float):
        """Split a polygon edge by inserting one GEO-MAP P record.

        Other bytes, including all attributes, identifiers, point labels,
        styles and unknown records, are left untouched. The inserted point
        must lie on the selected segment to millimetre precision.
        """
        from math import hypot, isfinite
        from .interactions import closest_point_on_edge, polygon_is_valid
        if uid not in self.by_id:
            raise KeyError(uid)
        obj = self.by_id[uid]
        if not obj.is_closed:
            raise ValueError('Only closed polygons can be edited')
        if not 0 <= segment_index < len(obj.points) - 1:
            raise IndexError('Segment outside polygon')
        if not all(isfinite(v) for v in (x, y)):
            raise ValueError('Invalid coordinates')
        a, b = obj.points[segment_index:segment_index + 2]
        px, py = closest_point_on_edge(x, y, a.x, a.y, b.x, b.y)
        if hypot(x - px, y - py) > 0.005:
            raise ValueError('New vertex must be on the selected edge')
        x, y = round(px, 3), round(py, 3)
        if min(hypot(x-a.x, y-a.y), hypot(x-b.x, y-b.y)) < 0.002:
            raise ValueError('New vertex is too close to an existing vertex')
        coords = [(p.x, p.y) for p in obj.points[:-1]]
        coords.insert(segment_index+1, (x, y))
        if not polygon_is_valid(coords):
            raise ValueError('Resulting polygon is invalid')
        record_lines = [(i, POINT_RE.match(raw.rstrip(b'\r\n')))
                        for i, raw in enumerate(self.lines[obj.start+1:obj.end],obj.start+1)]
        record_lines = [(i, m) for i, m in record_lines if m]
        if len(record_lines) != len(obj.points):
            raise ValueError('Unexpected P record count; refusing to insert')
        before_line, before_match = record_lines[segment_index]
        after_line, _ = record_lines[segment_index+1]
        before = self.lines[before_line]
        eol = b'\r\n' if before.endswith(b'\r\n') else b'\n'
        point_type = before_match.group(1).decode('ascii')
        new_line = f'P {point_type}   {x:.3f}   {y:.3f}'.encode('ascii') + eol
        self.lines.insert(after_line, new_line)
        self._parse()

    def delete_polygon_vertices(self, removals: dict[str, set[int]]) -> None:
        """Atomically delete P records from closed GEO-MAP polygon rings.

        Never remove the final 3 independent corners. For the first vertex
        update the duplicated closing P coordinates to the new first corner.
        All preflight checks run BEFORE mutating raw map lines, including
        rejecting a new edge crossing any existing non-adjacent edge.
        Vertex flags, other fields, and unknown records remain intact.
        """
        from .interactions import polygon_is_valid

        if not removals:
            raise ValueError("Nie wskazano żadnego węzła.")
        pending_deletes: set[int] = set()
        pending_rewrites: dict[int, bytes] = {}

        def intersects(a, b, c, d) -> bool:
            def cross(p, q, r):
                return (q[0] - p[0]) * (r[1] - p[1]) - (
                    q[1] - p[1]) * (r[0] - p[0])

            def on_segment(p, q, r):
                return (min(p[0], r[0]) - 1e-9 <= q[0] <= max(p[0], r[0]) + 1e-9
                        and min(p[1], r[1]) - 1e-9 <= q[1] <= max(p[1], r[1]) + 1e-9)
            s1, s2 = cross(a, b, c), cross(a, b, d)
            s3, s4 = cross(c, d, a), cross(c, d, b)
            if s1 * s2 < -1e-18 and s3 * s4 < -1e-18:
                return True
            return ((abs(s1) <= 1e-9 and on_segment(a, c, b)) or
                    (abs(s2) <= 1e-9 and on_segment(a, d, b)) or
                    (abs(s3) <= 1e-9 and on_segment(c, a, d)) or
                    (abs(s4) <= 1e-9 and on_segment(c, b, d)))

        for uid, indices in removals.items():
            if not isinstance(indices, set) or len(indices) != 1:
                raise ValueError("Usuwanie obejmuje jeden węzeł w każdym poligonie.")
            obj = self.by_id.get(uid)
            if obj is None or not obj.is_closed:
                raise ValueError("Usuwanie wymaga zamkniętego poligonu z ID.")
            size = len(obj.points) - 1
            index = next(iter(indices))
            if type(index) is not int or not 0 <= index < size:
                raise ValueError("Nieprawidłowy numer węzła.")
            if size <= 3:
                raise ValueError("Poligon musi zachować co najmniej 3 wierzchołki.")
            if any(point.point_type == 0 for point in obj.points[:-1]):
                raise ValueError("Usuwanie węzłów poligonów wieloczęściowych jest zablokowane.")

            original = [(p.x, p.y) for p in obj.points[:-1]]
            remaining = original[:index] + original[index + 1:]
            if len(set(remaining)) != len(remaining) or not polygon_is_valid(remaining):
                raise ValueError("Usunięcie węzła stworzyłoby nieprawidłowy poligon.")
            ax, bx = original[(index - 1) % size], original[(index + 1) % size]
            for j in range(len(remaining)):
                c, d = remaining[j], remaining[(j + 1) % len(remaining)]
                # Only the newly-created connecting edge needs checking.
                if c in (ax, bx) or d in (ax, bx):
                    continue
                if intersects(ax, bx, c, d):
                    raise ValueError("Usunięcie węzła przecięłoby inną krawędź.")

            matches = [(line_no, POINT_RE.match(raw.rstrip(b"\r\n")))
                       for line_no, raw in enumerate(
                           self.lines[obj.start + 1:obj.end], obj.start + 1)]
            matches = [(line_no, match) for line_no, match in matches if match]
            if len(matches) != len(obj.points):
                raise ValueError("Nieoczekiwana liczba rekordów P.")
            pending_deletes.add(matches[index][0])

            if index == 0:
                # GEO-MAP's last P duplicates the first. Removing first P
                # without rewriting this closure would leave an open ring.
                close_line_no, close_match = matches[-1]
                original_close = self.lines[close_line_no]
                eol = (b"\r\n" if original_close.endswith(b"\r\n")
                       else b"\n" if original_close.endswith(b"\n") else b"")
                x, y = remaining[0]
                pending_rewrites[close_line_no] = (
                    original_close[:close_match.start(2)]
                    + f"{x:.3f}".encode("ascii") + b"   "
                    + f"{y:.3f}".encode("ascii")
                    + close_match.group(4) + eol
                )

        for line_no, content in pending_rewrites.items():
            if line_no in pending_deletes:
                raise ValueError("Niejednoznaczne rekordy P.")
            self.lines[line_no] = content
        for line_no in sorted(pending_deletes, reverse=True):
            del self.lines[line_no]
        self._parse()

    def duplicate_polygons(self, uids: list[str], dx: float, dy: float) -> list[str]:
        """Copy full native records, changing ONLY :ID and P coordinates.

        Existing style, A-fields, unknown attributes and P flags are retained.
        The original source object records remain byte-identical.
        """
        from math import isfinite
        if not uids or len(set(uids)) != len(uids):
            raise ValueError("Choose distinct polygons to duplicate")
        if not all(isfinite(v) and -1e9<v<1e9 for v in (dx,dy)):
            raise ValueError("Invalid copy offset")
        raw_records=[]
        new_uids=[]
        existing=set(self.by_id)
        for uid in uids:
            obj=self.by_id[uid]
            if not obj.is_closed:
                raise ValueError("Only closed polygons may be duplicated")
            new_uid=str(uuid.uuid4()).upper()
            while new_uid in existing:
                new_uid=str(uuid.uuid4()).upper()
            existing.add(new_uid)
            new_uids.append(new_uid)
            found_id=False
            records=[]
            point_count=0
            for raw in self.lines[obj.start:obj.end]:
                eol = b'\r\n' if raw.endswith(b'\r\n') else (
                    b'\n' if raw.endswith(b'\n') else b'')
                text=raw.rstrip(b'\r\n')
                if text.startswith(b':ID['):
                    if found_id:
                        raise ValueError("Duplicate ID records in source")
                    text=b':ID['+new_uid.encode('ascii')+b']'
                    found_id=True
                else:
                    point=POINT_RE.match(text)
                    if point:
                        x=round(float(point.group(2))+dx,3)
                        y=round(float(point.group(3))+dy,3)
                        if not (-1e9<x<1e9 and -1e9<y<1e9):
                            raise ValueError("Copied point outside coordinate bounds")
                        # Retain the P flag and any native trailing notes.
                        text=(text[:point.start(2)]+f'{x:.3f}'.encode('ascii')+
                              b'   '+f'{y:.3f}'.encode('ascii')+point.group(4))
                        point_count+=1
                records.append(text+eol)
            if not found_id or point_count != len(obj.points):
                raise ValueError("Malformed source polygon: copying refused")
            raw_records.extend(records)
        if self.lines and not self.lines[-1].endswith((b'\r',b'\n')):
            self.lines[-1]+=b'\r\n'
        self.lines.extend(raw_records)
        self._parse()
        return new_uids

    def delete_objects(self, uids: list[str] | set[str]) -> int:
        """Delete entire object records in one pass without touching adjacent objects.

        This is significantly faster than reparsing a 100k-line map for every
        selected object. Unknown and non-object source records are preserved.
        """
        ids = set(uids)
        if not ids:
            return 0
        missing = ids.difference(self.by_id)
        if missing:
            raise KeyError(next(iter(missing)))
        intervals = sorted((self.by_id[uid].start, self.by_id[uid].end) for uid in ids)
        kept = []
        cursor = 0
        for start, end in intervals:
            if start < cursor or end > len(self.lines):
                raise ValueError("Overlapping or malformed object boundaries")
            kept.extend(self.lines[cursor:start])
            cursor = end
        kept.extend(self.lines[cursor:])
        self.lines = kept
        self._parse()
        return len(ids)

    def delete_object(self, uid: str) -> None:
        self.delete_objects([uid])

    @staticmethod
    def signed_area(points: list[tuple[float,float]]) -> float:
        """Stable signed planar area; native GEO-MAP expects positive exterior."""
        if len(points)<3:
            return 0.
        x0,y0=points[0]
        return sum(((x-x0)*(yn-y0)-(xn-x0)*(y-y0))
                   for (x,y),(xn,yn) in zip(points,points[1:]+points[:1]))/2

    def to_bytes_positive_areas(self) -> bytes:
        """Export new MAP with positive-oriented SIMPLE exterior rings.

        Preserve all non-P records, CP1250 data, and every polyline verbatim.
        Do not rewrite multi-ring P0 objects: their winding can mark holes.
        Also does not mutate the in-memory editable source or history.
        """
        pending={}
        for obj in self.objects:
            if (not obj.is_closed or len(obj.points)<4 or
                    any(p.point_type!=1 for p in obj.points)):
                continue
            coords=[(p.x,p.y) for p in obj.points[:-1]]
            if self.signed_area(coords)>=0:
                continue
            indices=[i for i in range(obj.start+1,obj.end)
                     if POINT_RE.match(self.lines[i].rstrip(b'\r\n'))]
            if len(indices)!=len(obj.points):
                raise ValueError("Nie można bezpiecznie zmienić kolejności punktów.")
            records=[self.lines[i] for i in indices]
            flipped=[records[0],*reversed(records[1:-1]),records[-1]]
            for index,record in zip(indices,flipped):
                pending[index]=record
        if not pending:
            return self.to_bytes()
        clone=GeoMap(b''.join(self.lines),filename=self.filename)
        for index,record in pending.items():
            clone.lines[index]=record
        clone._parse()
        return clone.to_bytes()

    def append_polygon(self, points: list[tuple[float,float]], code='5216',
                       label='', fields: dict[str, str] | None = None) -> str:
        if len(points) < 3:
            raise ValueError('A polygon needs at least three vertices')
        if not re.fullmatch(r'\d{4}', code):
            raise ValueError('Code must have exactly four digits')
        from math import isfinite
        if any(not (isfinite(x) and isfinite(y) and -1e9 < x < 1e9 and -1e9 < y < 1e9)
               for x, y in points):
            raise ValueError('Invalid coordinates')
        if points[0] != points[-1]:
            points = points + [points[0]]
        if self.signed_area(points[:-1])<0:
            points = [points[0], *reversed(points[1:-1]), points[0]]
        attrs = dict(fields or {})
        if label and 'A2' not in attrs:
            attrs['A2'] = label
        allowed = {'A1','A2','A3','A4','A5','A6','TX','MP','DT','KR'}
        if any(key not in allowed for key in attrs):
            raise ValueError('Unsupported new-object attribute')
        # Validate and encode before mutating the map.
        for value in attrs.values():
            if any(ch in value for ch in '\r\n]'):
                raise ValueError('Attributes cannot include a newline or ]')
        uid = str(uuid.uuid4()).upper()
        records = [f'*{code} 8553090  15          0', f':ID[{uid}]']
        for key in ('A1','A2','A3','A4','A5','A6','TX','MP','DT','KR'):
            if key in attrs:
                records.append(f':{key}[{attrs[key]}]')
        if 'MP' not in attrs:
            records.append(':MP[0]')
        records.append(':FA[-1]')
        records.extend(f'P 1   {x:.3f}   {y:.3f}' for x, y in points)
        encoded = [(line + '\r\n').encode('cp1250', errors='strict') for line in records]
        if self.lines and not self.lines[-1].endswith((b'\r', b'\n')):
            self.lines[-1] += b'\r\n'
        self.lines.extend(encoded)
        self._parse()
        return uid

    def append_polyline(self, points: list[tuple[float, float]], code='6900',
                        label='', fields: dict[str, str] | None = None) -> str:
        """Create a real open GEO-MAP line (no automatic polygon closure).

        Attribute and P-record preservation follows append_polygon, but a
        polyline needs only two distinct positions and may be collinear.
        """
        from math import isfinite
        if len(points) < 2 or len(set(points)) < 2:
            raise ValueError('Linia wymaga co najmniej dwóch różnych punktów.')
        if not re.fullmatch(r'\d{4}', code):
            raise ValueError('Code must have exactly four digits')
        if any(not (isfinite(x) and isfinite(y) and -1e9 < x < 1e9 and
                    -1e9 < y < 1e9) for x, y in points):
            raise ValueError('Invalid coordinates')
        if any(a == b for a, b in zip(points, points[1:])):
            raise ValueError('Linia nie może mieć kolejnych identycznych punktów.')
        attrs = dict(fields or {})
        if label and 'A2' not in attrs:
            attrs['A2'] = label
        allowed = {'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'TX', 'MP', 'DT', 'KR'}
        if any(key not in allowed for key in attrs):
            raise ValueError('Unsupported new-object attribute')
        if any(any(char in value for char in '\r\n]') for value in attrs.values()):
            raise ValueError('Attributes cannot include a newline or ]')
        uid = str(uuid.uuid4()).upper()
        records = [f'*{code} 8553090  15          0', f':ID[{uid}]']
        for key in ('A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'TX', 'MP', 'DT', 'KR'):
            if key in attrs:
                records.append(f':{key}[{attrs[key]}]')
        if 'MP' not in attrs:
            records.append(':MP[0]')
        records.append(':FA[-1]')
        records.extend(f'P 1   {x:.3f}   {y:.3f}' for x, y in points)
        encoded = [(line + '\r\n').encode('cp1250', errors='strict')
                   for line in records]
        if self.lines and not self.lines[-1].endswith((b'\r', b'\n')):
            self.lines[-1] += b'\r\n'
        self.lines.extend(encoded)
        self._parse()
        return uid

    def to_bytes(self) -> bytes:
        if not self.lines: raise ValueError('Empty map')
        # N is number of physical lines. CHK is MD5 of all bytes after first line.
        body=b''.join(self.lines[1:]); digest=hashlib.md5(body).hexdigest().encode()
        first=self.lines[0]
        if not HEADER_RE.search(first):raise ValueError('Unrecognized GEO-MAP header; refusing to write')
        first=re.sub(rb'N=\[\s*\d+\]',b'N=['+f'{len(self.lines):12d}'.encode()+b']',first,count=1)
        first=re.sub(rb'CHK=\[[0-9a-fA-F]{32}\]',b'CHK=['+digest+b']',first,count=1)
        return first+body

    def save_as(self, path: str | Path):
        target=Path(path)
        if target.exists():raise FileExistsError('Choose a new filename; original maps are never overwritten')
        target.write_bytes(self.to_bytes())


def library_symbols(path: str | Path) -> dict[str,str]:
    out={}
    for line in Path(path).read_bytes().decode('cp1250',errors='replace').splitlines():
        m=re.match(r'^\*(\d{4})\s+(.*)',line)
        if m:out[m.group(1)]=m.group(2).strip()
    return out


def library_layers(path: str | Path) -> tuple[list[str],dict[str,str]]:
    names=[]; codes={}; current='Pozostałe'
    for line in Path(path).read_bytes().decode('cp1250',errors='replace').splitlines():
        if line.startswith(';'):continue
        group=re.match(r'^\*\s+\S+\s+\S+\s+"([^"]+)"',line)
        if group:
            current=group.group(1)
            if current not in names:names.append(current)
            continue
        m=re.match(r'^\s*([0-9?]{4})\s+',line)
        if m:codes[m.group(1)]=current
    return names,codes


def library_colors(path: str | Path) -> dict[str,tuple[int,int,int]]:
    out={}
    for line in Path(path).read_bytes().decode('cp1250',errors='replace').splitlines():
        if not line or line.startswith(';'): continue
        toks=line.split()
        if len(toks)>=9:
            try:
                out[toks[0]]=tuple(int(t) for t in toks[1:4])
            except ValueError:continue
    return out


def resolve_layer(catalog: dict[str,str], code: str) -> str:
    """Exact or GEO-MAP '?' wildcard matching, most-specific rule first."""
    if code in catalog: return catalog[code]
    matching=[(key,name) for key,name in catalog.items()
              if '?' in key and len(key)==len(code)
              and all(a=='?' or a==b for a,b in zip(key,code))]
    if not matching:return 'Inne / kod '+code
    matching.sort(key=lambda entry:entry[0].count('?'))
    return matching[0][1]
