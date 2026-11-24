"""Wydajność podkładów: lekki JPEG, cache kafelków, kwantyzacja BBOX, osie WMTS."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from geostudio import wmts_service
from geostudio.web_app import underlay_wms

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def test_jpeg_without_transparency_is_first():
    assert underlay_wms.ORTO_ATTEMPTS[0] == ("1.1.1", "image/jpeg", False)


def test_tiles_are_only_for_huge_frames():
    assert underlay_wms.ORTO_TILE_LIMIT >= 2_000_000


def test_single_request_per_frame():
    # Bez drugiej fazy „ostrej” i z debounce 380 ms.
    assert "scheduleUnderlaySharp" not in JS
    assert "setTimeout(refreshUnderlay,immediate?0:380)" in JS
    assert "const maxPixels=sharp?1200000:1200000;" in JS


def test_frames_inside_the_cached_image_are_skipped():
    assert "function underlayCovers(item,bounds){" in JS
    assert 'if(item.kind!=="raster"&&underlayCovers(item,bounds))return;' in JS


def test_cache_key_snaps_the_bbox():
    a = underlay_wms._cache_key("standard", "ortho", 2180,
                                1000.0, 2000.0, 3000.0, 4000.0, 1024, 1024)
    # Przesunięcie o 0,3 m to mniej niż piksel obrazu — ten sam wpis cache.
    b = underlay_wms._cache_key("standard", "ortho", 2180,
                                1000.3, 2000.3, 3000.3, 4000.3, 1024, 1024)
    assert a == b


def test_cache_key_still_separates_different_frames():
    a = underlay_wms._cache_key("standard", "ortho", 2180,
                                1000.0, 2000.0, 3000.0, 4000.0, 1024, 1024)
    b = underlay_wms._cache_key("standard", "ortho", 2180,
                                1500.0, 2000.0, 3500.0, 4000.0, 1024, 1024)
    assert a != b


def test_tile_cache_round_trip():
    underlay_wms._tile_cache_clear()
    key = ("standard_wmts", "Raster", "EPSG:2180", "EPSG:2180:0", 1, 2)
    assert underlay_wms._tile_cache_get(key) is None
    underlay_wms._tile_cache_put(key, b"tile")
    assert underlay_wms._tile_cache_get(key) == b"tile"
    underlay_wms.clear_cache()
    assert underlay_wms._tile_cache_get(key) is None


def _matrix(top_left, width=40, height=40):
    return wmts_service.TileMatrix(identifier="m", scale_denominator=10000,
                                   top_left=top_left, tile_width=256,
                                   tile_height=256, matrix_width=width,
                                   matrix_height=height)


def test_top_left_corner_as_minimum_is_supported():
    """TopLeftCorner = (północ_min, wschód_min): wiersze rosną na północ."""
    matrix = _matrix((0.0, 1000000.0))
    box = wmts_service._range_for_mirror(matrix, 0.0, 1000000.0,
                                         3000.0, 1009000.0, swapped=False)
    col0, row0, col1, row1 = box
    assert col0 >= 0 and row0 >= 0 and col1 >= col0 and row1 >= row0


def test_tile_selection_never_clips_to_zero_zero():
    """Kadr poza „normalną” konwencją musi trafić w sensowny kafelek."""
    matrix = _matrix((0.0, 1000000.0))
    col0, row0, col1, row1, swapped = wmts_service.tile_selection(
        matrix, 0.0, 1000000.0, 3000.0, 1009000.0)
    assert (col0, row0) != (0, 0) or (col1, row1) != (0, 0)
    assert 0 <= col0 <= col1 < matrix.matrix_width
    assert 0 <= row0 <= row1 < matrix.matrix_height
