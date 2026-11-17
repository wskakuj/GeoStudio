"""Deterministic description of selection and snapping behaviour.

Captured from the code as it stood before ``selection.py`` was extracted, so a
refactor that changes which object wins a click, how cycling behaves, what the
properties panel shows, or where a snap lands fails loudly instead of quietly.

Every scenario drives the public window API (``select_at``, ``_snap``,
``_set_selected_uids``) exactly as the canvas does, then records the observable
result: selection order, the highlight outline, the properties rows and the
status message.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtGui import QPainterPath

from geostudio.app import GeoStudioWindow
from geostudio.geomap import GeoMap

PRECISION = 6


def _f(value: float) -> float:
    return round(float(value), PRECISION)


def selection_map_bytes() -> bytes:
    """Map with the geometry the selection rules care about.

    - PARCEL sits *under* LANDUSE: a click inside both must pick the parcel.
    - NEIGHBOUR shares an exact vertex with PARCEL (snap target for both).
    - HIDDEN lives on its own layer so hidden-layer rules can be exercised.
    - MULTI is a multipart record (connector handling during picking).
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from conftest import MapBuilder

    builder = MapBuilder(ext=(1000.0, 500000.0, 6500000.0, 500500.0, 6500500.0))
    builder.object(code="5230", uid="LANDUSE", fields={"A2": "R"},
                   points=[(500100.0, 6500100.0), (500300.0, 6500100.0),
                           (500300.0, 6500300.0), (500100.0, 6500300.0)])
    builder.object(code="5216", uid="PARCEL", fields={"A2": "12/3"},
                   points=[(500150.0, 6500150.0), (500250.0, 6500150.0),
                           (500250.0, 6500250.0), (500150.0, 6500250.0)])
    builder.object(code="5216", uid="NEIGHBOUR", fields={"A2": "12/4"},
                   points=[(500250.0, 6500250.0), (500350.0, 6500250.0),
                           (500350.0, 6500350.0), (500250.0, 6500350.0)])
    builder.object(code="5216", uid="HIDDEN", fields={"A2": "ukryta"},
                   points=[(500400.0, 6500100.0), (500450.0, 6500100.0),
                           (500450.0, 6500150.0)])
    builder.multipart(code="5216", uid="MULTI")
    builder.raw(":ZZZ[zachowaj]")
    return builder.build()


def build_selection_window(tmp_path: Path) -> GeoStudioWindow:
    window = GeoStudioWindow()
    window.doc = GeoMap(selection_map_bytes(), filename="SELECT.MAP")
    window.catalog = {"5216": "Działki", "5230": "Użytki"}
    window.symbols = {"5216": "granica", "5230": "użytek"}
    window.rebuild_scene(fit=False)
    return window


def _highlight(window) -> dict:
    item = window.highlight_item
    if item is None:
        return {"present": False}
    path = item.path()
    moves = sum(1 for i in range(path.elementCount())
                if path.elementAt(i).type == QPainterPath.ElementType.MoveToElement)
    return {"present": True, "elements": path.elementCount(), "subpaths": moves,
            "z": _f(item.zValue()), "width": _f(item.pen().widthF()),
            "color": item.pen().color().name(),
            "cosmetic": bool(item.pen().isCosmetic())}


def _properties(window) -> list[list[str]]:
    tree = window.props
    return [[tree.topLevelItem(i).text(0), tree.topLevelItem(i).text(1)]
            for i in range(tree.topLevelItemCount())]


def _state(window) -> dict:
    return {
        "selected": list(window.selected_uids),
        "current": window.selected_uid,
        "highlight": _highlight(window),
        "properties": _properties(window),
        "countLabel": window.selected_count_label.text(),
        "status": window.status.currentMessage(),
    }


def _snap_state(result) -> dict | None:
    if result is None:
        return None
    return {"x": _f(result.x), "y": _f(result.y), "kind": result.kind,
            "uid": result.uid, "code": result.code,
            "distance": _f(result.distance)}


def _radius(window, pixels: int) -> float:
    """Map-unit length of ``pixels`` at the current view transform.

    Computed the same way the window does it, so the value is comparable
    before and after the extraction, and so rotation can be checked.
    """
    origin = window.view.mapToScene(QPoint(0, 0))
    other = window.view.mapToScene(QPoint(pixels, 0))
    return _f(math.hypot(other.x() - origin.x(), other.y() - origin.y()))


