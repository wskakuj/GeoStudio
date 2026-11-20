"""Non-destructive GEO-MAP topology diagnostics.

Only FLAG potential problems. Never snap, merge or rewrite native P records.
Checks are code-aware: polygons of different GEO-MAP codes may legitimately
overlap or touch and must not be auto-corrected together.
"""
from __future__ import annotations

from collections import defaultdict
from math import hypot
from shapely.geometry import Point, box
from shapely.strtree import STRtree
from shapely.errors import GEOSException
from shapely.ops import polygonize, unary_union

from geostudio.web_app.geometry_6a import geometry_of

POLYGON_CODES = {"5216", "5220", "5230", "5310"}
# Tight native-coordinate tolerances in metres; GEO-MAP P records are 1 mm.
NODE_TOLERANCE = .0015
GAP_TOLERANCE = .025
MIN_OVERLAP_AREA = .002
MAX_AUDIT_OBJECTS = 25000
MAX_PAIR_CHECKS = 150000
MAX_ISSUES = 600


def _point_location(native_x: float, native_y: float) -> dict:
    # GEO-MAP X = northing, Y = easting; Canvas = (Y, -X).
    return {"x": round(float(native_y), 4), "y": round(-float(native_x), 4)}


def _bounds(entry, other=None) -> list:
    if other is None:
        return list(entry.bbox)
    return [
        min(entry.bbox[0], other.bbox[0]),
        min(entry.bbox[1], other.bbox[1]),
        max(entry.bbox[2], other.bbox[2]),
        max(entry.bbox[3], other.bbox[3]),
    ]


