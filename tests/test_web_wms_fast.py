"""Szybsze pobieranie ortofoto: JPEG + równoległe kafelki."""
from __future__ import annotations

from io import BytesIO

from PIL import Image

from geostudio.web_app import underlay_wms


def _jpeg(width=64, height=64, color=(20, 120, 200)):
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_ortofoto_requests_jpeg(monkeypatch):
    seen = []

    def download(url, max_bytes):
        seen.append(url)
        return _jpeg()

    monkeypatch.setattr(underlay_wms, "_download", download)
    monkeypatch.setattr(underlay_wms, "layers_for",
                        lambda preset: (type("L", (), {"name": "ortho",
                                                      "crs": ["EPSG:2180"]})(),))
    underlay_wms.clear_cache()
    data, media = underlay_wms.map_image("standard", "ortho", 2180,
                                         0, 0, 100, 100, 256, 256)
    assert media == "image/jpeg"
    assert data.startswith(b"\xff\xd8")
    assert "FORMAT=image%2Fjpeg" in seen[0] or "FORMAT=image/jpeg" in seen[0]


def test_large_frame_is_split_into_parallel_tiles(monkeypatch):
    calls = []

    def download(url, max_bytes):
        calls.append(url)
        return _jpeg()

    monkeypatch.setattr(underlay_wms, "_download", download)
    monkeypatch.setattr(underlay_wms, "layers_for",
                        lambda preset: (type("L", (), {"name": "ortho",
                                                      "crs": ["EPSG:2180"]})(),))
    underlay_wms.clear_cache()
    data, media = underlay_wms.map_image("standard", "ortho", 2180,
                                         0, 0, 2000, 2000, 1600, 1600)
    assert len(calls) == 4            # cztery kafelki
    assert media == "image/jpeg"
    assert Image.open(BytesIO(data)).size == (1600, 1600)


def test_small_frame_is_one_request(monkeypatch):
    calls = []
    monkeypatch.setattr(underlay_wms, "_download",
                        lambda url, size: (calls.append(url), _jpeg())[1])
    monkeypatch.setattr(underlay_wms, "layers_for",
                        lambda preset: (type("L", (), {"name": "ortho",
                                                      "crs": ["EPSG:2180"]})(),))
    underlay_wms.clear_cache()
    underlay_wms.map_image("standard", "ortho", 2180, 0, 0, 100, 100, 512, 512)
    assert len(calls) == 1