def _reset(window) -> None:
    window._last_pick_pos = None
    window._last_pick_candidates = ()
    window.select_code_filter = None
    window.hidden_layers = set()
    for name in window.layer_for_uid.values():
        window.items_by_layer.get(name, [])
    window._set_selected_uids([])


def run_scenarios(window: GeoStudioWindow) -> dict:
    """Every scenario the selection rules must keep behaving the same way."""
    out: dict[str, dict] = {}

    _reset(window)
    window.select_at(500200.0, 6500200.0)          # inside PARCEL and LANDUSE
    out["click_parcel_under_landuse"] = _state(window)

    window.select_at(500200.0, 6500200.0)          # same spot again -> cycle
    out["repeat_click_cycles"] = _state(window)

    window.select_at(500200.0, 6500200.0, cycle=True)
    out["cycle_flag"] = _state(window)

    window.select_at(500200.0, 6500200.0, additive=True)
    out["additive_toggle_off"] = _state(window)

    _reset(window)
    window.select_at(500200.0, 6500200.0)
    window.select_at(500300.0, 6500300.0, additive=True)   # NEIGHBOUR corner
    out["additive_two_objects"] = _state(window)

    _reset(window)
    window.select_at(500480.0, 6500480.0)          # empty space
    out["click_empty_space"] = _state(window)

    _reset(window)
    window.select_code_filter = "5230"
    window.select_at(500200.0, 6500200.0)
    out["code_filter"] = _state(window)
    window.select_code_filter = None

    _reset(window)
    window.hidden_layers = {"Działki"}
    window.rebuild_scene(fit=False)
    window.select_at(500200.0, 6500200.0)
    out["hidden_layer_skipped"] = _state(window)
    window.hidden_layers = set()
    window.rebuild_scene(fit=False)

    _reset(window)
    window._select_uid("PARCEL")
    window.select_all_same_code()
    out["select_all_same_code"] = _state(window)

    _reset(window)
    window._set_selected_uids(["PARCEL", "NEIGHBOUR", "MULTI"])
    out["multi_selection_outline"] = _state(window)

    _reset(window)
    window._set_selected_uids(["NIEZNANY"])
    out["unknown_uid_ignored"] = _state(window)

    # --- snapping -------------------------------------------------------
    _reset(window)
    window.snap_action.setChecked(True)
    out["snap_shared_vertex"] = _snap_state(window._snap(500250.0, 6500250.0))
    out["snap_edge"] = _snap_state(window._snap(500200.0, 6500152.0))
    out["snap_far_away"] = _snap_state(window._snap(500480.0, 6500480.0))
    out["snap_excluding_parcel"] = _snap_state(
        window._snap(500250.0, 6500250.0, exclude_uid="PARCEL"))
    window.snap_action.setChecked(False)
    out["snap_disabled"] = _snap_state(window._snap(500250.0, 6500250.0))
    window.snap_action.setChecked(True)

    window.hidden_layers = {"Działki"}
    window.rebuild_scene(fit=False)
    out["snap_hidden_layer"] = _snap_state(window._snap(500250.0, 6500250.0))
    window.hidden_layers = set()
    window.rebuild_scene(fit=False)

    # --- tolerances -----------------------------------------------------
    out["radius_pixels"] = {"pick_8": _radius(window, 8), "snap_12": _radius(window, 12)}
    window.view.scale(2.0, 2.0)
    out["radius_after_zoom_in"] = {"pick_8": _radius(window, 8), "snap_12": _radius(window, 12)}
    window.view.rotate(90)
    out["radius_after_rotation"] = {"pick_8": _radius(window, 8), "snap_12": _radius(window, 12)}
    out["snap_after_rotation"] = _snap_state(window._snap(500250.0, 6500250.0))
    window.view.rotate(-90)
    window.view.scale(0.5, 0.5)

    _reset(window)
    return out


def snapshot_json(window: GeoStudioWindow) -> str:
    return json.dumps(run_scenarios(window), indent=1, sort_keys=True, ensure_ascii=False)
