"""Fit a raster draft's complete sides to existing native 5310 boundaries.

Coordinates and distances are native MAP metres.  Only the new draft changes;
reference polygons (including multipart boundaries and holes) stay untouched.
The caller must still run the normal creation/overlap preflight after fitting.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import cos, hypot, pi

from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree


EPS = 1e-7
COS_ANGLE = cos(15 * pi / 180)
MAP_TOLERANCE = .0015


def _distance(a, b):
    return hypot(a[0] - b[0], a[1] - b[1])


def _project(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    size = dx * dx + dy * dy
    t = max(0., min(1., ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / size))
    if t == 0:
        return a, 0.
    if t == 1:
        return b, 1.
    return (a[0] + t * dx, a[1] + t * dy), t


def canonical_locks(points, locked_points):
    """Bind each explicit lock to an existing draft vertex on the MAP grid."""
    vertices = sorted({(round(x, 3), round(y, 3)) for x, y in points})
    result = set()
    for point in locked_points:
        nearest = min(vertices, key=lambda p: (_distance(p, point), p))
        if _distance(nearest, point) > MAP_TOLERANCE:
            raise ValueError("Zablokowany węzeł nie należy do wskazanego obrysu.")
        result.add(nearest)
    return result


def restore_locked_vertices(points, locked):
    """Keep safe, collinear manual vertices which GEOS simplification removed.

    Clipping still has priority over a lock: a manual vertex away from the
    remaining boundary is a conflict, never permission to recreate overlap.
    """
    ring = [tuple(p) for p in points]
    for point in sorted(locked - set(ring)):
        candidates = []
        for i, (a, b) in enumerate(zip(ring, ring[1:] + ring[:1])):
            if _distance(a, b) <= EPS:
                continue
            projection, t = _project(point, a, b)
            candidates.append((_distance(projection, point), i, t))
        distance, index, _ = min(candidates)
        if distance > MAP_TOLERANCE:
            raise ValueError("Ręcznie poprawiony węzeł koliduje z istniejącym 5310. Popraw jego położenie.")
        ring.insert(index + 1, point)
    shape = Polygon(ring)
    if len(ring) > 500 or not shape.is_valid or shape.is_empty or shape.area < .000001:
        raise ValueError("Nie można zachować ręcznych węzłów w poprawnym obrysie. Popraw ich położenie.")
    return ring


@dataclass
class _Boundary:
    points: list
    offsets: list
    length: float

    @classmethod
    def create(cls, ring):
        points = list(ring.coords)
        clean = [points[0]]
        for p in points[1:]:
            if _distance(p, clean[-1]) > EPS:
                clean.append(p)
        if len(clean) < 4:
            return None
        offsets = [0.]
        for a, b in zip(clean, clean[1:]):
            offsets.append(offsets[-1] + _distance(a, b))
        return cls(clean, offsets, offsets[-1])

    def path(self, start, end, forward):
        if not forward:
            return self.path(end, start, True)[::-1]
        a, pa, _ = start
        b, pb, _ = end
        if b < a:
            b += self.length
        between = [(offset + shift, p)
                   for shift in (0., self.length)
                   for offset, p in zip(self.offsets[:-1], self.points[:-1])
                   if a + EPS < offset + shift < b - EPS]
        between.sort(key=lambda item: item[0])
        return [pa] + [p for _, p in between] + [pb]


@dataclass
class _Match:
    path: list
    first: tuple
    last: tuple
    score: float


class _References:
    """A segment index keeps fitting local even on a dense MAP sheet."""

    def __init__(self, boundaries):
        self.boundaries = boundaries
        self.segments = [(ring_id, i, a, b)
                         for ring_id, boundary in enumerate(boundaries)
                         for i, (a, b) in enumerate(zip(boundary.points, boundary.points[1:]))]
        self.tree = STRtree([LineString([a, b]) for _, _, a, b in self.segments])

    def nearby(self, a, b, radius):
        query = box(min(a[0], b[0]) - radius, min(a[1], b[1]) - radius,
                    max(a[0], b[0]) + radius, max(a[1], b[1]) + radius)
        groups = {}
        for hit in self.tree.query(query):
            ring_id, index, u, v = self.segments[int(hit)]
            groups.setdefault(ring_id, []).append((index, u, v))
        for ring_id in sorted(groups):
            yield self.boundaries[ring_id], sorted(groups[ring_id])


def _match_side(a, b, references, radius):
    """Find a close monotone reference path, never an isolated nearby node."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    size = hypot(dx, dy)
    if size <= .002:
        return None
    source = LineString([a, b])
    candidates = []
    seen = set()
    for boundary, segments in references.nearby(a, b, radius):
        starts, ends = [], []
        for index, u, v in segments:
            length = boundary.offsets[index + 1] - boundary.offsets[index]
            dot = dx * (v[0] - u[0]) + dy * (v[1] - u[1])
            if abs(dot) < size * length * COS_ANGLE:
                continue
            for p, result in ((a, starts), (b, ends)):
                q, t = _project(p, u, v)
                distance = _distance(p, q)
                if distance <= radius + EPS:
                    result.append((distance, (boundary.offsets[index] + t * length,
                                              q, index)))
        # Degenerate dense legacy rings may have many equivalent projections.
        # Keep the closest possibilities without unbounded pairwise work.
        starts.sort(key=lambda item: item[0])
        ends.sort(key=lambda item: item[0])
        for start_distance, start in starts[:24]:
            for end_distance, end in ends[:24]:
                for forward in (True, False):
                    arc = ((end[0] - start[0]) if forward else
                           (start[0] - end[0])) % boundary.length
                    if arc <= EPS or arc > size + 2 * radius + EPS:
                        continue
                    path = boundary.path(start, end, forward)
                    path = [p for i, p in enumerate(path)
                            if i == 0 or _distance(p, path[i - 1]) > EPS]
                    if len(path) < 2:
                        continue
                    key = tuple(path)
                    if key in seen:
                        continue
                    seen.add(key)
                    # Every reference segment must follow the source side.
                    # This rejects perpendicular hits, loops and corner cuts.
                    if any((v[0] - u[0]) * dx + (v[1] - u[1]) * dy <
                           _distance(u, v) * size * COS_ANGLE - EPS
                           for u, v in zip(path, path[1:])):
                        continue
                    reference = LineString(path)
                    deviation = reference.hausdorff_distance(source)
                    if deviation > radius + EPS:
                        continue
                    first = tuple(boundary.points[start[2]:start[2] + 2])
                    last = tuple(boundary.points[end[2]:end[2] + 2])
                    candidates.append(_Match(path, first, last,
                                             deviation + .25 * (start_distance + end_distance)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item.score, tuple(item.path)))
    chosen = candidates[0]
    # Near-equal fits to genuinely different parallel tracks are ambiguous.
    # Existing-boundary clipping remains available even when snapping abstains.
    for other in candidates[1:]:
        if other.score > chosen.score + max(.001, radius * .1):
            break
        if LineString(other.path).hausdorff_distance(LineString(chosen.path)) > max(.003, radius * .2):
            return None
    return chosen


