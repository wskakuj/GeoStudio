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


def test_image_is_always_drawn_on_its_own_bounds():
    # Rozciąganie starego obrazu na nowy kadr przesuwało ortofoto względem
    # wektorów (2.0.62) — teraz georeferencja jest zawsze poprawna.
    assert "const bounds=item.bounds;" in JS
    assert "pendingBounds" not in JS


def test_loading_preview_is_only_a_background_hint():
    # Podczas pobierania widać rozmyte tło, ale wierzchnia warstwa to obraz
    # na swoim zasięgu.
    assert "if(item.loading&&item.image&&item.bounds){" in JS
    assert "ctx.drawImage(item.image,0,0,state.width,state.height);" in JS
