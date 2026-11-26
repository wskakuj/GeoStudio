"""Stage 13A: transparent cartography catalogue and direct draggable GCP workflow."""
from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient
from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app

STATIC=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"


def example_map():
    return (MapBuilder()
      .object("5310","BUILDING",{"A1":"m","A2":"So120"},
              [(0,0),(0,20),(20,20),(20,0)])
      .object("5216","PARCEL",{"A2":"12/9"},
              [(30,0),(30,30),(50,30),(50,0)])
      .build())


def test_cartographic_catalog_reads_actual_style_and_keeps_original_map():
    ws=PreviewWorkspace()
    source=example_map()
    ws.load_map(source,"TEST.MAP")
    ws.set_cartographic_library("znane.CDF",
                                b"5310 22 33 44 3 88 99 100 1.2\r\n")
    ws.set_cartographic_library("granice.LAY",
                                b"5310 32768 2.008 1 standard 2.5 0\r\n")
    ws.set_cartographic_library("znaki.SYM",
                                b"*5310 symbol\r\n O 4003 0 0 0 0 0\r\n"
                                b"*4003 dash\r\n2 2 -1 0 0\r\n")
    catalogue=ws.cartography_catalog()
    assert catalogue["sampleOnly"] is True
    assert catalogue["totalCodes"]==2
    assert catalogue["totalObjects"]==2
    item=next(x for x in catalogue["items"] if x["code"]=="5310")
    assert item["count"]==1
    assert item["a1"]=="m"
    assert item["a2"]=="So120"
    assert item["style"]["hatch"]==3
    assert item["style"]["dash"]==[6,3]
    # 5310 outlines default to 3 px on this branch (library width is not used).
    assert item["style"]["strokeWidth"]==3.0
    assert set(item["style"]["libraryMatches"])=={"CDF","LAY","SYM"}
    assert any("SYM" in note and "O" in note for note in item["notes"])
    assert ws.export_copy(ws.editing_status()["documentToken"])[1]==source


def test_cartographic_catalog_endpoint_requires_auth_and_open_map():
    ws=PreviewWorkspace()
    app=create_app(ws)
    with TestClient(app) as c:
        url="/api/cartography/catalog"
        token={"X-GeoStudio-Token":app.state.api_token}
        assert c.get(url).status_code==403
        assert c.get(url,headers=token).status_code==409
        ws.load_map(example_map(),"test.MAP")
        result=c.get(url,headers=token,params={"limit":1})
        assert result.status_code==200,result.text
        assert len(result.json()["items"])==1
        assert result.json()["totalCodes"]==2
        assert result.json()["items"][0]["code"]=="5216" or (
            result.json()["items"][0]["code"]=="5310")


def test_stage13_controls_and_automatic_pairing_exist():
    html=(STATIC/"index.html").read_text("utf-8")
    js=(STATIC/"map.js").read_text("utf-8")
    assert 'id="tool-carto-catalog"' in html
    assert 'id="cartography-catalog-dialog"' in html
    assert 'id="carto-catalog-filter"' in html
    assert 'id="raster-gcp-cancel"' in html
    assert 'id="raster-pick-map"' not in html
    assert 'link("tool-carto-catalog",openCartographyCatalog);' in js
    assert 'gcpView.pending=point;gcpView.waiting=true;' in js
    assert 'map.addEventListener("pointerdown",pickGcpMapPoint,true);' in js
    assert 'map.addEventListener("pointermove",moveGcpMapPoint,true);' in js
    assert 'map.addEventListener("pointerup",releaseGcpMapPoint,true);' in js
    assert 'applyVisualGCP(true);' in js


def test_gcp_pixel_positions_and_drag_map_handle_with_node():
    node=shutil.which("node")
    if not node:return
    script=r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('map.js','utf8');
function part(from,to){
  const a=src.indexOf(from),b=src.indexOf(to,a);
  assert.ok(a>=0&&b>a,from);
  return src.slice(a,b);
}
const raster={image:{width:2000,height:1000},sourceWidth:6000,
  sourceHeight:4000,gcps:[{u:1500,v:400,x:100,y:200}]};
