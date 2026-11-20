"""Stage 14C — one sharp TIFF/BigTIFF page from bounded RGB canvas tiles."""
from __future__ import annotations

import io
from pathlib import Path
import shutil
import subprocess

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.mosaic_tiff import tiff_header
from geostudio.web_app.server import create_app
from geostudio.web_app.tile_exports import TiledArchiveStore


def fixture_map():
    return (MapBuilder(ext=(5000, -100, -100, 100, 100))
            .object("5310", "A", {"A1": "a"},
                    [(0, 0), (0, 5), (5, 5), (5, 0)]).build())


def tile_rgb(x, y, width, height):
    return bytes(channel for local_y in range(height)
                 for local_x in range(width)
                 for channel in ((x + local_x) * 10,
                                 (y + local_y) * 20, 137))


def test_tiff_headers_are_classic_or_big_based_on_actual_size():
    small, offset, big = tiff_header(5, 3, 300)
    assert not big and offset == 180 and small[:4] == b"II*\x00"
    gigantic, offset, big = tiff_header(100_000, 100_000, 600)
    assert big and offset == 320
    assert gigantic[:4] == b"II+\x00"
    assert len(gigantic) == 320


def test_mosaic_is_one_real_tiff_with_exact_pixels_and_dpi():
    ws = PreviewWorkspace()
    ws.load_map(fixture_map(), "test.MAP")
    store = TiledArchiveStore(ws)
    status = ws.editing_status()
    ticket = store.begin_mosaic(
        status["documentToken"], status["revision"],
        "calosc", 5, 3, 300, 2, 2)
    with pytest.raises(ValueError,match="Brakuje"):
        store.finish_mosaic(ticket)
    # Three columns × two rows, including partial right/bottom tiles.
    for index, (x, y, w, h) in enumerate([
        (0, 0, 2, 2), (2, 0, 2, 2), (4, 0, 1, 2),
        (0, 2, 2, 1), (2, 2, 2, 1), (4, 2, 1, 1)
    ]):
        store.add_mosaic(ticket, index, tile_rgb(x, y, w, h))
    result = store.finish_mosaic(ticket)
    assert result["tiles"] == 6 and result["filename"] == "calosc_calosc.tif"
    name, path = store.archive(ticket)
    assert path.exists()
    with Image.open(path) as image:
        assert image.n_frames == 1 and image.size == (5, 3)
        assert image.mode == "RGB"
        assert image.tag_v2[282] == 300
        assert image.tag_v2[283] == 300
        assert image.tag_v2[296] == 2
        for y in range(3):
            for x in range(5):
                assert image.getpixel((x, y)) == (x*10, y*20, 137)
    store.discard(ticket)
    assert not path.exists()


def test_http_one_tiff_auth_exact_size_and_revision():
    app = create_app()
    with TestClient(app) as client:
        auth = {"X-GeoStudio-Token": app.state.api_token}
        opened = client.post("/api/map", content=fixture_map(),
                             headers={**auth, "X-Map-Name": "test.MAP"})
        assert opened.status_code == 200
        token = opened.json()["documentToken"]
        data = {"documentToken": token, "revision": 0,
                "filename": "test", "width": 3, "height": 2,
                "dpi": 300, "tileWidth": 2, "tileHeight": 2}
        assert client.post("/api/export/mosaic/start", json=data).status_code == 403
        started = client.post("/api/export/mosaic/start",
                              json=data,headers=auth)
        assert started.status_code == 200, started.text
        ticket = started.json()["ticket"]
        base = "/api/export/mosaic/" + ticket
        assert client.post(base + "/finish", headers=auth).status_code == 400
        assert client.post(base + "/part/0", headers=auth,
                           content=b"bad").status_code == 400
        assert client.post(base + "/part/0", headers=auth,
                           content=tile_rgb(0, 0, 2, 2)).status_code == 200
        assert client.post(base + "/part/1", headers=auth,
                           content=tile_rgb(2, 0, 1, 2)).status_code == 200
        assert client.post(base + "/finish", headers=auth).status_code == 200
        response = client.get(base + "/download", headers=auth)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/tiff"
        with Image.open(io.BytesIO(response.content)) as image:
            assert image.size == (3, 2)
            assert image.getpixel((2, 1)) == (20, 20, 137)
        invalid = client.post("/api/export/mosaic/start",headers=auth,
                              json={**data, "revision": 1})
        assert invalid.status_code == 409


def test_website_mosaic_plan_preserves_global_print_camera_and_furniture():
    root = Path(__file__).resolve().parents[1] / "geostudio/web_app/static"
    js = (root / "map.js").read_text("utf-8")
    assert 'options.virtualLayout?.full||options' in js
    assert 'paintLayoutFurniture(g,options.virtualLayout.full)' in js
    assert 'options.queryBounds||options.bounds' in js
    assert 'options.format==="tiff"' in js
    node = shutil.which("node")
    if not node:
        return
    script = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs');
const src=fs.readFileSync('./map.js','utf8');
const a=src.indexOf('  function planSingleTiffTiles(');
const b=src.indexOf('  function mosaicRGBBlob(',a);
assert.ok(a>0&&b>a);
const plan=new Function(src.slice(a,b)+'return planSingleTiffTiles;')();
const options={
 bounds:[0,0,184.37,148.36],width:18437,height:14836,
 fullWidth:19400,fullHeight:15400,margin:154,head:236,
 pxPerUnit:100,format:'tiff',dpi:300
};
const result=plan(options);
assert.equal(result.columns,10);
assert.equal(result.rows,8);
assert.equal(result.tiles.length,80);
let sum=0;
for(const tile of result.tiles){
 assert.ok(tile.fullWidth<=2048&&tile.fullHeight<=2048);
 assert.equal(tile.virtualLayout.full,options);
 assert.equal(tile.bounds[0],options.bounds[0]);
 sum+=tile.fullWidth*tile.fullHeight;
}
assert.equal(sum,options.fullWidth*options.fullHeight);
assert.equal(result.tiles[0].virtualLayout.x,0);
assert.equal(result.tiles[1].virtualLayout.x,2048);
assert.equal(result.tiles[result.columns].virtualLayout.y,2048);
"""
    result = subprocess.run([node, "-e", script],cwd=root,text=True,
                            capture_output=True,timeout=25)
    assert result.returncode == 0,result.stdout+result.stderr
