"""Obrót oznaczeń: zrąb, bagno, linia energetyczna, gazociąg."""
from __future__ import annotations

import math

import pytest

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.sheet_marks import ROTATABLE, primitives


def _map() -> bytes:
    return (MapBuilder(ext=(5000, 0, 0, 150, 150))
            .object("5216", "DZ-1", {"A1": "1", "A2": "1/1"},
                    [(0, 0), (0, 10), (10, 10), (10, 0)])
            .build())


def _item(kind="clearcut", **extra):
    base = {"kind": kind, "x": 0.0, "y": 0.0, "w": 40.0, "h": 20.0, "text": ""}
    base.update(extra)
    return base


def test_rotatable_set_matches_the_four_signs():
    assert ROTATABLE == {"clearcut", "marsh", "power", "gas"}


def test_rotation_moves_geometry_around_the_centre():
    plain = primitives(_item())
    turned = primitives(_item(angle=90))
    assert plain[0][1] != turned[0][1]
    # Środek obrotu (x+w/2, -y-h/2) musi zostać na miejscu: sprawdzamy, że
    # odległości od środka są zachowane.
    cx, cy = 20.0, -10.0
    def dists(parts):
        return [round(math.hypot(x - cx, y - cy), 3) for _, pts, *_ in parts for y, x in pts]
    assert dists(plain) == dists(turned)


def test_rotation_is_ignored_for_signs_without_direction():
    plain = primitives(_item("conifer"))
    turned = primitives(_item("conifer", angle=90))
    assert plain == turned


def test_workspace_accepts_angle_and_stores_it():
    ws = PreviewWorkspace()
    ws.load_map(_map(), "m.MAP")
    status = ws.editing_status()
    item = {"id": "s1", "kind": "clearcut", "x": 10.0, "y": -10.0, "w": 20.0,
            "h": 10.0, "text": "Zrąb", "angle": 45}
    ws.set_sheet_items([item], document_token=status["documentToken"],
                       revision=status["revision"])
    stored = ws.metadata()["sheetItems"]
    assert any(i["id"] == "s1" and i.get("angle") == 45 for i in stored)


@pytest.mark.parametrize("kind,angle", [
    ("conifer", 45), ("title", 10), ("clearcut", 400), ("marsh", None),
])
def test_workspace_rejects_bad_angle(kind, angle):
    ws = PreviewWorkspace()
    ws.load_map(_map(), "m.MAP")
    status = ws.editing_status()
    item = {"id": "s1", "kind": kind, "x": 10.0, "y": -10.0, "w": 20.0,
            "h": 10.0, "text": "x", "angle": angle}
    with pytest.raises(ValueError):
        ws.set_sheet_items([item], document_token=status["documentToken"],
                           revision=status["revision"])
