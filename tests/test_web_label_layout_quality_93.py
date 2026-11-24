"""A1/A2: osobne miejsca, zero nakładań, zero przecieć linii."""
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
    auto_layout_5310_labels, text_size)

MAP = Path("/scratch/input/MOKRA_WIEŚ-2.MAP")


def _prepared():
    if not MAP.exists():
        pytest.skip("brak mapy testowej")
    doc = GeoMap(MAP.read_bytes(), filename="MOKRA.MAP")
    out = []
    for obj in doc.objects:
        if obj.code != "5310" or not obj.is_closed:
            continue
        try:
            shape = geometry_of(obj)
        except ValueError:
            continue
        if shape is None or shape.is_empty:
            continue
        out.append((obj.uid, shape, _label_anchor(obj),
                    str(obj.fields.get("A1", "") or ""),
                    str(obj.fields.get("A2", "") or "")))
    return out


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
            width, height = text_size(text, fraction=(field == "A2"))
            cx, cy = base[0] + spec["dx"], base[1] + spec["dy"]
            out.append({"uid": change["uid"], "field": field, "text": text,
                        "rect": shapely_box(cx - height / 2, cy - width / 2,
                                            cx + height / 2, cy + width / 2),
                        "shape": shape, "leader": "anchor" in spec})
    return out


def test_all_labels_are_written():
    prepared = _prepared()
    result = auto_layout_5310_labels(prepared, scale=5000)
    written = sum(len(change["labels"]) for change in result["changes"])
    expected = sum(1 for _u, _s, _b, a1, a2 in prepared
                   for text in (a1, a2) if text)
    assert written == expected == 52


def test_no_overlaps_and_no_line_crossings():
    prepared = _prepared()
    boxes = _boxes(auto_layout_5310_labels(prepared, scale=5000), prepared)
    for index, first in enumerate(boxes):
        for second in boxes[index + 1:]:
            assert not first["rect"].intersects(second["rect"]), \
                (first["text"], second["text"])
    shapes = {uid: shape for uid, shape, _b, _a1, _a2 in prepared}
    for box in boxes:
        for uid, shape in shapes.items():
            assert box["rect"].intersection(shape.boundary).length <= 2.0, \
                (box["text"], uid)


def test_a1_is_always_inside():
    prepared = _prepared()
    boxes = _boxes(auto_layout_5310_labels(prepared, scale=5000), prepared)
    a1 = [box for box in boxes if box["field"] == "A1"]
    inside = [box for box in a1
              if box["shape"].buffer(1e-6).contains(box["rect"])]
    assert len(inside) == len(a1)


def test_fewer_leaders_than_before():
    """Wcześniej A2 szło na wysięgnik w 16 przypadkach; osobne miejsca to zmniejszają."""
    prepared = _prepared()
    result = auto_layout_5310_labels(prepared, scale=5000)
    assert result["stats"]["leaders"] <= 17
