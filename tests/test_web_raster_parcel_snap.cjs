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
function strokeFixture(half,options={}){
  const width=260,height=200,reference=options.reference||[[30,30],[210,30],[210,150],[30,150]];
  const pixels=new Uint8ClampedArray(width*height*4);pixels.fill(255);
  const mask=new Uint8ClampedArray(pixels.length),offset=options.offset??half;
  const plot=(x,y,radius=half)=>{
    for(let v=Math.round(y)-radius;v<=Math.round(y)+radius;v++)
      for(let u=Math.round(x)-radius;u<=Math.round(x)+radius;u++)
        if(u>=0&&v>=0&&u<width&&v<height)pixels.set([25,25,25,255],4*(v*width+u));
  };
  reference.forEach((a,i)=>{
    const b=reference[(i+1)%reference.length],steps=Math.ceil(Math.hypot(b[0]-a[0],b[1]-a[1])*2);
    for(let j=0;j<=steps;j++)plot(a[0]+offset+(b[0]-a[0])*j/steps,a[1]+(b[1]-a[1])*j/steps);
  });
  if(options.annotation)plot(120+offset,30,12);
  if(!context.traceLandUses)vm.runInContext(fs.readFileSync(path.join(__dirname,'../geostudio/web_app/static/raster_trace.js'),'utf8'),context);
  if(!context.GeoStudioRasterTraceMetrics)vm.runInContext(fs.readFileSync(path.join(__dirname,'../geostudio/web_app/static/raster_trace_metrics.js'),'utf8'),context);
  const trace=context.traceLandUses(pixels,mask,width,height,5,2.5);
  const metric=context.GeoStudioRasterTraceMetrics.estimateStrokeRadius(pixels,width,height,trace.shapes,2.5,mask);
  return {pixels,mask,width,height,reference,trace,metric};
}
function onReference(result,reference){
  function distanceTo(p,a,b){
    const dx=b[0]-a[0],dy=b[1]-a[1],t=Math.max(0,Math.min(1,
      ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy)));
    return Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy);
  }
  for(let i=0;i<result.length;i++){
    const a=result[i],b=result[(i+1)%result.length],middle=[(a[0]+b[0])/2,(a[1]+b[1])/2];
    for(const p of [a,middle])assert.ok(Math.min(...reference.map((q,j)=>distanceTo(p,q,reference[(j+1)%reference.length])))<1e-7,
      `Fitted side must follow actual reference edges: ${JSON.stringify(result)}`);
  }
  for(const corner of reference)assert.ok(result.some(p=>Math.hypot(p[0]-corner[0],p[1]-corner[1])<1e-7),
    `Missing native corner ${corner}: ${JSON.stringify(result)}`);
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
  increasing_search_distance_keeps_clear_nearby_partition_fits(){
    // A greater maximum search distance must not disable the already clear
    // 1 m correction on short sides, or propagate that rejection to every
    // adjoining field through the shared-border safety check.
    const rings=Array.from({length:6},(_,i)=>[[i*10,0],[(i+1)*10,0],[(i+1)*10,80],[i*10,80]]);
    const reference=rings.map(ring=>shift(ring,1,1)),index=buildIndex(reference.map(parcel));
    for(const precisionDistance of [0,3])for(const distance of [1.5,3,5,10,20]){
      const results=snapRings(rings,index,{distance,precisionDistance});
      assert.equal(results.diagnostics.referenceEdges,19);
      assert.equal(results.diagnostics.changedRings,6);
      assert.equal(results.diagnostics.matchedSides,24);
      results.forEach((result,i)=>{
        close(result.points,reference[i]);assert.equal(result.snappedEdges,4);
        assert.equal(result.diagnostics.referenceEdges,19);
        assert.equal(result.diagnostics.matchedSides,4);
        assert.equal(result.diagnostics.movedVertices,4);
        assert.ok(Math.abs(result.diagnostics.maxDisplacement-Math.SQRT2)<1e-8);
      });
      for(let i=1;i<results.length;i++){
        const shared=results[i].points.filter(p=>results[i-1].points.some(q=>p[0]===q[0]&&p[1]===q[1]));
        assert.equal(shared.length,2,'Adjacent fields must use exactly identical reference endpoints');
      }
    }
    snapRings(rings,index,{distance:.5}).forEach((result,i)=>close(result.points,rings[i]));
    const aligned=snapRings(reference,index,{distance:20,precisionDistance:3});
    assert.equal(aligned.diagnostics.matchedSides,24,'Already exact sides count as referenced, although no point moves');
    assert.equal(aligned.diagnostics.changedRings,0);
    assert.equal(aligned.diagnostics.maxDisplacement,0);
  },
  wide_search_keeps_nearest_track_without_hiding_real_ambiguity(){
    const original=[[0,0],[100,0],[100,80],[0,80]];
    const clear=buildIndex([line([[-10,.2],[110,.2]]),line([[-10,2.8],[110,2.8]])]);
    for(const distance of [3,5,10,20]){
      const result=snapRing(original,clear,{distance});
      close(result.points,[[0,.2],[100,.2],[100,80],[0,80]]);
      assert.equal(result.diagnostics.matchedSides,1);
      assert.equal(result.diagnostics.maxDisplacement,.2);
    }
    const equal=buildIndex([line([[-10,-1],[110,-1]]),line([[-10,1],[110,1]])]);
    const result=snapRing(original,equal,{distance:20});
    close(result.points,original);
    assert.equal(result.reason,'ambiguous');
    assert.equal(result.diagnostics.ambiguousSides,1);
    assert.equal(result.diagnostics.reasons.ambiguous,1);
    const farther=buildIndex([line([[-10,8],[110,8]])]);
    close(snapRing(original,farther,{distance:3,precisionDistance:2.6}).points,original);
    const expanded=snapRing(original,farther,{distance:10,precisionDistance:2.6});
    close(expanded.points,[[0,8],[100,8],[100,80],[0,80]]);
    assert.equal(expanded.diagnostics.maxDisplacement,8,
      'The wider search must still admit an unambiguous reference beyond the measured stroke width');
  },
  dense_reference_corridor_is_bounded_and_reports_complexity(){
    const ring=[[0,0],[100,0],[100,80],[0,80]];
    const features=Array.from({length:400},(_,i)=>line([[-10,.01+i*.0001],[110,.01+i*.0001]]));
    const index=buildIndex(features);
    for(const distance of [3,20]){
      const result=snapRings([ring],index,{distance,precisionDistance:2.6});
      close(result[0].points,ring);
      assert.equal(result[0].diagnostics.reasons['too-many-candidates'],1);
      assert.equal(result.diagnostics.reasons['too-many-candidates'],1);
      assert.equal(result.diagnostics.referenceEdges,400);
      assert.equal(result.diagnostics.maxDisplacement,0);
    }
  },
  large_search_preserves_real_pixel_pipeline_for_adjacent_thick_strokes(){
    const width=380,height=500,pixelMetres=.2,pixels=new Uint8ClampedArray(width*height*4);
    pixels.fill(255);
    const mask=new Uint8ClampedArray(pixels.length);
    const pixelRings=Array.from({length:6},(_,i)=>[[35+i*50,35],[85+i*50,35],[85+i*50,435],[35+i*50,435]]);
    const plot=(x,y)=>{
      for(let v=Math.round(y)-2;v<=Math.round(y)+2;v++)for(let u=Math.round(x)-2;u<=Math.round(x)+2;u++)
        if(u>=0&&v>=0&&u<width&&v<height)pixels.set([25,25,25,255],4*(v*width+u));
    };
    // Five-pixel ink, displaced by 1 m from its vector reference. Analyse
    // actual pixels instead of handing the fitter already ideal rectangles.
    for(const ring of pixelRings)ring.forEach((a,i)=>{
      const b=ring[(i+1)%ring.length],steps=Math.ceil(Math.hypot(b[0]-a[0],b[1]-a[1])*2);
      for(let j=0;j<=steps;j++)plot(a[0]+5+(b[0]-a[0])*j/steps,a[1]+5+(b[1]-a[1])*j/steps);
    });
    if(!context.traceLandUses)vm.runInContext(fs.readFileSync(path.join(__dirname,'../geostudio/web_app/static/raster_trace.js'),'utf8'),context);
    const trace=context.traceLandUses(pixels,mask,width,height,5,2.5);
    assert.equal(trace.shapes.size,6);
    if(!context.GeoStudioRasterTraceMetrics)vm.runInContext(fs.readFileSync(path.join(__dirname,'../geostudio/web_app/static/raster_trace_metrics.js'),'utf8'),context);
    const metric=context.GeoStudioRasterTraceMetrics.estimateStrokeRadius(pixels,width,height,trace.shapes,2.5,mask);
    assert.ok(metric?.radiusPixels>0);
    const reference=pixelRings.map(ring=>ring.map(p=>p.map(v=>v*pixelMetres)));
    const rings=[...trace.shapes.values()].map(shape=>shape.points.map(p=>p.map(v=>v*pixelMetres)))
      .sort((a,b)=>Math.min(...a.map(p=>p[0]))-Math.min(...b.map(p=>p[0])));
    const index=buildIndex(reference.map(parcel));
    for(const distance of [3,5,10,20]){
      const results=snapRings(rings,index,{distance,precisionDistance:metric.radiusPixels*pixelMetres});
      results.forEach((result,i)=>onReference(result.points,reference[i]));
      for(let i=1;i<results.length;i++){
        const shared=results[i].points.filter(p=>results[i-1].points.some(q=>p[0]===q[0]&&p[1]===q[1]));
        assert.ok(shared.length>=2,'Both independently selected fields must have one identical shared boundary');
      }
    }
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
  supported_shared_projection_recovers_a_neighbours_raster_bevel(){
    const left=[[-20,0],[2,0],[2,10],[-20,10]];
    const right=[[2,0],[2.5,1],[20,5],[20,10],[2,10]];
    const expectedLeft=[[-20,0],[0,0],[0,10],[-20,10]];
    const expectedRight=[[0,0],[2.5,1],[20,5],[20,10],[0,10]];
    for(const [dx,dy] of [[0,0],[5500000,7500000]]){
      const rings=[left,right].map(ring=>shift(ring,dx,dy));
      const index=buildIndex([line(shift([[0,-20],[0,30]],dx,dy))]);
      const before=JSON.stringify(rings);
      // The short raster bevel would intersect the reference outside the
      // range. Its neighbour supplies the one shared, supported projection.
      assert.equal(snapRing(rings[1],index,{distance:2.1}).snappedEdges,0);
      const result=snapRings(rings,index,{distance:2.1});
      close(result[0].points,shift(expectedLeft,dx,dy));
      close(result[1].points,shift(expectedRight,dx,dy));
      assert.equal(result[0].snappedEdges,1);assert.equal(result[1].snappedEdges,1);
      assert.deepEqual(plain(result[0].points[1]),plain(result[1].points[0]));
      assert.deepEqual(plain(result[0].points[2]),plain(result[1].points[4]));
      const reverse=snapRings(rings.slice().reverse().map(ring=>ring.slice().reverse()),index,{distance:2.1});
      assert.equal(set(reverse[0].points),set(result[1].points));
      assert.equal(set(reverse[1].points),set(result[0].points));
      for(let y=.125;y<10;y+=.5)for(let x=-19.125;x<20;x+=.5)
        assert.ok(result.filter(item=>inside([x+dx,y+dy],item.points)).length<=1,
          'The recovered common side must not introduce area overlap');
      assert.equal(JSON.stringify(rings),before);
    }
  },
  propagated_shared_projections_respect_manual_locks(){
    const left=[[-20,0],[2,0],[2,10],[-20,10]];
    const right=[[2,0],[2.5,1],[20,5],[20,10],[2,10]];
    const index=buildIndex([line([[0,-20],[0,30]])]);
    const result=snapRings([left,right],index,{distance:2.1,locked:[[2,0]]});
    close(result[0].points,left);close(result[1].points,right);
    assert.equal(result.diagnostics.movedVertices,0);
  },
  same_track_shared_projections_use_one_nearest_point(){
    // Different exterior raster tangents create different intersections with
    // the same straight cadastral track. Pick its closest shared position,
    // retaining the complete native path and every original source index.
    for(const depth of [-5,-.2])for(const [dx,dy] of [[0,0],[5500000,7500000]]){
      const left=shift([[-20,depth],[2,0],[2,10],[-20,10]],dx,dy);
      const right=shift([[2,0],[20,0],[20,10],[2,10]],dx,dy);
      const index=buildIndex([line(shift([[0,-20],[0,5]],dx,dy)),line(shift([[0,5],[0,30]],dx,dy))]);
      const independent=[left,right].map(ring=>snapRing(ring,index,{distance:3}));
      assert.equal(independent[0].snappedEdges,1);assert.equal(independent[1].snappedEdges,1);
      const leftTarget=independent[0].points[independent[0].sourceIndices.indexOf(1)];
      const rightTarget=independent[1].points[independent[1].sourceIndices.indexOf(0)];
      assert.ok(Math.abs(leftTarget[1]-rightTarget[1])>.01);
      const result=snapRings([left,right],index,{distance:3});
      close(result[0].points,shift([[-20,depth],[0,0],[0,5],[0,10],[-20,10]],dx,dy));
      close(result[1].points,shift([[0,0],[20,0],[20,10],[0,10],[0,5]],dx,dy));
      assert.deepEqual(plain(result[0].points.slice(1,4)),
        plain([result[1].points[0],...result[1].points.slice(3).reverse()]));
      assert.equal(result.diagnostics.matchedSides,2);
      assert.ok(result.diagnostics.maxDisplacement<=3);
      const reverse=snapRings([right.slice().reverse(),left.slice().reverse()],index,{distance:3});
      assert.equal(set(reverse[0].points),set(result[1].points));
      assert.equal(set(reverse[1].points),set(result[0].points));
      for(const options of [{distance:1.5},{distance:3,locked:[left[1]]}]){
        const fixed=snapRings([left,right],index,options);
        close(fixed[0].points,left);close(fixed[1].points,right);
      }
    }
  },
  distinct_shared_projection_tracks_remain_unresolved(){
    const rings=[[[0,0],[50,0],[50,50],[0,50]],[[0,0],[-50,0],[-50,-50],[0,-50]]];
    const index=buildIndex([line([[-60,1],[0,1]]),line([[0,-1],[60,-1]])]);
    const independent=rings.map(ring=>snapRing(ring,index,{distance:3}));
    assert.deepEqual(plain(independent.map(result=>result.points[0])),[[0,-1],[0,1]]);
    const result=snapRings(rings,index,{distance:3});
    result.forEach((item,i)=>close(item.points,rings[i]));
    const reverse=snapRings(rings.slice().reverse().map(ring=>ring.slice().reverse()),index,{distance:3});
    reverse.forEach((item,i)=>assert.equal(set(item.points),set(rings[1-i])));
  },
  shared_projection_never_bridges_a_gap_in_reference_coverage(){
    const rings=[[[-20,20],[0,0],[0,30],[-20,30]],[[0,0],[20,20],[20,-30],[0,-30]]];
    const index=buildIndex([line([[-1,.5],[-1,40]]),line([[-1,-40],[-1,-.5]])]);
    const independent=rings.map(ring=>snapRing(ring,index,{distance:3}));
    assert.deepEqual(plain([independent[0].points[1],independent[1].points[0]]),[[-1,1],[-1,-1]]);
    // Collinearity alone is insufficient: [-1,0] has no native support.
    const result=snapRings(rings,index,{distance:3});
    result.forEach((item,i)=>close(item.points,rings[i]));
    const reverse=snapRings(rings.slice().reverse().map(ring=>ring.slice().reverse()),index,{distance:3});
    reverse.forEach((item,i)=>assert.equal(set(item.points),set(rings[1-i])));
  },
  dense_shared_junction_does_not_expand_projection_work(){
    const left=[[-20,-5],[2,0],[2,10],[-20,10]],right=[[2,0],[20,0],[20,10],[2,10]];
    // Diagonal clutter is harmless to the vertical side match, but would
    // otherwise become a quadratic search when reconciling the junction.
    const clutter=Array.from({length:600},(_,i)=>{
      const d=i/1000;return line([[1+d,.3],[1.1+d,.4]]);
    });
    const index=buildIndex([line([[0,-20],[0,30]]),...clutter]);
    const independent=[left,right].map(ring=>snapRing(ring,index,{distance:3}));
    assert.ok(independent.every(item=>item.snappedEdges===1));
    const result=snapRings([left,right],index,{distance:3});
    close(result[0].points,left);close(result[1].points,right);
    assert.ok(result.diagnostics.reasons['shared-veto']>0);
  },
  a_fit_cannot_reverse_a_short_unreferenced_connector(){
    // A narrow spur remains a simple ring with a small area change. Moving
    // its endpoint past the preceding vertex must nevertheless be rejected.
    const ring=[[0,0],[20,0],[20,20],[2,20],[1.5,19],[0,20]];
    for(const [dx,dy] of [[0,0],[5500000,7500000]]){
      const source=shift(ring,dx,dy),index=buildIndex([line(shift([[2.1,-10],[2.1,30]],dx,dy))]);
      const result=snapRing(source,index,{distance:3});
      close(result.points,source);assert.equal(result.reason,'topology');
      assert.equal(result.diagnostics.reasons.topology,1);
      const reverse=snapRing(source.slice().reverse(),index,{distance:3});
      assert.equal(set(reverse.points),set(source));assert.equal(reverse.reason,'topology');
    }
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
    assert.ok(results[1].diagnostics.rejectedSides>=1,'A shared-side veto must be visible in rejection diagnostics');
    assert.ok(results[1].diagnostics.reasons['shared-veto']>=1);
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
  thick_stroke_bevels_follow_the_real_parcel_corners(){
    const reference=[[0,0],[100,0],[100,80],[0,80]],index=buildIndex([parcel(reference)]);
    const ring=[[4,2],[96,2],[98,4],[98,76],[96,78],[4,78],[2,76],[2,4]];
    const expected=[[4,0],[96,0],[100,0],[100,4],[100,76],[100,80],
      [96,80],[4,80],[0,80],[0,76],[0,4],[0,0]];
    const result=snapRing(ring,index,{distance:3});
    close(result.points,expected);assert.equal(result.snappedEdges,8);
    assert.deepEqual(plain(result.sourceIndices),[0,1,null,2,3,null,4,5,null,6,7,null]);
    // All source corners retain their identity, while the inserted real
    // corners belong to the short bevel sides for UI/manual edit purposes.
    for(let i=0;i<ring.length;i++)assert.equal(result.sourceIndices.filter(j=>j===i).length,1);
    for(let i=0;i<result.points.length;i++){
      const a=result.points[i],b=result.points[(i+1)%result.points.length];
      assert.ok(a[0]===b[0]||a[1]===b[1],'No diagonal shortcut remains at a native corner');
    }
    for(const source of [ring.slice().reverse(),ring.slice(3).concat(ring.slice(0,3))])
      assert.equal(set(snapRing(source,index,{distance:3}).points),set(expected));
    const offset=[7500000,-5800000];
    close(snapRing(shift(ring,...offset),buildIndex([parcel(shift(reference,...offset))]),{distance:3}).points,
      shift(expected,...offset));
  },
  a_bevel_already_touching_both_sides_keeps_distinct_source_vertices(){
    const ring=[[2,0],[98,0],[100,2],[100,78],[98,80],[2,80],[0,78],[0,2]];
    const result=snapRing(ring,buildIndex([parcel([[0,0],[100,0],[100,80],[0,80]])]),{distance:3});
    assert.equal(result.snappedEdges,8);assert.equal(result.points.length,12);
    for(let i=0;i<ring.length;i++)close([result.points[result.sourceIndices.indexOf(i)]],[ring[i]]);
    for(const corner of [[0,0],[100,0],[100,80],[0,80]])
      assert.ok(result.points.some(p=>p[0]===corner[0]&&p[1]===corner[1]));
    // Previously both ends of each bevel could claim the same native corner,
    // produce a zero-length side, and veto the entire fit as invalid.
    assert.equal(new Set(result.points.map(p=>p.join(','))).size,result.points.length);
  },
  short_collinear_junction_edges_use_whole_side_evidence(){
    const ring=[[2,2],[7,2],[12,2],[17,2],[22,2],[22,50],[2,50]];
    const index=buildIndex([line([[-10,0],[110,0]]),line([[0,-100],[0,110]])]);
    close(snapRing(ring,index,{distance:3}).points,[[0,0],[7,0],[12,0],[17,0],[22,0],[22,50],[0,50]]);
    const results=snapRings([ring,[[7,2],[2,2],[2,-40],[100,-40],[100,2]]],index,{distance:3});
    assert.ok(results[0].points.some(p=>p[0]===7&&p[1]===0));
    assert.ok(results[1].points.some(p=>p[0]===7&&p[1]===0));
    const small=[[1,1],[5,1],[3,4]];
    close(snapRing(small,index,{distance:3}).points,small);
  },
  short_slanted_connector_uses_one_supported_straight_track(){
    const ring=[[0,1],[40,1],[42,2],[100,2],[100,60],[0,60]];
    const index=buildIndex([line([[-10,0],[110,0]])]);
    const result=snapRing(ring,index,{distance:3});
    close(result.points,[[0,0],[40,0],[42,0],[100,0],[100,60],[0,60]]);
    assert.equal(result.snappedEdges,3);
    const locked=snapRing(ring,index,{distance:3,locked:[[40,1]]});
    close([locked.points[locked.sourceIndices.indexOf(1)]],[[40,1]]);
    // The missing bridge is not invented through a gap in native geometry.
    const gap=buildIndex([line([[-10,0],[40,0]]),line([[42,0],[110,0]])]);
    const unfitted=snapRing(ring,gap,{distance:3});
    assert.ok(unfitted.snappedEdges<3);
  },
  bevel_recovery_requires_a_short_supported_native_join(){
    const ring=[[4,2],[96,2],[98,4],[98,76],[96,78],[4,78],[2,76],[2,4]];
    const reference=parcel([[0,0],[100,0],[100,80],[0,80]]),index=buildIndex([reference]);
    const locked=snapRing(ring,index,{distance:3,locked:[[96,2]]});
    close([locked.points[locked.sourceIndices.indexOf(1)]],[[96,2]]);
    const blocked=snapRing(ring,index,{distance:3,blockedEdges:[[ring[1],ring[2]]]});
    assert.ok(!blocked.points.some(p=>p[0]===100&&p[1]===0),'An explicitly blocked side cannot acquire a corner bridge');
    const longCut=[[10,0],[90,0],[100,10],[100,70],[90,80],[10,80],[0,70],[0,10]];
    close(snapRing(longCut,index,{distance:3}).points,longCut);
    const crossing=buildIndex([line([[-10,0],[110,0]]),line([[100,-10],[100,90]])]);
    const result=snapRing(ring,crossing,{distance:3});
    assert.ok(!result.points.some(p=>p[0]===100&&p[1]===0),'Crossing lines without a native corner do not justify a bevel');
  },
  a_fully_supported_narrow_field_can_recover_its_stroke_width(){
    const reference=[[0,0],[16,0],[16,100],[0,100]],ring=[[2,2],[14,2],[14,98],[2,98]];
    const index=buildIndex([parcel(reference)]),result=snapRing(ring,index,{distance:3});
    close(result.points,reference);assert.equal(result.snappedEdges,4);
    const partial=buildIndex([line([[0,0],[0,100]]),line([[16,0],[16,100]])]);
    const incomplete=snapRing(ring,partial,{distance:3});
    close(incomplete.points,ring);assert.equal(incomplete.reason,'topology');
    // Even a complete reference cannot expand a tiny raster region without a
    // bound, or consume a narrow arm hidden by a compensating area change.
    const excessive=[[2,2],[9,2],[9,98],[2,98]];
    close(snapRing(excessive,buildIndex([parcel([[0,0],[11,0],[11,100],[0,100]])]),{distance:3}).points,excessive);
  },
  native_corners_use_the_diagonal_of_two_supported_distance_bands(){
    const reference=[[30,30],[210,30],[210,150],[30,150]];
    const ring=shift(reference,3,1),index=buildIndex([parcel(reference)]);
    close(snapRing(ring,index,{distance:3}).points,reference);
    // The wider corner allowance must not turn one isolated line into a wider
    // lateral snap corridor or override the explicit three-metre side range.
    const tooFar=shift(reference,3.1,0);
    close(snapRing(tooFar,buildIndex([line([[30,10],[30,180]])]),{distance:3}).points,tooFar);
  },
  real_pixel_strokes_overlapping_5216_snap_to_its_complete_perimeter(){
    let previous=0;
    for(const half of [1,2,3,5,8]){
      const fixture=strokeFixture(half),{trace,metric,reference}=fixture;
      assert.equal(trace.shapes.size,1,`Stroke width ${half*2+1}: one field`);
      assert.ok(metric,`Measure the actual ${half*2+1}px stroke`);
      assert.ok(Math.abs(metric.halfWidthPixels-half)<=1);
      assert.ok(metric.radiusPixels>previous);previous=metric.radiusPixels;
      const rings=Array.from(trace.shapes.values(),shape=>shape.points);
      const result=snapRings(rings,buildIndex([parcel(reference)]),{distance:metric.radiusPixels});
      onReference(result[0].points,reference);
      // The same pixel-derived fit must survive map-unit scaling and large
      // coordinate offsets; its extent is not a screen-zoom-dependent radius.
      const world=points=>points.map(([x,y])=>[7500000+x*.2,-5800000+y*.2]);
      const mapped=snapRings(rings.map(world),buildIndex([parcel(world(reference))]),{distance:metric.radiusPixels*.2});
      onReference(mapped[0].points,world(reference));
    }
    const diagonal=strokeFixture(5,{reference:[[40,25],[210,55],[190,150],[20,120]]});
    assert.equal(diagonal.trace.shapes.size,1);
    const result=snapRings(Array.from(diagonal.trace.shapes.values(),shape=>shape.points),
      buildIndex([parcel(diagonal.reference)]),{distance:diagonal.metric.radiusPixels});
    onReference(result[0].points,diagonal.reference);
  },
  stroke_measurement_rejects_solid_patches_masks_and_isolated_annotations(){
    const regular=strokeFixture(2),annotated=strokeFixture(2,{annotation:true});
    assert.ok(regular.metric&&annotated.metric);
    assert.ok(Math.abs(regular.metric.radiusPixels-annotated.metric.radiusPixels)<=1,
      'One thick letter crossing a side must not set the range for the sheet');
    const {pixels,width,height,trace,mask}=regular,measure=context.GeoStudioRasterTraceMetrics.estimateStrokeRadius;
    const filled=new Uint8ClampedArray(pixels.length);
    for(let i=0;i<filled.length;i+=4)filled.set([20,20,20,255],i);
    assert.equal(measure(filled,width,height,trace.shapes,2.5),null,'A solid dark patch is not a bounded stroke');
    const covered=mask.slice();for(let i=3;i<covered.length;i+=4)covered[i]=255;
    assert.equal(measure(pixels,width,height,trace.shapes,2.5,covered),null,'Occupied5310 do not supply ink evidence');
    assert.equal(measure(new Uint8ClampedArray(4),width,height,trace.shapes,2.5),null);
    assert.equal(measure(pixels,width,height,new Map(),2.5),null);
    assert.ok(regular.metric.samples<=512*5&&regular.metric.edges<=512);
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
