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

from scene_snapshot import build_scene_window, golden_map_bytes, snapshot_json

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
