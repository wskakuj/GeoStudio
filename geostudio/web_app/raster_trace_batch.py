"""Bounded, read-only preparation of a complete raster tracing proposal.

The browser supplies native MAP rings. Existing 5310 are checked through the
ordinary single-object preflight; this module preserves shared draft paths and
checks the whole collection without choosing an arbitrary overlap winner.
"""
from __future__ import annotations

from math import isfinite

from shapely.errors import GEOSException
from shapely.geometry import Point, Polygon, box
from shapely.strtree import STRtree

from .raster_trace_fit import EPS


MAX_BATCH_ITEMS = 1000
MAX_BATCH_VERTICES = 50000
MAX_BATCH_PAIR_CHECKS = 25000
MAX_BATCH_NODE_CHECKS = 500000
MAX_BATCH_BODY_BYTES = 4 * 1024 * 1024


class _NodingLimit(ValueError):
    pass


def batch_items(items):
    """Reject collection overflow; retain individual errors for the review UI."""
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH_ITEMS:
        raise ValueError("Partia musi zawierać 1–1000 propozycji. Wybierz mniejszy obszar.")
    if sum(len(item.get("points", [])) for item in items
           if isinstance(item, dict) and isinstance(item.get("points"), list)) > MAX_BATCH_VERTICES:
        raise ValueError("Partia przekracza limit 50 000 węzłów. Wybierz mniejszy obszar.")
    seen, result = set(), []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Każda propozycja musi mieć własny identyfikator i obrys.")
        identity = item.get("id")
        if (type(identity) not in (str, int) or
                isinstance(identity, str) and (not identity.strip() or len(identity) > 80 or
                                               any(c in identity for c in "\r\n\0")) or
                isinstance(identity, int) and abs(identity) >= 1e9 or str(identity) in seen):
            raise ValueError("Propozycje wymagają unikatowych identyfikatorów (tekst do 80 znaków lub liczba).")
        seen.add(str(identity))
        cleaned = {"id": identity, "points": item.get("points"),
                   "a1": "", "seedPoints": item.get("seedPoints"),
                   "lockedPoints": item.get("lockedPoints")}
        try:
            if set(item) - {"id", "points", "a1", "seedPoints", "lockedPoints"}:
                raise ValueError("Nieznane pola propozycji.")
            value = item.get("a1", "")
            if not isinstance(value, str) or any(c in value for c in "\r\n]\0"):
                raise ValueError("Nieprawidłowy numer A1.")
            value = value.strip()
            if len(value.encode("cp1250")) > 512:
                raise ValueError("Numer A1 przekracza 512 bajtów.")
            cleaned["a1"] = value
        except UnicodeEncodeError:
            cleaned["error"] = "Numer A1 musi mieć kodowanie CP1250."
        except ValueError as exc:
            cleaned["error"] = str(exc)
        result.append(cleaned)
    return result


def validate_snap_distance(value):
    if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 20:
        raise ValueError("Zasięg dopasowania musi mieścić się w zakresie 0–20 m.")


def item_result(item, *, points=None, clipped=False, snapped=False, error="", without_a1=False):
    missing = not item["a1"] and not without_a1
    return {"id": item["id"], "status": "rejected" if error else "needsA1" if missing else "ready",
            "points": [list(p) for p in (points or [])], "a1": item["a1"],
            "clipped": bool(clipped), "snapped": bool(snapped),
            "reason": error or ("Uzupełnij lub potwierdź numer A1." if missing else "")}


def batch_report(items, **extra):
    return {"items": items, "stats": {
        "total": len(items), "ready": sum(item["status"] == "ready" for item in items),
        "needsA1": sum(item["status"] == "needsA1" for item in items),
        "rejected": sum(item["status"] == "rejected" for item in items),
        "clipped": sum(item["clipped"] for item in items),
        "snapped": sum(item["snapped"] for item in items)}, **extra}


def _pairs(shapes):
    """Visit only intersecting envelopes, with a hard bound for dense input."""
    tree = STRtree(shapes)
    count = 0
    for i, shape in enumerate(shapes):
        if shape is None:
            continue
        for hit in sorted(tree.query(shape)):
            j = int(hit)
            if j <= i:
                continue
            count += 1
            if count > MAX_BATCH_PAIR_CHECKS:
                raise ValueError("Zbyt wiele nakładających się obrysów w jednej partii. Wybierz mniejszy obszar.")
            yield i, j


