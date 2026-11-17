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
                obj.points.append(GeoPoint(float(point.group(2)),float(point.group(3)),label))

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

    def append_polygon(self, points: list[tuple[float,float]], code='5216', label='') -> str:
        if len(points)<3:raise ValueError('A polygon needs at least three vertices')
        if not re.fullmatch(r'\d{4}',code):raise ValueError('Code must have exactly four digits')
        if any(not (-1e9<x<1e9 and -1e9<y<1e9) for x,y in points):
            raise ValueError('Invalid coordinates')
        if points[0]!=points[-1]: points=points+[points[0]]
        uid=str(uuid.uuid4()).upper()
        # Based on observed GEO-MAP v8 record layout. Experimental until roundtrip tested.
        records=[f'*{code} 8553090  15          0',f':ID[{uid}]']
        if label: records.append(f':A2[{label}]')
        records.extend([':MP[0]',':FA[-1]'])
        records.extend(f'P 1   {x:.3f}   {y:.3f}' for x,y in points)
        if self.lines and not self.lines[-1].endswith((b'\r',b'\n')):
            self.lines[-1]+=b'\r\n'
        self.lines.extend((x+'\r\n').encode('cp1250',errors='strict') for x in records)
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
