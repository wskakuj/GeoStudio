"""WMTS: kafelki zamiast GetMap oraz presety archiwalne z osią czasu."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from geostudio import wmts_service
from geostudio.web_app import underlay_wms

JS = Path("geostudio/web_app/static/map.js").read_text(encoding="utf-8")
HTML = Path("geostudio/web_app/static/index.html").read_text(encoding="utf-8")

CAPABILITIES = b"""<?xml version="1.0"?>
<Capabilities version="1.0.0" xmlns="http://www.opengis.net/wmts/1.0">
 <Contents>
  <Layer>
   <ows:Identifier xmlns:ows="http://www.opengis.net/ows/1.1">Raster</ows:Identifier>
   <ows:Title xmlns:ows="http://www.opengis.net/ows/1.1">Ortofotomapa</ows:Title>
   <Style><ows:Identifier xmlns:ows="http://www.opengis.net/ows/1.1">default</ows:Identifier></Style>
   <Format>image/jpeg</Format>
   <TileMatrixSetLink><TileMatrixSet>EPSG:2180</TileMatrixSet></TileMatrixSetLink>
  </Layer>
  <TileMatrixSet>
   <ows:Identifier xmlns:ows="http://www.opengis.net/ows/1.1">EPSG:2180</ows:Identifier>
   <ows:SupportedCRS xmlns:ows="http://www.opengis.net/ows/1.1">urn:ogc:def:crs:EPSG::2180</ows:SupportedCRS>
   <TileMatrix>
     <ows:Identifier xmlns:ows="http://www.opengis.net/ows/1.1">EPSG:2180:0</ows:Identifier>
     <ScaleDenominator>10000</ScaleDenominator>
     <TopLeftCorner>0 1000000</TopLeftCorner>
     <TileWidth>512</TileWidth><TileHeight>512</TileHeight>
     <MatrixWidth>10</MatrixWidth><MatrixHeight>10</MatrixHeight>
   </TileMatrix>
  </TileMatrixSet>
 </Contents>
