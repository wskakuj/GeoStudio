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
    # Jedno żądanie na kadr: 1,2 mln px (bez drugiej fazy „ostrej”).
    assert "const maxPixels=sharp?1200000:1200000;" in JS
    assert "scheduleUnderlaySharp" not in JS


def test_large_frames_split_into_tiles():
    # Kafelki to ostateczność: dopiero powyżej 2,4 mln px.
    assert underlay_wms.ORTO_TILE_LIMIT == 2_400_000


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
                         1600, 1600)
    assert len(calls) == 1          # jedno żądanie, bez kafelków


def test_image_is_always_drawn_on_its_own_bounds():
    # Rozciąganie starego obrazu na nowy kadr przesuwało ortofoto względem
    # wektorów (2.0.62) — teraz georeferencja jest zawsze poprawna.
    assert "const bounds=item.bounds;" in JS
    assert "pendingBounds" not in JS


def test_no_ghost_of_the_previous_frame():
    # Stary obraz rozciągnięty na cały ekran wyglądał jak „widmo” — usunięte.
    assert "ctx.drawImage(item.image,0,0,state.width,state.height);" not in JS
    assert "Żadnego „widma”" in JS
