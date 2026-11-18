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

    def move_polygon_vertex(self, uid: str, vertex_index: int, x: float, y: float):
        """Edit one vertex in-place, preserving the original P record's suffix.

        For closed rings the duplicated first/last vertex is updated together.
        Non-geometry records, point labels and line endings remain untouched.
        """
        from math import isfinite
        if uid not in self.by_id:
            raise KeyError(uid)
        obj = self.by_id[uid]
        if not obj.is_closed:
            raise ValueError('Only closed polygons can be edited')
        if not (isfinite(x) and isfinite(y) and -1e9 < x < 1e9 and -1e9 < y < 1e9):
            raise ValueError('Invalid coordinates')
        distinct_count = len(obj.points) - 1
        if not 0 <= vertex_index < distinct_count:
            raise IndexError('Vertex outside polygon')
        from .interactions import polygon_is_valid
        coords = [(p.x, p.y) for p in obj.points[:-1]]
        coords[vertex_index] = (x, y)
        if not polygon_is_valid(coords):
            raise ValueError('Polygon must have at least three distinct non-collinear vertices')
        records = [(i, POINT_RE.match(raw.rstrip(b'\r\n')))
                   for i, raw in enumerate(self.lines[obj.start+1:obj.end], obj.start+1)]
        records = [(i, m) for i, m in records if m]
        if len(records) != len(obj.points):
            raise ValueError('Unexpected P record count; refusing to edit')
        indices = [vertex_index]
        if vertex_index == 0:
            indices.append(distinct_count)
        for pos in indices:
            line_no, match = records[pos]
            original = self.lines[line_no]
            eol = b'\r\n' if original.endswith(b'\r\n') else b'\n' if original.endswith(b'\n') else b''
            # Keep P type, optional comma labels, flags, and line ending intact.
            prefix = original[:match.start(2)]
            suffix = match.group(4)
            self.lines[line_no] = prefix + f'{x:.3f}'.encode() + b'   ' + f'{y:.3f}'.encode() + suffix + eol
        self._parse()

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

    def append_geometry(self, points: list[tuple[float, float]], code: str,
                        *, kind: str = 'line',
                        fields: dict[str, str] | None = None) -> str:
        """Append an experimental open line or a point, preserving source records.

        GEO-MAP uses P 0 at the end of an open component. For line/text codes,
        reuse a style header from an existing object of the *same code* when
        available; unknown codes fall back to the existing generic header.
        Original source records are never rewritten.
        """
        if kind == 'polygon':
            return self.append_polygon(points, code, fields=fields)
        if kind not in {'line', 'point'}:
            raise ValueError('Geometry must be point, line or polygon')
        if not re.fullmatch(r'\d{4}', code):
            raise ValueError('Code must have exactly four digits')
        from math import isfinite
        if len(points) < (2 if kind == 'line' else 1):
            raise ValueError('An open line requires two vertices; a point requires one')
        if kind == 'point' and len(points) != 1:
            raise ValueError('A point must have exactly one vertex')
        if len(set(points)) < (2 if kind == 'line' else 1):
            raise ValueError('Geometry must contain distinct vertices')
        if any(not (isfinite(x) and isfinite(y) and -1e9 < x < 1e9 and -1e9 < y < 1e9)
               for x, y in points):
            raise ValueError('Invalid coordinates')
        attrs = dict(fields or {})
        allowed = {'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'TX', 'MP', 'DT', 'KR'}
        if any(key not in allowed for key in attrs):
            raise ValueError('Unsupported new-object attribute')
        for value in attrs.values():
            if not isinstance(value, str) or any(ch in value for ch in '\r\n]'):
                raise ValueError('Invalid attribute; use one line without ]')
        uid = str(uuid.uuid4()).upper()
        template = next((obj.style for obj in self.objects if obj.code == code), None)
        style = template if template is not None else '8553090  15          0'
        records = [f'*{code} {style}', f':ID[{uid}]']
        for key in ('A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'TX', 'MP', 'DT', 'KR'):
            if key in attrs:
                records.append(f':{key}[{attrs[key]}]')
        for i, (x, y) in enumerate(points):
            point_type = 0 if kind == 'line' and i == len(points) - 1 else 1
            records.append(f'P {point_type}   {x:.3f}   {y:.3f}')
        encoded = [(line + '\r\n').encode('cp1250', errors='strict') for line in records]
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
