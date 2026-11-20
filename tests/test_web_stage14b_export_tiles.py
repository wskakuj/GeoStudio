"""Stage 14B: zoom-independent rectangle/full-map export and safe tiled ZIP."""
from __future__ import annotations

import io
from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile

from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.web_app.server import create_app


def fixture_map():
    return (MapBuilder(ext=(5000, -100, -100, 200, 200))
            .object("5310", "A", {"A1": "m", "A2": "II"},
                    [(0, 0), (0, 10), (10, 10), (10, 0)]).build())


def test_large_map_zip_is_streamed_and_revision_bound():
    app = create_app()
    with TestClient(app) as client:
        header = {"X-GeoStudio-Token": app.state.api_token}
        opened = client.post("/api/map", headers={**header, "X-Map-Name": "A.MAP"},
                             content=fixture_map())
        assert opened.status_code == 200
        identity = opened.json()["documentToken"]
        base = {"documentToken": identity, "revision": 0,
                "filename": "Mokra Wies", "format": "tiff",
                "columns": 2, "rows": 1, "manifest": "Mapa pelna; 300 DPI"}
        assert client.post("/api/export/tiles/start", json=base).status_code == 403
        started = client.post("/api/export/tiles/start", json=base, headers=header)
        assert started.status_code == 200, started.text
        ticket = started.json()["ticket"]
        endpoint = f"/api/export/tiles/{ticket}"
        assert client.post(endpoint + "/finish", headers=header).status_code == 400
        payload = b"II*\\x00" + b"x" * 1024
        for index in range(2):
            response = client.post(f"{endpoint}/{index}", headers=header,
                                   content=payload)
            assert response.status_code == 200, response.text
        assert client.post(endpoint + "/1", headers=header,
                           content=payload).status_code == 400
        completed = client.post(endpoint + "/finish", headers=header)
        assert completed.status_code == 200, completed.text
        assert completed.json()["tiles"] == 2
        archive = client.get(endpoint + "/download", headers=header)
        assert archive.status_code == 200
        with ZipFile(io.BytesIO(archive.content)) as zip_file:
            assert zip_file.namelist() == [
                "INFORMACJE.txt", "mapa_r001_c001.tif", "mapa_r001_c002.tif"]
            assert zip_file.read("mapa_r001_c002.tif") == payload
        path = app.state.tile_exports.archive(ticket)[1]
        assert path.is_file()
        app.state.tile_exports.discard(ticket)
        assert not path.exists()

        stale = client.post("/api/export/tiles/start", headers=header,
                            json={**base, "revision": 1})
        assert stale.status_code == 409
        unsafe = client.post("/api/export/tiles/start", headers=header,
                             json={**base, "filename": "../mapa"})
        assert unsafe.status_code == 400


def test_js_full_map_and_tiled_region_is_not_dependent_on_zoom():
    node = shutil.which("node")
    if node is None:
        return
    assets = Path(__file__).resolve().parents[1] / "geostudio/web_app/static"
    script = r"""
const assert=require('node:assert/strict');
const fs=require('node:fs');
const src=fs.readFileSync('./map.js','utf8');
function extract(name,next){
 const at=src.indexOf('  function '+name+'(');
 const end=src.indexOf('  function '+next+'(',at);
 assert.ok(at>0&&end>at);
 return src.slice(at,end);
}
const plan=new Function(extract('planRasterTiles','tiledExportManifest')+
 'return planRasterTiles;')();
const options={
 bounds:[0,0,184.37,148.36],width:18437,height:14836,
 pxPerUnit:100,margin:154,head:236,foot:248,legend:614,
 dpi:300,orientation:'landscape',format:'tiff',denominator:5000
};
const result=plan(options);
assert.ok(result.columns>=3&&result.rows>=2);
assert.equal(result.tiles.length,result.columns*result.rows);
for(const tile of result.tiles){
 assert.ok(tile.fullWidth*tile.fullHeight<=40000000);
 assert.equal(tile.pxPerUnit,options.pxPerUnit);
}
for(let row=0;row<result.rows;row++)
 for(let col=1;col<result.columns;col++){
   const left=result.tiles[row*result.columns+col-1];
   const right=result.tiles[row*result.columns+col];
   assert.ok(Math.abs(left.bounds[2]-right.bounds[0])<1e-8);
 }
for(let row=1;row<result.rows;row++)
 for(let col=0;col<result.columns;col++){
   const top=result.tiles[(row-1)*result.columns+col];
   const bottom=result.tiles[row*result.columns+col];
   assert.ok(Math.abs(top.bounds[3]-bottom.bounds[1])<1e-8);
 }
const bounds=extract('selectedExportBounds','updateExportAreaControls');
let scale=.05;
const state={meta:{bounds:[1,2,300,400]},exportAreaBounds:[10,20,30,40]};
let scope='all';
const selected=new Function('state','$',
 bounds+'return selectedExportBounds;')(state,()=>({value:scope}));
assert.deepEqual(selected(),[1,2,300,400]);
scale=1000;
assert.deepEqual(selected(),[1,2,300,400]);
scope='rect';
assert.deepEqual(selected(),[10,20,30,40]);
"""
    run = subprocess.run([node, "-e", script], cwd=assets, check=False,
                         capture_output=True, text=True, timeout=25)
    assert run.returncode == 0, run.stdout + run.stderr


def test_simplified_export_controls_exist_and_advanced_layout_is_hidden():
    root = Path(__file__).resolve().parents[1] / "geostudio/web_app/static"
    html = (root / "index.html").read_text("utf-8")
    js = (root / "map.js").read_text("utf-8")
    assert '<option value="all" selected>Cała mapa</option>' in html
    assert '<option value="rect">Prostokąt zaznaczony na mapie</option>' in html
    assert "Skala opracowania (1:N)" in html
    assert 'id="layout-choose-area"' in html
    assert 'class="layout-editor-details" hidden' in html
    assert 'function installExportAreaCapture()' in js
    assert 'function exportTiledLayout(options,basename)' in js
    assert 'state.edit.compilationScale||5000' in js
