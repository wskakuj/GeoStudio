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
    const points=fourCornerOutline(ring,tolerance) || straightenRing(corners,junction,tolerance);
    if(points.length>=3 && points.length<=500)shapes.set(id,{points,suggested:regions[id].suggested,
      bounds:ring.reduce(([l,t,r,b],[x,y])=>[Math.min(l,x),Math.min(t,y),Math.max(r,x),Math.max(b,y)],
                         [width,height,0,0])});
  }
  return {labels,shapes};
}
// Build the perimeter from labelled pixels before straightening. Independently
// straightened fragments can leave hairline gaps along the original shared edge.
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
  const quad=corners.some(fixed)?null:fourCornerOutline(ring,2.5);
  return (quad||straightenRing(corners,fixed,2.5)).map(p=>edited.get(p.join(","))||p);
}
function openRasterTracing(item, view) {
  const dialog=document.createElement("dialog");
  dialog.className="trace-dialog";
  dialog.setAttribute("aria-labelledby","trace-dialog-title");
  dialog.innerHTML=`
    <header class="trace-heading">
      <div><h2 id="trace-dialog-title">Wkreśl 5310 z rastra</h2><span class="trace-file"></span></div>
      <button type="button" class="select-close trace-close" aria-label="Zamknij okno">×</button>
    </header>
    <div class="trace-tools">
      <label>Czarne kontury <select><option value="5">Grubsze</option><option value="3">Także cienkie</option><option value="7">Tylko bardzo grube</option></select></label>
      <label class="toolbar-checkbox" title="Alt chwilowo wyłącza przyciąganie"><input type="checkbox" class="trace-magnet"> Magnes</label>
    </div>
    <div class="trace-stage"><canvas aria-label="Podgląd rastra i węzłów wydzielenia"></canvas></div>
    <footer class="trace-footer">
      <p class="trace-hint">Klikaj fragmenty jednego wydzielenia lub zaznacz je prostokątem. Przeciągnij węzeł, aby poprawić obrys.</p>
      <div class="trace-actions">
        <label>A1 wydzielenia <input class="trace-a1" autocomplete="off"></label>
        <span role="status"></span>
        <button type="button" class="button primary trace-save" title="Zatwierdź klawiszem Enter">Zatwierdź wydzielenie 5310</button>
      </div>
    </footer>`;
  dialog.querySelector(".trace-file").textContent=item.name;
  document.body.append(dialog);
  const canvas=dialog.querySelector("canvas"),status=dialog.querySelector("[role=status]");
  const save=dialog.querySelector(".trace-save"),close=dialog.querySelector(".trace-close");
  const scale=Math.min(2,1500/view.width,1100/view.height);
  canvas.width=Math.max(1,Math.round(view.width*scale));
  canvas.height=Math.max(1,Math.round(view.height*scale));
  const w=canvas.width,h=canvas.height,ctx=canvas.getContext("2d",{willReadFrequently:true});
  ctx.fillStyle="white";ctx.fillRect(0,0,w,h);
  const [a,b,c,d,e,f]=item.affine;
  const sx=(item.sourceWidth||item.image.width)/item.image.width;
  const sy=(item.sourceHeight||item.image.height)/item.image.height;
  const k=view.scale*scale;
  const px=x=>(x-view.center.x)*k+view.width*scale/2;
  const py=y=>(y-view.center.y)*k+view.height*scale/2;
  ctx.setTransform(d*sx*k,-a*sx*k,e*sy*k,-b*sy*k,px(f),py(-c));
  ctx.drawImage(item.image,0,0);
  ctx.resetTransform();
  const source=ctx.getImageData(0,0,w,h);
  ctx.clearRect(0,0,w,h);
  for(const feature of view.features){
    if(feature.layer!=="Użytki Leśne" || !feature.closed)continue;
    ctx.beginPath();
    for(const ring of feature.geometry){
      ring.forEach(([x,y],i)=>i?ctx.lineTo(px(x),py(y)):ctx.moveTo(px(x),py(y)));
      ctx.closePath();
    }
    ctx.fillStyle="white";ctx.fill("evenodd");ctx.strokeStyle="black";ctx.lineWidth=2;ctx.stroke();
  }
  const mask=ctx.getImageData(0,0,w,h).data;
  let trace,anchor=null,drag=null,busy=false;
  const selected=new Set();
  const a1=dialog.querySelector(".trace-a1");
  const completed=[];
  let adjusted=null,outline=[];
  const edited=new Map();
  const magnet=dialog.querySelector(".trace-magnet");
  magnet.checked=view.magnetEnabled();
  magnet.onchange=()=>{if(magnet.checked!==view.magnetEnabled())view.toggleMagnet();};
  let snapHit=null;
  const cssScale=()=>canvas.getBoundingClientRect().width/w;
  function moveNode(ev){
    const p=position(ev), ratio=cssScale();
    let target=p;
    snapHit=null;
    if(magnet.checked&&!ev.altKey){
      // Keep subpixel MAP coordinates all the way to the object creation API.
      const world={x:(p.x-px(0))/k,y:(p.y-py(0))/k};
      const hit=window.GeoStudioDrawingSnap.snapPoint(world,drag.targets,{scale:k*ratio});
      if(hit.kind){target={x:px(hit.point.x),y:py(hit.point.y)};snapHit=hit;}
    }
    for(const vertex of drag.vertices){vertex[0]=target.x;vertex[1]=target.y;}
    draw();
  }
  function syncAttributes(){
    adjusted=null;
    outline=selectedRasterOutline(trace,selected,w,h,edited);
    if(!selected.size)a1.value="";
    else a1.focus({preventScroll:true});
  }
  a1.oninput=()=>draw();
  a1.onkeydown=event=>{
    if(event.key==="Enter"&&!event.isComposing){
      event.preventDefault();event.stopPropagation();
      if(!save.disabled)save.click();
    }
  };
  function draw(rect){
    ctx.putImageData(source,0,0);
    const visibleRings=outline?[outline]:Array.from(selected,id=>trace.shapes.get(id).points);
    for(const ring of visibleRings){
      ctx.beginPath();
      ring.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));
      ctx.closePath();ctx.fillStyle="rgba(0,165,180,.32)";ctx.fill();
      ctx.strokeStyle="#ff0000";ctx.lineWidth=3/cssScale();ctx.stroke();
    }
    for(const ring of completed){
      ctx.beginPath();
      ring.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));
      ctx.closePath();ctx.strokeStyle="#ff0000";ctx.lineWidth=3/cssScale();ctx.stroke();
    }
    const radius=3.5/cssScale();
    for(const [x,y] of outline||[]){
      ctx.fillStyle="#fff";ctx.strokeStyle="#007984";
      ctx.fillRect(x-radius,y-radius,2*radius,2*radius);
      ctx.strokeRect(x-radius,y-radius,2*radius,2*radius);
    }
    if(snapHit){
      const [x,y]=drag.vertices[0];
      ctx.beginPath();ctx.arc(x,y,2*radius,0,2*Math.PI);
      ctx.strokeStyle="#e47500";ctx.lineWidth=2/cssScale();ctx.stroke();
    }
    if(adjusted){
      ctx.beginPath();
      adjusted.forEach(([x,y],i)=>i?ctx.lineTo(px(y),py(-x)):ctx.moveTo(px(y),py(-x)));
      ctx.closePath();ctx.fillStyle="rgba(240,150,0,.35)";ctx.fill();
      ctx.strokeStyle="#cb7100";ctx.lineWidth=3/cssScale();ctx.stroke();
    }
    save.textContent=adjusted?"Zatwierdź dopasowany obrys":"Zatwierdź wydzielenie 5310";
    if(rect){ctx.strokeStyle="#096ed4";ctx.strokeRect(anchor.x,anchor.y,rect.x-anchor.x,rect.y-anchor.y);}
    status.textContent="Fragmenty wydzielenia: "+selected.size+" · Dodane 5310: "+completed.length+(snapHit?" · Magnes: "+snapHit.kind+" "+snapHit.code:"");
    if(!outline)status.textContent="Fragmenty muszą tworzyć jeden obrys bez otworów.";
    save.disabled=busy||!outline?.length||!a1.value.trim();
  }
  function analyze(){
    trace=traceLandUses(source.data,mask,w,h,Number(dialog.querySelector("select").value));
    selected.clear();edited.clear();syncAttributes();draw();
  }
  function position(event){
    const r=canvas.getBoundingClientRect();
    return {x:Math.max(0,Math.min(w-1,(event.clientX-r.left)*w/r.width)),
            y:Math.max(0,Math.min(h-1,(event.clientY-r.top)*h/r.height))};
  }
  canvas.onpointerdown=ev=>{
    if(busy)return;
    const p=position(ev);
    canvas.setPointerCapture(ev.pointerId);
    let nearest=null,distance=8/cssScale();
    for(const v of outline||[]){
      const d=Math.hypot(v[0]-p.x,v[1]-p.y);
      if(d<distance){distance=d;nearest=v;}
    }
    if(nearest){
      const targets=view.snapFeatures().slice(),parts=[];
      for(let i=0;i<outline.length;i++){
        const v=outline[i],next=outline[(i+1)%outline.length];
        if(v===nearest||next===nearest)continue;
        parts.push([v,next].map(([x,y])=>[(x-px(0))/k,(y-py(0))/k]));
      }
      if(parts.length)targets.push({geometry:parts,code:"5310"});
      let key=nearest.join(",");
      for(const [original,point] of edited)if(point===nearest){key=original;break;}
      const vertex=nearest.slice();
      outline[outline.indexOf(nearest)]=vertex;
      drag={vertices:[vertex],previous:nearest,key,targets,start:p,moved:false};
    }else if(!ev.shiftKey)anchor=p;
  };
  canvas.onpointermove=ev=>{
    if(drag){
      const p=position(ev);
      if(!drag.moved&&Math.hypot(p.x-drag.start.x,p.y-drag.start.y)*cssScale()<2)return;
      adjusted=null;drag.moved=true;moveNode(ev);
    }else if(anchor)draw(position(ev));
  };
  canvas.onpointercancel=()=>{
    if(drag)outline[outline.indexOf(drag.vertices[0])]=drag.previous;
    anchor=null;drag=null;snapHit=null;draw();
  };
  canvas.onpointerup=ev=>{
    if(drag){if(drag.moved){moveNode(ev);edited.set(drag.key,drag.vertices[0]);}else outline[outline.indexOf(drag.vertices[0])]=drag.previous;
      drag=null;snapHit=null;draw();return;}
    if(!anchor||busy)return;
    const p=position(ev);
    if(Math.hypot(p.x-anchor.x,p.y-anchor.y)<5){
      const id=trace.labels[Math.floor(p.y)*w+Math.floor(p.x)];
      if(!trace.shapes.has(id)){anchor=null;draw();status.textContent="Brak prostego, zamkniętego konturu. Zmień próg czerni lub powiększenie widoku.";return;}
      if(selected.has(id))selected.delete(id);else selected.add(id);
    }else{
      for(const [id,shape] of trace.shapes){
        if(shape.suggested && shape.points.every(([x,y])=>x>=Math.min(anchor.x,p.x)&&x<=Math.max(anchor.x,p.x)&&y>=Math.min(anchor.y,p.y)&&y<=Math.max(anchor.y,p.y)))selected.add(id);
      }
    }
    anchor=null;syncAttributes();draw();
  };
  dialog.querySelector("select").onchange=analyze;
  close.onclick=()=>dialog.close();
  dialog.oncancel=event=>{if(busy)event.preventDefault();};
  dialog.onclose=()=>dialog.remove();
  save.onclick=async()=>{
    if(busy||!outline?.length||!a1.value.trim())return;
    busy=true;save.disabled=close.disabled=a1.disabled=dialog.querySelector("select").disabled=true;
    let message="";
    try{
      const points=outline;
      if(points.length>500)throw Error("Wspólny obrys przekracza limit 500 węzłów.");
      const native=points.map(([x,y])=>[-(y-py(0))/k,(x-px(0))/k]);
      const correction=await view.add(native,a1.value.trim(),adjusted);
      if(correction){
        adjusted=correction;
        message="Pomarańczowy obrys pomija powierzchnię zajętą przez 5310. Enter zatwierdza ten obrys.";
        return;
      }
      completed.push(adjusted?adjusted.map(([x,y])=>[px(y),py(-x)]):points);
      adjusted=null;
      for(const id of selected)trace.shapes.delete(id);
      selected.clear();outline=[];a1.value="";
      await view.refresh();
    }catch(error){message=error.message;}
    finally{
      busy=false;close.disabled=a1.disabled=dialog.querySelector("select").disabled=false;
      draw();if(message)status.textContent=message;
    }
  };
  dialog.showModal();analyze();
}
