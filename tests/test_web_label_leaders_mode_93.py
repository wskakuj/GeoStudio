"""Tryb wysięgników: kółko kotwiczy, Q/W zmienia stronę, tryb zostaje włączony."""
from __future__ import annotations

from pathlib import Path

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def test_middle_click_anchors_without_picking_a_label():
    assert "function labelOfActiveObject(){" in JS
    assert "const selected=state.labelSelected||labelOfActiveObject();" in JS


def test_leader_mode_stays_on_after_anchoring():
    start = JS.index("async function setLeaderAnchor(selected,world){")
    block = JS[start:start + 1500]
    assert "leaveLeaderMode();" not in block
    assert "state.anchorDrag=null;" in block


def test_q_and_w_flip_the_side():
    assert 'if(key!=="q"&&key!=="w")return;' in JS
    assert "flipLeaderSide(selected,key===\"q\");" in JS


def test_escape_leaves_leader_mode():
    assert 'if(ev.key==="Escape"&&state.leaderMode){' in JS
    assert 'inform("Tryb wysięgników wyłączony.");' in JS
