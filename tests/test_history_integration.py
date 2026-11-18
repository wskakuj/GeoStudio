"""Undo/redo wired into the window: real edits, real sidecars, real files.

These tests drive the same methods the interface calls (attribute edit, delete,
vertex move, new polygon, fill style, label drag) and then undo them, checking
that the map bytes return to the original state and that the work copy, the
dirty flag and the save point behave as agreed in docs/HISTORY_CONTRACT.md.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import (QApplication, QFileDialog, QInputDialog, QMessageBox)

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap

import sys
sys.path.insert(0, str(Path(__file__).parent))
from conftest import MapBuilder


def map_bytes() -> bytes:
    builder = MapBuilder(ext=(1000.0, 500000.0, 6500000.0, 500500.0, 6500500.0))
    builder.object(code="5216", uid="P1", fields={"A2": "12/3"},
                   points=[(500100.0, 6500100.0), (500200.0, 6500100.0),
                           (500200.0, 6500200.0), (500100.0, 6500200.0)])
    builder.object(code="5216", uid="P2", fields={"A2": "12/4"},
                   points=[(500200.0, 6500200.0), (500300.0, 6500200.0),
                           (500300.0, 6500300.0)])
    builder.raw(":ZZZ[zachowaj]")
    return builder.build()


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    source = tmp_path / "ZRODLO.MAP"
    source.write_bytes(map_bytes())
    widget = GeoStudioWindow()
    widget.doc = GeoMap.open(source)
    widget.catalog = {"5216": "Działki"}
    widget._base_title = "GeoStudio test"
    widget._update_dirty_title()
    widget.rebuild_scene(fit=False)
    # dialogs are irrelevant here; silence them and answer "yes" where asked
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    yield widget
    widget.close()


def bytes_of(window) -> bytes:
    return window.doc.to_bytes()


def test_opening_a_map_starts_clean(window):
    assert window.history.is_dirty is False
    assert window.history.can_undo is False
    assert window.windowTitle() == "GeoStudio test"


def test_attribute_edit_can_be_undone(window, monkeypatch):
    original = bytes_of(window)
    window._set_selected_uids(["P1"])
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        staticmethod(lambda *a, **k: ("12/9", True)))
    window._edit_field("A2", "12/3")
    assert window.history.undo_depth == 1
    assert window.history.is_dirty is True
    assert window.windowTitle().endswith("*")
    window.undo_last_edit()
    assert bytes_of(window) == original
    assert window.doc.by_id["P1"].fields["A2"] == "12/3"
    assert window.history.is_dirty is False


def test_setting_the_same_value_records_nothing(window, monkeypatch):
    window._set_selected_uids(["P1"])
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        staticmethod(lambda *a, **k: ("12/3", True)))
    window._edit_field("A2", "12/3")
    assert window.history.can_undo is False
    assert window.history.is_dirty is False


def test_delete_restores_geometry_and_sidecar_in_one_step(window):
    original = bytes_of(window)
    window.visual_styles["P1"] = {"fill": "#AABBCC", "opacity": 40}
    window.label_positions["P1"] = {"A2": [500150.0, 6500150.0]}
    window._set_selected_uids(["P1"])
    window.delete_selected()
    assert "P1" not in window.doc.by_id
    assert "P1" not in window.visual_styles
    assert "P1" not in window.label_positions
    assert window.history.undo_depth == 1

    window.undo_last_edit()
    assert bytes_of(window) == original
    assert window.doc.by_id["P1"].fields["A2"] == "12/3"
    assert window.visual_styles["P1"] == {"fill": "#AABBCC", "opacity": 40}
    assert window.label_positions["P1"] == {"A2": [500150.0, 6500150.0]}


def test_fill_style_change_is_undoable(window, monkeypatch):
    window._set_selected_uids(["P1"])
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("#112233@25", True)))
    window.fill_entry.setText("#112233@25")
    window.opacity_spin.setValue(25)
    window.apply_fill_style()
    assert window.visual_styles["P1"]["fill"] == "#112233"
    window.undo_last_edit()
    assert "P1" not in window.visual_styles
    assert window.history.is_dirty is False


def test_vertex_move_is_undoable(window):
    original = bytes_of(window)
    window.edit_uid = "P1"
    window.view.edit_mode = True
    window.edit_points = [(500100.0, 6500100.0), (500200.0, 6500100.0),
                          (500200.0, 6500200.0), (500100.0, 6500200.0)]
    window.snap_action.setChecked(False)
    window.commit_vertex(500110.0, 6500105.0, 0)
    assert bytes_of(window) != original
    assert window.history.undo_depth == 1
    window.undo_last_edit()
    assert bytes_of(window) == original


def test_new_polygon_is_undoable(window, monkeypatch):
    original = bytes_of(window)
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("5216", True)))
    monkeypatch.setattr(window, "_ask_polygon_attributes",
                        lambda: {"A1": "", "A2": "nowa", "A3": "", "A4": "",
                                 "A5": "", "A6": "", "TX": "", "MP": "0",
                                 "DT": "", "KR": ""})
    window.start_polygon()
    for point in ((500250.0, 6500250.0), (500300.0, 6500250.0), (500300.0, 6500300.0)):
        window.add_polygon_point(*point)
    window.finish_polygon()
    assert len(window.doc.objects) == 3
    assert window.history.undo_depth == 1
    window.undo_last_edit()
    assert bytes_of(window) == original
    assert len(window.doc.objects) == 2


def test_label_drag_produces_a_single_entry(window):
    window.label_positions["P1"] = {"A2": [500150.0, 6500150.0]}
    window._begin_label_history("P1", "A2")
    for step in range(5):                      # intermediate mouse moves
        window.label_positions["P1"]["A2"] = [500150.0 + step, 6500150.0]
    window._commit_label_history()
    assert window.history.undo_depth == 1
    window.undo_last_edit()
    assert window.label_positions["P1"]["A2"] == [500150.0, 6500150.0]


def test_aborted_label_drag_records_nothing(window):
    window.label_positions["P1"] = {"A2": [500150.0, 6500150.0]}
    window._begin_label_history("P1", "A2")
    window.label_positions["P1"]["A2"] = [1.0, 2.0]
    window._abort_label_history()
    assert window.history.can_undo is False
    assert window.label_positions["P1"]["A2"] == [500150.0, 6500150.0]


def test_redo_brings_the_edit_back(window, monkeypatch):
    window._set_selected_uids(["P1"])
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        staticmethod(lambda *a, **k: ("12/9", True)))
    window._edit_field("A2", "12/3")
    edited = bytes_of(window)
    window.undo_last_edit()
    window.redo_last_edit()
    assert bytes_of(window) == edited
    assert window.doc.by_id["P1"].fields["A2"] == "12/9"


def test_autosave_failure_does_not_block_undo(window, monkeypatch, qt_app):
    original = bytes_of(window)
    window._set_selected_uids(["P1"])
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        staticmethod(lambda *a, **k: ("12/9", True)))
    window._edit_field("A2", "12/3")
    edited = bytes_of(window)
    assert edited != original

    def broken():
        raise RuntimeError("kopia robocza zajęta")
    monkeypatch.setattr(window, "_autosave_work_copy", broken)

    window.undo_last_edit()          # applies in memory, only warns
    assert bytes_of(window) == original
    window.redo_last_edit()
    assert bytes_of(window) == edited


def test_complete_save_moves_the_save_point(window, tmp_path, monkeypatch):
    window._set_selected_uids(["P1"])
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        staticmethod(lambda *a, **k: ("12/9", True)))
    window._edit_field("A2", "12/3")
    assert window.history.is_dirty
    target = tmp_path / "WYNIK.MAP"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    window.save_map()
    assert target.exists()
    assert window.history.is_dirty is False
    assert not window.windowTitle().endswith("*")


def test_partial_save_does_not_move_the_save_point(window, tmp_path, monkeypatch):
    import geostudio.app as app_module

    window._set_selected_uids(["P1"])
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        staticmethod(lambda *a, **k: ("12/9", True)))
    window._edit_field("A2", "12/3")
    window.visual_styles["P1"] = {"fill": "#112233", "opacity": 25}

    def broken_sidecar(*a, **k):
        raise OSError("dysk pełny")
    monkeypatch.setattr(app_module, "write_styles", broken_sidecar)

    target = tmp_path / "WYNIK.MAP"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    window.save_map()
    assert target.exists()                     # the map was written
    assert window.history.is_dirty             # but the save is incomplete
    assert window.windowTitle().endswith("*")


def test_opening_another_map_clears_history(window, tmp_path, monkeypatch):
    window._set_selected_uids(["P1"])
    monkeypatch.setattr(QInputDialog, "getMultiLineText",
                        staticmethod(lambda *a, **k: ("12/9", True)))
    window._edit_field("A2", "12/3")
    assert window.history.is_dirty

    other = tmp_path / "INNA.MAP"
    other.write_bytes(map_bytes())
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(other), "")))
    window.open_map()
    assert window.history.can_undo is False
    assert window.history.is_dirty is False
    assert window.windowTitle() == "GeoStudio v0.14 — INNA.MAP"
