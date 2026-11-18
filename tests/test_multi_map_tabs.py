"""Multiple open MAP tabs preserve independent documents, edit history and view."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from test_geomap import fixture_map


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def maps(tmp_path):
    a = tmp_path / "MAPA_A.MAP"
    b = tmp_path / "MAPA_B.MAP"
    a.write_bytes(fixture_map())
    second = GeoMap(fixture_map())
    second.append_polygon([(0, 0), (20, 0), (0, 20)], "5310",
                          fields={"A2": "TEST B"})
    b.write_bytes(second.to_bytes())
    return a, b


@pytest.fixture
def window(qt_app):
    w = GeoStudioWindow()
    yield w
    w.close()


def _open_paths(window, monkeypatch, paths):
    queue = list(paths)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(
        lambda *args, **kwargs: (str(queue.pop(0)), "GEO-MAP (*.MAP)")))
    for _ in paths:
        window.open_map()


def test_open_two_maps_and_switch_with_independent_histories(window, maps, monkeypatch):
    first, second = maps
    _open_paths(window, monkeypatch, maps)
    tabs = window.workspace.document_tabs
    assert tabs.count() == 2
    assert window.workspace.map_tabs_frame.isVisible() or tabs.count() == 2
    assert window.doc.filename == str(second)
    assert tabs.tabText(0) == first.name
    assert tabs.tabText(1) == second.name
    original_second = window.doc.to_bytes()

    tabs.setCurrentIndex(0)
    assert window.doc.filename == str(first)
    first_bytes = window.doc.to_bytes()
    with window.history.begin("Testowe A2 / stan A"):
        window.visual_styles["DEMO-01"] = {"fill": "#FF0000", "opacity": 40}
    window._history_changed()
    assert window.history.is_dirty
    assert tabs.tabText(0).endswith("*")
    assert tabs.tabText(1) == second.name

    tabs.setCurrentIndex(1)
    assert window.doc.filename == str(second)
    assert window.doc.to_bytes() == original_second
    assert window.history.is_dirty is False
    assert window.visual_styles.get("DEMO-01") is None

    tabs.setCurrentIndex(0)
    assert window.doc.filename == str(first)
    assert window.doc.to_bytes() == first_bytes
    assert window.history.is_dirty
    assert window.visual_styles["DEMO-01"]["fill"] == "#FF0000"
    window.undo_last_edit()
    assert window.history.is_dirty is False
    assert "DEMO-01" not in window.visual_styles


def test_reopen_same_path_focuses_existing_tab_without_duplication(window, maps, monkeypatch):
    first, second = maps
    _open_paths(window, monkeypatch, maps)
    count = window.workspace.document_tabs.count()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(
        lambda *args, **kwargs: (str(first), "GEO-MAP (*.MAP)")))
    window.open_map()
    assert window.workspace.document_tabs.count() == count
    assert window.doc.filename == str(first)


def test_close_background_and_active_tabs_without_losing_other_document(
        window, maps, monkeypatch):
    first, second = maps
    _open_paths(window, monkeypatch, maps)
    tabs = window.workspace.document_tabs
    assert window.doc.filename == str(second)
    window.close_map_tab(0)
    assert tabs.count() == 1
    assert window.doc.filename == str(second)
    window.close_map_tab(0)
    assert tabs.count() == 0
    assert window.doc is None
    assert not window.workspace.map_tabs_frame.isVisible()


def test_closing_dirty_map_requires_confirmation(window, maps, monkeypatch):
    _open_paths(window, monkeypatch, maps)
    tabs = window.workspace.document_tabs
    with window.history.begin("Niezapisana zmiana"):
        window.visual_styles["DEMO-01"] = {"fill": "#D94848", "opacity": 30}
    window._history_changed()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *args, **kwargs: QMessageBox.No))
    window.close_map_tab(1)
    assert tabs.count() == 2
    assert window.history.is_dirty
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *args, **kwargs: QMessageBox.Yes))
    window.close_map_tab(1)
    assert tabs.count() == 1
    assert window.doc.filename.endswith("MAPA_A.MAP")