def inspect_topology(entries, *, document_token: str, revision: int,
                     limit: int = MAX_ISSUES) -> dict:
    """Survey the current in-memory revision without changing it.

    Results are intentionally *suspicions*, not cadastral corrections:
    topological overlap may be an intended GEO-MAP overlay; enclosed
    courtyards and uncatalogued land-use regions can be legitimate.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_ISSUES:
        raise ValueError("Limit błędów musi być w zakresie 1–600.")
    total = len(entries)
    included = entries[:MAX_AUDIT_OBJECTS]
    skipped = total-len(included)
    issues = []
    counts = defaultdict(int)
    truncated = False
    pair_checks = 0
    by_code = defaultdict(list)

    def append(kind, severity, title, description, entry, other=None,
               *, location=None, area=None, can_delete_duplicate=False):
        nonlocal truncated
        counts[kind] += 1
        if len(issues) >= limit:
            truncated = True
            return
        source = entry.bbox
        bounds = _bounds(entry, other) if entry else None
        x = (source[0]+source[2])/2 if entry else 0
        y = (source[1]+source[3])/2 if entry else 0
        if location is None:
            location = {"x":round(x,4),"y":round(y,4)}
        item = {
            "id": "audit-" + str(len(issues)+1), "kind": kind,
            "severity": severity, "title": title,
            "description": description,
            "ids": [entry.fid] + ([other.fid] if other else []),
            "code": entry.obj.code,
            "bounds": bounds, "location": location,
            "canDeleteDuplicate": can_delete_duplicate,
        }
        if area is not None:
            item["areaM2"] = round(float(area), 5)
        issues.append(item)

    # Create valid geometry only for plausible cadastral polygons.
    # Open lines of unrelated codes are not "broken polygons".
    for entry in included:
        obj = entry.obj
        if obj.code not in POLYGON_CODES:
            continue
        if not obj.is_closed:
            if len(obj.points) >= 3 and obj.code in {"5216", "5220", "5230", "5310"}:
                append("open", "high", "Niezamknięty obrys",
                       "Obiekt o kodzie poligonowym nie ma zamkniętego konturu P. "
                       "Sprawdź, czy nie jest celowo linią.", entry)
            continue
        try:
            shape = geometry_of(obj)
        except (ValueError, TypeError, ArithmeticError, GEOSException):
            append("invalid", "high", "Niepoprawny poligon",
                   "Obrys jest pusty, samoprzecinający się albo zawiera "
                   "nieprawidłowe pierścienie. Sprawdź węzły i części P.",
                   entry)
            continue
        if shape.is_empty or not shape.is_valid or shape.area < .000001:
            append("invalid", "high", "Niepoprawny poligon",
                   "Poligon ma zerową powierzchnię lub nieprawidłowy obrys.",
                   entry)
            continue
        vertices = tuple((round(p.x, 4), round(p.y, 4))
                         for p in obj.points[:-1] if p.point_type != 0)
        by_code[obj.code].append((entry, shape, vertices))

    # Independent per-code STRtrees: compare only genuine same-code peers.
    for code, records in by_code.items():
        if len(records) < 2:
            continue
        geoms = [r[1] for r in records]
        tree = STRtree(geoms)
        for first, (entry, shape, vertices) in enumerate(records):
            if pair_checks >= MAX_PAIR_CHECKS:
                truncated = True
                break
            # Query a slightly expanded bounding box to catch narrow slits
            # even when polygons are disjoint but almost adjacent.
            lowx, lowy, highx, highy = shape.bounds
            around = box(lowx-GAP_TOLERANCE, lowy-GAP_TOLERANCE,
                         highx+GAP_TOLERANCE, highy+GAP_TOLERANCE)
            for raw_index in tree.query(around):
                second = int(raw_index)
                if second <= first:
                    continue
                pair_checks += 1
                if pair_checks > MAX_PAIR_CHECKS:
                    truncated = True
                    break
                other, neighbor, neighbor_vertices = records[second]
                try:
                    intersects = shape.intersects(neighbor)
                    if intersects:
                        common = shape.intersection(neighbor)
                        overlap = common.area if not common.is_empty else 0.
                        if overlap > MIN_OVERLAP_AREA:
                            # Same geometry is suspicious even with distinct
                            # attributes. Automatic deletion is permitted
                            # ONLY if ALL attributes match exactly.
                            duplicated = shape.equals(neighbor)
                            # :ID is the identity, not a semantic
                            # cadastral attribute. Naturally two distinct
                            # records cannot share the same :ID. Ignore
                            # only that field, still compare every OTHER
                            # attribute and the native symbol/pen style.
                            fields_a = {
                                key:value for key,value in entry.obj.fields.items()
                                if str(key).upper() != "ID"
                            }
                            fields_b = {
                                key:value for key,value in other.obj.fields.items()
                                if str(key).upper() != "ID"
                            }
                            safe_delete = (
                                duplicated and fields_a == fields_b and
                                entry.obj.style == other.obj.style and
                                bool(entry.obj.uid) and bool(other.obj.uid)
                            )
                            center = common.representative_point()
                            append(
                                "duplicate" if duplicated else "overlap",
                                "high" if duplicated else "medium",
                                "Powielony poligon" if duplicated else "Nakładające się poligony",
                                ("Dwa obiekty o tym samym kodzie mają identyczną "
                                 "geometrię. Atrybuty są jednakowe; sprawdź, "
                                 "czy drugi obiekt jest zbędny."
                                 if safe_delete else
                                 "Poligony mają identyczną geometrię, ale "
                                 "różnią się atrybutami — nie usuwaj automatycznie."
                                 if duplicated else
                                 "Części obiektów tego samego kodu zajmują "
                                 "ten sam obszar. Sprawdź, czy nakładka jest celowa."),
                                entry, other,
                                location=_point_location(center.x, center.y),
                                area=overlap,
                                can_delete_duplicate=safe_delete,
                            )
                    else:
                        distance = shape.distance(neighbor)
                        if 0 < distance <= GAP_TOLERANCE:
                            edge_area = (shape.boundary.buffer(GAP_TOLERANCE)
                                         .intersection(neighbor.boundary.buffer(
                                             GAP_TOLERANCE))).area
                            if edge_area > GAP_TOLERANCE * .35:
                                near = shape.boundary.interpolate(
                                    shape.boundary.project(neighbor.representative_point()))
                                append(
                                    "gap", "medium", "Wąska szczelina między obrysami",
                                    "Granice obiektów tego samego kodu są bardzo "
                                    "blisko, ale się nie stykają. Oceń, czy "
                                    "szczelina jest zamierzona.",
                                    entry, other, location=_point_location(near.x, near.y),
                                )

                    # T-junction: a vertex of one same-code polygon lies
                    # on the other's edge without an explicit native P.
                    # Do not require FOREIGN-CODE shared nodes.
                    if (shape.distance(neighbor) <= NODE_TOLERANCE and
                            len(vertices) <= 1500 and
                            len(neighbor_vertices) <= 1500):
                        found = None
                        for src, dst, edge in (
                                (vertices, neighbor_vertices, neighbor.boundary),
                                (neighbor_vertices, vertices, shape.boundary)):
                            if found is not None:
                                break
                            for vx, vy in src:
                                if any(hypot(vx-wx, vy-wy) <= NODE_TOLERANCE
                                       for wx, wy in dst):
                                    continue
                                if edge.distance(Point(vx, vy)) <= NODE_TOLERANCE:
                                    found = (vx, vy)
                                    break
                        if found is not None:
                            append(
                                "node", "medium", "Brak odpowiadającego węzła",
                                "Punkt P jednego obiektu leży na krawędzi innego "
                                "obiektu tego samego kodu, ale sąsiad nie ma "
                                "w tym miejscu własnego punktu P. Edytuj "
                                "węzły z włączonymi wspólnymi węzłami.",
                                entry, other,
                                location=_point_location(*found),
                            )
                except (ValueError, ArithmeticError, GEOSException):
                    # The invalid single-object geometry was already warned
                    # about above. One pair must not kill the entire scan.
                    continue
            if pair_checks > MAX_PAIR_CHECKS:
                break

    # Detect *small enclosed* holes in an otherwise joined parcel/use
    # mosaic. Never invent a missing surrounding parcel outside the map.
    # Not a blanket "any empty map is a gap" check.
    for code in ("5216", "5220", "5230"):
        group = by_code.get(code, [])
        if not 2 <= len(group) <= 1800 or truncated:
            continue
        try:
            shapes = [g for _, g, _ in group]
            coverage = unary_union(shapes)
            edges = unary_union([g.boundary for g in shapes])
            detected = 0
            for candidate in polygonize(edges):
                area = candidate.area
                if not .0005 <= area <= 3.0:
                    continue
                probe = candidate.representative_point()
                if coverage.covers(probe):
                    continue
                # A closed internal gap is surrounded by the overall
                # coverage; outer empty space remains unreported.
                if not coverage.convex_hull.contains(probe):
                    continue
                neighbor = min(group, key=lambda r:r[1].distance(probe))[0]
                append(
                    "gap", "medium", "Mała zamknięta szczelina",
                    "Niewielki pusty obszar wewnątrz obrysów tego kodu. "
                    "Może to być zamierzona enklawa — sprawdź przed korektą.",
                    neighbor, location=_point_location(probe.x,probe.y),
                    area=area,
                )
                detected += 1
                if detected >= 40:
                    truncated = True
                    break
        except (ValueError, ArithmeticError):
            continue

    return {
        "documentToken": document_token,
        "revision": revision,
        "issues": issues,
        "counts": dict(counts),
        "detected": sum(counts.values()),
        "returned": len(issues),
        "checked": len(included),
        "totalObjects": total,
        "truncated": truncated,
        "skippedObjects": skipped,
        "pairChecks": pair_checks,
        "thresholds": {
            "nodeToleranceM": NODE_TOLERANCE,
            "narrowGapM": GAP_TOLERANCE,
            "minimumOverlapM2": MIN_OVERLAP_AREA,
        },
        "guidance": (
            "Raport pokazuje potencjalne problemy, nie decyzje geodezyjne. "
            "Nakładki, enklawy i styki mogą być prawidłowe. "
            "Sprawdź każdy przypadek przed korektą; Ctrl+Z cofa zmiany."
        ),
    }
