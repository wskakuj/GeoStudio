"""WMS request dimensions and the visible completion status."""
from __future__ import annotations

from pathlib import Path

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def test_request_covers_mostly_the_visible_area():
    """Use a small border around the viewport."""
    assert "const bounds=boundsFromViewport(.15);" in JS
    assert "const bounds=boundsFromViewport(.6);" not in JS


def test_pixels_match_the_screen():
    assert "Math.round(state.width*dpr))" in JS
    assert "*1.20))" not in JS


def test_fetch_time_is_visible():
    assert "const elapsed=Math.round(performance.now()-started);" in JS
    assert '" · "+elapsed+" ms"' in JS
