"""Tests for picking, selection arithmetic and snapping.

The golden snapshot is the safety net: it was captured from main before the
code moved, and it records which object wins each click, the cycling order,
the properties rows, the status message, the selection outline and every snap
result. The tests around it pin the rules that matter most in daily use.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QGraphicsPathItem

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap
from geostudio.selection import (SelectionContext, highlight_path, pick_candidates,
                                 resolve_click, snap_at, toggle_selection,
                                 visible_uids)

from selection_snapshot import (build_selection_window, selection_map_bytes,
                                snapshot_json)

GOLDEN = Path(__file__).parent / "golden" / "selection_v014.json"


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qt_app, tmp_path):
    widget = build_selection_window(tmp_path)
    yield widget
    widget.close()


def test_selection_snapshot_matches_golden(qt_app, tmp_path):
    # The frozen v0.14 golden intentionally predates the newer B/Ctrl+L help.
    # Preserve its geometry/selection snapshot; update only this UI hint.
    expected = GOLDEN.read_text(encoding="utf-8").replace(
        "Ctrl+klik dodaje/usuwa, Ctrl+H otwiera wybór po kodzie i atrybutach.",
        "B utrwala obiekt, Ctrl+L zaznacza cały aktywny kod; F wyszukuje.")
    actual = snapshot_json(build_selection_window(tmp_path))
    if actual != expected:
        wanted = expected.splitlines()
        got = actual.splitlines()
        first = next((i for i, (a, b) in enumerate(zip(wanted, got)) if a != b),
                     min(len(wanted), len(got)))
        pytest.fail(
            "Selection behaviour differs from tests/golden/selection_v014.json "
            f"at line {first + 1}:\n  expected: {wanted[first] if first < len(wanted) else '<eof>'}"
            f"\n  actual:   {got[first] if first < len(got) else '<eof>'}")


# --- picking -------------------------------------------------------------

def test_parcel_wins_over_land_use_underneath(window):
    window.select_at(500200.0, 6500200.0)
    assert window.selected_uids == ["PARCEL"]
    assert window.doc.by_id["PARCEL"].code == "5216"


def test_repeat_click_cycles_through_overlapping_objects(window):
    window.select_at(500200.0, 6500200.0)
    assert window.selected_uids == ["PARCEL"]
    window.select_at(500200.0, 6500200.0)
    assert window.selected_uids == ["LANDUSE"]
    window.select_at(500200.0, 6500200.0)
    assert window.selected_uids == ["PARCEL"]


def test_click_away_from_the_last_spot_starts_from_the_first_candidate(window):
    window.select_at(500200.0, 6500200.0)
    window.select_at(500200.0, 6500200.0)
    assert window.selected_uids == ["LANDUSE"]
    window.select_at(500480.0, 6500480.0)          # empty space clears
    assert window.selected_uids == []
    window.select_at(500200.0, 6500200.0)
    assert window.selected_uids == ["PARCEL"]


def test_hidden_layer_is_not_pickable(window):
    window.hidden_layers = {"Działki"}
    window.rebuild_scene(fit=False)
    window.select_at(500200.0, 6500200.0)
    assert window.selected_uids == ["LANDUSE"]


def test_code_filter_restricts_candidates(window):
    window.select_code_filter = "5230"
    window.select_at(500200.0, 6500200.0)
    assert window.selected_uids == ["LANDUSE"]


def test_click_on_empty_space_clears_selection(window):
    window.select_at(500200.0, 6500200.0)
    window.select_at(500480.0, 6500480.0)
    assert window.selected_uids == []
    assert window.highlight_item is None


# --- multi selection -----------------------------------------------------

def test_ctrl_click_adds_and_removes_without_reordering(window):
    window.select_at(500200.0, 6500200.0)
    window.select_at(500300.0, 6500300.0, additive=True)
    assert window.selected_uids == ["PARCEL", "NEIGHBOUR"]
    # A different spot inside NEIGHBOUR only, so this is not a repeat click.
    window.select_at(500340.0, 6500340.0, additive=True)
    assert window.selected_uids == ["PARCEL"]


def test_ctrl_click_on_the_same_spot_cycles_to_the_next_object(window):
    """Pre-existing behaviour: Ctrl+click at one point walks the overlap."""
    window.select_at(500200.0, 6500200.0)
    window.select_at(500300.0, 6500300.0, additive=True)
    assert window.selected_uids == ["PARCEL", "NEIGHBOUR"]
    window.select_at(500300.0, 6500300.0, additive=True)
    assert window.selected_uids == ["PARCEL", "NEIGHBOUR", "LANDUSE"]


def test_select_all_same_code(window):
    window._select_uid("PARCEL")
    window.select_all_same_code()
    # HIDDEN shares code 5216 with the parcels, so it is selected too.
    assert set(window.selected_uids) == {"PARCEL", "NEIGHBOUR", "HIDDEN", "MULTI"}
    assert window.selected_uids[0] == "PARCEL"


def test_unknown_uid_is_ignored(window):
    window._set_selected_uids(["NIEZNANY"])
    assert window.selected_uids == []


# --- outline -------------------------------------------------------------

def test_outline_follows_contours_not_bounding_boxes(window):
    window._set_selected_uids(["MULTI"])
    item = window.highlight_item
    assert isinstance(item, QGraphicsPathItem)
    path = item.path()
    # MULTI is two three-vertex components: a bounding box would be one
    # subpath of four corners, the real contour is two subpaths of three.
    assert path.elementCount() == 6
    moves = sum(1 for i in range(path.elementCount())
                if path.elementAt(i).type.name == "MoveToElement")
    assert moves == 2


def test_outline_style_is_unchanged(window):
    window._set_selected_uids(["PARCEL"])
    item = window.highlight_item
    assert item.pen().color().name() == "#ffb000"
    assert item.pen().widthF() == pytest.approx(3.0)
    assert item.pen().isCosmetic() is True
    assert item.zValue() == pytest.approx(1000.0)


def test_properties_panel_still_shows_the_selected_object(window):
    window._set_selected_uids(["PARCEL"])
    rows = {window.props.topLevelItem(i).text(0): window.props.topLevelItem(i).text(1)
            for i in range(window.props.topLevelItemCount())}
    assert rows["Kod"] == "5216"
    assert rows["ID"] == "PARCEL"
    assert rows["Warstwa"] == "Działki"
    assert window.selected_count_label.text() == "Zaznaczono: 1 obiektów"


# --- tolerances ----------------------------------------------------------

def test_pixel_tolerance_converts_to_map_units(window):
    window.view.resetTransform()
    window.view.setTransform(window.view.transform())
    base = window._map_radius(8)
    window.view.scale(2.0, 2.0)
    assert window._map_radius(8) == pytest.approx(base / 2, rel=1e-6)
    window.view.scale(0.5, 0.5)
    assert window._map_radius(8) == pytest.approx(base, rel=1e-6)


def test_pixel_tolerance_is_rotation_independent(window):
    base = window._map_radius(8)
    window.view.rotate(90)
    assert window._map_radius(8) == pytest.approx(base, rel=1e-6)
    assert window._map_radius(12) == pytest.approx(base * 1.5, rel=1e-6)
    window.view.rotate(-90)
    assert window._map_radius(8) == pytest.approx(base, rel=1e-6)


def test_snap_tolerance_shrinks_when_zooming_in(window):
    # Inside PARCEL, five map units from both of its edges.
    near_edge = (500245.0, 6500245.0)
    assert window._snap(*near_edge) is not None
    window.view.scale(4.0, 4.0)                  # 12 px is now 3 map units
    assert window._snap(*near_edge) is None


# --- snapping ------------------------------------------------------------

def test_snap_prefers_vertices_and_falls_back_to_edges(window):
    vertex = window._snap(500250.0, 6500250.0)
    assert vertex is not None and vertex.kind == "vertex"
    edge = window._snap(500200.0, 6500152.0)
    assert edge is not None and edge.kind == "edge"
    assert window._snap(500480.0, 6500480.0) is None


def test_snap_honours_exclude_uid(window):
    first = window._snap(500250.0, 6500250.0)
    assert first.uid == "PARCEL"
    other = window._snap(500250.0, 6500250.0, exclude_uid="PARCEL")
    assert other is not None and other.uid != "PARCEL"


def test_snap_respects_the_toggle(window):
    window.snap_action.setChecked(False)
    assert window._snap(500250.0, 6500250.0) is None
    window.snap_action.setChecked(True)
    assert window._snap(500250.0, 6500250.0) is not None


def test_snap_ignores_hidden_layers(window):
    window.hidden_layers = {"Działki"}
    window.rebuild_scene(fit=False)
    assert window._snap(500250.0, 6500250.0) is None


# --- pure functions ------------------------------------------------------

def test_resolve_click_wraps_around():
    uids = ["A", "B", "C"]
    assert resolve_click(uids, "", cycle=True) == "A"
    assert resolve_click(uids, "A", cycle=True) == "B"
    assert resolve_click(uids, "C", cycle=True) == "A"
    assert resolve_click(uids, "C", repeat=True) == "A"
    assert resolve_click(uids, "B") == "A"


def test_toggle_selection_keeps_order():
    assert toggle_selection([], "A") == ["A"]
    assert toggle_selection(["A"], "B") == ["A", "B"]
    assert toggle_selection(["A", "B"], "A") == ["B"]
    assert toggle_selection(["A", "B"], "B") == ["A"]


def test_visible_uids_skips_hidden_and_missing():
    doc = GeoMap(selection_map_bytes())
    ctx = SelectionContext(doc=doc, geometry_index=None,
                           layer_for_uid={"PARCEL": "Działki", "HIDDEN": "Ukryte",
                                          "GHOST": "Działki"},
                           hidden_layers=frozenset({"Ukryte"}))
    assert visible_uids(ctx) == {"PARCEL"}


def test_highlight_path_uses_components():
    doc = GeoMap(selection_map_bytes())
    path = highlight_path(doc, ["MULTI"], hide_connectors=True)
    assert path.elementCount() == 6
    joined = highlight_path(doc, ["MULTI"], hide_connectors=False)
    assert joined.elementCount() == 6


def test_snap_at_without_a_document_or_radius_returns_none():
    doc = GeoMap(selection_map_bytes())
    window_ctx = SelectionContext(doc=doc, geometry_index=None, radius=0.0)
    assert snap_at(window_ctx, 0.0, 0.0) is None
    empty = SelectionContext(doc=None, geometry_index=None, radius=1.0)
    assert snap_at(empty, 0.0, 0.0) is None
