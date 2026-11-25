// Pure annotation assignment: synthetic coordinates, no uploaded scan data.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const context=vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../geostudio/web_app/static/raster_a1.js'),'utf8'),context);
const {assign}=context.GeoStudioRasterA1;
const w=160,h=120,labels=new Int32Array(w*h),shapes=new Map();
for(const [id,l,r] of [[1,20,60],[2,60,100]]){
  shapes.set(id,{points:[[l,20],[r,20],[r,100],[l,100]],bounds:[l,20,r,100]});
  for(let y=20;y<100;y++)for(let x=l;x<r;x++)labels[y*w+x]=id;
}
const trace={labels,shapes};
const ann=(text,anchor,extra={})=>({text,anchor,box:[25,25,45,45],status:'ok',confidence:.98,source:'inside',hasLeader:false,...extra});
const run=annotations=>assign({width:w,height:h,annotations},trace,w,h);
let cases=0;function test(name,fn){fn();cases++;console.log('OK '+name);}
test('a leader ending in another field determines A1 ownership',()=>{
  const result=run([ann('178',[80,50],{source:'callout',hasLeader:true,leaderEndpoints:[[80,50]]})]);
  assert.equal(result.size,1);assert.equal(result.get(2).text,'178');assert.equal(result.get(2).status,'ok');
});
test('a missing or branched leader never falls back to its circle centre',()=>{
  assert.equal(run([ann('178',null,{hasLeader:true})]).size,0);
  const result=run([ann('178',[40,50],{hasLeader:true,leaderEndpoints:[[40,50],[80,50]]})]);
  assert.equal(result.size,2);assert.ok([...result.values()].every(p=>p.status==='uncertain'));
});
test('normalised preview pixels are rescaled for the selected analysis quality',()=>{
  const result=assign({width:320,height:240,annotations:[ann('175',[160,100],{box:[140,80,180,120]})]},trace,w,h);
  assert.equal(result.get(2).text,'175');assert.deepEqual(Array.from(result.get(2).anchor),[80,50]);
  assert.deepEqual(Array.from(result.get(2).box),[70,40,90,60]);
});
test('different numbers within the same field require a manual choice',()=>{
  const result=run([ann('17',[40,50]),ann('18',[40,60])]);
  assert.equal(result.get(1).status,'conflict');assert.equal(result.get(1).text,'');
  assert.equal(run([ann('17',[40,50]),ann('17',[40,60])]).get(1).status,'ok');
});
test('a weak conflicting guess cannot erase a confirmed field number in either order',()=>{
  const sure=ann('175',[40,50]);
  const weak=ann('1',[40,60],{status:'uncertain',textStatus:'uncertain',confidence:.7,reason:'weak_text'});
  for(const items of [[sure,weak],[weak,sure]]){
    const suggestion=run(items).get(1);
    assert.equal(suggestion.text,'175');assert.equal(suggestion.status,'ok');
    assert.equal(suggestion.assignmentStatus,'ok');
    assert.deepEqual([...suggestion.alternatives].map(a=>a.text).sort(),['1','175']);
  }
});
test('uncertain text keeps its reliable anchor and full-number alternatives for review',()=>{
  const suggestion=run([ann('208',[40,50],{status:'uncertain',textStatus:'uncertain',
    confidence:.73,reason:'truncated_text',alternatives:[{text:'28',confidence:.96,votes:2}]})]).get(1);
  assert.equal(suggestion.text,'208');assert.equal(suggestion.status,'uncertain');
  assert.equal(suggestion.assignmentStatus,'ok');assert.equal(suggestion.reason,'truncated_text');
  assert.deepEqual([...suggestion.alternatives].map(a=>a.text).sort(),['208','28']);
});
test('separate credible numbers in one region flag a leaked boundary for review',()=>{
  const confirmed=ann('36',[40,35]);
  const second=ann('37',[40,65],{status:'uncertain',textStatus:'uncertain',confidence:.78,
    box:[25,55,45,75],reason:'truncated_text'});
  for(const input of [[confirmed,second],[second,confirmed]]){
    const suggestion=run(input).get(1);
    assert.equal(suggestion.text,'36');assert.equal(suggestion.assignmentStatus,'ok');
    assert.equal(suggestion.status,'uncertain');assert.equal(suggestion.reason,'multiple_field_numbers');
  }
  const duplicate=run([confirmed,{...second,box:confirmed.box}]).get(1);
  assert.equal(duplicate.status,'ok','An alternative reading of the same ink mark is not a second field');
  const unknown=run([confirmed,{...second,associationStatus:'uncertain',reason:'boundary_anchor'}]).get(1);
  assert.equal(unknown.status,'ok','Uncertain ownership cannot prove a second field');
});
test('a separate unread coloured callout flags a possible leaked field without guessing text',()=>{
  const known=ann('170',[40,35]);
  const unread=ann('',[40,65],{status:'uncertain',textStatus:'uncertain',confidence:0,
    reason:'unread_callout',source:'callout',ink:'blue',circleConfidence:.96,box:[25,55,45,75]});
  const result=run([known,unread]).get(1);
  assert.equal(result.text,'170');assert.equal(result.status,'uncertain');
  assert.equal(result.reason,'unread_field_number');assert.equal(result.assignmentStatus,'ok');
  assert.equal(run([known,{...unread,associationStatus:'uncertain'}]).get(1).status,'ok',
    'An unread mark with unknown ownership cannot disqualify the confirmed number');
  assert.equal(run([known,{...unread,ink:'dark'}]).get(1).status,'ok',
    'An unread printed loop is not evidence of another handwritten field number');
});
test('unknown and branched leaders never become a reliable tentative assignment',()=>{
  const result=run([ann('133',null,{status:'uncertain',textStatus:'ok',source:'callout',hasLeader:true,
    associationStatus:'uncertain',leaderEndpoints:[[40,50],[80,50]]})]);
  assert.equal(result.size,2);
  assert.ok([...result.values()].every(s=>s.assignmentStatus==='uncertain'&&s.status==='uncertain'));
  assert.equal(run([ann('178',null,{status:'uncertain',textStatus:'ok',source:'inside',
    associationStatus:'uncertain',hasLeader:true,reason:'possible_circle'})]).size,0);
});
test('a map-line network with many endpoints cannot seed false field conflicts',()=>{
  const endpoints=[[40,30],[40,40],[40,50],[40,60],[80,50]];
  const result=run([ann('175',[40,50]),ann('1',null,{hasLeader:true,status:'uncertain',leaderEndpoints:endpoints})]);
  assert.equal(result.size,1);assert.equal(result.get(1).text,'175');assert.equal(result.get(1).status,'ok');
});
test('occupied, outside and ambiguous boundary anchors cannot acquire a guessed field',()=>{
  assert.equal(run([ann('17',[10,50]),ann('18',[60,10])]).size,0);
  const uncertain=run([ann('17',[59.5,50])]);assert.equal(uncertain.get(1).status,'uncertain');
  assert.equal(uncertain.get(1).assignmentStatus,'uncertain');
  const occupied=new Int32Array(labels);occupied[50*w+40]=0;
  assert.equal(assign({width:w,height:h,annotations:[ann('17',[40,50])]},
    {labels:occupied,shapes},w,h).size,0,'An occupied pixel is not moved to its nearest free neighbour');
});
test('invalid OCR data and stale region IDs are ignored',()=>{
  assert.equal(run([ann('1x7',[40,50]),ann('17',[NaN,20]),null]).size,0);
  assert.equal(assign({width:w,height:h,annotations:[ann('17',[40,50])]},
    {labels,shapes:new Map()},w,h).size,0);
  assert.equal(assign({width:0,height:h,annotations:[]},trace,w,h).size,0);
});
console.log(cases+' raster A1 assignment regressions passed');
