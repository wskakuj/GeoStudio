"""Mocniejszy magnes w auto-wkreślaniu + scalanie wydzieleń po A1."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from geostudio.web_app.data import PreviewWorkspace  # noqa: E402

TRACE = Path("geostudio/web_app/static/raster_trace.js").read_text(encoding="utf-8")
MAP_JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
MAP = Path("/scratch/input/02_BYSŁAWEK.MAP")


def _workspace():
    if not MAP.exists():
        pytest.skip("brak mapy testowej")
    workspace = PreviewWorkspace()
    workspace.load_map(MAP.read_bytes(), "02.MAP")
    return workspace


def _create(workspace, points, a1, merge=True):
    status = workspace.editing_status()
    operation = {"action": "create", "code": "5310", "points": points,
                 "fields": {"A1": a1}, "clipRasterOverlap": False,
                 "mergeSameA1": merge}
    preview = workspace.preview_object_operation(
        operation, document_token=status["documentToken"],
        revision=status["revision"])
    status = workspace.editing_status()
    return workspace.apply_object_operation(
        operation, preview_key=preview["previewKey"],
        document_token=status["documentToken"], revision=status["revision"])


def test_trace_snapping_is_stronger():
    assert "vertexPixels:18,edgePixels:8" in TRACE
    assert "nearestVertex(p,14)" in TRACE


def test_merge_option_is_offered():
    assert 'class="trace-merge-a1"' in TRACE
    assert "mergeSameA1:!!mergeA1?.checked" in TRACE
    assert "mergeSameA1:options?.mergeSameA1===true" in MAP_JS


def test_distant_polygons_with_same_a1_are_merged():
    workspace = _workspace()
    first = [[626100.0, 430900.0], [626120.0, 430900.0],
             [626120.0, 430920.0], [626100.0, 430920.0]]
    second = [[626300.0, 431300.0], [626320.0, 431300.0],
              [626320.0, 431320.0], [626300.0, 431320.0]]
    assert _create(workspace, first, "77z")["mergedSameA1"] == 0
    result = _create(workspace, second, "77z")
    assert result["mergedSameA1"] == 1
    features = workspace.viewport((0, -1e6, 1e6, 1e6), limit=3000)["features"]
    merged = [f for f in features
              if any(l.get("text") == "77z" for l in f["labels"])]
    # Jeden obiekt, dwa odległe obrysy (części) w środku.
    assert len(merged) == 1
    assert len(merged[0]["geometry"]) == 2


def test_merge_does_not_touch_other_a1():
    workspace = _workspace()
    first = [[626100.0, 430900.0], [626120.0, 430900.0],
             [626120.0, 430920.0], [626100.0, 430920.0]]
    second = [[626300.0, 431300.0], [626320.0, 431300.0],
              [626320.0, 431320.0], [626300.0, 431320.0]]
    _create(workspace, first, "55a")
    assert _create(workspace, second, "55b")["mergedSameA1"] == 0
