// Trace a nearby chain of actual vector edges, including joins between objects.
// Progress along the polygon side rules out shortcuts around closed parcels.
function heldBoundarySide(ring,index,features,scale){
  const held=ring[index],radius=9/scale,band=22/scale;
  let best=null;
  for(const step of [-1,1]){
    const fixed=ring[(index+step+ring.length)%ring.length];
    const dx=held[0]-fixed[0],dy=held[1]-fixed[1],length=Math.hypot(dx,dy);
    if(length<3*radius)continue;
    const along=p=>((p[0]-fixed[0])*dx+(p[1]-fixed[1])*dy)/length;
    const across=p=>Math.abs((p[0]-fixed[0])*dy-(p[1]-fixed[1])*dx)/length;
    const graph=new Map(),starts=[],ends=[];
    function node(p){
      const key=Math.round(p[0]*1000)+","+Math.round(p[1]*1000);
      if(!graph.has(key))graph.set(key,{p,at:along(p),cost:Infinity,next:[],prev:null});
      return graph.get(key);
    }
    for(const feature of features){
      if(feature.bbox && (feature.bbox[2]<Math.min(held[0],fixed[0])-band||
         feature.bbox[0]>Math.max(held[0],fixed[0])+band||
         feature.bbox[3]<Math.min(held[1],fixed[1])-band||
         feature.bbox[1]>Math.max(held[1],fixed[1])+band))continue;
      for(const part of feature.geometry){
        for(let j=0;j<(feature.closed?part.length:part.length-1);j++){
          let a=part[j],b=part[(j+1)%part.length];
          if(along(a)>along(b))[a,b]=[b,a];
          const u=b[0]-a[0],v=b[1]-a[1],den=u*u+v*v;
          if(!den||along(b)-along(a)<Math.sqrt(den)*.25||along(a)>length+radius||along(b)<-radius)continue;
          const chain=[];
          for(const p of [a,b])if(across(p)<=band&&along(p)>=-radius&&along(p)<=length+radius)chain.push(node(p));
          for(const [target,list] of [[fixed,starts],[held,ends]]){
            const f=Math.max(0,Math.min(1,((target[0]-a[0])*u+(target[1]-a[1])*v)/den));
            const p=[a[0]+f*u,a[1]+f*v],dist=Math.hypot(p[0]-target[0],p[1]-target[1]);
            if(dist<=radius){const n=node(p);chain.push(n);list.push([n,dist]);}
          }
          chain.sort((s,t)=>s.at-t.at);
          for(let i=1;i<chain.length;i++)if(chain[i].at>chain[i-1].at)chain[i-1].next.push(chain[i]);
        }
      }
    }
    for(const [n,d] of starts)n.cost=Math.min(n.cost,4*d);
    for(const n of [...graph.values()].sort((a,b)=>a.at-b.at)){
      if(!Number.isFinite(n.cost))continue;
      for(const m of n.next){
        const cost=n.cost+Math.hypot(m.p[0]-n.p[0],m.p[1]-n.p[1])-(m.at-n.at)
          +(m.at-n.at)*(across(n.p)+across(m.p))/(2*length);
        if(cost<m.cost){m.cost=cost;m.prev=n;}
      }
    }
    for(const [end,d] of ends){
      const score=end.cost+4*d;
      if(!end.prev||!Number.isFinite(score)||(best&&score>=best.score))continue;
      const path=[];
      for(let n=end;n;n=n.prev)path.push(n.p);
      path.reverse();
      if(Math.hypot(path[0][0]-fixed[0],path[0][1]-fixed[1])<.002)path.shift();
      const point=path.pop();
      if(!point||!path.length||path.length>200)continue;
      best={step,point,between:path,score};
    }
  }
  return best;
}
// Geometry is fitted in analysis pixels, independently of the source file format.
// A shared boundary is fitted once, in a canonical direction, and reused by both
// polygons. Junctions stay fixed and the explicit tolerance bounds every move.
function traceTolerance(value){
  return Number.isFinite(Number(value))?Math.max(0,Math.min(8,Number(value))):2.5;
}
function traceCompare(a,b){return a[0]-b[0]||a[1]-b[1];}
function traceDistanceSq(p,a,b){
  const dx=b[0]-a[0],dy=b[1]-a[1],den=dx*dx+dy*dy;
  const t=den?Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den)):0;
  return (p[0]-a[0]-t*dx)**2+(p[1]-a[1]-t*dy)**2;
}
function traceArea(points){
  let sum=0;
  for(let i=0;i<points.length;i++){
    const a=points[i],b=points[(i+1)%points.length];sum+=a[0]*b[1]-a[1]*b[0];
  }
  return sum/2;
}
function traceSpanError(points,start,end,a,b){
  let max=0;
  for(let i=start;i<=end;i++)max=Math.max(max,traceDistanceSq(points[i%points.length],a,b));
  return max;
}
function traceSplitIndices(points,closed,locked,tolerance){
  const n=points.length,anchors=[];
  for(let i=0;i<n;i++)if(locked?.has(points[i].join(',')))anchors.push(i);
  if(!closed){if(anchors[0]!==0)anchors.unshift(0);if(anchors.at(-1)!==n-1)anchors.push(n-1);}
  else if(!anchors.length)anchors.push(0);
  if(closed&&anchors.length===1){
    const first=anchors[0];let far=first,distance=-1;
    for(let i=0;i<n;i++){
      const d=(points[i][0]-points[first][0])**2+(points[i][1]-points[first][1])**2;
      if(d>distance){distance=d;far=i;}
    }
    if(far!==first)anchors.push(far);anchors.sort((a,b)=>a-b);
  }
  const keep=new Set(anchors),stack=[];
  for(let i=0;i<anchors.length-(closed?0:1);i++)
    stack.push([anchors[i],i+1<anchors.length?anchors[i+1]:anchors[0]+n]);
  while(stack.length){
    const [start,end]=stack.pop(),a=points[start%n],b=points[end%n];
    let peak=-1,max=tolerance*tolerance;
    for(let i=start+1;i<end;i++){
      const d=traceDistanceSq(points[i%n],a,b);
      if(d>max+1e-9){max=d;peak=i;}
    }
    if(peak>=0){keep.add(peak%n);stack.push([start,peak],[peak,end]);}
  }
  // Remove artificial closed-ring starting points and redundant split points.
  // Testing the ORIGINAL span prevents several small removals accumulating drift.
  let ids=[...keep].sort((a,b)=>a-b),changed=true;
  while(changed&&ids.length>(closed?3:2)){
    changed=false;
    for(let j=closed?0:1;j<ids.length-(closed?0:1);j++){
      const id=ids[j];if(locked?.has(points[id].join(',')))continue;
      const start=ids[(j+ids.length-1)%ids.length],stop=ids[(j+1)%ids.length];
      const end=stop>start?stop:stop+n;
      if(traceSpanError(points,start,end,points[start],points[stop])<=tolerance*tolerance+1e-9){
        ids.splice(j,1);changed=true;break;
      }
    }
  }
  return ids;
}
// Orthogonal least squares uses arc-length weights, so a densely jagged part of
// a stroke does not outweigh a long clean side. Huber weights limit pen notches.
function traceFitLine(points,start,end,tolerance){
  const samples=[];
  for(let i=start;i<=end;i++){
    const p=points[i%points.length];let weight=0;
    if(i>start){const q=points[(i-1)%points.length];weight+=Math.hypot(p[0]-q[0],p[1]-q[1])/2;}
    if(i<end){const q=points[(i+1)%points.length];weight+=Math.hypot(p[0]-q[0],p[1]-q[1])/2;}
    if(weight)samples.push({p,weight});
  }
  let line=null;
  for(let pass=0;pass<3;pass++){
    let weight=0,x=0,y=0;
    const weights=samples.map(sample=>{
      let w=sample.weight;
      if(line){const r=Math.abs((sample.p[0]-line.x)*line.nx+(sample.p[1]-line.y)*line.ny);
        w*=Math.min(1,Math.max(.1,tolerance*.5)/Math.max(r,1e-12));}
      weight+=w;x+=w*sample.p[0];y+=w*sample.p[1];return w;
    });
    if(!weight)return null;x/=weight;y/=weight;
    let xx=0,yy=0,xy=0;
    samples.forEach(({p},i)=>{const dx=p[0]-x,dy=p[1]-y,w=weights[i];xx+=w*dx*dx;yy+=w*dy*dy;xy+=w*dx*dy;});
    if(xx+yy<1e-12)return null;
    const angle=.5*Math.atan2(2*xy,xx-yy);
    line={x,y,nx:-Math.sin(angle),ny:Math.cos(angle)};
  }
  return line;
}
function traceFitVertices(points,ids,closed,locked,tolerance,cornerLimit){
  const n=points.length,count=ids.length,result=ids.map(i=>points[i]),adjusted=ids.slice(),lines=[];
  for(let j=0;j<count-(closed?0:1);j++){
    const start=ids[j],stop=ids[(j+1)%count],end=stop>start?stop:stop+n;
    lines.push(traceFitLine(points,start,end,tolerance));
  }
  for(let j=closed?0:1;j<count-(closed?0:1);j++){
    const p=points[ids[j]];if(locked?.has(p.join(',')))continue;
    const a=lines[(j+lines.length-1)%lines.length],b=lines[j];if(!a||!b)continue;
    const den=a.nx*b.ny-a.ny*b.nx;if(Math.abs(den)<.05)continue;
    const ca=a.nx*a.x+a.ny*a.y,cb=b.nx*b.x+b.ny*b.y;
    const q=[(ca*b.ny-a.ny*cb)/den,(a.nx*cb-ca*b.nx)/den];
    if(Math.hypot(q[0]-p[0],q[1]-p[1])>cornerLimit+1e-9)continue;
    // Rounded ink corners can put the split point a few pixels along either
    // side. Locate the fitted intersection on the ORIGINAL corner arc before
    // checking each side, instead of preserving that arbitrary split point.
    const previous=j?ids[j-1]:ids[count-1]-n;
    const next=j+1<count?ids[j+1]:ids[0]+n;
    let nearest=-1,distance=Infinity;
    for(let i=Math.ceil((previous+ids[j])/2);i<=Math.floor((ids[j]+next)/2);i++){
      const k=(i+n)%n,r=points[k],d=(q[0]-r[0])**2+(q[1]-r[1])**2;
      if(d<distance){distance=d;nearest=k;}
    }
    if(distance<=tolerance*tolerance+1e-9){result[j]=q;adjusted[j]=nearest;}
  }
  return {points:result,ids:adjusted};
}
function tracePathWithin(points,ids,result,closed,tolerance){
  if(new Set(ids).size!==ids.length)return false;
  let wraps=0;
  for(let j=0;j<ids.length-(closed?0:1);j++)if(ids[(j+1)%ids.length]<ids[j])wraps++;
  if(wraps!==(closed?1:0))return false;
  for(let j=0;j<ids.length-(closed?0:1);j++){
    const start=ids[j],stop=ids[(j+1)%ids.length],end=stop>start?stop:stop+points.length;
    if(traceSpanError(points,start,end,result[j],result[(j+1)%result.length])>tolerance*tolerance+1e-8)return false;
  }
  return true;
}
function traceRegularizePath(points,closed,locked,tolerance){
  if(points.length<3)return points;
  if(!tolerance)return traceSplitIndices(points,closed,locked,0).map(i=>points[i]);
  // Coarse partitions find the long sides through rounded ink corners. They
  // are accepted ONLY when the final fitted perimeter meets the real bound.
  for(const partitionTolerance of [4*tolerance,2*tolerance,tolerance]){
    const ids=traceSplitIndices(points,closed,locked,partitionTolerance);
    if(ids.length<(closed?3:2))continue;
    const fitted=traceFitVertices(points,ids,closed,locked,tolerance,2*partitionTolerance);
    if(tracePathWithin(points,fitted.ids,fitted.points,closed,tolerance))return fitted.points;
    if(partitionTolerance===tolerance)return ids.map(i=>points[i]);
  }
  return points;
}
function traceCanonicalPath(points,closed,locked){
  let path=points.slice(),reverse=false;
  if(closed){
    let first=0;
    for(let i=1;i<path.length;i++)if(traceCompare(path[i],path[first])<0)first=i;
    path=path.slice(first).concat(path.slice(0,first));
    if(traceCompare(path[1],path.at(-1))>0){path=[path[0],...path.slice(1).reverse()];reverse=true;}
  }else if(traceCompare(path[0],path.at(-1))>0){path.reverse();reverse=true;}
  return {path,reverse,locked};
}
function tracePreparePerimeter(ring,fixed,tolerance,cache){
  const locked=new Set(),anchors=[];
  for(let i=0;i<ring.length;i++)if(fixed(ring[i])){anchors.push(i);locked.add(ring[i].join(','));}
  const bounds=ring.reduce((b,p)=>[Math.min(b[0],p[0]),Math.min(b[1],p[1]),Math.max(b[2],p[0]),Math.max(b[3],p[1])],[Infinity,Infinity,-Infinity,-Infinity]);
  // Do not collapse narrow strips when the user chooses a broad pen tolerance.
  const effective=Math.min(traceTolerance(tolerance),Math.min(bounds[2]-bounds[0],bounds[3]-bounds[1])*.1);
  const chains=[];
  function add(source,closed){
    const {path,reverse}=traceCanonicalPath(source,closed,locked);
    const key=[closed,path.length,path[0].join(','),path.at(-1).join(','),path[Math.floor(path.length/2)].join(',')].join('|');
    const bucket=cache.get(key)||[];
    let chain=bucket.find(c=>c.raw.length===path.length&&c.raw.every((p,i)=>p[0]===path[i][0]&&p[1]===path[i][1]));
    if(!chain){chain={raw:path,closed,locked:new Set(locked),tolerance:effective,points:null};bucket.push(chain);cache.set(key,bucket);}
    else{chain.tolerance=Math.min(chain.tolerance,effective);for(const p of locked)chain.locked.add(p);}
    chains.push({chain,reverse});
  }
  if(anchors.length<2)add(ring,true);
  else for(let j=0;j<anchors.length;j++){
    const start=anchors[j],stop=anchors[(j+1)%anchors.length],end=stop>start?stop:stop+ring.length,path=[];
    for(let i=start;i<=end;i++)path.push(ring[i%ring.length]);
    add(path,false);
  }
  return {ring,chains,tolerance:effective};
}
function traceAssemblePerimeter(prepared){
  const result=[];
  for(const {chain,reverse} of prepared.chains){
    let points=chain.points;
    if(reverse)points=chain.closed?[points[0],...points.slice(1).reverse()]:points.slice().reverse();
    result.push(...(chain.closed?points:points.slice(0,-1)));
  }
  return result;
}
function traceValidPerimeter(original,points){
  if(points.length<3||points.length>500)return false;
  const before=traceArea(original),after=traceArea(points);
  if(before*after<=0||Math.abs(after-before)>Math.abs(before)*.15+1e-6)return false;
  const repaired=uncrossTraceRing(points);
  // The automatic result must be simple already. Reordering crossings would
  // change the relationship to adjacent fields and to the scanned perimeter.
  return repaired&&repaired.every((p,i)=>p===points[i]);
}
function traceFinishPerimeters(prepared,cache){
  const chains=[...cache.values()].flat();
  for(const chain of chains){
    chain.stage=0;
    chain.points=traceRegularizePath(chain.raw,chain.closed,chain.locked,chain.tolerance);
  }
  // If a fit creates a crossing, use a stricter partition of its complete shared
  // chains on EVERY side, then exact collinear reduction as the last fallback.
  // A per-polygon fallback would create slivers along a shared boundary.
  let changed=true;
  while(changed){
    changed=false;
    for(const item of prepared){
      const points=traceAssemblePerimeter(item);
      if(traceValidPerimeter(item.ring,points))continue;
      for(const {chain} of item.chains)if(chain.stage<2){
        chain.stage++;
        chain.points=traceSplitIndices(chain.raw,chain.closed,chain.locked,
          chain.stage===1?chain.tolerance:0).map(i=>chain.raw[i]);
        changed=true;
      }
    }
  }
  return prepared.map(item=>{
    const points=traceAssemblePerimeter(item);return traceValidPerimeter(item.ring,points)?points:null;
  });
}
function straightenRing(points,junction,tolerance){
  if(points.length<3)return points;
  const cache=new Map(),prepared=tracePreparePerimeter(points,junction,tolerance,cache);
  return traceFinishPerimeters([prepared],cache)[0]||points;
}
function traceLandUses(pixels, forest, width, height, blackWidth, tolerance=2.5) {
  const size = width * height;
  const dark = new Uint8Array(size), wall = new Uint8Array(size);
  const colored = new Uint8Array(size), red = new Uint8Array(size);
  for (let i = 0; i < size; i++) {
    const [r,g,b] = [pixels[4*i], pixels[4*i+1], pixels[4*i+2]];
    dark[i] = Math.max(r,g,b) < 155 && Math.max(r,g,b)-Math.min(r,g,b) < 48;
    red[i] = r-g > 22 && r-b > 18 && g-b < (r-g)*0.65;
    colored[i] = Math.max(r,g,b)-Math.min(r,g,b) > 17 && Math.min(r,g,b)>90;
  }
  // Printed ownership bands are bright, broad red. Preserve thin red pen dividers.
  const printed=new Uint8Array(size), work=new Int32Array(size);
  const bright=i=>red[i] && pixels[4*i]>185 && pixels[4*i]-pixels[4*i+1]>68;
  let end=0;
  for(let y=2;y<height-2;y++)for(let x=2;x<width-2;x++){
    const i=y*width+x;
    if(bright(i)&&bright(i-2)&&bright(i+2)&&bright(i-2*width)&&bright(i+2*width)){
      printed[i]=1;work[end++]=i;
    }
  }
  for(let head=0;head<end;head++){
    const i=work[head];red[i]=0;colored[i]=0;
    for(const n of [i-1,i+1,i-width,i+width]){
      if(n>=0&&n<size&&!printed[n]&&bright(n)){printed[n]=1;work[end++]=n;}
    }
  }
  for (let y=1; y<height-1; y++) for(let x=1; x<width-1; x++) {
    const i=y*width+x;
    let count=0;
    for(let dy=-1;dy<=1;dy++) for(let dx=-1;dx<=1;dx++) count+=dark[i+dy*width+dx];
    wall[i]=red[i] || (dark[i] && count>=blackWidth) || (forest[i*4+3] && forest[i*4]<64);
  }
  // Heal one- or two-pixel breaks in a pen divider only when both ends
  // have an aligned run of original red ink. Added pixels never seed a join.
  for(let y=4;y<height-4;y++)for(let x=4;x<width-4;x++){
    const i=y*width+x;
    if(!red[i])continue;
    for(const step of [1,width,width+1,width-1]){
      if(!red[i-step]||!red[i-2*step]||red[i+step])continue;
      const gap=red[i+2*step]?1:2;
      const end=i+(gap+1)*step;
      if(!red[end]||!red[end+step])continue;
      wall[i+step]=1;
      if(gap===2)wall[i+2*step]=1;
    }
  }
  // Label enclosed regions; short annotations inside a region do not split it.
  const labels=new Int32Array(size), queue=new Int32Array(size);
  const regions=[null], stride=width+1;
  for(let start=0;start<size;start++){
    if(labels[start] || wall[start])continue;
    const id=regions.length;
    let tail=1,edge=false,tint=0,ink=0,wood=0;
    let sumR=0,sumG=0,sumB=0,minX=width,minY=height,maxX=0,maxY=0;
    labels[start]=id;queue[0]=start;
    for(let head=0;head<tail;head++){
      const i=queue[head],x=i%width,y=Math.floor(i/width);
      edge ||= x===0 || y===0 || x===width-1 || y===height-1;
      minX=Math.min(minX,x);maxX=Math.max(maxX,x);
      minY=Math.min(minY,y);maxY=Math.max(maxY,y);
      sumR+=pixels[4*i];sumG+=pixels[4*i+1];sumB+=pixels[4*i+2];
      tint+=colored[i];wood+=forest[4*i]>128?1:0;
      for(const n of [x?i-1:-1,x+1<width?i+1:-1,i-width,i+width]){
        if(n<0||n>=size)continue;
        ink+=red[n];
        if(!labels[n]&&!wall[n]){labels[n]=id;queue[tail++]=n;}
      }
    }
    regions.push({area:tail,ink,minX,minY,maxX,maxY,color:[sumR/tail,sumG/tail,sumB/tail],speck:!edge && tail<36, valid:!edge && tail>=36, suggested:tint>tail*.22||wood>tail*.5||ink>=5});
  }
  // Tiny islands inside printed letters and numbers belong to the surrounding field.
  for(let i=0;i<size;i++)if(labels[i] && regions[labels[i]].speck)labels[i]=0;
  // Extend adjacent interiors to the centre of ink strokes for a shared boundary.
  let tail=0;
  for(let i=width+1;i<size-width-1;i++)if(labels[i] &&
    (!labels[i-1]||!labels[i+1]||!labels[i-width]||!labels[i+width]))queue[tail++]=i;
  for(let head=0;head<tail;head++){
    const i=queue[head];
    for(const n of [i-1,i+1,i-width,i+width])
      if(n>=0&&n<size&&!labels[n]){labels[n]=labels[i];queue[tail++]=n;}
  }
  // A closed loop in lettering (e.g. 0 or 8) can exceed the speck threshold
  // at high zoom. Adjacent counters may also touch across a narrow stroke.
  const neighbor=new Int32Array(regions.length),protectedInk=new Uint8Array(regions.length);
  const runnerUp=new Int32Array(regions.length);
  function note(id,other,i,j){
    if(!id||!other||id===other)return;
    const first=neighbor[id];
    if(other!==first){
      if(!first || regions[other].area>regions[first].area){
        runnerUp[id]=first;neighbor[id]=other;
      }else if(!runnerUp[id] || regions[other].area>regions[runnerUp[id]].area)runnerUp[id]=other;
    }
    if(red[i]||red[j]||(forest[4*i+3]&&forest[4*i]<64)||
       (forest[4*j+3]&&forest[4*j]<64))protectedInk[id]=1;
  }
  for(let y=0;y<height-1;y++)for(let x=0;x<width-1;x++){
    const i=y*width+x,id=labels[i];
    if(id!==labels[i+1]){note(id,labels[i+1],i,i+1);note(labels[i+1],id,i+1,i);}
    if(id!==labels[i+width]){note(id,labels[i+width],i,i+width);note(labels[i+width],id,i+width,i);}
  }
  const owner=new Int32Array(regions.length);
  for(let id=1;id<regions.length;id++){
    const outer=regions[neighbor[id]],inner=regions[id];
    if(inner.valid && outer?.valid && inner.area<=outer.area*.08 &&
       inner.minX>outer.minX && inner.maxX<outer.maxX && inner.minY>outer.minY && inner.maxY<outer.maxY &&
       (!runnerUp[id] || regions[runnerUp[id]].area<=outer.area*.08) &&
       !inner.ink && !protectedInk[id] &&
       inner.color.every((value,k)=>Math.abs(value-outer.color[k])<=20))owner[id]=neighbor[id];
  }
  for(let i=0;i<size;i++)if(owner[labels[i]])labels[i]=owner[labels[i]];
  const borders=new Map();
  function line(id,a,b){
    if(!borders.has(id)) borders.set(id,new Map());
    const links=borders.get(id);
    if(links.has(a)) regions[id].valid=false; // ambiguous point contact
    links.set(a,b);
  }
  for(let y=1;y<height-1;y++)for(let x=1;x<width-1;x++){
    const i=y*width+x,id=labels[i],v=y*stride+x;
    if(!regions[id]?.valid)continue;
    if(labels[i-width]!==id)line(id,v,v+1);
    if(labels[i+1]!==id)line(id,v+1,v+stride+1);
    if(labels[i+width]!==id)line(id,v+stride+1,v+stride);
    if(labels[i-1]!==id)line(id,v+stride,v);
  }
  const shapes=new Map(),outlines=[],perimeters=[],chainCache=new Map();
  for(const [id,links] of borders){
    if(!regions[id].valid)continue;
    const start=links.keys().next().value,ring=[];
    let v=start;
    do{
      ring.push([v%stride,Math.floor(v/stride)]);
      const next=links.get(v);links.delete(v);v=next;
    }while(v!==undefined&&v!==start);
    if(v!==start||links.size)continue; // open rings or holes require manual editing
    function junction([x,y]){
      const i=y*width+x;
      const a=labels[i],b=labels[i-1],c=labels[i-width],d=labels[i-width-1];
      return (a!==b && (c!==a&&c!==b || d!==a&&d!==b)) ||
             (c!==d && (a!==c&&a!==d || b!==c&&b!==d));
    }
    perimeters.push(tracePreparePerimeter(ring,junction,tolerance,chainCache));
    outlines.push({id,suggested:regions[id].suggested,
      bounds:ring.reduce(([l,t,r,b],[x,y])=>[Math.min(l,x),Math.min(t,y),Math.max(r,x),Math.max(b,y)],
                         [width,height,0,0])});
  }
  traceFinishPerimeters(perimeters,chainCache).forEach((points,i)=>{
    if(points){const {id,...shape}=outlines[i];shapes.set(id,{points,...shape});}
  });
  return {labels,shapes,tolerance:traceTolerance(tolerance)};
}
// Build the perimeter from labelled pixels before straightening. Independently
// straightened fragments can leave hairline gaps along the original shared edge.
// Restore the order around the perimeter when two non-neighbouring sides cross.
function uncrossTraceRing(points){
  if(points.length>500)return null;
  const ring=points.slice();
  const turn=(a,b,p)=>(b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]);
  const onSegment=(a,b,p)=>Math.abs(turn(a,b,p))<1e-9 &&
    p[0]>=Math.min(a[0],b[0]) && p[0]<=Math.max(a[0],b[0]) &&
    p[1]>=Math.min(a[1],b[1]) && p[1]<=Math.max(a[1],b[1]);
  const n=ring.length;
  if(n<3)return null;
  // Each reversal shortens the perimeter. Bound work for heavily tangled drafts.
  for(let pass=0;pass<=32;pass++){
    let crossed=false,touch=false;
    for(let i=0;i<n&&!crossed;i++){
      const a=ring[i],b=ring[(i+1)%n];
      if(a[0]===b[0] && a[1]===b[1])return null;
      for(let j=i+2;j<n;j++){
        if(i===0 && j===n-1)continue;
        const c=ring[j],d=ring[(j+1)%n];
        if(turn(a,b,c)*turn(a,b,d)<0 && turn(c,d,a)*turn(c,d,b)<0){
          ring.splice(i+1,j-i,...ring.slice(i+1,j+1).reverse());
          crossed=true;break;
        }
        if(onSegment(a,b,c)||onSegment(a,b,d)||onSegment(c,d,a)||onSegment(c,d,b))touch=true;
      }
    }
    if(!crossed)return touch||!ring.some((p,i)=>Math.abs(turn(p,ring[(i+1)%n],ring[(i+2)%n]))>1e-9)?null:ring;
  }
  return null;
}
function simplifiedTracePerimeter(ring,corners,fixed,tolerance,allowQuad){
  if(ring.length<3)return null;
  const cache=new Map(),prepared=tracePreparePerimeter(ring,fixed,tolerance,cache);
  return traceFinishPerimeters([prepared],cache)[0];
}
function selectedRasterOutline(trace,selected,width,height,edited){
  if(!selected.size)return [];
  if(selected.size===1){
    const shape=trace.shapes.get(selected.values().next().value);
    return shape.points.map(p=>edited.get(p.join(","))||p);
  }
  const {labels}=trace,stride=width+1,links=new Map();
  const bounds=Array.from(selected,id=>trace.shapes.get(id).bounds);
  const xmin=Math.max(1,Math.min(...bounds.map(b=>b[0]))-1);
  const xmax=Math.min(width-2,Math.max(...bounds.map(b=>b[2]))+1);
  const ymin=Math.max(1,Math.min(...bounds.map(b=>b[1]))-1);
  const ymax=Math.min(height-2,Math.max(...bounds.map(b=>b[3]))+1);
  let ambiguous=false;
  function edge(a,b){
    if(links.has(a))ambiguous=true;
    links.set(a,b);
  }
  for(let y=ymin;y<=ymax;y++)for(let x=xmin;x<=xmax;x++){
    const i=y*width+x;
    if(!selected.has(labels[i]))continue;
    const v=y*stride+x;
    if(!selected.has(labels[i-width]))edge(v,v+1);
    if(!selected.has(labels[i+1]))edge(v+1,v+stride+1);
    if(!selected.has(labels[i+width]))edge(v+stride+1,v+stride);
    if(!selected.has(labels[i-1]))edge(v+stride,v);
  }
  if(ambiguous||!links.size)return null;
  const start=links.keys().next().value,ring=[];
  let v=start;
  do{
    ring.push([v%stride,Math.floor(v/stride)]);
    const next=links.get(v);links.delete(v);v=next;
  }while(v!==start&&v!==undefined);
  if(v!==start||links.size)return null;
  // Fitted corners need not coincide with an integer raster vertex. Reattach
  // manual edits to their original corner arc when adjoining fields are merged.
  // Edits on an internal divider disappear with that divider, as they should.
  const anchors=new Map();
  for(const [key,point] of edited){
    const original=key.split(",").map(Number);
    let nearest=null,distance=(traceTolerance(trace.tolerance??2.5)+.75)**2;
    for(const p of ring){
      const d=(p[0]-original[0])**2+(p[1]-original[1])**2;
      if(d<distance){distance=d;nearest=p;}
    }
    if(nearest)anchors.set(nearest.join(","),point);
  }
  const fixed=p=>anchors.has(p.join(","));
  const corners=ring.filter((p,i)=>{
    const a=ring[(i+ring.length-1)%ring.length],b=ring[(i+1)%ring.length];
    return (a[0]!==b[0] && a[1]!==b[1]) || fixed(p);
  });
  const perimeter=simplifiedTracePerimeter(ring,corners,fixed,trace.tolerance??2.5,!corners.some(fixed));
  return perimeter?.map(p=>anchors.get(p.join(","))||p);
}
// Union the consistently fitted vector boundaries, instead of tracing the
// pixels again: a fresh independent fit could undo a shared-edge veto and
// reopen a gap beside a neighbouring field. Interior reversed edges cancel.
function selectedParcelOutline(shapes,selected,edited){
  const empty={points:[],origins:new Map()};
  if(!selected.size)return empty;
  const edges=new Map(),counts=new Map();
  for(const id of selected){
    const shape=shapes.get(id);if(!shape)return {points:null,origins:new Map()};
    shape.points.forEach((p,i)=>{
      const q=shape.points[(i+1)%shape.points.length],from=p.join(","),to=q.join(",");
      const key=from<to?from+"|"+to:to+"|"+from;
      const count=(counts.get(key)||0)+1;counts.set(key,count);
      const previous=edges.get(key);
      if(previous&&previous.from===to&&previous.to===from)edges.delete(key);
      else edges.set(key,{from,to,p,origin:shape.origins[i],invalid:!!previous||count>2});
    });
  }
  const links=new Map();
  for(const edge of edges.values()){
    if(edge.invalid||links.has(edge.from))return {points:null,origins:new Map()};
    links.set(edge.from,edge);
  }
  if(!links.size)return {points:null,origins:new Map()};
  const start=links.keys().next().value,ring=[];
  let current=start;
  do{
    const edge=links.get(current);if(!edge)return {points:null,origins:new Map()};
    ring.push({p:edited.get(edge.origin)||edge.p,origin:edge.origin});
    links.delete(current);current=edge.to;
  }while(current!==start);
  if(links.size)return {points:null,origins:new Map()}; // disjoint pieces or holes
  // After a union, an obsolete interior junction need not remain a redundant
  // vertex of a straight outer side. Deliberate manual vertices are retained.
  if(selected.size>1){
    let changed=true;
    while(changed&&ring.length>3){
      changed=false;
      for(let i=0;i<ring.length;i++){
        if(edited.has(ring[i].origin))continue;
        if(traceDistanceSq(ring[i].p,ring[(i+ring.length-1)%ring.length].p,
          ring[(i+1)%ring.length].p)<=1e-14){ring.splice(i,1);changed=true;break;}
      }
    }
  }
  return {points:ring.map(item=>item.p),origins:new Map(ring.map(item=>[item.p.join(","),item.origin]))};
}
function openRasterTracing(item, view) {
  const panel=document.createElement("section");
  panel.className="trace-map-panel";
  panel.setAttribute("aria-label","Auto Wkreślanie 5310");
  panel.innerHTML=`
    <div class="trace-map-heading"><strong>Auto Wkreślanie · 5310</strong>
      <button type="button" class="select-close trace-close" title="Zakończ wkreślanie (Esc)" aria-label="Zakończ wkreślanie">×</button></div>
    <div class="trace-map-options"><label>Kontury <select><option value="5">Grubsze</option><option value="3">Także cienkie</option><option value="7">Tylko bardzo grube</option></select></label>
      <label><input type="checkbox" class="trace-magnet"> Magnes</label>
      <label title="Nowe wydzielenie z tym samym A1 scala się z istniejącym, nawet gdy leży daleko"><input type="checkbox" class="trace-merge-a1" checked> Scalaj po A1</label>
      <button type="button" class="button ghost trace-fit">Cały raster</button></div>
    <div class="trace-map-options">
      <label>Analiza <select class="trace-quality"><option value="12000000">Dokładna</option><option value="6000000">Szybsza</option></select></label>
      <label title="Maksymalne odchylenie prostego boku od odczytanego konturu, w pikselach analizy">Prostowanie <select class="trace-tolerance"><option value="1">Delikatne</option><option value="2.5" selected>Proste boki</option><option value="4">Drżąca kreska</option></select></label>
    </div>
    <div class="trace-map-options">
      <label title="Dopasowuje bliskie, współbieżne boki obrysu do rzeczywistych granic działek"><input type="checkbox" class="trace-parcel-snap" checked> Dopasuj do 5216</label>
      <label title="Maksymalny zasięg dopasowania w metrach, niezależny od powiększenia mapy">Zasięg <input type="number" class="trace-parcel-distance" min="0.1" max="20" step="0.1" aria-label="Zasięg dopasowania do 5216 w metrach"> m</label>
    </div>
    <span class="trace-parcel-status"></span>
    <span class="trace-accuracy"></span>
    <div class="trace-map-save"><label>A1 <input class="trace-a1" autocomplete="off"></label>
      <button type="button" class="button primary trace-save">Zatwierdź 5310</button></div>
    <span role="status"></span>`;
  const stage=view.shell,canvas=document.createElement("canvas");
  canvas.className="trace-map-overlay";canvas.tabIndex=0;
  canvas.setAttribute("aria-label","Edycja wydzieleń 5310 na mapie");
  canvas.title="Prawy klik na boku dodaje węzeł. Klik kółkiem usuwa węzeł. Przeciągnięcie prawym lub środkowym przyciskiem przesuwa mapę.";
  stage.append(canvas,panel);
  const ctx=canvas.getContext("2d"),status=panel.querySelector("[role=status]");
  const save=panel.querySelector(".trace-save"),close=panel.querySelector(".trace-close");
  const quality=panel.querySelector(".trace-quality"),tolerance=panel.querySelector(".trace-tolerance");
  const accuracy=panel.querySelector(".trace-accuracy");
  const parcelSnap=panel.querySelector(".trace-parcel-snap");
  const parcelDistance=panel.querySelector(".trace-parcel-distance");
  const parcelStatus=panel.querySelector(".trace-parcel-status");
  parcelSnap.checked=true;
  let w,h,sx,sy;
  function configureResolution(){
    const budget=Number(quality.value)===6000000?6000000:12000000;
    const scale=Math.min(1,Math.sqrt(budget/(item.image.width*item.image.height)),
                         8192/Math.max(item.image.width,item.image.height));
    w=Math.max(1,Math.floor(item.image.width*scale));
    h=Math.max(1,Math.floor(item.image.height*scale));
    sx=(item.sourceWidth||item.image.width)/w;sy=(item.sourceHeight||item.image.height)/h;
  }
  configureResolution();
  const [a,b,c,d,e,f]=item.affine,det=a*e-b*d;
  // Choose the initial range from the imported preview, not from the current
  // analysis budget or screen zoom. Once chosen, it remains a map distance.
  const previewSx=(item.sourceWidth||item.image.width)/item.image.width;
  const previewSy=(item.sourceHeight||item.image.height)/item.image.height;
  const previewXX=(a*a+d*d)*previewSx*previewSx;
  const previewYY=(b*b+e*e)*previewSy*previewSy;
  const previewXY=(a*b+d*e)*previewSx*previewSy;
  let parcelRange=Math.round(Math.max(.5,Math.min(5,
    3*Math.sqrt((previewXX+previewYY+Math.hypot(previewXX-previewYY,2*previewXY))/2)))*10)/10;
  parcelDistance.value=String(parcelRange);
  // Display geometry uses easting and negative northing. The affine uses
  // original source pixels even when the decoder supplied a smaller preview.
  const worldAt=(x,y)=>({x:d*x*sx+e*y*sy+f,y:-(a*x*sx+b*y*sy+c)});
  const pixelAt=(x,y)=>({x:(e*(-y-c)-b*(x-f))/(det*sx),y:(a*(x-f)-d*(-y-c))/(det*sy)});
  const extent=[[0,0],[w,0],[w,h],[0,h]].map(([x,y])=>worldAt(x,y));
  const bounds=[Math.min(...extent.map(p=>p.x)),Math.min(...extent.map(p=>p.y)),
                Math.max(...extent.map(p=>p.x)),Math.max(...extent.map(p=>p.y))];
  let features=[],worker=null,analysisId=0,analysisPending=0,preparationId=0,failure="";
  let parcelIndex=null,parcelShapes=null,parcelMessage="",vertexOrigins=new Map();
  function stopAnalysisWorker(){
    const previous=worker;worker=null;analysisPending=0;
    if(previous){
      previous.onmessage=previous.onerror=null;
      previous.terminate();
    }
  }
  let pan=null,rectEnd=null,disposed=false;
  const screenAt=p=>{
    const q=worldAt(p.x,p.y);return view.worldToScreen(q.x,q.y);
  };
  const pixelAtScreen=(x,y)=>{
    const q=view.screenToWorld(x,y);return pixelAt(q.x,q.y);
  };
  function resize(){
    const ratio=Math.min(window.devicePixelRatio||1,2);
    canvas.width=Math.max(1,Math.round(stage.clientWidth*ratio));
    canvas.height=Math.max(1,Math.round(stage.clientHeight*ratio));
    draw();
  }
  let trace,anchor=null,drag=null,busy=false;
  const selected=new Set();
  const a1=panel.querySelector(".trace-a1");
  const completed=[];
  let outline=[],fitVersion=0,fitPending=false,fitMessage="",fitError=false,nativeOutline=null,sourceOutline=null;
  let queuedSave=false;
  function invalidateFit(){
    fitVersion++;fitPending=false;fitMessage="";fitError=false;nativeOutline=null;sourceOutline=null;queuedSave=false;
  }
  async function fitSelection(){
    invalidateFit();
    if(!outline?.length)return;
    const repaired=uncrossTraceRing(outline);
    if(repaired){
      outline=repaired;
      drafts.set(selectionKey(),outline.slice());
    }
    const version=fitVersion;
    const native=outline.map(([x,y])=>{const p=worldAt(x,y);return [-p.y,p.x];});
    fitPending=true;draw();
    try{
      const result=await view.fitOutline(native);
      if(disposed||version!==fitVersion)return;
      nativeOutline=result.points;sourceOutline=native;
      if(result.clipped){
        outline=result.points.map(([x,y])=>{const p=pixelAt(y,-x);return [p.x,p.y];});
        drafts.set(selectionKey(),outline.slice());activeNode=null;
        fitMessage="Dopasowano do istniejących 5310. Czerwony obrys pokazuje granicę do zapisu.";
      }
    }catch(error){
      if(disposed||version!==fitVersion)return;
      fitError=true;fitMessage=error.message;
    }finally{
      if(!disposed&&version===fitVersion){
        fitPending=false;draw();
        if(queuedSave&&!fitError)submit();
        queuedSave=false;
      }
    }
  }
  const edited=new Map(),drafts=new Map(),manualDrafts=new Set();
  const draftOrigins=new Map(),draftReports=new Map();
  let activeNode=null;
  const selectionKey=()=>Array.from(selected).sort((a,b)=>a-b).join(",");
  function clearDrafts(){
    drafts.clear();manualDrafts.clear();draftOrigins.clear();draftReports.clear();
    vertexOrigins=new Map();parcelShapes=null;parcelMessage="";
  }
  function keepDraft(){
    manualDrafts.add(selectionKey());
    drafts.set(selectionKey(),outline.slice());
    parcelMessage="Ręczne poprawki zachowano. Dopasowanie 5216 ich nie zmienia.";
    fitSelection();
  }
  function removeVertex(v){
    if(!v||outline.length<=3)return;
    outline.splice(outline.indexOf(v),1);activeNode=null;keepDraft();draw();
  }
  canvas.onkeydown=ev=>{
    if(busy||drag||ev.key!=="Delete"||!activeNode)return;
    ev.preventDefault();ev.stopPropagation();removeVertex(activeNode);
  };
  const mergeA1=panel.querySelector(".trace-merge-a1");
  const magnet=panel.querySelector(".trace-magnet");
  magnet.checked=view.magnetEnabled();
  magnet.onchange=()=>{if(magnet.checked!==view.magnetEnabled())view.toggleMagnet();};
  let snapHit=null;
  const cssScale=()=>view.scale()*Math.sqrt(Math.abs(det*sx*sy));
  let holdTimer=0;
  function armHold(ev){
    clearTimeout(holdTimer);
    if(!magnet.checked||ev.altKey||!drag)return;
    const current=drag;
    holdTimer=setTimeout(()=>{
      if(disposed||drag!==current||!magnet.checked)return;
      const vertex=drag.vertices[0],index=outline.indexOf(vertex);
      const ring=outline.map(([x,y])=>{const p=worldAt(x,y);return [p.x,p.y];});
      const targets=features.filter(view.isVisible);
      for(const saved of completed)targets.push({closed:true,geometry:[saved.map(([x,y])=>{
        const p=worldAt(x,y);return [p.x,p.y];})]});
      const fit=heldBoundarySide(ring,index,targets,view.scale());
      if(!fit||outline.length+fit.between.length>500)return;
      const endpoint=pixelAt(...fit.point);
      vertex[0]=endpoint.x;vertex[1]=endpoint.y;
      const extra=fit.between.map(p=>{const q=pixelAt(...p);return [q.x,q.y];});
      if(fit.step<0)outline.splice(index,0,...extra);
      else outline.splice(index+1,0,...extra.reverse());
      edited.set(drag.key,vertex);activeNode=vertex;drag=null;snapHit=null;
      keepDraft();draw();
    },650);
  }
  function moveNode(ev){
    const p=position(ev), ratio=cssScale();
    let target=p;
    snapHit=null;
    if(magnet.checked&&!ev.altKey){
      // Keep subpixel MAP coordinates all the way to the object creation API.
      const world=worldAt(p.x,p.y);
      // Mocniejszy magnes w auto-wkreślaniu: węzły łapią z 18 px,
      // krawędzie z 8 px (wcześniej domyślne 7/5 px).
      const hit=window.GeoStudioDrawingSnap.snapPoint(world,drag.targets,
        {scale:ratio/Math.sqrt(Math.abs(det*sx*sy)),
         vertexPixels:18,edgePixels:8});
      if(hit.kind){target=pixelAt(hit.point.x,hit.point.y);snapHit=hit;}
    }
    for(const vertex of drag.vertices){vertex[0]=target.x;vertex[1]=target.y;}
    draw();
  }
  function fittedParcelShapes(){
    if(parcelShapes)return parcelShapes;
    const entries=Array.from(trace.shapes);
    const rings=entries.map(([,shape])=>shape.points.map(([x,y])=>{const p=worldAt(x,y);return [p.x,p.y];}));
    // Decide shared boundaries together. A narrow neighbour that cannot safely
    // accept a fit must also veto that fit on the other side of the same edge.
    const results=globalThis.GeoStudioRasterParcelSnap.snapRings(rings,parcelIndex,{distance:parcelRange});
    parcelShapes=new Map();
    entries.forEach(([id,shape],index)=>{
      const points=shape.points,world=rings[index],result=results[index],origins=[];
      const snapped=result.points.map(([x,y])=>{const p=pixelAt(x,y);return [p.x,p.y];});
      // Retain the original corner/side identity for manual edits when the
      // selection is later extended to an adjoining field.
      let sourceEdge=0;
      for(let j=0;j<snapped.length;j++){
        const sourceIndex=result.sourceIndices[j];let original;
        if(sourceIndex!==null){sourceEdge=sourceIndex;original=points[sourceIndex];}
        else{
          const next=(sourceEdge+1)%world.length,start=world[sourceEdge],end=world[next];
          const dx=end[0]-start[0],dy=end[1]-start[1],den=dx*dx+dy*dy;
          const t=den?Math.max(0,Math.min(1,((result.points[j][0]-start[0])*dx+
            (result.points[j][1]-start[1])*dy)/den)):0;
          original=[points[sourceEdge][0]+t*(points[next][0]-points[sourceEdge][0]),
            points[sourceEdge][1]+t*(points[next][1]-points[sourceEdge][1])].map(v=>Math.round(v*1e8)/1e8);
        }
        origins.push(original.join(","));
      }
      const changed=result.points.length!==world.length||result.points.some((p,i)=>
        Math.hypot(p[0]-world[i][0],p[1]-world[i][1])>1e-6);
      parcelShapes.set(id,{points:snapped,origins,changed});
    });
    return parcelShapes;
  }
  function freshOutline(){
    vertexOrigins=new Map();parcelMessage="";
    if(!selected.size||!parcelSnap.checked||!parcelIndex?.size)
      return selectedRasterOutline(trace,selected,w,h,edited);
    const shapes=fittedParcelShapes(),result=selectedParcelOutline(shapes,selected,edited);
    vertexOrigins=result.origins;
    parcelMessage=Array.from(selected,id=>shapes.get(id).changed).some(Boolean)
      ?"Dopasowano obrys do 5216 z uwzględnieniem sąsiednich pól. Sprawdź czerwony obrys."
      :"Brak bezpiecznego dopasowania do 5216 w wybranym zasięgu.";
    return result.points;
  }
  function syncAttributes(){
    activeNode=null;
    const key=selectionKey(),cached=drafts.get(key);
    if(cached){
      outline=cached.slice();vertexOrigins=draftOrigins.get(key)||new Map();
      parcelMessage=manualDrafts.has(key)
        ?"Ręcznie poprawiony szkic zachowuje kształt przy zmianie ustawień 5216."
        :draftReports.get(key)||"";
    }else{
      outline=freshOutline();
      draftOrigins.set(key,vertexOrigins);draftReports.set(key,parcelMessage);
    }
    if(!selected.size)a1.value="";
    else a1.focus({preventScroll:true});
    fitSelection();
  }
  a1.oninput=()=>draw();
  function draw(rect=rectEnd){
    if(disposed)return;
    ctx.resetTransform();ctx.clearRect(0,0,canvas.width,canvas.height);
    if(!stage.clientWidth||!stage.clientHeight)return;
    ctx.scale(canvas.width/stage.clientWidth,canvas.height/stage.clientHeight);
    const origin=screenAt({x:0,y:0}),scale=view.scale();
    ctx.transform(d*sx*scale,-a*sx*scale,e*sy*scale,-b*sy*scale,origin.x,origin.y);
    const visibleRings=fitPending?[]:outline?[outline]:Array.from(selected,id=>trace.shapes.get(id).points);
    for(const ring of visibleRings){
      ctx.beginPath();
      ring.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));
      ctx.closePath();
      if(!fitError){ctx.fillStyle="rgba(0,165,180,.32)";ctx.fill();}
      ctx.strokeStyle="#ff0000";ctx.lineWidth=3/cssScale();ctx.stroke();
    }
    const radius=3.5/cssScale();
    for(const v of fitPending?[]:outline||[]){
      const [x,y]=v;
      ctx.fillStyle=v===activeNode?"#ffd04a":"#fff";ctx.strokeStyle="#007984";
      ctx.fillRect(x-radius,y-radius,2*radius,2*radius);
      ctx.strokeRect(x-radius,y-radius,2*radius,2*radius);
    }
    if(snapHit){
      const [x,y]=drag.vertices[0];
      ctx.beginPath();ctx.arc(x,y,2*radius,0,2*Math.PI);
      ctx.strokeStyle="#e47500";ctx.lineWidth=2/cssScale();ctx.stroke();
    }
    if(anchor&&rect){
      const p=screenAt(anchor),q=screenAt(rect);
      ctx.setTransform(canvas.width/stage.clientWidth,0,0,canvas.height/stage.clientHeight,0,0);
      ctx.strokeStyle="#096ed4";ctx.lineWidth=1;ctx.strokeRect(p.x,p.y,q.x-p.x,q.y-p.y);
    }
    status.textContent="Fragmenty wydzielenia: "+selected.size+" · Dodane 5310: "+completed.length+(snapHit?" · Magnes: "+snapHit.kind+" "+snapHit.code:"");
    if(!outline)status.textContent="Fragmenty muszą tworzyć jeden obrys bez otworów.";
    if(!trace)status.textContent=failure||"Rozpoznawanie pól na całym rastrze…";
    if(fitPending)status.textContent="Dopasowuję granicę do istniejących 5310…";
    else if(fitMessage)status.textContent=fitMessage;
    // The largest singular value bounds ground displacement even for a
    // rotated/sheared GCP transform. This is a simplification limit, not a
    // statement about the independent georeferencing accuracy of the scan.
    const xx=(a*a+d*d)*sx*sx,yy=(b*b+e*e)*sy*sy,xy=(a*b+d*e)*sx*sy;
    const groundPixel=Math.sqrt((xx+yy+Math.hypot(xx-yy,2*xy))/2);
    accuracy.textContent="Piksel analizy: do "+groundPixel.toFixed(2)+" m · Prostowanie: do "+
      (groundPixel*Number(tolerance.value)).toFixed(2)+" m. Dokładność położenia zależy także od kalibracji.";
    parcelStatus.textContent=parcelMessage||(!parcelSnap.checked?"Dopasowanie do 5216 wyłączone.":
      !parcelIndex?"Wczytywanie granic 5216…":!parcelIndex.size?"Brak granic 5216 w pobliżu rastra.":
      "Bliskie, współbieżne boki zostaną dopasowane do 5216. Zasięg: "+parcelRange.toFixed(1)+" m.");
    parcelDistance.disabled=busy||!parcelSnap.checked;
    save.disabled=busy||fitError||!trace||!outline?.length||!a1.value.trim();
  }
  function analyze(){
    if(disposed||!worker)return;
    trace=null;failure="";selected.clear();edited.clear();clearDrafts();outline=[];invalidateFit();
    activeNode=null;anchor=drag=pan=rectEnd=snapHit=null;clearTimeout(holdTimer);a1.value="";
    analysisPending=++analysisId;
    draw();
    worker.postMessage({threshold:Number(panel.querySelector("select").value),
      tolerance:Number(panel.querySelector(".trace-tolerance").value),id:analysisPending});
  }
  function position(event){
    const r=canvas.getBoundingClientRect();
    return pixelAtScreen(event.clientX-r.left,event.clientY-r.top);
  }
  canvas.onwheel=ev=>{
    ev.preventDefault();if(anchor||drag||pan)return;
    const r=canvas.getBoundingClientRect();
    view.zoomAt(Math.exp(-ev.deltaY*.00125),ev.clientX-r.left,ev.clientY-r.top);
  };
  canvas.onauxclick=ev=>ev.preventDefault();
  canvas.oncontextmenu=ev=>ev.preventDefault();
  panel.querySelector(".trace-fit").onclick=()=>view.fit(bounds);
  function nearestVertex(p,radius){
    let nearest=null,distance=radius/cssScale();
    for(const v of outline||[]){
      const d=Math.hypot(v[0]-p.x,v[1]-p.y);
      if(d<distance){distance=d;nearest=v;}
    }
    return nearest;
  }
  function editAt(p,button){
    if(!trace||busy||fitPending||!outline?.length)return;
    if(button===1){removeVertex(nearestVertex(p,14));return;}
    if(button!==2||outline.length>=500)return;
    let best=10/cssScale(),at=-1,point;
    for(let i=0;i<outline.length;i++){
      const [x,y]=outline[i],[u,v]=outline[(i+1)%outline.length];
      const dx=u-x,dy=v-y,len=dx*dx+dy*dy;
      if(!len)continue;
      const f=((p.x-x)*dx+(p.y-y)*dy)/len;
      if(f<=0||f>=1)continue;
      const q=[x+f*dx,y+f*dy],distance=Math.hypot(p.x-q[0],p.y-q[1]);
      if(distance<best){best=distance;at=i+1;point=q;}
    }
    if(at>=0 && !nearestVertex(p,4)){
      outline.splice(at,0,point);activeNode=point;keepDraft();draw();
    }

  }
  function movePan(ev){
    const dx=ev.clientX-pan.x,dy=ev.clientY-pan.y;
    if(!pan.moved&&Math.hypot(dx,dy)<4)return;
    pan.moved=true;pan.x=ev.clientX;pan.y=ev.clientY;view.panBy(dx,dy);
  }
  canvas.onpointerdown=ev=>{
    if(pan||anchor||drag)return;
    if(ev.button===1||ev.button===2){
      ev.preventDefault();canvas.setPointerCapture(ev.pointerId);
      pan={id:ev.pointerId,button:ev.button,x:ev.clientX,y:ev.clientY,moved:false};return;
    }
    if(busy||!trace||ev.button!==0)return;
    const p=position(ev);
    if(p.x<0||p.y<0||p.x>=w||p.y>=h)return;
    canvas.setPointerCapture(ev.pointerId);
    const nearest=fitPending?null:nearestVertex(p,8);
    canvas.focus({preventScroll:true});
    activeNode=nearest;
    if(nearest){
      const targets=features.filter(view.isVisible),parts=[];
      for(const ring of completed)targets.push({geometry:[ring.concat([ring[0]]).map(([x,y])=>{
        const p=worldAt(x,y);return [p.x,p.y];})],code:"5310"});
      for(let i=0;i<outline.length;i++){
        const v=outline[i],next=outline[(i+1)%outline.length];
        if(v===nearest||next===nearest)continue;
        parts.push([v,next].map(([x,y])=>{const p=worldAt(x,y);return [p.x,p.y];}));
      }
      if(parts.length)targets.push({geometry:parts,code:"5310"});
      let key=vertexOrigins.get(nearest.join(","))||nearest.join(",");
      for(const [original,point] of edited)if(point===nearest||
        (point[0]===nearest[0]&&point[1]===nearest[1])){key=original;break;}
      const vertex=nearest.slice();
      outline[outline.indexOf(nearest)]=vertex;
      drag={vertices:[vertex],previous:nearest,key,targets,start:p,moved:false};
      armHold(ev);
    }else if(!ev.shiftKey)anchor=p;
  };
  canvas.onpointermove=ev=>{
    if(pan){if(ev.pointerId===pan.id)movePan(ev);return;}
    if(drag){
      const p=position(ev);
      if(!drag.moved&&Math.hypot(p.x-drag.start.x,p.y-drag.start.y)*cssScale()<2)return;
      if(!drag.moved)invalidateFit();drag.moved=true;moveNode(ev);armHold(ev);
    }else if(anchor){rectEnd=position(ev);draw();}
  };
  canvas.onpointercancel=()=>{
    pan=null;rectEnd=null;
    if(drag){outline[outline.indexOf(drag.vertices[0])]=drag.previous;fitSelection();}
    anchor=null;drag=null;snapHit=null;draw();
  };
  canvas.onpointerup=ev=>{
    if(pan){
      if(pan.id!==ev.pointerId)return;
      movePan(ev);
      if(!pan.moved&&ev.button===pan.button){canvas.focus({preventScroll:true});editAt(position(ev),ev.button);}
      pan=null;return;
    }
    if(drag){if(drag.moved){moveNode(ev);edited.set(drag.key,drag.vertices[0]);activeNode=drag.vertices[0];keepDraft();}else outline[outline.indexOf(drag.vertices[0])]=drag.previous;
      drag=null;snapHit=null;draw();return;}
    if(!anchor||busy)return;
    const p=position(ev);
    const u=screenAt(anchor),v=screenAt(p);rectEnd=null;
    if(Math.hypot(v.x-u.x,v.y-u.y)<5){
      const id=p.x>=0&&p.y>=0&&p.x<w&&p.y<h?trace.labels[Math.floor(p.y)*w+Math.floor(p.x)]:0;
      if(!trace.shapes.has(id)){anchor=null;draw();status.textContent="Brak zamkniętego konturu. Sprawdź ustawienie Kontury lub przełącz analizę na Dokładną.";return;}
      if(selected.has(id))selected.delete(id);else selected.add(id);
    }else{
      for(const [id,shape] of trace.shapes){
        if(shape.suggested && shape.points.every(([x,y])=>{
          const q=screenAt({x,y});return q.x>=Math.min(u.x,v.x)&&q.x<=Math.max(u.x,v.x)&&q.y>=Math.min(u.y,v.y)&&q.y<=Math.max(u.y,v.y);
        }))selected.add(id);
      }
    }
    anchor=null;syncAttributes();draw();
  };
  panel.querySelector("select").onchange=analyze;
  tolerance.onchange=()=>{if(!busy)analyze();};
  function changeParcelSettings(){
    if(busy||disposed)return;
    const value=Number(parcelDistance.value);
    if(Number.isFinite(value)&&value>0)parcelRange=Math.max(.1,Math.min(20,value));
    parcelDistance.value=String(parcelRange);
    parcelShapes=null;
    clearTimeout(holdTimer);
    if(drag)outline[outline.indexOf(drag.vertices[0])]=drag.previous;
    anchor=drag=pan=rectEnd=snapHit=null;
    // Rebuild automatic previews only. A deliberate manual correction takes
    // precedence, including a move made with Alt or with the magnet disabled.
    for(const key of drafts.keys())if(!manualDrafts.has(key)){
      drafts.delete(key);draftOrigins.delete(key);draftReports.delete(key);
    }
    if(trace)syncAttributes();
    draw();
  }
  parcelSnap.onchange=parcelDistance.onchange=changeParcelSettings;
  quality.onchange=()=>{
    if(busy||disposed)return;
    const oldWidth=w,oldHeight=h;
    selected.clear();edited.clear();clearDrafts();outline=[];activeNode=null;
    anchor=drag=pan=rectEnd=snapHit=null;clearTimeout(holdTimer);invalidateFit();
    a1.value="";
    configureResolution();
    for(const ring of completed)for(const p of ring){p[0]*=w/oldWidth;p[1]*=h/oldHeight;}
    prepare();
  };
  function finish(){
    if(busy)return false;
    if(!disposed){
      disposed=true;preparationId++;analysisId++;stopAnalysisWorker();
      clearTimeout(holdTimer);anchor=drag=pan=rectEnd=snapHit=null;
      observer.disconnect();canvas.remove();panel.remove();view.closed();
    }
    return true;
  }
  close.onclick=finish;
  async function submit(){
    if(disposed||busy||drag||fitError||!outline?.length||!a1.value.trim())return;
    if(fitPending){queuedSave=true;return;}
    if(!nativeOutline)return;
    busy=true;save.disabled=close.disabled=a1.disabled=panel.querySelector("select").disabled=true;
    quality.disabled=tolerance.disabled=parcelSnap.disabled=parcelDistance.disabled=true;
    let message="";
    try{
      const points=outline;
      if(points.length>500)throw Error("Wspólny obrys przekracza limit 500 węzłów.");
      await view.add(sourceOutline,a1.value.trim(),nativeOutline,
        {mergeSameA1:!!mergeA1?.checked});
      completed.push(points);
      invalidateFit();
      for(const id of selected)trace.shapes.delete(id);
      selected.clear();outline=[];activeNode=null;clearDrafts();a1.value="";
      await view.refresh();
      // Nowy poligon musi wejść do maski, inaczej następna propozycja
      // wkreślenia wypadłaby dokładnie na nim.
      await prepare();
    }catch(error){message=error.message;}
    finally{
      busy=false;close.disabled=a1.disabled=panel.querySelector("select").disabled=false;
      quality.disabled=tolerance.disabled=parcelSnap.disabled=false;
      if(message)fitMessage=message;
      draw();a1.focus({preventScroll:true});
    }
  }
  save.onclick=submit;
  const observer=new ResizeObserver(resize);
  resize();observer.observe(stage);canvas.focus({preventScroll:true});
  async function prepare(){
    const generation=++preparationId;
    analysisId++;stopAnalysisWorker();trace=null;parcelShapes=null;invalidateFit();draw();
    try{
      const loaded=await view.featuresIn(bounds);
      if(disposed||generation!==preparationId)return;
      features=loaded;
      if(!globalThis.GeoStudioRasterParcelSnap)throw Error("Nie wczytano modułu dopasowania do 5216. Uruchom program ponownie.");
      parcelIndex=globalThis.GeoStudioRasterParcelSnap.buildIndex(features);
      const buffer=document.createElement("canvas");buffer.width=w;buffer.height=h;
      const g=buffer.getContext("2d",{willReadFrequently:true});
      g.fillStyle="white";g.fillRect(0,0,w,h);g.drawImage(item.image,0,0,w,h);
      const source=g.getImageData(0,0,w,h).data;
      g.clearRect(0,0,w,h);
      for(const feature of features){
        // Maska obejmuje WSZYSTKIE zamknięte poligony 5310 (niezależnie od
        // nazwy warstwy), żeby auto-wkreślanie nie proponowało obrysu w
        // miejscu, gdzie wydzielenie jest już wkreślone.
        if(!feature.closed)continue;
        if(feature.code!=="5310"&&feature.layer!=="Użytki Leśne")continue;
        g.beginPath();
        for(const ring of (feature.nativeGeometry||feature.geometry)){
          ring.forEach(([x,y],i)=>{const p=pixelAt(x,y);i?g.lineTo(p.x,p.y):g.moveTo(p.x,p.y);});
          g.closePath();
        }
        g.fillStyle="white";g.fill("evenodd");g.strokeStyle="black";g.lineWidth=2;g.stroke();
      }
      const mask=g.getImageData(0,0,w,h).data;
      const current=new Worker("/raster_trace.js");worker=current;
      const isCurrent=()=>!disposed&&generation===preparationId&&worker===current;
      current.onmessage=({data})=>{
        if(!isCurrent()||data.id!==analysisId||data.id!==analysisPending)return;
        analysisPending=0;
        trace=data.trace;failure=data.error||"";draw();
      };
      current.onerror=()=>{
        if(!isCurrent()||!analysisPending)return;
        analysisPending=0;trace=null;failure="Nie udało się rozpoznać pól na rastrze.";draw();
      };
      current.postMessage({source,mask,w,h},[source.buffer,mask.buffer]);analyze();
    }catch(error){
      if(disposed||generation!==preparationId)return;
      stopAnalysisWorker();failure="Błąd wczytywania mapy: "+error.message;draw();
    }
  }
  prepare();
  return {id:item.id,token:view.token,redraw:draw,close:finish,submit};
}

if(typeof WorkerGlobalScope!=="undefined" && self instanceof WorkerGlobalScope){
  let sheet;
  self.onmessage=({data})=>{
    if(data.source){sheet=data;return;}
    try{
      const trace=traceLandUses(sheet.source,sheet.mask,sheet.w,sheet.h,data.threshold,data.tolerance);
      self.postMessage({id:data.id,trace},[trace.labels.buffer]);
    }catch(error){self.postMessage({id:data.id,error:"Błąd rozpoznawania: "+error.message});}
  };
}
