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

from dataclasses import dataclass
from .interactions import closest_point_on_edge


@dataclass(frozen=True)
class LinkedVertexPlan:
    """Edits for a shared corner, including exact T-junctions.

    "inserts" are existing, SAME-CODE polygon edges which pass through the
    source corner without having a P vertex there. They must first be split
    at the ORIGINAL corner, then the newly inserted P is moved together with
    all matched same-code vertices. Other codes are never in this plan.
    """

    moves: dict[str, dict[int, tuple[float, float]]]
    inserts: dict[str, tuple[int, tuple[float, float]]]


def linked_vertex_plan(doc: GeoMap, uid: str, index: int, new_x: float,
                       new_y: float, *, tolerance: float = 0.0015,
                       endpoint_clearance: float = 0.005) -> LinkedVertexPlan:
    """Plan corner edits on same-code polygons, even on a neighbor's edge.

    A source corner sitting inside a neighboring segment is a T-junction:
    the existing linked_vertex_moves() does not find it because there is no
    P record at that coordinate. Insert a new P at that exact source-side
    position first; then move the new point in one History transaction.

    If one neighbor has multiple candidate edges at this corner, refuse
    the ambiguous topology rather than modify an arbitrary ring.
    """
    current = doc.by_id[uid]
    moves = linked_vertex_moves(doc, uid, index, new_x, new_y,
                                tolerance=tolerance)
    start = current.points[index]
    inserts: dict[str, tuple[int, tuple[float, float]]] = {}
    for other in doc.objects:
        if (other.uid == uid or other.code != current.code or
                not other.is_closed or not other.uid or
                other.uid in moves):
            continue
        candidates = []
        for i in range(len(other.points) - 1):
            a, b = other.points[i], other.points[i + 1]
            if a.point_type == 0:
                # P 0 closes a display component; no invisible bridges.
                continue
            cx, cy = closest_point_on_edge(
                start.x, start.y, a.x, a.y, b.x, b.y)
            if (hypot(cx - start.x, cy - start.y) <= tolerance and
                    hypot(cx - a.x, cy - a.y) > endpoint_clearance and
                    hypot(cx - b.x, cy - b.y) > endpoint_clearance):
                candidates.append((i, (cx, cy)))
        if len(candidates) > 1:
            raise ValueError(
                "Niejednoznaczna wspólna krawędź poligonu " + other.uid)
        if candidates:
            segment_index, corner = candidates[0]
            inserts[other.uid] = (segment_index, corner)
            # The new record is placed AFTER the identified segment vertex.
            moves[other.uid] = {segment_index + 1: (new_x, new_y)}
    return LinkedVertexPlan(moves=moves, inserts=inserts)
