"""Modeless attributes and resizable, cursor-anchored raster calibration."""
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from geostudio.web_app.server import create_app


STATIC = Path(__file__).resolve().parents[1] / "geostudio/web_app/static"


def node(script):
    executable = shutil.which("node")
    if not executable:
        pytest.skip("Node.js required for interaction regressions")
    result = subprocess.run([executable, "-e", script], cwd=STATIC,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_floating_window_drag_keyboard_resize_and_reopen_remain_reachable():
    node(r"""
const assert=require('node:assert/strict');
const {attach,boundedRect}=require('./floating_dialog.js');
class Target{
 constructor(){this.events={};this.style={};this.flags=new Set();this.classList={
  add:x=>this.flags.add(x),remove:x=>this.flags.delete(x),
  toggle:(x,on)=>on?this.flags.add(x):this.flags.delete(x)};}
 addEventListener(name,fn){(this.events[name]??=[]).push(fn);}
 removeEventListener(name,fn){this.events[name]=this.events[name].filter(x=>x!==fn);}
 emit(name,extra={}){const ev={button:0,pointerId:7,clientX:0,clientY:0,target:this,
  preventDefault(){this.prevented=true;},stopPropagation(){},...extra};
  for(const f of this.events[name]||[])f(ev);return ev;}
 closest(){return null;} setAttribute(name,value){this[name]=value;}
 setPointerCapture(id){this.pointer=id;}hasPointerCapture(id){return this.pointer===id;}
 releasePointerCapture(){this.pointer=null;}focus(){this.focused=true;}
}
const owner=new Target();owner.innerWidth=1000;owner.innerHeight=700;
owner.ResizeObserver=class{constructor(cb){this.callback=cb;}observe(){}disconnect(){}};
const dialog=new Target(),handle=new Target(),expand=new Target();
dialog.ownerDocument={defaultView:owner};dialog.open=false;
dialog.querySelector=s=>s==='.floating-dialog-handle'?handle:expand;
dialog.getBoundingClientRect=()=>({left:parseFloat(dialog.style.left)||490,
 top:parseFloat(dialog.style.top)||110,width:parseFloat(dialog.style.width)||500,
 height:parseFloat(dialog.style.height)||530});
let shows=0,changes=0;
dialog.show=()=>{dialog.open=true;shows++;};
dialog.showModal=()=>{throw Error('map must remain usable');};
dialog.close=()=>{dialog.open=false;dialog.emit('close');};
const control=attach(dialog,{onGeometry:()=>changes++});control.show();
assert.equal(shows,1);assert.equal(dialog.style.left,'490px');
handle.emit('pointerdown',{clientX:510,clientY:140});
handle.emit('pointermove',{clientX:-900,clientY:-500});
assert.equal(dialog.style.left,'8px');assert.equal(dialog.style.top,'8px');
handle.emit('pointerup');assert.equal(handle.pointer,null);
handle.emit('keydown',{key:'ArrowRight'});assert.equal(dialog.style.left,'28px');
handle.emit('keydown',{key:'ArrowDown',shiftKey:true});assert.equal(dialog.style.top,'9px');
// Clicking a control in the title must not start a window drag.
handle.emit('pointerdown',{target:{closest:()=>true}});assert.equal(handle.pointer,null);
const position={...dialog.style};control.close();control.show();
assert.equal(dialog.style.left,position.left);assert.equal(dialog.style.top,position.top);
expand.emit('click');assert.equal(dialog.style.width,'984px');
assert.equal(dialog.style.height,'684px');assert.equal(expand['aria-pressed'],'true');
owner.innerWidth=640;owner.innerHeight=480;owner.emit('resize');
assert.equal(dialog.style.width,'624px');assert.equal(dialog.style.height,'464px');
expand.emit('click');assert.equal(expand['aria-pressed'],'false');
const restored=dialog.getBoundingClientRect();
assert.ok(restored.left>=8&&restored.left+restored.width<=632);
assert.ok(restored.top>=8&&restored.top+restored.height<=472);
assert.deepEqual(boundedRect({left:900,top:-5,width:900,height:900},
 {width:360,height:240}),{left:8,top:8,width:344,height:224});
assert.ok(changes>4);control.dispose();
""")


def test_calibration_zoom_goes_beyond_old_limit_and_resize_preserves_source_point():
    node(r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('map.js','utf8');
const part=(start,end)=>src.slice(src.indexOf(start),src.indexOf(end,src.indexOf(start)));
const raster={image:{width:4000,height:3000},sourceWidth:8000,sourceHeight:6000};
const gcpView={open:true,zoom:1,panX:0,panY:0,fitted:true};
const canvas={clientWidth:500,clientHeight:300};
let f;
const draw=()=>{gcpView.lastLayout={...f.gcpCanvasLayout(),image:raster.image};};
f=new Function('raster','gcpView','$','drawGcpCanvas',
 part('  function gcpCanvasLayout()','  function drawGcpCanvas()')+
 part('  function resizeGcpCanvas()','  function updateGcpUi(')+
 'return {gcpCanvasLayout,zoomGcpAt,gcpScreenToSource,gcpSourceToScreen,resizeGcpCanvas};')(
 raster,gcpView,()=>canvas,draw);
const target=f.gcpScreenToSource(140,220);
f.zoomGcpAt(140,220,-2000);assert.ok(gcpView.zoom>100);
assert.ok(gcpView.zoom>35); // The old hard limit was reached too early.
const zoomed=f.gcpScreenToSource(140,220);
assert.ok(Math.abs(target.u-zoomed.u)<1e-8&&Math.abs(target.v-zoomed.v)<1e-8);
for(let i=0;i<4;i++)f.zoomGcpAt(140,220,-1000);
assert.equal(gcpView.zoom,256);
const atLimit=f.gcpScreenToSource(140,220);
assert.ok(Math.abs(target.u-atLimit.u)<1e-8&&Math.abs(target.v-atLimit.v)<1e-8);
f.zoomGcpAt(140,220,700);
const before=f.gcpCanvasLayout(),centre=f.gcpScreenToSource(before.w/2,before.h/2);
canvas.clientWidth=900;canvas.clientHeight=650;f.resizeGcpCanvas();
const after=f.gcpCanvasLayout(),sameCentre=f.gcpScreenToSource(after.w/2,after.h/2);
assert.ok(Math.abs(after.scale-before.scale)<1e-10);
assert.ok(Math.abs(sameCentre.u-centre.u)<1e-8&&Math.abs(sameCentre.v-centre.v)<1e-8);
const screen=f.gcpSourceToScreen(target),roundtrip=f.gcpScreenToSource(screen.x,screen.y);
assert.ok(Math.abs(roundtrip.u-target.u)<1e-8&&Math.abs(roundtrip.v-target.v)<1e-8);
// A fitted whole-image view still expands to fill a larger window.
gcpView.zoom=1;gcpView.panX=0;gcpView.panY=0;gcpView.fitted=true;draw();
canvas.clientWidth=1100;canvas.clientHeight=700;f.resizeGcpCanvas();
assert.equal(gcpView.zoom,1);assert.equal(gcpView.panX,0);assert.equal(gcpView.panY,0);
canvas.clientWidth=184;canvas.clientHeight=120;f.resizeGcpCanvas();
assert.equal(f.gcpCanvasLayout().w,184);assert.equal(f.gcpCanvasLayout().h,120);
const small=f.gcpScreenToSource(80,60),smallScreen=f.gcpSourceToScreen(small);
assert.ok(Math.abs(smallScreen.x-80)<1e-9&&Math.abs(smallScreen.y-60)<1e-9);
""")


def test_attribute_inspection_does_not_add_nodes_and_stale_drafts_cannot_apply():
    node(r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('map.js','utf8');
const part=(a,b)=>src.slice(src.indexOf(a),src.indexOf(b,src.indexOf(a)));
const state={meta:{},edit:{documentToken:'map-a',revision:4},tool:'draw',
 drawPoints:[[0,0],[1,0],[1,1]],center:{x:100,y:200},scale:2,editBusy:false};
const create={open:true,close(){this.open=false;}},line={open:false,close(){this.open=false;}};
const fields={'create-dialog':create,'line-dialog':line,'create-summary':{},'create-apply':{}};
const canvas={setPointerCapture(id){this.id=id;},hasPointerCapture(id){return id===this.id;},
 releasePointerCapture(){this.id=null;}};
const shell={classList:{add(){},remove(){}}};let viewports=0,apiCalls=[],resolvePreview,rejectPreview;
const api=(path,options)=>{apiCalls.push(path);return new Promise((r,j)=>{resolvePreview=r;rejectPreview=j;});};
const helpers=new Function('state','$','canvas','shell','eventCoords','requestDraw','scheduleViewport',
 'api','updateEditState','editRequestBody','objectOperation','inform',
 'let drawingAttributeEpoch=1,drawingInspectionDrag=null,attributeSave=null;const floatingWindows={};'+
 part('  function drawingAttributesOpen()','  function setupFloatingWindows()')+
 part('  async function quickCreatePolygon(ev){','  async function applyObject(')+
 'return {inspectMapDuringAttributes,drawingAttributesContext,drawingAttributesCurrent,closeDrawingAttributes,quickCreatePolygon};')(
 state,id=>fields[id],canvas,shell,ev=>({x:ev.clientX,y:ev.clientY}),()=>{},()=>viewports++,
 api,()=>{},()=>({documentToken:state.edit.documentToken,revision:state.edit.revision}),
 ()=>({action:'create',points:state.drawPoints}),()=>{});
const points=JSON.stringify(state.drawPoints),context=helpers.drawingAttributesContext();
function ev(type,x,y,extras={}){return {type,target:canvas,pointerId:3,button:0,
 clientX:x,clientY:y,preventDefault(){this.prevented=true;},stopImmediatePropagation(){this.stopped=true;},...extras};}
const down=ev('pointerdown',10,20);helpers.inspectMapDuringAttributes(down);
assert.ok(down.prevented&&down.stopped);
helpers.inspectMapDuringAttributes(ev('pointermove',30,50));
helpers.inspectMapDuringAttributes(ev('pointerup',30,50));
assert.deepEqual(state.center,{x:90,y:185});assert.equal(viewports,1);
assert.equal(JSON.stringify(state.drawPoints),points);
helpers.inspectMapDuringAttributes(ev('dblclick',40,60));
assert.equal(JSON.stringify(state.drawPoints),points);
assert.equal(helpers.drawingAttributesCurrent(context),true);
state.edit.documentToken='map-b';assert.equal(helpers.drawingAttributesCurrent(context),false);
state.edit.documentToken='map-a';state.edit.revision=5;
assert.equal(helpers.drawingAttributesCurrent(context),false);state.edit.revision=4;
// A late preview after closing the form must never launch apply.
(async()=>{
 const saving=helpers.quickCreatePolygon({preventDefault(){}});
 assert.equal(state.editBusy,true);helpers.closeDrawingAttributes(null,true);
 resolvePreview({canApply:true,previewKey:'old-preview'});await saving;
 assert.deepEqual(apiCalls,['/api/objects/preview']);assert.equal(state.editBusy,false);
 assert.equal(JSON.stringify(state.drawPoints),points);
 const closed=ev('pointerdown',0,0);helpers.inspectMapDuringAttributes(closed);
 assert.equal(closed.prevented,undefined);
 // A late rejection must not re-enable another draft or overwrite its status.
 create.open=true;
 const failed=helpers.quickCreatePolygon({preventDefault(){}});
 helpers.closeDrawingAttributes(null,true);
 create.open=true;state.editBusy=true;
 fields['create-summary'].textContent='Nowy szkic';fields['create-apply'].disabled=true;
 rejectPreview(Error('old request failed'));await failed;
 assert.equal(fields['create-summary'].textContent,'Nowy szkic');
 assert.equal(fields['create-apply'].disabled,true);assert.equal(state.editBusy,true);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_late_line_preview_error_does_not_overwrite_reopened_attributes():
    node(r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('map.js','utf8');
const part=(a,b)=>src.slice(src.indexOf(a),src.indexOf(b,src.indexOf(a)));
const state={edit:{documentToken:'a',revision:1},tool:'line',editBusy:false};
const dialog={open:true,close(){this.open=false;}};
const fields={'line-dialog':dialog,'create-dialog':{open:false},
 'line-summary':{},'line-preview':{},'line-apply':{}};
let rejectRequest;
const f=new Function('state','$','canvas','shell','requestDraw','updateEditState',
 'api','editRequestBody','operationForGeometry','inform',
 'let drawingAttributeEpoch=1,drawingInspectionDrag=null,attributeSave=null;const floatingWindows={};'+
 part('  function drawingAttributesOpen()','  function setupFloatingWindows()')+
 part('  async function previewGeometryForm(','  // „Utwórz linię"')+
 'return {previewGeometryForm,closeDrawingAttributes};')(
 state,id=>fields[id],{}, {classList:{remove(){}}},()=>{},()=>{},
 ()=>new Promise((resolve,reject)=>{rejectRequest=reject;}),()=>({}),()=>({}),()=>{});
(async()=>{
 const old=f.previewGeometryForm('line');f.closeDrawingAttributes('line');
 dialog.open=true;state.edit.documentToken='b';state.geometryPreview={new:true};
 fields['line-summary'].textContent='Nowa linia';fields['line-preview'].disabled=true;
 fields['line-apply'].disabled=true;
 rejectRequest(Error('old preview failed'));await old;
 assert.equal(fields['line-summary'].textContent,'Nowa linia');
 assert.equal(fields['line-preview'].disabled,true);assert.equal(fields['line-apply'].disabled,true);
 assert.deepEqual(state.geometryPreview,{new:true});
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_attribute_keyboard_keeps_native_text_editing_and_escape_preserves_sketch():
    node(r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('map.js','utf8');
const start=src.indexOf('    const attributeDialog=drawingAttributesOpen();');
const end=src.indexOf('    if(activeTrace',start);assert.ok(start>0&&end>start);
let closed=0,submitted=0;
const form={requestSubmit(){submitted++;}};
const dialog={open:true,contains:x=>x.inside,querySelector:()=>form};
const fn=new Function('ev','drawingAttributesOpen','document','closeDrawingAttributes',
 src.slice(start,end)+'return "global";');
const doc={querySelector:()=>null};
function run(key,inside=false,extras={}){const ev={key,target:{inside,matches:()=>inside},
 preventDefault(){this.prevented=true;},...extras};
 const result=fn(ev,()=>dialog.open?dialog:null,doc,()=>{closed++;dialog.open=false;});return {ev,result};}
assert.equal(run('Enter',true).ev.prevented,undefined);assert.equal(submitted,0);
assert.equal(run('z',true,{ctrlKey:true}).result,undefined);
assert.equal(run('Enter',false,{isComposing:true}).ev.prevented,undefined);
assert.equal(run('Enter',false).ev.prevented,true);assert.equal(submitted,1);
assert.equal(run('Enter',false,{repeat:true}).ev.prevented,undefined);assert.equal(submitted,1);
assert.equal(run('Escape',true).ev.prevented,true);assert.equal(closed,1);
assert.equal(run('n').result,'global');
""")


def test_calibration_and_attributes_do_not_compete_for_map_clicks():
    node(r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const src=fs.readFileSync('map.js','utf8');
const part=(a,b)=>src.slice(src.indexOf(a),src.indexOf(b,src.indexOf(a)));
const state={editBusy:false,drawPoints:[[0,0],[1,0],[1,1]]};
const fields={};
for(const name of ['create-dialog','line-dialog','raster-dialog','raster-visual-dialog',
 'create-preview','line-preview','raster-gcp-canvas'])
 fields[name]={open:false,style:{},close(){this.open=false;}};
const gcpView={open:false,fitSerial:0},raster={image:{},gcps:[],affine:null};
const floatingWindows={};
for(const name of ['create','line','calibration']){
 const field=fields[(name==='calibration'?'raster-visual':name)+'-dialog'];
 floatingWindows[name]={show(){field.open=true;},close(){field.close();}};
}
const canvas={style:{}},shell={classList:{remove(){}}};
let cancelled=0;
const f=new Function('state','$','gcpView','raster','floatingWindows','canvas','shell',
 'requestDraw','updateEditState','updateGcpUi','cancelSheetTransforms','inform',
 'let drawingAttributeEpoch=0,drawingInspectionDrag=null,attributeSave=null;'+
 part('  function drawingAttributesOpen()','  function setupFloatingWindows()')+
 part('  function openVisualCalibration(){','  function gcpMapPoint(')+
 'return {openDrawingAttributes,openVisualCalibration,inspectMapDuringAttributes};')(
 state,id=>fields[id],gcpView,raster,floatingWindows,canvas,shell,
 ()=>{},()=>{},()=>{},()=>cancelled++,()=>{});
const points=JSON.stringify(state.drawPoints);
f.openDrawingAttributes('create');assert.equal(fields['create-dialog'].open,true);
state.editBusy=true;f.openVisualCalibration();
assert.equal(gcpView.open,false,'Saving a drawing cannot be interrupted by calibration');
assert.equal(fields['create-dialog'].open,true);
state.editBusy=false;f.openVisualCalibration();
assert.equal(fields['create-dialog'].open,false);assert.equal(gcpView.open,true);
assert.equal(fields['raster-visual-dialog'].open,true);assert.equal(cancelled,1);
const click={target:canvas,preventDefault(){throw Error('Attributes stole a GCP click');}};
f.inspectMapDuringAttributes(click);
f.openDrawingAttributes('line');
assert.equal(gcpView.open,false);assert.equal(fields['raster-visual-dialog'].open,false);
assert.equal(fields['line-dialog'].open,true);assert.equal(JSON.stringify(state.drawPoints),points);
""")


def test_floating_window_asset_is_served_before_map_initializes():
    with TestClient(create_app()) as client:
        response = client.get("/floating_dialog.js")
        assert response.status_code == 200
        assert "function attach(dialog,options={})" in response.text
    html = (STATIC / "index.html").read_text("utf-8")
    assert html.index('src="/floating_dialog.js"') < html.index('src="/map.js"')
