'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../geostudio/web_app/static/sheet.js'),'utf8');
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-8,`${a} != ${b}`);
const identity=(x,y)=>({x,y});
const scope={window:{},document:{createElement:()=>({getContext:()=>({measureText:t=>({width:t.length*7})})})}};
vm.runInNewContext(source,scope);const Sheet=scope.window.GeoStudioSheet;
function recorder(){
  let m=[1,0,0,1,0,0],stack=[],current=[];const paths=[];
  function multiply(n){const [a,b,c,d,e,f]=m,[u,v,w,x,y,z]=n;m=[a*u+c*v,b*u+d*v,a*w+c*x,b*w+d*x,a*y+c*z+e,b*y+d*z+f];}
  function point(x,y){return [m[0]*x+m[2]*y+m[4],m[1]*x+m[3]*y+m[5]];}
  return {paths,save(){stack.push([...m]);},restore(){m=stack.pop();},
    translate(x,y){multiply([1,0,0,1,x,y]);},scale(x,y){multiply([x,0,0,y,0,0]);},
    rotate(r){multiply([Math.cos(r),Math.sin(r),-Math.sin(r),Math.cos(r),0,0]);},
    beginPath(){current=[];},moveTo(x,y){current.push(point(x,y));},lineTo(x,y){current.push(point(x,y));},
    closePath(){if(current.length)current.push(current[0]);},fill(){},stroke(){paths.push(current);},fillRect(){},fillText(){}};
}
function draw(kind,angle){
  const item={id:'__preview__',kind,x:123.5,y:-67,w:72,h:29,angle,text:''};
  const g=recorder();Sheet.paint(g,[item],identity,1,5000);
  return {item,paths:g.paths};
}
if(process.argv[2]==='geometry'){
  console.log(JSON.stringify(Sheet.signs.flatMap(kind=>[0,37,90,-120].map(angle=>draw(kind,angle)))));
  process.exit(0);
}
const base={id:'one',kind:'path',x:10,y:20,w:80,h:16,text:'',angle:90};
const box=Sheet.frame(base,identity,1);
near(box.centre.x,50);near(box.centre.y,28);
assert.ok(Sheet.hit(base,{x:50,y:62},identity,1),'Rotated visible end remains selectable');
assert.equal(Sheet.hit(base,{x:15,y:28},identity,1),false,'Old unrotated empty box does not catch clicks');
near(box.corners[2].x,42);near(box.corners[2].y,68);
const enlarged=Sheet.resize(base,{x:34,y:108});
near(enlarged.w,120);near(enlarged.h,24);
const enlargedBox=Sheet.frame(enlarged,identity,1);
near(enlargedBox.corners[0].x,box.corners[0].x);near(enlargedBox.corners[0].y,box.corners[0].y);
near(Sheet.dragAngle(23,{x:10,y:0},{x:10,y:0},{x:0,y:0}),23);
near(Sheet.dragAngle(23,{x:10,y:0},{x:0,y:10},{x:0,y:0}),113);
near(Sheet.dragAngle(23,{x:10,y:0},{x:0,y:10},{x:0,y:0},true),120);
near(Sheet.dragAngle(179,{x:-10,y:.1},{x:-10,y:-.1},{x:0,y:0}),-180);
function environment(){
  const listeners=new Map(),nodes=new Map(),timers=new Map(),requests=[],selectionCalls=[],inspectorCalls=[];
  let timerId=0,blocked=false,holdKind=null,releaseHeld=null;
  class Element{
    constructor(id){this.id=id;this.hidden=id==='ribbon-panel-insert';this.handlers=new Map();this.value='0';this.tagName='BUTTON';this.classList={toggle(){}};}
    addEventListener(type,fn){const a=this.handlers.get(type)||[];a.push(fn);this.handlers.set(type,a);}
    setPointerCapture(){} releasePointerCapture(){this.released=true;} show(){this.open=true;} close(){this.open=false;} getBoundingClientRect(){return {left:0,top:0};}
    dispatch(type,extra={}){const ev={target:this,pointerId:7,button:0,clientX:0,clientY:0,shiftKey:false,
      preventDefault(){this.defaultPrevented=true;},stopPropagation(){},stopImmediatePropagation(){this.stopped=true;},...extra};
      for(const fn of this.handlers.get(type)||[]){fn(ev);if(ev.stopped)break;}
      return ev;}
  }
  const $=id=>{if(!nodes.has(id))nodes.set(id,new Element(id));return nodes.get(id);};
  const canvas=$('canvas');canvas.tagName='CANVAS';
  const state={meta:{name:'test',layers:[]},tool:'select',scale:1,editBusy:false,viewportFeatureCache:new Map(),
    visibleLayers:new Set(),inspectorCache:new Map(),
    edit:{documentToken:'doc-one',revision:1,sheetItems:[{...base,angle:0}],sheetGroups:{one:['native-one']}}};
  const window={addEventListener(type,fn,capture=false){const a=listeners.get(type)||[];a.push({fn,capture:!!capture});listeners.set(type,a);}};
  const document={querySelector:()=>blocked?{}:null,querySelectorAll:()=>[],activeElement:null,addEventListener(){}};
  const gcpView={open:false},raster={image:{},gcps:[],affine:null};
  const context={window,document,canvas,state,$,gcpView,raster,GeoStudioSheet:Sheet,console,
    updateGcpUi(){},closeDrawingAttributes(){},floatingWindows:{calibration:{show(){}}},
    worldToScreen:identity,screenToWorld:identity,eventCoords:ev=>({x:ev.clientX,y:ev.clientY}),
    requestDraw(){},inform(){},editRequestBody:()=>({documentToken:state.edit.documentToken,revision:state.edit.revision}),
    api:async(url,options)=>{
      const kind=url==='/api/map'?'get':'post';let result;
      if(kind==='post'){const body=JSON.parse(options.body);requests.push({url,body});result={...state.edit,revision:state.edit.revision+1,sheetItems:body.items};}
      else result={...state.edit,layers:[],name:'test',objectCount:2,vertexCount:7};
      if(holdKind===kind){holdKind=null;await new Promise(resolve=>{releaseHeld=resolve;});}
      return result;
    },
    selectedObjectIds:()=>[],nativeAPI:()=>null,updateBulkButton(){},notifyHost(){},scheduleRecovery(){},
    renderLayers(){},display:x=>x,refreshViewport:async()=>{
      if(holdKind==='viewport'){holdKind=null;await new Promise(resolve=>{releaseHeld=resolve;});}
    },updateInspector(){inspectorCalls.push(state.edit.documentToken);},
    selectFeature:async id=>{selectionCalls.push({id,token:state.edit.documentToken});state.active=id;},
    setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id)};
  const js=fs.readFileSync(path.join(__dirname,'../geostudio/web_app/static/map.js'),'utf8');
  const start=js.indexOf('  let pendingSheet=null,selectedSheet=null,'),end=js.indexOf('  let fontDraft=null;',start);
  assert.ok(start>=0&&end>start);
  const update=js.slice(js.indexOf('  function updateEditState(status) {'),js.indexOf('  function scheduleRecovery() {'));
  const refresh=js.slice(js.indexOf('  async function refreshEditedDocument('),js.indexOf('  async function saveAttributeChanges('));
  const calibration=js.slice(js.indexOf('  function openVisualCalibration(){'),js.indexOf('  function closeVisualCalibration(){'));
  vm.runInNewContext(update+refresh+calibration+js.slice(start,end)+`\nthis.test={sheetItems,liveSheetPreview,commitSheetAngle,openVisualCalibration,refreshEditedDocument,
    select:id=>{selectedSheet=id;},draft:()=>sheetAngleDraft,rotating:()=>sheetRotate};`,context);
  context.test.select('one');
  function dispatch(type,extra={}){
    const ev={target:canvas,pointerId:7,button:0,clientX:0,clientY:0,shiftKey:false,
      preventDefault(){this.defaultPrevented=true;},stopPropagation(){},stopImmediatePropagation(){this.stopped=true;},...extra};
    for(const {fn} of [...(listeners.get(type)||[])].sort((a,b)=>Number(b.capture)-Number(a.capture))){fn(ev);if(ev.stopped)break;}return ev;
  }
  return {state,$,canvas,dispatch,requests,timers,gcpView,selectionCalls,inspectorCalls,test:context.test,block:v=>{blocked=v;},
    holdNext:kind=>{holdKind=kind;},release:()=>releaseHeld(),hasHeld:()=>!!releaseHeld,
    flush:async()=>{for(const [id,fn] of [...timers]){timers.delete(id);await fn();}await new Promise(resolve=>setImmediate(resolve));}};
}
(async()=>{
  for(const kind of Sheet.signs){
    const e=environment();e.state.edit.sheetItems[0].kind=kind;
    const item=e.state.edit.sheetItems[0],frame=Sheet.frame(item,identity,1);
    e.canvas.dispatch('pointerdown',{clientX:frame.handle.x,clientY:frame.handle.y});
    assert.ok(e.test.rotating(),`${kind}: handle starts rotation`);
    e.dispatch('pointermove',{clientX:frame.centre.x+62,clientY:frame.centre.y});
    assert.equal(e.test.liveSheetPreview().angle,90,`${kind}: full live preview follows pointer`);
    assert.equal(e.state.edit.sheetItems[0].angle,0,'Preview does not mutate saved edit state');
    e.dispatch('pointerup');await e.flush();
    assert.equal(e.requests.length,1,`${kind}: gesture is saved only once`);
    assert.equal(e.requests[0].body.items[0].angle,90);
    assert.equal(e.state.edit.sheetItems[0].angle,90);
    assert.deepEqual(e.state.edit.sheetGroups,{one:['native-one']},'Actual edit state keeps native sign IDs');
  }
  {
    const e=environment(),box=Sheet.frame(e.state.edit.sheetItems[0],identity,1);
    e.canvas.dispatch('pointerdown',{button:2,clientX:box.centre.x+10,clientY:box.centre.y});
    e.dispatch('pointermove',{clientX:box.centre.x+10,clientY:box.centre.y});
    assert.equal(e.test.liveSheetPreview().angle,0,'Right drag starts without a sudden jump');
    e.dispatch('pointermove',{clientX:box.centre.x,clientY:box.centre.y+10});
    e.dispatch('pointercancel');await e.flush();
    assert.equal(e.requests.length,0,'Pointer cancellation never changes native geometry');
    assert.equal(e.test.liveSheetPreview(),null);
  }
  {
    const e=environment();e.dispatch('keydown',{key:']',code:'BracketRight'});
    e.dispatch('keydown',{key:'}',code:'BracketRight',shiftKey:true});
    assert.equal(e.test.liveSheetPreview().angle,20,'Keyboard works for shifted bracket keys');
    e.test.select(null);await e.flush();
    assert.equal(e.requests[0].body.items[0].angle,20,'Delayed save uses original sign, not current selection');
    assert.equal(e.requests.length,1,'Repeated keys make one history operation');
  }
  {
    const e=environment();e.dispatch('keydown',{key:']',code:'BracketRight'});
    assert.equal(e.test.liveSheetPreview().angle,5);
    e.test.openVisualCalibration();
    assert.equal(e.gcpView.open,true);assert.equal(e.test.liveSheetPreview(),null);
    assert.equal(e.test.draft(),null,'Opening actual calibration restores pending rotation');
    let picked=false;e.canvas.addEventListener('pointerdown',()=>{picked=true;});
    const click=e.canvas.dispatch('pointerdown',{clientX:50,clientY:28});
    assert.ok(picked,'A GCP target over a sign reaches the following map calibration handler');
    assert.equal(click.stopped,undefined,'Sheet selection must not intercept calibration');
    const key=e.dispatch('keydown',{key:']',code:'BracketRight'});
    assert.equal(key.defaultPrevented,undefined);
    e.$('sheet-rotate').dispatch('input',{target:{value:'90'}});
    await e.flush();assert.equal(e.requests.length,0);assert.equal(e.state.edit.revision,1);
    e.gcpView.open=false;await e.flush();assert.equal(e.requests.length,0,'Closing calibration cannot revive a cancelled debounce');
  }
  {
    const e=environment(),box=Sheet.frame(e.state.edit.sheetItems[0],identity,1);
    e.canvas.dispatch('pointerdown',{clientX:box.handle.x,clientY:box.handle.y});
    e.dispatch('pointermove',{clientX:box.centre.x+62,clientY:box.centre.y});
    e.test.openVisualCalibration();
    assert.equal(e.test.rotating(),null);assert.equal(e.test.liveSheetPreview(),null);
    assert.equal(e.canvas.released,true,'Opening calibration releases the previous rotation capture');
    e.dispatch('pointerup');await e.flush();assert.equal(e.requests.length,0);
  }
  {
    const e=environment();e.dispatch('keydown',{key:']',code:'BracketRight'});
    e.gcpView.open=true;await e.flush();
    assert.equal(e.requests.length,0,'Even direct calibration state blocks an already queued save');
    assert.equal(e.test.draft(),null);assert.equal(e.test.liveSheetPreview(),null);
  }
  {
    const e=environment(),box=Sheet.frame(e.state.edit.sheetItems[0],identity,1);
    e.$('ribbon-panel-insert').hidden=false;e.state.tool='draw';e.state.drawPoints=[{x:1,y:2}];
    e.canvas.dispatch('pointerdown',{clientX:box.handle.x,clientY:box.handle.y});
    e.dispatch('pointermove',{clientX:box.centre.x+62,clientY:box.centre.y});
    const escape=e.dispatch('keydown',{key:'Escape'});
    assert.equal(escape.stopped,true,'Capture cancellation stops Escape before document drawing shortcuts');
    assert.equal(escape.defaultPrevented,true);assert.equal(e.test.rotating(),null);
    assert.deepEqual(e.state.drawPoints,[{x:1,y:2}]);
    e.dispatch('pointerup');await e.flush();assert.equal(e.requests.length,0);
  }
  for(const pendingKind of ['post','get']){
    const e=environment();e.holdNext(pendingKind);
    e.$('sheet-angle').dispatch('change',{target:{valueAsNumber:45,value:'45'}});
    await new Promise(resolve=>setImmediate(resolve));
    assert.ok(e.hasHeld(),'The actual save/metadata request is pending');
    e.state.edit={...e.state.edit,documentToken:'new-map',revision:1};
    e.state.meta={name:'new-map',layers:[]};
    e.release();await e.flush();
    assert.equal(e.state.edit.documentToken,'new-map','Late save/refresh cannot restore a previous map');
    assert.equal(e.state.meta.name,'new-map');
  }
  for(const activeId of ['old-f9',null])for(const change of ['token','revision']){
    const e=environment();e.holdNext('viewport');
    const waiting=e.test.refreshEditedDocument(activeId,{documentToken:'doc-one',revision:1});
    await new Promise(resolve=>setImmediate(resolve));
    assert.ok(e.hasHeld(),'Guarded refresh is awaiting viewport geometry');
    e.state.edit={...e.state.edit,documentToken:change==='token'?'new-map':'doc-one',revision:2};
    e.state.meta={name:'new-state',layers:[]};e.state.detail={id:'new-selection'};e.state.active='new-selection';
    e.release();await waiting;
    assert.deepEqual(e.selectionCalls,[],'Late viewport must not select an old feature in another document/revision');
    assert.deepEqual(e.inspectorCalls,[],'Late viewport must not clear the new inspector');
    assert.deepEqual(e.state.detail,{id:'new-selection'});assert.equal(e.state.active,'new-selection');
    assert.equal(e.state.meta.name,'new-state');
  }
  for(const target of [{tagName:'INPUT'},{tagName:'TEXTAREA'},{tagName:'SELECT'},
      {tagName:'DIV',isContentEditable:true}]){
    const e=environment();e.dispatch('keydown',{target,key:']',code:'BracketRight'});
    await e.flush();assert.equal(e.requests.length,0,'Typing bracket cannot rotate an old selection');
  }
  for(const change of ['token','revision']){
    const e=environment();e.$('sheet-rotate').dispatch('input',{target:{value:'77'}});
    if(change==='token')e.state.edit={...e.state.edit,documentToken:'other-map'};
    else e.state.edit.revision++;
    assert.equal(e.test.liveSheetPreview(),null,'Stale draft does not appear on another document state');
    await e.flush();assert.equal(e.requests.length,0,'Stale angle cannot write to another revision/map');
  }
  {
    const e=environment();e.dispatch('keydown',{key:']',code:'BracketRight'});
    e.block(true);await e.flush();assert.equal(e.requests.length,0,'A1 form cancels a pending angle debounce');
  }
  {
    const e=environment();e.block(true);
    e.dispatch('keydown',{key:']',code:'BracketRight'});
    e.$('sheet-rotate').dispatch('input',{target:{value:'90'}});
    e.canvas.dispatch('pointerdown',{button:2,clientX:50,clientY:28});
    await e.flush();assert.equal(e.requests.length,0);assert.equal(e.test.rotating(),null);
  }
  {
    const e=environment();e.$('sheet-angle').dispatch('change',{target:{valueAsNumber:270,value:'270'}});
    await e.flush();assert.equal(e.requests[0].body.items[0].angle,-90);
    e.$('sheet-rotate-reset').dispatch('click');await e.flush();assert.equal(e.requests[1].body.items[0].angle,0);
  }
  console.log('All nine signs: live drag, hitboxes, clockwise geometry, cancellation, shortcuts, numeric angle and guarded saves: OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
