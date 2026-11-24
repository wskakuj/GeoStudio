"""Szybsze pobieranie ortofoto: JPEG + równoległe kafelki."""
from __future__ import annotations

from io import BytesIO

from PIL import Image

from geostudio.web_app import underlay_wms


def _png(width=64, height=64, color=(20, 120, 200)):
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg(width=64, height=64, color=(20, 120, 200)):
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_ortofoto_requests_jpeg_first(monkeypatch):
    seen = []

    def download(url, max_bytes):
        seen.append(url)
        return _png() if "png" in url.lower() else _jpeg()

    monkeypatch.setattr(underlay_wms, "_download", download)
    monkeypatch.setattr(underlay_wms, "layers_for",
                        lambda preset, url=None: (type("L", (), {"name": "ortho",
                                                      "crs": ["EPSG:2180"]})(),))
    underlay_wms.clear_cache()
    data, media = underlay_wms.map_image("standard", "ortho", 2180,
                                         0, 0, 100, 100, 256, 256)
    # Najpierw lekki JPEG bez przezroczystości.
    assert media == "image/jpeg"
    assert "FORMAT=image%2Fjpeg" in seen[0] or "FORMAT=image/jpeg" in seen[0]


def test_tiles_are_only_a_fallback(monkeypatch):
    """Duży kadr idzie JEDNYM żądaniem; kafelki dopiero gdy ono zawiedzie."""
    calls = []

    def download(url, max_bytes):
        calls.append(url)
        # Pojedyncze żądanie dużego kadru „wisi”, kafelki (mniejsze) działają.
        if "WIDTH=1600" in url:
            raise TimeoutError("timed out")
        return _jpeg()

    monkeypatch.setattr(underlay_wms, "_download", download)
    monkeypatch.setattr(underlay_wms, "layers_for",
                        lambda preset, url=None: (type("L", (), {"name": "ortho",
                                                      "crs": ["EPSG:2180"]})(),))
    underlay_wms.clear_cache()
    data, media = underlay_wms.map_image("standard", "ortho", 2180,
                                         0, 0, 2000, 2000, 1600, 1600)
    assert media == "image/jpeg"
    assert len(calls) > 1                 # po nieudanej próbie poszły kafelki


def test_small_frame_is_one_request(monkeypatch):
    calls = []
    monkeypatch.setattr(underlay_wms, "_download",
                        lambda url, size: (calls.append(url), _jpeg())[1])
    monkeypatch.setattr(underlay_wms, "layers_for",
                        lambda preset, url=None: (type("L", (), {"name": "ortho",
                                                      "crs": ["EPSG:2180"]})(),))
    underlay_wms.clear_cache()
    underlay_wms.map_image("standard", "ortho", 2180, 0, 0, 100, 100, 512, 512)
    # 512x512 = 262 tys. pikseli, poniżej progu kafelków: jedno żądanie.
    assert len(calls) == 1
