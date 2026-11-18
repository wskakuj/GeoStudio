"""Regression tests for E/P shortcuts, object parameters and unrestricted snapping."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog

from conftest import MapBuilder
from geostudio.app import GeoStudioWindow
from geostudio.feature_dialogs import ObjectParametersDialog
from geostudio.geomap import GeoMap
from geostudio.geometry_index import GeometryIndex
from geostudio.selection import SelectionContext, snap_at


def sample_doc():
    data = (MapBuilder(ext=(1000, -5, -5, 55, 30))
            .object("5310", "BUILD", {"A1": "b", "A2": "test"},
                    [(0, 0), (10, 0), (10, 10), (0, 10)])
            .object("5310", "SAME", {"A1": "c"},
                    [(10, 0), (15, 0), (15, 10), (10, 10)])
            .object("5216", "OTHER", {"A2": "parcel"},
                    [(20, 0), (30, 0), (30, 10), (20, 10)])
            .object("1246", "MARK", points=[(20, 5)], closed=False)
            .object("6000", "LINE", points=[(40, 0), (40, 20)],
                    closed=False)
            .build())
    return GeoMap(data)


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app):
    win = GeoStudioWindow()
    win.doc = sample_doc()
    win.catalog = {"5310": "Budynki", "5216": "Działki",
                   "1246": "Graniczniki", "6000": "Linie"}
    win.hidden_layers = {"Graniczniki"}
    win.rebuild_scene(fit=False)
    yield win
    win.close()


def test_shortcut_mapping_matches_requested_keys(window):
    editor_menu = next(action.menu() for action in window.menuBar().actions()
                       if action.text().replace("&", "") == "Edycja")
    shortcuts = {action.shortcut().toString(): action.text()
                 for action in editor_menu.actions() if not action.shortcut().isEmpty()}
    assert "Parametry aktywnego" in shortcuts["E"]
    assert "węzły" in shortcuts["P"]
    assert "poligon" in shortcuts["N"]
    assert window.tool_actions["edit"].toolTip().find("(P)") >= 0
    assert window.tool_actions["draw"].toolTip().find("(N)") >= 0


def test_object_dialog_displays_real_attributes_and_coordinates(window):
    obj = window.doc.by_id["BUILD"]
    dialog = ObjectParametersDialog(obj, symbols={"5310": "Budynek"},
                                    layer_name="Budynki")
    try:
        assert dialog.entries["A1"].text() == "b"
        assert dialog.entries["A2"].text() == "test"
        assert dialog.findChild(type(dialog.entries["A1"]), "object_field_A2")
        from PySide6.QtWidgets import QTreeWidget
        coords = dialog.findChild(QTreeWidget, "GeoStudioObjectCoordinates")
        assert coords.topLevelItemCount() == 5  # Closing vertex is preserved.
        assert dialog.changed_fields() == {}
        dialog.entries["A2"].setText("nowy opis")
        assert dialog.changed_fields() == {"A2": "nowy opis"}
    finally:
        dialog.close()


def test_e_dialog_commits_all_changed_attributes_as_one_undo(window, monkeypatch):
    from geostudio import app

    class AcceptedParameters:
        def __init__(self, obj, **_kwargs):
            assert obj.uid == "BUILD"

        def exec(self):
            return QDialog.Accepted

        def changed_fields(self):
            return {"A1": "k", "A2": "odnowiony"}

    window._select_uid("BUILD")
    monkeypatch.setattr(app, "ObjectParametersDialog", AcceptedParameters)
    window.show_active_object_parameters()
    assert window.doc.by_id["BUILD"].fields["A1"] == "k"
    assert window.doc.by_id["BUILD"].fields["A2"] == "odnowiony"
    assert window.history.undo_depth == 1
    window.undo_last_edit()
    assert window.doc.by_id["BUILD"].fields["A1"] == "b"
    assert window.doc.by_id["BUILD"].fields["A2"] == "test"


def test_hidden_granicznik_is_a_snap_target_but_not_selectable(window):
    ctx = SelectionContext(
        doc=window.doc, geometry_index=GeometryIndex(window.doc.objects),
        layer_for_uid=window.layer_for_uid,
        hidden_layers=frozenset(window.hidden_layers),
        radius=1.5)
    assert snap_at(ctx, 20.2, 5.3) is None
    snap = snap_at(ctx, 20.2, 5.3, include_hidden_markers=True)
    assert snap is not None
    assert snap.uid == "MARK"
    assert snap.kind == "vertex"
    window.snap_action.setChecked(False)
    assert window._snap(20.2, 5.3) is None


def test_cross_code_vertex_snap_does_not_move_foreign_geometry(window, monkeypatch):
    window._select_uid("BUILD")
    window.start_vertex_edit()
    # More than six screen pixels from the original BUILD vertex; snapping
    # to an object of another code is allowed but only BUILD+SAME move.
    monkeypatch.setattr(window, "_autosave_work_copy", lambda: None)
    before_other = [(p.x, p.y) for p in window.doc.by_id["OTHER"].points]
    before_marker = [(p.x, p.y) for p in window.doc.by_id["MARK"].points]
    window.commit_vertex(20.2, 5.3, 1)
    assert (window.doc.by_id["BUILD"].points[1].x,
            window.doc.by_id["BUILD"].points[1].y) == (20.0, 5.0)
    assert (window.doc.by_id["SAME"].points[0].x,
            window.doc.by_id["SAME"].points[0].y) == (20.0, 5.0)
    assert [(p.x, p.y) for p in window.doc.by_id["OTHER"].points] == before_other
    assert [(p.x, p.y) for p in window.doc.by_id["MARK"].points] == before_marker


def test_snap_finds_edges_of_other_codes(window):
    snap = window._snap(40.5, 12.0)
    assert snap is not None
    assert snap.kind == "edge"
    assert snap.code == "6000"
    assert (snap.x, snap.y) == pytest.approx((40, 12))
