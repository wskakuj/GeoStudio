"""Picking, selection arithmetic and snapping, independent of the window.

Everything here works in native GEO-MAP map units. Screen tolerances are
converted by the caller before they arrive: a radius of 8 *pixels* is not a
radius of 8 metres, and the conversion depends on the current zoom. See
``GeoStudioWindow._map_radius`` for the only place that conversion happens.

The module knows nothing about menus, docks, status bars or the view widget.
``highlight_path`` is the single Qt-aware function, because it builds the
QPainterPath used for the selection outline.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtGui import QPainterPath

from .geomap import GeoMap, GeoObject
from .geometry_index import GeometryIndex, point_in_ring
from .interactions import SnapResult, find_snap
from .scene_builder import object_path


@dataclass(frozen=True)
class SelectionContext:
    """State the picking and snapping rules need, gathered in one place.

    ``radius`` is already in map units. ``layer_for_uid`` and ``hidden_layers``
    are kept instead of a precomputed visible set so both rules use exactly the
    same notion of visibility.
    """

    doc: GeoMap | None
    geometry_index: GeometryIndex
    layer_for_uid: dict[str, str] = field(default_factory=dict)
    hidden_layers: frozenset[str] = frozenset()
    code_filter: str | None = None
    hide_connectors: bool = True
    radius: float = 0.0
    excluded_uids: frozenset[str] = frozenset()


def visible_uids(ctx: SelectionContext) -> set[str]:
    """Objects on layers that are currently switched on and still in the map."""
    if ctx.doc is None:
        return set()
    return {uid for uid, layer in ctx.layer_for_uid.items()
            if (layer not in ctx.hidden_layers and uid in ctx.doc.by_id
                and uid not in ctx.excluded_uids)}


def pick_candidates(ctx: SelectionContext, x: float, y: float) -> list[GeoObject]:
    """Objects under the cursor, in the order the user cycles through them.

    The ordering itself lives in GeometryIndex.pick and is deliberately not
    touched here: parcels (5216) win over land use (5230) so a parcel lying
    under a land-use polygon stays selectable with a plain click.
    """
    if ctx.doc is None:
        return []
    radius = max(ctx.radius, 1e-8)
    hits = ctx.geometry_index.pick(x, y, radius, visible=visible_uids(ctx),
                                   code_filter=ctx.code_filter)
    return [hit.obj for hit in hits if hit.obj.uid in ctx.doc.by_id]


def resolve_click(uids: list[str], current_uid: str, *,
                  cycle: bool = False, repeat: bool = False) -> str:
    """Which candidate wins this click.

    ``cycle`` comes from Ctrl+click, ``repeat`` from clicking the same spot
    again; both advance to the next candidate after the current one and wrap.
    """
    if (cycle or repeat) and current_uid in uids:
        index = (uids.index(current_uid) + 1) % len(uids)
    else:
        index = 0
    return uids[index]


def rectangle_candidates(ctx: SelectionContext, x0: float, y0: float,
                         x1: float, y1: float) -> list[GeoObject]:
    """Visible map objects whose geometry bounds intersect a drag rectangle.

    Coordinates are map units. The active code filter and layer visibility use
    the same context as single-click picking, so rectangle selection cannot
    accidentally include other codes or hidden layers.
    """
    if ctx.doc is None:
        return []
    left, right = sorted((x0, x1))
    bottom, top = sorted((y0, y1))
    visible = visible_uids(ctx)
    matches = []
    for obj in ctx.doc.objects:
        if (not obj.uid or obj.uid not in visible or
                (ctx.code_filter is not None and obj.code != ctx.code_filter)):
            continue
        if not obj.points:
            continue
        xs = [point.x for point in obj.points]
        ys = [point.y for point in obj.points]
        if max(xs) < left or min(xs) > right or max(ys) < bottom or min(ys) > top:
            continue
        if _geometry_intersects_rectangle(obj, left, bottom, right, top):
            matches.append(obj)
    return matches


def _geometry_intersects_rectangle(obj: GeoObject, left: float, bottom: float,
                                   right: float, top: float) -> bool:
    """Exact segment/area intersection for a map-coordinate rectangle."""
    parts = [[(point.x, point.y) for point in part]
             for part in obj.display_parts if part]
    if not parts:
        parts = [[(point.x, point.y) for point in obj.points]]

    def inside(point: tuple[float, float]) -> bool:
        return left <= point[0] <= right and bottom <= point[1] <= top

    corners = [(left, bottom), (right, bottom), (right, top), (left, top)]

    def orientation(a, b, c) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    def on_segment(a, b, p) -> bool:
        return (min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and
                min(a[1], b[1]) <= p[1] <= max(a[1], b[1]) and
                abs(orientation(a, b, p)) <= 1e-10)

    def segments_intersect(a, b, c, d) -> bool:
        o1, o2 = orientation(a, b, c), orientation(a, b, d)
        o3, o4 = orientation(c, d, a), orientation(c, d, b)
        if ((o1 > 1e-10 and o2 < -1e-10 or o1 < -1e-10 and o2 > 1e-10) and
                (o3 > 1e-10 and o4 < -1e-10 or o3 < -1e-10 and o4 > 1e-10)):
            return True
        return ((abs(o1) <= 1e-10 and on_segment(a, b, c)) or
                (abs(o2) <= 1e-10 and on_segment(a, b, d)) or
                (abs(o3) <= 1e-10 and on_segment(c, d, a)) or
                (abs(o4) <= 1e-10 and on_segment(c, d, b)))

    rect_edges = list(zip(corners, corners[1:] + corners[:1]))
    for part in parts:
        if any(inside(point) for point in part):
            return True
        segments = list(zip(part, part[1:]))
        if len(part) > 2 and part[0] != part[-1]:
            segments.append((part[-1], part[0]))
        if any(segments_intersect(a, b, c, d)
               for a, b in segments for c, d in rect_edges):
            return True
        if (len(part) >= 4 and part[0] == part[-1] and
                any(point_in_ring(x, y, part[:-1]) for x, y in corners)):
            return True
    return False


def toggle_selection(selected: list[str], uid: str) -> list[str]:
    """Ctrl+click behaviour: add the object, or remove it if already selected."""
    updated = [item for item in selected if item != uid]
    if uid not in selected:
        updated.append(uid)
    return updated


def highlight_path(doc: GeoMap, uids: list[str], *,
                   hide_connectors: bool = True) -> QPainterPath:
    """One outline for the whole selection, following the real contours.

    Paths come from object_path, so multipart records are outlined along their
    components instead of being joined by connector lines, and the result is a
    true contour rather than a bounding rectangle.
    """
    combined = QPainterPath()
    for uid in uids:
        obj = doc.by_id[uid]
        if obj.points:
            combined.addPath(object_path(obj, hide_connectors=hide_connectors))
    return combined


def snap_at(ctx: SelectionContext, x: float, y: float, *,
            exclude_uid: str | None = None,
            enabled: bool = True,
            include_hidden_markers: bool = False) -> SnapResult | None:
    """Snap to every nearby vertex or edge, regardless of object code.

    Hidden ordinary layers stay excluded. An explicit opt-in lets the map
    editor also snap to survey monuments in the normally hidden
    'Graniczniki' layer without making them selectable/rendered.
    ``radius`` is already in map units, derived from screen pixels.
    """
    if ctx.doc is None or not enabled:
        return None
    radius = ctx.radius
    if radius <= 0:
        return None
    candidates = []
    for obj in ctx.geometry_index.nearby(x, y, radius):
        if obj.uid in ctx.excluded_uids:
            continue
        layer = ctx.layer_for_uid.get(obj.uid, '')
        hidden = layer in ctx.hidden_layers
        marker = (include_hidden_markers and
                  layer.casefold().startswith('granicznik'))
        if not hidden or marker:
            candidates.append(obj)
    return find_snap(x, y, candidates, radius, exclude_uid=exclude_uid,
                     hide_connectors=ctx.hide_connectors)
