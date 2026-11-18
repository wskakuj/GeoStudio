"""Numerical regressions for raster calibration and georeferencing."""
from __future__ import annotations

from math import isclose
from pathlib import Path

import pytest

from geostudio.raster_georef import (
    GroundControlPoint as GCP, find_world_file, fit_affine, parse_world_file,
)


def _true(u, v):
    return 12.0 + 1.25 * u - 0.4 * v + 5_150_000, -23.0 + 0.2 * u - 0.8 * v + 6_670_000


def test_seven_raster_points_fit_in_projected_coordinates():
    pixels = [(10, 10), (100, 10), (10, 95), (100, 95),
              (55, 15), (12, 50), (77, 80)]
    points = [GCP(u, v, *_true(u, v)) for u, v in pixels]
    result = fit_affine(points)
    assert result.rmse < 1e-5
    assert max(result.residuals) < 1e-5
    for p in points:
        x, y = result.world_at(p.u, p.v)
        assert isclose(x, p.x, abs_tol=1e-5)
        assert isclose(y, p.y, abs_tol=1e-5)


def test_calibration_reports_bad_control_point_error():
    samples = [(0, 0), (100, 0), (100, 100), (0, 100), (50, 50)]
    pairs = [GCP(u, v, *_true(u, v)) for u, v in samples]
    corrupted = list(pairs)
    p = corrupted[-1]
    corrupted[-1] = GCP(p.u, p.v, p.x + 15, p.y)
    fit = fit_affine(corrupted)
    assert fit.rmse > 1
    assert len(fit.residuals) == len(pairs)


@pytest.mark.parametrize("pairs", [
    [],
    [GCP(1, 1, 2, 2), GCP(2, 2, 4, 4)],
    [GCP(0, 0, 0, 0), GCP(1, 1, 1, 1), GCP(2, 2, 2, 2)],
    [GCP(0, 0, 0, 0), GCP(1, 0, 1, 0), GCP(2, 0, 2, 0)],
    [GCP(0, 0, 0, 0), GCP(1, 1, 0, 0), GCP(1, 1, 0, 0)],
])
def test_rejects_too_few_or_collinear_points(pairs):
    with pytest.raises(ValueError):
        fit_affine(pairs)


def test_world_file_pixel_centres_are_converted_to_item_corners(tmp_path):
    p = tmp_path / "scan.tfw"
    # Standard ESRI: pixel centre at (C,F); raster item origin is corner.
    p.write_text("2\n0\n0\n-2\n500\n800\n", encoding="utf-8")
    assert parse_world_file(p) == (2., 0., 499., 0., -2., 801.)


def test_world_file_lookup(tmp_path):
    img = tmp_path / "sample.JPG"
    img.write_bytes(b"")
    assert find_world_file(img) is None
    wf = tmp_path / "sample.JGW"
    wf.write_text("1\n0\n0\n-1\n0\n0\n")
    assert find_world_file(img) == wf
