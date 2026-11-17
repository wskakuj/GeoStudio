"""Regression tests for GeoStudio v0.6 search, colors and safe bulk operations."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from geostudio.geomap import GeoMap
from geostudio.object_search import search_objects
from geostudio.visual_styles import (
    parse_fill_code, fill_code, sidecar_path, load_styles, write_styles,
)
from test_geomap import fixture_map


def test_fill_codes_are_copyable_and_strict():
    assert parse_fill_code("#c42828@40") == ("#C42828", 40)
    assert parse_fill_code("C42828", 75) == ("#C42828", 75)
    assert fill_code("#C42828", 40) == "#C42828@40"
    for bad in ("not-a-color", "#fff", "#FFFFFF@101", "#FFFFFF@-1"):
        with pytest.raises(ValueError):
            parse_fill_code(bad)


def test_style_sidecar_roundtrip_while_map_remains_unmodified(tmp_path):
    file = tmp_path / "sample.MAP"
    raw = fixture_map()
    file.write_bytes(raw)
    styles = {"DEMO-01": {"fill": "#FF0000", "opacity": 45}}
    write_styles(file, styles)
    assert sidecar_path(file).exists()
    assert load_styles(file) == styles
    with pytest.raises(FileExistsError):
        write_styles(file, styles)
    assert file.read_bytes() == raw


def test_search_exact_code_and_attribute():
    doc = GeoMap(fixture_map())
    uid1 = doc.append_polygon([(2,2),(3,2),(3,3)],"5310",
                               fields={"A1": "bx", "A2": "budynek"})
    uid2 = doc.append_polygon([(4,4),(5,4),(5,5)],"5216",
                               fields={"A2": "29/16"})
    assert [o.uid for o in search_objects(doc.objects, "5310", "A1", "BX")] == [uid1]
    assert [o.uid for o in search_objects(doc.objects, "5216", "A2", "29/16")] == [uid2]
    assert search_objects(doc.objects, "5310", "A2", "29/16") == []


def test_bulk_deletion_preserves_other_records():
    doc = GeoMap(fixture_map())
    original = doc.to_bytes()
    uid1 = doc.append_polygon([(2,2),(3,2),(2,3)],"5310",label="a")
    uid2 = doc.append_polygon([(4,4),(5,4),(4,5)],"5310",label="b")
    assert doc.delete_objects([uid1,uid2]) == 2
    assert doc.to_bytes() == original
    assert GeoMap(doc.to_bytes()).checksum_valid


@pytest.fixture
def window(qtbot_dummy):
    # Only pytest-qt-free, headless QApplication is needed.
    from PySide6.QtWidgets import QApplication
    from geostudio.app import GeoStudioWindow
    app = QApplication.instance() or QApplication([])
    w = GeoStudioWindow()
    w.show()
    w.doc = GeoMap(fixture_map())
    w.rebuild_scene()
    app.processEvents()
    yield w
    w.close()


@pytest.fixture
def qtbot_dummy():
    pytest.importorskip("PySide6")
    return None


def test_esc_undoes_single_vertex_without_exiting_tool(window, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(
        lambda *args, **kwargs: ("5216", True)))
    window.start_polygon()
    for xy in ((5,5),(8,5),(7,8)):
        window.add_polygon_point(*xy)
    assert len(window.current_polygon) == 3
    QTest.keyClick(window.view, Qt.Key_Escape)
    assert len(window.current_polygon) == 2
    assert len(window.draft_points) == 2
    assert window.view.draw_mode
    QTest.keyClick(window.view, Qt.Key_Escape)
    QTest.keyClick(window.view, Qt.Key_Escape)
    assert len(window.current_polygon) == 0 and window.view.draw_mode


def test_restore_panels_and_search(window):
    assert window.layers_dock.isVisible()
    window.layers_dock.hide()
    assert not window.layers_dock.isVisible()
    window.restore_panels()
    assert window.layers_dock.isVisible()
    window.search_code.setText("5216")
    window.search_field.setCurrentText("A2")
    window.search_value.setText("TEST")
    window.run_search()
    assert window._search_uids == ["DEMO-01"]
    assert window.selected_uid == "DEMO-01"
    assert window.search_results.topLevelItemCount() == 1


def test_ctrl_h_and_bulk_style_fill(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    uid = window.doc.append_polygon([(2,2),(3,2),(2,3)],"5216","second")
    window.rebuild_scene()
    window._select_uid("DEMO-01")
    window.select_all_same_code()
    assert set(window.selected_uids) == {"DEMO-01", uid}
    window.fill_entry.setText("#AABBCC@37")
    window.apply_fill_style()
    assert all(window.visual_styles[x] == {"fill":"#AABBCC","opacity":37}
               for x in ("DEMO-01",uid))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *args, **kwargs: QMessageBox.Yes))
    window.delete_selected()
    assert len(window.doc.objects) == 0
    assert window.visual_styles == {}


def test_open_remembers_last_directory(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QFileDialog
    path = tmp_path / "sample.MAP"
    path.write_bytes(fixture_map())
    seen = []
    def fake_open(*args):
        seen.append(args[2])
        return str(path), "GEO-MAP (*.MAP)"
    monkeypatch.setattr(QFileDialog,"getOpenFileName",staticmethod(fake_open))
    window.settings.setValue("last_map_dir",str(tmp_path))
    window.open_map()
    assert seen == [str(tmp_path)]
    assert window.settings.value("last_map_dir") == str(tmp_path)
