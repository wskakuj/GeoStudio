"""Przesuwanie poligonów 5310: sąsiad dopasowuje granice (odwracalne wycięcie)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from geostudio.web_app.data import PreviewWorkspace  # noqa: E402
from geostudio.web_app.topology_safety import ring_of  # noqa: E402

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
MAP = Path("/scratch/input/02_BYSŁAWEK.MAP")


def _workspace():
    if not MAP.exists():
        pytest.skip("brak mapy testowej")
    workspace = PreviewWorkspace()
    workspace.load_map(MAP.read_bytes(), "02.MAP")
    return workspace


def _overlapping_pair(workspace):
    features = workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    objects = [f for f in features if f["code"] == "5310"]
    first = workspace._lookup[objects[0]["id"]].obj
    second = workspace._lookup[objects[1]["id"]].obj
    ring_a, ring_b = ring_of(first), ring_of(second)
    return (objects[0]["id"], ring_b[0][0] - ring_a[0][0],
            ring_b[0][1] - ring_a[0][1], objects[1]["id"])


def test_overlap_is_detected_and_reversible():
    workspace = _workspace()
    fid, dx, dy, _ = _overlapping_pair(workspace)
    status = workspace.editing_status()
    report = workspace.preview_move_polygons(
        [fid], dx, dy, document_token=status["documentToken"],
        revision=status["revision"], allow_detach=True, snap_distance=0)
    assert report["canApply"] is True
    assert report["overlapConflicts"]
    assert report["reversibleCutout"] is True


def test_stationary_polygon_gets_its_border_adjusted():
    workspace = _workspace()
    fid, dx, dy, other_id = _overlapping_pair(workspace)
    before = workspace._lookup[other_id].obj.area_m2
    status = workspace.editing_status()
    report = workspace.preview_move_polygons(
        [fid], dx, dy, document_token=status["documentToken"],
        revision=status["revision"], allow_detach=True, snap_distance=0)
    status = workspace.editing_status()
    result = workspace.apply_move_polygons(
        [fid], dx, dy, allow_detach=True, preview_key=report["previewKey"],
        document_token=status["documentToken"], revision=status["revision"],
        snap_distance=0)
    assert result["changed"] is True
    assert result["hasReversibleMasks"] is True
    # Źródłowe punkty zostają (wycięcie jest odwracalne), ale NA EKRANIE
    # sąsiad jest rysowany z wycięciem — mniejsza widoczna powierzchnia.
    features = workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    neighbour = next(f for f in features if f["id"] == other_id)
    assert neighbour["visibleAreaM2"] < neighbour["baseAreaM2"]


def test_screen_refreshes_geometry_after_a_move():
    """Bez pełnego odświeżenia ekran pokazywał stare obrysy z cache."""
    start = JS.index("async function commitDraggedMove(ids,ghost) {")
    block = JS[start:start + 2500]
    assert "await refreshLabelsNow();" in block
    assert "refreshEditedDocument(state.active)" not in block
