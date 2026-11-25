"""Stan „Odświeżanie obrazu…” musi się kończyć także po przerwaniu żądania."""
from __future__ import annotations

from pathlib import Path

from geostudio.web_app import underlay_wms

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


# Aborted requests and stale generations are exercised by the actual JS
# in test_web_wms_request_lifecycle.py instead of checking source strings.


def test_panel_refreshes_when_loading_starts():
    start = JS.index("    item.loading=true;")
    assert JS[start:start + 80].count("renderRasterLayers();") == 1


def test_geoportal_timeout_is_shorter():
    assert underlay_wms.HOST_TIMEOUTS["mapy.geoportal.gov.pl"] <= 30


def test_frame_is_about_one_megapixel():
    assert "const maxPixels=sharp?1000000:1000000;" in JS
