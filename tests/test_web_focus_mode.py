"""Tryb skupienia i zwijanie paneli (Inspektor, Warstwy mapy, wstążka)."""
from __future__ import annotations

from pathlib import Path

HTML = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")
JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
CSS = Path("geostudio/web_app/static/styles.css").read_text(encoding="utf-8")


def test_history_is_on_the_left_of_the_window():
    """Cofnij/Ponów stoją zaraz za logo, PRZED tytułem dokumentu."""
    identity = HTML.index('class="identity"')
    history = HTML.index('class="header-action-group header-history"')
    center = HTML.index('<div class="header-center">')
    actions = HTML.index('<div class="header-actions">')
    assert identity < history < center < actions


def test_focus_button_sits_before_export():
    assert 'id="btn-focus"' in HTML
    focus = HTML.index('id="btn-focus"')
    export = HTML.index('id="btn-export"')
    open_map = HTML.index('id="btn-open"')
    assert focus < export < open_map
    assert 'aria-pressed="false"' in HTML[focus:focus + 400]


def test_ribbon_collapse_is_first_in_the_tab_row():
    tabs = HTML.index('<div class="ribbon-tabs"')
    collapse = HTML.index('id="ribbon-collapse"')
    assert collapse < tabs
    assert ".ribbon-collapse" in CSS


def test_collapse_buttons_use_theme_variables():
    """Bez tego przyciski mają kolory ciemnego motywu także w jasnym."""
    start = CSS.index(".panel-collapse {")
    block = CSS[start:start + 420]
    assert "var(--ui-panel" in block and "var(--ui-edge" in block
    # Brak twardych kolorów ciemnego motywu (dopuszczalny tylko fallback w var()).
    assert "background:#182a3d" not in block
    assert "border:1px solid #2d4054" not in block


def test_focus_icon_is_symmetric():
    focus = HTML.index('id="btn-focus"')
    block = HTML[focus:focus + 1200]
    # Cztery symetryczne narożniki (9/27), a nie krzywy łuk.
    assert 'd="M9 13V9h4M27 9h4v4M31 27v4h-4M13 31H9v-4"' in block


def test_every_panel_has_a_collapse_button():
    assert 'id="panel-collapse-left"' in HTML
    assert 'id="panel-collapse-right"' in HTML
    assert 'id="ribbon-collapse"' in HTML


def test_collapsed_states_are_styled():
    assert "body.left-collapsed .workspace" in CSS
    assert "body.right-collapsed .workspace" in CSS
    assert "body.ribbon-collapsed .ribbon-panels { display:none; }" in CSS
    assert "body.focus-mode .workspace" in CSS
    # Szybki przybornik zostaje widoczny w trybie skupienia.
    assert ".floating" not in CSS.split("body.focus-mode")[1][:600]


def test_focus_logic_toggles_all_three_panels():
    assert "function togglePanel(which){" in JS
    assert "function toggleFocus(){" in JS
    assert 'link("btn-focus",toggleFocus);' in JS
    assert 'link("panel-collapse-left",()=>togglePanel("left"));' in JS
    assert 'link("panel-collapse-right",()=>togglePanel("right"));' in JS
    assert 'link("ribbon-collapse",()=>togglePanel("ribbon"));' in JS
    assert 'if(ev.key==="F11"' in JS


def test_focus_restores_the_saved_layout():
    assert 'localStorage.setItem("geostudio.panels"' in JS
    assert 'localStorage.getItem("geostudio.panels"' in JS


def test_tab_click_expands_the_collapsed_ribbon():
    """Klik w dowolną zakładkę ma rozwijać wstążkę, jak przycisk Zwiń/Rozwiń."""
    start = JS.index("function activateRibbonTab(id,focus=false){")
    block = JS[start:start + 1600]
    assert 'document.body.classList.contains("ribbon-collapsed")' in block
    assert 'document.body.classList.remove("ribbon-collapsed");' in block
    assert "applyPanelState();" in block
