"""Stage 15 — land-use A1 filters and independent application/map appearance."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace


def fixture_map():
    return (MapBuilder(ext=(5000,-100,-100,160,160))
        .object("5220","R1",{"A1":"R"},[(0,0),(0,5),(5,5),(5,0)])
        .object("5220","R2",{"A1":"r"},[(10,0),(10,5),(15,5),(15,0)])
        .object("5230","PS",{"A1":"Ps"},[(20,0),(20,5),(25,5),(25,0)])
        .object("5230","DR",{"A1":"dr"},[(30,0),(30,5),(35,5),(35,0)])
        .object("5230","LS",{"A1":"LsV"},[(40,0),(40,5),(45,5),(45,0)])
        .object("5216","PARCEL",{"A2":"11/4"},[(50,0),(50,5),(55,5),(55,0)])
        .build())


def test_land_use_classes_come_from_actual_a1_values_not_fixed_catalog():
    ws = PreviewWorkspace()
    original=fixture_map()
    metadata=ws.load_map(original,"test.MAP")
    uses={item["key"]:item for item in metadata["landUseClasses"]}
    assert uses == {
        "r":{"key":"r","label":"R","count":2},
        "ps":{"key":"ps","label":"Ps","count":1},
        "dr":{"key":"dr","label":"dr","count":1},
    }
    assert metadata["forestClasses"]["LsV"]==1
    features=ws.viewport(tuple(metadata["bounds"]))["features"]
    assert sum(f["layer"]=="Użytki" for f in features)==4
    assert sum(f["layer"]=="Użytki Leśne" for f in features)==1
    assert sorted(f["landUse"] for f in features if f["layer"]=="Użytki") == [
        "dr", "ps", "r", "r"
    ]
    assert ws.export_copy(ws.editing_status()["documentToken"])[1] == original


def test_pdf_respects_individual_hidden_uses_without_modifying_geometry(monkeypatch):
    ws=PreviewWorkspace()
    raw=fixture_map()
    meta=ws.load_map(raw,"test.MAP")
    token=ws.editing_status()["documentToken"]
    captured=[]
    def render(features,options):
        captured.extend(features)
        return b"%PDF-STUB"
    monkeypatch.setattr("geostudio.web_app.print_layout.render_vector_pdf",render)
    options={
      "bounds":meta["bounds"],"denominator":5000,"paper":"auto",
      "showLegend":False,"visibleLayers":["Użytki","Użytki Leśne"],
      "hiddenLandUses":["r"],
    }
    _, content=ws.export_vector_pdf(token,options)
    assert content == b"%PDF-STUB"
    assert sorted(f["landUse"] for f in captured if f["layer"]=="Użytki") == [
        "dr","ps"
    ]
    assert any(f["layer"]=="Użytki Leśne" for f in captured)
    assert ws.export_copy(token)[1] == raw
    with pytest.raises(ValueError,match="klas użytków"):
        ws.export_vector_pdf(token,{**options,"hiddenLandUses":[34]})


def test_dynamic_class_visibility_and_theme_are_independent():
    root=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"
    html=(root/"index.html").read_text("utf-8")
    css=(root/"styles.css").read_text("utf-8")
    js=(root/"map.js").read_text("utf-8")
    assert 'id="map-background-color"' in html
    assert 'id="map-background-menu"' in html
    assert 'id="btn-theme"' in html
    assert 'body[data-theme="light"]' in css
    assert 'body[data-theme="dark"]' in css
    assert 'function changeMapBackground(value)' in js
    assert 'ctx.fillStyle=state.mapBackground;' in js
    assert 'document.body.dataset.theme=state.appTheme;' in js
    assert 'function buildLayer(name,count,filter="")' in js
    assert 'state.hiddenLandUses.has(feature.landUse||"")' in js

    node=shutil.which("node")
    if node is None:
        return
    script=r"""
const assert=require('node:assert/strict');
const fs=require('node:fs');
const source=fs.readFileSync('./map.js','utf8');
const a=source.indexOf('  function isVisible(feature)');
const b=source.indexOf('  function isInView(',a);
assert.ok(a>=0&&b>a);
const state={
 visibleLayers:new Set(['Użytki','Użytki Leśne']),
 hiddenLandUses:new Set(['r']),hiddenGrades:new Set(['LsV'])
};
const visible=new Function('state',source.slice(a,b)+'return isVisible;')(state);
assert.equal(visible({layer:'Użytki',landUse:'r',grade:null}),false);
assert.equal(visible({layer:'Użytki',landUse:'ps',grade:null}),true);
assert.equal(visible({layer:'Użytki Leśne',grade:'LsV'}),false);
assert.equal(visible({layer:'Użytki Leśne',grade:'LsVI'}),true);
state.hiddenLandUses.clear();
assert.equal(visible({layer:'Użytki',landUse:'r',grade:null}),true);
state.visibleLayers.delete('Użytki');
assert.equal(visible({layer:'Użytki',landUse:'r',grade:null}),false);
"""
    result=subprocess.run([node,"-e",script],cwd=root,capture_output=True,
                          text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
