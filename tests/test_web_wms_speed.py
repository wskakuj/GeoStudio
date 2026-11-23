"""Szybsze odświeżanie podkładu: mniejszy kadr, kafelki, płynne przesuwanie."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from geostudio.web_app import underlay_wms

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def _png(width=64, height=64):
    buffer = BytesIO()
    image = Image.new("RGB", (width, height), (40, 90, 140))
    for x in range(0, width, 8):
        image.paste((200, 180, 60), (x, 0, min(x + 4, width), 4))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_frame_size_is_capped_for_speed():
    assert "const maxPixels=800000;" in JS


def test_large_frames_split_into_tiles():
    assert underlay_wms.ORTO_TILE_LIMIT == 450_000


def test_big_frame_uses_several_requests(monkeypatch):
    calls = []

    def download(url, size):
        calls.append(url)
        return _png()

    monkeypatch.setattr(underlay_wms, "_download", download)
    monkeypatch.setattr(underlay_wms, "layers_for",
                        lambda preset, url=None: [
                            type("L", (), {"name": "Raster",
                                           "crs": ["EPSG:2180"]})()])
    underlay_wms.clear_cache()
    underlay_wms.map_png("standard", "Raster", 2180, 0, 0, 1000, 1000,
                         1000, 1000)
    assert len(calls) > 1          # kafelki, nie jedno wielkie żądanie


def test_old_image_is_stretched_while_loading():
    # Podczas pobierania rysujemy poprzedni obraz na obszarze docelowym,
    # żeby mapa nie robiła się pusta.
    assert "const bounds=(item.loading&&item.pendingBounds)?item.pendingBounds:item.bounds;" in JS
    assert "item.pendingBounds=bounds.slice();" in JS
    assert "item.pendingBounds=null;" in JS
