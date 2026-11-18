"""WMS query, axis orientation and official Google reference regression tests."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from geostudio.wms_service import (
    WMSBounds, capabilities_url, getmap_url, google_maps_reference_url,
    parse_capabilities,
)


CAPABILITIES = b"""<?xml version="1.0"?>
<WMS_Capabilities xmlns="http://www.opengis.net/wms" version="1.3.0">
  <Capability><Layer><Title>Layers</Title><CRS>EPSG:2180</CRS>
    <Layer><Name>ortofoto</Name><Title>Ortofotomapa</Title>
      <Attribution><Title>GUGiK</Title></Attribution></Layer>
    <Layer><Name>dzialki</Name><Title>Dzialki</Title><CRS>EPSG:3857</CRS></Layer>
  </Layer></Capability>
</WMS_Capabilities>"""


def test_parse_capabilities_layers_and_inherited_crs():
    layers = parse_capabilities(CAPABILITIES)
    assert [layer.name for layer in layers] == ["ortofoto", "dzialki"]
    assert layers[0].title == "Ortofotomapa"
    assert layers[0].crs == ("EPSG:2180",)
    assert layers[0].attribution == "GUGiK"
    assert layers[1].crs == ("EPSG:2180", "EPSG:3857")


def test_wms_projected_bbox_flips_geomap_north_east_order():
    bounds = WMSBounds(5_151_000, 667_000, 5_152_000, 668_000)
    url = getmap_url("https://maps.example/wms?SERVICE=WMS&token=x",
                     "orto", "EPSG:2180", bounds, 1000, 1000)
    query = parse_qs(urlparse(url).query)
    assert query["BBOX"] == ["667000,5151000,668000,5152000"]
    assert query["CRS"] == ["EPSG:2180"]
    assert query["TRANSPARENT"] == ["TRUE"]
    assert query["FORMAT"] == ["image/png"]
    assert query["token"] == ["x"]


def test_wms_4326_axis_order_and_wms_111():
    box = WMSBounds(50, 19, 52, 21)
    query_130 = parse_qs(urlparse(
        getmap_url("https://maps.example/wms", "L", "EPSG:4326", box,
                   512, 512)).query)
    assert query_130["BBOX"] == ["50,19,52,21"]
    assert query_130["CRS"] == ["EPSG:4326"]
    query_111 = parse_qs(urlparse(
        getmap_url("https://maps.example/wms", "L", "EPSG:4326", box,
                   512, 512, version="1.1.1")).query)
    assert query_111["BBOX"] == ["19,50,21,52"]
    assert "SRS" in query_111 and "CRS" not in query_111


def test_getcapabilities_url_retains_only_nonoperation_params():
    url = capabilities_url(
        "https://maps.example/wms?SERVICE=WMS&REQUEST=GetMap&apikey=hello")
    query = parse_qs(urlparse(url).query)
    assert query["REQUEST"] == ["GetCapabilities"]
    assert query["SERVICE"] == ["WMS"]
    assert query["apikey"] == ["hello"]


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://", "", "ftp://example.com"])
def test_reject_non_http_wms(url):
    with pytest.raises(ValueError):
        capabilities_url(url)


@pytest.mark.parametrize("size", [(1, 500), (500, 10), (5000, 500), (500, 9999)])
def test_reject_invalid_image_dimensions(size):
    with pytest.raises(ValueError):
        getmap_url("https://maps.example/wms", "x", "EPSG:2180",
                   WMSBounds(10, 20, 30, 40), *size)


def test_google_reference_uses_official_maps_and_verified_epsg():
    from pyproj import Transformer
    east, north = Transformer.from_crs(
        "EPSG:4326", "EPSG:2180", always_xy=True).transform(21.011, 52.229)
    url = google_maps_reference_url(north, east, 2180)
    assert url.startswith("https://www.google.com/maps/@52.229")
    assert ",21.011" in url
    with pytest.raises(ValueError):
        google_maps_reference_url(north, east, 12345)
