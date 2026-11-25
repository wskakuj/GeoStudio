"""Persistent WMS image cache (request lifecycle is exercised in Node tests)."""
from __future__ import annotations

from geostudio.web_app import underlay_wms


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
