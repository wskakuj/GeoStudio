"""Ekran startowy, nagłówek, Inspektor, Łącznik 4100."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from geostudio.web_app.data import PreviewWorkspace  # noqa: E402

HTML = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")
JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
CSS = Path("geostudio/web_app/static/styles.css").read_text(encoding="utf-8")
MAP = Path("/scratch/input/MOKRA_WIEŚ.MAP")


def test_splash_texts_and_icon():
    assert "NOWA GENERACJA EDYTORA" not in HTML
    assert ">GeoStudio 2.0</div>" in HTML
    assert "Pliki GEO-MAP." in HTML
    assert "Nowy standard pracy." in HTML
    assert 'src="/geostudio-icon.png"' in HTML
    assert "object-fit:contain" in CSS


def test_undo_redo_moved_to_header():
    start = HTML.index('class="header-action-group header-history"')
    block = HTML[start:start + 3000]
    assert 'id="tool-undo"' in block and 'id="tool-redo"' in block
    # W zakładce Start nie ma już sekcji HISTORIA
    assert '<span class="section-label">HISTORIA</span>' not in HTML


def test_block_buttons_renamed():
    assert ">W prostokącie</button>" in HTML
    assert ">Odznacz</button>" in HTML
    assert ">W fragmencie</button>" not in HTML
    assert ">Wyczyść</button>" not in HTML


def test_enter_finishes_line_and_link():
    assert '["draw","cut","line","line-edit","link"].includes(state.tool)&&ev.key==="Enter"' in JS


def test_inspector_can_change_line_style():
    assert 'id="inspector-line-style"' in HTML
    assert "Rodzaj linii" in HTML
    assert "async function setInspectorLineStyle()" in JS
    assert '"/api/objects/dash"' in JS


def test_link_tool_exists_in_both_toolbars():
    assert 'id="tool-link"' in HTML and 'id="float-link"' in HTML
    assert ">Łącznik</button>" in HTML
    assert 'link("tool-link",()=>setTool("link"));' in JS
    assert 'link("float-link",()=>setTool("link"));' in JS
    assert '["link","tool-link"]' in JS and '["link","float-link"]' in JS


def test_connector_glyph_is_built_from_two_points():
    assert "function connectorPoints(start, end){" in JS
    assert "async function finishConnector(){" in JS
    assert 'code:"4100"' in JS


def test_connector_object_can_be_created():
    if not MAP.exists():
        pytest.skip("brak mapy testowej")
    workspace = PreviewWorkspace()
    workspace.load_map(MAP.read_bytes(), "M.MAP")
    before = len([o for o in workspace._doc.objects if o.code == "4100"])
    points = [[512880.0, 669740.0], [512880.0, 669748.0],
              [512892.0, 669740.0], [512892.0, 669748.0]]
    status = workspace.editing_status()
    operation = {"action": "create_line", "code": "4100", "points": points,
                 "fields": {}}
    preview = workspace.preview_geometry_operation(
        operation, document_token=status["documentToken"],
        revision=status["revision"])
    status = workspace.editing_status()
    workspace.apply_geometry_operation(
        operation, preview_key=preview["previewKey"],
        document_token=status["documentToken"], revision=status["revision"])
    after = len([o for o in workspace._doc.objects if o.code == "4100"])
    assert after == before + 1


def test_details_expose_line_style():
    if not MAP.exists():
        pytest.skip("brak mapy testowej")
    workspace = PreviewWorkspace()
    workspace.load_map(MAP.read_bytes(), "M.MAP")
    obj = next(o for o in workspace._doc.objects if o.code == "4100")
    detail = workspace.details(workspace._object_id[id(obj)])
    assert detail["closed"] is False
    assert "dash" in detail["style"]


def test_icon_is_packaged_for_the_installer():
    """Bez tego PyInstaller nie zabiera PNG i ikona nie wczytuje się w exe."""
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    assert '"static/*.png"' in pyproject


def test_link_tool_has_its_own_status_hint():
    assert 'else if(tool==="link")' in JS
    assert "Łącznik 4100: kliknij punkt początkowy" in JS
    # Nie może wpadać w podpowiedź trybu przesuwania mapy.
    start = JS.index('else if(tool==="link")')
    block = JS[start:start + 400]
    assert "Tryb przesuwania mapy" not in block


def test_icon_file_exists():
    assert Path("geostudio/web_app/static/geostudio-icon.png").is_file()


def test_brand_uses_the_program_icon_and_display_type():
    # W nagłówku jest ikona programu, nie trzy kreski.
    assert '<img class="mark" src="/geostudio-icon.png"' in HTML
    assert '<div class="mark" aria-hidden="true"><span></span>' not in HTML
    # Profesjonalna typografia marki i podpisu na ekranie startowym.
    assert "Bahnschrift" in CSS
    assert ".wordmark .brand-number" in CSS
    assert "letter-spacing:.34em" in CSS


def test_brand_lockup_is_crisp_and_typographic():
    # Ikona w dwóch gęstościach — ostra także na ekranach HiDPI.
    assert 'srcset="/geostudio-icon.png 1x, /geostudio-icon@2x.png 2x"' in HTML
    assert Path("geostudio/web_app/static/geostudio-icon@2x.png").is_file()
    # Nazwa i wersja to jeden lockup, nie dwa sklejone napisy.
    assert '<strong class="wordmark">GeoStudio<span class="brand-number">2.0</span></strong>' in HTML
    assert ".wordmark .brand-number" in CSS
    assert '"/geostudio-icon@2x.png"' in Path("geostudio/web_app/server.py").read_text(encoding="utf-8")


def test_clicking_the_map_draws_a_connector():
    """Bez tego klik w trybie Łącznik zaznaczał obiekty zamiast rysować."""
    assert ('if(["draw","cut","line","line-edit","link"].includes(state.tool)&&\n'
            '       ev.button===0&&!state.editBusy&&state.meta){\n'
            '      appendDrawingPoint(ev,p);') in JS


def test_second_click_creates_the_connector():
    assert 'if(state.tool==="link"&&state.drawPoints.length>=2){' in JS
    start = JS.index('if(state.tool==="link"&&state.drawPoints.length>=2){')
    assert "finishGeometryDrawing();" in JS[start:start + 120]


def test_escape_cancels_the_connector():
    """Esc w trybie Łącznik musi anulować akcję, a nie tylko ostatni punkt."""
    # Właściwy handler Escape (nie dispatch w finishGeometryDrawing).
    start = JS.index('Wkreślanie łącznika anulowane.') - 300
    block = JS[start:start + 520]
    assert "Wkreślanie łącznika anulowane." in block
    assert 'setTool("select");' in block
    assert "state.drawPoints=[];" in block
    # Musi być przed gałęzią rysowania poligonu, żeby nie „cofać punktu”.
    polygon_branch = JS.index('if(["draw","cut","line","line-edit"].includes(state.tool)){\n        ev.preventDefault();\n        if(state.drawPoints.length){')
    assert start < polygon_branch
