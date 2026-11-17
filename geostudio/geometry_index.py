"""Geometry-based feature picking independent of Qt's visual item shapes.

All coordinates are native GEO-MAP X/Y units, not display pixels. The spatial
index is immutable between edits, and must be rebuilt after modifying geometry.
"""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from math import floor, hypot
from typing import Iterable

from .geomap import GeoObject
from .interactions import closest_point_on_edge


def point_in_ring(x: float, y: float, vertices: list[tuple[float, float]]) -> bool:
    """Even-odd test for a closed simple polygon; boundary handled separately."""
    inside = False
    for (ax, ay), (bx, by) in zip(vertices, vertices[1:] + vertices[:1]):
        if (ay > y) != (by > y):
            boundary_x = ax + (y - ay) * (bx - ax) / (by - ay)
            if x < boundary_x:
                inside = not inside
    return inside


def boundary_distance(x: float, y: float, vertices: list[tuple[float, float]]) -> float:
    if not vertices:
        return float('inf')
    if len(vertices) == 1:
        return hypot(x - vertices[0][0], y - vertices[0][1])
    return min(hypot(x - px, y - py)
               for a, b in zip(vertices, vertices[1:])
               for px, py in [closest_point_on_edge(x, y, *a, *b)])


@dataclass(frozen=True)
class Pick:
    obj: GeoObject
    hit_kind: str
    distance: float
    area: float


class GeometryIndex:
    """Uniform grid: fast world-coordinate hit tests even for large maps."""

    def __init__(self, objects: Iterable[GeoObject], *, hide_connectors=False):
        self.hide_connectors = hide_connectors
        self.objects = [o for o in objects if o.points]
        if not self.objects:
            self.tile = 100.0
            self._tiles = {}
            self._oversized = []
            return
        xs = [p.x for o in self.objects for p in o.points]
        ys = [p.y for o in self.objects for p in o.points]
        self.tile = max(max(max(xs) - min(xs), max(ys) - min(ys)) / 45, 0.5)
        self._tiles = defaultdict(list)
        self._oversized = []
        for o in self.objects:
            ox = [p.x for p in o.points]
            oy = [p.y for p in o.points]
            xa, xb = floor(min(ox) / self.tile), floor(max(ox) / self.tile)
            ya, yb = floor(min(oy) / self.tile), floor(max(oy) / self.tile)
            # Very large items are few; don't populate thousands of cells.
            if (xb - xa + 1) * (yb - ya + 1) > 400:
                self._oversized.append(o)
            else:
                for cx in range(xa, xb + 1):
                    for cy in range(ya, yb + 1):
                        self._tiles[(cx, cy)].append(o)

    def nearby(self, x: float, y: float, radius: float = 0) -> list[GeoObject]:
        radius = max(0.0, radius)
        xa, xb = floor((x - radius) / self.tile), floor((x + radius) / self.tile)
        ya, yb = floor((y - radius) / self.tile), floor((y + radius) / self.tile)
        candidates = list(self._oversized)
        seen = {id(o) for o in candidates}
        for cx in range(xa, xb + 1):
            for cy in range(ya, yb + 1):
                for o in self._tiles.get((cx, cy), ()):
                    if id(o) not in seen:
                        seen.add(id(o))
                        candidates.append(o)
        return candidates

    def pick(self, x: float, y: float, radius: float, *,
             visible: set[str] | None = None,
             code_filter: str | None = None) -> list[Pick]:
        """Pick interior of polygons AND the outline within a screen-space tolerance.

        Order: specific requested code; parcel (5216); land-use (5230); then
        shorter-distance edges and smaller-area objects. Caller cycles ties.
        """
        hits = []
        for o in self.nearby(x, y, radius):
            if visible is not None and o.uid not in visible:
                continue
            if code_filter is not None and o.code != code_filter:
                continue
            if self.hide_connectors:
                # P 0 closes a component. Do not select empty connector lines
                # between independent contours of the same GEO-MAP record.
                parts = [[(p.x, p.y) for p in part] for part in o.display_parts]
                distance = min((boundary_distance(x, y, part) for part in parts),
                               default=float('inf'))
                interior = any(len(part) >= 4 and part[0] == part[-1]
                               and point_in_ring(x, y, part[:-1]) for part in parts)
            else:
                pts = [(p.x, p.y) for p in o.points]
                distance = boundary_distance(x, y, pts)
                interior = o.is_closed and point_in_ring(x, y, pts[:-1])
            if not interior and distance > radius:
                continue
            kind = 'inside' if interior else 'edge'
            hits.append(Pick(o, kind, distance, o.area_m2 or float('inf')))
        hits.sort(key=lambda p: (0 if p.obj.code == '5216' else
                                 1 if p.obj.code == '5230' else 2,
                                 0 if p.hit_kind == 'edge' else 1,
                                 p.distance if p.hit_kind == 'edge' else p.area,
                                 p.obj.uid))
        return hits
