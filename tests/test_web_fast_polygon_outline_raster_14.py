"""Fast polygon drawing, code-outline presets, 5310 label visibility and independent WMS/JPG.

No user-supplied MAP/raster is included in these tests.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient
import pytest

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app
from geostudio.visual_styles import validated_styles

STATIC=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"


def sample():
    return (MapBuilder()
      .object("5310","B1",{"A1":"b","A2":"II-0.5"},
              [(0,0),(0,15),(15,15),(15,0)])
      .object("5216","P1",{"A2":"7/3"},
              [(40,40),(40,60),(60,60),(60,40)])
      .build())


def auth(ws):
    status=ws.editing_status()
    return {"document_token":status["documentToken"],
            "revision":status["revision"]}


def node_script(script):
    node=shutil.which("node")
    if not node:pytest.skip("Node.js is needed for Canvas behavior tests")
    result=subprocess.run([node,"-e",script],cwd=STATIC,
        capture_output=True,text=True,timeout=25)
    assert result.returncode==0,result.stdout+result.stderr


def test_outline_style_by_code_undo_safe_and_applies_to_new_polygons():
    ws=PreviewWorkspace()
    original=sample();ws.load_map(original,"test.MAP")
    base=ws.outline_settings("5310")
    assert not base["custom"]
    token=auth(ws)["document_token"]
    result=ws.set_outline_settings("5310","#245D8A",2.5,**auth(ws))
    assert result["changed"]
    setting=ws.outline_settings("5310")
    assert setting["custom"] and setting["stroke"]=="#245D8A"
    assert setting["strokeWidth"]==2.5
    assert ws.viewport((-100,-100,100,100))["features"][0]["style"]["stroke"]=="#245D8A"
    assert ws.export_copy(token)[1]==original
    sidecar=json.loads(ws.export_visual_sidecar(original))
    assert sidecar["objects"]["code:5310"]["stroke"]=="#245D8A"
    assert sidecar["objects"]["code:5310"]["stroke_width"]==2.5
    assert validated_styles(sidecar["objects"])["code:5310"]["stroke"]=="#245D8A"

    operation={"action":"create","code":"5310","fields":{"A1":"m"},
       "points":[[100,100],[100,110],[110,110],[110,100]]}
    preview=ws.preview_object_operation(operation,**auth(ws))
    assert preview["canApply"]
    applied=ws.apply_object_operation(
        operation,preview_key=preview["previewKey"],**auth(ws))
    new_id=applied["createdIds"][0]
    new_feature=next(f for f in ws.viewport((-200,-200,200,200))["features"]
                     if f["id"]==new_id)
    assert new_feature["style"]["stroke"]=="#245D8A"
    assert new_feature["style"]["strokeWidth"]==2.5
    ws.set_outline_settings("5310","",0,reset=True,**auth(ws))
    assert not ws.outline_settings("5310")["custom"]


def test_outline_default_for_code_not_yet_on_map():
    ws=PreviewWorkspace()
    ws.load_map((MapBuilder().object("5216","ONLY",{"A2":"1"},
        [(0,0),(0,10),(10,10),(10,0)]).build()),"empty_buildings.MAP")
    original=ws.outline_settings("5310")
    assert original["code"]=="5310"
    assert not original["custom"]
    result=ws.set_outline_settings("5310","#AA3300",4.0,**auth(ws))
    assert result["changed"]
    assert ws.outline_settings("5310")["stroke"]=="#AA3300"
    operation={"action":"create","code":"5310","fields":{"A1":"m"},
      "points":[[100,100],[100,120],[120,120],[120,100]]}
    report=ws.preview_object_operation(operation,**auth(ws))
    applied=ws.apply_object_operation(
        operation,preview_key=report["previewKey"],**auth(ws))
    item=next(f for f in ws.viewport((-150,-150,150,150))["features"]
      if f["id"]==applied["createdIds"][0])
    assert item["style"]["stroke"]=="#AA3300"
    assert item["style"]["strokeWidth"]==4.0


def test_outline_api_guards_input_and_returns_current_style():
    ws=PreviewWorkspace()
    ws.load_map(sample(),"test.MAP")
    app=create_app(ws)
    headers={"X-GeoStudio-Token":app.state.api_token}
    with TestClient(app) as c:
        assert c.get("/api/cartography/outline",params={"code":"5310"}).status_code==403
        get=c.get("/api/cartography/outline",params={"code":"5310"},headers=headers)
        assert get.status_code==200 and get.json()["code"]=="5310"
        payload={"code":"5310","stroke":"#1234AB","strokeWidth":3.5,
                 "documentToken":auth(ws)["document_token"],
                 "revision":auth(ws)["revision"]}
        response=c.post("/api/cartography/outline",headers=headers,json=payload)
        assert response.status_code==200,response.text
        assert ws.outline_settings("5310")["strokeWidth"]==3.5
        wrong={**payload,"revision":0}
        assert c.post("/api/cartography/outline",headers=headers,json=wrong).status_code==409
        invalid={**payload,"revision":auth(ws)["revision"],"stroke":"red"}
        assert c.post("/api/cartography/outline",headers=headers,json=invalid).status_code==400
        invalid["stroke"]="#FFFFFF";invalid["strokeWidth"]=150
        assert c.post("/api/cartography/outline",headers=headers,json=invalid).status_code==400


def test_draw_click_adds_point_immediately_without_waiting_for_pointerup():
    node_script(r"""
