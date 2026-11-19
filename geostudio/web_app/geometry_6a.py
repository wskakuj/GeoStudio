"""Safe, non-destructive GIS overlays and explicit boolean operations.

GEO-MAP input records are the authoritative BASE geometry. Overlap cutouts are
computed on demand for GeoStudio 2.0 only; they never destroy any base P record.
Standalone MAP exports retain the uncut source polygons by design. The companion
topology JSON stores only the stacking priority and verified MAP checksum.

Shapely is used for robust polygon set operations; all coordinates here are
native GEO-MAP (X northing, Y easting) in metres.
"""
from __future__ import annotations

from math import isfinite, hypot
from shapely.geometry import Polygon, LineString, MultiPolygon, GeometryCollection
from shapely.ops import split as shapely_split, unary_union


def polygon_of(obj):
    if not obj.is_closed or len(obj.points)<4:
        raise ValueError("Obiekt nie jest zamkniętym poligonem.")
    if any(p.point_type!=1 for p in obj.points):
        raise ValueError("Nieobsługiwany poligon wieloczęściowy w tym narzędziu.")
    base=[(p.x,p.y) for p in obj.points[:-1]]
    poly=Polygon(base)
    if poly.is_empty or not poly.is_valid or poly.area < .000001:
        raise ValueError("Obiekt ma nieprawidłową geometrię lub zerową powierzchnię.")
    return poly


def positive_shell(geometry):
    """A single simple polygon as X/Y tuples, positive signed area."""
    if not isinstance(geometry, Polygon) or geometry.is_empty or len(geometry.interiors):
        raise ValueError("Geometria zawiera otwór albo więcej niż jeden obszar.")
    coords=[(round(x,3),round(y,3)) for x,y in list(geometry.exterior.coords)[:-1]]
    if len(set(coords))<3:
        raise ValueError("Powstały poligon ma za mało różnych punktów.")
    signed=sum((x-x0)*(yn-y0)-(xn-x0)*(y-y0) for ((x,y),(xn,yn))
               in zip(coords,coords[1:]+coords[:1]) for x0,y0 in [coords[0]]) / 2
    if signed<0:
        coords=[coords[0]]+list(reversed(coords[1:]))
    return coords


def shape_parts(shape):
    """Convert visible polygon difference into Canvas (east, -north) rings."""
    if shape.is_empty:
        return []
    polygons=[]
    if isinstance(shape,Polygon):
        polygons=[shape]
    elif isinstance(shape,(MultiPolygon,GeometryCollection)):
        for member in shape.geoms:
            if isinstance(member,Polygon):
                polygons.append(member)
            elif isinstance(member,MultiPolygon):
                polygons.extend(member.geoms)
    result=[]
    for poly in polygons:
        for ring in [poly.exterior,*poly.interiors]:
            part=[[round(y,6),round(-x,6)] for x,y in ring.coords]
            if len(part)>=4:
                result.append(part)
    return result


def visible_difference(base, upper):
    """Polygon minus all later foreground polygon geometries of SAME code."""
    if not upper:
        return base
    nearby=[p for p in upper if p.intersects(base)]
    if not nearby:
        return base
    return base.difference(unary_union(nearby))


def merge_simple(polygons):
    if not 2<=len(polygons)<=100:
        raise ValueError("Scalanie wymaga 2–100 poligonów.")
    result=unary_union(polygons)
    if not isinstance(result,Polygon) or result.is_empty or len(result.interiors):
        raise ValueError("Scalanie wymaga przylegających poligonów bez otworów.")
    return positive_shell(result)


def split_simple(poly,cut):
    if not 2<=len(cut)<=500 or any(not all(isfinite(v) for v in p) for p in cut):
        raise ValueError("Linia podziału wymaga 2–500 prawidłowych punktów.")
    line=LineString(cut)
    if not line.is_simple:
        raise ValueError("Linia podziału przecina samą siebie.")
    result=shapely_split(poly,line)
    parts=[p for p in result.geoms if isinstance(p,Polygon) and p.area>.000001]
    if len(parts)<2 or len(parts)>100:
        raise ValueError("Linia musi przeciąć poligon na 2–100 części.")
    if abs(sum(p.area for p in parts)-poly.area)>max(.001,poly.area*1e-8):
        raise ValueError("Podział nie zachował całkowitej powierzchni.")
    return [positive_shell(p) for p in parts]
