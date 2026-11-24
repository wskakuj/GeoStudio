"""Stan „Odświeżanie obrazu…” musi się kończyć także po przerwaniu żądania."""
from __future__ import annotations

from pathlib import Path

from geostudio.web_app import underlay_wms

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def test_abort_clears_the_loading_flag():
    start = JS.index('if(error.name==="AbortError"||id!==item.ticket){')
    block = JS[start:start + 320]
    assert "if(id===item.ticket)item.loading=false;" in block


def test_panel_refreshes_when_loading_starts():
    start = JS.index("    item.loading=true;")
    assert JS[start:start + 80].count("renderRasterLayers();") == 1


def test_geoportal_timeout_is_shorter():
    assert underlay_wms.HOST_TIMEOUTS["mapy.geoportal.gov.pl"] <= 30


def test_frame_is_about_one_megapixel():
    assert "const maxPixels=sharp?1000000:1000000;" in JS
