"""Workflow regressions: pinned B, isolated topology, 6900 lines and map furniture."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QDialog
from conftest import MapBuilder
from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.map_decorations import KINDS
from geostudio.visual_styles import write_styles, load_styles


def make_map():
    return (MapBuilder(ext=(1000, 0, 0, 150, 150))
            .object("5310", "A", {"A2": "Budynek A"},
                    [(5, 5), (15, 5), (15, 15), (5, 15)])
            .object("5310", "B", {"A2": "Budynek B"},
                    [(15, 5), (25, 5), (25, 15), (15, 15)])
            .object("5216", "C", {"A2": "Dzialka"},
                    [(30, 5), (40, 5), (40, 15), (30, 15)])
            .object("7900", "OLD", {"A2": "Stara legenda"},
                    [(100, 40), (130, 40), (130, 70), (100, 70)])
            .build())


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, monkeypatch):
    w = GeoStudioWindow()
    w.doc = GeoMap(make_map())
    w.catalog = {"5310": "Budynki", "5216": "Działki", "7900": "Oprawa"}
    w.rebuild_scene(fit=False)
    monkeypatch.setattr(w, "_autosave_work_copy", lambda: None)
    yield w
    w.close()


def test_b_keeps_multiple_highlighted_objects_and_unpins(win):
    win._select_uid("A")
    win.toggle_pin_active()
    assert win.pinned_uids == ["A"]
    win._select_uid("B")
    assert win.selected_uids == ["A", "B"]
    win.toggle_pin_active()
    assert win.pinned_uids == ["A", "B"]
    win._select_uid("C")
    assert win.selected_uids == ["A", "B", "C"]
    assert win.highlight_item is not None
    win._select_uid("A")
    assert win.selected_uid == "A"
    win.toggle_pin_active()
    assert win.pinned_uids == ["B"]
    win.clear_pinned_selection()
    assert win.selected_uids == []


def test_f_is_only_search_hotkey_and_ctrl_l_selects_code(win):
    edit_menu = next(a.menu() for a in win.menuBar().actions()
                     if a.text().replace("&", "") == "Edycja")
    shortcuts = {a.shortcut().toString(): a.text()
                 for a in edit_menu.actions() if not a.shortcut().isEmpty()}
    assert "Ctrl+H" not in shortcuts
    assert shortcuts["Ctrl+L"].startswith("Zaznacz wszystkie")
    assert shortcuts["B"].startswith("Utrwal")
    win._select_uid("A")
    win.select_all_same_code()
    assert set(win.selected_uids) == {"A", "B"}


def test_shared_vertex_sync_can_be_switched_off_and_on(win):
    win._select_uid("A")
    win.start_vertex_edit()
    assert win.sync_shared_vertices
    win.snap_action.setChecked(False)
    win.set_shared_vertex_sync(False)
    win.commit_vertex(16, 6, 1)
    assert win.doc.by_id["A"].points[1].x == 16
    assert win.doc.by_id["B"].points[0].x == 15
    win.set_shared_vertex_sync(True)
    win.commit_vertex(17, 7, 1)
    # B's coordinate is still 15: once corners separate, topology linking
    # must never seek a previously shared point and move it by accident.
    assert win.doc.by_id["B"].points[0].x == 15


def test_code_6900_creates_open_line_with_only_two_points(win, monkeypatch):
    monkeypatch.setattr(win, "_ask_polygon_attributes",
                        lambda: {"A1": "", "A2": "Nowa linia"})
    win._start_polygon_with_code("6900")
    assert win.draw_geometry_kind == "line"
    win.snap_action.setChecked(False)
    win.add_polygon_point(65, 65)
    win.add_polygon_point(75, 80)
    old_count = len(win.doc.objects)
    win.finish_polygon()
    assert len(win.doc.objects) == old_count + 1
    obj = win.doc.by_id[win.selected_uid]
    assert obj.code == "6900"
    assert len(obj.points) == 2
    assert not obj.is_closed
    assert (obj.points[1].x, obj.points[1].y) == (75.0, 80.0)
    assert GeoMap(win.doc.to_bytes()).checksum_valid


def test_decorations_are_editable_movable_undoable_and_persisted(win, tmp_path):
    for kind in KINDS:
        win.insert_map_decoration(kind, x=50, y=60)
    keys = [uid for uid in win.visual_styles if uid.startswith("layout:")]
    assert len(keys) == len(KINDS)
    for uid in keys:
        assert uid in win.decoration_items
        assert win.decoration_items[uid].data(0) == "geostudio-decoration"
    uid = keys[0]
    initial = win.visual_styles[uid].copy()
    win.move_map_decoration(uid, 55, 65)
    assert win.visual_styles[uid]["x"] == 55
    win.undo_last_edit()
    assert win.visual_styles[uid] == initial
    source = tmp_path / "COPY.MAP"
    source.write_bytes(win.doc.to_bytes())
    write_styles(source, win.visual_styles)
    reloaded = load_styles(source)
    for uid in keys:
        assert reloaded[uid]["kind"] == win.visual_styles[uid]["kind"]
        assert reloaded[uid]["details"] == win.visual_styles[uid]["details"]


def test_can_hide_only_selected_old_fragment_not_original_map(win):
    source = win.doc.to_bytes()
    win._select_uid("OLD")
    win.hide_selected_legacy_decoration()
    assert win.visual_styles["legacy-hidden:OLD"] == {"hidden": True}
    assert not win.graphics_for_uid["OLD"].isVisible()
    assert not any(obj.uid == "OLD" for obj in win._pick_candidates(115, 55))
    assert win.doc.to_bytes() == source
    win.restore_legacy_decorations()
    assert "legacy-hidden:OLD" not in win.visual_styles
    assert win.doc.to_bytes() == source


def test_autosave_one_slot_outside_map_directory_and_recovers(
        qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    source = tmp_path / "INPUT.MAP"
    source.write_bytes(make_map())
    win = GeoStudioWindow()
    try:
        win.doc = GeoMap.open(source)
        first = win._autosave_work_copy()
        assert first is not None and first.is_file()
        assert first.parent != source.parent
        assert sorted(source.parent.glob("*robocza*.MAP")) == []
        win.doc.update_field("A", "A2", "zmodyfikowany")
        second = win._autosave_work_copy()
        assert first == second
        assert GeoMap.open(first).by_id["A"].fields["A2"] == "zmodyfikowany"
        assert source.read_bytes() == make_map()
        recovered = GeoStudioWindow()
        try:
            monkeypatch.setattr(
                QFileDialog, "getOpenFileName", staticmethod(
                    lambda *a, **k: (str(source), "GEO-MAP (*.MAP)")))
            monkeypatch.setattr(
                QMessageBox, "question", staticmethod(
                    lambda *a, **k: QMessageBox.Yes))
            recovered.open_map()
            assert recovered.doc.by_id["A"].fields["A2"] == "zmodyfikowany"
            assert recovered._auto_copy_path == first
        finally:
            recovered.close()
    finally:
        win.close()
