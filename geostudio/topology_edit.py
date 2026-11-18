"""Conservative shared-boundary editing of same-code closed GEO-MAP polygons.

Only vertices already coincident within source precision are linked.
Arbitrary polygon overlap is NOT solved by clipping: automatic subtraction
can create holes, split polygons or silently damage land registry geometry.
"""
from __future__ import annotations

from math import hypot

from .geomap import GeoMap


def linked_vertex_moves(doc: GeoMap, uid: str, index: int,
                        new_x: float, new_y: float, *,
                        tolerance: float = 0.0015) -> dict[str, dict[int, tuple[float, float]]]:
    """Return all same-code vertices sharing the original selected corner.

    No geometry changes happen here. Each source vertex may be repeated by
    two or more adjacent polygons; the final caller validates the entire
    change set and records a SINGLE history transaction.
    """
    current = doc.by_id[uid]
    if not current.is_closed:
        raise ValueError("Edycja wspólnej granicy wymaga zamkniętego poligonu.")
    if not 0 <= index < len(current.points) - 1:
        raise IndexError("Niepoprawny indeks węzła.")
    old = current.points[index]
    changes = {uid: {index: (new_x, new_y)}}
    for other in doc.objects:
        if other.uid == uid or other.code != current.code or not other.is_closed:
            continue
        matches = {
            other_index: (new_x, new_y)
            for other_index, point in enumerate(other.points[:-1])
            if hypot(point.x - old.x, point.y - old.y) <= tolerance
        }
        if matches:
            changes[other.uid] = matches
    return changes
