"""Stage 12B: raster world-file, GCP and GeoTIFF conversion regressions."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import shutil
import subprocess

import pytest
from PIL import Image, TiffImagePlugin
from fastapi.testclient import TestClient

from geostudio.web_app.underlay_raster import (
    parse_world_text, fit_gcp_payload, prepare_geotiff)
from geostudio.web_app.server import create_app
from geostudio.web_app.data import PreviewWorkspace
from conftest import MapBuilder


def test_world_file_preserves_half_pixel_and_geodetic_axis_order():
    values = parse_world_text("2\n0\n0\n-2\n700001\n500001\n")
    assert values == (0,-2,500002,2,0,700000)
    # Northing X (vertical), easting Y (horizontal).
    a,b,c,d,e,f=values
    assert (a*50+b*100+c,d*50+e*100+f)==(499802,700100)
    with pytest.raises(ValueError,match="sześciu"):
        parse_world_text("1\n2\n3")


def test_3_or_4_gcp_affine_recovers_world_coordinates():
    points=[
      {"u":0,"v":0,"x":500000,"y":700000},
      {"u":100,"v":0,"x":500000,"y":700200},
      {"u":0,"v":50,"x":499900,"y":700000},
      {"u":100,"v":50,"x":499900,"y":700200},
    ]
    fit=fit_gcp_payload(points)
    assert fit["count"]==4
    assert fit["coefficients"]==pytest.approx((0,-2,500000,2,0,700000),abs=1e-7)
    assert fit["rmse"]<1e-7
    with pytest.raises(ValueError):
        fit_gcp_payload(points[:2])
    bad=[dict(points[0]),dict(points[0]),dict(points[0])]
    with pytest.raises(ValueError):
        fit_gcp_payload(bad)


def tiff_bytes(*,geo=False):
    image=Image.new("RGB",(18,14),(20,80,130))
    output=BytesIO()
    if geo:
        tags=TiffImagePlugin.ImageFileDirectory_v2()
        tags[33550]=(2.0,2.0,0.0)
        tags[33922]=(0.0,0.0,0.0,700000.0,500000.0,0.0)
        tags[34735]=(1,1,0,1,3072,0,1,2180)
        image.save(output,format="TIFF",tiffinfo=tags)
    else:
        image.save(output,format="TIFF")
    return output.getvalue()


def test_tiff_conversion_without_geo_is_unpositioned():
    png,meta=prepare_geotiff(tiff_bytes())
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert (meta["width"],meta["height"])==(18,14)
    assert meta["coefficients"] is None
    assert meta["epsg"] is None
    with pytest.raises(ValueError):
        prepare_geotiff(b"not a tiff")


def test_geotiff_embedded_transform_and_epsg():
    png,meta=prepare_geotiff(tiff_bytes(geo=True))
    assert png.startswith(b"\x89PNG")
    assert meta["epsg"]==2180
    assert meta["coefficients"]==pytest.approx((0,-2,500000,2,0,700000))


def test_gcp_and_geotiff_endpoint_token_check():
    workspace=PreviewWorkspace()
    app=create_app(workspace)
    with TestClient(app) as client:
        path="/api/underlay/gcp"
        assert client.post(path,json={"points":[]}).status_code==403
        headers={"X-GeoStudio-Token":app.state.api_token}
        params=[{"u":0,"v":0,"x":1,"y":2},
                {"u":1,"v":0,"x":1,"y":3},
                {"u":0,"v":1,"x":0,"y":2}]
        response=client.post(path,json={"points":params},headers=headers)
        assert response.status_code==200,response.text
        assert response.json()["rmse"]<1e-8
        tiffpath="/api/underlay/raster/prepare"
        assert client.post(tiffpath,data=tiff_bytes(),headers=headers).status_code==409
        workspace.load_map(MapBuilder().object("5216","P",{"A2":"4"},
          [(0,0),(0,10),(10,10),(10,0)]).build(),"map.MAP")
        tiff=client.post(tiffpath,content=tiff_bytes(geo=True),headers=headers)
        assert tiff.status_code==200,tiff.text
        assert tiff.headers["x-raster-epsg"]=="2180"
        assert tiff.headers["content-type"]=="image/png"
        assert client.post(tiffpath,content=b"bad",headers=headers).status_code==400


def test_raster_canvas_uses_georeferenced_affine_and_not_export():
    static=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"
    js=(static/"map.js").read_text("utf-8")
    html=(static/"index.html").read_text("utf-8")
    assert 'id="underlay-world-file"' in html
    assert 'id="raster-gcp"' in html
    assert "paintUnderlay();paintRaster();drawGrid();" in js
    assert "ctx.transform(d*scale,-a*scale,e*scale,-b*scale" in js
    assert 'if(pass==="strokes")for(const item of visible)renderStroke(item);' in js
    assert 'id="raster-calibrate"' in html
    node=shutil.which("node")
    if node:
        script=r"""
const fs=require('fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('map.js','utf8');
const a=src.indexOf('  function parseWorldFileText(');
const b=src.indexOf('  function rasterGeoValid(',a);
assert.ok(a>0&&b>a);
const parse=new Function(src.slice(a,b)+';return parseWorldFileText;')();
assert.deepEqual(parse('2\n0\n0\n-2\n700001\n500001'),
                 [0,-2,500002,2,0,700000]);
assert.throws(()=>parse('bad'),/6 wierszy/);
"""
        result=subprocess.run([node,"-e",script],cwd=static,
                              capture_output=True,text=True,timeout=20)
        assert result.returncode==0,result.stdout+result.stderr
