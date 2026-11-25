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
test('occupied, outside and ambiguous boundary anchors cannot acquire a guessed field',()=>{
  assert.equal(run([ann('17',[10,50]),ann('18',[60,10])]).size,0);
  const uncertain=run([ann('17',[59.5,50])]);assert.equal(uncertain.get(1).status,'uncertain');
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
