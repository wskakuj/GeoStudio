"""Same-code vertex topology and localized Qt redraw regressions."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from geostudio.geomap import GeoMap
from geostudio.topology_edit import linked_vertex_moves
from test_geomap import fixture_map


def buildings():
    doc = GeoMap(fixture_map())
    a = doc.append_polygon(
        [(10, 10), (20, 10), (20, 20), (10, 20)], "5310",
        fields={"A1": "b", "A2": "Ol75|II-0.5"})
    b = doc.append_polygon(
        [(20, 10), (30, 10), (30, 20), (20, 20)], "5310",
        fields={"A1": "c"})
    third = doc.append_polygon(
        [(20, 10), (30, 10), (30, 20), (20, 20)], "5216")
    unrelated = doc.append_polygon(
        [(100, 100), (110, 100), (110, 110)], "5310")
    return doc, a, b, third, unrelated


def test_shared_node_changes_only_same_code_neighbor_and_closure():
    doc, uid, neighbor, other_code, distant = buildings()
    prior_unchanged = doc.by_id[other_code].points[0].x
    changes = linked_vertex_moves(doc, uid, 1, 22.0, 11.0)
    assert set(changes) == {uid, neighbor}
    assert changes[neighbor] == {0: (22.0, 11.0)}
    before = doc.to_bytes()
    doc.move_polygon_vertices(changes, reparse=False)
    assert doc.by_id[uid].points[1].x == 22.0
    assert doc.by_id[neighbor].points[0].x == 22.0
    assert doc.by_id[neighbor].points[-1].x == 22.0
    assert doc.by_id[other_code].points[0].x == prior_unchanged
    assert doc.by_id[distant].points[0].x == 100
    roundtrip = GeoMap(doc.to_bytes())
    assert roundtrip.checksum_valid
    assert roundtrip.by_id[neighbor].points[0].x == 22.0
    assert b':A2[Ol75|II-0.5]' in before
    assert b':A2[Ol75|II-0.5]' in doc.to_bytes()


def test_bulk_vertex_change_rejects_invalid_neighbor_without_partial_write():
    doc, uid, neighbor, *_ = buildings()
    original = doc.to_bytes()
    changes = linked_vertex_moves(doc, uid, 1, 20, 20)
    # If another vertex would become coincident, the batch must fail before
    # even rewriting the first polygon's original P record.
    with pytest.raises(ValueError):
        doc.move_polygon_vertices(changes, reparse=False)
    assert doc.to_bytes() == original
    assert doc.by_id[uid].points[1].y == 10
    assert doc.by_id[neighbor].points[0].y == 10


def test_legacy_single_vertex_edit_has_same_source_roundtrip():
    doc, uid, neighbor, *_ = buildings()
    before = doc.to_bytes()
    doc.move_polygon_vertex(uid, 1, 21, 11)
    assert doc.by_id[uid].points[1].x == 21
    assert doc.by_id[neighbor].points[0].x == 20
    assert GeoMap(doc.to_bytes()).checksum_valid
    assert doc.to_bytes() != before


@pytest.fixture(scope="module")
def qt_app():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_gui_vertex_commit_updates_only_changed_graphics(qt_app, monkeypatch):
    from geostudio.app import GeoStudioWindow
    window = GeoStudioWindow()
    try:
        doc, a, b, c, distant = buildings()
        window.doc = doc
        window.rebuild_scene(fit=False)
        window._select_uid(a)
        window.start_vertex_edit()
        assert window.edit_scope_code == "5310"
        first_item = window.graphics_for_uid[a]
        second_item = window.graphics_for_uid[b]
        other_item = window.graphics_for_uid[distant]
        monkeypatch.setattr(window, "rebuild_scene", lambda *args, **kwargs:
                            pytest.fail("Vertex commit rebuilt the entire map"))
        monkeypatch.setattr(window, "_autosave_work_copy", lambda: None)
        window.snap_action.setChecked(False)
        window.commit_vertex(22.0, 11.0, 1)
        assert window.doc.by_id[a].points[1].x == 22.0
        assert window.doc.by_id[b].points[0].x == 22.0
        assert window.graphics_for_uid[a] is first_item
        assert window.graphics_for_uid[b] is second_item
        assert window.graphics_for_uid[distant] is other_item
        assert window.history.undo_depth == 1
        assert window.view.edit_mode
    finally:
        window.close()


def test_gui_can_activate_all_same_code_vertices_without_choosing_each_polygon(qt_app):
    from geostudio.app import GeoStudioWindow
    window = GeoStudioWindow()
    try:
        doc, a, b, c, distant = buildings()
        window.doc = doc
        window.rebuild_scene(fit=False)
        window._select_uid(a)
        window.start_vertex_edit()
        # This calls exactly the handler wired to a click on a new vertex.
        window.activate_vertex_at(30, 10)
        assert window.edit_uid == b
        assert window.selected_uid == b
        assert window.view.edit_mode
        assert window.edit_scope_code == "5310"
        assert len(window.view.edit_points) == 4
        # Clicking a 5216-only vertex must never change the edit scope.
        window.activate_vertex_at(30, 20)
        assert window.edit_scope_code == "5310"
    finally:
        window.close()
