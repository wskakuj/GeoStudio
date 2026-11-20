"""Stage 12A: safe WMS proxy, explicit CRS and Canvas underlay smoke tests."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.web_app import underlay_wms
from geostudio.web_app.server import create_app
from geostudio.web_app.data import PreviewWorkspace


CAPABILITIES = b"""<?xml version="1.0" encoding="utf-8"?>
<WMS_Capabilities version="1.3.0">
 <Capability><Layer><Title>Ortofotomapa</Title>
  <CRS>EPSG:2180</CRS><CRS>EPSG:2177</CRS>
  <Layer><Name>ortho</Name><Title>Ortofotomapa PL</Title></Layer>
 </Layer></Capability>
</WMS_Capabilities>"""
PNG = b"\x89PNG\r\n\x1a\n" + b"test-image"


@pytest.fixture
def stubbed_wms(monkeypatch):
    queries = []
    def download(url, limit):
        queries.append((url, limit))
        return CAPABILITIES if "GetCapabilities" in url else PNG
    monkeypatch.setattr(underlay_wms, "_download", download)
    underlay_wms.layers_for.cache_clear()
    yield queries
    underlay_wms.layers_for.cache_clear()


def test_layers_and_world_to_1_1_1_bbox(stubbed_wms):
    data = underlay_wms.list_layers("standard")
    assert data["layers"] == [{"id":"ortho","title":"Ortofotomapa PL",
                                "epsg":[2177,2180]}]
    # Canvas: world horizontal=easting, vertical=-northing.
    image = underlay_wms.map_png("standard", "ortho", 2180,
                                 700000, -515000, 700600, -514500, 800, 600)
    assert image == PNG
    url = stubbed_wms[-1][0]
    q = parse_qs(urlsplit(url).query)
    assert q["BBOX"] == ["700000,514500,700600,515000"]
    assert q["SRS"] == ["EPSG:2180"]
    assert q["VERSION"] == ["1.1.1"]
    assert q["FORMAT"] == ["image/png"]
    assert urlsplit(url).hostname == "mapy.geoportal.gov.pl"


def test_reject_unsupported_sources_epsg_layers_and_non_images(stubbed_wms,monkeypatch):
    with pytest.raises(ValueError, match="źródło"):
        underlay_wms.list_layers("http://localhost/")
    for kwargs in (
        {"epsg":3857}, {"layer":"other"}, {"width":99999},
        {"xmin":float("nan")}, {"ymax":-515000}
    ):
        spec={"preset":"standard","layer":"ortho","epsg":2180,
              "xmin":700000,"ymin":-515000,"xmax":700600,"ymax":-514500,
              "width":800,"height":600}
        spec.update(kwargs)
        with pytest.raises(ValueError):
            underlay_wms.map_png(**spec)
    monkeypatch.setattr(underlay_wms, "_download",
                        lambda url, limit: b"<ServiceException>blocked</ServiceException>")
    with pytest.raises(ValueError, match="inne niż"):
        underlay_wms.map_png("standard","ortho",2180,700000,-515000,
                             700600,-514500,800,600)


def test_wms_http_requires_token_and_loaded_map(stubbed_wms):
    ws=PreviewWorkspace()
    app=create_app(ws)
    with TestClient(app) as client:
        query="/api/underlay/wms/layers?preset=standard"
        assert client.get(query).status_code==403
        headers={"X-GeoStudio-Token":app.state.api_token}
        ok=client.get(query,headers=headers)
        assert ok.status_code==200,ok.text
        params={"preset":"standard","layer":"ortho","epsg":2180,
                "xmin":700000,"ymin":-515000,"xmax":700600,
                "ymax":-514500,"width":800,"height":600}
        assert client.get("/api/underlay/wms/map",headers=headers,
                          params=params).status_code==409
        ws.load_map(MapBuilder().object("5216","P",{"A2":"11/4"},
           [(0,0),(0,20),(20,20),(20,0)]).build(),"map.MAP")
        response=client.get("/api/underlay/wms/map",headers=headers,params=params)
        assert response.status_code==200,response.text
        assert response.content == PNG
        assert response.headers["content-type"]=="image/png"
        assert client.get("/api/underlay/wms/map",headers=headers,
          params={**params,"epsg":3857}).status_code==400
        assert client.get("/api/underlay/wms/layers",headers=headers,
          params={"preset":"attacker"}).status_code==400


def test_underlay_is_behind_vectors_and_not_in_export():
    static=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"
    js=(static/"map.js").read_text("utf-8")
    html=(static/"index.html").read_text("utf-8")
    assert 'id="tool-underlay"' in html
    assert 'id="underlay-epsg"' in html
    assert 'id="underlay-opacity"' in html
    assert 'paintUnderlay();paintRaster();drawGrid();' in js
    assert 'ctx.drawImage(underlay.image,top.x,top.y' in js
    assert 'scheduleUnderlayRefresh();' in js
    assert 'if(pass==="fills")for(const item of visible)renderFill(item);' in js
    assert 'state.exporting=true;' in js
    assert 'state.hasVisibleUnderlay&&!state.exporting?.40:1' in js
    assert '"X-GeoStudio-Token":token' in js


def test_kieg_classic_source_preset_is_explicitly_allowlisted(stubbed_wms):
    """Classic WMS dialog also offered GUGiK KIEG parcel boundaries/numbers."""
    data=underlay_wms.list_layers("kieg")
    assert data["layers"][0]["id"]=="ortho"  # Fixture simulates capabilities.
    url=stubbed_wms[-1][0]
    assert urlsplit(url).hostname=="integracja.gugik.gov.pl"
    assert "/cgi-bin/KrajowaIntegracjaEwidencjiGruntow" in url
    assert "kieg" in underlay_wms.PRESETS
    assert underlay_wms.PRESETS["kieg"][0].startswith("Działki")
