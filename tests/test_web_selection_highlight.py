"""Zaznaczenie obiektu musi być widoczne na czerwonym 5310."""
from __future__ import annotations

from pathlib import Path

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def _highlight_block() -> str:
    start = JS.index("function renderHighlights(features) {")
    end = JS.index("function nativeWorldPoint(point) {")
    return JS[start:end]


def test_selection_has_white_halo():
    block = _highlight_block()
    assert 'ctx.strokeStyle="rgba(255,255,255,.95)";' in block
    assert "ctx.lineWidth=active?8:6;" in block


def test_selection_colour_contrasts_with_red_5310():
    block = _highlight_block()
    assert 'ctx.strokeStyle=active?"#1B6BFF":"#00C2A8";' in block
    assert "#f28b4b" not in block          # stary pomarańczowy cień


def test_active_object_gets_a_light_fill():
    block = _highlight_block()
    assert 'ctx.fillStyle="rgba(27,107,255,.13)";' in block
    assert 'ctx.fill("evenodd");' in block


def test_pinned_objects_use_dashed_outline():
    block = _highlight_block()
    assert "ctx.setLineDash(active?[]:[6,4]);" in block
