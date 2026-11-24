"""Ręczne scalanie po A1, maska z geometrii natywnej, znacznik po zapisie."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from geostudio.web_app.data import PreviewWorkspace  # noqa: E402

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
HTML = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")
TRACE = Path("geostudio/web_app/static/raster_trace.js").read_text(encoding="utf-8")
MAP = Path("/scratch/input/02_BYSŁAWEK.MAP")


def _workspace():
    if not MAP.exists():
        pytest.skip("brak mapy testowej")
    workspace = PreviewWorkspace()
    workspace.load_map(MAP.read_bytes(), "02.MAP")
    return workspace


def test_manual_create_offers_merge_by_a1():
    assert 'id="create-merge-a1"' in HTML
    assert "Scalaj po A1" in HTML
    assert 'mergeSameA1:!!$("create-merge-a1")?.checked' in JS


def test_manual_create_reports_merge():
    assert "scalony z " in JS and "mergedSameA1" in JS


def test_trace_mask_uses_native_geometry():
    assert "(feature.nativeGeometry||feature.geometry)" in TRACE
    assert 'native:"1"' in JS


def test_viewport_can_return_native_geometry():
    workspace = _workspace()
    plain = workspace.viewport((0, -1e6, 1e6, 1e6), limit=5)["features"]
    native = workspace.viewport((0, -1e6, 1e6, 1e6), limit=5,
                                native=True)["features"]
    assert "nativeGeometry" not in plain[0]
    assert "nativeGeometry" in native[0]


def test_dirty_marker_is_cleared_immediately_after_save():
    start = JS.index("async function downloadMapCopy() {")
    block = JS[start:start + 1400]
    assert "state.edit.dirty=false;updateEditState(state.edit);" in block


def test_wms_request_margin_matches_geo_map():
    # GEO-MAP prosi o widoczny prostokąt z małym zapasem.
    assert "boundsFromViewport(.15)" in JS
