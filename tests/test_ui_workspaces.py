"""Contextual workspaces maximise the map without changing source geometry."""
from __future__ import annotations

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from test_geomap import fixture_map


@pytest.fixture(scope='module')
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app):
    w = GeoStudioWindow()
    yield w
    w.close()


def test_workspaces_are_accessible_by_menu_and_shortcuts(window):
    actions = window.workspace_actions
    assert set(actions) == {'map', 'edit', 'search'}
    assert actions['map'].shortcut().toString() == 'Ctrl+1'
    assert actions['edit'].shortcut().toString() == 'Ctrl+2'
    assert actions['search'].shortcut().toString() == 'Ctrl+3'
    assert window.workspace_button.menu() is window.workspace_menu


def test_search_and_inspector_are_tabs_in_same_dock_area(window):
    assert window.search_dock in window.tabifiedDockWidgets(window.properties_dock)
    window.set_workspace('search')
    assert window.workspace_mode == 'search'
    assert not window.search_dock.isHidden()
    window.set_workspace('edit')
    assert window.workspace_mode == 'edit'
    assert not window.properties_dock.isHidden()


def test_focus_mode_leaves_geometry_and_selection_unchanged(window):
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene()
    window._select_uid('DEMO-01')
    before = (window.doc.to_bytes(), window.selected_uid,
              len(window.map_scene.items()))
    window.set_workspace('edit')
    window.toggle_focus_workspace()
    assert window.workspace_mode == 'map'
    assert window.layers_dock.isHidden()
    assert window.properties_dock.isHidden()
    assert window.search_dock.isHidden()
    assert window.panel_toolbar.isHidden()
    window.toggle_focus_workspace()
    assert window.workspace_mode == 'edit'
    assert not window.layers_dock.isHidden()
    assert not window.properties_dock.isHidden()
    assert (window.doc.to_bytes(), window.selected_uid,
            len(window.map_scene.items())) == before


def test_search_shortcut_preserves_search_edit_controls(window):
    window.set_workspace('map')
    window.show_search()
    assert window.workspace_mode == 'search'
    assert not window.search_dock.isHidden()
    assert window.search_code.hasFocus() or not window.isVisible()


def test_unknown_workspace_does_not_change_ui(window):
    previous = window.workspace_mode
    with pytest.raises(ValueError):
        window.set_workspace('broken')
    assert window.workspace_mode == previous
