"""Stage 12C: verify PRJ, transform points read-only, never guess EPSG."""
from __future__ import annotations

from pathlib import Path

import pytest
from pyproj import CRS
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.underlay_crs import verified_prj_epsg, convert_point
from geostudio.web_app.server import create_app


def test_verified_prj_is_explicit_authoritative_not_guessed():
    for epsg in (2180,2176,2177,2178,2179):
        wkt=CRS.from_epsg(epsg).to_wkt().encode()
        assert verified_prj_epsg(wkt)==epsg
    with pytest.raises(ValueError):
        verified_prj_epsg(b"epsg:2180")
    with pytest.raises(ValueError):
        verified_prj_epsg(b"")
    with pytest.raises(ValueError):
        verified_prj_epsg(CRS.from_epsg(4326).to_wkt().encode())


def test_control_point_roundtrip_preserves_geodetic_order():
    converted=convert_point(500000.0, 700000.0, 2180, 2177)
    restored=convert_point(converted["x"],converted["y"],2177,2180)
    assert restored["x"]==pytest.approx(500000,abs=.01)
    assert restored["y"]==pytest.approx(700000,abs=.01)
    with pytest.raises(ValueError):
        convert_point(500000,700000,0,2180)


def test_crs_endpoints_authentication_and_map_integrity():
    source=MapBuilder().object("5216","P",{"A2":"77"},
       [(0,0),(0,10),(10,10),(10,0)]).build()
    ws=PreviewWorkspace()
    app=create_app(ws)
    with TestClient(app) as c:
        url="/api/underlay/crs/prj"
        data=CRS.from_epsg(2180).to_wkt().encode()
        assert c.post(url,content=data).status_code==403
        headers={"X-GeoStudio-Token":app.state.api_token}
        assert c.post(url,headers=headers,content=data).status_code==409
        ws.load_map(source,"m.MAP")
        good=c.post(url,headers=headers,content=data)
        assert good.status_code==200,good.text
        assert good.json()["epsg"]==2180
        t=c.get("/api/underlay/crs/point",headers=headers,
                params={"x":500000,"y":700000,"source":2180,"target":2177})
        assert t.status_code==200,t.text
        assert "x" in t.json() and "y" in t.json()
        fail=c.get("/api/underlay/crs/point",headers=headers,
                params={"x":500000,"y":700000,"source":4326,"target":2180})
        assert fail.status_code==400
        assert ws.export_copy(ws.editing_status()["documentToken"])[1]==source


def test_crs_selectors_and_ui_no_crs_guess():
    static=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"
    html=(static/"index.html").read_text("utf-8")
    js=(static/"map.js").read_text("utf-8")
    assert 'id="underlay-prj-file"' in html
    assert 'id="underlay-crs-target"' in html
    assert 'id="underlay-crs-convert"' in html
    assert '<option value="" selected>Wybierz świadomie EPSG…</option>' in html
    assert 'readUnderlayPrj(ev.target.files?.[0])' in js
    assert 'x:String(-state.center.y),y:String(state.center.x)' in js
    assert '"underlay-epsg").value="";' in js
