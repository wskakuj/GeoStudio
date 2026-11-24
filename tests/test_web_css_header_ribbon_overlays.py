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
    assert "body[data-theme] .floating-tools {\n  background: #1e2c3d;" in CSS
    assert "body[data-theme] .floating.active {" in CSS
