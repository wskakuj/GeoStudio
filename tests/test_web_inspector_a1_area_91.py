"""Inspektor: A1 pod kodem i powierzchnia w hektarach; stack etykiet w kliencie."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

HTML = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")
JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
CSS = Path("geostudio/web_app/static/styles.css").read_text(encoding="utf-8")
MAP = Path("/scratch/input/MOKRA_WIEŚ_GeoStudio2_kopia-2.MAP")


def test_markup_has_a1_and_hectares():
    assert 'id="inspector-summary-a1"' in HTML
    assert 'id="inspector-summary-ha"' in HTML


def test_styles_exist():
    assert ".inspector-summary-a1" in CSS
    assert ".inspector-summary-ha" in CSS


def test_client_fills_a1_and_hectares():
    assert '$("inspector-summary-a1")' in JS
    assert '(area/10000).toFixed(4)+" ha"' in JS
    assert "summaryMain.hidden=!a1&&!showHa;" in JS


def test_client_clears_the_summary_without_selection():
    assert 'if(summaryMainClear&&!detail){' in JS


def test_native_position_is_drawn_exactly_where_it_is():
    """Etykieta z rekordu L ma własną pozycję — klient nie dokłada przesunięć."""
    src = Path("geostudio/web_app/data.py").read_text(encoding="utf-8")
    assert '"manuallyPlaced":bool(location),' in src


def test_inspector_returns_area_and_a1():
    if not MAP.exists():
        pytest.skip("brak mapy testowej")
    from geostudio.web_app.data import PreviewWorkspace
    workspace = PreviewWorkspace()
    workspace.load_map(MAP.read_bytes(), "MOKRA.MAP")
    entry = next(e for e in workspace._entries
                 if e.obj.code == "5310" and e.obj.is_closed
                 and e.obj.fields.get("A1"))
    fid = workspace._object_id[id(entry.obj)]
    detail = workspace.details(fid)
    assert detail["fields"]["A1"]
    assert detail["areaM2"] and detail["areaM2"] > 0
    assert detail["closed"] is True