def overlap_pairs(results):
    shapes = [Polygon(item["points"]) if item["status"] != "rejected" else None for item in results]
    # Existing MAP references have their established 1.5 mm rounding guard.
    # Newly created neighbours can share exactly the same canonical path, so
    # a second, displaced boundary must not be accepted as a rounding sliver.
    return [(i, j) for i, j in _pairs(shapes) if shapes[i].intersection(shapes[j]).area > 1e-10]


def mark_conflicts(results, pairs):
    conflicts = {}
    for i, j in pairs:
        conflicts.setdefault(i, []).append(results[j]["id"])
        conflicts.setdefault(j, []).append(results[i]["id"])
    for i, identities in conflicts.items():
        results[i].update(status="rejected", conflicts=identities,
                          reason="Propozycja nakłada się na inne propozycje. Popraw wspólne granice lub odznacz kolidujące pola.")


def _contact_parts(geometry):
    if geometry.is_empty:
        return
    if geometry.geom_type in {"LineString", "Point"}:
        yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _contact_parts(part)


def _node_ring(points, nodes):
    """Give both sides of a T-junction the same canonical shared vertex."""
    result = []
    ring = [tuple(p) for p in points]
    for a, b in zip(ring, ring[1:] + ring[:1]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        positions = {0.: a}
        if length2 > EPS ** 2:
            for p in (nodes(a, b) if callable(nodes) else nodes):
                t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2
                if (EPS < t < 1 - EPS and
                        abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) <= EPS * length2 ** .5):
                    positions[t] = p
        result.extend(p for _, p in sorted(positions.items()))
        if len(result) > 500:
            raise ValueError("Po połączeniu wspólnych granic obrys przekracza 500 węzłów. Uprość go ręcznie.")
    return result


def _node_source_mesh(items):
    """Share original vertices before either side is rounded to the MAP grid.

    A T-junction at (1, 1/3) on (0, 0)--(3, 1) must be inserted into both
    neighbours before rounding to millimetres. Otherwise the rounded shorter
    side crosses the longer one and creates a false overlap. Use the existing
    floating-point EPS only; this never joins two displaced raster borders.
    """
    rings = []
    for item in items:
        points = item.get("points")
        if (item.get("error") or not isinstance(points, list) or not 3 <= len(points) <= 500 or
                any(not isinstance(p, list) or len(p) != 2 or
                    any(type(v) not in (int, float) or not isfinite(v) or abs(v) >= 1e9 for v in p)
                    for p in points)):
            rings.append(None)
            continue
        ring = [tuple(p) for p in points]
        if ring[0] == ring[-1]:
            ring.pop()
        try:
            shape = Polygon(ring)
            rings.append(ring if shape.is_valid and not shape.is_empty and shape.area > 0 else None)
        except (ValueError, GEOSException):
            rings.append(None)

    nodes = sorted({point for ring in rings if ring for point in ring})
    if not nodes:
        return items
    index = STRtree([Point(point) for point in nodes])
    work = 0

    def nearby(a, b):
        nonlocal work
        hits = index.query(box(min(a[0], b[0]) - EPS, min(a[1], b[1]) - EPS,
                               max(a[0], b[0]) + EPS, max(a[1], b[1]) + EPS))
        work += len(hits)
        if work > MAX_BATCH_NODE_CHECKS:
            raise _NodingLimit("Zbyt wiele wspólnych węzłów w jednej partii. Wybierz mniejszy obszar.")
        return (nodes[int(hit)] for hit in sorted(hits))

    prepared = []
    for item, ring in zip(items, rings):
        if ring is None:
            prepared.append(item)
            continue
        try:
            prepared.append(dict(item, points=[list(p) for p in _node_ring(ring, nearby)]))
        except _NodingLimit:
            raise
        except ValueError as exc:
            prepared.append(dict(item, error=str(exc)))
    if sum(len(item["points"]) for item in prepared if isinstance(item.get("points"), list)) > MAX_BATCH_VERTICES:
        raise ValueError("Po połączeniu wspólnych granic partia przekracza 50 000 węzłów. Wybierz mniejszy obszar.")
    return prepared