def _joint(before, after, original, radius):
    a, b = before.path[-1], after.path[0]
    if _distance(a, b) <= EPS:
        return a
    # Two neighbouring fitted sides may meet at the native corner rather
    # than at their independent perpendicular projections. Only a shared
    # reference endpoint can provide that corner, not a line extrapolation.
    common = [p for p in before.last for q in after.first
              if _distance(p, q) <= EPS and _distance(p, original) <= radius + EPS]
    if not common:
        return None
    return min(common, key=lambda p: (_distance(p, original), p))


def _assemble(original, matches, radius, locked):
    n = len(original)
    corners = []
    for i, p in enumerate(original):
        before, after = matches[(i - 1) % n], matches[i]
        if p in locked:
            corner = p
        elif before and after:
            corner = _joint(before, after, p, radius)
            if corner is None:
                return None
        elif before:
            corner = before.path[-1]
        elif after:
            corner = after.path[0]
        else:
            corner = p
        corners.append(corner)
    fitted = []
    for i, match in enumerate(matches):
        path = [corners[i]]
        if match:
            # A deliberately moved corner stays put. A short explicit bridge
            # joins it to the true reference path; the rest of the side must
            # still follow that path instead of becoming a parallel chord.
            if original[i] in locked and _distance(corners[i], match.path[0]) > EPS:
                path.append(match.path[0])
            path.extend(match.path[1:-1])
            if original[(i + 1) % n] in locked and _distance(corners[(i + 1) % n], match.path[-1]) > EPS:
                path.append(match.path[-1])
        path.append(corners[(i + 1) % n])
        for p in path[:-1]:
            if not fitted or _distance(p, fitted[-1]) > EPS:
                fitted.append(p)
    if len(fitted) > 1 and _distance(fitted[0], fitted[-1]) <= EPS:
        fitted.pop()
    if not 3 <= len(fitted) <= 500:
        return None
    source, result = Polygon(original), Polygon(fitted)
    if (not result.is_valid or result.is_empty or result.area < .000001
            or abs(result.area - source.area) > .35 * source.area
            or result.boundary.hausdorff_distance(source.boundary) > radius + EPS):
        return None
    return fitted