const view={zoom:1,panX:0,panY:0};
const source=part('  function gcpCanvasLayout()','  function zoomGcpAt(')
             +part('  function gcpScreenToSource(','  function drawGcpCanvas(');
const helpers=new Function('gcpView','raster','$','worldToScreen',
   source+'return {gcpScreenToSource,gcpSourceToScreen,gcpNearestRasterPoint};')(
   view,raster,()=>({clientWidth:600,clientHeight:300}),()=>({x:-100,y:-100}));
const p=helpers.gcpSourceToScreen(raster.gcps[0]);
const converted=helpers.gcpScreenToSource(p.x,p.y);
assert.ok(Math.abs(converted.u-1500)<1e-7);
assert.ok(Math.abs(converted.v-400)<1e-7);
assert.equal(helpers.gcpNearestRasterPoint(p.x,p.y),0);

// Map handles are captured before ordinary selection and update native XY.
const current={open:true,waiting:false,pending:null,fitSerial:0,
  mapDragging:null,consumeMapUp:null,activeIndex:null};
let updates=0,completed=0,stopped=0;
const cv={setPointerCapture(){},hasPointerCapture(){return true;},
  releasePointerCapture(){}};
const mapFns=new Function('gcpView','raster','eventCoords','screenToWorld',
  'gcpNearestMapPoint','updateGcpUi','renderRasterLayers',
  'canvas','finishGcpAdjustment',
  part('  function gcpMapPoint(','  async function applyVisualGCP(')+
  'return {pickGcpMapPoint,moveGcpMapPoint,releaseGcpMapPoint};')(
    current,raster,()=>({x:20,y:30}),()=>({x:701234.5,y:-513210.75}),
    ()=>0,()=>updates++,()=>{},cv,()=>completed++);
const ev={button:0,pointerId:7,preventDefault(){},
  stopImmediatePropagation(){stopped++;}};
