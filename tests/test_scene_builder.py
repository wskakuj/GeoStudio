"""Tests for the extracted scene builder.

The centrepiece is ``test_scene_snapshot_matches_golden``: it compares a full
description of the rendered scene (every item, its geometry, pens, brushes,
fonts, stacking and label data) against a snapshot captured from the code as
it stood before ``scene_builder`` was extracted. If a refactor changes
rendering in any way, that test fails even when everything else passes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsScene

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.scene_builder import (RenderContext, SceneBuildResult,
                                     build_scene, label_anchor, object_path)

from scene_snapshot import (SHEET_CODES, build_scene_window, golden_map_bytes,
                            serialize_scene, snapshot_json)

GOLDEN = Path(__file__).parent / "golden" / "scene_v014.json"


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_scene_snapshot_matches_golden(qt_app, tmp_path):
    expected = GOLDEN.read_text(encoding="utf-8")
    actual = snapshot_json(build_scene_window(tmp_path))
    if actual != expected:
        wanted = expected.splitlines()
        got = actual.splitlines()
        first = next((i for i, (a, b) in enumerate(zip(wanted, got)) if a != b),
                     min(len(wanted), len(got)))
        pytest.fail(
            "Rendered scene differs from tests/golden/scene_v014.json at line "
            f"{first + 1}:\n  expected: {wanted[first] if first < len(wanted) else '<eof>'}"
            f"\n  actual:   {got[first] if first < len(got) else '<eof>'}")


def test_snapshot_covers_every_rendering_branch(qt_app, tmp_path):
    window = build_scene_window(tmp_path)
    assert window.doc is not None
    assert len(window.map_scene.items()) == 24
    assert set(window.graphics_for_uid) >= {"PARCEL", "PRECINCT", "FOREST",
                                            "MEADOW", "BUILDING", "MULTI", "OPEN"}
    # Filled polygons get their own fill stage plus a stroke item.
    assert set(window.fill_items_for_uid) >= {"PARCEL", "FOREST", "MEADOW"}
    assert ("PARCEL", "A2") in window.label_items
    assert window.label_world_span["PRECINCT"] == pytest.approx(300.0)


def test_multipart_connectors_change_only_the_path(qt_app, tmp_path):
    doc = GeoMap(golden_map_bytes())
    obj = doc.by_id["MULTI"]
    hidden = object_path(obj, hide_connectors=True)
    visible = object_path(obj, hide_connectors=False)
    assert hidden.elementCount() == visible.elementCount()
    count = lambda path: sum(1 for i in range(path.elementCount())
                             if path.elementAt(i).type == QPainterPath.ElementType.MoveToElement)
    assert count(hidden) == 2 and count(visible) == 1


def test_window_path_helper_still_delegates():
    """test_gui.py calls GeoStudioWindow._path_for directly; keep it working."""
    doc = GeoMap(golden_map_bytes())
    obj = doc.by_id["MULTI"]
    assert GeoStudioWindow._path_for(obj, hide_connectors=True).elementCount() == \
        object_path(obj, hide_connectors=True).elementCount()


def test_window_label_anchor_still_delegates():
    """GeoStudioWindow keeps _label_anchor as a thin alias to scene_builder."""
    doc = GeoMap(golden_map_bytes())
    for uid in ("PARCEL", "OPEN"):
        obj = doc.by_id[uid]
        assert GeoStudioWindow._label_anchor(obj) == label_anchor(obj)
    assert GeoStudioWindow._label_anchor(doc.by_id["PARCEL"]) == pytest.approx((500150.0, 6500150.0))


def test_label_anchor_centroid_and_midpoint():
    doc = GeoMap(golden_map_bytes())
    assert label_anchor(doc.by_id["PARCEL"]) == pytest.approx((500150.0, 6500150.0))
    open_obj = doc.by_id["OPEN"]
    assert label_anchor(open_obj) == pytest.approx((500300.0, 6500460.0))


def test_single_point_object_keeps_screen_size(qt_app, tmp_path):
    window = build_scene_window(tmp_path)
    item = window.graphics_for_uid["BUILDING"]
    assert item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
    assert item.zValue() == pytest.approx(250.0)


def test_stacking_follows_map_codes(qt_app, tmp_path):
    window = build_scene_window(tmp_path)
    assert window.graphics_for_uid["PRECINCT"].zValue() == pytest.approx(220.0)
    assert window.graphics_for_uid["PARCEL"].zValue() == pytest.approx(180.0)
    assert window.graphics_for_uid["FOREST"].zValue() == pytest.approx(130.0)
    assert window.graphics_for_uid["MEADOW"].zValue() == pytest.approx(130.0)
    assert window.fill_items_for_uid["PARCEL"].zValue() == pytest.approx(-100.0)


def test_build_scene_is_repeatable(qt_app):
    doc = GeoMap(golden_map_bytes())
    scene = QGraphicsScene()
    first = build_scene(scene, doc, RenderContext())
    count = len(scene.items())
    second = build_scene(scene, doc, RenderContext())
    assert len(scene.items()) == count          # clear() removed the first pass
    assert first.layer_for_uid == second.layer_for_uid
    assert isinstance(second.items_by_layer, type(first.items_by_layer))
    second.items_by_layer["nieznana"].append(None)  # defaultdict contract
    assert isinstance(second, SceneBuildResult)


def test_render_context_is_frozen():
    ctx = RenderContext()
    assert ctx.hide_multipart_connectors is True
    assert ctx.compilation_scale == 1000.0
    with pytest.raises(Exception):
        ctx.catalog = {}          # type: ignore[misc]


# --- font independence ---------------------------------------------------
# Qt resolves "Segoe UI" differently on Windows and Linux, so the golden file
# stores label metrics in normalised form. These tests pin the rules behind
# that normalisation, so the same assertions hold on any platform regardless
# of which font Qt picks.

def test_label_offsets_scale_with_the_font(qt_app, tmp_path):
    window = build_scene_window(tmp_path)
    building = window.doc.by_id["BUILDING"]
    for field, sign in (("A1", -1.0), ("A2", 1.0)):
        item = window.label_items[("BUILDING", field)]
        height = item.boundingRect().height()
        assert item.data(2) == pytest.approx(sign * 0.6 * height, rel=1e-6)


def test_sheet_label_ratio_reduces_to_nominal_a1(qt_app, tmp_path):
    window = build_scene_window(tmp_path)
    scale_factor = window.compilation_scale / window.source_compilation_scale
    for uid in ("TITLE", "NORTH"):
        for (item_uid, field), item in window.label_items.items():
            if item_uid != uid:
                continue
            height = item.boundingRect().height()
            # A1 is absent on these objects, so source_text_height() defaults to 12.
            assert item.data(3) * height / scale_factor == pytest.approx(12.0, rel=1e-6)


def test_plain_label_ratio_is_a_constant(qt_app, tmp_path):
    window = build_scene_window(tmp_path)
    scale_factor = window.compilation_scale / window.source_compilation_scale
    for uid in ("PARCEL", "PRECINCT", "FOREST", "MEADOW"):
        item = window.label_items[(uid, "A2" if uid != "PRECINCT" else "A3")]
        assert item.data(3) == pytest.approx(0.55 * scale_factor, rel=1e-6)


def test_golden_survives_font_substitution(qt_app, tmp_path, monkeypatch):
    """A machine with different system fonts must not produce a false failure.

    The renderer asks for "Segoe UI"; on Linux Qt silently substitutes another
    face with different metrics. Re-running the snapshot with an explicitly
    different family must still match the golden file (the requested family
    name is the only thing allowed to differ, and it is a constant in the code).
    """
    import geostudio.scene_builder as scene_builder
    from PySide6.QtGui import QFont as RealQFont

    def strip_family(text):
        data = json.loads(text)
        for item in data["items"]:
            if "text" in item:
                item["text"].pop("family", None)
        return json.dumps(data, sort_keys=True)

    golden = strip_family(GOLDEN.read_text(encoding="utf-8"))
    monkeypatch.setattr(scene_builder, "QFont",
                        lambda family, *a, **k: RealQFont("DejaVu Serif", *a, **k))
    assert strip_family(snapshot_json(build_scene_window(tmp_path))) == golden


def test_golden_stores_no_raw_font_metrics():
    """Guards the normalisation: raw setData(2..4) must never reach the file."""
    snapshot = json.loads(GOLDEN.read_text(encoding="utf-8"))
    texts = [item for item in snapshot["items"]
             if item["kind"] == "QGraphicsSimpleTextItem"]
    assert len(texts) == 9
    for item in texts:
        assert "metrics" in item
        assert set(item["metrics"]) <= {"offsetPerHeight", "ratioRule"}
        for forbidden in ("data2", "data3", "data4"):
            assert forbidden not in item


# --- drawing order and label placement -----------------------------------

def test_snapshot_records_paint_order(qt_app, tmp_path):
    snapshot = serialize_scene(build_scene_window(tmp_path))
    indices = [item["paintIndex"] for item in snapshot["items"]]
    assert indices == list(range(len(indices)))
    zs = [item["z"] for item in snapshot["items"]]
    assert zs == sorted(zs), "paint order must follow stacking, bottom to top"
    assert zs[0] == pytest.approx(-100.0)      # fills first
    assert zs[-1] == pytest.approx(1300.0)     # labels last


def test_snapshot_records_label_positions(qt_app, tmp_path):
    snapshot = serialize_scene(build_scene_window(tmp_path))
    positions = snapshot["labelPositions"]
    assert len(positions) == 9
    # A dragged label keeps its explicit position from label_positions.
    assert positions["PARCEL|A2"] == pytest.approx([500160.0, -6500160.0])
    # Untouched labels sit on the object anchor.
    assert positions["FOREST|A2"] == pytest.approx([500160.0, -6500140.0])


def test_snapshot_covers_every_map_code(qt_app, tmp_path):
    snapshot = serialize_scene(build_scene_window(tmp_path))
    z_by_uid = {item["data0"]: item["z"] for item in snapshot["items"]
                if item["data0"] in window_uid_whitelist
                and item["kind"] != "QGraphicsSimpleTextItem"}
    assert z_by_uid["PARCEL"] == pytest.approx(180.0)
    assert z_by_uid["PRECINCT"] == pytest.approx(220.0)
    assert z_by_uid["BUILDING"] == pytest.approx(250.0)


window_uid_whitelist = {"PARCEL", "PRECINCT", "FOREST", "MEADOW",
                        "BUILDING", "MULTI", "OPEN", "COMPASS"}
