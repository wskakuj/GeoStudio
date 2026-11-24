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

# ── Metryka napisu zgodna z RYSOWANIEM (map.js → labelFontSize) ──────────
# Klient liczy wysokość glifu w metrach na gruncie jako:
#     worldTextHeight = px * 2500 * 0.0254 / 96
# czyli 16 px daje ~10,58 m. Wcześniejszy model (3,2 m na linię) był ponad
# trzykrotnie za mały, przez co silnik "nie widział" nakładań i wychodzenia
# napisów na linie — etykiety wyglądały źle mimo poprawnych współrzędnych.
LABEL_PX = 16.0             # bazowa wielkość napisu 5310 w stylu
LABEL_REF_SCALE = 2500.0    # kalibracja klienta (stała, nie zależna od skali)
GLYPH_H_M = LABEL_PX * LABEL_REF_SCALE * 0.0254 / 96.0     # ≈ 10,58 m
ADVANCE = 0.58              # średnia szerokość znaku / wysokość glifu
GAP_M = 0.8
PAD_M = 1.0

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
        """Prostokąt w osiach mapy: x = PÓŁNOC, y = WSCHÓD.

        Napis biegnie poziomo na wydruku, czyli wschód–zachód (oś y), a jego
        wysokość odkłada się wzdłuż północy (oś x). Wcześniej szerokość szła
        po północy, więc model kolizji był obrócony o 90° — etykiety
        „wchodziły” na linie i na siebie mimo poprawnych współrzędnych.
        """
        half_w, half_h = self.width / 2, self.height / 2
        return box(self.cx - half_h, self.cy - half_w,
                   self.cx + half_h, self.cy + half_w)


def text_size(text: str, scale: int = 5000, *, fraction: bool = False) -> tuple[float, float]:
    """Szerokość i wysokość napisu w metrach na gruncie.

    Liczona TĄ SAMĄ metryką, którą rysuje klient (16 px × 2500 × 0,0254 / 96),
    żeby prostokąt kolizji odpowiadał temu, co naprawdę widać na mapie.
    """
    lines = str(text or "").replace("||", "\n").split("\n")
    if fraction:
        lines = [line.replace("|", "\n") for line in lines]
        lines = [part for line in lines for part in line.split("\n")]
    longest = max((len(line) for line in lines), default=1)
    width = longest * GLYPH_H_M * ADVANCE + 2 * PAD_M
    height = len(lines) * GLYPH_H_M + 2 * PAD_M
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


def _fits(shape, box_: LabelBox, margin: float) -> bool:
    """Prostokąt leży wewnątrz poligonu i nie dotyka granicy (margines)."""
    rect = box_.rect
    if not shape.contains(rect):
        return False
    return rect.distance(shape.boundary) >= margin


def _clear_of(box_: LabelBox, occupied: list, boundaries: list,
              foreign: list, own) -> bool:
    """Twarde warunki: brak kolizji z etykietami, obcymi granicami i obcymi poligonami."""
    rect = box_.rect
    for other in occupied:
        if rect.intersects(other):
            return False
    for boundary in boundaries:
        if boundary is own:
            continue
        try:
            if rect.intersection(boundary).length > 0.01:
                return False
        except Exception:                            # noqa: BLE001
            if rect.intersects(boundary):
                return False
    for region in foreign:
        if region is own:
            continue
        if region.contains(rect.centroid):
            return False
    return True


def _single_spots(shape, width: float, height: float,
                  north: float, east: float, margin: float):
    """Kolejne pozycje wewnątrz poligonu: środek, potem siatka wokół niego."""
    yield LabelBox(north, east, width, height)
    minx, miny, maxx, maxy = shape.bounds
    span_n = maxx - minx
    span_e = maxy - miny
    for step_n in (-0.25, 0.25, -0.15, 0.15, 0.0):
        for step_e in (0.0, -0.25, 0.25, -0.15, 0.15):
            if not step_n and not step_e:
                continue
            yield LabelBox(north + step_n * span_n, east + step_e * span_e,
                           width, height)


