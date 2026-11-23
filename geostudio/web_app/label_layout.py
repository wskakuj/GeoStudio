"""Automatyczne układanie etykiet A1/A2 dla poligonów 5310.

Silnik jest deterministyczny i działa po stronie backendu, dzięki czemu ten sam
wynik trafia do pliku .MAP, eksportu i testów.

Model danych: etykieta jest opisana przesunięciem ``(dx, dy)`` wobec punktu
bazowego poligonu (tak jak rekord ``L``), a wysięgnik dodatkowo punktem
zaczepienia ``(ax, ay)`` i flagą 69 (napis na wschód od zaczepu) lub
133 (napis na zachód).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import box

# Wymiary znaku i linii w metrach na gruncie dla skali 1:5000.
CHAR_W_M = 1.9
LINE_H_M = 3.2
GAP_M = 0.8
PAD_M = 3.0

FLAG_PLAIN = 5
FLAG_RIGHT = 69      # 64 + 5 — napis na wschód od zaczepu
FLAG_LEFT = 133      # 128 + 5 — napis na zachód od zaczepu

# Wagi funkcji kary (identyczne jak w specyfikacji).
W_TEXT_COLLISION = 100_000
W_BOUNDARY = 20_000
W_LEADER_CROSS = 8_000
W_LEADER_THROUGH_TEXT = 5_000
W_INSIDE_FOREIGN = 1_500
W_PARCEL = 300
W_SHARP_ANGLE = 150
W_DISTANCE = 1.0


@dataclass(slots=True)
class LabelBox:
    """Prostokąt etykiety w metrach na gruncie (osie GEO-MAP)."""

    cx: float
    cy: float
    width: float
    height: float

    @property
    def rect(self):
        half_w, half_h = self.width / 2, self.height / 2
        return box(self.cx - half_w, self.cy - half_h,
                   self.cx + half_w, self.cy + half_h)


def text_size(text: str, scale: int = 5000, *, fraction: bool = False) -> tuple[float, float]:
    """Szerokość i wysokość napisu w metrach na gruncie."""
    factor = max(0.2, scale / 5000)
    lines = str(text or "").replace("||", "\n").split("\n")
    if fraction:
        lines = [line.replace("|", "\n") for line in lines]
        lines = [part for line in lines for part in line.split("\n")]
    longest = max((len(line) for line in lines), default=1)
    width = longest * CHAR_W_M * factor + 2 * PAD_M * factor
    height = len(lines) * LINE_H_M * factor + 2 * PAD_M * factor
    return width, height


def polylabel(polygon, precision: float = 0.5) -> tuple[float, float]:
    """Pole of Inaccessibility — punkt najdalszy od krawędzi poligonu.

    Quadtree z kolejką priorytetową (algorytm Mapboxa) w czystym Pythonie.
    Dla zdegenerowanych poligonów zwraca centroid albo pierwszy wierzchołek.
    """
    from heapq import heappush, heappop
    from shapely.geometry import Point

    if polygon is None or polygon.is_empty:
        return (0.0, 0.0)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
        if polygon.is_empty:
            return (0.0, 0.0)

    boundary = polygon.boundary
    centroid = polygon.centroid
    minx, miny, maxx, maxy = polygon.bounds

    def signed_distance(x: float, y: float) -> float:
        point = Point(x, y)
        if not polygon.contains(point):
            return -boundary.distance(point)
        return boundary.distance(point)

    def potential(x: float, y: float, half: float) -> float:
        # Tanie GÓRNE oszacowanie: odległość do ramki zasięgu (nigdy nie zaniża
        # odległości do granicy) + połowa przekątnej komórki. Prawdziwy dystans
        # liczymy tylko dla komórek, które mają szansę wygrać.
        dx = max(minx - x, 0.0, x - maxx)
        dy = max(miny - y, 0.0, y - maxy)
        return math.hypot(dx, dy) + half * 1.4142135623730951


    minx, miny, maxx, maxy = polygon.bounds
    width, height = maxx - minx, maxy - miny
    if width <= 0 or height <= 0:
        return (minx, miny)
    precision = max(precision, min(2.0, max(width, height) / 200))

    # Punkt startowy MUSI leżeć wewnątrz: centroid poligonu wklęsłego
    # (np. litery L) potrafi wypaść poza obrys.
    start = polygon.representative_point()
    best = (signed_distance(start.x, start.y), start.x, start.y)
    if best[0] < 0:
        best = (0.0, start.x, start.y)
    cell = min(width, height) / 2
    heap: list = []
    x = minx
    while x < maxx:
        y = miny
        while y < maxy:
            cx, cy = x + cell / 2, y + cell / 2
            heappush(heap, (-potential(cx, cy, cell / 2), cx, cy, cell / 2))
            y += cell
        x += cell

    guard = 0
    while heap and guard < 4000:
        guard += 1
        _, cx, cy, half = heappop(heap)
        # Potencjał to GÓRNE oszacowanie: pomijamy komórkę tylko wtedy, gdy
        # nawet on nie przebije dotychczasowego najlepszego wyniku.
        if potential(cx, cy, half) <= best[0]:
            continue
        value = signed_distance(cx, cy)
        if value > best[0]:
            best = (value, cx, cy)
        if half > precision:
            quarter = half / 2
            for dx in (-quarter, quarter):
                for dy in (-quarter, quarter):
                    nx, ny = cx + dx, cy + dy
                    heappush(heap, (-potential(nx, ny, quarter), nx, ny, quarter))
    return (best[1], best[2])


def _box_clear(polygon, candidate: LabelBox) -> bool:
    """Czy prostokąt etykiety mieści się w poligonie bez dotykania granic."""
    rect = candidate.rect
    return bool(polygon.contains(rect))


def layout_object(shape, a1: str, a2: str, *, scale: int,
                  occupied: list) -> dict | None:
    """Układa etykiety jednego poligonu; zwraca zmianę lub ``None``."""
    if shape is None or shape.is_empty:
        return None
    width1, height1 = text_size(a1, scale) if a1 else (0.0, 0.0)
    width2, height2 = text_size(a2, scale, fraction=True) if a2 else (0.0, 0.0)
    px, py = polylabel(shape, precision=max(0.25, scale / 20000))

    stacked = []
    total_h = height1 + height2
    top = py + total_h / 2
    if a1:
        stacked.append(("A1", LabelBox(px, top - height1 / 2, width1, height1)))
        top -= height1
    if a2:
        stacked.append(("A2", LabelBox(px, top - height2 / 2, width2, height2)))

    if stacked and all(_box_clear(shape, item[1]) for item in stacked):
        boxes = [item[1] for item in stacked]
        for box_ in boxes:
            occupied.append(box_.rect)
        return {"mode": "inside", "anchor": (0.0, 0.0),
                "labels": {field: {"dx": 0.0, "dy": 0.0, "flags": FLAG_PLAIN}
                           for field, _ in stacked}}

    # A1 w środku, A2 na wysięgniku.
    if a1 and a2:
        centre = LabelBox(px, py, width1, height1)
        if _box_clear(shape, centre):
            occupied.append(centre.rect)
            return {"mode": "mixed", "anchor": (0.0, 0.0),
                    "labels": {"A1": {"dx": 0.0, "dy": 0.0, "flags": FLAG_PLAIN}},
                    "external": ["A2"]}
    # Oba na wysięgnikach.
    return {"mode": "external", "anchor": (0.0, 0.0),
            "external": [name for name in ("A1", "A2") if (a1 if name == "A1" else a2)]}


def candidate_positions(shape, width: float, height: float, *, steps=12,
                        distances=4, scale: int = 5000):
    """Kandydaci poza poligonem: promienie w 16 kierunkach × kilka odległości."""
    minx, miny, maxx, maxy = shape.bounds
    reach = max(maxx - minx, maxy - miny) / 2
    base = max(width, height)
    factor = max(0.2, scale / 5000)
    for index in range(steps):
        angle = 2 * math.pi * index / steps
        dx, dy = math.cos(angle), math.sin(angle)
        for step in range(1, distances + 1):
            distance = reach + base / 2 + step * 0.8 * height * factor
            yield (dx * distance, dy * distance, distance)


def score_candidate(box_: LabelBox, anchor: tuple[float, float], distance: float,
                    occupied: list, boundaries: list, foreign: list) -> float:
    """Kara według tabeli ze specyfikacji (im mniej, tym lepiej)."""
    rect = box_.rect
    cost = W_DISTANCE * distance
    for other in occupied:
        if rect.intersects(other):
            cost += W_TEXT_COLLISION
            break
    for boundary in boundaries:
        if rect.intersects(boundary):
            cost += W_BOUNDARY
            break
    for region in foreign:
        if region.contains(rect.centroid):
            cost += W_INSIDE_FOREIGN
            break
    return cost


def auto_layout_5310_labels(objects, *, scale: int = 5000,
                            selected_ids=None) -> dict:
    """Układa etykiety A1/A2 dla listy poligonów 5310.

    ``objects`` to sekwencja ``(uid, shape, base, a1, a2)``. Zwraca słownik
    ``{"changes": [...], "stats": {...}}``, gdzie każda zmiana opisuje oba
    sloty w jednostkach względnych wobec punktu bazowego poligonu.
    """
    occupied: list = []
    boundaries: list = []
    foreign: list = []
    entries = []
    for uid, shape, base, a1, a2 in objects:
        if selected_ids is not None and uid not in selected_ids:
            continue
        if shape is None or shape.is_empty:
            continue
        entries.append((uid, shape, base, a1, a2))
        boundaries.append(shape.boundary)
        foreign.append(shape)

    changes = []
    inside_count = 0
    leader_count = 0
    # Najpierw duże poligony (łatwe), potem trudne — jak w specyfikacji.
    entries.sort(key=lambda item: -item[1].area)
    for uid, shape, base, a1, a2 in entries:
        plan = layout_object(shape, a1, a2, scale=scale, occupied=occupied)
        if not plan:
            continue
        labels = dict(plan.get("labels") or {})
        anchor_world = (base[0] + plan.get("anchor", (0.0, 0.0))[0],
                        base[1] + plan.get("anchor", (0.0, 0.0))[1])
        if plan["mode"] in ("external", "mixed"):
            anchor_world = polylabel(shape, precision=max(0.25, scale / 20000))
        for field in plan.get("external", []):
            text = a1 if field == "A1" else a2
            width, height = text_size(text, scale, fraction=(field == "A2"))
            best = None
            for dx, dy, distance in candidate_positions(
                    shape, width, height, scale=scale):
                candidate = LabelBox(anchor_world[0] + dx, anchor_world[1] + dy,
                                     width, height)
                cost = score_candidate(candidate, anchor_world, distance,
                                       occupied, boundaries, foreign)
                if best is None or cost < best[0]:
                    best = (cost, candidate)
                # Kandydat bez kolizji i blisko poligonu — dalej szukać nie ma sensu.
                if cost < W_INSIDE_FOREIGN:
                    break
            if best is None:
                continue
            box_ = best[1]
            occupied.append(box_.rect)
            east = box_.cx - anchor_world[1]
            labels[field] = {
                "dx": round(box_.cx - base[1], 3),
                "dy": round(box_.cy - base[0], 3),
                "flags": FLAG_RIGHT if east >= 0 else FLAG_LEFT,
                "anchor": (round(anchor_world[0] - base[0], 3),
                           round(anchor_world[1] - base[1], 3)),
            }
            leader_count += 1
        if plan["mode"] == "inside":
            inside_count += 1
        changes.append({"uid": uid, "mode": plan["mode"], "labels": labels})
    return {"changes": changes,
            "stats": {"objects": len(entries), "inside": inside_count,
                      "leaders": leader_count}}