def _split_supported_sides(original, references, radius, protected=None):
    """Keep a reference T-junction even if raster simplification removed it.

    A neighbour may share only the middle or one end of a long straight side.
    Split that source side at supported boundary endpoints before matching,
    so its shared part can fit without extending a neighbour's short edge.
    """
    result = []
    for a, b in zip(original, original[1:] + original[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        size = hypot(dx, dy)
        positions = {0.: a}
        if size > EPS and not (protected and protected(a, b)):
            for _, segments in references.nearby(a, b, radius):
                for _, u, v in segments:
                    length = _distance(u, v)
                    if abs(dx * (v[0] - u[0]) + dy * (v[1] - u[1])) < size * length * COS_ANGLE:
                        continue
                    ta = ((u[0] - a[0]) * dx + (u[1] - a[1]) * dy) / size ** 2
                    tb = ((v[0] - a[0]) * dx + (v[1] - a[1]) * dy) / size ** 2
                    overlap = (min(1., max(ta, tb)) - max(0., min(ta, tb))) * size
                    if overlap < min(size * .5, max(.01, radius)):
                        continue
                    for p, t in ((u, ta), (v, tb)):
                        # A nearby original corner is handled jointly by its
                        # two sides; splitting off a tiny end fragment would
                        # conceal that supported native corner from the fit.
                        if not radius + EPS < t * size < size - radius - EPS:
                            continue
                        q = (a[0] + t * dx, a[1] + t * dy)
                        if _distance(p, q) <= radius + EPS:
                            positions[t] = q
        result.extend(p for _, p in sorted(positions.items()))
        if len(result) > 500:
            return original
    return result


def _resolve_joints(original, matches, radius, locked):
    """Keep the most supported boundary length at incompatible corners.

    Only consecutive source sides can conflict, so two linear passes solve
    the cyclic choice without repeatedly validating hundreds of polygons.
    """
    n = len(matches)
    conflicts = [bool(original[i] not in locked and matches[i - 1] and matches[i] and
                      _joint(matches[i - 1], matches[i], original[i], radius) is None)
                 for i in range(n)]
    if not any(conflicts):
        return matches
    weights = [(LineString(match.path).length, -match.score, 1) if match else (0., 0., 0)
               for match in matches]
    best = None
    for first in (0, 1):
        if first and matches[0] is None:
            continue
        layers = [{first: (weights[0] if first else (0., 0., 0), None)}]
        for i in range(1, n):
            layer = {}
            for choice in (0, 1):
                if choice and matches[i] is None:
                    continue
                weight = weights[i] if choice else (0., 0., 0)
                for previous, (value, _) in layers[-1].items():
                    if choice and previous and conflicts[i]:
                        continue
                    score = tuple(a + b for a, b in zip(value, weight))
                    if choice not in layer or score > layer[choice][0]:
                        layer[choice] = (score, previous)
            layers.append(layer)
        for last, (score, _) in layers[-1].items():
            if last and first and conflicts[0]:
                continue
            if best is None or score > best[0]:
                choices = [0] * n
                choice = last
                for i in range(n - 1, -1, -1):
                    choices[i] = choice
                    choice = layers[i][choice][1]
                best = score, choices
    return [match if keep else None for match, keep in zip(matches, best[1])]


def fit_neighbour_boundaries(points, obstacles, radius, locked_points=None,
                             protected_edges=None):
    """Return a bounded, valid draft fitted to complete nearby 5310 sides.

    This never accepts a result just because its vertices are near something:
    an entire side must be supported by a co-directional boundary path. Its
    real intermediate vertices are retained. A failed local fit does not
    suppress another independent side which can safely join its neighbour.
    A batch may protect common draft edges from independent local fitting;
    its shared junctions must also be supplied in ``locked_points``.
    """
    original = [tuple(p) for p in points]
    locked = {tuple(p) for p in (locked_points or [])}
    if not locked.issubset(set(original)):
        raise ValueError("Zablokowany węzeł nie należy do wskazanego obrysu.")
    if not obstacles or radius <= 0:
        return original, 0
    merged = unary_union(obstacles)
    parts = [merged] if merged.geom_type == "Polygon" else list(merged.geoms)
    boundaries = []
    for part in parts:
        if part.geom_type != "Polygon":
            continue
        for ring in (part.exterior, *part.interiors):
            boundary = _Boundary.create(ring)
            if boundary:
                boundaries.append(boundary)
    references = _References(boundaries)
    protected_tree = STRtree([LineString(edge) for edge in protected_edges]) if protected_edges else None

    def protected(a, b):
        if protected_tree is None:
            return False
        line = LineString([a, b])
        return any(line.intersection(protected_tree.geometries[int(hit)]).length > EPS
                   for hit in protected_tree.query(line))

    original = _split_supported_sides(original, references, radius, protected)
    matches = [None if protected(a, b) else _match_side(a, b, references, radius)
               for a, b in zip(original, original[1:] + original[:1])]
    matches = _resolve_joints(original, matches, radius, locked)
    fitted = _assemble(original, matches, radius, locked)
    if fitted is None:
        accepted = [None] * len(original)
        ordered = sorted((i for i, match in enumerate(matches) if match),
                         key=lambda i: (-LineString(matches[i].path).length, matches[i].score, i))
        fitted = original
        for i in ordered:
            trial = list(accepted)
            trial[i] = matches[i]
            candidate = _assemble(original, trial, radius, locked)
            if candidate is not None:
                accepted, fitted = trial, candidate
        matches = accepted
    return fitted, sum(match is not None for match in matches)
