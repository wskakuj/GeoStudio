"""GUI chrome tests: visual redesign must not change map geometry or editing."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QToolBar

from geostudio.app import GeoStudioWindow
from geostudio.ui_theme import PALETTES, theme_stylesheet, ui_icon


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qt_app):
    w = GeoStudioWindow()
    yield w
    w.close()


def test_both_themes_have_no_unexpanded_tokens():
    for mode, colors in PALETTES.items():
        stylesheet = theme_stylesheet(mode)
        assert len(stylesheet) > 3000
        assert "@window@" not in stylesheet
        assert "@accent@" not in stylesheet
        assert colors["accent"] in stylesheet
        assert "GeoStudioPrimaryButton" in stylesheet


def test_new_workspace_has_separate_toolbars_and_visible_mode(window):
    assert isinstance(window.file_toolbar, QToolBar)
    assert window.file_toolbar.objectName() == "GeoStudioFileToolbar"
    assert window.main_toolbar.objectName() == "GeoStudioToolsToolbar"
    assert window.panel_toolbar.objectName() == "GeoStudioPanelToolbar"
    assert window.mode_badge.text() == "ZAZNACZANIE"
    assert window.tool_actions["select"].isChecked()
    assert window.selected_count_label.objectName() == "GeoStudioSelectionBadge"
    assert window.info_dock.isHidden()
    assert all(window.tool_actions[k].isCheckable() for k in
               ("select", "pan", "draw", "edit", "labels"))


def test_theme_switch_keeps_map_scene_and_tool_actions(window):
    previous = window.theme_mode
    try:
        before = len(window.map_scene.items())
        window.set_theme("dark")
        assert window.theme_mode == "dark"
        assert window.theme_actions["dark"].isChecked()
        assert PALETTES["dark"]["accent"] in window.styleSheet()
        assert len(window.map_scene.items()) == before
        window.set_theme("light")
        assert window.theme_actions["light"].isChecked()
        assert PALETTES["light"]["accent"] in window.styleSheet()
        assert len(window.map_scene.items()) == before
    finally:
        window.set_theme(previous)


def test_mode_badge_tracks_non_destructive_navigation(window):
    window.start_pan()
    assert window.mode_badge.text() == "PRZESUWANIE"
    assert window.tool_actions["pan"].isChecked()
    window.cancel_edit()
    assert window.mode_badge.text() == "ZAZNACZANIE"
    assert window.tool_actions["select"].isChecked()


def test_icons_are_created_with_qt_not_bundled_assets(qt_app):
    assert not ui_icon("▣").isNull()
    assert not ui_icon("✎", "dark").isNull()


def test_invalid_theme_does_not_change_user_preferences(window):
    previous = window.theme_mode
    with pytest.raises(ValueError):
        window.set_theme("neon")
    assert window.theme_mode == previous
