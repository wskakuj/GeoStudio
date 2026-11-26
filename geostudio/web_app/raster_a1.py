"""Local, bounded OCR of handwritten map numbers and their callout leaders.

Input is the already normalized raster preview, regardless of its source format.
No image, coordinate or text is sent outside GeoStudio. The model files must be
present in the installed wheel; missing files are an error, never a download.
The caller owns the image/result cache. This module owns one locked CPU engine.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from math import ceil, cos, pi, sin
from pathlib import Path
import os
import re
from threading import Lock

MAX_PIXELS = 14_000_000
MAX_BYTES = 48 * 1024 * 1024
MODEL_VERSION = "rapidocr-3.10.0-ppocr-v6-small"
_MODELS = {
    "PP-OCRv6_rec_small.onnx": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
    "PP-OCRv6_det_small.onnx": "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
}
_ENGINE = None
_ENGINE_LOCK = Lock()


def _engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    # The environment opt-out precedes import: recent ONNX Runtime wheels can
    # initialize their uploader before disable_telemetry_events() is callable.
    os.environ["ORT_DISABLE_TELEMETRY"] = "1"
    import onnxruntime

    # ONNX Runtime enables platform telemetry by default. Disable it before
    # importing/constructing the OCR engine or opening any inference session.
    onnxruntime.disable_telemetry_events()
    import rapidocr
    from rapidocr import RapidOCR

    folder = Path(rapidocr.__file__).parent / "models"
    for name, digest in _MODELS.items():
        path = folder / name
        if not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError("Brak kompletnego lokalnego modelu odczytu A1. Zainstaluj ponownie GeoStudio.")
    _ENGINE = RapidOCR(params={
        "Global.log_level": "error", "Global.use_cls": False,
        "Global.max_side_len": 1800,
        "Det.model_path": str(folder / "PP-OCRv6_det_small.onnx"),
        "Rec.model_path": str(folder / "PP-OCRv6_rec_small.onnx"),
        "Det.limit_side_len": 960, "Det.limit_type": "max",
        "EngineConfig.onnxruntime.intra_op_num_threads": 2,
        "EngineConfig.onnxruntime.inter_op_num_threads": 1,
        "EngineConfig.onnxruntime.use_cuda": False,
        "EngineConfig.onnxruntime.use_dml": False,
    })
    return _ENGINE


def _numeric(text):
    # Delimiters may be the enclosing pen circle. Never guess O→0, l→1 or
    # strip arbitrary letters from an unreadable handwritten identifier.
    value = str(text or "").strip().strip("()[]{} ")
    return value if re.fullmatch(r"[0-9]{1,5}", value) else None


def _read_line(engine, ink):
    import cv2
    import numpy as np

    ys, xs = np.where(ink)
    if not len(xs):
        return None
    cropped = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    if cropped.shape[0] < 5 or cropped.shape[1] < 2:
        return None
    image = np.pad(255 - cropped.astype(np.uint8) * 255, 6, constant_values=255)
    image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    image = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    result = engine(image, use_det=False, use_cls=False)
    if not result.txts:
        return None
    text = _numeric(result.txts[0])
    return (text, float(result.scores[0])) if text else None


def _box_iou(a, b):
    area = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - area
    return area / union if union else 0


def _text_candidates(engine, mask):
    import cv2
    import numpy as np

    height, width = mask.shape
    found = []
    tile, stride = 960, 800
    for top in range(0, height, stride):
        for left in range(0, width, stride):
            part = mask[top:min(height, top + tile), left:min(width, left + tile)]
            if np.count_nonzero(part) < 18:
                continue
            image = cv2.cvtColor(255 - part.astype(np.uint8) * 255, cv2.COLOR_GRAY2BGR)
            result = engine(image, use_det=True, use_cls=False, text_score=.35, box_thresh=.35)
            if not result.txts:
                continue
            for raw, confidence, quad in zip(result.txts, result.scores, result.boxes):
                text = _numeric(raw)
                if not text:
                    continue
                local = [float(quad[:, 0].min()), float(quad[:, 1].min()),
                         float(quad[:, 0].max()), float(quad[:, 1].max())]
                if ((left and local[0] < 3) or (top and local[1] < 3) or
                        (left + tile < width and local[2] > part.shape[1] - 3) or
                        (top + tile < height and local[3] > part.shape[0] - 3)):
                    continue  # The overlapping tile will see the complete word.
                box = [max(0, int(local[0]) + left), max(0, int(local[1]) + top),
                       min(width, ceil(local[2]) + left), min(height, ceil(local[3]) + top)]
                if box[3] - box[1] < 7 or box[2] - box[0] < 2:
                    continue
                candidate = {"text": text, "confidence": float(confidence), "box": box}
                old = next((item for item in found if _box_iou(item["box"], box) > .45), None)
                if old is None:
                    found.append(candidate)
                elif old["text"] == text:
                    if confidence > old["confidence"]:
                        old.update(candidate)
                else:
                    old["disagreement"] = True
            if len(found) >= 600:
                return found[:600]
    return found


def _radius(circle, points):
    import numpy as np

    cx, cy, rx, ry, angle = circle[:5]
    xy = np.asarray(points, dtype=np.float64) - [cx, cy]
    ca, sa = cos(angle), sin(angle)
    u = (xy[..., 0] * ca + xy[..., 1] * sa) / rx
    v = (-xy[..., 0] * sa + xy[..., 1] * ca) / ry
    return u * u + v * v


def _circles(mask, color="blue"):
    """Find supported outer ink rings; shape fitting never interprets digits."""
    import cv2
    import numpy as np

    height, width = mask.shape
    scale = min(1., 2200 / max(width, height))
    small = cv2.resize(mask.astype(np.uint8) * 255, None, fx=scale, fy=scale,
                       interpolation=cv2.INTER_AREA)
    small = (small > 35).astype(np.uint8)
    closed = cv2.morphologyEx(small, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, hierarchy = cv2.findContours(closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    if hierarchy is not None:
        for contour, relation in zip(contours, hierarchy[0]):
            if relation[3] < 0 or len(contour) < 5:
                continue
            hull = cv2.convexHull(contour)
            if len(hull) < 5:
                continue
            (cx, cy), (dx, dy), angle = cv2.fitEllipse(hull)
            if min(dx, dy) >= 13 and max(dx, dy) <= 145 and max(dx, dy) / min(dx, dy) < 2.1:
                candidates.append((cx, cy, dx / 2, dy / 2, angle * pi / 180))
    hough = cv2.HoughCircles(cv2.GaussianBlur(small * 255, (3, 3), .7),
        cv2.HOUGH_GRADIENT, dp=1.2, minDist=12, param1=70, param2=15,
        minRadius=7, maxRadius=60)
    if hough is not None:
        candidates.extend((float(x), float(y), float(r), float(r), 0.) for x, y, r in hough[0])
    distance = cv2.distanceTransform(1 - small, cv2.DIST_L2, 3)
    theta = np.arange(72) * (2 * pi / 72)
    accepted, possible = [], []
    for cx, cy, rx, ry, angle in candidates[:4000]:
        if min(rx, ry) < 6.5 or max(rx, ry) > 75:
            continue
        ca, sa = cos(angle), sin(angle)
        xx = cx + ca * rx * np.cos(theta) - sa * ry * np.sin(theta)
        yy = cy + sa * rx * np.cos(theta) + ca * ry * np.sin(theta)
        ix, iy = np.rint(xx).astype(int), np.rint(yy).astype(int)
        if ix.min() < 1 or iy.min() < 1 or ix.max() >= small.shape[1] - 1 or iy.max() >= small.shape[0] - 1:
            continue
        quality = float(np.mean(distance[iy, ix] <= 1.6))
        if color != "dark" and quality >= .68:
            possible.append((cx, cy, rx, ry, angle, quality))
        if quality < (.94 if color == "dark" else .83) or (color == "dark" and min(rx, ry) < 11):
            continue
        l, t = max(0, int(cx - max(rx, ry))), max(0, int(cy - max(rx, ry)))
        r, b = min(small.shape[1], ceil(cx + max(rx, ry))), min(small.shape[0], ceil(cy + max(rx, ry)))
        y, x = np.mgrid[t:b, l:r]
        inside = _radius((cx, cy, rx, ry, angle), np.stack([x, y], axis=-1)) < .58
        if np.count_nonzero(small[t:b, l:r] & inside) < 4:
            continue
        accepted.append((cx, cy, rx, ry, angle, quality))
    # Prefer the complete, supported outer ring over a loop within its number.
    accepted.sort(key=lambda c: -(c[2] * c[3] * (.7 + c[5])))
    kept = []
    for circle in accepted:
        if any(float(_radius(other, circle[:2])) < .60 for other in kept):
            continue
        kept.append(circle)
        if len(kept) >= 240:
            break
    return small, scale, kept, possible


def _thin(mask):
    """Zhang–Suen thinning keeps joined pen leaders and their real endpoints."""
    import numpy as np

    image = np.pad(mask.astype(np.uint8), 1)
    for _ in range(24):
        removed = 0
        for phase in (0, 1):
            p = [image[:-2, 1:-1], image[:-2, 2:], image[1:-1, 2:], image[2:, 2:],
                 image[2:, 1:-1], image[2:, :-2], image[1:-1, :-2], image[:-2, :-2]]
            neighbours = sum(p)
            transitions = sum(((p[i] == 0) & (p[(i + 1) % 8] != 0)).astype(np.uint8) for i in range(8))
            if phase == 0:
                a, b = p[0] * p[2] * p[4], p[2] * p[4] * p[6]
            else:
                a, b = p[0] * p[2] * p[6], p[0] * p[4] * p[6]
            erase = (image[1:-1, 1:-1] != 0) & (neighbours >= 2) & (neighbours <= 6) & (transitions == 1) & (a == 0) & (b == 0)
            removed += int(np.count_nonzero(erase))
            image[1:-1, 1:-1][erase] = 0
        if not removed:
            break
    return image[1:-1, 1:-1]


def _leader_data(small, circles, scale, occluder=None):
    import cv2
    import numpy as np

    # Closing heals short scan gaps; thinning is performed before removing the
    # circles, so the outgoing leader remains attached up to its true rim.
    joined = cv2.morphologyEx(small, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # A dark printed boundary can interrupt a coloured pen leader. Longer
    # repairs are allowed only where that printed ink actually exists. Closing
    # across white paper can join an arrowhead to a nearby unrelated pen mark.
    allowed = np.zeros_like(small)
    if occluder is not None:
        printed = cv2.resize(occluder.astype(np.uint8) * 255, small.shape[::-1],
                             interpolation=cv2.INTER_AREA) > 60
        allowed = cv2.dilate(printed.astype(np.uint8), np.ones((3, 3), np.uint8))
    for kernel in (np.ones((7, 1), np.uint8), np.ones((1, 7), np.uint8),
                   np.eye(7, dtype=np.uint8), np.fliplr(np.eye(7, dtype=np.uint8))):
        joined |= cv2.morphologyEx(small, cv2.MORPH_CLOSE, kernel) & allowed
    skeleton = _thin(joined)
    _, connected_before_cut = cv2.connectedComponents(skeleton, 8)
    blocked = np.zeros_like(skeleton)
    for c in circles:
        cx, cy, rx, ry, angle = c[:5]
        cv2.ellipse(skeleton, (round(cx), round(cy)), (ceil(rx * 1.04), ceil(ry * 1.04)),
                    angle * 180 / pi, 0, 360, 0, -1)
        cv2.ellipse(blocked, (round(cx), round(cy)), (ceil(rx * 1.15), ceil(ry * 1.15)),
                    angle * 180 / pi, 0, 360, 1, -1)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(skeleton, 8)
    degree = cv2.filter2D(skeleton, cv2.CV_16S, np.ones((3, 3), np.int16))
    yy, xx = np.where((skeleton != 0) & (degree <= 2))
    terminals, all_terminals = {}, {}
    for x, y in zip(xx.tolist(), yy.tolist()):
        ident = int(labels[y, x])
        all_terminals.setdefault(ident, []).append((x, y))
        if blocked[y, x]:
            continue
        terminals.setdefault(ident, []).append((x, y))
    result = []

    def tip_direction(ident, point, steps):
        """Direction of a terminal stroke, stopping before a real junction."""
        origin = np.asarray(point, dtype=float)
        current = tuple(point)
        visited = {current}
        for _ in range(steps):
            xx, yy = current
            neighbours = [(xx + dx, yy + dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                if (dx or dy) and 0 <= yy + dy < labels.shape[0] and 0 <= xx + dx < labels.shape[1]
                and labels[yy + dy, xx + dx] == ident and (xx + dx, yy + dy) not in visited]
            if len(neighbours) != 1:
                break
            current = neighbours[0]
            visited.add(current)
        vector = origin - np.asarray(current, dtype=float)
        length = float(np.linalg.norm(vector))
        return vector / length if length >= 2 else None

    for c in circles:
        cx, cy, rx, ry, angle = c[:5]
        extent = max(rx, ry) * 1.5
        l, t = max(0, int(cx - extent)), max(0, int(cy - extent))
        r, b = min(small.shape[1], ceil(cx + extent)), min(small.shape[0], ceil(cy + extent))
        y, x = np.mgrid[t:b, l:r]
        radius = _radius(c, np.stack([x, y], axis=-1))
        ids = np.unique(labels[t:b, l:r][(radius > 1.04) & (radius < 1.9)])
        endpoints, directions, has_leader = [], [], False
        network_component = False
        components = []
        for ident in ids:
            if not ident or stats[ident, cv2.CC_STAT_AREA] < max(3, min(rx, ry) * .18):
                continue
            st = stats[ident]
            if st[cv2.CC_STAT_AREA] > 4096:
                network_component = True
                has_leader = True
                continue
            cyy, cxx = np.where(labels[st[1]:st[1] + st[3], st[0]:st[0] + st[2]] == ident)
            pixels = np.column_stack((cxx + st[0], cyy + st[1]))
            radii = _radius(c, pixels)
            maximum = float(np.max(radii))
            if maximum < 1.65:
                continue
            tips = terminals.get(int(ident), [])
            if len(tips) == 2 and len(all_terminals.get(int(ident), [])) == 2:
                # A scan gap just outside the ring leaves a simple line with
                # two visible ends. The end immediately beside the ring is
                # its beginning, not a second target. A genuine branch has
                # at least three raw terminals and does not enter this case.
                near, far = sorted(tips, key=lambda p: float(_radius(c, p)))
                near_radius, far_radius = float(_radius(c, near)), float(_radius(c, far))
                u, v = np.asarray(near) - [cx, cy], np.asarray(far) - [cx, cy]
                alignment = float(np.dot(u, v) / max(1e-9, np.linalg.norm(u) * np.linalg.norm(v)))
                if 1.15 < near_radius < 2.25 and far_radius > 2.4 and alignment > .8:
                    tips = [far]
            tip_vectors = [tip_direction(ident, p, max(4, min(12, round(min(rx, ry) * .5)))) for p in tips]
            # Preserve every terminal of a genuinely forked component. Even
            # a short branch turning back toward the ring can mark a second
            # field; radial direction alone must never erase that evidence.
            retained = list(zip(tips, tip_vectors))
            if len(all_terminals.get(int(ident), [])) == 1 and len(retained) == 1 and maximum >= 3.5:
                tip, vector = retained[0]
                radial = np.asarray(tip, dtype=float) - [cx, cy]
                outward = float(np.dot(vector, radial) / max(1e-9, np.linalg.norm(radial))) if vector is not None else 0.
                if float(_radius(c, tip)) < 2.25 and outward < -.3:
                    # The only terminal is the start at the ring, while the
                    # far stroke enters a loop/network. Its target is missing;
                    # a separate short ring fragment cannot replace that tip.
                    retained = []
            # Bounding-box corners exaggerate a short circular arc's reach.
            # Measure the actual pixels and their angular/radial movement.
            angles = np.unwrap(np.arctan2(pixels[:, 1] - cy, pixels[:, 0] - cx))
            angles = np.sort(np.mod(angles, 2 * pi))
            angular_span = 2 * pi - float(np.max(np.diff(np.r_[angles, angles[0] + 2 * pi])))
            radial_span = maximum ** .5 - float(np.min(radii)) ** .5
            ring_fragment = maximum < 3.5 and radial_span < .75 and angular_span > .25
            tiny_fragment = maximum < 2.5 and len(pixels) < max(6., min(rx, ry) * .5)
            original_component = int(connected_before_cut[pixels[0, 1], pixels[0, 0]])
            components.append((maximum, ring_fragment or tiny_fragment, retained, original_component))
        outgoing_components = {original_component for maximum, fragment, retained, original_component in components
                               if not fragment and maximum >= 3.5 and retained}
        unresolved_outgoing = any(maximum >= 3.5 and not retained
                                 for maximum, fragment, retained, _ in components if not fragment)
        for maximum, fragment, retained, original_component in components:
            # Cutting out the ring can separate two genuine arms. Their
            # shared component before that cut is positive connection
            # evidence and must survive any short-fragment heuristic.
            if fragment and outgoing_components and original_component not in outgoing_components:
                continue
            has_leader = True
            for tip, vector in retained:
                endpoints.append(tip)
                directions.append(vector)
        clusters = []
        cluster_directions = []
        for point, direction in zip(endpoints, directions):
            if float(_radius(c, point)) < 1.35:
                continue
            cluster = next((group for group in clusters if np.linalg.norm(np.mean(group, axis=0) - point) <= 7), None)
            if cluster is None:
                clusters.append([point])
                cluster_directions.append([] if direction is None else [direction])
            else:
                cluster.append(point)
                if direction is not None:
                    cluster_directions[clusters.index(cluster)].append(direction)
        ends = [[round(float(v) / scale, 3) for v in np.mean(group, axis=0)] for group in clusters]
        end_directions = []
        for vectors in cluster_directions:
            vector = np.mean(vectors, axis=0) if vectors else np.zeros(2)
            length = float(np.linalg.norm(vector))
            end_directions.append([round(float(v) / length, 5) for v in vector] if length >= .85 else None)
        network = len(ends) > 4 or network_component
        result.append({"hasLeader": has_leader, "leaderEndpoints": [] if network or unresolved_outgoing else ends,
                       "leaderDirections": [] if network or unresolved_outgoing else end_directions,
                       "leaderEndpointCount": len(ends),
                       "reason": "leader_network" if network else
                       "missing_leader" if unresolved_outgoing else
                       "branched_leader" if len(ends) > 1 else
                       "missing_leader" if has_leader and not ends else "ready",
                       "anchor": None if network or unresolved_outgoing else ends[0] if len(ends) == 1 else
                       (None if has_leader else [cx / scale, cy / scale])})
    return result


def _circle_box(circle, scale, width, height):
    cx, cy, rx, ry, angle = circle[:5]
    ex = ((rx * cos(angle)) ** 2 + (ry * sin(angle)) ** 2) ** .5
    ey = ((rx * sin(angle)) ** 2 + (ry * cos(angle)) ** 2) ** .5
    return [max(0, int((cx - ex) / scale)), max(0, int((cy - ey) / scale)),
            min(width, ceil((cx + ex) / scale)), min(height, ceil((cy + ey) / scale))]


def _consensus(readings, *, prefer_complete=True):
    readings = [(text, float(score)) for text, score in readings if text and score >= .55]
    groups = {}
    for text, score in readings:
        groups.setdefault(text, []).append(score)
    if not groups:
        return {"text": "", "confidence": 0., "status": "uncertain",
                "reason": "weak_text", "alternatives": []}
    ranked = sorted(groups.items(), key=lambda row: (sum(v >= .82 for v in row[1]), max(row[1])), reverse=True)
    text, scores = ranked[0]
    votes = sum(v >= .82 for v in scores)
    other_votes = sum(v >= .82 for v in ranked[1][1]) if len(ranked) > 1 else 0
    # Inner crops can agree on a clipped 28/67 while a wider crop reads
    # 208/167 with lower confidence. Keep that complete number for review;
    # do not promote the shorter word just because its visible digits are easy.
    longer = [(other, values) for other, values in ranked[1:] if len(other) > len(text)]
    ok = votes >= 2 and votes > other_votes and max(scores) >= .90 and not longer
    if longer and prefer_complete:
        text, scores = max(longer, key=lambda row: (len(row[0]), max(row[1])))
    return {"text": text, "confidence": round(max(scores), 5), "status": "ok" if ok else "uncertain",
            "reason": "ready" if ok else "truncated_text" if longer else
            "conflicting_text" if votes and other_votes >= votes else "weak_text",
            "alternatives": [{"text": value, "confidence": round(max(evidence), 5),
                              "votes": sum(v >= .82 for v in evidence)}
                             for value, evidence in ranked[:4]]}


def _recover_circle_text(engine, ink, radius, occluder, suggestion):
    """Recover a complete review number without promoting rotated guesses.

    Printed black strokes can cut a blue digit into several pieces. Only
    short gaps covered by actual printed ink are repaired. Rotation/cropping
    agreement is useful for a *longer* number, but not grounds to replace a
    confident number or choose between same-length alternatives automatically.
    """
    import cv2
    import numpy as np

    if suggestion["status"] == "ok":
        return suggestion
    original = ink.astype(np.uint8)
    seen, groups = set(), {}

    def inspect(part):
        signature = part.tobytes()
        if signature in seen:
            return
        seen.add(signature)
        reading = _read_line(engine, part)
        if reading and len(reading[0]) >= 2 and reading[1] >= .40:
            groups.setdefault(reading[0], []).append(reading[1])

    if occluder is not None and np.any(occluder):
        allowed = cv2.dilate(occluder.astype(np.uint8), np.ones((3, 3), np.uint8))
        for size in (3, 5, 7):
            repaired = original.copy()
            for kernel in (np.ones((size, 1), np.uint8), np.ones((1, size), np.uint8),
                           np.eye(size, dtype=np.uint8), np.fliplr(np.eye(size, dtype=np.uint8))):
                repaired |= cv2.morphologyEx(original, cv2.MORPH_CLOSE, kernel) & allowed
            if np.array_equal(repaired, original):
                continue
            for threshold in (.62, .80, .95):
                inspect(repaired & (radius < threshold))
    for threshold in (.70, .80, .90):
        part = original & (radius < threshold)
        for angle in (-10, 10, 20):
            rotated = cv2.warpAffine(part, cv2.getRotationMatrix2D(
                (part.shape[1] / 2, part.shape[0] / 2), angle, 1), part.shape[::-1],
                flags=cv2.INTER_NEAREST)
            inspect(rotated)
    candidates = [{"text": text, "confidence": round(max(scores), 5),
                   "votes": sum(score >= .55 for score in scores)} for text, scores in groups.items()]
    supported = [item for item in candidates if item["votes"] >= 2 and item["confidence"] >= .75]
    if not candidates:
        return suggestion
    choices = {item["text"]: dict(item) for item in suggestion["alternatives"]}
    for item in candidates:
        old = choices.get(item["text"])
        if old:
            item = {**item, "confidence": max(item["confidence"], old["confidence"]),
                    "votes": max(item["votes"], old.get("votes", 0))}
        choices[item["text"]] = item
    alternatives = sorted(choices.values(), key=lambda item: -item["confidence"])[:8]
    possible_truncation = any(len(item["text"]) > len(suggestion["text"]) and
                              item["confidence"] >= .55 for item in candidates)
    longer = [item for item in supported if len(item["text"]) > len(suggestion["text"])]
    if not longer:
        return {**suggestion, "alternatives": alternatives, "possibleTruncation": possible_truncation}
    longest = max(len(item["text"]) for item in longer)
    complete = [item for item in longer if len(item["text"]) == longest]
    if len(complete) != 1:
        return {**suggestion, "alternatives": alternatives, "possibleTruncation": possible_truncation}
    return {**suggestion, **complete[0], "status": "uncertain", "reason": "recovered_text",
            "alternatives": alternatives, "possibleTruncation": False}


def _has_outgoing_ink(mask, box):
    """An uncircled number can also have a leader; do not use its centre."""
    import cv2
    import numpy as np

    l, t, r, b = box
    margin = max(24, b - t)
    left, top = max(0, l - 2 * margin), max(0, t - 2 * margin)
    right, bottom = min(mask.shape[1], r + 2 * margin), min(mask.shape[0], b + 2 * margin)
    original = mask[top:bottom, left:right].astype(np.uint8)
    part = cv2.morphologyEx(original, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    # Printed map lines can interrupt a coloured pen stroke. Repair only short
    # directional gaps; broad dilation would join neighbouring numbers.
    for kernel in (np.ones((7, 1), np.uint8), np.ones((1, 7), np.uint8),
                   np.eye(7, dtype=np.uint8), np.fliplr(np.eye(7, dtype=np.uint8))):
        part |= cv2.morphologyEx(original, cv2.MORPH_CLOSE, kernel)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(part, 8)
    ids = np.unique(labels[t - top:b - top, l - left:r - left])
    for ident in ids:
        if not ident:
            continue
        x, y, w, h, area = stats[ident]
        if area < 6:
            continue
        if (x + left < l - margin * .65 or x + left + w > r + margin * .65 or
                y + top < t - margin * .65 or y + top + h > b + margin * .65):
            return True
    # Some handwritten leaders deliberately stop short of the digits. A nearby
    # long, thin stroke makes centre assignment ambiguous even without a ring.
    # Abstain instead of assigning the field underneath the number itself.
    proximity = max(8., (b - t) * .65)
    for ident in range(1, len(stats)):
        if ident in ids or stats[ident, cv2.CC_STAT_AREA] < 10:
            continue
        ys, xs = np.where(labels == ident)
        xs, ys = xs + left, ys + top
        dx = np.maximum(np.maximum(l - xs, xs - r), 0)
        dy = np.maximum(np.maximum(t - ys, ys - b), 0)
        if float(np.min(dx * dx + dy * dy)) > proximity * proximity:
            continue
        points = np.column_stack([xs, ys]).astype(np.float32)
        side_a, side_b = cv2.minAreaRect(points)[1]
        major, minor = max(side_a, side_b), min(side_a, side_b)
        if major >= max(24., (b - t) * 1.3) and major / max(1., minor) >= 4.:
            return True
    return False


def _analyze_mask(engine, mask, color, occluder=None):
    import numpy as np

    height, width = mask.shape
    if np.count_nonzero(mask) < 12:
        return []
    small, scale, circles, possible = _circles(mask, color)
    leaders = _leader_data(small, circles, scale, occluder) if circles else []
    texts = _text_candidates(engine, mask) if color != "dark" else []
    used = set()
    annotations = []
    for circle, leader in zip(circles, leaders):
        box = _circle_box(circle, scale, width, height)
        l, t, r, b = box
        y, x = np.mgrid[t:b, l:r]
        radius = _radius(circle, np.stack([x * scale, y * scale], axis=-1))
        readings = []
        for index, candidate in enumerate(texts):
            cl, ct, cr, cb = candidate["box"]
            center = ((cl + cr) * scale / 2, (ct + cb) * scale / 2)
            if float(_radius(circle, center)) < .72:
                readings.append((candidate["text"], candidate["confidence"]))
                used.add(index)
        detected = readings[:]
        # Agreement across an inner and a wider crop rules out accepting a
        # clipped prefix merely because the recognizer is confident about it.
        for threshold in (.55, .62, .70, .80, 1.05):
            reading = _read_line(engine, mask[t:b, l:r] & (radius < threshold))
            if reading:
                readings.append(reading)
        suggestion = _consensus(readings)
        if color != "dark":
            suggestion = _recover_circle_text(engine, mask[t:b, l:r], radius,
                None if occluder is None else occluder[t:b, l:r], suggestion)
        if not suggestion["text"]:
            # A well supported coloured callout is still evidence that the
            # field has another label even when none of its digits is legible.
            # Keep the mark for boundary review without inventing a number.
            if color != "dark" and circle[5] >= .9:
                annotations.append({**leader, "text": "", "confidence": 0.,
                    "status": "uncertain", "textStatus": "uncertain",
                    "associationStatus": "ok" if not leader["hasLeader"] or
                    len(leader["leaderEndpoints"]) == 1 else "uncertain",
                    "reason": "unread_callout", "alternatives": suggestion["alternatives"],
                    "circleConfidence": round(float(circle[5]), 5),
                    "source": "callout", "box": box, "ink": color})
            continue
        suggestion["textStatus"] = suggestion["status"]
        suggestion["associationStatus"] = "ok"
        if leader["hasLeader"] and len(leader["leaderEndpoints"]) != 1:
            suggestion["status"] = "uncertain"
            suggestion["associationStatus"] = "uncertain"
            suggestion["reason"] = leader.get("reason", "branched_leader")
        if len(suggestion["text"]) == 1 and not any(
                text == suggestion["text"] and confidence >= .82 for text, confidence in detected):
            # A digit-only crop can be just the last digit of a larger number
            # touching its rim. Require independent whole-text detection.
            suggestion["status"] = "uncertain"
            suggestion["textStatus"] = "uncertain"
            suggestion["reason"] = "partial_digit"
            if color != "dark" and circle[5] >= .9:
                # A lone recognized stroke may be only one digit of an unread
                # multi-digit callout. Keep it among alternatives, never as
                # the field's number, while retaining the visible circle.
                suggestion["text"] = ""
                suggestion["confidence"] = 0.
                suggestion["reason"] = "unread_callout"
        annotations.append({**leader, **suggestion, "source": "callout", "box": box,
                            "ink": color, "circleConfidence": round(float(circle[5]), 5)})
    for index, candidate in enumerate(texts):
        if index in used or len(candidate["text"]) < 2:
            continue
        l, t, r, b = candidate["box"]
        if (r - l) / max(1, b - t) > 4.5:
            continue
        reading = _read_line(engine, mask[t:b, l:r])
        # This is an independently detected full text box, not an inner circle
        # crop. A weaker extra stroke can look like a trailing digit; preserve
        # the strongest complete-word reading as the review text in that case.
        suggestion = _consensus([(candidate["text"], candidate["confidence"])] + ([reading] if reading else []),
                                prefer_complete=False)
        if candidate.get("disagreement"):
            suggestion["status"] = "uncertain"
            suggestion["reason"] = "conflicting_text"
        suggestion["textStatus"] = suggestion["status"]
        suggestion["associationStatus"] = "ok"
        center = ((l + r) * scale / 2, (t + b) * scale / 2)
        possible_circle = any(c[2] * c[3] * pi > (r - l) * (b - t) * scale * scale * 1.1 and
               min(c[2], c[3]) > (b - t) * scale * .45 and
               float(_radius(c, center)) < .72 for c in possible)
        if possible_circle:
            # A broken/overwritten ring may have an unseen leader. Do not turn
            # an unassociated callout into an ordinary label under its centre.
            suggestion["status"] = "uncertain"
            suggestion["associationStatus"] = "uncertain"
            suggestion["reason"] = "possible_circle"
        outgoing = _has_outgoing_ink(mask, candidate["box"])
        if outgoing:
            suggestion["status"] = "uncertain"
            suggestion["associationStatus"] = "uncertain"
            suggestion["reason"] = "detached_leader"
        annotations.append({**suggestion, "source": "inside", "box": candidate["box"],
                            "ink": color, "hasLeader": outgoing or possible_circle,
                            "anchor": None if outgoing or possible_circle else [(l + r) / 2, (t + b) / 2]})
    return annotations


def recognize_raster_a1(content: bytes) -> dict:
    """Read one normalized preview. Results are evidence, never saved fields."""
    if not isinstance(content, bytes) or not content or len(content) > MAX_BYTES:
        raise ValueError("Nieprawidłowy podgląd rastra do odczytu A1.")
    from PIL import Image
    import cv2
    import numpy as np

    with Image.open(BytesIO(content)) as image:
        width, height = image.size
        if width * height > MAX_PIXELS:
            raise ValueError("Podgląd do odczytu A1 przekracza 14 mln pikseli.")
        if image.mode in ("RGBA", "LA") or "transparency" in image.info:
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", image.size, "white")
            background.alpha_composite(rgba)
            pixels = np.asarray(background.convert("RGB"))
        else:
            pixels = np.asarray(image.convert("RGB"))
    red, green, blue = cv2.split(pixels)
    masks = {
        "blue": (cv2.subtract(blue, red) > 23) & (cv2.subtract(blue, green) > 12) & (red < 195),
        "green": (cv2.subtract(green, red) > 22) & (cv2.subtract(green, blue) > 8) & (red < 170),
        "dark": (np.maximum(np.maximum(red, green), blue) < 140) &
                (cv2.subtract(np.maximum(np.maximum(red, green), blue), np.minimum(np.minimum(red, green), blue)) < 45),
    }
    occluder = (np.maximum(np.maximum(red, green), blue) < 190) & (
        cv2.subtract(np.maximum(np.maximum(red, green), blue), np.minimum(np.minimum(red, green), blue)) < 45)
    with _ENGINE_LOCK:
        engine = _engine()
        annotations = []
        for color, mask in masks.items():
            annotations.extend(_analyze_mask(engine, mask, color, occluder))
    return {"width": width, "height": height, "annotations": annotations,
            "engine": MODEL_VERSION, "status": "ready"}


def selftest_raster_a1() -> bool:
    """Exercise the packaged models using a generated, non-user fixture."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (280, 160), "white")
    draw = ImageDraw.Draw(image)
    ink = (20, 35, 180)
    draw.ellipse((20, 20, 110, 110), outline=ink, width=2)
    draw.text((43, 45), "21", font=ImageFont.load_default(size=31), fill=ink)
    draw.line((109, 70, 242, 125), fill=ink, width=2)
    output = BytesIO()
    image.save(output, format="PNG")
    result = recognize_raster_a1(output.getvalue())
    return any(a["text"] == "21" and a["status"] == "ok" and a["source"] == "callout"
               for a in result["annotations"])
