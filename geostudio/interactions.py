"""Map-coordinate snapping and geometry helpers; independent of Qt.

Coordinates here are source x/y values, *not* screen pixels. UI converts a
pixel radius into map units before calling the snapping function.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite
from typing import Iterable

from .geomap import GeoObject


@dataclass(frozen=True)
class SnapResult:
    x: float
    y: float
    kind: str  # 'vertex' or 'edge'
    uid: str
    code: str
    distance: float


def closest_point_on_edge(x: float, y: float, ax: float, ay: float, bx: float, by: float) -> tuple[float, float]:
    dx, dy = bx - ax, by - ay
    square = dx * dx + dy * dy
    if square == 0:
        return ax, ay
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / square))
    return ax + t * dx, ay + t * dy


def find_snap(x: float, y: float, objects: Iterable[GeoObject], radius: float,
              *, exclude_uid: str | None = None, hide_connectors=False) -> SnapResult | None:
    """Snap to the nearest vertex; otherwise use the nearest line segment.

    Vertex snaps take precedence over edges within the tolerance, including
    survey markers and shared polygon corners. Zero-length edges are ignored.
    """
    if not all(isfinite(v) for v in (x, y, radius)) or radius <= 0:
        return None
    best_vertex = None
    best_edge = None
    for obj in objects:
        if not obj.points or (exclude_uid is not None and obj.uid == exclude_uid):
            continue
        for p in obj.points:
            d = hypot(x - p.x, y - p.y)
            if d <= radius and (best_vertex is None or d < best_vertex.distance):
                best_vertex = SnapResult(p.x, p.y, 'vertex', obj.uid, obj.code, d)
        for a, b in zip(obj.points, obj.points[1:]):
            if hide_connectors and a.point_type == 0:
                continue  # never snap to an invisible connector
            if a.x == b.x and a.y == b.y:
                continue
            cx, cy = closest_point_on_edge(x, y, a.x, a.y, b.x, b.y)
            d = hypot(x - cx, y - cy)
            if d <= radius and (best_edge is None or d < best_edge.distance):
                best_edge = SnapResult(cx, cy, 'edge', obj.uid, obj.code, d)
    return best_vertex or best_edge


def polygon_is_valid(points: list[tuple[float, float]]) -> bool:
    if len(points) < 3 or len(set(points)) < 3:
        return False
    if not all(isfinite(x) and isfinite(y) for x, y in points):
        return False
    x0, y0 = points[0]
    closed = points[1:] + [points[0]]
    area2 = sum((a[0]-x0)*(b[1]-y0) - (b[0]-x0)*(a[1]-y0)
                for a, b in zip(points, closed))
    return abs(area2) >= 1e-8
