"""Przesuwanie etykiet i kotwice wysięgników: szybkość i brak zawieszeń."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
MAP = Path("/scratch/input/MOKRA_WIEŚ_GeoStudio2_kopia-3.MAP")


def test_label_drag_does_not_block_the_ui():
    """Upuszczenie etykiety nie ustawia blokady edycji — zapis idzie w tle."""
    start = JS.index("function commitLabelDrag(drag) {")
    block = JS[start:start + 400]
    assert "queueLabelMove(drag);" in block
    assert "editBusy=true" not in block


def test_label_moves_are_coalesced():
    assert "const pendingLabelMoves=new Map();" in JS
    assert "labelMoveTimer=setTimeout(flushLabelMoves,140);" in JS


def test_leader_mode_stays_on_after_anchoring():
    """Kotwiczenie kilku etykiet pod rząd — tryb zostaje włączony."""
    assert "function leaveLeaderMode(){" in JS
    start = JS.index("async function setLeaderAnchor(selected,world){")
    block = JS[start:start + 1400]
    assert "finally{" in block
    assert "state.anchorDrag=null;" in block


def test_pointer_safety_nets():
    assert 'window.addEventListener("pointercancel"' in JS
    assert "if(state.labelDrag&&dragState&&dragState.pointer!==ev.pointerId){" in JS


def test_move_label_is_fast_on_a_real_map():
    if not MAP.exists():
        pytest.skip("brak mapy testowej")
    from geostudio.web_app.data import PreviewWorkspace
    workspace = PreviewWorkspace()
    workspace.load_map(MAP.read_bytes(), "MOKRA.MAP")
    status = workspace.editing_status()
    entry = next(e for e in workspace._entries
                 if e.obj.code == "5310" and e.obj.is_closed
                 and e.obj.fields.get("A1"))
    fid = workspace._object_id[id(entry.obj)]
    started = time.perf_counter()
    workspace.move_label(fid, "A1", 512900.0, 669340.0,
                         document_token=status["documentToken"],
                         revision=status["revision"])
    elapsed = time.perf_counter() - started
    assert elapsed < 0.5, f"przesunięcie etykiety trwało {elapsed:.2f} s"


def test_leader_anchor_is_fast_on_a_real_map():
    if not MAP.exists():
        pytest.skip("brak mapy testowej")
    from geostudio.web_app.data import PreviewWorkspace
    workspace = PreviewWorkspace()
    workspace.load_map(MAP.read_bytes(), "MOKRA.MAP")
    status = workspace.editing_status()
    entry = next(e for e in workspace._entries
                 if e.obj.code == "5310" and e.obj.is_closed
                 and e.obj.fields.get("A1"))
    fid = workspace._object_id[id(entry.obj)]
    started = time.perf_counter()
    workspace.set_label_leader(fid, 2, True, (512900.0, 669340.0),
                               prefer_left=True,
                               document_token=status["documentToken"],
                               revision=status["revision"])
    elapsed = time.perf_counter() - started
    assert elapsed < 0.5, f"kotwica wysięgnika trwała {elapsed:.2f} s"
