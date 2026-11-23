"""Auto-wkreślanie nie proponuje obrysu na już wkreślonym poligonie."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

JS = Path("geostudio/web_app/static/raster_trace.js").read_text(encoding="utf-8")
MAP_JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
MAP = Path("/scratch/input/02_BYSŁAWEK.MAP")


def test_mask_covers_every_closed_5310():
    # Maska nie może zależeć tylko od nazwy warstwy — inaczej poligony
    # z innej warstwy nie są wycinane z rozpoznawania.
    assert 'if(feature.code!=="5310"&&feature.layer!=="Użytki Leśne")continue;' in JS
    assert 'if(feature.layer!=="Użytki Leśne"||!feature.closed)continue;' not in JS


def test_mask_is_rebuilt_after_saving():
    assert JS.count("await prepare();") >= 1
    start = JS.index("completed.push(points);")
    block = JS[start:start + 700]
    assert "await view.refresh();" in block
    assert "await prepare();" in block


def test_server_still_blocks_polygon_on_polygon():
    """Nawet gdy podgląd zawiedzie, serwer odrzuca nakładający się poligon."""
    source = Path("geostudio/web_app/data.py").read_text(encoding="utf-8")
    assert "Nowy poligon nakłada się na istniejący poligon tego samego kodu." in source
    assert "clipRasterOverlap" in source


def test_trace_uses_viewport_features_with_codes():
    assert "features=await view.featuresIn(bounds);" in JS
    assert "async featuresIn(bounds){" in MAP_JS
