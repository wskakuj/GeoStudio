"""Zachowanie jak w GEO-MAP: mały kadr, JPEG, bez zbędnych faz."""
from __future__ import annotations

from pathlib import Path

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def test_request_covers_mostly_the_visible_area():
    """GEO-MAP prosi o widoczny prostokąt z małym zapasem — serwer renderuje mniej."""
    assert "const bounds=boundsFromViewport(.15);" in JS
    assert "const bounds=boundsFromViewport(.6);" not in JS


def test_pixels_match_the_screen():
    assert "Math.round(state.width*dpr))" in JS
    assert "*1.20))" not in JS


def test_prefetch_steps_by_most_of_a_screen():
    assert "const stepX=lastPanVector.x*spanX*.85" in JS


def test_fetch_time_is_visible():
    assert "const elapsed=Math.round(performance.now()-started);" in JS
    assert '" · "+elapsed+" ms"' in JS
