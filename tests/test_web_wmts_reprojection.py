"""PL-2000 views must stay on WMTS and retain geographic alignment."""
from __future__ import annotations

from io import BytesIO
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image
from pyproj import Transformer

from geostudio.wmts_service import TileMatrix, TileMatrixSet, WmtsLayer
from geostudio.web_app import underlay_wms as wms


@pytest.fixture(autouse=True)
def empty_cache():
    wms.clear_cache()
    yield
    wms.clear_cache()


def install_geographic_tiles(monkeypatch, source_center):
    """Each source pixel encodes its east/north location as a smooth colour."""
    matrix = TileMatrix("1m", 1 / .00028, (850000, 100000), 512, 512, 2000, 2000)
    matrix_set = TileMatrixSet("PL-1992", "EPSG:2180", (matrix,))
    layer = WmtsLayer("ortho", "Ortofoto", ("default",), ("image/png",), ("PL-1992",))
    monkeypatch.setattr(wms, "_wmts_capabilities", lambda _preset: (matrix_set,))
    monkeypatch.setattr(wms, "_wmts_layer_info", lambda _preset: (layer,))
    seen = []

    def colour(east, north):
        return (max(0, min(255, round(128 + (east-source_center[0]) / 4))),
                max(0, min(255, round(128 + (source_center[1]-north) / 4))), 170)

    def download(url, _limit):
        query = parse_qs(urlsplit(url).query)
        assert query["SERVICE"] == ["WMTS"]
        assert query["REQUEST"] == ["GetTile"]
        assert query["TILEMATRIXSET"] == ["PL-1992"]
        row, col = int(query["TILEROW"][0]), int(query["TILECOL"][0])
        seen.append((row, col))
        east = 100000 + col*512
        north = 850000 - row*512
        red = Image.frombytes("L", (512, 1), bytes(
            colour(east+x+.5, north)[0] for x in range(512))).resize((512, 512))
        green = Image.frombytes("L", (1, 512), bytes(
            colour(east, north-y-.5)[1] for y in range(512))).resize((512, 512))
        image = Image.merge("RGB", (red, green, Image.new("L", (512, 512), 170)))
        out = BytesIO()
        image.save(out, "PNG")
        return out.getvalue()

    def no_wms(*_args, **_kwargs):
        pytest.fail("Selecting WMTS in PL-2000 must not trigger a WMS render")

    monkeypatch.setattr(wms, "_download", download)
    monkeypatch.setattr(wms, "_fetch_orto", no_wms)
    return seen, colour


@pytest.mark.parametrize("epsg,longitude", [(2176, 15), (2177, 18), (2178, 21), (2179, 24)])
@pytest.mark.parametrize("width,height", [(320, 240), (960, 160)])
def test_all_pl2000_zones_use_native_tiles_and_keep_positions(
        monkeypatch, epsg, longitude, width, height):
    east, north = Transformer.from_crs(4326, epsg, always_xy=True).transform(longitude, 52)
    to_source = Transformer.from_crs(epsg, 2180, always_xy=True)
    source_center = to_source.transform(east, north)
    seen, colour = install_geographic_tiles(monkeypatch, source_center)
    west, south = east-width/2, north-height/2
    raw, media = wms.map_image("standard_wmts", "ortho", epsg,
                               west, -(south+height), west+width, -south,
                               width, height)
    image = Image.open(BytesIO(raw)).convert("RGB")
    assert media == "image/jpeg"
    assert image.size == (width, height)
    assert 1 <= len(seen) <= 12
    for x in (20, width//2, width-21):
        for y in (20, height//2, height-21):
            e, n = to_source.transform(west+x+.5, south+height-y-.5)
            expected = colour(e, n)
            actual = image.getpixel((x, y))
            # JPEG and bicubic sampling may change a channel by a few units.
            assert max(abs(a-b) for a, b in zip(actual, expected)) <= 6, (
                epsg, (x, y), actual, expected)


def test_native_tile_cache_is_shared_by_1992_and_2000_views(monkeypatch):
    east, north = Transformer.from_crs(4326, 2177, always_xy=True).transform(18, 52)
    source_east, source_north = Transformer.from_crs(2177, 2180, always_xy=True).transform(east, north)
    seen, _ = install_geographic_tiles(monkeypatch, (source_east, source_north))
    wms.map_image("standard_wmts", "ortho", 2180,
                  source_east-512, -source_north-512,
                  source_east+512, -source_north+512, 1024, 1024)
    downloaded = len(seen)
    wms.map_image("standard_wmts", "ortho", 2177,
                  east-128, -north-128, east+128, -north+128, 256, 256)
    assert len(seen) == downloaded


def test_reprojection_uses_only_a_matrix_set_linked_to_the_layer(monkeypatch):
    matrix = TileMatrix("1m", 1 / .00028, (850000, 100000), 512, 512, 2000, 2000)
    monkeypatch.setattr(wms, "_wmts_capabilities", lambda _preset: (
        TileMatrixSet("unlinked", "EPSG:2180", (matrix,)),))
    monkeypatch.setattr(wms, "_wmts_layer_info", lambda _preset: (
        WmtsLayer("ortho", "Ortofoto", ("default",), ("image/jpeg",), ("other",)),))
    monkeypatch.setattr(wms, "_download", lambda *_a: pytest.fail("No linked matrix to request"))
    with pytest.raises(ValueError, match="układu EPSG"):
        wms._wmts_image("standard_wmts", "ortho", 2177,
                         wms.WMSBounds(5700000, 6500000, 5701000, 6501000), 256, 256)
