"""Opt-in v20 appearance: preserve the stable UI and MAP data semantics."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app

ROOT = Path(__file__).resolve().parents[1] / "geostudio" / "web_app" / "static"
NEXT = ROOT / "next" / "index.html"


class _IDs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=[]
    def handle_starttag(self, tag, attrs):
        for key,value in attrs:
            if key == "id":
                self.ids.append(value)


def test_next_route_is_opt_in_and_stable_root_is_unchanged():
    app=create_app()
    with TestClient(app) as client:
        current=client.get("/")
        preview=client.get("/next")
        assert current.status_code == preview.status_code == 200
        assert 'id="map-canvas"' in current.text
        assert 'id="map"' in preview.text
        assert 'id="setSharedNodes"' in preview.text
        assert 'href="/"' in preview.text
        assert 'href="/classic"' not in preview.text
        assert "__GEOSTUDIO_LOCAL_TOKEN__" not in preview.text
        assert app.state.api_token in preview.text
        assert "unsafe-inline" not in current.headers["content-security-policy"]
        assert "unsafe-inline" in preview.headers["content-security-policy"]
        assert "connect-src 'self'" in preview.headers["content-security-policy"]
        api=client.get("/api/map")
        assert api.status_code==403


def test_next_document_ids_js_syntax_and_regression_guards(tmp_path):
    source=NEXT.read_text("utf-8")
    ids=_IDs()
    ids.feed(source)
    assert len(ids.ids)==len(set(ids.ids))
    assert source.count('id="gcpFit"')==1
    assert source.count('id="gcpFitPreview"')==1
    assert "async function loadFeatures()" in source
    assert "offset:String(offset)" in source
    assert "scheduleGeometry()" in source
    assert "state.loadedBounds = region;" in source
    assert "state.sharedNodes" in source
    assert "shared: state.sharedNodes" in source
    assert "hiddenForestClasses: [...state.hiddenForestClasses]" in source
    assert "visibleLayers:" in source
    assert "state.hiddenForestClasses.clear();" in source
    assert "state.mapBackground" in source
    assert "persistAppearance()" in source
    assert "await loadMeta(true);" in source
    assert "state.view = null;" in source
    assert "message.textContent = String(text)" in source
    assert "window.confirm(`Usunąć ${n}" not in source
    assert "const t = el('div', 'toast', (icon" not in source
    code=re.search(r"<script>(.*?)</script>",source,re.S)
    assert code
    node=shutil.which("node")
    if node:
        js=tmp_path/"next-check.js"
        js.write_text(code.group(1),"utf-8")
        result=subprocess.run([node,"--check",str(js)],
                              capture_output=True,text=True,timeout=15)
        assert result.returncode==0,result.stdout+result.stderr


def test_hidden_forest_class_is_excluded_from_vector_pdf(monkeypatch):
    raw=(MapBuilder(ext=(5000,0,0,150,150))
        .object("5230","F-1",{"A1":"LsV","A2":"LsV"},
                [(0,0),(10,0),(10,10),(0,10)])
        .object("5220","F-2",{"A1":"Ls","A2":"LsVI"},
                [(20,0),(30,0),(30,10),(20,10)])
        .object("5230","R-1",{"A1":"R","A2":"RV"},
                [(40,0),(50,0),(50,10),(40,10)])
        .build())
    ws=PreviewWorkspace()
    metadata=ws.load_map(raw,"forests.MAP")
    assert metadata["forestClasses"]=={"LsV":1,"LsVI":1}
    captured=[]
    def fake_renderer(features,options):
        captured.extend(features)
        return b"%PDF-stub"
    monkeypatch.setattr(
        "geostudio.web_app.print_layout.render_vector_pdf",fake_renderer)
    token=ws.editing_status()["documentToken"]
    options={
        "bounds":metadata["bounds"],"denominator":5000,"paper":"auto",
        "visibleLayers":["Użytki Leśne","Użytki"],
        "hiddenForestClasses":["LsVI"],
        "hiddenLandUses":["rv"],
    }
    _,content=ws.export_vector_pdf(token,options)
    assert content==b"%PDF-stub"
    assert [f["grade"] for f in captured]==["LsV"]
    assert ws.export_copy(token)[1]==raw
    with pytest.raises(ValueError,match="leśnych"):
        ws.export_vector_pdf(token,{**options,"hiddenForestClasses":[123]})
