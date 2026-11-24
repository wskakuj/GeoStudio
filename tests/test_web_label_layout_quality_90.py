"""A1/A2 bezkolizyjne: metryka jak w rysowaniu + kolumna A1+A2."""
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
    GAP_M, GLYPH_H_M, LabelBox, auto_layout_5310_labels, text_size)

MAP = Path("/scratch/input/MOKRA_WIEŚ-2.MAP")


def test_glyph_height_matches_the_renderer():
    """map.js: 16 px × 2500 × 0,0254 / 96 ≈ 10,58 m na gruncie."""
    assert 10.0 < GLYPH_H_M < 11.2
    assert round(16 * 2500 * 0.0254 / 96, 2) == round(GLYPH_H_M, 2)


def test_label_box_axes_follow_the_map():
    rect = LabelBox(0.0, 0.0, 20.0, 4.0).rect
    assert round(rect.bounds[2] - rect.bounds[0], 3) == 4.0    # północ
    assert round(rect.bounds[3] - rect.bounds[1], 3) == 20.0   # wschód


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
        labels = change["labels"]
        same = ("A1" in labels and "A2" in labels and
                labels["A1"]["dx"] == labels["A2"]["dx"] and
                labels["A1"]["dy"] == labels["A2"]["dy"])
        if same:
            w1, h1 = text_size(a1)
            w2, h2 = text_size(a2, fraction=True)
            total, wid = h1 + h2 + GAP_M, max(w1, w2)
            cx, cy = base[0] + labels["A1"]["dx"], base[1] + labels["A1"]["dy"]
            out.append({"uid": change["uid"], "text": a1 + "/" + a2,
                        "rect": shapely_box(cx - total / 2, cy - wid / 2,
                                            cx + total / 2, cy + wid / 2),
                        "shape": shape,
                        "leader": "anchor" in labels["A1"]})
            continue
        for field in ("A1", "A2"):
            if field not in labels:
                continue
            text = a1 if field == "A1" else a2
            width, height = text_size(text, fraction=(field == "A2"))
            cx = base[0] + labels[field]["dx"]
            cy = base[1] + labels[field]["dy"]
            out.append({"uid": change["uid"], "text": text,
                        "rect": shapely_box(cx - height / 2, cy - width / 2,
                                            cx + height / 2, cy + width / 2),
                        "shape": shape,
                        "leader": "anchor" in labels[field]})
    return out


def test_every_label_is_written():
    prepared = _prepared()
    result = auto_layout_5310_labels(prepared, scale=5000)
    written = sum(1 for change in result["changes"]
                  for field in ("A1", "A2") if field in change["labels"])
    expected = sum(1 for _u, _s, _b, a1, a2 in prepared
                   for text in (a1, a2) if text)
    assert written == expected == 52


def test_no_label_overlaps_another():
    prepared = _prepared()
    boxes = _boxes(auto_layout_5310_labels(prepared, scale=5000), prepared)
    for index, first in enumerate(boxes):
        for second in boxes[index + 1:]:
            assert not first["rect"].intersects(second["rect"]), \
                (first["text"], second["text"])


def test_no_label_crosses_any_polygon_line():
    prepared = _prepared()
    boxes = _boxes(auto_layout_5310_labels(prepared, scale=5000), prepared)
    shapes = {uid: shape for uid, shape, _b, _a1, _a2 in prepared}
    for box in boxes:
        for uid, shape in shapes.items():
            assert box["rect"].intersection(shape.boundary).length <= 0.01, \
                (box["text"], uid)


def test_every_label_is_inside_or_has_a_leader():
    prepared = _prepared()
    boxes = _boxes(auto_layout_5310_labels(prepared, scale=5000), prepared)
    for box in boxes:
        inside = box["shape"].buffer(1e-6).contains(box["rect"])
        assert inside or box["leader"], box["text"]


def test_layout_is_readable_inside_when_it_fits():
    """Co najmniej połowa obiektów ma napis w środku poligonu."""
    prepared = _prepared()
    result = auto_layout_5310_labels(prepared, scale=5000)
    assert result["stats"]["inside"] >= 13
