"""Zapis kopii gasi znacznik zmian; odwrót WMTS->WMS bierze nazwę z WMS."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from geostudio.web_app import underlay_wms

PICKER = Path("geostudio/web_app/native_picker.py").read_text(encoding="utf-8")
JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")

WMS_CAPABILITIES = b"""<?xml version="1.0"?>
<WMS_Capabilities version="1.3.0"><Capability><Layer><Layer>
  <Name>ORTOFOTOMAPA</Name><Title>Ortofotomapa</Title><CRS>EPSG:2180</CRS>
</Layer></Layer></Capability></WMS_Capabilities>"""

WMTS_CAPABILITIES = b"""<?xml version="1.0"?>
<Capabilities><Contents>
 <Layer><Identifier>Raster</Identifier><Title>Orto</Title>
  <Style><Identifier>default</Identifier></Style><Format>image/jpeg</Format></Layer>
 <TileMatrixSet><Identifier>EPSG:2180</Identifier>
  <SupportedCRS>EPSG:2180</SupportedCRS>
  <TileMatrix><Identifier>EPSG:2180:0</Identifier><ScaleDenominator>10000</ScaleDenominator>
   <TopLeftCorner>0 1000000</TopLeftCorner><TileWidth>512</TileWidth><TileHeight>512</TileHeight>
   <MatrixWidth>10</MatrixWidth><MatrixHeight>10</MatrixHeight></TileMatrix>
 </TileMatrixSet></Contents></Capabilities>"""


def _png(width=64, height=64):
    buffer = BytesIO()
    image = Image.new("RGB", (width, height), (40, 90, 140))
    for x in range(0, width, 8):
        image.paste((200, 180, 60), (x, 0, min(x + 4, width), 4))
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_saving_a_copy_marks_the_document_saved():
    # _save_map jest zdefiniowane PO save_base_map, więc szukamy od jego
    # definicji do końca metody (kolejna definicja na tym samym poziomie).
    start = PICKER.index("def _save_map(self, *, burn_cutouts: bool | None) -> dict:")
    rest = PICKER[start + 10:]
    nxt = rest.find("\n    def ")
    block = rest[:nxt if nxt > 0 else len(rest)]
    assert "self._workspace.mark_saved()" in block


def test_wmts_fallback_uses_the_wms_layer_name(monkeypatch):
    seen = []

    def download(url, size):
        seen.append(url)
        if "GetCapabilities" in url and "WMTS" in url:
            return WMTS_CAPABILITIES
        if "GetCapabilities" in url:
            return WMS_CAPABILITIES
        if "GetTile" in url:
            # WMTS zwraca błąd, żeby wymusić odwrót do WMS.
            return b"<ExceptionReport><Exception><ExceptionText>Boom</ExceptionText></Exception></ExceptionReport>"
        return _png()

    monkeypatch.setattr(underlay_wms, "_download", download)
    for name in ("_wmts_capabilities", "_wmts_layer_info", "_wmts_layers",
                 "_layers_for_preset"):
        getattr(underlay_wms, name).cache_clear()
    underlay_wms.clear_cache()
    data, media = underlay_wms.map_image(
        "standard_wmts", "Raster", 2180, 900000, -1200, 1000000, 0, 256, 256)
    assert data
    wms_urls = [url for url in seen if "GetMap" in url]
    assert wms_urls
    # Nazwa warstwy z WMTS ("Raster") nie może trafić do WMS.
    assert "LAYERS=Raster" not in wms_urls[0]
    assert "LAYERS=ORTOFOTOMAPA" in wms_urls[0]


def test_client_clears_dirty_before_asking_the_server():
    start = JS.index("async function downloadMapCopy() {")
    block = JS[start:start + 1400]
    assert "state.edit.dirty=false;updateEditState(state.edit);" in block
