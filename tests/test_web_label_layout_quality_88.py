"""Jakość auto-układania A1/A2: brak nakładań, brak wchodzenia na linie."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from shapely.geometry import box as shapely_box

sys.path.insert(0, str(Path(__file__).parent))

from geostudio.geomap import GeoMap  # noqa: E402
from geostudio.web_app.data import _label_anchor  # noqa: E402
from geostudio.web_app.geometry_6a import geometry_of  # noqa: E402
from geostudio.web_app.label_layout import (  # noqa: E402
    LabelBox, auto_layout_5310_labels, text_size)

MAP = Path("/scratch/input/MOKRA_WIEŚ-2.MAP")
SCALE = 5000


def _objects():
    if not MAP.exists():
        pytest.skip("brak mapy testowej")
    doc = GeoMap(MAP.read_bytes(), filename="MOKRA.MAP")
    prepared = []
    for obj in doc.objects:
        if obj.code != "5310" or not obj.is_closed:
            continue
        try:
            shape = geometry_of(obj)
        except ValueError:
            continue
        if shape is None or shape.is_empty:
            continue
        prepared.append((obj.uid, shape, _label_anchor(obj),
                         str(obj.fields.get("A1", "") or ""),
                         str(obj.fields.get("A2", "") or "")))
    return prepared


def _boxes(result, prepared):
    by_uid = {uid: (shape, base, a1, a2)
              for uid, shape, base, a1, a2 in prepared}
    out = []
    for change in result["changes"]:
        shape, base, a1, a2 = by_uid[change["uid"]]
        for field, spec in change["labels"].items():
            text = a1 if field == "A1" else a2
            if not text:
                continue
            width, height = text_size(text, SCALE, fraction=(field == "A2"))
            cx, cy = base[0] + spec["dx"], base[1] + spec["dy"]
            rect = shapely_box(cx - height / 2, cy - width / 2,
                               cx + height / 2, cy + width / 2)
            out.append({"uid": change["uid"], "rect": rect, "shape": shape,
                        "leader": "anchor" in spec, "text": text})
    return out


def test_label_box_axes_follow_the_map():
    """Szerokość napisu biegnie wschód–zachód, wysokość wzdłuż północy."""
    rect = LabelBox(0.0, 0.0, 20.0, 4.0).rect
    assert round(rect.bounds[2] - rect.bounds[0], 3) == 4.0   # północ
    assert round(rect.bounds[3] - rect.bounds[1], 3) == 20.0  # wschód


def test_layout_never_overlaps_or_crosses_foreign_lines():
    prepared = _objects()
    result = auto_layout_5310_labels(prepared, scale=SCALE)
    boxes = _boxes(result, prepared)
    assert len(boxes) == 52                     # komplet etykiet

    for index, first in enumerate(boxes):
        for second in boxes[index + 1:]:
            assert not first["rect"].intersects(second["rect"]), \
                (first["text"], second["text"])

    shapes = {uid: shape for uid, shape, _b, _a1, _a2 in prepared}
    for box in boxes:
        for uid, shape in shapes.items():
            if uid == box["uid"]:
                continue
            assert box["rect"].intersection(shape.boundary).length <= 0.01, \
                (box["text"], uid)


def test_every_label_is_inside_or_has_a_leader():
    prepared = _objects()
    result = auto_layout_5310_labels(prepared, scale=SCALE)
    for box in _boxes(result, prepared):
        inside = box["shape"].buffer(1e-6).contains(box["rect"])
        assert inside or box["leader"], box["text"]


def test_most_labels_fit_inside_like_geo_map():
    """Wzorzec GEO-MAP: 48 z 52 etykiet w środku poligonu."""
    prepared = _objects()
    result = auto_layout_5310_labels(prepared, scale=SCALE)
    inside = sum(1 for box in _boxes(result, prepared)
                 if box["shape"].buffer(1e-6).contains(box["rect"]))
    assert inside >= 48
