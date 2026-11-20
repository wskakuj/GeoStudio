"""Regression: zoom-independent Canvas labels and consistent raster export."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


STATIC = Path(__file__).resolve().parents[1] / "geostudio/web_app/static"


def _node_assertions(script: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for Canvas text rendering checks")
    result = subprocess.run(
        [node, "-e", script], cwd=STATIC, capture_output=True,
        text=True, timeout=25, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_screen_glyphs_follow_map_zoom_but_export_uses_existing_sizes():
    _node_assertions(r"""
const assert=require('node:assert/strict');
const fs=require('node:fs');
const src=fs.readFileSync('./map.js','utf8');
const start=src.indexOf('  function labelFontSize(');
const stop=src.indexOf('  function renderLabels(',start);
assert.ok(start>=0&&stop>start);
const fontSource=src.slice(start,stop);
const sample={field:'A1',text:'l',size:16};
const mapFeature={code:'5310'};
function size(scale,dpi,compilation=5000){
  const state={
    scale,exporting:dpi!==96,exportFontRatio:dpi/96,
    edit:{compilationScale:compilation,sourceCompilationScale:5000}
  };
  return new Function('state',fontSource+';return labelFontSize;')
    (state)(mapFeature,sample,false);
}
// On-screen text is a world/map-space size and shrinks on zoom out.
const reference=96/(.0254*2500);
for(const scale of [.012,.1,1,8]){
  assert.ok(Math.abs(size(scale,96)-16*scale/reference)<1e-8);
  // PNG/JPG/TIFF export keeps its previously verified font size at
  // different physical DPI values rather than using viewport zoom.
  assert.equal(size(scale,150),16);
  assert.equal(size(scale,300),16);
}
assert.ok(size(1,96,1000)<size(1,96,5000));
assert.ok(size(1,96,10000)>size(1,96,5000));
assert.ok(!fontSource.includes('exportFontRatio'));
""")


def test_both_5310_labels_remain_visible_even_across_export_batches():
    _node_assertions(r"""
const assert=require('node:assert/strict');
const fs=require('node:fs');
const src=fs.readFileSync('./map.js','utf8');
const start=src.indexOf('  function labelFontSize(');
const end=src.indexOf('  function draw() {',start);
const snippet=src.slice(start,end);
const painted=[];
const ctx={
  save(){},restore(){},measureText(v){return {width:v.length*9}},
  fillRect(){},strokeRect(){},strokeText(){},
  fillText(v){painted.push(v)}
};
const state={
  labels:true,active:null,pinned:new Set(),tool:'select',
  labelSelected:null,labelHits:[],exporting:true,scale:1,
  width:200,height:200,
  edit:{sourceCompilationScale:5000,compilationScale:5000}
};
const renderLabels=new Function(
 'state','ctx','worldToScreen','document',
 snippet+';return renderLabels;'
)(state,ctx,(x,y)=>({x,y}),{body:{classList:{contains:()=>false}}});
function building(id,labelText){
  return {
    id,code:'5310',bbox:[0,0,80,80],
    labels:[
      {field:'A1',text:labelText,x:100,y:100,size:16,color:'#CC202C'},
      {field:'A2',text:'II-0.5',x:100,y:100,size:16,color:'#CC202C'}
    ]
  };
}
const collisions=[];
renderLabels([building('f1','a')],collisions);
assert.deepEqual(painted,['a','II-0.5']);
assert.equal(collisions.length,2);
renderLabels([building('f2','b')],collisions);
assert.deepEqual(painted,['a','II-0.5','b','II-0.5']);
assert.equal(collisions.length,4);
// A subsequent export page uses the SAME ledger; the export renderer
// never applies a second text scale for 300 DPI.
assert.ok(src.includes('renderLabels(visible,collisions)'));
assert.ok(src.includes('renderExportBatch(g,options,part,pass,exportLabelCollisions)'));
assert.ok(!src.includes('state.exportFontRatio=options.dpi/96'));
""")


def test_navigation_does_not_resample_previous_bitmap():
    source=(STATIC/"map.js").read_text(encoding="utf-8")
    assert "function beginNavigationPreview()" not in source
    assert "function drawNavigationPreview()" not in source
    assert "snapshotContext.drawImage(canvas,0,0);" not in source
    assert "renderScreenLabels(features)" in source
