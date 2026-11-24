"""Przybliżenie mapy musi pobierać ostrzejszy obraz (jak w GEO-MAP)."""
from __future__ import annotations

from pathlib import Path

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def test_density_is_tracked_per_image():
    assert "function underlayDensity(bounds,size){" in JS
    assert "item.density=underlayDensity(bounds,size);" in JS


def test_zoom_in_refetches_for_sharper_pixels():
    start = JS.index("function underlayCovers(item,bounds,size){")
    block = JS[start:start + 900]
    assert "const wanted=underlayDensity(bounds,size);" in block
    assert "const have=item.density||0;" in block
    assert "if(wanted>have*1.02)return false;" in block


def test_cover_check_receives_the_requested_size():
    assert 'if(item.kind!=="raster"&&underlayCovers(item,bounds,size)){' in JS
