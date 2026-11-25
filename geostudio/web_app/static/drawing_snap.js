/* Precise, opt-in/out snapping for NEW drawing gestures.
   Coordinates are Canvas world units [easting Y, -northing X].
   Pure helper: no edits to stationary GEO-MAP P records.
   Exported for both Windows WebView2 and offline Node regression tests. */
(function (root, factory) {
  "use strict";
  const api=factory();
  if(typeof module==="object"&&module.exports) module.exports=api;
  else root.GeoStudioDrawingSnap=api;
})(typeof window==="object"?window:globalThis,function () {
  "use strict";
  function closestPointOnSegment(point,a,b) {
    const dx=b[0]-a[0],dy=b[1]-a[1],length=dx*dx+dy*dy;
    const t=length?Math.max(0,Math.min(1,
      ((point.x-a[0])*dx+(point.y-a[1])*dy)/length)):0;
    return {x:a[0]+t*dx,y:a[1]+t*dy};
  }
  function snapPoint(world,features,options={}) {
    const scale=Number(options.scale);
    const noMatch={point:world,kind:null,code:null,targetId:null,distancePx:null};
    if(options.enabled===false||options.bypass||!Number.isFinite(scale)||
       scale<=0||!Number.isFinite(world?.x)||!Number.isFinite(world?.y))
      return noMatch;
    // Distances are *screen pixels*, not metres. A narrow capture radius
    // lets users digitize parallel lines just outside the target boundary.
    // Węzły łapią z większego promienia niż krawędzie: przy wkreślaniu
    // poligonu mysz łatwo uciekała z punktu zaczepienia.
    const vRadius=Math.max(1,Math.min(options.preferVertices?40:20,options.vertexPixels??14));
    const eRadius=Math.max(1,Math.min(12,options.edgePixels??7));
    const previous=options.previous?.kind==="węzeł"?options.previous:null;
    const releaseRadius=previous?Math.max(vRadius,Math.min(48,options.releasePixels??vRadius)):vRadius;
    const search=Math.max(releaseRadius,eRadius)/scale;
    let vertex=null,edge=null,sticky=null,featureCount=0,segments=0;
    for(const feature of features||[]) {
      if(feature.visible===false||!feature.geometry?.length)continue;
      const bbox=feature.bbox;
      if(bbox&&(world.x<bbox[0]-search||world.x>bbox[2]+search||
                world.y<bbox[1]-search||world.y>bbox[3]+search))continue;
      // Work is capped even on >100k-point MAP at very low zoom.
      if(++featureCount>120)break;
      for(const part of feature.geometry) {
        if(!Array.isArray(part)||!part.length)continue;
        const closes=feature.closed&&part.length>2&&
          (part[0][0]!==part.at(-1)[0]||part[0][1]!==part.at(-1)[1]);
        for(let i=0;i<part.length+(closes?1:0);i++) {
          if(++segments>12000)break;
          const p=part[i%part.length];
          if(!Array.isArray(p)||p.length<2||
             !Number.isFinite(p[0])||!Number.isFinite(p[1]))continue;
          const dist=Math.hypot(world.x-p[0],world.y-p[1])*scale;
          if(dist<=vRadius&&(!vertex||dist<vertex.distancePx))
            vertex={point:{x:p[0],y:p[1]},kind:"węzeł",code:feature.code,
                    targetId:feature.id,distancePx:dist};
          if(previous&&dist<=releaseRadius&&previous.point?.x===p[0]&&previous.point?.y===p[1])
            sticky={point:{x:p[0],y:p[1]},kind:"węzeł",code:feature.code,
                    targetId:feature.id,distancePx:dist};
          if(i===0)continue;
          const a=part[i-1];
          if(!Array.isArray(a)||a.length<2)continue;
          const q=closestPointOnSegment(world,a,p);
          const eDist=Math.hypot(world.x-q.x,world.y-q.y)*scale;
          if(eDist<=eRadius&&(!edge||eDist<edge.distancePx))
            edge={point:q,kind:"krawędź",code:feature.code,
                  targetId:feature.id,distancePx:eDist};
        }
        if(segments>12000)break;
      }
      if(segments>12000)break;
    }
    // Auto tracing favours a nearby exact corner over an edge projection.
    // Keep it captured through small hand movements, but allow a clearly
    // closer node to take over. Free drawing retains the narrower old policy.
    if(options.preferVertices){
      if(sticky&&(!vertex||vertex.distancePx+6>=sticky.distancePx))return sticky;
      if(vertex)return vertex;
    }
    // Prefer an exact node only when similarly close to an edge. Otherwise
    // the drawn point would jump several pixels along the neighbor line.
    if(vertex&&(!edge||vertex.distancePx<=edge.distancePx+1.2))
      return vertex;
    return edge||vertex||noMatch;
  }
  return {closestPointOnSegment,snapPoint};
});
