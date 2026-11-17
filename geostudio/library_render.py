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


def parse_cdf(path: str | Path) -> dict[str,CDFStyle]:
    styles = {}
    for line in Path(path).read_bytes().decode('cp1250', errors='replace').splitlines():
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


def parse_sym_primitives(path: str | Path) -> dict[str,list[SymbolPrimitive]]:
    """Load simple primitives; keep O/T/arc instructions for future renderers."""
    result={}
    current=None
    for line in Path(path).read_bytes().decode('cp1250',errors='replace').splitlines():
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


def parse_lay_pen_styles(path: str | Path) -> dict[str,LAYPenStyle]:
    """Parse named GEO-MAP overlay codes without modifying the .LAY library.

    Standard rows:  5220 32768 2.008 1 standard 2.5 ...
    2.008 represents the line catalogue ID; exact visual parity still needs
    its own line-pattern definition. Only known 008 is drawn dashed.
    """
    result={}
    for line in Path(path).read_bytes().decode('cp1250',errors='replace').splitlines():
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