const fs=require('fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('map.js','utf8');
const a=src.indexOf('  function appendDrawingPoint(');
const b=src.indexOf('  function updateDrawingHover(',a);
assert.ok(a>=0&&b>a);
const status={textContent:''};
const state={meta:{},editBusy:false,tool:'draw',drawPoints:[],drawSnap:null};
let drawCount=0,finished=0,alerts=0;
let close=false;
const fn=new Function('state','screenToWorld','drawingSnapAt',
  'finishDrawPolygon','$','requestDraw','inform',
  src.slice(a,b)+'return appendDrawingPoint;')(
  state,(x,y)=>({x,y}),world=>({point:world,kind:close?'start':null}),
  ()=>{finished++;},()=>status,()=>{drawCount++;},()=>{alerts++;});
for(const [x,y] of [[10,10],[20,10],[20,20]])
  fn({altKey:false},{x,y});
assert.equal(state.drawPoints.length,3);
assert.equal(drawCount,3);
assert.equal(alerts,0);
assert.match(status.textContent,/3 punkt/);
close=true;fn({altKey:false},{x:10,y:10});
assert.equal(finished,1);
assert.equal(state.drawPoints.length,3);
assert.ok(!src.slice(src.indexOf('  canvas.addEventListener("pointerup", ev=>{'),
                            src.indexOf('  canvas.addEventListener("dblclick",ev=>{'))
        .includes('appendDrawingPoint(ev,p)'));
assert.ok(src.includes('appendDrawingPoint(ev,p);'));
""")


def test_code_wide_preset_editor_and_enter_shortcut_are_visible():
    html=(STATIC/"index.html").read_text(encoding="utf-8")
    js=(STATIC/"map.js").read_text(encoding="utf-8")
    for name in ["tool-outline-style","outline-style-dialog","outline-style-code",
                 "outline-style-color","outline-style-width","outline-style-apply",
                 "outline-style-reset"]:
        assert 'id="'+name+'"' in html
    assert 'id="create-preview" type="button" class="button ghost" hidden' in html
    assert 'id="create-apply" type="submit" class="button primary"' in html
    assert '$("create-a1").focus();' in js
    create=js[js.index('  async function quickCreatePolygon(ev){'):
              js.index('  async function applyObject(which,ev)')]
    for phrase in ['"/api/objects/preview"','"/api/objects/apply"',
                   'state.drawPoints=[];state.drawHover=null;',
                   'setTool("draw");','await refreshEditedDocument(null);']:
        assert phrase in create
    assert "const pad=12/Math.max(.000001,state.scale);" in js
    assert 'if(state.tool==="draw")return;' in js
    assert 'if(["cut","line","line-edit"].includes(state.tool)&&state.meta)' in js


def test_5310_A1_A2_never_culled_for_overlap_zoom_or_label_cap():
    js=(STATIC/"map.js").read_text(encoding="utf-8")
    area=js[js.index('  function renderLabels(features,collisions=[]) {'):
            js.index('  function renderScreenLabels(features)')]
    assert 'const mandatory5310=feature.code==="5310"&&' in area
    assert '(label.field==="A1"||label.field==="A2")' in area
    assert 'if(!mandatory5310&&!selected&&overlapsAnother' in area
    assert 'if(!mandatory5310&&painted>=' in area
    assert 'feature.code!=="5310"&&' in area


def test_raster_stays_visible_when_wms_selects_epsg_for_same_map():
    node_script(r"""
const assert=require('node:assert/strict'),fs=require('fs');
const src=fs.readFileSync('map.js','utf8');
const a=src.indexOf('  function setMapEPSG(');
const b=src.indexOf('  const wmsPresetUrls',a);
assert.ok(a>=0&&b>a);
const inputs=Object.fromEntries(
  ['underlay-epsg','raster-epsg','crs-epsg'].map(id=>[id,{value:''}]));
const jpg={image:{},affine:[0,1,2,3,4,5],
  epsg:null,boundEPSG:'',visible:true};
const geotiff={image:{},affine:[0,1,2,3,4,5],
  epsg:2177,boundEPSG:'',visible:true};
const raster={...jpg,layers:[geotiff]};
const state={mapEPSG:'',previewActive:true,geometrySnapshotValid:true};
let drawCount=0;
const setEPSG=new Function('state','underlay','raster','$',
  'removeUnderlay','rasterInfo','requestDraw',
  src.slice(a,b)+'return setMapEPSG;')(
    state,{enabled:false},raster,id=>inputs[id],()=>{},()=>{},()=>drawCount++);
setEPSG('2180');
assert.equal(raster.boundEPSG,'2180');
assert.equal(geotiff.boundEPSG,'');
setEPSG('2177');
assert.equal(raster.boundEPSG,'2177');
assert.equal(geotiff.boundEPSG,'2177');
assert.equal(drawCount,2);
""")
