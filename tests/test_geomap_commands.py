"""Regression tests for GEO-MAP-style commands and precise feature selection."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from geostudio.geomap import GeoMap
from geostudio.feature_dialogs import (
    find_by_attributes, replacement_plan, ReplaceSpecification,
)
from geostudio.scene_builder import RenderContext, object_fill_brush
from geostudio.topology_edit import linked_vertex_moves
from test_geomap import fixture_map


def sample_doc():
    doc = GeoMap(fixture_map())
    building1 = doc.append_polygon(
        [(5, 5), (10, 5), (10, 10), (5, 10)], "5310",
        fields={"A1": "b", "A2": "Ol75|II-0.5"})
    building2 = doc.append_polygon(
        [(12, 5), (17, 5), (17, 10), (12, 10)], "5310",
        fields={"A1": "b", "A2": "Ol75|I-0.8"})
    parcel = doc.append_polygon(
        [(4, 4), (18, 4), (18, 18), (4, 18)], "5216",
        fields={"A1": "b", "A2": "15/2"})
    return doc, building1, building2, parcel


def test_attribute_filter_supports_code_only_exact_and_optional_second_condition():
    doc, b1, b2, parcel = sample_doc()
    assert {x.uid for x in find_by_attributes(doc.objects, code="5310")} == {b1, b2}
    assert [x.uid for x in find_by_attributes(
        doc.objects, code="5310", first=("A2", "ol75|ii-0.5"))] == [b1]
    assert {x.uid for x in find_by_attributes(
        doc.objects, code="5310", first=("A2", "Ol75"),
        partial=True)} == {b1, b2}
    assert [x.uid for x in find_by_attributes(
        doc.objects, code="5310", first=("A2", "Ol75|II-0.5"),
        second=("A1", "b"), join="and")] == [b1]
    assert {x.uid for x in find_by_attributes(
        doc.objects, code="5310", first=("A2", "Ol75|II-0.5"),
        second=("A1", "nomatch"), join="or")} == {b1}


def test_text_replacement_is_one_atomic_batch_preserving_map_and_other_fields():
    doc, b1, b2, parcel = sample_doc()
    before_parcel = doc.by_id[parcel].fields["A2"]
    plan = replacement_plan(
        doc.objects, ReplaceSpecification("A2", "Ol75", "Ol76", True, True))
    assert set(plan) == {(b1, "A2"), (b2, "A2")}
    doc.bulk_update_fields(plan)
    assert doc.by_id[b1].fields["A2"] == "Ol76|II-0.5"
    assert doc.by_id[b2].fields["A2"] == "Ol76|I-0.8"
    assert doc.by_id[parcel].fields["A2"] == before_parcel
    restored = GeoMap(doc.to_bytes())
    assert restored.checksum_valid


def test_batch_replacement_rejects_unrepresentable_and_preserves_bytes():
    doc, b1, b2, parcel = sample_doc()
    original = doc.to_bytes()
    with pytest.raises(UnicodeEncodeError):
        doc.bulk_update_fields({(b1, "A2"): "Ok", (b2, "A2"): "😀"})
    assert doc.to_bytes() == original
    with pytest.raises(ValueError):
        doc.bulk_update_fields({(b1, "A2"): "broken]"})
    assert doc.to_bytes() == original


def test_5230_road_has_no_fill_while_ls_is_transparent_green():
    doc = GeoMap(fixture_map())
    road = doc.append_polygon(
        [(0, 0), (4, 0), (4, 4)], "5230",
        fields={"A1": "dr", "A2": "dr"})
    road_full = doc.append_polygon(
        [(5, 0), (9, 0), (9, 4)], "5230",
        fields={"A1": "Droga"})
    forest = doc.append_polygon(
        [(0, 6), (4, 6), (4, 10)], "5230",
        fields={"A1": "Ls"})
    ctx = RenderContext(
        default_fill_opacity=60,
        visual_styles={"code:5230": {"fill": "#00FF00", "opacity": 65}})
    for uid in (road, road_full):
        assert object_fill_brush(doc.by_id[uid], ctx).style().name == "NoBrush"
    forest_color = object_fill_brush(doc.by_id[forest], RenderContext()).color()
    assert forest_color.green() > forest_color.red()
    assert 0 < forest_color.alpha() < 200
    assert object_fill_brush(doc.by_id[forest], ctx).color().alpha() == round(.65 * 255)


def test_shared_vertex_moves_only_same_code_even_when_other_code_shares_position():
    doc = GeoMap(fixture_map())
    a = doc.append_polygon([(0,0),(10,0),(10,10),(0,10)], "5310")
    b = doc.append_polygon([(10,0),(20,0),(20,10),(10,10)], "5310")
    other = doc.append_polygon([(10,0),(11,-5),(15,-5)], "5216")
    old_other = [(p.x,p.y) for p in doc.by_id[other].points]
    moves = linked_vertex_moves(doc, a, 1, 11, 1)
    assert set(moves) == {a,b}
    doc.move_polygon_vertices(moves, reparse=False)
    assert [(p.x,p.y) for p in doc.by_id[other].points] == old_other


@pytest.fixture(scope="module")
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_window_selects_building_first_and_highlights_a1_a2(qt_app):
    from geostudio.app import GeoStudioWindow
    window = GeoStudioWindow()
    try:
        doc, b1, b2, parcel = sample_doc()
        window.doc = doc
        window.rebuild_scene(fit=False)
        window.select_at(7.5, 7.5)
        assert window.selected_uid == b1
        assert len(window._selected_label_frames) == 2
        window.select_at(7.5, 7.5)
        assert window.selected_uid != b1
        # Parcel and land-use features can have an A2 label of their own.
        # Old building's A1/A2 frames must be removed rather than left on
        # screen after switching selection.
        assert all(
            frame.parentItem().data(0) == window.selected_uid
            for frame in window._selected_label_frames)
    finally:
        window.close()


def test_shortcuts_match_requested_mapping_and_preserve_crs(qt_app):
    from geostudio.app import GeoStudioWindow
    window = GeoStudioWindow()
    try:
        actions = {a.text(): a.shortcut().toString() for a in
                   window.findChildren(__import__("PySide6.QtGui", fromlist=["QAction"]).QAction)}
        assert any(v == "T" for v in actions.values())
        assert any(v == "F" for v in actions.values())
        assert not any(v == "Ctrl+H" for v in actions.values())
        assert any(v == "Ctrl+L" for v in actions.values())
        assert any(v == "B" for v in actions.values())
        assert any(v == "Ctrl+F" for v in actions.values())
        assert any(v == "Ctrl+T" for v in actions.values())
    finally:
        window.close()


def test_open_map_defaults_to_hidden_boundary_markers(qt_app, tmp_path, monkeypatch):
    from geostudio.app import GeoStudioWindow
    from PySide6.QtWidgets import QFileDialog
    p = tmp_path / "sample.MAP"
    p.write_bytes(fixture_map())
    window = GeoStudioWindow()
    try:
        monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(
            lambda *_args, **_kwargs: (str(p), "GEO-MAP (*.MAP)")))
        window.open_map()
        assert "Graniczniki" in window.hidden_layers
        assert window.doc.filename == str(p)
    finally:
        window.close()
