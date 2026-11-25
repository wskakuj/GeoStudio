"""WMTS: kafelki zamiast GetMap oraz presety archiwalne z osią czasu."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

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
     <TopLeftCorner>850000 100000</TopLeftCorner>
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
        matrix, 840000.0, 101000.0, 843000.0, 111000.0, crs=sets[0].crs)
    assert (col0, row0, col1, row1) == (0, 4, 7, 6)


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
    # Canvas: x = wschód, y = -północ. EPSG:2180 zapisuje narożnik N,E.
    data, media = underlay_wms.map_image(
        "standard_wmts", "Raster", 2180,
        101000, -849000, 104000, -847000, 300, 200)
    assert media == "image/jpeg"
    assert Image.open(BytesIO(data)).size == (300, 200)


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
                           101000, -849000, 104000, -847000, 300, 200)
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
                                 underlay_wms.WMSBounds(847000, 101000, 849000, 104000),
                                 300, 200)
    # ...a cały podkład i tak się pobiera (odwrót do WMS) albo kończy czytelnym
    # błędem, gdy i WMS zawiedzie.
    try:
        data, media = underlay_wms.map_image(
            "standard_wmts", "Raster", 2180, 101000, -849000, 104000, -847000, 300, 200)
        assert data
    except RuntimeError as exc:
        assert "TileOutOfRange" in str(exc)


def test_axis_order_is_read_from_the_advertised_crs():
    """EPSG:3857 podaje narożnik E,N; kierunki kafli pozostają takie same."""
    swapped_xml = CAPABILITIES.replace(b"EPSG:2180", b"EPSG:3857").replace(
        b"EPSG::2180", b"EPSG::3857").replace(
        b"<TopLeftCorner>850000 100000</TopLeftCorner>",
        b"<TopLeftCorner>100000 850000</TopLeftCorner>")
    sets = wmts_service.parse_capabilities(swapped_xml)
    matrix = sets[0].matrices[0]
    # Matryca testowa ma 10x10 kafli po 1433 m, więc kadr musi się w niej zmieścić.
    col0, row0, col1, row1, swapped = wmts_service.tile_selection(
        matrix, 847000.0, 101000.0, 849000.0, 104000.0, crs=sets[0].crs)
    assert swapped is True
    assert 0 <= col0 <= col1 < matrix.matrix_width
    assert 0 <= row0 <= row1 < matrix.matrix_height


def test_row_never_exceeds_matrix_height():
    sets = wmts_service.parse_capabilities(CAPABILITIES)
    matrix = sets[0].matrices[0]
    col0, row0, col1, row1 = wmts_service.tile_range(
        matrix, 840000.0, 100000.0, 850000.0, 120000.0, crs=sets[0].crs)
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
        underlay_wms.WMSBounds(847000, 101000, 849000, 105000), 400, 200)
    image = Image.open(BytesIO(data))
    assert image.size == (400, 200)


def test_axis_swap_does_not_stretch(monkeypatch):
    swapped_caps = CAPABILITIES.replace(b"EPSG:2180", b"EPSG:3857").replace(
        b"EPSG::2180", b"EPSG::3857").replace(
        b"<TopLeftCorner>850000 100000</TopLeftCorner>",
        b"<TopLeftCorner>100000 850000</TopLeftCorner>")

    def download(url, size):
        return swapped_caps if "GetCapabilities" in url else _jpeg()

    monkeypatch.setattr(underlay_wms, "_download", download)
    underlay_wms._wmts_capabilities.cache_clear()
    underlay_wms._wmts_layer_info.cache_clear()
    underlay_wms._wmts_layers.cache_clear()
    underlay_wms.clear_cache()
    data = underlay_wms._wmts_image(
        "standard_wmts", "Raster", 3857,
        underlay_wms.WMSBounds(847000, 101000, 849000, 104000), 300, 200)
    assert Image.open(BytesIO(data)).size == (300, 200)


@pytest.mark.parametrize("width,height,tile_width,tile_height", [
    (512, 512, 256, 256),
    (1024, 512, 256, 256),
    (512, 256, 256, 128),
])
def test_wmts_preserves_north_south_and_east_west_orientation(
        monkeypatch, width, height, tile_width, tile_height):
    """Różne kolory kafli wykrywają błędne osie, czego sam rozmiar nie sprawdza."""
    caps = CAPABILITIES.replace(
        b"<ScaleDenominator>10000</ScaleDenominator>",
        b"<ScaleDenominator>3571.4285714285716</ScaleDenominator>").replace(
        b"<TileWidth>512</TileWidth>",
        f"<TileWidth>{tile_width}</TileWidth>".encode()).replace(
        b"<TileHeight>512</TileHeight>",
        f"<TileHeight>{tile_height}</TileHeight>".encode())
    colors = {(0, 0): (220, 30, 30), (0, 1): (30, 210, 30),
              (1, 0): (30, 30, 220), (1, 1): (220, 210, 30)}
    seen = []

    def download(url, size):
        if "GetCapabilities" in url:
            return caps
        params = parse_qs(urlsplit(url).query)
        row, col = int(params["TILEROW"][0]), int(params["TILECOL"][0])
        seen.append((row, col))
        image = Image.new("RGB", (tile_width, tile_height),
                          colors[row % 2, col % 2])
        buffer = BytesIO()
        image.save(buffer, "JPEG", quality=95)
        return buffer.getvalue()

    monkeypatch.setattr(underlay_wms, "_download", download)
    for name in ("_wmts_capabilities", "_wmts_layer_info", "_wmts_layers"):
        getattr(underlay_wms, name).cache_clear()
    underlay_wms.clear_cache()
    data = underlay_wms._wmts_image(
        "standard_wmts", "Raster", 2180,
        underlay_wms.WMSBounds(850000 - height, 100000, 850000, 100000 + width),
        width, height)
    image = Image.open(BytesIO(data)).convert("RGB")
    assert image.size == (width, height)
    assert set(seen) == {(row, col) for row in range(height // tile_height)
                         for col in range(width // tile_width)}
    for row, col in seen:
        actual = image.getpixel((col * tile_width + tile_width // 2,
                                 row * tile_height + tile_height // 2))
        expected = colors[row % 2, col % 2]
        assert max(abs(a - e) for a, e in zip(actual, expected)) < 12


def test_wide_view_uses_screen_resolution_without_excess_tiles(monkeypatch):
    """1600×900 m na 1600×900 px wymaga 1 m/px, nie 0,28125 m/px."""
    levels = tuple(wmts_service.TileMatrix(
        f"r{resolution:g}", resolution / 0.00028, (850000, 100000),
        512, 512, 10000, 10000) for resolution in (0.25, 0.5, 1.0, 2.0))
    matrix_set = wmts_service.TileMatrixSet("EPSG:2180", "EPSG:2180", levels)
    published = wmts_service.WmtsLayer(
        "Raster", "Orto", ("default",), ("image/jpeg",), ("EPSG:2180",))
    monkeypatch.setattr(underlay_wms, "_wmts_capabilities", lambda preset: (matrix_set,))
    monkeypatch.setattr(underlay_wms, "_wmts_layer_info", lambda preset: (published,))
    underlay_wms._tile_cache_clear()
    seen = []
    tile = _jpeg()

    def download(url, size):
        seen.append(parse_qs(urlsplit(url).query))
        return tile

    monkeypatch.setattr(underlay_wms, "_download", download)
    data = underlay_wms._wmts_image(
        "standard_wmts", "Raster", 2180,
        underlay_wms.WMSBounds(500000, 400000, 500900, 401600), 1600, 900)
    assert Image.open(BytesIO(data)).size == (1600, 900)
    assert {params["TILEMATRIX"][0] for params in seen} == {"r1"}
    assert len(seen) == 15


def test_temporary_xml_error_does_not_poison_the_tile_cache(monkeypatch):
    level = wmts_service.TileMatrix(
        "r1", 1.0 / 0.00028, (850000, 100000), 512, 512, 2, 2)
    matrix_set = wmts_service.TileMatrixSet("EPSG:2180", "EPSG:2180", (level,))
    published = wmts_service.WmtsLayer(
        "Raster", "Orto", ("default",), ("image/jpeg",), ("EPSG:2180",))
    monkeypatch.setattr(underlay_wms, "_wmts_capabilities", lambda preset: (matrix_set,))
    monkeypatch.setattr(underlay_wms, "_wmts_layer_info", lambda preset: (published,))
    underlay_wms._tile_cache_clear()
    attempts = []
    tile = _jpeg()

    def download(url, size):
        attempts.append(url)
        if len(attempts) == 1:
            return (b"<ExceptionReport><Exception><ExceptionText>TemporaryError"
                    b"</ExceptionText></Exception></ExceptionReport>")
        return tile

    monkeypatch.setattr(underlay_wms, "_download", download)
    args = ("standard_wmts", "Raster", 2180,
            underlay_wms.WMSBounds(849488, 100000, 850000, 100512), 512, 512)
    with pytest.raises(ValueError, match="TemporaryError"):
        underlay_wms._wmts_image(*args)
    key = ("standard_wmts", "Raster", "EPSG:2180", "r1", 0, 0)
    assert underlay_wms._tile_cache_get(key) is None
    image = underlay_wms._wmts_image(*args)
    assert Image.open(BytesIO(image)).size == (512, 512)
    assert underlay_wms._tile_cache_get(key) == tile
    assert len(attempts) == 2
