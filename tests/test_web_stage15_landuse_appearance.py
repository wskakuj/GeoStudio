"""Stage 15 — land-use A2 filters and independent application/map appearance."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace


def fixture_map():
    return (MapBuilder(ext=(5000,-100,-100,160,160))
        # A1 is deliberately broader than A2. Two distinct A2 grades
        # must not be accidentally merged by their shared A1 category.
        .object("5220","R1",{"A1":"R","A2":"RV"},[(0,0),(0,5),(5,5),(5,0)])
        .object("5220","R2",{"A1":"R","A2":"rV"},[(10,0),(10,5),(15,5),(15,0)])
        .object("5230","PS",{"A1":"Ps","A2":"PsIV"},[(20,0),(20,5),(25,5),(25,0)])
        .object("5230","RVI",{"A1":"R","A2":"RVI"},[(30,0),(30,5),(35,5),(35,0)])
        .object("5230","LS",{"A1":"LsV","A2":"LsV"},[(40,0),(40,5),(45,5),(45,0)])
        .object("5216","PARCEL",{"A2":"11/4"},[(50,0),(50,5),(55,5),(55,0)])
        .build())


def test_land_use_classes_come_from_a2_bonitation_values_not_a1():
    ws = PreviewWorkspace()
    original=fixture_map()
    metadata=ws.load_map(original,"test.MAP")
    uses={item["key"]:item for item in metadata["landUseClasses"]}
    assert uses == {
        "rv":{"key":"rv","label":"RV","count":2},
        "psiv":{"key":"psiv","label":"PsIV","count":1},
        "rvi":{"key":"rvi","label":"RVI","count":1},
    }
    assert metadata["forestClasses"]["LsV"]==1
    features=ws.viewport(tuple(metadata["bounds"]))["features"]
    assert sum(f["layer"]=="Użytki" for f in features)==4
    assert sum(f["layer"]=="Użytki Leśne" for f in features)==1
    assert sorted(f["landUse"] for f in features if f["layer"]=="Użytki") == [
        "psiv", "rv", "rv", "rvi"
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
      "hiddenLandUses":["rv"],
    }
    _, content=ws.export_vector_pdf(token,options)
    assert content == b"%PDF-STUB"
    assert sorted(f["landUse"] for f in captured if f["layer"]=="Użytki") == [
        "psiv","rvi"
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
    assert 'KLASY BONITACYJNE A2' in js
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
 hiddenLandUses:new Set(['rv']),hiddenGrades:new Set(['LsV'])
};
const visible=new Function('state',source.slice(a,b)+'return isVisible;')(state);
assert.equal(visible({layer:'Użytki',landUse:'rv',grade:null}),false);
assert.equal(visible({layer:'Użytki',landUse:'psiv',grade:null}),true);
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


def test_native_appearance_preference_survives_map_open_and_restart(tmp_path):
    from geostudio.web_app.native_picker import (
        read_appearance_preference,save_appearance_preference,
        save_last_map_directory,read_last_map_directory,
    )
    settings=tmp_path/"GeoStudio2"/"preferences.json"
    maps=tmp_path/"mapy"
    maps.mkdir()
    assert read_appearance_preference(settings)=={
        "theme":"dark","mapBackground":"#FFFFFF"
    }
    assert save_appearance_preference(settings,"light","#e5e7eb")=={
        "theme":"light","mapBackground":"#E5E7EB"
    }
    save_last_map_directory(settings,maps)
    assert read_appearance_preference(settings)=={
        "theme":"light","mapBackground":"#E5E7EB"
    }
    assert read_last_map_directory(settings)==str(maps)
    save_appearance_preference(settings,"dark","#ffffff")
    assert read_last_map_directory(settings)==str(maps)
    with pytest.raises(ValueError,match="kolor"):
        save_appearance_preference(settings,"light","rgb(1,2,3)")


def test_appearance_api_stays_local_authenticated_and_does_not_touch_map(
        tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from geostudio.web_app.server import create_app
    prefs=tmp_path/"prefs.json"
    monkeypatch.setattr("geostudio.web_app.server.preference_file",lambda:prefs)
    ws=PreviewWorkspace()
    original=fixture_map()
    ws.load_map(original,"untouched.MAP")
    app=create_app(ws)
    with TestClient(app) as client:
        token={"X-GeoStudio-Token":app.state.api_token}
        assert client.get("/api/appearance").status_code==403
        assert client.post("/api/appearance",
            json={"theme":"light","mapBackground":"#f1f4f6"}).status_code==403
        result=client.post("/api/appearance",headers=token,
            json={"theme":"light","mapBackground":"#f1f4f6"})
        assert result.status_code==200,result.text
        assert result.json()["mapBackground"]=="#F1F4F6"
        assert client.get("/api/appearance",headers=token).json()=={
            "theme":"light","mapBackground":"#F1F4F6"
        }
        assert client.post("/api/appearance",headers=token,
            json={"theme":"light","mapBackground":"red"}).status_code==400
    doc=ws.editing_status()["documentToken"]
    assert ws.export_copy(doc)[1]==original
