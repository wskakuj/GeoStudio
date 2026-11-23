"""Róża kierunków: dwubarwne groty bez rozwarstwionych końców."""
from __future__ import annotations

from pathlib import Path

JS = Path("geostudio/web_app/static/sheet.js").read_text(encoding="utf-8")


def test_both_halves_are_filled():
    # Biała połowa musi być wypełniona, inaczej przy ostrym grocie linie
    # dublują się i końcówka wygląda na rozwarstwioną.
    assert 'path([[0,0],[0,-34],[-6,-6],[0,0]].map(p=>rotate(...p)),"#ffffff",ink);' in JS
    assert "path([[0,0],[0,-34],[-6,-6],[0,0]].map(p=>rotate(...p)));" not in JS


def test_rose_has_four_black_and_four_white_halves():
    assert JS.count("const rotate=(x,y)=>[[53+x,53+y]") == 1
    assert 'for(let i=0;i<4;i++){' in JS


def test_compass_labels_sit_beyond_the_tips():
    assert 'const [x,y]=rotate(0,-44);' in JS
