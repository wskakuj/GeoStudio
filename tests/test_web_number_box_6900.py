"""Pudełko numeru 6900 przylega do cyfry, nie do całego pola arkusza."""
from __future__ import annotations

from pathlib import Path

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
SHEET = Path("geostudio/web_app/static/sheet.js").read_text(encoding="utf-8")


def test_box_is_computed_from_text_and_size():
    assert "function compartmentBox(text, fontSize){" in JS
    assert "const unitsW=Math.max(size*0.75,chars*size*0.62);" in JS
    assert "const unitsH=size*1.3;" in JS


def test_all_three_paths_use_the_tight_box():
    # utworzenie, edycja dwuklikiem i podgląd pod kursorem
    assert JS.count("compartmentBox(") >= 4
    assert "GeoStudioSheet.sizes.compartment[1]*factor*sheetWorldPerPixel()" not in JS


def test_digit_fills_its_box():
    # Rozmiar cyfry zależy od pudełka, a nie stała 12 w polu 54x32.
    assert "const size=Math.max(4,Math.min(w*1.4,h*.82));" in SHEET
    assert 'label(w/2,h*.74,item.text,12,true)' not in SHEET
