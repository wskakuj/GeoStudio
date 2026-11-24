"""Ortofoto: dłuższy limit czasu i odwrót do mniejszego obrazu."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from geostudio.web_app import underlay_wms

SRC = Path("geostudio/web_app/underlay_wms.py").read_text(encoding="utf-8")
JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def _png(width, height):
    buffer = BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


class Layer:
    name = "ortho"
    crs = ["EPSG:2180"]


def test_geoportal_has_a_long_timeout():
    assert 'HOST_TIMEOUTS = {' in SRC
    assert '"mapy.geoportal.gov.pl": 60,' in SRC
    assert "def _timeout_for(host: str) -> int:" in SRC


def test_client_asks_for_smaller_images():
    # 2048x2048 renderowało się dłużej niż limit czasu serwera.
    assert "const maxPixels=sharp?2200000:800000;" in JS


def test_timeout_falls_back_to_a_smaller_image(monkeypatch):
    calls = []

    def download(url, max_bytes):
        calls.append(url)
        # Duży obraz „wisi”, mały odpowiada.
        if "WIDTH=1600" in url:
            raise TimeoutError("timed out")
        return _png(64, 64)

    monkeypatch.setattr(underlay_wms, "_download", download)
    monkeypatch.setattr(underlay_wms, "layers_for", lambda preset, url=None: [Layer()])
    # Wyłączamy kafelki, żeby sprawdzić właśnie odwrót do mniejszego obrazu.
    monkeypatch.setattr(underlay_wms, "ORTO_TILE_LIMIT", 10_000_000)
    underlay_wms.clear_cache()
    data, media = underlay_wms.map_image("standard", "ortho", 2180,
                                         0, 0, 1000, 1000, 1600, 1600)
    assert media == "image/png"
    assert Image.open(BytesIO(data)).size == (64, 64)
    assert any("WIDTH=1120" in url for url in calls)   # 0,7 × 1600
