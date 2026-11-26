/* Match raster-derived sides to nearby, co-directed native parcel boundaries.
 * All distances are map units (metres), independent of view/analysis resolution.
 * The raster segmentation is deliberately not split by the parcel network. */
(function(root){
  "use strict";
  const EPS=1e-7,COS_ANGLE=Math.cos(Math.PI/12),MAX_POINTS=500,MAX_GRAPH_WORK=250000;
  const point=p=>Array.isArray(p)&&p.length>=2&&Number.isFinite(p[0])&&Number.isFinite(p[1]);
  const compare=(a,b)=>a[0]-b[0]||a[1]-b[1];
  const key=p=>Math.round(p[0]/EPS)+","+Math.round(p[1]/EPS);
  const edgeKey=(a,b)=>[key(a),key(b)].sort().join("|");
  const exactKey=p=>p[0]+","+p[1];
  const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
  const cross=(x,y,u,v)=>x*v-y*u;
  function bounds(a,b,padding=0){return [Math.min(a[0],b[0])-padding,Math.min(a[1],b[1])-padding,
    Math.max(a[0],b[0])+padding,Math.max(a[1],b[1])+padding];}
  function overlaps(a,b){return a[0]<=b[2]+EPS&&a[2]+EPS>=b[0]&&a[1]<=b[3]+EPS&&a[3]+EPS>=b[1];}
  function projection(p,a,b,clamp=true){
    const x=b[0]-a[0],y=b[1]-a[1],den=x*x+y*y;
    let t=den?((p[0]-a[0])*x+(p[1]-a[1])*y)/den:0;
    if(clamp)t=Math.max(0,Math.min(1,t));
    if(t===0)return a.slice();if(t===1)return b.slice();
    return [a[0]+t*x,a[1]+t*y];
  }
  const lineDistance=(p,a,b)=>Math.abs(cross(b[0]-a[0],b[1]-a[1],p[0]-a[0],p[1]-a[1]))/distance(a,b);
  const segmentDistance=(p,a,b)=>distance(p,projection(p,a,b));
  function intersection(a,b,c,d){
    const x=b[0]-a[0],y=b[1]-a[1],u=d[0]-c[0],v=d[1]-c[1],den=cross(x,y,u,v);
    if(Math.abs(den)<=1e-10*Math.hypot(x,y)*Math.hypot(u,v))return null;
    const t=cross(c[0]-a[0],c[1]-a[1],u,v)/den;
    return [a[0]+t*x,a[1]+t*y];
  }
  function tree(edges){
    if(!edges.length)return null;
    const box=edges.reduce((r,e)=>[Math.min(r[0],e.box[0]),Math.min(r[1],e.box[1]),
      Math.max(r[2],e.box[2]),Math.max(r[3],e.box[3])],[Infinity,Infinity,-Infinity,-Infinity]);
    if(edges.length<=12)return {box,edges};
    const axis=box[2]-box[0]>=box[3]-box[1]?0:1;
    const sorted=edges.slice().sort((a,b)=>(a.a[axis]+a.b[axis])-(b.a[axis]+b.b[axis])||a.id-b.id);
    const middle=Math.floor(sorted.length/2);
    return {box,left:tree(sorted.slice(0,middle)),right:tree(sorted.slice(middle))};
  }
  function query(index,box){
    const result=[],stack=index?.tree?[index.tree]:[];
    while(stack.length){
      const node=stack.pop();if(!overlaps(node.box,box))continue;
      if(node.edges){for(const edge of node.edges)if(overlaps(edge.box,box))result.push(edge);}
      else stack.push(node.left,node.right);
    }
    return result.sort((a,b)=>a.id-b.id);
  }
  function buildIndex(features){
    const unique=new Map();
    for(const feature of features||[]){
      if(String(feature?.code)!=="5216")continue;
      const geometry=Array.isArray(feature.nativeGeometry)?feature.nativeGeometry:feature.geometry;
      if(!Array.isArray(geometry))continue;
      for(const ring of geometry){
        if(!Array.isArray(ring)||ring.length<2)continue;
        const repeated=point(ring[0])&&point(ring.at(-1))&&distance(ring[0],ring.at(-1))<=EPS;
        const n=ring.length-(repeated?1:0),closed=!!feature.closed||repeated;
        for(let i=0;i<n-(closed?0:1);i++){
          let a=ring[i],b=ring[(i+1)%n];
          if(!point(a)||!point(b)||distance(a,b)<=EPS)continue;
          if(compare(a,b)>0)[a,b]=[b,a];
          const id=exactKey(a)+"|"+exactKey(b);
          if(!unique.has(id))unique.set(id,{a:a.slice(0,2),b:b.slice(0,2),box:bounds(a,b)});
        }
      }
    }
    const edges=[...unique.values()].sort((a,b)=>compare(a.a,b.a)||compare(a.b,b.b));
    edges.forEach((edge,id)=>{edge.id=id;});
    return {size:edges.length,tree:tree(edges)};
  }
  // Crop a reference edge to a narrow, directed corridor. Only actual edges
  // whose direction agrees with the raster side are admitted to the graph.
  function crop(edge,a,ux,uy,length,radius){
    const dx=edge.b[0]-edge.a[0],dy=edge.b[1]-edge.a[1],size=Math.hypot(dx,dy);
    if(Math.abs(dx*ux+dy*uy)<size*COS_ANGLE)return null;
    const px=edge.a[0]-a[0],py=edge.a[1]-a[1];
    let low=0,high=1;
    for(const [start,delta,min,max] of [[px*ux+py*uy,dx*ux+dy*uy,-radius,length+radius],
      [cross(ux,uy,px,py),cross(ux,uy,dx,dy),-radius,radius]]){
      if(Math.abs(delta)<1e-14){if(start<min-EPS||start>max+EPS)return null;continue;}
      let p=(min-start)/delta,q=(max-start)/delta;if(p>q)[p,q]=[q,p];
      low=Math.max(low,p);high=Math.min(high,q);if(high-low<=1e-12)return null;
    }
    const at=t=>t<=0?edge.a.slice():t>=1?edge.b.slice():[edge.a[0]+t*dx,edge.a[1]+t*dy];
    let p=at(low),q=at(high);
    if((q[0]-p[0])*ux+(q[1]-p[1])*uy<0)[p,q]=[q,p];
    return {a:p,b:q,edge};
  }
  function matchSide(a,b,index,radius,supportsShort=()=>false,report={},precision=0){
    if(precision>EPS&&radius>precision+EPS){
      const nearbyReport={},nearby=matchSide(a,b,index,precision,supportsShort,nearbyReport,precision);
      // Resolve a supported nearby track before considering distant parcels.
      // A wider user range may add missing fits; it must not reshuffle clear
      // close matches or make a genuinely ambiguous near track look certain.
      if(nearby||nearbyReport.reason==="too-many-candidates"){
        Object.assign(report,nearbyReport);return nearby;
      }
    }
    const length=distance(a,b);
    const reject=reason=>{report.reason=reason;return null;};
    const ux=(b[0]-a[0])/length,uy=(b[1]-a[1])/length;
    const along=p=>(p[0]-a[0])*ux+(p[1]-a[1])*uy;
    const across=p=>cross(ux,uy,p[0]-a[0],p[1]-a[1]);
    const nearby=query(index,bounds(a,b,radius));
    report.nearbyEdges=nearby.length;
    report.closestReferenceDistance=nearby.length?nearby.reduce((nearest,edge)=>
      Math.min(nearest,segmentSeparation(a,b,edge.a,edge.b)),Infinity):null;
    const candidates=nearby.map(edge=>crop(edge,a,ux,uy,length,radius)).filter(Boolean);
    if(!candidates.length)return reject(nearby.length?"direction-or-range":"no-nearby-reference");
    if(candidates.length>2000)return reject("too-many-candidates");
    const nodes=new Map(),starts=new Map(),ends=new Map();
    function node(p){
      const id=key(p);
      if(!nodes.has(id))nodes.set(id,{id,p,at:along(p),next:new Map(),states:[]});
      return nodes.get(id);
    }
    for(const candidate of candidates){
      node(candidate.a);node(candidate.b);
      for(const [target,list] of [[a,starts],[b,ends]]){
        const p=projection(target,candidate.a,candidate.b),d=distance(target,p);
        const nativeEnd=distance(p,candidate.edge.a)<=EPS||distance(p,candidate.edge.b)<=EPS;
        if(d<=(nativeEnd?Math.SQRT2*radius:radius)+EPS){
          const n=node(p);list.set(n,Math.min(list.get(n)??Infinity,d));
        }
      }
    }
    if(!starts.size||!ends.size)return reject("incomplete-coverage");
    // Bound the actual graph size, not just its segment count. Hundreds of
    // nearly coincident alternatives can create thousands of projection
    // nodes and otherwise block the UI before a batch limit is checked.
    const graphWork=()=>candidates.length*(candidates.length-1)/2+candidates.length*nodes.size;
    if(graphWork()>MAX_GRAPH_WORK)return reject("too-many-candidates");
    // Node partial duplicate edges and genuine joins, including a T junction
    // represented by a long edge on one parcel and two short edges on another.
    for(let i=0;i<candidates.length;i++)for(let j=i+1;j<candidates.length;j++){
      const first=candidates[i],second=candidates[j];
      if(!overlaps(bounds(first.a,first.b),bounds(second.a,second.b)))continue;
      const p=intersection(first.a,first.b,second.a,second.b);
      if(p&&segmentDistance(p,first.a,first.b)<=EPS&&segmentDistance(p,second.a,second.b)<=EPS){
        node(p);if(graphWork()>MAX_GRAPH_WORK)return reject("too-many-candidates");
      }
    }
    const ordered=[...nodes.values()].sort((p,q)=>p.at-q.at||compare(p.p,q.p));
    for(const candidate of candidates){
      const on=ordered.filter(n=>segmentDistance(n.p,candidate.a,candidate.b)<=EPS);
      for(let i=1;i<on.length;i++){
        const previous=on[i-1],next=on[i],progress=next.at-previous.at;if(progress<=EPS)continue;
        if(previous.next.has(next.id))continue;
        const ca=across(previous.p),cb=across(next.p);
        const mean=ca*cb>=0?(Math.abs(ca)+Math.abs(cb))/2:
          (ca*ca+cb*cb)/(2*(Math.abs(ca)+Math.abs(cb)));
        previous.next.set(next.id,{node:next,cost:progress*mean/length+
          .05*(distance(previous.p,next.p)-progress)/length});
      }
    }
    function push(n,state){
      if(n.states.some(s=>s.ids===state.ids))return;
      n.states.push(state);n.states.sort((p,q)=>p.cost-q.cost||p.ids.localeCompare(q.ids));
      if(n.states.length>6)n.states.length=6;
    }
    for(const [n,d] of starts)push(n,{cost:.25*d,points:[n.p],ids:n.id});
    for(const n of ordered)for(const link of n.next.values())for(const state of n.states){
      push(link.node,{cost:state.cost+link.cost,points:[...state.points,link.node.p],ids:state.ids+"|"+link.node.id});
    }
    const finished=[];
    for(const [n,d] of ends)for(const state of n.states){
      if(state.points.length<2||along(state.points.at(-1))-along(state.points[0])<.8*length)continue;
      finished.push({...state,cost:state.cost+.25*d});
    }
    finished.sort((p,q)=>Math.abs(p.cost-q.cost)>1e-9?p.cost-q.cost:p.ids.localeCompare(q.ids));
    const best=finished[0];if(!best)return reject("incomplete-coverage");
    // `radius` is a maximum search distance, not the uncertainty of every
    // candidate. Increasing it used to reject a perfectly clear 1 m fit on
    // all 10 m-wide adjoining fields: their short sides suddenly failed the
    // length > 2*radius gate and the shared-boundary veto removed the rest.
    // Judge directional evidence and competing tracks by the displacement
    // actually needed for this path, so a wider search preserves close fits.
    const displacement=Math.max(distance(a,best.points[0]),distance(b,best.points.at(-1)),
      ...best.points.map(p=>segmentDistance(p,a,b)));
    const evidenceDistance=Math.min(radius,Math.max(displacement,precision));
    if(length<=2*evidenceDistance+EPS&&!supportsShort(evidenceDistance))return reject("short-side");
    report.candidate=true;
    function ordinate(path,t){
      for(let i=1;i<path.length;i++){
        const lo=along(path[i-1]),hi=along(path[i]);
        if(t<=hi+EPS){const f=Math.max(0,Math.min(1,(t-lo)/(hi-lo)));return across(path[i-1])*(1-f)+across(path[i])*f;}
      }
      return across(path.at(-1));
    }
    // Different projections onto the same noded track are equivalent. Distinct
    // nearby tracks with similar evidence remain deliberately unresolved.
    for(const other of finished.slice(1)){
      if(other.cost-best.cost>.2*evidenceDistance+EPS)break;
      if([.2,.5,.8].some(t=>Math.abs(ordinate(best.points,t*length)-ordinate(other.points,t*length))>EPS))
        {report.reason="ambiguous";return {ambiguous:true};}
    }
    return {points:best.points,along,cost:best.cost,source:[a,b],displacement,searchDistance:radius};
  }
  // Segmentation junctions can split one straight border into many pieces
  // shorter than the snap diameter. Measure the surrounding co-directed run
  // before rejecting such a piece for lack of directional evidence.
  function supportedShortSide(ring,i,radius){
    const a=ring[i],b=ring[(i+1)%ring.length],length=distance(a,b);
    if(length>2*radius+EPS)return false;
    const ux=(b[0]-a[0])/length,uy=(b[1]-a[1])/length;
    let span=length;
    const visited=new Set([i]);
    for(const step of [-1,1])for(let k=1;k<ring.length;k++){
      const j=(i+step*k+ring.length)%ring.length;
      if(visited.has(j))break;
      const p=ring[j],q=ring[(j+1)%ring.length],size=distance(p,q);
      const progress=(q[0]-p[0])*ux+(q[1]-p[1])*uy;
      if(progress<size*COS_ANGLE||lineDistance(p,a,b)>.5*radius+EPS||
        lineDistance(q,a,b)>.5*radius+EPS)break;
      visited.add(j);span+=progress;
      if(span>4*radius+EPS)return true;
    }
    return false;
  }
  // Thick raster strokes often leave a small bevel at a true parcel corner,
  // or a short slanted connector on an otherwise straight side. Intersecting
  // its raster tangent with the fitted sides enlarges that bevel. Instead,
  // follow the real connecting parcel edges when both neighbouring long sides
  // independently support the same nearby corner/track.
  function bridgeShortSide(a,b,before,after,index,radius){
    radius=Math.min(radius,Math.max(before?.searchDistance||radius,after?.searchDistance||radius));
    if(!before||!after||before.ambiguous||after.ambiguous||distance(a,b)>2*radius+EPS)return null;
    const left=before.points.slice(-2),right=after.points.slice(0,2);
    const start=projection(a,...left),end=projection(b,...right);
    if(distance(a,start)>radius+EPS||distance(b,end)>radius+EPS||distance(start,end)<=EPS)return null;
    let knots;
    if(lineDistance(right[0],...left)<=EPS&&lineDistance(right[1],...left)<=EPS){
      knots=[start,end];
    }else{
      const corner=intersection(...left,...right);
      if(!corner||segmentDistance(corner,a,b)>Math.SQRT2*radius+EPS)return null;
      // A real native vertex must join the two sides; crossing unrelated lines
      // is not sufficient evidence for replacing an internal raster divider.
      if(!query(index,bounds(corner,corner,EPS)).some(edge=>
        distance(corner,edge.a)<=EPS||distance(corner,edge.b)<=EPS))return null;
      knots=[start,corner,end].filter((p,i,array)=>!i||distance(p,array[i-1])>EPS);
    }
    const dx=b[0]-a[0],dy=b[1]-a[1],length=distance(a,b);
    const along=p=>((p[0]-a[0])*dx+(p[1]-a[1])*dy)/length;
    const points=[];
    for(let i=1;i<knots.length;i++){
      if(along(knots[i])-along(knots[i-1])<=EPS)return null;
      const part=supportedPiece(knots[i-1],knots[i],index);if(!part)return null;
      points.push(...part.slice(0,-1));
    }
    points.push(end);
    return {points,along,cost:0,cornerBridge:true};
  }
  // Return the exact reference vertices covering a straight piece. This also
  // verifies that extending a fitted corner did not invent a parcel edge.
  function supportedPiece(a,b,index){
    const length=distance(a,b);if(length<=EPS)return null;
    const ux=(b[0]-a[0])/length,uy=(b[1]-a[1])/length;
    const along=p=>(p[0]-a[0])*ux+(p[1]-a[1])*uy;
    const intervals=[],vertices=[];
    for(const edge of query(index,bounds(a,b,EPS))){
      if(lineDistance(edge.a,a,b)>EPS||lineDistance(edge.b,a,b)>EPS)continue;
      let lo=along(edge.a),hi=along(edge.b);if(lo>hi)[lo,hi]=[hi,lo];
      if(hi<-EPS||lo>length+EPS)continue;
      intervals.push([Math.max(0,lo),Math.min(length,hi)]);
      for(const p of [edge.a,edge.b]){const t=along(p);if(t>EPS&&t<length-EPS)vertices.push({p,t});}
    }
    intervals.sort((p,q)=>p[0]-q[0]||p[1]-q[1]);let covered=0;
    for(const [lo,hi] of intervals){if(lo>covered+EPS)return null;covered=Math.max(covered,hi);}
    if(covered<length-EPS)return null;
    vertices.sort((p,q)=>p.t-q.t||compare(p.p,q.p));
    const result=[a];
    for(const {p} of vertices)if(distance(p,result.at(-1))>EPS)result.push(p);
    result.push(b);return result;
  }
  function adjustedPath(match,start,end,index){
    const lo=match.along(start),hi=match.along(end);
    if(hi-lo<=EPS)return null;
    const knots=[];
    for(const p of [start,...match.points.filter(p=>match.along(p)>lo+EPS&&match.along(p)<hi-EPS),end]){
      // Avoid constructing a support line from a tiny virtual projection and
      // a nearby extended corner at million-metre coordinates. Native nodes
      // removed here are restored by supportedPiece below.
      while(knots.length>1&&lineDistance(knots.at(-1),knots.at(-2),p)<=EPS)knots.pop();
      knots.push(p);
    }
    const result=[];
    for(let i=1;i<knots.length;i++){
      const part=supportedPiece(knots[i-1],knots[i],index);if(!part)return null;
      result.push(...part.slice(0,-1));
      if(result.length>MAX_POINTS)return null;
    }
    result.push(end);
    // Start/end projections are graph search nodes, not cadastral vertices.
    // Remove only those artificial collinear points after extending a corner.
    return result.filter((p,i)=>i===0||i===result.length-1||
      lineDistance(p,result[i-1],result[i+1])>EPS||
      query(index,bounds(p,p,EPS)).some(edge=>distance(p,edge.a)<=EPS||distance(p,edge.b)<=EPS));
  }
  // Two incident raster tangents can place their common junction at different
  // points along the same straight cadastral boundary. These are not competing
  // tracks: agree on the closest point of that proven continuous track before
  // the shared-node veto freezes it. Use a native edge's tangent, rather than a
  // line between almost coincident projections at large map coordinates.
  function commonProjection(p,choices,index,radius){
    const nearby=query(index,bounds(p,p,radius));
    // Side searches can reject dense off-angle clutter before graph creation.
    // Keep this junction-level fallback bounded for that same input too.
    if(nearby.length*(nearby.length+choices.length)>MAX_GRAPH_WORK)return null;
    nearby.sort((a,b)=>distance(b.a,b.b)-distance(a.a,a.b)||a.id-b.id);
    for(const edge of nearby){
      if(choices.some(q=>lineDistance(q,edge.a,edge.b)>EPS))continue;
      const target=projection(p,edge.a,edge.b,false);
      if(distance(p,target)>radius+EPS)continue;
      const size=distance(edge.a,edge.b),dx=(edge.b[0]-edge.a[0])/size,dy=(edge.b[1]-edge.a[1])/size;
      const along=q=>(q[0]-edge.a[0])*dx+(q[1]-edge.a[1])*dy;
      const locations=[target,...choices].map(along),lo=Math.min(...locations),hi=Math.max(...locations);
      const intervals=nearby.filter(other=>lineDistance(other.a,edge.a,edge.b)<=EPS&&
        lineDistance(other.b,edge.a,edge.b)<=EPS).map(other=>{
          const a=along(other.a),b=along(other.b);return [Math.min(a,b),Math.max(a,b)];
        }).sort((a,b)=>a[0]-b[0]||a[1]-b[1]);
      let covered=lo;
      for(const [a,b] of intervals){
        if(b<covered-EPS)continue;
        if(a>covered+EPS)break;
        covered=Math.max(covered,b);
        if(covered>=hi-EPS)return target;
      }
    }
    return null;
  }
  function referenceCorner(p,before,after,index,radius){
    if(!before||!after||before.cornerBridge||after.cornerBridge)return null;
    radius=Math.min(radius,Math.max(before.searchDistance||radius,after.searchDistance||radius));
    // At a shallow bend both side searches may continue across the same real
    // parcel vertex. Their end tangents then coincide, so intersecting those
    // tangents would attach the original corner to an arbitrary projection.
    // Assign the corner to the supported native bend and trim both paths there.
    const candidates=new Map();
    const cornerRadius=Math.SQRT2*radius;
    for(const edge of query(index,bounds(p,p,cornerRadius)))for(const q of [edge.a,edge.b])
      if(distance(p,q)<=cornerRadius+EPS&&lineDistance(q,...before.source)<=radius+EPS&&
        lineDistance(q,...after.source)<=radius+EPS)candidates.set(key(q),q);
    const supported=[];
    for(const q of candidates.values()){
      const left=adjustedPath(before,before.points[0],q,index);
      const right=adjustedPath(after,q,after.points.at(-1),index);
      if(!left||!right||left.length<2||right.length<2)continue;
      const a=left.at(-2),b=right[1];
      // A collinear survey node is not evidence for moving a true interior
      // T junction along a straight parcel line.
      if(lineDistance(q,a,b)<=EPS)continue;
      supported.push(q);
    }
    return supported.length===1?supported[0].slice():null;
  }
  function area(ring){
    const origin=ring[0];let sum=0;
    for(let i=0;i<ring.length;i++){
      const a=ring[i],b=ring[(i+1)%ring.length];
      sum+=cross(a[0]-origin[0],a[1]-origin[1],b[0]-origin[0],b[1]-origin[1]);
    }
    return sum/2;
  }
  function intersects(a,b,c,d){
    const hit=intersection(a,b,c,d);
    if(hit&&segmentDistance(hit,a,b)<=EPS&&segmentDistance(hit,c,d)<=EPS)return true;
    return Math.min(segmentDistance(a,c,d),segmentDistance(b,c,d),segmentDistance(c,a,b),segmentDistance(d,a,b))<=EPS;
  }
  function simple(ring){
    if(ring.length<3||ring.length>MAX_POINTS||!ring.every(point))return false;
    for(let i=0;i<ring.length;i++){
      const a=ring[i],b=ring[(i+1)%ring.length];if(distance(a,b)<=EPS)return false;
      for(let j=i+2;j<ring.length;j++){
        if(i===0&&j===ring.length-1)continue;
        const c=ring[j],d=ring[(j+1)%ring.length];
        if(overlaps(bounds(a,b),bounds(c,d))&&intersects(a,b,c,d))return false;
      }
    }
    return Math.abs(area(ring))>EPS;
  }
  function segmentSeparation(a,b,c,d){
    if(intersects(a,b,c,d))return 0;
    return Math.min(segmentDistance(a,c,d),segmentDistance(b,c,d),segmentDistance(c,a,b),segmentDistance(d,a,b));
  }
  function safe(original,paths,result,radius,matches,targets){
    if(!simple(result))return false;
    // Moving a supported junction past the next raster vertex can reverse
    // an otherwise unmatched short connector. That creates a folded spur
    // into the adjacent field even when this ring remains simple and its
    // area changes only slightly. Keep every side's forward progression.
    for(let i=0;i<paths.length;i++){
      const a=original[i],b=original[(i+1)%original.length],path=paths[i];
      const u=path[0],v=path.at(-1);
      if((v[0]-u[0])*(b[0]-a[0])+(v[1]-u[1])*(b[1]-a[1])<=EPS*distance(a,b))return false;
    }
    const before=area(original),after=area(result);
    if(before*after<=0)return false;
    // A thick stroke shrinks the detected white interior on every side of a
    // narrow field. Its fully supported cadastral perimeter can therefore be
    // substantially larger. Permit that bounded correction only when every
    // side follows a real reference path; a single nearby line must still not
    // expand a thin field or override a shared-neighbour veto.
    const fullyReferenced=matches.every(Boolean);
    const areaAllowance=fullyReferenced&&Math.abs(after)>Math.abs(before)?.5:.15;
    if(Math.abs(after-before)>areaAllowance*Math.abs(before)+EPS)return false;
    for(let i=0;i<paths.length;i++)for(let j=0;j<paths[i].length;j++){
      // The diagonal of two accepted offset bands may contain a native corner
      // just beyond one side's radius. Only an independently supported native
      // anchor or short bevel may use that additional corner allowance.
      const p=paths[i][j],a=original[i],b=original[(i+1)%original.length];
      const nativeCorner=[a,b].some(q=>targets.has(key(q))&&distance(p,q)<=Math.SQRT2*radius+EPS);
      const limit=nativeCorner||matches[i]?.cornerBridge&&j>0&&j<paths[i].length-1?Math.SQRT2*radius:radius;
      if(segmentDistance(paths[i][j],original[i],original[(i+1)%original.length])>limit+EPS)return false;
    }
    // An unchanged overall area can conceal a collapsed narrow arm of a large
    // polygon. Preserve separation of nearby, overlapping opposite sides too.
    for(let i=0;i<original.length;i++)for(let j=i+2;j<original.length;j++){
      if(i===0&&j===original.length-1)continue;
      const a=original[i],b=original[(i+1)%original.length],c=original[j],d=original[(j+1)%original.length];
      const la=distance(a,b),lb=distance(c,d),ux=(b[0]-a[0])/la,uy=(b[1]-a[1])/la;
      if(Math.abs(ux*(d[0]-c[0])+uy*(d[1]-c[1]))<lb*COS_ANGLE)continue;
      const t=p=>(p[0]-a[0])*ux+(p[1]-a[1])*uy;
      if(Math.min(la,Math.max(t(c),t(d)))-Math.max(0,Math.min(t(c),t(d)))<=.25*Math.min(la,lb))continue;
      const separation=segmentSeparation(a,b,c,d);if(separation>4*radius||separation<=EPS)continue;
      let next=Infinity;
      for(let p=1;p<paths[i].length;p++)for(let q=1;q<paths[j].length;q++)
        next=Math.min(next,segmentSeparation(paths[i][p-1],paths[i][p],paths[j][q-1],paths[j][q]));
      if(next<.35*separation-EPS)return false;
    }
    return true;
  }
  function snapRing(ring,index,options={}){
    const original=Array.isArray(ring)?ring.map(p=>Array.isArray(p)?p.slice(0,2):p):[];
    const observations=[],diagnostics={referenceEdges:index?.size||0,sourceSides:original.length,
      candidateSides:0,matchedSides:0,ambiguousSides:0,rejectedSides:0,movedVertices:0,
      maxDisplacement:0,closestReferenceDistance:null,reasons:{}};
    function summarize(count=0,paths=null){
      // Include sides already lying on 5216. "No vertex moved" is different
      // from "no reference fit", especially when the checkbox is toggled on
      // an outline that is already geometrically exact.
      let referenced=count,aligned=[];
      if(index?.size&&original.length>=3&&original.every(point)){
        const sides=paths||original.map((p,i)=>[p,original[(i+1)%original.length]]);
        aligned=sides.map(path=>path?.length>1&&path.every((p,i)=>!i||
          distance(path[i-1],p)>EPS&&supportedPiece(path[i-1],p,index)));
        referenced=aligned.filter(Boolean).length;
      }
      const result={...diagnostics,matchedSides:referenced,reasons:{...diagnostics.reasons}};
      for(const [i,observation] of observations.entries()){
        if(observation.candidate)result.candidateSides++;
        if(observation.candidate&&!aligned[i])result.rejectedSides++;
        if(observation.reason&&!aligned[i]){
          result.reasons[observation.reason]=(result.reasons[observation.reason]||0)+1;
          if(observation.reason==="ambiguous")result.ambiguousSides++;
        }
        if(Number.isFinite(observation.closestReferenceDistance))
          result.closestReferenceDistance=result.closestReferenceDistance===null?observation.closestReferenceDistance:
            Math.min(result.closestReferenceDistance,observation.closestReferenceDistance);
      }
      return result;
    }
    const unchanged=reason=>({points:original.map(p=>Array.isArray(p)?p.slice():p),snappedEdges:0,
      sourceIndices:original.map((_,i)=>i),reason,diagnostics:summarize()});
    const radius=Number(options.distance);
    // The measured stroke/regularization uncertainty can remain fixed while
    // the user increases the maximum search range. It prevents tiny raster
    // bevels at junctions from becoming independent sides merely because
    // they happen to be close to one branch of the reference network.
    const precision=Number.isFinite(Number(options.precisionDistance))?
      Math.max(0,Number(options.precisionDistance)):0;
    if(!Number.isFinite(radius)||radius<=0||!index?.size)return unchanged("disabled");
    if(!simple(original))return unchanged("invalid");
    const locks=new Set((Array.isArray(options.locked)?options.locked:[]).filter(point).map(key));
    const blocked=options.blockedEdges instanceof Set?options.blockedEdges:
      new Set((Array.isArray(options.blockedEdges)?options.blockedEdges:[])
        .filter(edge=>Array.isArray(edge)&&point(edge[0])&&point(edge[1])).map(edge=>edgeKey(...edge)));
    const matches=original.map((a,i)=>{
      const report={};observations.push(report);
      if(blocked.has(edgeKey(a,original[(i+1)%original.length]))){
        report.reason="shared-veto";report.candidate=true;return null;
      }
      return matchSide(a,original[(i+1)%original.length],index,radius,
        displacement=>supportedShortSide(original,i,displacement),report,precision);
    });
    let ambiguous=false;
    for(let i=0;i<matches.length;i++)if(matches[i]?.ambiguous){ambiguous=true;matches[i]=null;}
    const n=original.length;
    const direct=matches.slice();
    for(let i=0;i<n;i++)if(!matches[i]&&!blocked.has(edgeKey(original[i],original[(i+1)%n]))&&
      !locks.has(key(original[i]))&&!locks.has(key(original[(i+1)%n])))
      matches[i]=bridgeShortSide(original[i],original[(i+1)%n],direct[(i+n-1)%n],direct[(i+1)%n],index,radius);
    matches.forEach((match,i)=>{if(match)observations[i].candidate=true;});
    const targets=new Map(options._targets||[]),sharedProjections=new Map(options._sharedProjections||[]);
    original.forEach((p,i)=>{
      if(locks.has(key(p)))return;
      const target=referenceCorner(p,matches[(i+n-1)%n],matches[i],index,radius);
      if(target){
        if(!targets.has(key(p)))targets.set(key(p),target);
        if(typeof options._collectAnchors==="function")options._collectAnchors(p,target);
      }
    });
    let corners,paths;
    for(let pass=0;pass<=n;pass++){
      let changed=false;corners=original.map(p=>p.slice());
      for(let i=0;i<n;i++){
        const previous=(i+n-1)%n,before=matches[previous],after=matches[i],p=original[i];
        const anchor=locks.has(key(p))?p:targets.get(key(p))||sharedProjections.get(key(p));
        const cornerRadius=targets.has(key(p))?Math.SQRT2*radius:radius;
        if(anchor&&distance(p,anchor)<=cornerRadius+EPS)corners[i]=anchor.slice();
        if(!before&&!after)continue;
        const left=before?before.points.slice(-2):[original[previous],p];
        const right=after?after.points.slice(0,2):[p,original[(i+1)%n]];
        let target;
        if(anchor&&distance(p,anchor)<=cornerRadius+EPS){
          target=anchor.slice();
        }else if(locks.has(key(p))){
          if((!before||lineDistance(p,...left)<=EPS)&&(!after||lineDistance(p,...right)<=EPS))target=p.slice();
        }else{
          target=referenceCorner(p,before,after,index,radius)||intersection(...left,...right);
          if(!target&&before&&after&&lineDistance(right[0],...left)<=EPS&&lineDistance(right[1],...left)<=EPS)
            target=projection(p,...left,false);
        }
        if(!target||distance(p,target)>cornerRadius+EPS){
          const reason=locks.has(key(p))?"manual-lock":target?"corner-out-of-range":"corner-junction";
          if(before){matches[previous]=null;observations[previous].reason=reason;changed=true;}
          if(after){matches[i]=null;observations[i].reason=reason;changed=true;}
        }else corners[i]=target;
      }
      if(changed)continue;
      paths=corners.map((p,i)=>matches[i]?adjustedPath(matches[i],p,corners[(i+1)%n],index):[p,corners[(i+1)%n]]);
      for(let i=0;i<n;i++)if(!paths[i]){matches[i]=null;observations[i].reason="unsupported-reference-path";changed=true;}
      if(!changed)break;
    }
    let count=matches.filter(Boolean).length;
    const moved=corners?.some((p,i)=>distance(p,original[i])>EPS);
    if(!count&&!moved)return unchanged(ambiguous?"ambiguous":"no-match");
    if(!paths||paths.some(p=>!p))return unchanged("topology");
    // A short side can be unambiguous once both its ends have independent,
    // supported native-corner anchors. Recover its real reference nodes then.
    for(let i=0;i<n;i++)if(!matches[i]&&!blocked.has(edgeKey(original[i],original[(i+1)%n]))){
      const a=corners[i],b=corners[(i+1)%n],p=original[i],q=original[(i+1)%n];
      if(distance(a,p)<=EPS&&distance(b,q)<=EPS)continue;
      if(((b[0]-a[0])*(q[0]-p[0])+(b[1]-a[1])*(q[1]-p[1]))<distance(a,b)*distance(p,q)*COS_ANGLE)continue;
      const supported=supportedPiece(a,b,index);
      if(supported){paths[i]=supported;count++;}
    }
    const points=[],sourceIndices=[];
    paths.forEach((path,i)=>path.slice(0,-1).forEach((p,j)=>{points.push(p.slice());sourceIndices.push(j===0?i:null);}));
    if(!safe(original,paths,points,radius,matches,targets)){
      diagnostics.reasons.topology=1;return unchanged("topology");
    }
    let sourceEdge=0;
    points.forEach((p,i)=>{
      const sourceIndex=sourceIndices[i];
      if(sourceIndex!==null)sourceEdge=sourceIndex;
      const displacement=sourceIndex!==null?distance(p,original[sourceIndex]):
        segmentDistance(p,original[sourceEdge],original[(sourceEdge+1)%original.length]);
      diagnostics.maxDisplacement=Math.max(diagnostics.maxDisplacement,displacement);
      if(displacement>EPS)diagnostics.movedVertices++;
    });
    return {points,snappedEdges:count,sourceIndices,diagnostics:summarize(count,paths),...(!count?{reason:"shared-corner"}:{})};
  }
  // A polygon-level area/crossing veto must also apply to its neighbours.
  // Compute candidates as one partition, then monotonically freeze only the
  // shared nodes/edges whose proposals disagree. UI unions can consequently
  // cancel identical shared paths without returning to the raster contours.
  function snapRings(rings,index,options={}){
    const source=Array.isArray(rings)?rings:[],vertices=new Map(),edges=new Map();
    function note(map,id,entry){if(!map.has(id))map.set(id,[]);map.get(id).push(entry);}
    source.forEach((ring,r)=>{
      if(!Array.isArray(ring)||!ring.every(point))return;
      ring.forEach((p,i)=>{
        note(vertices,key(p),{r,i,p});
        const q=ring[(i+1)%ring.length];
        note(edges,edgeKey(p,q),{r,i,a:p,b:q,reverse:key(p)>key(q)});
      });
    });
    const sharedVertices=[...vertices.entries()].filter(([,items])=>new Set(items.map(item=>item.r)).size>1);
    const sharedEdges=[...edges.entries()].filter(([,items])=>new Set(items.map(item=>item.r)).size>1);
    const locks=new Map(),blocked=new Set(),cached=[],proposals=new Map(),targets=new Map(),sharedProjections=new Map();
    if(Array.isArray(options.locked))for(const p of options.locked)if(point(p))locks.set(key(p),p);
    // A node can be a genuine corner in two neighbouring fields while appearing
    // almost straight in the third. Share the independently supported native
    // anchor before comparing proposals; disagreement of corner ownership is
    // not a reason to freeze an otherwise correct parcel boundary.
    for(const ring of source)snapRing(ring,index,{distance:options.distance,precisionDistance:options.precisionDistance,
      _collectAnchors(p,q){
        const id=key(p);if(!proposals.has(id))proposals.set(id,new Map());
        proposals.get(id).set(key(q),q);
      }});
    for(const [id,choices] of proposals)if(choices.size===1)targets.set(id,choices.values().next().value);
    function run(){
      return source.map((ring,i)=>{
        const localLocks=ring.filter(p=>locks.has(key(p)));
        const localEdges=ring.map((p,j)=>edgeKey(p,ring[(j+1)%ring.length])).filter(id=>blocked.has(id));
        const signature=localLocks.map(key).join(";")+"/"+localEdges.join(";");
        if(cached[i]?.signature===signature)return cached[i].result;
        const result=snapRing(ring,index,{distance:options.distance,precisionDistance:options.precisionDistance,
          locked:localLocks,blockedEdges:blocked,_targets:targets,_sharedProjections:sharedProjections});
        cached[i]={signature,result};return result;
      });
    }
    function paths(result,length){
      const offsets=new Array(length);
      result.sourceIndices.forEach((i,j)=>{if(i!==null&&i>=0&&i<length)offsets[i]=j;});
      const paths=[];
      for(let i=0;i<length;i++){
        const start=offsets[i],stop=offsets[(i+1)%length],path=[];
        if(start===undefined||stop===undefined){paths.push([]);continue;}
        const end=stop>start?stop:stop+result.points.length;
        for(let j=start;j<=end;j++)path.push(result.points[j%result.points.length]);
        paths.push(path);
      }
      return {offsets,paths};
    }
    // A raster bevel on one field can prevent its local corner intersection,
    // although the neighbouring field already supports the shared vertex on
    // a complete parcel side. Try that single supported position on both
    // fields before freezing their shared border. Every recipient still runs
    // the ordinary displacement, area, narrow-arm and path safety checks.
    // Different tracks and explicit manual locks remain unresolved. Different
    // projections along one straight track can share its nearest
    // point without choosing either neighbour's raster tangent arbitrarily.
    function propagateSharedTargets(results){
      const geometry=results.map((result,i)=>paths(result,source[i].length));
      let changed=false;
      for(const [id,items] of sharedVertices){
        if(locks.has(id)||targets.has(id)||sharedProjections.has(id))continue;
        const choices=new Map();
        for(const {r,i,p} of items){
          const position=results[r].points[geometry[r].offsets[i]];
          if(!point(position)||distance(position,p)<=EPS)continue;
          // Only reuse an ordinary in-range projection. Native bend anchors
          // with the diagonal allowance were already shared above.
          if(distance(position,p)>Number(options.distance)+EPS)continue;
          const incident=[geometry[r].paths[i],geometry[r].paths[(i+source[r].length-1)%source[r].length]];
          if(!incident.some(path=>path.length>1&&path.every((q,j)=>!j||
            distance(path[j-1],q)>EPS&&supportedPiece(path[j-1],q,index))))continue;
          choices.set(key(position),position);
        }
        const positions=[...choices.values()];
        const target=positions.length===1?positions[0]:positions.length>1?
          commonProjection(items.map(item=>item.p).sort(compare)[0],positions,index,Number(options.distance)):null;
        if(!target)continue;
        sharedProjections.set(id,target.slice());changed=true;
      }
      if(changed)cached.length=0;
      return changed;
    }
    function conflicts(results){
      const geometry=results.map((result,i)=>paths(result,source[i].length));
      let changed=false;
      for(const [id,items] of sharedVertices){
        const positions=new Set(items.map(({r,i})=>key(results[r].points[geometry[r].offsets[i]])));
        if(positions.size>1&&!locks.has(id)){locks.set(id,items[0].p);changed=true;}
      }
      for(const [id,items] of sharedEdges){
        const signatures=new Set(items.map(({r,i,reverse})=>{
          const path=geometry[r].paths[i],ordered=reverse?path.slice().reverse():path;
          return ordered.map(key).join(";");
        }));
        if(signatures.size<=1)continue;
        if(!blocked.has(id)){blocked.add(id);changed=true;}
        for(const {a,b} of items)for(const p of [a,b])if(!locks.has(key(p))){locks.set(key(p),p);changed=true;}
      }
      return changed;
    }
    const bound=Math.max(1,sharedVertices.length+sharedEdges.length+1);
    const requested=Number(options.maxIterations);
    const limit=Number.isFinite(requested)?Math.max(1,Math.min(bound,Math.floor(requested))):Math.min(bound,16);
    let results,stable=false;
    for(let iteration=0;iteration<limit;iteration++){
      results=run();
      if(propagateSharedTargets(results))results=run();
      if(!conflicts(results)){stable=true;break;}
    }
    if(!stable){
      // Emergency bound for a pathological cascade. Shared geometry stays
      // original; independent exterior sides may still use their valid fit.
      // Ordinary conflicts above only freeze their own local nodes and sides.
      for(const [id,items] of sharedVertices)locks.set(id,items[0].p);
      for(const [id,items] of sharedEdges){
        blocked.add(id);
        for(const {a,b} of items)for(const p of [a,b])locks.set(key(p),p);
      }
      results=run();
      for(const result of results)result.topologyGuard="iteration-limit";
    }
    // Equal epsilon keys must mean identical JS coordinates, not merely an
    // approximate comparison, or exact edge cancellation could leave slivers.
    const canonical=new Map();
    for(const result of results)for(const p of result.points){
      const id=key(p),previous=canonical.get(id);
      if(!previous||compare(p,previous)<0)canonical.set(id,p);
    }
    const output=results.map(result=>({...result,points:result.points.map(p=>canonical.get(key(p)).slice())}));
    const diagnostics={referenceEdges:index?.size||0,rings:output.length,changedRings:0,
      sourceSides:0,candidateSides:0,matchedSides:0,ambiguousSides:0,rejectedSides:0,
      movedVertices:0,maxDisplacement:0,closestReferenceDistance:null,reasons:{}};
    for(const result of output){
      const report=result.diagnostics;
      if(report.movedVertices)diagnostics.changedRings++;
      for(const name of ["sourceSides","candidateSides","matchedSides","ambiguousSides","rejectedSides","movedVertices"])
        diagnostics[name]+=report[name];
      diagnostics.maxDisplacement=Math.max(diagnostics.maxDisplacement,report.maxDisplacement);
      if(report.closestReferenceDistance!==null)
        diagnostics.closestReferenceDistance=diagnostics.closestReferenceDistance===null?report.closestReferenceDistance:
          Math.min(diagnostics.closestReferenceDistance,report.closestReferenceDistance);
      for(const [reason,count] of Object.entries(report.reasons))
        diagnostics.reasons[reason]=(diagnostics.reasons[reason]||0)+count;
    }
    output.diagnostics=diagnostics;
    return output;
  }
  root.GeoStudioRasterParcelSnap={buildIndex,snapRing,snapRings};
})(typeof globalThis!=="undefined"?globalThis:this);
