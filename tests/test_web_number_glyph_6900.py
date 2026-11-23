"""Cyfra numeru 6900 wypełnia pudełko bez rozciągania."""
from __future__ import annotations

from pathlib import Path

SHEET = Path("geostudio/web_app/static/sheet.js").read_text(encoding="utf-8")


def test_digit_is_drawn_inside_its_box():
    # Rysowanie wprost w pudełku: rozmiar czcionki z wysokości pudełka,
    # wyśrodkowanie w obu osiach — brak rozciągania osiowego.
    assert 'const px=Math.max(4,height*.78);' in SHEET
    assert 'g.fillText(String(item.text||""),width/2,height/2);' in SHEET
    assert 'g.textBaseline="middle";' in SHEET


def test_no_axis_stretching_for_numbers():
    # Skalowanie niejednolite (width/w, height/h) nie może dotyczyć numeru.
    start = SHEET.index('if(item.kind==="compartment"){')
    end = SHEET.index('g.scale(width/w,height/h);g.lineWidth=.65;')
    block = SHEET[start:end]
    assert "g.scale(width/w,height/h)" not in block
    assert "continue;" in block


def test_rotation_still_works_for_numbers():
    assert "g.rotate(Number(item.angle)*Math.PI/180);" in SHEET
