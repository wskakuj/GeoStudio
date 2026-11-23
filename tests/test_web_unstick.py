"""Mapa nie może zostać zablokowana po edycji etykiet/wysięgników."""
from __future__ import annotations

from pathlib import Path

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def test_hard_reset_clears_every_drag_state():
    assert "function resetTransientDrags(){" in JS
    for state_name in ("state.drag", "state.labelDrag", "state.anchorDrag",
                       "state.vertexDrag", "state.sheetRotate",
                       "state.blockRectDrag"):
        assert f"{state_name}=null" in JS


def test_pointerdown_recovers_from_stale_drag():
    assert "Poprzednie przeciąganie nie zostało zamknięte" in JS
    assert "resetTransientDrags();" in JS


def test_blur_and_hidden_window_reset_drags():
    assert 'window.addEventListener("blur"' in JS
    assert 'document.addEventListener("visibilitychange"' in JS


def test_escape_unsticks_the_map():
    assert 'ev.key==="Escape"&&(state.drag||state.labelDrag||state.anchorDrag||state.editBusy)' in JS
    assert 'inform("Odblokowano mapę.");' in JS


def test_anchor_drag_does_not_reload_the_document():
    start = JS.index('window.addEventListener("pointerup",async ev=>{')
    block = JS[start:start + 900]
    assert "refreshEditedDocument" not in block
    # Po zmianie kotwicy pobieramy świeże etykiety (nie pełny reload dokumentu).
    assert "refreshLabelsNow();" in block


def test_leader_mode_does_not_hijack_the_tool():
    """Tryb wysięgników jest nakładką — nie może ustawiać state.tool."""
    assert 'if(state.leaderMode)state.tool="labels";' not in JS
    assert "Tryb wysięgników NIE przejmuje narzędzia" in JS


def test_leader_mode_miss_falls_through_to_normal_click():
    assert "W trybie wysięgników pudło w etykietę NIE blokuje mapy" in JS


def test_s_key_toggles_leader_mode():
    assert 'if(ev.key.toLowerCase()!=="s"||!state.edit)return;' in JS
    assert "toggleLeaderMode();" in JS


def test_all_visible_wms_layers_refresh():
    assert "const targets=underlays.filter(item=>item.visible);" in JS
    assert "async function refreshUnderlayItem(" in JS


def test_label_changes_force_a_viewport_refetch():
    """Gdy cała mapa jest w pamięci, scheduleViewport() rysował STARE etykiety."""
    assert "async function refreshLabelsNow(){" in JS
    assert "state.localMapReady=false;" in JS
    assert JS.count("await refreshLabelsNow();") >= 5
