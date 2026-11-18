"""Workspace v2: readability and navigation without altering GEO-MAP data."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QToolButton

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.ui_theme import ui_icon
from test_geomap import fixture_map


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(qt_app):
    w = GeoStudioWindow()
    yield w
    w.close()


def test_compact_command_bar_keeps_core_actions(window):
    assert window.open_toolbar_action.text() == "Otwórz mapę"
    assert window.save_toolbar_action.text() == "Zapisz jako"
    assert isinstance(window.data_button, QToolButton)
    assert len(window.data_button.menu().actions()) == 2
    assert len(window.export_button.menu().actions()) == 2
    assert len(window.map_settings_button.menu().actions()) == 3
    assert window.labels_action in window.map_settings_button.menu().actions()
    assert window.snap_action in window.main_toolbar.actions()
    assert window.tool_actions["select"].isChecked()


def test_the_icon_system_uses_semantic_vector_shapes(qt_app):
    for name in ("folder", "save", "fit", "select", "hand", "polygon",
                 "vertices", "search", "layers", "properties", "snap", "export"):
        assert not ui_icon(name, "dark").isNull()


def test_layer_filter_never_hides_geometry(window):
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene(fit=False)
    rows = window.layers_tree.topLevelItemCount()
    assert rows >= 1
    name = window.layers_tree.topLevelItem(0).text(0)
    existing_visibility = {
        uid: item.isVisible() for uid, item in window.graphics_for_uid.items()
    }
    window.layer_filter.setText("not-a-real-layer-keyword")
    assert all(window.layers_tree.topLevelItem(i).isHidden() for i in range(rows))
    assert "0 z" in window.layers_summary.text()
    assert existing_visibility == {
        uid: item.isVisible() for uid, item in window.graphics_for_uid.items()
    }
    window.layer_filter.setText(name[:4])
    assert not window.layers_tree.topLevelItem(0).isHidden()
    window.layer_filter.clear()
    assert all(not window.layers_tree.topLevelItem(i).isHidden() for i in range(rows))


def test_bulk_layer_visibility_can_be_reversed(window):
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene(fit=False)
    assert window.layers_tree.topLevelItemCount()
    window._set_all_layers_visible(False)
    assert all(not item.isVisible() for item in window.graphics_for_uid.values())
    assert all(window.layers_tree.topLevelItem(i).checkState(0) ==
               window.layers_tree.topLevelItem(0).checkState(0)
               for i in range(window.layers_tree.topLevelItemCount()))
    window._set_all_layers_visible(True)
    assert all(item.isVisible() for item in window.graphics_for_uid.values())


def test_inspector_has_readable_attributes_and_separate_style_tab(window):
    assert window.inspector_tabs.count() == 2
    assert window.inspector_tabs.tabText(0) == "Atrybuty"
    assert window.inspector_tabs.tabText(1) == "Wygląd"
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene(fit=False)
    window._select_uid("DEMO-01")
    assert window.props.topLevelItemCount() >= 2
    assert window.object_title.text() != "Wybierz obiekt na mapie"
    assert "Kod" in window.object_details.text()
    assert window.props.topLevelItem(0).toolTip(1)
    window.fill_entry.setText("#D94848@40")
    assert "#D94848" in window.fill_preview.text()
    assert "40%" in window.fill_preview.text()
    window._select_uid(None)
    assert window.object_title.text() == "Wybierz obiekt na mapie"


def test_existing_canvas_is_not_rebuilt_when_theme_switches(window):
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene(fit=False)
    before = [(uid, item.path().elementCount()) for uid, item in
              window.graphics_for_uid.items() if hasattr(item, "path")]
    old = window.theme_mode
    try:
        window.set_theme("light")
        window.set_theme("dark")
        after = [(uid, item.path().elementCount()) for uid, item in
                 window.graphics_for_uid.items() if hasattr(item, "path")]
        assert before == after
    finally:
        window.set_theme(old)


def test_coordinate_readout_is_always_visible_without_overwriting_messages(window):
    window.status.showMessage("Zapisano kopię roboczą")
    window.on_coordinate(515432.98765, 668123.45678)
    assert "515432.988" in window.coordinate_readout.text()
    assert "668123.457" in window.coordinate_readout.text()
    assert window.status.currentMessage() == "Zapisano kopię roboczą"


def test_docks_have_room_for_attribute_values(window):
    assert window.layers_dock.minimumWidth() >= 260
    assert window.properties_dock.minimumWidth() >= 330
    assert window.panel_toolbar.width() <= 50
