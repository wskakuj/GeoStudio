"""Blok CSS użytkownika: jednorzędowy nagłówek, wstążka, nakładki mapy."""
from __future__ import annotations

from pathlib import Path

CSS = Path("geostudio/web_app/static/styles.css").read_text(encoding="utf-8")


def test_appended_block_is_present_and_balanced():
    assert "Układ jednorzędowy nagłówka, kompaktowa wstążka" in CSS
    assert CSS.count("{") == CSS.count("}")
    assert CSS.count("/*") == CSS.count("*/")


def test_header_is_one_row_in_both_modes():
    assert 'body[data-document-editor="true"][data-theme] .topbar {' in CSS
    block = CSS[CSS.index('body[data-theme] .topbar,\nbody[data-document-editor'):
                CSS.index('body[data-theme] .topbar,\nbody[data-document-editor') + 400]
    assert "flex-wrap: nowrap" in block
    assert "min-height: 46px" in block


def test_history_labels_return_on_wide_screens():
    assert "body[data-theme] .topbar .header-history .history-label {\n  display: inline;" in CSS
    # ...i znikają dopiero poniżej 1240 px
    narrow = CSS[CSS.index("@media (max-width: 1240px)"):]
    assert ".header-history .history-label {\n    display: none;" in narrow[:400]


def test_ribbon_collapse_is_on_the_right_in_one_row():
    # Nasz blok jest na końcu pliku — bierzemy OSTATNIE wystąpienie selektora.
    start = CSS.rindex('body[data-theme] #main-ribbon.toolbar {')
    block = CSS[start:start + 1600]
    assert "display: grid" in block
    assert "grid-template-columns: minmax(0, 1fr) auto" in block
    assert "justify-self: end" in block


def test_map_overlays_are_offset_from_the_tool_rail():
    assert "body[data-theme] .map-scale-box {\n  left: 68px;" in CSS
    assert "body[data-theme] .map-bottom-left {\n  left: 68px;" in CSS


def test_floating_tool_rail_styles():
    """Pasek przyborów ma osobne kolory dla jasnego i ciemnego motywu."""
    assert 'body[data-theme="light"] .floating-tools {' in CSS
    assert 'body[data-theme="dark"] .floating-tools {' in CSS
    assert 'body[data-theme="light"] .floating.active {' in CSS
    assert 'body[data-theme="dark"] .floating.active {' in CSS
    # Ramki skali i współrzędnych nie mogą wchodzić pod pasek narzędzi.
    assert "body[data-theme] .map-scale-box,\nbody[data-theme] .map-bottom-left {\n  z-index: 2;" in CSS


def test_splash_grid_and_layers_placeholder():
    """Siatka kartograficzna na starcie i sylwetka kontynentów w panelu warstw."""
    assert ".canvas-shell:has(#empty-state:not([hidden]))::before" in CSS
    assert "body.dark-map .canvas-shell:has(#empty-state:not([hidden]))::before" in CSS
    assert ".placeholder-world-map" in CSS
    html = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")
    assert 'class="placeholder-world-map"' in html
    # Narzędzia mapy muszą być NAD siatką, karta powitalna też.
    assert "body[data-theme] .empty-state {\n  z-index: 2;" in CSS
    assert "body[data-theme] .floating-tools," in CSS


def test_html_markup_is_balanced():
    """Panel Wektory musi być zamknięty przed panelami Rastry i Podkłady."""
    html = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")
    assert html.count("<div") == html.count("</div>")
    vectors = html.index('id="vectors-layer-panel"')
    rasters = html.index('id="rasters-layer-panel"')
    between = html[vectors:rasters]
    # Panel Wektory zamyka się PRZED panelem Rastry.
    assert between.count("</div>") >= between.count("<div")


def test_codes_are_named_after_the_users_request():
    """5310 = Wydzielenie, 5332 = Budynki (data.py + kolor warstwy)."""
    from geostudio.web_app.data import CODES
    assert CODES["5310"] == "Wydzielenie"
    assert CODES["5332"] == "Budynki"
    js = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
    assert 'layer === "Budynki" || layer === "Wydzielenie"' in js


def test_focus_button_is_labelled_focus():
    html = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")
    assert "<kbd>Focus</kbd>" in html
    assert "<kbd>F11</kbd>" not in html
    assert "skrót F11" in html      # skrót nadal działa, tylko nie jest etykietą
