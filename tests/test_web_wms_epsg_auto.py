"""WMS: układ MAP proponowany automatycznie z zasięgu mapy."""
from __future__ import annotations

from pathlib import Path

JS = Path("geostudio/web_app/static/map.js")


def test_map_epsg_falls_back_to_bounds_guess():
    source = JS.read_text(encoding="utf-8")
    assert "const guess=chosen||probablePolishCRS(state.meta?.bounds);" in source
    # Propozycja musi trafić do wszystkich trzech selektorów układu.
    assert 'for(const id of ["underlay-epsg","raster-epsg","crs-epsg"])' in source
    assert "$(id).value=guess;" in source


def test_probable_crs_marks_the_value_as_suggestion():
    source = JS.read_text(encoding="utf-8")
    assert "prawdopodobny — potwierdź w razie potrzeby" in source


def test_probable_crs_covers_both_polish_systems():
    source = JS.read_text(encoding="utf-8")
    # 1992 (strefy 5-8) oraz 2180.
    assert "return String(2171+zone);" in source
    assert 'return "2180";' in source
