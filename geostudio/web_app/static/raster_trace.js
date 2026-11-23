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
// Segment the visible, calibrated raster in preview-pixel coordinates.
// Simplify between junctions, preserving the same endpoints on both sides of a cut.
function straightenRing(points,junction,tolerance){
  if(points.length<4||!tolerance)return points;
  const compare=(i,j)=>points[i][0]-points[j][0]||points[i][1]-points[j][1];
  function structuralCorner(i){
    const p=points[i],prev=points[(i+points.length-1)%points.length],next=points[(i+1)%points.length];
    const ax=prev[0]-p[0],ay=prev[1]-p[1],bx=next[0]-p[0],by=next[1]-p[1];
    const a=Math.hypot(ax,ay),b=Math.hypot(bx,by);
    return Math.min(a,b)>=10 && Math.abs(ax*bx+ay*by)<0.4*a*b;
  }
  const locked=i=>junction(points[i])||structuralCorner(i);
  const anchors=[];
  for(let i=0;i<points.length;i++)if(locked(i))anchors.push(i);
  if(!anchors.length){
    let first=0;
    for(let i=1;i<points.length;i++)if(compare(i,first)<0)first=i;
    anchors.push(first);
  }
  if(anchors.length===1){
    const [x,y]=points[anchors[0]];
    let far=anchors[0],distance=0;
    for(let i=0;i<points.length;i++){
      const d=(points[i][0]-x)**2+(points[i][1]-y)**2;
      if(d>distance||(d===distance&&compare(i,far)<0)){far=i;distance=d;}
    }
    anchors.push(far);anchors.sort((a,b)=>a-b);
  }
  const keep=new Set(anchors),length=points.length;
  const segments=anchors.map((a,i)=>[a,i+1<anchors.length?anchors[i+1]:anchors[0]+length]);
  while(segments.length){
    const [start,end]=segments.pop();
    const [x,y]=points[start%length],[bx,by]=points[end%length];
    const dx=bx-x,dy=by-y,den=dx*dx+dy*dy;
    // Long printed sides often have shallow waves or a short pen notch.
    // Score their length as well as the single worst pixel. Weight by path
    // length so a noisy patch with many pixel corners cannot dominate the fit.
    const lengthPx=Math.sqrt(den);
    const band=Math.max(tolerance,Math.min(12,lengthPx*0.09));
    const notch=Math.max(band,Math.min(25,lengthPx*0.13));
    let outside=0,travel=0,previousDistance=0;
    let peak=-1,max=tolerance*tolerance;
    for(let i=start+1;i<end;i++){
      const [u,v]=points[i%length];
      const t=den?Math.max(0,Math.min(1,((u-x)*dx+(v-y)*dy)/den)):0;
      const d=(u-x-t*dx)**2+(v-y-t*dy)**2;
      const previous=points[(i-1)%length];
      const step=Math.hypot(u-previous[0],v-previous[1]);
      const distance=Math.sqrt(d);
      travel+=step;
      outside+=step*((distance>band)+(previousDistance>band))/2;
      previousDistance=distance;
      if(d>max+1e-8||(peak>=0&&Math.abs(d-max)<1e-8&&compare(i%length,peak%length)<0)){
        max=d;peak=i;
      }
    }
    const last=points[(end-1)%length];
    const step=Math.hypot(bx-last[0],by-last[1]);
    travel+=step;
    if(previousDistance>band)outside+=step/2;
    if(max<=notch*notch && outside<=travel*0.24)continue;
    if(peak>=0){keep.add(peak%length);segments.push([start,peak],[peak,end]);}
  }
  // The recursive split can retain a bump near the end of an otherwise
  // straight side. Revisit runs of surviving corners against the original
  // outline and replace a supported side by its corner-to-corner chord.
  const corners=[...keep].sort((a,b)=>a-b);
  const removed=new Set();
  const proposals=[];
  for(let first=0;first<corners.length;first++){
    for(let count=2;count<=Math.min(12,corners.length-2);count++){
      if(locked(corners[(first+count-1)%corners.length]))break;
      const start=corners[first],stop=corners[(first+count)%corners.length];
      const [ax,ay]=points[start],[bx,by]=points[stop];
      const dx=bx-ax,dy=by-ay,chord=Math.hypot(dx,dy);
      if(chord<12)continue;
      const band=Math.max(tolerance,Math.min(12,chord*.09));
      let path=0,sum=0,peak=0,lastDistance=0;
      for(let i=start;i!==stop;){
        const next=(i+1)%length,[x,y]=points[next];
        const along=((x-ax)*dx+(y-ay)*dy)/chord;
        const distance=Math.hypot((x-ax)-dx*Math.max(0,Math.min(chord,along))/chord,
                                  (y-ay)-dy*Math.max(0,Math.min(chord,along))/chord);
        const step=Math.hypot(x-points[i][0],y-points[i][1]);
        sum+=step*(distance+lastDistance)/2;
        path+=step;peak=Math.max(peak,distance);lastDistance=distance;i=next;
        if(peak>Math.max(band,Math.min(25,chord*.13)) || path>chord*1.35)break;
      }
      if(peak<=Math.max(band,Math.min(25,chord*.13)) && path<=chord*1.35 && sum<=path*band*.85)
        proposals.push({first,count,chord,start,stop});
    }
  }
  const ends=new Set();
  proposals.sort((a,b)=>b.chord-a.chord ||
    compare(compare(a.start,a.stop)<0?a.start:a.stop,compare(b.start,b.stop)<0?b.start:b.stop));
  for(const {first,count,start,stop} of proposals){
    if(removed.has(start)||removed.has(stop))continue;
    const inside=[];
    for(let k=1;k<count;k++)inside.push(corners[(first+k)%corners.length]);
    if(inside.some(i=>ends.has(i)) || corners.length-removed.size-inside.filter(i=>!removed.has(i)).length<3)continue;
    for(const i of inside)removed.add(i);
    ends.add(start);ends.add(stop);
  }
  return corners.length<3?points:corners.filter(i=>!removed.has(i)).map(i=>points[i]);
}
// Try four corners only when all four sides follow the observed perimeter.
// The shorter dimension limits the error for long, narrow fields.
function fourCornerOutline(ring,tolerance){
  if(ring.length<4||!tolerance)return null;
  const n=ring.length;
  function farthest(from){
    const [x,y]=ring[from];
    let far=from,max=0;
    for(let i=0;i<n;i++){
      const d=(ring[i][0]-x)**2+(ring[i][1]-y)**2;
      if(d>max){max=d;far=i;}
    }
    return far;
  }
  function distance(i,start,end){
    const [x,y]=ring[i],[a,b]=ring[start],[c,d]=ring[end];
    const dx=c-a,dy=d-b;
    const t=Math.max(0,Math.min(1,((x-a)*dx+(y-b)*dy)/(dx*dx+dy*dy)));
    return Math.hypot(x-a-t*dx,y-b-t*dy);
  }
  function peak(start,end){
    let far=start,max=0;
    for(let i=(start+1)%n;i!==end;i=(i+1)%n){
      const d=distance(i,start,end);
      if(d>max){max=d;far=i;}
    }
    return far;
  }
  const a=farthest(0),c=farthest(a);
  if(a===c)return null;
  const ids=[a,peak(a,c),c,peak(c,a)];
  if(new Set(ids).size!==4)return null;
  const corners=ids.map(i=>ring[i]);
  const shortest=Math.min(...corners.map(([x,y],i)=>{
    const q=corners[(i+1)%4];return Math.hypot(q[0]-x,q[1]-y);
  }));
  const band=Math.min(shortest*.12,Math.max(tolerance,Math.min(6,shortest*.045)));
  let turn=0;
  for(let j=0;j<4;j++){
    const [x,y]=corners[j],[u,v]=corners[(j+1)%4],[p,q]=corners[(j+2)%4];
    const cross=(u-x)*(q-v)-(v-y)*(p-u);
    if(!cross || turn*cross<0)return null;
    turn=cross;
    const start=ids[j],end=ids[(j+1)%4];
    for(let i=(start+1)%n;i!==end;i=(i+1)%n)
      if(distance(i,start,end)>band)return null;
  }
  return corners;
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
  const shapes=new Map();
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
    const corners=ring.filter((p,i)=>{
      const a=ring[(i+ring.length-1)%ring.length],b=ring[(i+1)%ring.length];
      return junction(p) || (a[0]!==b[0] && a[1]!==b[1]);
    });
    const points=simplifiedTracePerimeter(ring,corners,junction,tolerance,true);
    if(points)shapes.set(id,{points,suggested:regions[id].suggested,
      bounds:ring.reduce(([l,t,r,b],[x,y])=>[Math.min(l,x),Math.min(t,y),Math.max(r,x),Math.max(b,y)],
                         [width,height,0,0])});
  }
  return {labels,shapes};
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
  const quad=allowQuad && fourCornerOutline(ring,tolerance);
  if(quad)return quad;
  const simple=straightenRing(corners,fixed,tolerance);
  return uncrossTraceRing(simple)||uncrossTraceRing(corners);
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
  const fixed=p=>edited.has(p.join(","));
  const corners=ring.filter((p,i)=>{
    const a=ring[(i+ring.length-1)%ring.length],b=ring[(i+1)%ring.length];
    return (a[0]!==b[0] && a[1]!==b[1]) || fixed(p);
  });
  const perimeter=simplifiedTracePerimeter(ring,corners,fixed,2.5,!corners.some(fixed));
  return perimeter?.map(p=>edited.get(p.join(","))||p);
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
  const analysisScale=Math.min(1,Math.sqrt(6000000/(item.image.width*item.image.height)),
                               8192/Math.max(item.image.width,item.image.height));
  const w=Math.max(1,Math.round(item.image.width*analysisScale));
  const h=Math.max(1,Math.round(item.image.height*analysisScale));
  const sx=(item.sourceWidth||item.image.width)/w,sy=(item.sourceHeight||item.image.height)/h;
  const [a,b,c,d,e,f]=item.affine,det=a*e-b*d;
  // Display geometry uses easting and negative northing. The affine uses
  // original source pixels even when the decoder supplied a smaller preview.
  const worldAt=(x,y)=>({x:d*x*sx+e*y*sy+f,y:-(a*x*sx+b*y*sy+c)});
  const pixelAt=(x,y)=>({x:(e*(-y-c)-b*(x-f))/(det*sx),y:(a*(x-f)-d*(-y-c))/(det*sy)});
  const extent=[[0,0],[w,0],[w,h],[0,h]].map(([x,y])=>worldAt(x,y));
  const bounds=[Math.min(...extent.map(p=>p.x)),Math.min(...extent.map(p=>p.y)),
                Math.max(...extent.map(p=>p.x)),Math.max(...extent.map(p=>p.y))];
  let features=[],worker=null,analysisId=0,failure="";
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
  const edited=new Map(),drafts=new Map();
  let activeNode=null;
  const selectionKey=()=>Array.from(selected).sort((a,b)=>a-b).join(",");
  function keepDraft(){
    drafts.set(selectionKey(),outline.slice());
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
  function syncAttributes(){
    activeNode=null;
    outline=drafts.get(selectionKey())?.slice() || selectedRasterOutline(trace,selected,w,h,edited);
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
    save.disabled=busy||fitError||!trace||!outline?.length||!a1.value.trim();
  }
  function analyze(){
    if(!worker)return;
    trace=null;failure="";selected.clear();edited.clear();drafts.clear();outline=[];invalidateFit();
    activeNode=null;a1.value="";
    draw();
    worker.postMessage({threshold:Number(panel.querySelector("select").value),id:++analysisId});
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
      let key=nearest.join(",");
      for(const [original,point] of edited)if(point===nearest){key=original;break;}
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
      if(!trace.shapes.has(id)){anchor=null;draw();status.textContent="Brak prostego, zamkniętego konturu. Zmień próg czerni lub powiększenie widoku.";return;}
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
  function finish(){
    if(busy)return false;
    if(!disposed){
      disposed=true;worker?.terminate();observer.disconnect();canvas.remove();panel.remove();view.closed();
    }
    return true;
  }
  close.onclick=finish;
  async function submit(){
    if(disposed||busy||drag||fitError||!outline?.length||!a1.value.trim())return;
    if(fitPending){queuedSave=true;return;}
    if(!nativeOutline)return;
    busy=true;save.disabled=close.disabled=a1.disabled=panel.querySelector("select").disabled=true;
    let message="";
    try{
      const points=outline;
      if(points.length>500)throw Error("Wspólny obrys przekracza limit 500 węzłów.");
      await view.add(sourceOutline,a1.value.trim(),nativeOutline,
        {mergeSameA1:!!mergeA1?.checked});
      completed.push(points);
      invalidateFit();
      for(const id of selected)trace.shapes.delete(id);
      selected.clear();outline=[];activeNode=null;drafts.clear();a1.value="";
      await view.refresh();
      // Nowy poligon musi wejść do maski, inaczej następna propozycja
      // wkreślenia wypadłaby dokładnie na nim.
      await prepare();
    }catch(error){message=error.message;}
    finally{
      busy=false;close.disabled=a1.disabled=panel.querySelector("select").disabled=false;
      if(message)fitMessage=message;
      draw();a1.focus({preventScroll:true});
    }
  }
  save.onclick=submit;
  const observer=new ResizeObserver(resize);
  resize();observer.observe(stage);canvas.focus({preventScroll:true});
  async function prepare(){
    try{
      features=await view.featuresIn(bounds);
      if(disposed)return;
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
      worker=new Worker("/raster_trace.js");
      worker.onmessage=({data})=>{
        if(data.id!==analysisId)return;
        trace=data.trace;failure=data.error||"";draw();
      };
      worker.onerror=()=>{failure="Nie udało się rozpoznać pól na rastrze.";draw();};
      worker.postMessage({source,mask,w,h},[source.buffer,mask.buffer]);analyze();
    }catch(error){failure="Błąd wczytywania mapy: "+error.message;draw();}
  }
  prepare();
  return {id:item.id,token:view.token,redraw:draw,close:finish,submit};
}

if(typeof WorkerGlobalScope!=="undefined" && self instanceof WorkerGlobalScope){
  let sheet;
  self.onmessage=({data})=>{
    if(data.source){sheet=data;return;}
    try{
      const trace=traceLandUses(sheet.source,sheet.mask,sheet.w,sheet.h,data.threshold);
      self.postMessage({id:data.id,trace},[trace.labels.buffer]);
    }catch(error){self.postMessage({id:data.id,error:"Błąd rozpoznawania: "+error.message});}
  };
}
