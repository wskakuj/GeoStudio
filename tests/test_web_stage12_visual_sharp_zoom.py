"""Stage 12 regression: crisp vector zoom, WMS refresh, raster stack and click GCP."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess

import pytest

STATIC=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"


def test_live_zoom_never_stretches_previous_map_bitmap():
    js=(STATIC/"map.js").read_text("utf-8")
    draw=js[js.index("  function draw() {"):js.index("  function requestDraw()",js.index("  function draw() {"))]
    zoom=js[js.index("  function zoomAt("):js.index("  // Same logical-DPI",js.index("  function zoomAt("))]
    viewport=js[js.index("  function scheduleViewport("):js.index("  // Stage 11:",js.index("  function scheduleViewport("))]
    assert "drawNavigationPreview()" not in draw
    assert "beginNavigationPreview()" not in zoom
    assert "renderFill(feature)" in draw and "renderStroke(feature)" in draw
    assert "renderScreenLabels(features)" in draw
    assert "if(state.localMapReady){requestDraw();return;}" in viewport
    assert "setTimeout(refreshViewport,85)" in viewport
    assert "boundsFromViewport(.65)" in js
    assert "viewportFeatureCache.set(feature.id,feature)" in js


def test_wms_request_is_hidpi_cancelable_and_reloads_after_zoom():
    js=(STATIC/"map.js").read_text("utf-8")
    assert "state.width*dpr*1.20" in js
    assert "underlay.ticket++;" in js
    assert "if(underlay.abort){underlay.abort.abort();underlay.abort=null;}" in js
    assert "setTimeout(refreshUnderlay,immediate?0:115)" in js
    # Rysowanie idzie po stosie podkładów, więc warunek jest per warstwa.
    assert "if(!underlay.enabled)return;" in js
    assert "if(!item.visible||!item.image||!item.bounds)continue;" in js
    assert "documentToken!==state.edit?.documentToken)return" in js
    # Obraz trafia do konkretnej warstwy stosu (odświeżamy wszystkie widoczne).
    assert "item.image=image;item.bounds=bounds;item.loading=false;" in js


def test_sidebar_layers_and_nonmodal_visual_pairing():
    html=(STATIC/"index.html").read_text("utf-8")
    js=(STATIC/"map.js").read_text("utf-8")
    css=(STATIC/"styles.css").read_text("utf-8")
    for id_ in ("layers-vectors-tab","layers-rasters-tab",
                "vectors-layer-panel","rasters-layer-panel",
                "raster-layers-list","raster-gcp-canvas",
                "raster-gcp-cancel","raster-gcp-apply",
                "raster-visual-dialog"):
        assert f'id="{id_}"' in html
    assert '<textarea id="raster-gcp"' not in html
    assert "raster.layers.push(rasterEntry())" in js
    assert "raster.layers.filter(x=>x.id!==item.id)" in js
    assert "checkbox.checked=item.visible" in js
    assert "target.opacity=value" in js
    assert "gcpView.waiting=true;" in js
    assert "gcpView.pending=point;gcpView.waiting=true" in js
    assert '$("raster-visual-dialog").show();' in js
    assert 'map.addEventListener("pointerdown",pickGcpMapPoint,true);' in js
    assert ".layer-tab-panel[hidden]{display:none!important;}" in css


def test_photo_gcp_without_chosen_crs_and_native_map_coordinate_conversion():
    node=shutil.which("node")
    if not node:
        pytest.skip("Node required to execute JavaScript regressions")
    script=r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('map.js','utf8');
function block(start,end){
  const a=src.indexOf(start),b=src.indexOf(end,a);
  assert.ok(a>=0&&b>a,start+' '+end);
  return src.slice(a,b);
}
// User-selected JPG/PNG calibrated against an existing MAP never
// requires a geographic EPSG: the two clicked points share MAP XY.
const raster={epsg:null,affine:null,gcps:[],image:{}};
const state={mapEPSG:''};
const verify=new Function('raster','state','rasterInfo',
  block('  function rasterGeoValid()','  function showRasterIfCalibrated()')+
  ';return rasterGeoValid;')(raster,state,()=>{});
assert.equal(verify(),true);
raster.epsg=2180;
assert.equal(verify(),false);
raster.epsg=null;
const visible=new Function('state',
  block('  function rasterCanShow(','  function renderRasterLayers(')+
  ';return rasterCanShow;')(state);
assert.equal(visible({image:{},affine:[0,1,2,3,4,5],
  visible:true,boundEPSG:'',epsg:null}),true);
let draws=0;
const view={open:true,waiting:true,pending:{u:125,v:231},fitSerial:0};
const picked=new Function('gcpView','raster','eventCoords','screenToWorld',
  'gcpNearestMapPoint','updateGcpUi','renderRasterLayers','canvas',
  block('  function gcpMapPoint(','  function moveGcpMapPoint(')+
  ';return pickGcpMapPoint;')(
  view,raster,()=>({x:25,y:35}),()=>({x:701234.5,y:-513210.75}),
  ()=>-1,()=>draws++,()=>{},{});
let blocked=false;
picked({button:0,pointerId:1,preventDefault(){blocked=true;},stopImmediatePropagation(){}});
assert.ok(blocked);
assert.deepEqual(raster.gcps[0],{u:125,v:231,x:513210.75,y:701234.5});
assert.equal(view.waiting,false);
assert.equal(view.pending,null);
assert.equal(draws,1);
"""
    result=subprocess.run([node,"-e",script],cwd=STATIC,
        capture_output=True,text=True,timeout=25)
    assert result.returncode==0,result.stdout+result.stderr


def test_underlay_dimensions_follow_dpr_without_exceeding_server_limits():
    node=shutil.which("node")
    if not node: pytest.skip("Node required")
    script=r"""
const assert=require('node:assert/strict'),fs=require('node:fs');
const src=fs.readFileSync('map.js','utf8');
const a=src.indexOf('  function underlayRequestDimensions(');
const b=src.indexOf('  function scheduleUnderlayRefresh(',a);
const state={width:700,height:550,pixelRatio:2};
const size=new Function('state',src.slice(a,b)+'return underlayRequestDimensions;')(state);
const image=size([0,0,700,550]);
assert.ok(image.width>=1200 && image.height>=900,JSON.stringify(image));
assert.ok(image.width*image.height<=3000000);
for(const b of [[0,0,1,1000],[0,0,1000,1],[0,0,1500,1000]]){
 const dim=size(b);
 assert.ok(dim.width>=128 && dim.height>=128);
 assert.ok(dim.width<=2048 && dim.height<=2048);
 assert.ok(dim.width*dim.height<=3000000);
}
"""
    result=subprocess.run([node,"-e",script],cwd=STATIC,
      capture_output=True,text=True,timeout=25)
    assert result.returncode==0,result.stdout+result.stderr
