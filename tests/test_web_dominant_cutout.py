"""Przesunięty poligon dominuje: sąsiad tego samego kodu dostaje wycięcie."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from conftest import MapBuilder  # noqa: E402
from geostudio.web_app.data import PreviewWorkspace  # noqa: E402


def _two_overlapping_squares() -> PreviewWorkspace:
    source = (MapBuilder(ext=(5000, 0, 0, 200, 200))
              .object("5310", "B1", {"A1": "1"},
                      [(0, 0), (0, 40), (40, 40), (40, 0)])
              .object("5310", "B2", {"A1": "2"},
                      [(100, 100), (100, 140), (140, 140), (140, 100)])
              .build())
    workspace = PreviewWorkspace()
    workspace.load_map(source, "t.MAP")
    return workspace


def _move_second_onto_first(workspace: PreviewWorkspace) -> None:
    features = [f for f in workspace.viewport((0, -200, 200, 0), limit=100)["features"]
                if f["code"] == "5310"]
    status = workspace.editing_status()
    report = workspace.preview_move_polygons(
        [features[1]["id"]], -100, -100, allow_detach=True,
        document_token=status["documentToken"], revision=status["revision"])
    workspace.apply_move_polygons(
        [features[1]["id"]], -100, -100, allow_detach=True,
        preview_key=report["previewKey"],
        document_token=status["documentToken"], revision=status["revision"])


def test_moved_polygon_wins_and_neighbour_is_cut_out():
    workspace = _two_overlapping_squares()
    _move_second_onto_first(workspace)
    features = [f for f in workspace.viewport((0, -200, 200, 0), limit=100)["features"]
                if f["code"] == "5310"]
    stationary = features[0]
    moved = features[1]
    # Przesunięty zachowuje pełne pole, sąsiad pod nim jest wycięty.
    assert moved["visibleAreaM2"] == moved["baseAreaM2"]
    assert stationary["visibleAreaM2"] == 0
    assert stationary["reversibleCutout"] is True


def test_cutout_survives_duplicated_uids():
    """Mapy po wielu zapisach mają powtórzone uid-y — wycięcie musi działać."""
    workspace = _two_overlapping_squares()
    _move_second_onto_first(workspace)
    for uid in list(workspace._uid_counts):
        workspace._uid_counts[uid] = 2
    features = [f for f in workspace.viewport((0, -200, 200, 0), limit=100)["features"]
                if f["code"] == "5310"]
    assert features[0]["reversibleCutout"] is True
    assert features[0]["visibleAreaM2"] == 0
