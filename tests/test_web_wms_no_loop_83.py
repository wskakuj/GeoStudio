"""„Cały czas pobieranie” — stan musi się kończyć, a błędy nie mogą się zapętlać."""
from __future__ import annotations

from pathlib import Path

from geostudio.web_app import underlay_wms

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def test_loading_state_is_always_cleared():
    start = JS.index("  async function refreshUnderlay(){")
    block = JS[start:start + 2200]
    assert "finally{" in block
    assert "underlay.loading=false;" in block
    assert '"Podkład gotowy · EPSG:"+underlay.epsg' in block


def test_error_status_is_visible_in_the_summary():
    assert 'błąd(y) pobierania — szczegóły w panelu Rastry.' in JS


def test_retry_cooldown_after_error():
    assert "item.retryAfter=Date.now()+5000;" in JS
    start = JS.index("async function refreshUnderlayItem(")
    block = JS[start:start + 900]
    assert "if(item.retryAfter&&Date.now()<item.retryAfter){" in block
    assert "item.retryAfter=0;" in JS


def test_jpeg_first_only_for_ortho():
    """Warstwy wektorowe (KIEG) i własne serwery potrzebują PNG z alfą."""
    assert underlay_wms._attempts_for("standard")[0][1] == "image/jpeg"
    assert underlay_wms._attempts_for("kieg")[0][1] == "image/png"
    assert underlay_wms._attempts_for("custom")[0][1] == "image/png"
