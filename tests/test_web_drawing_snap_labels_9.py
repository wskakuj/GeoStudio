"""Stage 9: non-invasive drawing magnet and zoom-consistent A1/A2 labels."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from geostudio.web_app.server import create_app


STATIC = Path(__file__).resolve().parents[1] / "geostudio/web_app/static"
NODE = shutil.which("node")


def node_assertions(script: str):
    if NODE is None:
        pytest.skip("Node is only required for JS geometry tests")
    result = subprocess.run(
        [NODE, "-e", script], cwd=STATIC, capture_output=True,
        text=True, timeout=25, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_bundled_drawing_snap_is_served_before_map_js():
    html = (STATIC/"index.html").read_text(encoding="utf-8")
    assert html.index('src="/drawing_snap.js"') < html.index('src="/map.js"')
    assert 'id="tool-draw-snap"' in html
    assert 'aria-pressed="true"' in html
    with TestClient(create_app()) as client:
        response=client.get("/drawing_snap.js")
        assert response.status_code==200
        assert "closestPointOnSegment" in response.text


def test_magnet_snaps_to_near_nodes_and_edges_but_not_distant_lines():
    node_assertions(r"""
const assert=require('node:assert/strict');
const {snapPoint}=require('./drawing_snap.js');
const feature={
 id:'f12', code:'5310', closed:true, visible:true,
 bbox:[0,0,20,20],
 geometry:[[[0,0],[20,0],[20,20],[0,20],[0,0]]]
};
const options={scale:10,enabled:true,vertexPixels:7,edgePixels:5};
let hit=snapPoint({x:0.02,y:0.02},[feature],options);
assert.equal(hit.kind,'węzeł');
assert.deepEqual(hit.point,{x:0,y:0});
assert.equal(hit.code,'5310');
hit=snapPoint({x:8,y:0.4},[feature],options);
assert.equal(hit.kind,'krawędź');
assert.deepEqual(hit.point,{x:8,y:0});
hit=snapPoint({x:8,y:0.7},[feature],options);
assert.equal(hit.kind,null);
assert.deepEqual(hit.point,{x:8,y:0.7});
hit=snapPoint({x:8,y:0.4},[feature],{...options,bypass:true});
assert.equal(hit.kind,null);
assert.deepEqual(hit.point,{x:8,y:0.4});
hit=snapPoint({x:8,y:0.4},[feature],{...options,enabled:false});
assert.equal(hit.kind,null);
assert.deepEqual(hit.point,{x:8,y:0.4});
// The cursor threshold is fixed in SCREEN pixels, not GEO-MAP metres.
hit=snapPoint({x:8,y:4},[feature],{...options,scale:1});
assert.equal(hit.kind,'krawędź');
hit=snapPoint({x:8,y:6},[feature],{...options,scale:1});
assert.equal(hit.kind,null);
// Hidden layers are not valid snap targets.
hit=snapPoint({x:8,y:0.4},[{...feature,visible:false}],options);
assert.equal(hit.kind,null);
""")


def test_magnet_applies_to_all_draw_tools_uses_actual_clicked_point_and_alt():
    src=(STATIC/"map.js").read_text(encoding="utf-8")
    assert "state.drawMagnet" in src
    assert 'link("tool-draw-snap",toggleDrawMagnet)' in src
    assert 'window.GeoStudioDrawingSnap' in src
    assert "vertexPixels:7,edgePixels:5" in src
    assert "state.features.filter(isVisible)" in src
    assert "drawingSnapAt(world,ev.altKey)" in src
    assert '["draw","cut","line","line-edit"]' in src
    assert "renderScreenLabels(features);drawGcpMapMarkers();" in src
    assert "drawDraftPolygon();drawMagnetMarker();drawVertexTool();" in src
    # The marker must also render BEFORE the first draft point is added.
    assert "state.drawSnap=null;state.drawCursorWorld=null;" in src
    assert "Math.round(-snapped.point.y*1000)/1000" in src


def test_5310_a1_and_a2_are_independent_and_readable_at_typical_zoom():
    """10A changed grouping: a field has its own drag target and collision box."""
    node_assertions(r"""
const assert=require('node:assert/strict');
const fs=require('node:fs');
const src=fs.readFileSync('./map.js','utf8');
const start=src.indexOf('  function labelFontSize(');
const stop=src.indexOf('  function renderLabels(',start);
assert.ok(start>=0&&stop>start);
const make=(scale,compilationScale=5000)=>
  new Function('state',src.slice(start,stop)+';return labelFontSize;')
    ({scale,tool:'select',edit:{compilationScale,sourceCompilationScale:5000}});
const feature={code:'5310'};
const a1={field:'A1',text:'l',x:10,y:20,size:16};
const a2={field:'A2',text:'So120\nII-0.3',x:10,y:20,size:16};
// A1 and A2 are anchored in map metres: text changes in exactly
// the same ratio as parcel and building geometry during wheel zoom.
const scaleAt2500=96/(.0254*2500);
assert.ok(Math.abs(make(scaleAt2500)(feature,a1,false)-16)<1e-9);
for(const scale of [.01,.2,1,5,12]){
  const expected=16*scale/scaleAt2500;
  assert.ok(Math.abs(make(scale)(feature,a1,false)-expected)<1e-8);
  assert.ok(Math.abs(make(scale)(feature,a2,false)-expected)<1e-8);
  assert.ok(Math.abs(make(scale)(feature,a1,true)-expected)<1e-8);
}
assert.ok(make(.01)(feature,a1,false)<1); // No 8px screen minimum.
// Compilation scale explicitly changes the size stored in map units.
assert.ok(make(.6,1000)(feature,a1,false)<
          make(.6,5000)(feature,a1,false));
assert.ok(make(.6,10000)(feature,a1,false)>
          make(.6,5000)(feature,a1,false));
const main=src.slice(stop,src.indexOf('  function draw() {',stop));
assert.ok(main.includes('for(const label of feature.labels)'));
assert.ok(main.includes('item.fid!==feature.id'));
assert.ok(main.includes('state.labelHits.push({fid:feature.id,field:label.field'));
assert.ok(!main.includes('for(const group of labelGroups('));
""")


def test_regression_user_map_a1_a2_not_silently_removed_from_api():
    from conftest import MapBuilder
    from geostudio.web_app.data import PreviewWorkspace
    map_bytes=(MapBuilder()
        .object("5310","BASE",{"A1":"l","A2":"So120|II-0.3"},
            [(0,0),(0,20),(20,20),(20,0)])
        .build())
    ws=PreviewWorkspace()
    ws.load_map(map_bytes,"mapa.MAP")
    features=ws.viewport((-1,-21,21,1))["features"]
    assert len(features)==1
    fields={l["field"]:l["text"] for l in features[0]["labels"]}
    assert fields=={"A1":"l","A2":"So120\nII-0.3"}
    assert ws.export_copy(ws.editing_status()["documentToken"])[1]==map_bytes
