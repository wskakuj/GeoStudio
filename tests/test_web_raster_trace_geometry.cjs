'use strict';
// Generated geometry only: no uploaded forestry map or scan is redistributed.
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={};vm.createContext(context);
vm.runInContext(fs.readFileSync('geostudio/web_app/static/raster_trace.js','utf8'),context);
const {simplifiedTracePerimeter,tracePreparePerimeter,traceFinishPerimeters,
  traceLandUses,selectedRasterOutline}=context;
function waveRectangle(amplitude){
  const ring=[];
  for(let x=0;x<=240;x++)ring.push([x,amplitude*Math.sin(x*Math.PI/15)]);
  for(let y=1;y<=100;y++)ring.push([240,y]);
  for(let x=239;x>=0;x--)ring.push([x,100]);
  for(let y=99;y>0;y--)ring.push([0,y]);
  return ring;
}
function distance(p,a,b){
  const dx=b[0]-a[0],dy=b[1]-a[1],t=Math.max(0,Math.min(1,
    ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)));
  return Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy);
}
function displacement(source,result){
  return Math.max(...source.map(p=>Math.min(...result.map((q,i)=>distance(p,q,result[(i+1)%result.length])))));
}
function area(points){return Math.abs(points.reduce((sum,p,i)=>{
  const q=points[(i+1)%points.length];return sum+p[0]*q[1]-p[1]*q[0];
},0)/2);}
function dense(points){
  const ring=[];
  points.forEach((a,i)=>{
    const b=points[(i+1)%points.length],n=Math.ceil(Math.hypot(b[0]-a[0],b[1]-a[1]));
    for(let j=0;j<n;j++)ring.push([a[0]+(b[0]-a[0])*j/n,a[1]+(b[1]-a[1])*j/n]);
  });return ring;
}
function simplify(ring,tolerance=2.5,fixed=()=>false){
  return simplifiedTracePerimeter(ring,ring,fixed,tolerance,true);
}
function pointSet(points){return JSON.stringify(Array.from(points,p=>p.map(n=>Number(n.toFixed(9)))).sort((a,b)=>a[0]-b[0]||a[1]-b[1]));}
function hasPoint(points,expected){return points.some(p=>p[0]===expected[0]&&p[1]===expected[1]);}
function inside(p,ring){
  let found=false;
  for(let i=0,j=ring.length-1;i<ring.length;j=i++){
    const a=ring[i],b=ring[j];
    if((a[1]>p[1])!==(b[1]>p[1])&&p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0])found=!found;
  }return found;
}
function sharedFixture(){
  const lower=[],upper=[];
  for(let y=0;y<=160;y++){
    const p=[100+3*Math.sin(y*Math.PI/20),y];
    if(y===0||y===80||y===160)p[0]=100;
    if(y<=80)upper.push(p);if(y>=80)lower.push(p);
  }
  return [ [[0,0],...upper,...lower.slice(1),[0,160]],
    [[100,0],[200,0],[200,80],...upper.slice().reverse().slice(0,-1)],
    [[100,80],[200,80],[200,160],...lower.slice().reverse().slice(0,-1)] ];
}
function commonPrepared(rings,tolerance){
  const cache=new Map(),fixed=p=>(p[0]===100&&[0,80,160].includes(p[1]))||(p[0]===200&&p[1]===80);
  const prepared=rings.map(ring=>tracePreparePerimeter(ring,fixed,tolerance,cache));
  return traceFinishPerimeters(prepared,cache);
}
function raster(){
  const width=180,height=140,pixels=new Uint8ClampedArray(width*height*4),forest=new Uint8ClampedArray(pixels.length);
  for(let i=0;i<width*height;i++)pixels.set([255,255,255,255],4*i);
  for(let y=20;y<=120;y++)for(let x=20;x<=160;x++)pixels.set([205,225,175,255],4*(y*width+x));
  function put(x,y,color,radius=1){for(let dy=-radius;dy<=radius;dy++)for(let dx=-radius;dx<=radius;dx++)pixels.set([...color,255],4*((y+dy)*width+x+dx));}
  for(let x=20;x<=160;x++){put(x,20,[30,30,30]);put(x,120,[30,30,30]);}
  for(let y=20;y<=120;y++){put(20,y,[30,30,30]);put(160,y,[30,30,30]);put(90+Math.round(2*Math.sin((y-20)*Math.PI/20)),y,[180,35,40],0);}
  return {pixels,forest,width,height};
}
const cases={
  waves_become_supported_straight_sides(){
    const ring=waveRectangle(3),straight=simplify(ring,4),precise=simplify(ring,1);
    assert.equal(straight.length,4,'A supported wavy side should become one straight segment');
    assert.ok(displacement(ring,straight)<=4+1e-8);
    assert.ok(displacement(straight,ring)<=4+1e-8);
    assert.ok(precise.length>4,'A smaller explicit tolerance must not silently accept a larger change');
    assert.ok(displacement(ring,precise)<=1+1e-8);
    for(const corner of [[0,0],[240,0],[240,100],[0,100]])
      assert.ok(Math.min(...straight.map(p=>Math.hypot(p[0]-corner[0],p[1]-corner[1])))<1,
        'Fit the ink centre instead of copying a pen-wave extremum');
  },
  genuine_bend_and_concavity_are_retained(){
    const bend=dense([[0,0],[100,0],[200,8],[300,0],[400,0],[400,100],[0,100]]);
    const result=simplify(bend,2.5);
    assert.ok(result.length>=5,'Do not force all fields to quadrilaterals');
    assert.ok(displacement(bend,result)<=2.5+1e-8);
    assert.ok(Math.min(...result.map(p=>Math.hypot(p[0]-200,p[1]-8)))<=2.5);
    const concave=dense([[0,0],[120,0],[120,100],[70,100],[70,45],[40,45],[40,100],[0,100]]);
    const notch=simplify(concave,4);
    assert.ok(notch&&notch.length>=8);
    assert.equal(inside([55,80],notch),false,'A real notch remains outside the field');
    assert.ok(displacement(concave,notch)<=4+1e-8);
  },
  fixed_junction_survives_quad_like_outline(){
    const ring=[[0,0],[100,0],[100,100],[50,102],[0,100]];
    const result=simplify(ring,2.5,p=>p[0]===50&&p[1]===102);
    assert.ok(hasPoint(result,[50,102]),'A shared junction must not disappear through a four-corner shortcut');
    assert.ok(displacement(ring,result)<=2.5+1e-8);
  },
  canonical_direction_and_ring_start(){
    const ring=waveRectangle(3),expected=pointSet(simplify(ring,4));
    for(const source of [ring.slice().reverse(),ring.slice(57).concat(ring.slice(0,57)),
      ring.slice(87).concat(ring.slice(0,87)).reverse()])assert.equal(pointSet(simplify(source,4)),expected);
  },
  shared_edges_are_identical_and_topology_has_no_slivers(){
    const source=sharedFixture(),result=commonPrepared(source,4);
    assert.ok(result.every(Boolean));
    for(const ring of result)assert.ok(hasPoint(ring,[100,80]),'All three fields share exactly one junction');
    assert.deepEqual(Array.from(result,p=>p.length),[5,4,4]);
    const edges=new Map();
    for(const ring of result)ring.forEach((p,i)=>{
      const q=ring[(i+1)%ring.length],key=JSON.stringify([Array.from(p),Array.from(q)].sort((a,b)=>a[0]-b[0]||a[1]-b[1]));
      edges.set(key,(edges.get(key)||0)+1);
    });
    assert.equal([...edges.values()].filter(n=>n===2).length,3);
    assert.ok(Math.abs(result.reduce((sum,r)=>sum+area(r),0)-32000)<1e-6);
    for(let y=3.25;y<160;y+=5)for(let x=3.25;x<200;x+=5)
      assert.equal(result.filter(r=>inside([x,y],r)).length,1,'No gaps or overlaps in the shared partition');
    const reordered=commonPrepared([source[2].slice().reverse(),source[0].slice().reverse(),source[1]],4);
    assert.equal(pointSet(result[0]),pointSet(reordered[1]));
    assert.equal(pointSet(result[1]),pointSet(reordered[2]));
    assert.equal(pointSet(result[2]),pointSet(reordered[0]));
  },
  narrow_fields_and_zero_tolerance_do_not_collapse(){
    const strip=dense([[0,0],[300,0],[300,6],[0,6]]),result=simplify(strip,8);
    assert.equal(result.length,4);assert.ok(Math.abs(area(result)-1800)<1e-6);
    const exact=simplify(dense([[0,0],[100,0],[100,100],[0,100]]),0);
    assert.equal(exact.length,4);assert.equal(area(exact),10000);
  },
  red_divider_is_preserved_and_merged_selection_uses_chosen_tolerance(){
    const {pixels,forest,width,height}=raster();
    const trace=traceLandUses(pixels,forest,width,height,5,4);
    assert.equal(trace.shapes.size,2,'A true red divider separates two proposed fields');
    assert.equal(trace.tolerance,4);
    const ids=Array.from(trace.shapes.keys()),rings=Array.from(trace.shapes.values(),s=>s.points);
    assert.ok(rings.every(p=>p.length===4));
    const shared=rings[0].filter(p=>rings[1].some(q=>p[0]===q[0]&&p[1]===q[1]));
    assert.equal(shared.length,2,'Both sides use exactly the same divider endpoints');
    const merged=selectedRasterOutline(trace,new Set(ids),width,height,new Map());
    assert.equal(merged.length,4);assert.ok(area(merged)>area(rings[0])*1.9);
    const outerCorner=rings[0].find(p=>p[0]<50&&p[1]<50),moved=[outerCorner[0]-3,outerCorner[1]-4];
    const edited=new Map([[outerCorner.join(','),moved]]);
    const retained=selectedRasterOutline(trace,new Set(ids),width,height,edited);
    assert.ok(retained.some(p=>p[0]===moved[0]&&p[1]===moved[1]),'A manual edit of a fitted corner survives merging adjacent fragments');
    const clamped=traceLandUses(pixels,forest,width,height,5,Infinity);
    assert.equal(clamped.tolerance,2.5);
  },
};
const selected=process.argv[2];assert.ok(cases[selected],`Unknown geometry case: ${selected}`);
cases[selected]();console.log(`PASS ${selected}`);
