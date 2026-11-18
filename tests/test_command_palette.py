"""ArcGIS-like productivity affordances: command search and collapsible ribbon.

Tests guard QAction identity and preserve document state when navigating chrome.
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton

from geostudio.app import GeoStudioWindow
from geostudio.command_palette import CommandPalette
from geostudio.geomap import GeoMap
from test_geomap import fixture_map


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    w = GeoStudioWindow()
    yield w
    if w._command_palette is not None:
        w._command_palette.close()
    w.close()


def test_ribbon_quick_access_uses_original_actions(window):
    quick = window.ribbon.findChildren(QToolButton, "GeoStudioQuickAccessButton")
    linked = [b.defaultAction() for b in quick]
    assert window.open_toolbar_action in linked
    assert window.save_toolbar_action in linked
    assert window.ribbon_undo_action in linked
    assert window.ribbon_redo_action in linked
    assert len(quick) == 4


def test_collapsible_ribbon_uses_less_height_and_restores_tools(window):
    ribbon = window.ribbon
    original = (ribbon.tabs.minimumHeight(), ribbon.tabs.maximumHeight())
    action = window.tool_actions["select"]
    assert action.isChecked()
    ribbon.set_collapsed(True)
    assert ribbon.collapsed
    assert ribbon.tabs.maximumHeight() <= 40
    assert action.isChecked()
    ribbon.set_collapsed(False)
    assert not ribbon.collapsed
    assert (ribbon.tabs.minimumHeight(), ribbon.tabs.maximumHeight()) == original
    assert action.isChecked()


def test_edit_mode_expands_ribbon_and_selects_context_tab(window):
    ribbon = window.ribbon
    ribbon.select_tab("Mapa")
    ribbon.set_collapsed(True)
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene(fit=False)
    window._select_uid("DEMO-01")
    before = window.doc.to_bytes()
    window.start_vertex_edit()
    assert not ribbon.collapsed
    assert ribbon.tabs.tabText(ribbon.tabs.currentIndex()) == "Edycja"
    assert window.doc.to_bytes() == before
    window.cancel_edit()


def test_command_palette_finds_commands_with_or_without_accents(app):
    dialog = CommandPalette()
    actions = [QAction("Współrzędne", dialog), QAction("Skala opracowania", dialog)]
    dialog.set_commands(list(zip(["Współrzędne", "Skala opracowania"], actions)))
    dialog.query.setText("wspolrzedne")
    assert dialog.results.count() == 1
    assert dialog.results.item(0).data(Qt.ItemDataRole.UserRole) is actions[0]
    dialog.query.setText("skala")
    assert dialog.results.count() == 1
    assert dialog.results.item(0).data(Qt.ItemDataRole.UserRole) is actions[1]
    dialog.close()


def test_command_palette_executes_same_qaction_not_new_callback(app):
    dialog = CommandPalette()
    events = []
    command = QAction("Włącz warstwy", dialog)
    command.triggered.connect(lambda: events.append("run"))
    dialog.set_commands([("Włącz warstwy", command)])
    dialog.query.setText("warstwy")
    dialog.activate_current()
    assert events == ["run"]
    dialog.close()


def test_disabled_palette_action_cannot_run(app):
    dialog = CommandPalette()
    events = []
    command = QAction("Usuń wybrany", dialog)
    command.setEnabled(False)
    command.triggered.connect(lambda: events.append("removed"))
    dialog.set_commands([("Usuń wybrany", command)])
    dialog.activate_current()
    assert events == []
    dialog.close()


def test_arrow_keys_navigate_palette_results(app):
    dialog = CommandPalette()
    acts = [QAction(name, dialog) for name in ("Zapisz", "Zaznacz", "Zamknij")]
    dialog.set_commands(list(zip(["Zapisz", "Zaznacz", "Zamknij"], acts)))
    assert dialog.results.currentRow() == 0
    QTest.keyClick(dialog.query, Qt.Key.Key_Down)
    assert dialog.results.currentRow() == 1
    QTest.keyClick(dialog.query, Qt.Key.Key_Up)
    assert dialog.results.currentRow() == 0
    dialog.close()


def test_main_window_palette_exposes_real_tools_without_mutation(window):
    window.doc = GeoMap(fixture_map())
    window.rebuild_scene(fit=False)
    before = window.doc.to_bytes()
    commands = window._searchable_actions()
    assert any(action is window.open_toolbar_action for _label, action in commands)
    assert any(action is window.tool_actions["edit"] for _label, action in commands)
    assert window.command_palette_action.shortcut().toString() == "Ctrl+K"
    window.show_command_palette()
    palette = window._command_palette
    palette.query.setText("poligon")
    assert palette.results.count() >= 1
    assert window.doc.to_bytes() == before
    palette.close()