mapFns.pickGcpMapPoint(ev);
assert.equal(current.mapDragging.index,0);
mapFns.moveGcpMapPoint(ev);
assert.equal(raster.gcps[0].x,513210.75);
assert.equal(raster.gcps[0].y,701234.5);
mapFns.releaseGcpMapPoint(ev);
assert.equal(completed,1);
assert.equal(current.mapDragging,null);
assert.ok(stopped>=3);
"""
    result=subprocess.run([node,"-e",script],cwd=STATIC,
       capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr


def test_reselect_pending_image_pixel_no_extra_pair():
    node=shutil.which("node")
    if not node:return
    script=r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('map.js','utf8');
const a=src.indexOf('  function setupVisualCalibration()');
const b=src.indexOf('  function drawGcpMapMarkers()',a);
assert.ok(a>=0&&b>a);
const handlers={};
const imageCanvas={
  clientLeft:1,clientTop:1,
  addEventListener(name,fn){handlers[name]=fn;},
  getBoundingClientRect(){return {left:0,top:0};}
};
const mapCanvas={addEventListener(){}};
const raster={image:{width:1000,height:800},sourceWidth:3000,
  sourceHeight:1600,gcps:[]};
const view={waiting:false,pending:null,activeIndex:null};
const fn=new Function('raster','gcpView','$','gcpNearestRasterPoint',
'gcpScreenToSource','updateGcpUi','drawGcpCanvas','zoomGcpAt',
'link','finishGcpAdjustment','applyVisualGCP','closeVisualCalibration',
'pickGcpMapPoint','moveGcpMapPoint','releaseGcpMapPoint',
  src.slice(a,b)+'return setupVisualCalibration;')(
raster,view,id=>id==='raster-gcp-canvas'?imageCanvas:mapCanvas,
()=>-1,(x,y)=>({u:x*3,v:y*2}),()=>{},()=>{},()=>{},
()=>{},()=>{},()=>{},()=>{},()=>{},()=>{},()=>{});
fn();
handlers.pointerdown({button:0,clientX:10,clientY:15});
assert.deepEqual(view.pending,{u:27,v:28});
assert.equal(view.waiting,true);
handlers.pointerdown({button:0,clientX:23,clientY:31});
assert.deepEqual(view.pending,{u:66,v:60});
assert.equal(view.waiting,true);
assert.equal(raster.gcps.length,0);
"""
    result=subprocess.run([node,"-e",script],cwd=STATIC,
       capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr


def test_cdf_hatch_density_matches_qt_grid_and_unsupported_pattern_falls_back():
    node=shutil.which("node")
    if not node:return
    script=r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('map.js','utf8');
const a=src.indexOf('  function hatchPattern(style) {');
const b=src.indexOf('  function renderFill(feature) {',a);
assert.ok(a>=0&&b>a);
let dots=0,segments=0,tiles=[];
const document={createElement:()=>{
  const tile={width:0,height:0,getContext(){
    return {clearRect(){},fillRect(){dots++;},beginPath(){},moveTo(){},
      lineTo(){},stroke(){segments++;}};
  }};
  tiles.push(tile);return tile;
}};
const ctx={createPattern(){return 'pattern';}};
const hatchCache=new Map();
const hatch=new Function('document','ctx','hatchCache',
  src.slice(a,b)+'return hatchPattern;')(document,ctx,hatchCache);
assert.equal(hatch({fill:'#334455',hatch:1}),'pattern');
assert.equal(dots,32);
assert.equal(tiles[0].width,8);
dots=0;
assert.equal(hatch({fill:'#334455',hatch:2}),'pattern');
assert.equal(dots,24);
assert.equal(hatch({fill:'#334455',hatch:15}),'#334455');
segments=0;
assert.equal(hatch({fill:'#334455',hatch:8}),'pattern');
assert.ok(segments>=4);
"""
    result=subprocess.run([node,"-e",script],cwd=STATIC,
       capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr


def test_drag_existing_image_gcp_keeps_source_pixels_and_requests_refit():
    node=shutil.which("node")
    if not node:return
    script=r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('map.js','utf8');
const a=src.indexOf('  function setupVisualCalibration()');
const b=src.indexOf('  function drawGcpMapMarkers()',a);
assert.ok(a>=0&&b>a);
const callbacks={};
const image={
 addEventListener(name,fn){callbacks[name]=fn;},
 getBoundingClientRect(){return {left:0,top:0};},
 setPointerCapture(){},hasPointerCapture(){return true;},
 releasePointerCapture(){}
};
const map={addEventListener(){}};
const raster={image:{width:1000,height:800},sourceWidth:2000,
  sourceHeight:1600,gcps:[{u:100,v:200,x:500,y:800}]};
const gcpView={waiting:false,pending:null,activeIndex:null};
let fits=0;
const setup=new Function('raster','gcpView','$','gcpNearestRasterPoint',
 'gcpScreenToSource','updateGcpUi','drawGcpCanvas','zoomGcpAt',
 'link','finishGcpAdjustment','applyVisualGCP','closeVisualCalibration',
 'pickGcpMapPoint','moveGcpMapPoint','releaseGcpMapPoint',
 src.slice(a,b)+'return setupVisualCalibration;')(
 raster,gcpView,id=>id==='raster-gcp-canvas'?image:map,
 ()=>0,(x,y)=>({u:x*2,v:y*2}),()=>{},()=>{},()=>{},
 ()=>{},()=>fits++,()=>{},()=>{},()=>{},()=>{},()=>{});
setup();
callbacks.pointerdown({button:0,pointerId:1,clientX:50,clientY:100});
assert.equal(gcpView.dragging.kind,'point');
callbacks.pointermove({pointerId:1,clientX:160,clientY:250});
assert.equal(raster.gcps[0].u,320);
assert.equal(raster.gcps[0].v,500);
assert.equal(raster.gcps[0].x,500);
assert.equal(raster.gcps[0].y,800);
callbacks.pointerup({pointerId:1});
assert.equal(fits,1);
assert.equal(gcpView.dragging,null);
"""
    result=subprocess.run([node,"-e",script],cwd=STATIC,
       capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
