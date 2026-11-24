"""Cztery błędy WMS/WMTS: krycie, TIME w kafelkach, data podkładu, podwójny XML."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from geostudio.web_app import underlay_wms

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")


def _png(width=64, height=64):
    buffer = BytesIO()
    Image.new("RGB", (width, height), (40, 90, 140)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_opacity_slider_updates_visible_underlays():
    """Suwak z okna WMS musi zmieniać item.opacity, a nie tylko underlay.opacity."""
    start = JS.index('$("underlay-opacity").addEventListener("input"')
    block = JS[start:start + 500]
    assert 'for(const item of underlays)if(item.kind!=="raster")item.opacity=value;' in block


def test_archive_date_is_part_of_the_underlay_identity():
    start = JS.index("function applyUnderlayUnsafe(){")
    block = JS[start:start + 2600]
    assert "wantedTime=timePresets.has(preset)" in block
    assert '(entry.time||"")===wantedTime' in block
    assert "time:wantedTime," in block


def test_dialog_informs_where_to_change_opacity():
    """Okno zostaje otwarte (widać status i błędy), ale mówi, gdzie zmienić krycie."""
    start = JS.index("function applyUnderlayUnsafe(){")
    block = JS[start:start + 2600]
    assert "Krycie i widoczność ustawisz w panelu Rastry." in block


def test_tiles_keep_the_archive_date(monkeypatch):
    seen = []

    def download(url, size):
        seen.append(url)
        return _png()

    monkeypatch.setattr(underlay_wms, "_download", download)
    monkeypatch.setattr(underlay_wms, "layers_for",
                        lambda preset, url=None: [type("L", (), {
                            "name": "Raster", "crs": ["EPSG:2180"]})()])
    underlay_wms.clear_cache()
    underlay_wms.map_png("standard", "Raster", 2180, 0, 0, 1000, 1000,
                         1000, 1000, time="2020-05-01")
    assert len(seen) > 1                       # poszło kafelkami
    assert all("TIME=2020-05-01" in url for url in seen)


def test_smaller_fallback_keeps_the_archive_date(monkeypatch):
    seen = []

    def download(url, size):
        seen.append(url)
        raise RuntimeError("Geoportal: zbyt duży obraz")

    monkeypatch.setattr(underlay_wms, "_download", download)
    monkeypatch.setattr(underlay_wms, "layers_for",
                        lambda preset, url=None: [type("L", (), {
                            "name": "Raster", "crs": ["EPSG:2180"]})()])
    monkeypatch.setattr(underlay_wms, "ORTO_TILE_LIMIT", 10 ** 9)
    underlay_wms.clear_cache()
    try:
        underlay_wms.map_png("standard", "Raster", 2180, 0, 0, 100, 100,
                             512, 512, time="2019-08-02")
    except RuntimeError:
        pass
    assert seen
    assert any("TIME=2019-08-02" in url for url in seen)


def test_capabilities_xml_is_downloaded_once(monkeypatch):
    calls = []

    def download(url, size):
        calls.append(url)
        return CAPABILITIES

    monkeypatch.setattr(underlay_wms, "_download", download)
    underlay_wms._wmts_capabilities_xml.cache_clear()
    underlay_wms._wmts_capabilities.cache_clear()
    underlay_wms._wmts_layer_info.cache_clear()
    underlay_wms._wmts_capabilities("standard_wmts")
    underlay_wms._wmts_layer_info("standard_wmts")
    assert len(calls) == 1


CAPABILITIES = b"""<?xml version="1.0"?>
<Capabilities><Contents>
 <Layer><Identifier>Raster</Identifier><Title>Orto</Title>
  <Style><Identifier>default</Identifier></Style><Format>image/jpeg</Format></Layer>
 <TileMatrixSet><Identifier>EPSG:2180</Identifier>
  <SupportedCRS>EPSG:2180</SupportedCRS>
  <TileMatrix><Identifier>EPSG:2180:0</Identifier><ScaleDenominator>10000</ScaleDenominator>
   <TopLeftCorner>0 1000000</TopLeftCorner><TileWidth>512</TileWidth><TileHeight>512</TileHeight>
   <MatrixWidth>10</MatrixWidth><MatrixHeight>10</MatrixHeight></TileMatrix>
 </TileMatrixSet></Contents></Capabilities>"""
