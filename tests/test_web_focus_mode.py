"""Tryb skupienia i zwijanie paneli (Inspektor, Warstwy mapy, wstążka)."""
from __future__ import annotations

from pathlib import Path

HTML = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")
JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
CSS = Path("geostudio/web_app/static/styles.css").read_text(encoding="utf-8")


def test_history_is_left_of_the_other_header_actions():
    actions = HTML.index('<div class="header-actions">')
    history = HTML.index('class="header-action-group header-history"')
    preferences = HTML.index('class="header-action-group header-preferences"')
    assert actions < history < preferences


def test_focus_button_sits_where_history_was():
    assert 'id="btn-focus"' in HTML
    focus = HTML.index('id="btn-focus"')
    # Po prawej stronie paska akcji, za ustawieniami i tytułem dokumentu.
    assert focus > HTML.index('class="header-action-group header-preferences"')
    assert 'aria-pressed="false"' in HTML[focus:focus + 400]


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
