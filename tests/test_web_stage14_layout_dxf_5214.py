"""Stage 14A: large-format vector PDF, editable sheet furniture and CAD DXF."""
from __future__ import annotations

import io
import re

import ezdxf
import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.print_layout import render_vector_pdf, _setup
from geostudio.web_app.server import create_app


def fixture_map() -> bytes:
    return (MapBuilder(ext=(5000,-100,-100,200,200))
      .object("5310","B1",{"A1":"m","A2":"II"},
              [(0,0),(0,10),(10,10),(10,0)])
      .object("5214","PRECINCT",{},
              [(20,20),(25,30),(30,40)],closed=False)
      .object("5216","PARCEL",{"A2":"5/2"},
              [(55,50),(55,65),(70,65),(70,50)])
      .build())


def options(paper="A0", denominator=5000):
    return {
      "bounds":[-80.,-100.,100.,80.],
      "denominator":denominator,"paper":paper,"orientation":"landscape",
      "title":"Mapa obrębu — etap 14",
      "frame":True,"frameColor":"#263C4D","frameWidthMm":0.3,
      "north":True,"scaleBar":True,"showLegend":True,
      "legendRows":[
        {"name":"Linia obrębu","color":"#705A83"},
        {"name":"Działki","color":"#426A88"}],
      "tableRows":[{"label":"Obręb","value":"Testowy"},
                   {"label":"Opracował","value":"GeoStudio"}]
    }


def test_5214_is_an_administrative_line_and_not_a_polygon_fill():
    ws=PreviewWorkspace()
    ws.load_map(fixture_map(),"precinct.MAP")
    layer=next(x for x in ws.metadata()["layers"] if x["name"]=="Linia obrębu")
    assert layer["count"]==1
    obj=next(f for f in ws.viewport((-100,-100,200,200))["features"]
             if f["code"]=="5214")
    assert obj["closed"] is False
    assert obj["style"]["hasFill"] is False
    assert obj["style"]["opacity"]==0

    ws.set_cartographic_library("regula.CDF",
        b"5214 250 90 40 5 25 20 60 1.4\r\n")
    same=next(f for f in ws.viewport((-100,-100,200,200))["features"]
             if f["code"]=="5214")
    assert same["style"]["hasFill"] is False


def test_pdf_a0_vector_geometry_and_editable_furniture():
    ws=PreviewWorkspace()
    original=fixture_map()
    ws.load_map(original,"obręb.MAP")
    token=ws.editing_status()["documentToken"]
    name,pdf=ws.export_vector_pdf(token,options())
    assert name.endswith(".pdf")
    assert pdf.startswith(b"%PDF-")
    assert len(pdf)>2000
    match=re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)",pdf)
    assert match is not None
    width,height=map(float,match.groups())
    # A0 horizontal = 1189 x 841 mm; 72 points per inch.
    assert width==pytest.approx(1189*72/25.4,abs=.3)
    assert height==pytest.approx(841*72/25.4,abs=.3)
    assert ws.export_copy(token)[1]==original


def test_pdf_rejects_wrong_paper_scale_legend_and_frame():
    with pytest.raises(ValueError,match="mieści"):
        _setup(options(paper="A4",denominator=50))
    bad=options();bad["legendRows"]=[{"name":"Bad","color":"red"}]
    with pytest.raises(ValueError,match="Legenda"):
        _setup(bad)
    bad=options();bad["frameWidthMm"]=20
    with pytest.raises(ValueError,match="ramki"):
        _setup(bad)
    bad=options();bad["bounds"]=[0,0,0,10]
    with pytest.raises(ValueError,match="granice"):
        _setup(bad)


def test_pdf_endpoint_auth_and_native_buffer():
    app=create_app()
    with TestClient(app) as c:
        h={"X-GeoStudio-Token":app.state.api_token}
        opened=c.post("/api/map",headers={**h,"X-Map-Name":"test.MAP"},
                      content=fixture_map())
        assert opened.status_code==200,opened.text
        doc=opened.json()
        payload={"documentToken":doc["documentToken"],"options":options()}
        assert c.post("/api/export/pdf",json=payload).status_code==403
        result=c.post("/api/export/pdf",headers=h,json=payload)
        assert result.status_code==200,result.text[:150]
        assert result.headers["content-type"]=="application/pdf"
        assert result.content.startswith(b"%PDF-")
        payload["documentToken"]="stale-token"
        assert c.post("/api/export/pdf",headers=h,json=payload).status_code==409
        invalid={"documentToken":doc["documentToken"],
                 "options":options(paper="A4",denominator=50)}
        assert c.post("/api/export/pdf",headers=h,json=invalid).status_code==400
        status=app.state.workspace.editing_status()
        ticket=app.state.workspace.store_generated_export(
            status["documentToken"],status["revision"],"mapa.pdf","pdf",
            result.content)
        assert app.state.workspace.generated_export(ticket)[1]=="pdf"


def test_dxf_preserves_5214_and_separates_a1_a2_text_layers_with_native_xy():
    ws=PreviewWorkspace();ws.load_map(fixture_map(),"test.MAP")
    ws.set_cartographic_library("filled.CDF",
        b"5310 30 120 180 3 180 90 20 2\r\n")
    token=ws.editing_status()["documentToken"]
    _,payload=ws.export_dxf(token)
    cad=ezdxf.read(io.StringIO(payload.decode("utf-8")))
    assert cad.header["$INSUNITS"]==6
    msp=cad.modelspace()
    precinct=list(msp.query('LWPOLYLINE[layer=="G5214"]'))
    assert len(precinct)==1
    assert not precinct[0].closed
    assert "G5214" in cad.layers
    labels=list(msp.query("TEXT"))
    assert any(x.dxf.layer=="G5310_A1" and x.dxf.text=="m" for x in labels)
    assert any(x.dxf.layer=="G5310_A2" and x.dxf.text=="II" for x in labels)
    assert len(list(msp.query("HATCH")))>0
    assert precinct[0].has_xdata("GEOSTUDIO")


def test_browser_pdf_controls_a1_and_delete_are_explicit():
    from pathlib import Path
    assets=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"
    html=(assets/"index.html").read_text("utf-8")
    js=(assets/"map.js").read_text("utf-8")
    for identifier in ("layout-paper","layout-orientation","layout-legend-rows",
       "layout-table-rows","layout-frame-color","layout-frame-width"):
        assert f'id="{identifier}"' in html
    assert '<option value="pdf">PDF' in html
    assert '<input id="create-a1" type="text" maxlength="512" placeholder="Np. b" autofocus>' in html
    assert 'requestAnimationFrame(()=>{' in js
    block=js[js.index("  async function deleteObjects() {"):
             js.index("  function finishDrawPolygon()")]
    assert "window.confirm" not in block
    assert "window.prompt" not in block
    assert 'selectedObjectIds().length' in js
    assert "if(ev.key===\"Delete\"" in js
    assert 'pdfLayoutOptions()' in js
    assert '"/api/export/pdf"' in js
