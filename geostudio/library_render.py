"""Partial, data-driven renderer support for GEO-MAP libraries (Windows-1250).

CDF encodes fill RGB, hatch index, border RGB, and border width. LAY includes
drawing-code color/pen settings. SYM contains drawing instructions, not only
human names. Unknown primitives remain intentionally unrendered until verified.
No proprietary library contents are included in the project repository.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import fnmatch
import re


@dataclass(frozen=True)
class CDFStyle:
    fill: tuple[int,int,int]
    hatch: int
    border: tuple[int,int,int]
    width: float


@dataclass(frozen=True)
class SymbolPrimitive:
    kind: str
    parameters: tuple[float, ...]


def _library_lines(source: str | Path | bytes) -> list[str]:
    """Both desktop libraries and browser-selected in-memory CP1250 libraries.

    Never interpret arbitrary library text as executable instructions.
    """
    raw=source if isinstance(source,bytes) else Path(source).read_bytes()
    if len(raw)>8*1024*1024:
        raise ValueError("Biblioteka GEO-MAP jest większa niż 8 MB.")
    return raw.decode("cp1250",errors="replace").splitlines()


def parse_cdf(path: str | Path | bytes) -> dict[str,CDFStyle]:
    styles = {}
    for line in _library_lines(path):
        line=line.strip()
        if not line or line.startswith(';'):
            continue
        parts = line.split()
        if len(parts) < 9:
            continue
        try:
            rgb=tuple(int(n) for n in parts[1:4])
            hatch=int(parts[4])
            border=tuple(int(n) for n in parts[5:8])
            width=float(parts[8])
        except ValueError:
            continue
        if (len(rgb)!=3 or len(border)!=3 or
            any(n<0 or n>255 for n in (*rgb, *border)) or not 0<=hatch<=16):
            continue
        styles[parts[0]] = CDFStyle(rgb,hatch,border,width)
    return styles


def cdf_for_object(styles: dict[str,CDFStyle], code: str,
                   a1: str='', a2: str='') -> CDFStyle | None:
    """Match only documented-looking CODE(.A1)(.A2) selectors.

    Avoid interpreting unrelated CDF entries (e.g. '5221.Ls') as a style
    for GEO-MAP object 5220. Wildcards are matched against exact variants.
    """
    values=[code]
    if a2: values.append(f'{code}.{a2}')
    if a1: values.append(f'{code}.{a1}')
    if a1 and a2: values.append(f'{code}.{a1}.{a2}')
    for value in reversed(values):
        if value in styles:
            return styles[value]
    for value in reversed(values):
        matched=[(key,style) for key,style in styles.items()
                 if ('?' in key or '*' in key) and fnmatch.fnmatchcase(value,key)]
        if matched:
            matched.sort(key=lambda p:sum(c in '?*' for c in p[0]))
            return matched[0][1]
    return None


def native_fill_color(style: str) -> tuple[int,int,int] | None:
    """Third map style token is an optional COLORREF on observed v8 records.

    It is not always present or meaningful: never infer a fill from zero.
    """
    tokens=style.split()
    if len(tokens)<3:
        return None
    try:
        n=int(tokens[2])
    except ValueError:
        return None
    if not 0<n<=0xFFFFFF:
        return None
    return (n&255,(n>>8)&255,(n>>16)&255)


def parse_sym_primitives(path: str | Path | bytes) -> dict[str,list[SymbolPrimitive]]:
    """Load simple primitives; keep O/T/arc instructions for future renderers."""
    result={}
    current=None
    for line in _library_lines(path):
        if line.startswith('*') and len(line)>4 and line[1:5].isdigit():
            current=line[1:5]
            result[current]=[]
            continue
        if current is None or not line.strip() or line.lstrip().startswith(';'):
            continue
        parts=line.split()
        if not parts or parts[0] not in {'L','V','A','T','O','I','S','P'}:
            continue
        try:
            params=tuple(float(v) for v in parts[1:7])
        except ValueError:
            continue
        if len(params)==6:
            result[current].append(SymbolPrimitive(parts[0],params))
    return result


def simple_point_segments(primitives: list[SymbolPrimitive]) -> list[tuple[float,float,float,float]]:
    """Return only directly understood L straight segments.

    GEO-MAP L X1 Y1 X2 Y2 ... is used for symbol marks; skip recursive O
    and annotation T until their semantics and print scaling are verified.
    """
    return [(p.parameters[0],p.parameters[1],p.parameters[2],p.parameters[3])
            for p in primitives if p.kind=='L' and
            (p.parameters[0],p.parameters[1])!=(p.parameters[2],p.parameters[3])]


@dataclass(frozen=True)
class LAYPenStyle:
    """Layer line color and basic pattern ID as recorded in .LAY."""
    colorref: int
    line_id: str
    width_mm: float


def parse_lay_pen_styles(path: str | Path | bytes) -> dict[str,LAYPenStyle]:
    """Parse named GEO-MAP overlay codes without modifying the .LAY library.

    Standard rows:  5220 32768 2.008 1 standard 2.5 ...
    2.008 represents the line catalogue ID; exact visual parity still needs
    its own line-pattern definition. Only known 008 is drawn dashed.
    """
    result={}
    for line in _library_lines(path):
        if not line.strip() or line.lstrip().startswith((';','*')):
            continue
        match=re.match(r'^\s*([0-9?]{4})\s+(\d+)\s+([0-9]+\.[0-9]+)\s+\d+\s+\S+\s+([\d.]+)',line)
        if not match:
            continue
        code, colorref, line_id, width = match.groups()
        try:
            result[code]=LAYPenStyle(int(colorref),line_id,float(width))
        except ValueError:
            continue
    return result


def lay_for_code(styles: dict[str,LAYPenStyle],code: str) -> LAYPenStyle|None:
    if code in styles:
        return styles[code]
    candidates=[(pattern, value) for pattern,value in styles.items()
                if len(pattern)==len(code)
                and '?' in pattern
                and all(a=='?' or a==b for a,b in zip(pattern,code))]
    if not candidates:
        return None
    return sorted(candidates,key=lambda pair:pair[0].count('?'))[0][1]


def simple_point_circles(primitives: list[SymbolPrimitive]) -> list[tuple[float,float,float]]:
    """Render verified full-circle A instructions for point symbols.

    A centreX centreY radiusX radiusY startAngle endAngle.
    Unknown arc geometries are NOT approximated.
    """
    result=[]
    for primitive in primitives:
        if primitive.kind != 'A':
            continue
        cx,cy,rx,ry,start,end=primitive.parameters
        if abs(start)<1e-5 and abs(end-360)<1e-5 and rx>0 and abs(ry)<1e-5:
            result.append((cx,cy,rx))
    return result


def parse_sym_line_patterns(path: str | Path | bytes) -> dict[str,tuple[float,...]]:
    """Read confirmed 400x/401x catalogue dash/gap sequences in SYM.

    Examples from GEO-MAP's standard library:
    *4001 -> '1 1 0 ...' (solid), *4002 -> '2 1 -1 ...' (1:1 dash),
    *4003 -> '2 2 -1 ...' (2:1 dash).
    A richer pattern grammar must be decoded for other symbol types.
    """
    result={}
    current=None
    for line in _library_lines(path):
        m=re.match(r'^\*(40\d{2})\s',line)
        if m:
            current=m.group(1)
            continue
        if line.startswith('*'):
            current=None
            continue
        if current is None or line.lstrip().startswith(';'):
            continue
        tokens=line.split()
        if len(tokens)<3:
            continue
        try:
            count=int(tokens[0])
            on=float(tokens[1])
            off=float(tokens[2])
        except ValueError:
            continue
        if count==1 and on>0 and off==0:
            result[current]=()
        elif count==2 and on>0 and off<0:
            result[current]=(on,abs(off))
        current=None
    return result


def object_sym_line_pattern(sym_primitives: dict[str,list[SymbolPrimitive]],
                            line_patterns: dict[str,tuple[float,...]],
                            code: str) -> tuple[float,...] | None:
    """Follow the top-level O or L symbol reference to a 400x pattern.

    Returns empty tuple for an explicit continuous stroke, None for an
    unsupported reference. One nested reference level covers 5216→4216→4001.
    """
    refs=[code]
    seen=set()
    for _ in range(3):
        if not refs:
            break
        symbol=refs.pop(0)
        if symbol in seen:
            continue
        seen.add(symbol)
        if symbol in line_patterns:
            return line_patterns[symbol]
        for primitive in sym_primitives.get(symbol,()):
            if primitive.kind not in {'O','L'}:
                continue
            ref=round(primitive.parameters[0])
            if 4000 <= ref <= 4999:
                refs.append(str(ref))
    return None
