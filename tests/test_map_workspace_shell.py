"""Map-first UI integration: the editor's scene/editor actions remain intact."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.workspace_shell import MapWorkspace
from test_geomap import fixture_map


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    w = GeoStudioWindow()
    yield w
    w.close()


def test_real_map_view_has_contextual_shell_and_vertical_tool_palette(window):
    assert isinstance(window.centralWidget(), MapWorkspace)
    assert window.workspace.map_view is window.view
    assert window.main_toolbar.parent() is window.workspace.tool_rail
    assert window.main_toolbar.orientation() == Qt.Vertical
    assert window.selector.parent() is not window.main_toolbar
    assert window.workspace.focus_button.text() == "Skupienie"
    assert window.workspace.document_name.text().startswith("Otwórz plik")
    assert set(window.tool_actions) == {"select", "pan", "draw", "edit", "labels"}


def test_map_shell_updates_document_and_dirty_status(window):
    window.doc = GeoMap(fixture_map(), filename="/demo/TEST.MAP")
    window.rebuild_scene()
    window._update_dirty_title()
    assert "TEST.MAP" in window.workspace.document_name.text()
    assert "TEST.MAP" in window.workspace.document_name.toolTip()
    window.workspace.set_document(window.doc.filename, dirty=True)
    assert "zmieniono" in window.workspace.document_name.text()
    assert window.workspace.document_hint.text() == "NIEZAPISANE ZMIANY"


def test_map_only_mode_hides_edit_palette_but_not_canvas(window):
    window.set_workspace("map")
    assert window.workspace.tool_rail.isHidden()
    assert window.workspace.canvas_footer.isHidden()
    assert window.workspace.map_view is window.view
    assert window.workspace.focus_button.text() == "Powrót do edycji"
    window.set_workspace("edit")
    assert not window.workspace.tool_rail.isHidden()
    assert window.workspace.focus_button.text() == "Skupienie"


def test_mode_specific_help_changes_with_active_tool(window):
    window.workspace.set_tool("ZAZNACZANIE")
    assert "Ctrl+klik" in window.workspace.canvas_footer.text()
    window.workspace.set_tool("EDYCJA WIERZCHOŁKÓW")
    assert "węzeł" in window.workspace.canvas_footer.text()
    window.workspace.set_tool("PRZESUWANIE ETYKIET")
    assert "Przeciągnij napis" in window.workspace.canvas_footer.text()


def test_inspector_quick_actions_have_correct_enabled_state(window):
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene()
    window._set_selected_uids([])
    assert not window.edit_object_button.isEnabled()
    assert not window.copy_object_button.isEnabled()
    window._select_uid("DEMO-01")
    assert window.edit_object_button.isEnabled()
    assert window.copy_object_button.isEnabled()
    assert "wierzchołków" in window.object_metrics.text()
    window.copy_selected_uid()
    assert QApplication.clipboard().text() == "DEMO-01"
    window._select_uid(None)
    assert not window.edit_object_button.isEnabled()


def test_layers_inspector_and_search_share_a_single_sidebar(window):
    assert window.dockWidgetArea(window.layers_dock) == Qt.LeftDockWidgetArea
    assert window.dockWidgetArea(window.properties_dock) == Qt.LeftDockWidgetArea
    assert window.dockWidgetArea(window.search_dock) == Qt.LeftDockWidgetArea
    assert window.properties_dock in window.tabifiedDockWidgets(window.layers_dock)
    assert window.search_dock in window.tabifiedDockWidgets(window.layers_dock)
    assert window.panel_toolbar.isHidden()
