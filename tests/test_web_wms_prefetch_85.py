"""Szybsze odświeżanie: cache na dysku, większy zapas kadru, pobieranie z wyprzedzeniem."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from geostudio.web_app import underlay_wms

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def test_overscan_is_larger():
    assert "const bounds=boundsFromViewport(.6);" in JS


def test_prefetch_follows_the_pan_direction():
    assert "function scheduleUnderlayPrefetch(){" in JS
    assert "function rememberPanVector(dx,dy){" in JS
    assert "rememberPanVector(stepX,stepY);" in JS
    assert "lastPanVector.x*spanX*.5" in JS


def test_prefetch_does_not_replace_the_visible_image():
    start = JS.index("async function refreshUnderlayItem(")
    block = JS[start:start + 2600]
    assert "prefetch=false" in block
    assert "if(prefetch){item.loading=false;item.error=\"\";item.retryAfter=0;return;}" in block


def test_disk_cache_round_trip(monkeypatch, tmp_path):
    monkeypatch.delenv("GEOSTUDIO_WMS_DISK_CACHE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    key = ("standard", "ortho", 2180, 1, 2, 3, 4, 128, 128)
    underlay_wms._disk_cache_clear_for_tests() if hasattr(
        underlay_wms, "_disk_cache_clear_for_tests") else None
    underlay_wms._disk_put(key, b"obraz")
    assert underlay_wms._disk_get(key) == b"obraz"


def test_disk_cache_can_be_disabled(monkeypatch):
    monkeypatch.setenv("GEOSTUDIO_WMS_DISK_CACHE", "0")
    assert underlay_wms._disk_cache_dir() is None
    assert underlay_wms._disk_get(("a",)) is None
