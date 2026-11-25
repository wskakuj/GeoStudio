"""OGC WMTS axes, coverage and screen resolution regressions."""
from dataclasses import replace
from pathlib import Path

import pytest

from geostudio import wmts_service as wmts


def matrix(*, resolution=1.0, top_left=(850000.0, 100000.0),
           tile_width=512, tile_height=512, width=2000, height=2000):
    return wmts.TileMatrix("test", resolution / 0.00028, top_left,
                           tile_width, tile_height, width, height)


def test_real_geoportal_capabilities_corner_and_tile_location():
    xml = Path("tests/fixtures/wmts_geoportal_2180.xml").read_bytes()
    matrix_set, = wmts.parse_capabilities(xml)
    assert matrix_set.crs == "EPSG:2180"
    level = next(m for m in matrix_set.matrices if m.identifier == "EPSG:2180:10")
    assert level.top_left == (850000.0, 100000.0)
    assert wmts.top_left_east_north(level, matrix_set.crs) == (100000.0, 850000.0)
    # Coordinates of exactly tile column 100, row 200, calculated in E,N.
    span = level.resolution() * 512
    north = 850000.0 - 200 * span
    east = 100000.0 + 100 * span
    assert wmts.tile_selection(level, north - span, east,
                               north, east + span, crs=matrix_set.crs) == (
        100, 200, 100, 200, False)


@pytest.mark.parametrize("crs", ["EPSG:2180", "EPSG:2176", "EPSG:2177",
                                 "EPSG:2178", "EPSG:2179",
                                 "urn:ogc:def:crs:EPSG::2180"])
def test_polish_north_east_crs_columns_run_east_and_rows_south(crs):
    assert wmts.top_left_east_north(matrix(), crs) == (100000.0, 850000.0)
    assert wmts.tile_selection(matrix(), 500000.0, 400000.0,
                               500900.0, 401600.0, crs=crs) == (
        585, 681, 589, 683, False)


def test_east_north_crs_preserves_the_published_corner():
    level = matrix(top_left=(100000.0, 850000.0))
    assert wmts.top_left_east_north(level, "EPSG:3857") == (100000.0, 850000.0)
    assert wmts.tile_selection(level, 500000.0, 400000.0,
                               500900.0, 401600.0, crs="EPSG:3857") == (
        585, 681, 589, 683, True)


@pytest.mark.parametrize("resolution", [1.0, 2.8, 1.3229193125])
@pytest.mark.parametrize("tile_width,tile_height", [(512, 512), (256, 128)])
def test_exact_tile_boundaries_do_not_fetch_neighbours(
        resolution, tile_width, tile_height):
    level = matrix(resolution=resolution, tile_width=tile_width,
                   tile_height=tile_height)
    span_east = resolution * tile_width
    span_north = resolution * tile_height
    east = 100000.0 + 2 * span_east
    north = 850000.0 - 3 * span_north
    assert wmts.tile_range(level, north - span_north, east,
                           north, east + span_east) == (2, 3, 2, 3)


def test_partial_overlap_fetches_only_existing_intersection():
    level = matrix(top_left=(1024.0, 0.0), width=2, height=2)
    # The matrix covers E=0..1024 and N=0..1024; the view extends left/up.
    assert wmts.tile_range(level, 512.0, -256.0, 1280.0, 512.0) == (0, 0, 0, 0)
    # The view extends right/down.
    assert wmts.tile_range(level, -256.0, 512.0, 512.0, 1280.0) == (1, 1, 1, 1)


@pytest.mark.parametrize("bounds", [
    (0.0, -512.0, 512.0, 0.0),       # touches western edge
    (0.0, 1024.0, 512.0, 1536.0),   # touches eastern edge
    (1024.0, 0.0, 1536.0, 512.0),   # touches northern edge
    (-512.0, 0.0, 0.0, 512.0),      # touches southern edge
    (50000.0, 50000.0, 51000.0, 51000.0),
])
def test_outside_view_does_not_download_an_unrelated_edge_tile(bounds):
    level = matrix(top_left=(1024.0, 0.0), width=2, height=2)
    with pytest.raises(ValueError, match="poza zasięgiem"):
        wmts.tile_selection(level, *bounds)


def test_mosaic_origin_is_always_east_north():
    assert wmts.mosaic_origin(matrix(), 2, 3, False) == (
        100000.0 + 2 * 512, 850000.0 - 3 * 512)
    assert wmts.mosaic_origin(matrix(top_left=(100000.0, 850000.0)),
                              2, 3, True, crs="EPSG:3857") == (
        100000.0 + 2 * 512, 850000.0 - 3 * 512)


def test_geographic_crs_resolution_is_in_degrees():
    level = matrix(top_left=(56.0, 12.0))
    assert wmts.top_left_east_north(level, "EPSG:4326") == (12.0, 56.0)
    assert level.resolution("EPSG:4326") == pytest.approx(1 / 111319.49079327357)


def test_pick_matrix_uses_requested_screen_resolution():
    levels = tuple(replace(matrix(resolution=res), identifier=str(res))
                   for res in (0.25, 0.5, 1.0, 2.0))
    matrix_set = wmts.TileMatrixSet("EPSG:2180", "EPSG:2180", levels)
    assert wmts.pick_matrix(matrix_set, 1.0).identifier == "1.0"
    assert wmts.pick_matrix(matrix_set, 0.9).identifier == "1.0"


@pytest.mark.parametrize("resolution", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_screen_resolution_is_rejected(resolution):
    matrix_set = wmts.TileMatrixSet("EPSG:2180", "EPSG:2180", (matrix(),))
    with pytest.raises(ValueError, match="rozdzielczość"):
        wmts.pick_matrix(matrix_set, resolution)


def test_unknown_axis_order_is_reported_instead_of_guessed():
    with pytest.raises(ValueError, match="osi układu"):
        wmts.top_left_east_north(matrix(), "not-a-crs")
