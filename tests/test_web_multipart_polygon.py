"""Podział i scalanie działają też dla obrysów wieloczęściowych."""
from __future__ import annotations

from types import SimpleNamespace

from geostudio.web_app.geometry_6a import polygon_of


def _point(x, y):
    return SimpleNamespace(x=x, y=y, point_type=1)


def _object(rings):
    points = [p for ring in rings for p in ring]
    return SimpleNamespace(
        is_closed=True,
        points=points,
        display_parts=[[_point(x, y) for x, y in ring] for ring in rings],
    )


def test_polygon_of_uses_the_outer_ring_and_keeps_holes():
    outer = [(0, 0), (0, 40), (40, 40), (40, 0), (0, 0)]
    hole = [(10, 10), (10, 30), (30, 30), (30, 10), (10, 10)]
    shape = polygon_of(_object([outer, hole]))
    assert shape.area == 1600 - 400
    assert len(shape.interiors) == 1


def test_polygon_of_takes_the_largest_contour_when_separate():
    small = [(0, 0), (0, 5), (5, 5), (5, 0), (0, 0)]
    big = [(100, 100), (100, 140), (140, 140), (140, 100), (100, 100)]
    shape = polygon_of(_object([small, big]))
    assert shape.area == 1600


def test_polygon_of_still_rejects_open_object():
    import pytest
    obj = _object([[(0, 0), (0, 10), (10, 10), (0, 0)]])
    obj.is_closed = False
    with pytest.raises(ValueError):
        polygon_of(obj)
