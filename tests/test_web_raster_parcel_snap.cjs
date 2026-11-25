'use strict';
// Synthetic parcel geometry only; no user MAP/raster is redistributed.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const context={};vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../geostudio/web_app/static/raster_parcel_snap.js'),'utf8'),context);
const {buildIndex,snapRing,snapRings}=context.GeoStudioRasterParcelSnap;
const parcel=points=>({code:'5216',closed:true,geometry:[points]});
const line=points=>({code:'5216',closed:false,geometry:[points]});
const plain=value=>JSON.parse(JSON.stringify(value));
const shift=(ring,x,y)=>ring.map(p=>[p[0]+x,p[1]+y]);
function close(actual,expected,tolerance=1e-8){
  assert.equal(actual.length,expected.length);
  actual.forEach((p,i)=>p.forEach((v,k)=>assert.ok(Math.abs(v-expected[i][k])<=tolerance,
    `point ${i}, coordinate ${k}: ${v} versus ${expected[i][k]}`)));
}
function set(points){return JSON.stringify(plain(points).map(p=>p.map(v=>Number(v.toFixed(8)))).sort((a,b)=>a[0]-b[0]||a[1]-b[1]));}
function inside(p,ring){
  let result=false;
  for(let i=0,j=ring.length-1;i<ring.length;j=i++){
    const a=ring[i],b=ring[j];
    if((a[1]>p[1])!==(b[1]>p[1])&&p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0])result=!result;
  }
  return result;
}
const cases={
  translated_sides_use_exact_parcel_corners(){
    const original=[[0,0],[100,0],[100,80],[0,80]],reference=shift(original,2,1);
    const source=JSON.stringify(original),features=[parcel(reference)],before=JSON.stringify(features);
    const result=snapRing(original,buildIndex(features),{distance:3});
    close(result.points,reference);assert.equal(result.snappedEdges,4);
    assert.deepEqual(plain(result.sourceIndices),[0,1,2,3]);
    assert.equal(JSON.stringify(original),source);assert.equal(JSON.stringify(features),before);
    result.points[0][0]=999;assert.equal(original[0][0],0);assert.equal(reference[0][0],2);
  },
  native_5216_only_and_duplicate_edges(){
    const original=[[0,0],[100,0],[100,80],[0,80]],reference=shift(original,2,1);
    const correct=parcel(reference);correct.nativeGeometry=[reference];correct.geometry=[shift(reference,1000,1000)];
    const index=buildIndex([correct,parcel(reference.slice().reverse()),
      {...parcel(original),code:'5310'},{...parcel(original),code:'5220'},
      line([[NaN,0],[10,0]]),line([[5,5],[5,5]])]);
    assert.equal(index.size,4);close(snapRing(original,index,{distance:3}).points,reference);
    const ignored=buildIndex([{...parcel(reference),code:'5310'}]);
    assert.equal(ignored.size,0);close(snapRing(original,ignored,{distance:3}).points,original);
  },
  contiguous_parcel_edges_keep_real_intermediate_nodes(){
    const original=[[0,0],[120,0],[120,60],[0,60]];
    const features=[line([[-10,2],[40,2]]),line([[40,2],[80,2]]),line([[80,2],[130,2]]),
      line([[130,2],[-10,2]])]; // one neighbouring parcel stores the same side without T nodes
    const index=buildIndex(features),result=snapRing(original,index,{distance:3});
    close(result.points,[[0,2],[40,2],[80,2],[120,2],[120,60],[0,60]]);
    assert.equal(result.snappedEdges,1);assert.deepEqual(plain(result.sourceIndices),[0,null,null,1,2,3]);
    const gap=buildIndex([line([[-10,2],[49,2]]),line([[50,2],[130,2]])]);
    close(snapRing(original,gap,{distance:3}).points,original);
  },
  gently_bent_reference_is_followed_without_shortcuts(){
    const original=[[0,0],[120,0],[120,60],[0,60]];
    const index=buildIndex([line([[-10,2],[40,2],[80,3],[130,2]])]);
    const result=snapRing(original,index,{distance:3});
    close(result.points,[[0,2],[40,2],[80,3],[120,2.2],[120,60],[0,60]]);
    assert.equal(result.snappedEdges,1);
  },
  parallel_ambiguity_is_left_for_review(){
    const original=[[0,0],[100,0],[100,80],[0,80]];
    const ambiguous=buildIndex([line([[-10,-1],[110,-1]]),line([[-10,1],[110,1]])]);
    const result=snapRing(original,ambiguous,{distance:3});
    close(result.points,original);assert.equal(result.snappedEdges,0);assert.equal(result.reason,'ambiguous');
    const clear=buildIndex([line([[-10,.2],[110,.2]]),line([[-10,2.8],[110,2.8]])]);
    close(snapRing(original,clear,{distance:3}).points,[[0,.2],[100,.2],[100,80],[0,80]]);
  },
  crossings_distant_sides_and_short_contact_do_not_snap(){
    const original=[[0,0],[100,0],[100,80],[0,80]];
    for(const features of [[line([[50,-100],[50,100]])],
      [line([[-10,5],[110,5]])],[line([[-5,2],[5,2]])],
      [line([[-10,-20],[110,20]])]]){
      const result=snapRing(original,buildIndex(features),{distance:3});
      close(result.points,original);assert.equal(result.snappedEdges,0);
    }
  },
  shared_t_junction_and_internal_divider_are_preserved(){
    const index=buildIndex([line([[2,-10],[2,110]])]);
    const rings=[[[0,0],[100,0],[100,50],[0,50]],
      [[0,50],[100,50],[100,100],[0,100]],
      [[-100,0],[0,0],[0,50],[0,100],[-100,100]]];
    const results=rings.map(ring=>snapRing(ring,index,{distance:3}));
    for(const result of results)assert.ok(result.points.some(p=>p[0]===2&&p[1]===50));
    close(results[0].points,[[2,0],[100,0],[100,50],[2,50]]);
    close(results[1].points,[[2,50],[100,50],[100,100],[2,100]]);
    close(results[2].points,[[-100,0],[2,0],[2,50],[2,100],[-100,100]]);
    for(let y=1.125;y<100;y+=6.5)for(let x=-99.125;x<100;x+=6.5)
      assert.equal(results.filter(result=>inside([x,y],result.points)).length,1,'Shared partition has no gap or overlap');
    // The unreferenced divider at y=50 must not acquire any bend or parcel split.
    for(const result of results.slice(0,2))assert.ok(result.points.some(p=>p[0]===100&&p[1]===50));
  },
  order_direction_and_repeated_calls_are_deterministic(){
    const original=[[0,0],[120,0],[120,60],[0,60]];
    const features=[line([[-10,2],[40,2]]),line([[40,2],[80,3],[130,2]])];
    const index=buildIndex(features),expected=snapRing(original,index,{distance:3});
    for(const ring of [original.slice().reverse(),original.slice(2).concat(original.slice(0,2))])
      assert.equal(set(snapRing(ring,index,{distance:3}).points),set(expected.points));
    const reversed=features.slice().reverse().map(feature=>line(feature.geometry[0].slice().reverse()));
    assert.equal(set(snapRing(original,buildIndex(reversed),{distance:3}).points),set(expected.points));
    assert.equal(set(snapRing(original,index,{distance:3}).points),set(expected.points));
  },
  manual_locks_are_kept_and_report_original_corner_indices(){
    const original=[[0,0],[100,0],[100,100],[0,100]];
    const index=buildIndex([line([[-10,2],[110,2]]),line([[-10,102],[110,102]]),
      line([[2,-10],[2,110]]),line([[102,-10],[102,110]])]);
    const result=snapRing(original,index,{distance:3,locked:[[0,0]]});
    close(result.points,[[0,0],[102,0],[102,102],[0,102]]);assert.equal(result.snappedEdges,2);
    assert.deepEqual(plain(result.sourceIndices),[0,1,2,3]);
    const disabled=snapRing(original,index,{distance:0});
    close(disabled.points,original);assert.deepEqual(plain(disabled.sourceIndices),[0,1,2,3]);
  },
  area_limit_and_narrow_notch_prevent_invalid_snaps(){
    const thin=[[0,0],[100,0],[100,10],[0,10]];
    const enlarged=snapRing(thin,buildIndex([line([[-10,-2],[110,-2]])]),{distance:3});
    close(enlarged.points,thin);assert.equal(enlarged.reason,'topology');
    const notch=[[0,0],[100,0],[100,100],[52,100],[52,50],[50,50],[50,100],[0,100]];
    const collapsed=snapRing(notch,buildIndex([line([[51,40],[51,110]])]),{distance:3});
    close(collapsed.points,notch);assert.equal(collapsed.snappedEdges,0);
    const crossing=[[0,0],[100,100],[100,0],[0,100]];
    const invalid=snapRing(crossing,buildIndex([line([[0,2],[100,2]])]),{distance:3});
    close(invalid.points,crossing);assert.equal(invalid.reason,'invalid');
  },
  million_metre_coordinates_keep_subpixel_precision(){
    const original=[[7500320,-5800600],[7501920,-5801000],[7501600,-5803000],[7500000,-5802600]];
    const reference=shift(original,.6,-.4),index=buildIndex([parcel(reference)]);
    const result=snapRing(original,index,{distance:2.5});
    close(result.points,reference);assert.equal(result.snappedEdges,4);
    for(let turn=0;turn<3;turn++)close(snapRing(original,index,{distance:2.5}).points,reference);
  },
  shared_area_veto_is_local_and_keeps_neighbours_together(){
    const thin=[[0,0],[10,0],[10,100],[0,100]];
    const wide=[[10,0],[110,0],[110,100],[10,100]];
    const distant=[[500,0],[600,0],[600,100],[500,100]];
    const index=buildIndex([line([[12,-10],[12,110]]),line([[112,-10],[112,110]]),parcel(shift(distant,2,1))]);
    assert.equal(snapRing(thin,index,{distance:3}).reason,'topology');
    assert.ok(snapRing(wide,index,{distance:3}).snappedEdges>0);
    const results=snapRings([thin,wide,distant],index,{distance:3});
    close(results[0].points,thin);
    close(results[1].points,[[10,0],[112,0],[112,100],[10,100]]);
    close(results[2].points,shift(distant,2,1));
    assert.equal(results[1].snappedEdges,1,'An unrelated exterior side remains snapped after a shared-side veto');
    assert.equal(results[2].snappedEdges,4,'A remote field remains independent of a local veto');
    for(let y=1.125;y<100;y+=6.5)for(let x=.125;x<110;x+=2.5)
      assert.equal(results.slice(0,2).filter(result=>inside([x,y],result.points)).length,1);
    const reordered=snapRings([distant.slice().reverse(),wide.slice().reverse(),thin.slice().reverse()],index,{distance:3});
    assert.equal(set(reordered[0].points),set(results[2].points));
    assert.equal(set(reordered[1].points),set(results[1].points));
    assert.equal(set(reordered[2].points),set(results[0].points));
  },
  shared_path_veto_catches_bulges_with_unchanged_endpoints(){
    const thin=[[0,0],[10,0],[10,100],[0,100]],wide=[[10,0],[110,0],[110,100],[10,100]];
    const index=buildIndex([line([[10,0],[12,20],[12,80],[10,100]]),line([[112,-10],[112,110]])]);
    const narrow=snapRing(thin,index,{distance:3}),broad=snapRing(wide,index,{distance:3});
    assert.equal(narrow.reason,'topology');assert.ok(broad.points.some(p=>p[0]===12&&p[1]===20));
    assert.ok(broad.points.some(p=>p[0]===10&&p[1]===0));
    assert.ok(broad.points.some(p=>p[0]===10&&p[1]===100));
    const result=snapRings([thin,wide],index,{distance:3});
    close(result[0].points,thin);
    close(result[1].points,[[10,0],[112,0],[112,100],[10,100]]);
    assert.equal(result[1].snappedEdges,1);
  },
  shared_iteration_limit_freezes_only_shared_geometry(){
    const thin=[[0,0],[10,0],[10,100],[0,100]],wide=[[10,0],[110,0],[110,100],[10,100]];
    const index=buildIndex([line([[12,-10],[12,110]]),line([[112,-10],[112,110]])]);
    const result=snapRings([thin,wide],index,{distance:3,maxIterations:1});
    close(result[0].points,thin);close(result[1].points,[[10,0],[112,0],[112,100],[10,100]]);
    assert.ok(result.every(item=>item.topologyGuard==='iteration-limit'));
    assert.equal(result[1].snappedEdges,1);
    assert.deepEqual(plain(result[1].sourceIndices),[0,1,2,3]);
  },
  shared_points_have_identical_numbers_after_epsilon_normalization(){
    const left=[[0,0],[10,0],[10,100],[0,100]],right=[[10+2e-8,0],[110,0],[110,100],[10+2e-8,100]];
    const result=snapRings([left,right],buildIndex([]),{distance:3});
    assert.deepEqual(plain(result[0].points[1]),plain(result[1].points[0]));
    assert.deepEqual(plain(result[0].points[2]),plain(result[1].points[3]));
    const edges=new Map();
    for(const item of result)item.points.forEach((p,i)=>{
      const q=item.points[(i+1)%item.points.length],id=[p.join(','),q.join(',')].sort().join('|');
      edges.set(id,(edges.get(id)||0)+1);
    });
    assert.equal([...edges.values()].filter(count=>count===2).length,1,'Exact edge cancellation sees the shared side');
    assert.equal(right[0][0],10+2e-8,'Normalization must not mutate the source geometry');
  },
  shallow_native_corners_do_not_trigger_false_shared_veto(){
    // The corner [35,30] is shallow enough that both side searches can include
    // it. Its source index must belong to the native bend, not a projection
    // onto the neighbouring side which merely happens to precede that bend.
    const pair=[[[0,20],[53,11],[35,30],[17,42]],
      [[53,11],[94,-8],[113,37],[35,30]]];
    const references=[];
    for(let row=0;row<4;row++)for(let column=0;column<5;column++)
      for(const ring of pair)references.push(shift(ring,column*200,row*150));
    const source=references.map(ring=>shift(ring,.6,-.4)),index=buildIndex(references.map(parcel));
    const individual=snapRing(source[0],index,{distance:2.5});
    close(individual.points,references[0]);assert.deepEqual(plain(individual.sourceIndices),[0,1,2,3]);
    const results=snapRings(source,index,{distance:2.5});
    assert.equal(results.length,40);
    results.forEach((result,i)=>{
      close(result.points,references[i]);assert.equal(result.snappedEdges,4);
      assert.deepEqual(plain(result.sourceIndices),[0,1,2,3]);
    });
    const reverse=snapRings(source.slice().reverse().map(ring=>ring.slice().reverse()),index,{distance:2.5});
    reverse.forEach((result,i)=>assert.equal(set(result.points),set(references[references.length-1-i])));
  },
  supported_shared_anchors_can_move_a_short_interior_field(){
    const small=[[0,0],[4,0],[2,3]];
    const reference=[[[0,0],[-50,0],[-50,-50],[0,-50]],
      [[4,0],[54,0],[54,-50],[4,-50]],[[2,3],[52,3],[52,53],[2,53]]];
    // Only the surrounding large polygons are 5216. The three short sides of
    // the small field are internal divisions, never new parcel references.
    const index=buildIndex(reference.map(parcel)),rings=[small,...reference].map(ring=>shift(ring,.6,-.4));
    const individual=snapRing(rings[0],index,{distance:2.5});
    close(individual.points,rings[0]);assert.equal(individual.snappedEdges,0);
    const results=snapRings(rings,index,{distance:2.5});
    close(results[0].points,small);assert.equal(results[0].snappedEdges,0);
    assert.equal(results[0].reason,'shared-corner');
    assert.deepEqual(plain(results[0].sourceIndices),[0,1,2]);
    reference.forEach((ring,i)=>close(results[i+1].points,ring));
    const locked=snapRings(rings,index,{distance:2.5,locked:[rings[0][0]]});
    assert.deepEqual(plain(locked[0].points[0]),rings[0][0]);
    assert.deepEqual(plain(locked[1].points[0]),rings[0][0]);
  },
  parcel_index_handles_3555_edges_without_global_quadratic_search(){
    const features=[];
    for(let row=0;row<45;row++)for(let col=0;col<79;col++)
      features.push(line([[col*100,row*50],[(col+1)*100,row*50]]));
    const start=performance.now(),index=buildIndex(features);assert.equal(index.size,3555);
    for(let col=2;col<22;col++){
      const x=col*100,ring=[[x,1001],[x+200,1001],[x+200,1020],[x,1020]];
      const result=snapRing(ring,index,{distance:3});
      close(result.points,[[x,1000],[x+100,1000],[x+200,1000],[x+200,1020],[x,1020]]);
      assert.equal(result.snappedEdges,1);
    }
    const elapsed=performance.now()-start;
    assert.ok(elapsed<10000,`3555 edges and 20 selections took ${elapsed.toFixed(0)} ms`);
    console.log(`3555 reference edges, 20 selections: ${elapsed.toFixed(1)} ms`);
  },
};
const selected=process.argv[2];assert.ok(cases[selected],`Unknown parcel snap case: ${selected}`);
cases[selected]();console.log(`PASS ${selected}`);
