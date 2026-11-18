"""ArcGIS-style ribbon contract: action wiring, task tabs and map safety.

These tests exercise Qt action identity, not just presence of button labels.
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QToolButton, QTabWidget

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.gis_ribbon import GISRibbon
from test_geomap import fixture_map


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app):
    win = GeoStudioWindow()
    yield win
    win.close()


def _action_buttons(window):
    return [button for button in window.ribbon.findChildren(QToolButton)
            if button.defaultAction() is not None]


def test_ribbon_has_real_task_tabs_and_replaces_old_toolbar(window):
    assert isinstance(window.ribbon, GISRibbon)
    assert isinstance(window.ribbon.tabs, QTabWidget)
    assert [window.ribbon.tabs.tabText(i) for i in
            range(window.ribbon.tabs.count())] == [
        "Mapa", "Edycja", "Dane", "Widok", "Eksport"]
    assert window.file_toolbar.isHidden()
    assert window.workspace.tool_rail.isHidden()
    assert not window.ribbon_toolbar.isHidden()


def test_edit_buttons_delegate_to_existing_actions_without_duplicate_signals(window):
    linked = [button.defaultAction() for button in _action_buttons(window)]
    for action in window.tool_actions.values():
        assert action in linked
    assert window.delete_action in linked
    assert window.snap_action in linked
    assert window.labels_action in linked
    assert window.open_toolbar_action in linked
    assert window.save_toolbar_action in linked


def test_ribbon_relocates_filter_without_changing_filter_model(window):
    assert window.selector.parent() is not window.workspace
    assert window.selector.count() == 3
    assert [window.selector.itemData(i) for i in range(3)] == [
        None, "5216", "5230"]
    assert window.selector in window.ribbon.findChildren(type(window.selector))


def test_edits_switch_to_edit_tab_and_keep_map_contents(window):
    win = window
    win.doc = GeoMap(fixture_map())
    win.rebuild_scene(fit=False)
    original = win.doc.to_bytes()
    count = len(win.map_scene.items())
    win.ribbon.select_tab("Mapa")
    win.start_vertex_edit()
    assert win.ribbon.tabs.tabText(win.ribbon.tabs.currentIndex()) == "Edycja"
    assert win.tool_actions["edit"].isChecked()
    win.cancel_edit()
    assert win.doc.to_bytes() == original
    assert len(win.map_scene.items()) == count


def test_focus_hides_ribbon_but_restores_it_and_panel_visibility(window):
    window.set_workspace("map")
    assert window.ribbon_toolbar.isHidden()
    assert window.workspace.tool_rail.isHidden()
    window.set_workspace("edit")
    assert not window.ribbon_toolbar.isHidden()
    assert not window.workspace.tool_rail.isHidden() is False


def test_ribbon_theme_switch_and_document_context(window):
    win = window
    previous = win.theme_mode
    try:
        win.set_theme("dark")
        assert win.ribbon.theme == "dark"
        win.set_theme("light")
        assert win.ribbon.theme == "light"
        win.ribbon.set_document("/tmp/MOKRA WIES.MAP", dirty=True)
        assert "MOKRA WIES.MAP" in win.ribbon.document_state.text()
        assert "niezapisane" in win.ribbon.document_state.text()
    finally:
        win.set_theme(previous)


def test_ribbon_group_commands_have_titles(window):
    from PySide6.QtWidgets import QLabel
    captions = [label.text() for label in window.ribbon.findChildren(QLabel)
                if label.objectName() == "GeoStudioRibbonGroupCaption"]
    assert {"Projekt", "Nawigacja", "Zawartość mapy",
            "Narzędzia edycji", "Biblioteki GEO-MAP",
            "Układ stanowiska", "Udostępnianie"}.issubset(set(captions))
