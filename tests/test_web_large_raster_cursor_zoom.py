"""Regression for cursor-anchored image zoom and large raster previews."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import math
import shutil
import subprocess

from PIL import Image
from fastapi.testclient import TestClient
import pytest

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app
from geostudio.web_app.underlay_raster import (
    MAX_SOURCE_PIXELS, MAX_RASTER_PIXELS, prepare_raster, prepare_geotiff,
)

STATIC=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"


def test_wheel_anchor_tracks_cursor_not_static_center():
    node=shutil.which("node")
    if node is None:
        pytest.skip("Node.js needed to execute zoom coordinate regression")
    script=r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('map.js','utf8');
const begin=src.indexOf('  function gcpCanvasLayout()');
const end=src.indexOf('  function drawGcpCanvas()',begin);
assert.ok(begin>=0&&end>begin);
const raster={image:{width:4000,height:2200}};
const gcpView={zoom:1,panX:0,panY:0};
const canvas={clientWidth:620,clientHeight:350};
let draws=0;
const functions=new Function('raster','gcpView','$','drawGcpCanvas',
  src.slice(begin,end)+';return {gcpCanvasLayout,zoomGcpAt};')(
  raster,gcpView,()=>canvas,()=>{draws++;});
const point={x:87,y:246};
const pixelUnderCursor=()=>{
 const p=functions.gcpCanvasLayout();
 return {u:(point.x-p.left)/p.scale,v:(point.y-p.top)/p.scale};
};
const initial=pixelUnderCursor();
functions.zoomGcpAt(point.x,point.y,-120,0);
assert.ok(gcpView.zoom>1);
assert.ok(Math.abs(pixelUnderCursor().u-initial.u)<1e-9);
assert.ok(Math.abs(pixelUnderCursor().v-initial.v)<1e-9);
functions.zoomGcpAt(point.x,point.y,120,0);
assert.ok(Math.abs(gcpView.zoom-1)<1e-9);
assert.ok(Math.abs(pixelUnderCursor().u-initial.u)<1e-9);
assert.ok(Math.abs(pixelUnderCursor().v-initial.v)<1e-9);
// Trackpad-like deltas and line-mode deltas obey the same anchor.
functions.zoomGcpAt(point.x,point.y,-7,1);
functions.zoomGcpAt(point.x,point.y,14,0);
assert.ok(Math.abs(pixelUnderCursor().u-initial.u)<1e-9);
assert.ok(Math.abs(pixelUnderCursor().v-initial.v)<1e-9);
// Panning never changes the raster pixel under a fixed cursor during zoom.
gcpView.panX=123;gcpView.panY=-98;
const panned=pixelUnderCursor();
functions.zoomGcpAt(point.x,point.y,-150,0);
assert.ok(Math.abs(pixelUnderCursor().u-panned.u)<1e-9);
assert.ok(Math.abs(pixelUnderCursor().v-panned.v)<1e-9);
assert.equal(draws,5);
// Browser wheel event MUST pass real canvas-relative mouse coordinates.
assert.ok(src.includes('zoomGcpAt(ev.clientX-rect.left,ev.clientY-rect.top,'));
"""
    result=subprocess.run([node,"-e",script],cwd=STATIC,
       capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


def test_large_png_uses_bounded_preview_and_source_dimensions():
    source=Image.new("RGB",(5200,4900),(40,130,220))
    buf=BytesIO()
    source.save(buf,format="PNG")
    image_bytes=buf.getvalue()
    assert len(image_bytes)<48*1024*1024
    png,meta=prepare_raster(image_bytes)
    with Image.open(BytesIO(png)) as preview:
        assert preview.width*preview.height<=MAX_RASTER_PIXELS
        assert preview.width<5200 and preview.height<4900
        assert meta["width"]==preview.width
        assert meta["height"]==preview.height
        assert meta["sourceWidth"]==5200
        assert meta["sourceHeight"]==4900
        assert meta["coefficients"] is None
        # Map coordinates must be identical for a source pixel
        # regardless of the preview resolution.
        u,v=1424.5,2150.25
        up=u/meta["sourceWidth"]*preview.width
        vp=v/meta["sourceHeight"]*preview.height
        assert up*(meta["sourceWidth"]/preview.width)==pytest.approx(u)
        assert vp*(meta["sourceHeight"]/preview.height)==pytest.approx(v)


def test_small_tiff_still_returns_exact_pixel_affine_and_transparent_png():
    src=Image.new("RGBA",(30,20),(0,80,120,128))
    buf=BytesIO()
    src.save(buf,format="TIFF")
    png,meta=prepare_geotiff(buf.getvalue())
    assert png.startswith(b"\\x89PNG".decode("unicode_escape").encode("latin1"))
    assert meta["sourceWidth"]==meta["width"]==30
    assert meta["sourceHeight"]==meta["height"]==20
    with Image.open(BytesIO(png)) as im:
        assert im.mode=="RGBA"
        assert im.getpixel((0,0))[3]==128


def test_raster_transform_compensates_preview_downsample_on_canvas():
    node=shutil.which("node")
    if node is None: pytest.skip("Node.js required")
    script=r"""
const fs=require('fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('map.js','utf8');
const a=src.indexOf('  function paintRaster()');
const b=src.indexOf('  function resizeCanvas()',a);
assert.ok(a>0&&b>a);
let transform;
const ctx={save(){},restore(){},drawImage(){},
  transform(...args){transform=args;}};
const item={image:{width:2000,height:1000},
  sourceWidth:6000,sourceHeight:4000,
  affine:[0,-2,500000,3,0,700000],visible:true,opacity:1};
const state={scale:2,center:{x:700000,y:-500000},width:800,height:600};
const paint=new Function('raster','rasterEntry','rasterCanShow','ctx','state',
  src.slice(a,b)+'return paintRaster;')(
  {layers:[item],image:null},()=>null,()=>true,ctx,state);
paint();
assert.deepEqual(transform.map(x=>x===0?0:x),[18,0,0,16,400,300]);
// Source pixel 500,250 maps to preview 500/3,250/4;
// without these scales the raster would be geographically undersized.
"""
    result=subprocess.run([node,"-e",script],cwd=STATIC,
        capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr


def test_preview_endpoint_reports_original_dimensions():
    source=Image.new("RGB",(300,220),(10,40,60))
    output=BytesIO();source.save(output,format="JPEG")
    ws=PreviewWorkspace()
    app=create_app(ws)
    with TestClient(app) as client:
        headers={"X-GeoStudio-Token":app.state.api_token}
        ws.load_map(MapBuilder().object("5216","P",{"A2":"4"},
           [(0,0),(0,10),(10,10),(10,0)]).build(),"map.MAP")
        response=client.post("/api/underlay/raster/prepare",
          content=output.getvalue(),headers=headers)
        assert response.status_code==200,response.text
        assert response.headers["x-raster-source-width"]=="300"
        assert response.headers["x-raster-source-height"]=="220"
        assert response.headers["content-type"]=="image/png"
