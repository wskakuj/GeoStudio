"""GUI chrome tests: visual redesign must not change map geometry or editing."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QToolBar
from PySide6.QtCore import Qt

from geostudio.app import GeoStudioWindow
from geostudio.ui_theme import PALETTES, theme_stylesheet, ui_icon


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    """Keep window preferences out of the developer's real QSettings.

    Without this, a run after someone used the modern style would start in
    that style and the classic-style assertions below would fail for a reason
    that has nothing to do with the code.
    """
    from PySide6.QtCore import QSettings
    store = {}
    monkeypatch.setattr(QSettings, "value",
                        lambda self, key, default=None, type=None: store.get(key, default))
    monkeypatch.setattr(QSettings, "setValue",
                        lambda self, key, value: store.__setitem__(key, value))
    return store


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
    assert window.main_toolbar.objectName() == "GeoStudioToolPalette"
    assert window.workspace.map_view is window.view
    assert window.main_toolbar.orientation() == Qt.Vertical
    assert window.workspace.map_view is window.view
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


# --- modern style switch (Widok → Styl interfejsu) -----------------------

from geostudio.ui_theme import (MODERN_PALETTES, STYLE_CLASSIC, STYLE_MODERN,
                                modern_stylesheet, stylesheet)

# Classic output is pinned: the new style must not silently rewrite the old one.
CLASSIC_SHA256 = {
    "light": "1ce501e9c27831b6957ee2d16684c10d7658067a1ebabc659acbf14e079d577e",
    "dark": "297a1c74550dd4fc221339b89047467a73fb6acff9be3d55bd6e781d9ff824d4",
}


def test_classic_stylesheet_is_byte_identical_to_the_previous_release():
    import hashlib
    for theme, digest in CLASSIC_SHA256.items():
        assert hashlib.sha256(theme_stylesheet(theme).encode()).hexdigest() == digest


def test_modern_stylesheet_is_complete_for_both_themes():
    for theme, colors in MODERN_PALETTES.items():
        css = modern_stylesheet(theme)
        assert "@" not in css                      # every token expanded
        assert colors["accent"] in css
        assert colors["window"] in css
        assert "GeoStudioPrimaryButton" in css     # every classic selector kept
        assert "GeoStudioMapDocumentTabs" in css


def test_stylesheet_dispatches_and_falls_back_to_classic():
    assert stylesheet("light") == theme_stylesheet("light")
    assert stylesheet("light", STYLE_CLASSIC) == theme_stylesheet("light")
    assert stylesheet("dark", STYLE_MODERN) == modern_stylesheet("dark")
    assert stylesheet("dark", "nieznany") == theme_stylesheet("dark")


def test_modern_style_differs_from_classic():
    assert modern_stylesheet("dark") != theme_stylesheet("dark")
    assert modern_stylesheet("light") != modern_stylesheet("dark")


def test_style_switch_updates_window_and_keeps_the_scene(window):
    previous = window.style_mode
    try:
        before = len(window.map_scene.items())
        window.set_style(STYLE_MODERN)
        assert window.style_mode == STYLE_MODERN
        assert window.style_actions[STYLE_MODERN].isChecked()
        assert MODERN_PALETTES[window.theme_mode]["accent"] in window.styleSheet()
        assert len(window.map_scene.items()) == before

        window.set_style(STYLE_CLASSIC)
        assert window.style_actions[STYLE_CLASSIC].isChecked()
        assert PALETTES[window.theme_mode]["accent"] in window.styleSheet()
        assert len(window.map_scene.items()) == before
    finally:
        window.set_style(previous)


def test_style_and_theme_combine(window):
    previous_style, previous_theme = window.style_mode, window.theme_mode
    try:
        window.set_style(STYLE_MODERN)
        window.set_theme("dark")
        assert window.styleSheet() == modern_stylesheet("dark")
        window.set_theme("light")
        assert window.styleSheet() == modern_stylesheet("light")
    finally:
        window.set_style(previous_style)
        window.set_theme(previous_theme)


def test_style_switch_is_persisted(window):
    previous = window.style_mode
    try:
        window.set_style(STYLE_MODERN)
        assert window.settings.value("ui/style") == STYLE_MODERN
        window.set_style(STYLE_CLASSIC)
        assert window.settings.value("ui/style") == STYLE_CLASSIC
    finally:
        window.set_style(previous)


def test_invalid_style_is_rejected_without_changing_preferences(window):
    previous = window.style_mode
    with pytest.raises(ValueError):
        window.set_style("futurystyczny")
    assert window.style_mode == previous
    # Nothing was written: the stored value is either untouched or absent.
    assert window.settings.value("ui/style") in (None, previous)


def test_view_menu_and_ribbon_expose_the_style_switch(window):
    assert set(window.style_actions) == {STYLE_CLASSIC, STYLE_MODERN}
    assert window.style_menu.title() == "Styl interfejsu"
    assert all(action.isCheckable() for action in window.style_actions.values())
    assert sum(action.isChecked() for action in window.style_actions.values()) == 1