def shared_topology(results):
    """Lock common junctions and protect shared sides from independent fits.

    Two polygons can touch along differently subdivided edges. Intersecting
    their actual boundaries handles that case as well as partial T-junctions;
    endpoint proximity alone never invents a new shared boundary.
    """
    shapes = [Polygon(item["points"]) if item["status"] != "rejected" else None for item in results]
    nodes, paths = [set() for _ in results], [[] for _ in results]
    for i, j in _pairs(shapes):
        contact = shapes[i].boundary.intersection(shapes[j].boundary)
        for part in _contact_parts(contact):
            coords = [(round(x, 3), round(y, 3)) for x, y in part.coords]
            nodes[i].update(coords)
            nodes[j].update(coords)
            if part.geom_type == "LineString" and part.length > EPS:
                edges = list(zip(coords, coords[1:]))
                paths[i].extend(edges)
                paths[j].extend(edges)
    return nodes, paths


def fit_batch(items, fit, snap_distance):
    """Fit each draft, preserve the mesh, and return all individual outcomes.

    ``fit`` delegates to the workspace's existing guarded single-outline API.
    A first pass clips occupied land without moving the shared draft mesh.
    Local fits are then allowed only on its exterior, unshared sides. If an
    otherwise safe local fit conflicts with another draft, keep the base mesh.
    """
    validate_snap_distance(snap_distance)
    items = _node_source_mesh(items)
    results = []
    for item in items:
        try:
            if item.get("error"):
                raise ValueError(item["error"])
            base = fit(item, fit_boundaries=False)
            results.append(item_result(item, **base))
        except (ValueError, GEOSException) as exc:
            results.append(item_result(item, error=str(exc)))

    mark_conflicts(results, overlap_pairs(results))
    nodes, paths = shared_topology(results)
    bases = [dict(item, points=[list(p) for p in item["points"]]) for item in results]
    for i, (item, base) in enumerate(zip(items, bases)):
        if base["status"] == "rejected":
            continue
        try:
            noded = _node_ring(base["points"], nodes[i])
            # Explicit manual locks have already been checked against the
            # original ring and survived the initial occupied-land clipping.
            locks = nodes[i] | {tuple(p) for p in (item.get("lockedPoints") or [])}
            current = dict(item, points=[list(p) for p in noded],
                           lockedPoints=[list(p) for p in sorted(locks)])
            fitted = fit(current, protected_edges=paths[i])
            fitted["clipped"] = base["clipped"] or fitted["clipped"]
            results[i] = item_result(item, **fitted)
            bases[i]["points"] = [list(p) for p in noded]
        except (ValueError, GEOSException) as exc:
            results[i] = item_result(item, points=base["points"], error=str(exc), clipped=base["clipped"])

    # Reverting one conflicting fit may expose another fit against the base.
    # Two bounded rounds suffice: revert involved fits, then all remaining
    # local fits if needed. The original shared mesh is always the fallback.
    for all_fitted in (False, True):
        pairs = overlap_pairs(results)
        if not pairs:
            break
        involved = {i for pair in pairs for i in pair}
        for i, result in enumerate(results):
            if result["status"] != "rejected" and result["snapped"] and (all_fitted or i in involved):
                results[i] = dict(bases[i])
                results[i]["reason"] = ("Zachowano obrys bez przesuwania: dopasowanie powodowałoby nałożenie propozycji."
                                          + (" Uzupełnij numer A1." if not result["a1"] else ""))
    mark_conflicts(results, overlap_pairs(results))
    if sum(len(item["points"]) for item in results) > MAX_BATCH_VERTICES:
        raise ValueError("Po dopasowaniu partia przekracza 50 000 węzłów. Wybierz mniejszy obszar.")
    return batch_report(results)


def encode_batch(items):
    """Reuse the MAP polygon/label writer without reparsing a large MAP N times."""
    from geostudio.geomap import GeoMap

    records, created = [], []
    for item in items:
        temporary = GeoMap(b"")
        created.append(temporary.append_polygon([tuple(p) for p in item["points"]], code="5310",
                                                fields={"A1": item["a1"]} if item["a1"] else {}))
        records.extend(temporary.lines)
    return records, created