def _inside_spots(shape, width1, height1, width2, height2,
                  north: float, east: float, margin: float):
    """Pary (A1, A2) do wypróbowania wewnątrz poligonu."""
    for a1_box in _single_spots(shape, width1, height1, north, east, margin):
        yield (a1_box, None)
    for a2_box in _single_spots(shape, width2, height2, north, east, margin):
        yield (None, a2_box)


def _column_spots(shape, north: float, east: float):
    """Kolejne środki kolumny A1+A2 wewnątrz poligonu: polylabel, potem siatka."""
    yield north, east
    minx, miny, maxx, maxy = shape.bounds
    span_n, span_e = maxx - minx, maxy - miny
    for step_n in (0.0, -0.2, 0.2, -0.12, 0.12, -0.3, 0.3):
        for step_e in (0.0, -0.2, 0.2, -0.12, 0.12, -0.3, 0.3):
            if not step_n and not step_e:
                continue
            yield north + step_n * span_n, east + step_e * span_e


def layout_object(shape, a1: str, a2: str, *, scale: int,
                  occupied: list, boundaries=None, foreign=None) -> dict | None:
    """Planuje JEDNĄ kolumnę A1+A2 dla poligonu.

    Klient rysuje A1 i A2 jako kolumnę wyśrodkowaną na (x, y), więc silnik
    liczy kolizje dla całej kolumny — nie dla dwóch osobnych prostokątów.
    Kolejność: (1) kolumna w środku poligonu, (2) kolumna na zewnątrz
    z wysięgnikiem do środka.
    """
    if shape is None or shape.is_empty:
        return None
    margin = 0.35 * GLYPH_H_M
    width1, height1 = text_size(a1, scale) if a1 else (0.0, 0.0)
    width2, height2 = text_size(a2, scale, fraction=True) if a2 else (0.0, 0.0)
    parts = [(w, h) for w, h in ((width1, height1), (width2, height2)) if w]
    if not parts:
        return None
    width = max(w for w, _h in parts)
    height = sum(h for _w, h in parts) + GAP_M * (len(parts) - 1)

    north, east = polylabel(shape, precision=max(0.25, scale / 20000))
    boundaries = boundaries or []
    foreign = foreign or []

    # (1) w środku poligonu — najczytelniej.
    for cand_n, cand_e in _column_spots(shape, north, east):
        box_ = LabelBox(cand_n, cand_e, width, height)
        if (_fits(shape, box_, margin) and
                _clear_of(box_, occupied, boundaries, foreign, shape)):
            occupied.append(box_.rect)
            return {"mode": "inside", "anchor": (cand_n, cand_e),
                    "box": box_, "inside": True}

    # (1b) nie mieści się cała kolumna — spróbuj sam A1 w środku,
    #      a A2 z wysięgnikiem. Tak robi GEO-MAP dla ciasnych poligonów.
    if a1 and a2 and width1 and height1:
        for cand_n, cand_e in _column_spots(shape, north, east):
            single = LabelBox(cand_n, cand_e, width1, height1)
            if (_fits(shape, single, margin) and
                    _clear_of(single, occupied, boundaries, foreign, shape)):
                occupied.append(single.rect)
                return {"mode": "mixed", "anchor": (north, east),
                        "box": single, "inside": True, "partial": True}

    # (2) na zewnątrz, z wysięgnikiem do punktu w środku poligonu.
    anchor = (north, east)
    best = None
    fallback = None
    for dx, dy, distance in candidate_positions(shape, width, height,
                                               scale=scale):
        candidate = LabelBox(anchor[0] + dx, anchor[1] + dy, width, height)
        if fallback is None:
            fallback = candidate
        if not _clear_of(candidate, occupied, boundaries, foreign, shape):
            continue
        cost = score_candidate(candidate, anchor, distance, occupied,
                               boundaries, foreign)
        if best is None or cost < best[0]:
            best = (cost, candidate)
    box_ = best[1] if best is not None else fallback
    if box_ is None:
        return None
    occupied.append(box_.rect)
    return {"mode": "external", "anchor": anchor, "box": box_, "inside": False}


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


