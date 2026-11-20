"""Map-space A1/A2 regression: glyph size follows camera zoom."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

STATIC=Path(__file__).resolve().parents[1]/"geostudio/web_app/static"


def test_labels_are_separate_screen_space_overlay():
    html=(STATIC/"index.html").read_text("utf-8")
    css=(STATIC/"styles.css").read_text("utf-8")
    js=(STATIC/"map.js").read_text("utf-8")
    assert '<canvas id="map-labels-canvas" aria-hidden="true"></canvas>' in html
    assert "#map-labels-canvas { pointer-events:none; }" in css
    assert "const labelCtx = labelCanvas.getContext(\"2d\");" in js
    assert "labelCanvas.width=w;labelCanvas.height=h;" in js
    assert "renderScreenLabels(state.features.filter" in js
    assert "renderScreenLabels(features);drawDraftPolygon()" in js
    assert "snapshotContext.drawImage(canvas,0,0);" in js
    assert "if(pass===\"labels\")renderLabels(visible,collisions);" in js


def test_zoom_changes_label_position_and_glyph_size_proportionally():
    node=shutil.which("node")
    if node is None:
        pytest.skip("Node.js needed for offline JavaScript regression")
    script=r"""
const assert=require('node:assert/strict');
const fs=require('node:fs');
const src=fs.readFileSync('./map.js','utf8');
const start=src.indexOf('  function labelFontSize(');
const end=src.indexOf('  function draw() {',start);
assert.ok(start>0&&end>start);
const state={
 labels:true, active:null, pinned:new Set(), tool:'select',
 labelSelected:null,labelHits:[],exporting:false,
 width:500,height:500,pixelRatio:2,scale:1,
 edit:{sourceCompilationScale:5000,compilationScale:5000}
};
const scenePaints=[],labelPaints=[],transforms=[];
const sceneCtx={fillText(text){scenePaints.push(text);}};
const overlayCtx={
 font:'',save(){},restore(){},setTransform(...args){transforms.push(args);},
 clearRect(){},measureText(text){return {width:text.length*8};},
 fillRect(){},strokeRect(){},strokeText(){},
 fillText(text,x,y){labelPaints.push({text,x,y,font:this.font});}
};
const screenPoint=(x,y)=>({
 x:250+(x-100)*state.scale,
 y:250+(y-100)*state.scale
});
const view=new Function('state','sceneCtx','labelCtx','worldToScreen','document',
 'let ctx=sceneCtx;\n'+src.slice(start,end)+
 '\nreturn {renderScreenLabels,currentCtx:()=>ctx};'
)(state,sceneCtx,overlayCtx,screenPoint,{
 body:{classList:{contains:()=>false}}
});
const feature={
 id:'f10',code:'5310',bbox:[80,80,140,140],
 labels:[
   {field:'A1',text:'b',size:16,x:120,y:110,color:'#CC202C'},
   {field:'A2',text:'So120',size:16,x:120,y:110,color:'#CC202C'}
 ]
};
const xPositions=[],fontSizes=[];
for(const zoom of [.5,1,2,4]){
 state.scale=zoom;
 labelPaints.length=0;
 view.renderScreenLabels([feature]);
 assert.deepEqual(labelPaints.map(p=>p.text),['b','So120']);
 // The font size is proportional to zoom, not fixed at 16 CSS pixels.
 const actual=parseFloat(labelPaints[0].font.match(/([0-9.]+)px/)[1]);
 assert.ok(Math.abs(actual-16*2500*.0254/96*zoom)<1e-9,actual);
 assert.equal(labelPaints[1].font.match(/([0-9.]+)px/)[1],
              labelPaints[0].font.match(/([0-9.]+)px/)[1]);
 assert.equal(view.currentCtx(),sceneCtx);
 assert.equal(state.labelHits.length,2);
 xPositions.push(labelPaints[0].x);
 fontSizes.push(actual);
}
assert.ok(xPositions[0]<xPositions[1]&&xPositions[1]<xPositions[2]&&
          xPositions[2]<xPositions[3]);
for(let i=1;i<fontSizes.length;i++)
 assert.ok(Math.abs(fontSizes[i]/fontSizes[i-1]-2)<1e-9);
assert.deepEqual(scenePaints,[]);
assert.ok(transforms.every(args=>args[0]===2&&args[3]===2));
"""
    result=subprocess.run([node,"-e",script],cwd=STATIC,
                          capture_output=True,text=True,timeout=25,check=False)
    assert result.returncode==0,result.stdout+result.stderr