</Capabilities>"""


def _jpeg(width=512, height=512):
    # Kafelek z teksturą — jednolity kolor byłby uznany za „pusty” (brak danych).
    image = Image.new("RGB", (width, height), (30, 90, 160))
    for x in range(0, width, 8):
        for y in range(0, height, 8):
            image.paste((200, 180, 60), (x, y, min(x + 4, width),
                                         min(y + 4, height)))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def test_presets_are_declared():
    for preset in ("standard_wmts", "high_wmts", "standard_time", "high_time"):
        assert preset in underlay_wms.PRESETS
    assert "WMTS/StandardResolution" in underlay_wms.PRESETS["standard_wmts"][1]
    assert "StandardResolutionTime" in underlay_wms.PRESETS["standard_time"][1]
    assert underlay_wms.TIME_PRESETS == frozenset({"standard_time", "high_time"})


def test_capabilities_are_parsed():
    sets = wmts_service.parse_capabilities(CAPABILITIES)
    assert sets[0].identifier == "EPSG:2180"
    matrix = sets[0].matrices[0]
    assert matrix.tile_width == 512
    assert matrix.resolution() == pytest.approx(10000 * 0.00028)


def test_tile_range_covers_the_area():
    sets = wmts_service.parse_capabilities(CAPABILITIES)
    matrix = sets[0].matrices[0]
    # Kafelek ma 512 x 2,8 m = 1433,6 m, więc 3000 m to co najmniej 2 kolumny.
    col0, row0, col1, row1 = wmts_service.tile_range(
        matrix, 0.0, 990000.0, 3000.0, 1000000.0)
    assert col0 == 0 and col1 >= 1
    assert row0 == 0 and row1 >= 1


def test_gettile_url_has_all_parameters():
    url = wmts_service.gettile_url("https://x/wmts", "Raster", "EPSG:2180",
                                   "EPSG:2180:0", 3, 7)
    for part in ("SERVICE=WMTS", "REQUEST=GetTile", "TILEMATRIX=EPSG:2180:0",
                 "TILEROW=3", "TILECOL=7", "TILEMATRIXSET=EPSG:2180"):
        assert part in url


def test_wmts_image_is_stitched_and_cropped(monkeypatch):
    monkeypatch.setattr(underlay_wms, "_download",
                        lambda url, size: CAPABILITIES if "GetCapabilities" in url
                        else _jpeg())
    underlay_wms._wmts_capabilities.cache_clear()
    underlay_wms._wmts_layers.cache_clear()
    underlay_wms.clear_cache()
    # Canvas: x = wschód, y = -północ. Matryca pokrywa północ 0..5120
    # i wschód 994880..1000000.
    data, media = underlay_wms.map_image(
        "standard_wmts", "Raster", 2180,
        900000, -1200, 1000000, 0, 256, 256)
    assert media == "image/jpeg"
    assert Image.open(BytesIO(data)).size == (256, 256)


def test_time_parameter_is_added_to_getmap(monkeypatch):
    seen = []

    def download(url, size):
        seen.append(url)
        return _jpeg(64, 64)

    monkeypatch.setattr(underlay_wms, "_download", download)
    monkeypatch.setattr(underlay_wms, "layers_for",
                        lambda preset, url=None: [
                            type("L", (), {"name": "Raster",
                                           "crs": ["EPSG:2180"]})()])
    underlay_wms.clear_cache()
    underlay_wms.map_png("standard_time", "Raster", 2180, 0, 0, 100, 100,
                         256, 256, None, "2020-06-15")
    assert any("TIME=2020-06-15" in url for url in seen)


def test_ui_lists_new_sources_and_date_field():
    for preset in ("standard_wmts", "high_wmts", "standard_time", "high_time"):
        assert f'<option value="{preset}">' in HTML
    assert 'id="underlay-time"' in HTML
    assert "const timePresets=new Set(" in JS


def test_layers_are_read_from_capabilities():
    layers = wmts_service.parse_layers(CAPABILITIES)
    assert layers[0].identifier == "Raster"
    assert layers[0].styles == ("default",)
    assert layers[0].formats == ("image/jpeg",)


def test_tile_uses_advertised_style_and_format(monkeypatch):
    seen = []

    def download(url, size):
        seen.append(url)
        if "GetCapabilities" in url:
            return CAPABILITIES
        return _jpeg()

    monkeypatch.setattr(underlay_wms, "_download", download)
    underlay_wms._wmts_capabilities.cache_clear()
    underlay_wms._wmts_layer_info.cache_clear()
    underlay_wms._wmts_layers.cache_clear()
    underlay_wms.clear_cache()
    underlay_wms.map_image("standard_wmts", "Raster", 2180,
                           900000, -1200, 1000000, 0, 256, 256)
    tiles = [url for url in seen if "GetTile" in url]
    assert tiles
    assert "STYLE=default" in tiles[0]
    assert "FORMAT=image/jpeg" in tiles[0]


def test_non_image_tile_reports_server_message(monkeypatch):
    def download(url, size):
        if "GetCapabilities" in url:
            return CAPABILITIES
        return (b"<ExceptionReport><Exception><ExceptionText>TileOutOfRange"
                b"</ExceptionText></Exception></ExceptionReport>")

    monkeypatch.setattr(underlay_wms, "_download", download)
    underlay_wms._wmts_capabilities.cache_clear()
    underlay_wms._wmts_layer_info.cache_clear()
    underlay_wms._wmts_layers.cache_clear()
    underlay_wms.clear_cache()
    # Ścieżka WMTS zgłasza treść wyjątku serwera...
    with pytest.raises(ValueError, match="TileOutOfRange"):
        underlay_wms._wmts_image("standard_wmts", "Raster", 2180,
                                 underlay_wms.WMSBounds(0, 900000, 1200, 1000000),
                                 256, 256)
    # ...a cały podkład i tak się pobiera (odwrót do WMS) albo kończy czytelnym
    # błędem, gdy i WMS zawiedzie.
    try:
        data, media = underlay_wms.map_image(
            "standard_wmts", "Raster", 2180, 900000, -1200, 1000000, 0, 256, 256)
        assert data
    except RuntimeError as exc:
        assert "TileOutOfRange" in str(exc)


def test_axis_order_is_detected_from_capabilities():
    """Geoportal podaje TopLeftCorner w innej kolejności — wykrywamy to."""
    # TopLeftCorner = "1000000 0" (wschód, północ) — konwencja odwrócona.
    swapped_xml = CAPABILITIES.replace(b"<TopLeftCorner>0 1000000</TopLeftCorner>",
                                       b"<TopLeftCorner>1000000 0</TopLeftCorner>")
    sets = wmts_service.parse_capabilities(swapped_xml)
    matrix = sets[0].matrices[0]
    # Matryca testowa ma 10x10 kafli po 1433 m, więc kadr musi się w niej zmieścić.
    col0, row0, col1, row1, swapped = wmts_service.tile_selection(
        matrix, -3000.0, 1000000.0, 0.0, 1009000.0)
    assert swapped is True
    assert 0 <= col0 <= col1 < matrix.matrix_width
    assert 0 <= row0 <= row1 < matrix.matrix_height


def test_row_never_exceeds_matrix_height():
    sets = wmts_service.parse_capabilities(CAPABILITIES)
    matrix = sets[0].matrices[0]
    col0, row0, col1, row1 = wmts_service.tile_range(
        matrix, 0.0, 990000.0, 3000.0, 1000000.0)
    assert row1 < matrix.matrix_height
    assert col1 < matrix.matrix_width


def test_tiles_fill_the_requested_frame_without_stretching(monkeypatch):
    """Obraz musi mieć dokładnie żądany rozmiar i proporcje kadru."""
    def download(url, size):
        return CAPABILITIES if "GetCapabilities" in url else _jpeg()

    monkeypatch.setattr(underlay_wms, "_download", download)
    underlay_wms._wmts_capabilities.cache_clear()
    underlay_wms._wmts_layer_info.cache_clear()
    underlay_wms._wmts_layers.cache_clear()
    underlay_wms.clear_cache()
    # Kadr 4000 x 2000 m -> obraz 400 x 200 px (proporcje 2:1).
    data = underlay_wms._wmts_image(
        "standard_wmts", "Raster", 2180,
        underlay_wms.WMSBounds(996000, 1000, 1000000, 3000), 400, 200)
    image = Image.open(BytesIO(data))
    assert image.size == (400, 200)


def test_axis_swap_does_not_stretch(monkeypatch):
    swapped_caps = CAPABILITIES.replace(b"<TopLeftCorner>0 1000000</TopLeftCorner>",
                                        b"<TopLeftCorner>1000000 0</TopLeftCorner>")

    def download(url, size):
        return swapped_caps if "GetCapabilities" in url else _jpeg()

    monkeypatch.setattr(underlay_wms, "_download", download)
    underlay_wms._wmts_capabilities.cache_clear()
    underlay_wms._wmts_layer_info.cache_clear()
    underlay_wms._wmts_layers.cache_clear()
    underlay_wms.clear_cache()
    data = underlay_wms._wmts_image(
        "standard_wmts", "Raster", 2180,
        underlay_wms.WMSBounds(-3000, 1000000, 0, 1009000), 300, 200)
    assert Image.open(BytesIO(data)).size == (300, 200)