def _external_spot(shape, anchor, width: float, height: float,
                   occupied: list, boundaries: list, foreign: list,
                   scale: int):
    """Najlepsze miejsce na zewnątrz dla pojedynczego napisu."""
    best = None
    fallback = None
    for dx, dy, distance in candidate_positions(shape, width, height,
                                               scale=scale):
        candidate = LabelBox(anchor[0] + dx, anchor[1] + dy, width, height)
        if fallback is None:
            fallback = candidate
        if not _clear_of(candidate, occupied, boundaries, foreign, shape):
            continue
        cost = score_candidate(candidate, anchor, distance, occupied,
                               boundaries, foreign)
        if best is None or cost < best[0]:
            best = (cost, candidate)
    return best[1] if best is not None else fallback


def auto_layout_5310_labels(objects, *, scale: int = 5000,
                            selected_ids=None) -> dict:
    """Układa etykiety A1/A2 dla listy poligonów 5310.

    ``objects`` to sekwencja ``(uid, shape, base, a1, a2)``. Zwraca słownik
    ``{"changes": [...], "stats": {...}}``; każda zmiana opisuje oba sloty
    w jednostkach względnych wobec punktu bazowego poligonu.
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
        if not (a1 or a2):
            continue
        entries.append((uid, shape, base, a1, a2))
        boundaries.append(shape.boundary)
        foreign.append(shape)

    changes = []
    inside_count = 0
    leader_count = 0
    # Najpierw duże poligony (łatwe), potem trudne.
    entries.sort(key=lambda item: -item[1].area)
    for uid, shape, base, a1, a2 in entries:
        plan = layout_object(shape, a1, a2, scale=scale, occupied=occupied,
                             boundaries=boundaries, foreign=foreign)
        if not plan or plan.get("box") is None:
            continue
        box_ = plan["box"]
        dx = round(box_.cx - base[0], 3)
        dy = round(box_.cy - base[1], 3)
        labels: dict = {}
        if plan["inside"] and not plan.get("partial"):
            for field, text in (("A1", a1), ("A2", a2)):
                if text:
                    labels[field] = {"dx": dx, "dy": dy, "flags": FLAG_PLAIN}
            inside_count += 1
        elif plan.get("partial"):
            # A1 w środku, A2 z wysięgnikiem do tego samego punktu.
            labels["A1"] = {"dx": dx, "dy": dy, "flags": FLAG_PLAIN}
            inside_count += 1
            anchor = plan["anchor"]
            width2, height2 = text_size(a2, scale, fraction=True)
            spot = _external_spot(shape, anchor, width2, height2, occupied,
                                  boundaries, foreign, scale)
            if spot is not None:
                labels["A2"] = {
                    "dx": round(spot.cx - base[0], 3),
                    "dy": round(spot.cy - base[1], 3),
                    "flags": FLAG_RIGHT if spot.cy >= anchor[1] else FLAG_LEFT,
                    "anchor": (round(anchor[0] - base[0], 3),
                               round(anchor[1] - base[1], 3)),
                }
                occupied.append(spot.rect)
                leader_count += 1
        else:
            # Oba napisy stoją w jednej kolumnie z wysięgnikiem do środka.
            anchor = plan["anchor"]
            east = box_.cy - anchor[1]
            flags = FLAG_RIGHT if east >= 0 else FLAG_LEFT
            for field, text in (("A1", a1), ("A2", a2)):
                if not text:
                    continue
                labels[field] = {
                    "dx": dx, "dy": dy, "flags": flags,
                    "anchor": (round(anchor[0] - base[0], 3),
                               round(anchor[1] - base[1], 3)),
                }
                leader_count += 1
        changes.append({"uid": uid, "mode": plan["mode"], "labels": labels})
    return {"changes": changes,
            "stats": {"objects": len(entries), "inside": inside_count,
                      "leaders": leader_count}}
