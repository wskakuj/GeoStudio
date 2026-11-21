// Segment the visible, calibrated raster in preview-pixel coordinates.
// Simplify between junctions, preserving the same endpoints on both sides of a cut.
function straightenRing(points,junction,tolerance){
  if(points.length<4||!tolerance)return points;
  const compare=(i,j)=>points[i][0]-points[j][0]||points[i][1]-points[j][1];
  const anchors=[];
  for(let i=0;i<points.length;i++)if(junction(points[i]))anchors.push(i);
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
    let peak=-1,max=tolerance*tolerance;
    for(let i=start+1;i<end;i++){
      const [u,v]=points[i%length];
      const t=den?Math.max(0,Math.min(1,((u-x)*dx+(v-y)*dy)/den)):0;
      const d=(u-x-t*dx)**2+(v-y-t*dy)**2;
      if(d>max+1e-8||(peak>=0&&Math.abs(d-max)<1e-8&&compare(i%length,peak%length)<0)){
        max=d;peak=i;
      }
    }
    if(peak>=0){keep.add(peak%length);segments.push([start,peak],[peak,end]);}
  }
  return keep.size<3?points:points.filter((_,i)=>keep.has(i));
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
    labels[start]=id;queue[0]=start;
    for(let head=0;head<tail;head++){
      const i=queue[head],x=i%width,y=Math.floor(i/width);
      edge ||= x===0 || y===0 || x===width-1 || y===height-1;
      tint+=colored[i];wood+=forest[4*i]>128?1:0;
      for(const n of [x?i-1:-1,x+1<width?i+1:-1,i-width,i+width]){
        if(n<0||n>=size)continue;
        ink+=red[n];
        if(!labels[n]&&!wall[n]){labels[n]=id;queue[tail++]=n;}
      }
    }
    regions.push({speck:!edge && tail<36, valid:!edge && tail>=36, suggested:tint>tail*.22||wood>tail*.5||ink>=5});
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
    const points=straightenRing(corners,junction,tolerance);
    if(points.length>=3 && points.length<=500)shapes.set(id,{points,suggested:regions[id].suggested});
  }
  return {labels,shapes};
}
function openRasterTracing(item, view) {
  const dialog=document.createElement("dialog");
  dialog.style.cssText="width:min(92vw,1100px);padding:1rem;color:inherit;background:var(--panel,#fff)";
  dialog.innerHTML='<h2>Wkreśl 5310 z rastra</h2><p>Przeciągnij prostokąt, aby wybrać pola. Kliknij poligon i wpisz A1. Enter przechodzi do kolejnego pola. Po ostatnim wpisie możesz wskazać następny poligon. Shift i przeciągnięcie przesuwa węzeł wybranego obrysu. Przybliż mapę przed otwarciem, aby rozróżnić małe wydzielenia.</p><label>Czarne kontury <select><option value="5">Grubsze</option><option value="3">Także cienkie</option><option value="7">Tylko bardzo grube</option></select></label> <canvas style="display:block;max-width:100%;max-height:58vh;touch-action:none;cursor:crosshair;margin:.5rem auto"></canvas><div class="trace-attributes" style="max-height:18vh;overflow:auto"></div><p role="status"></p><button type="button" class="button primary">Dodaj wybrane 5310</button> <button type="button" class="button ghost">Zamknij</button>';
  document.body.append(dialog);
  const canvas=dialog.querySelector("canvas"),status=dialog.querySelector("[role=status]");
  const [save,close]=dialog.querySelectorAll("button");
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
  const attributes=dialog.querySelector(".trace-attributes");
  const inputs=new Map();
  let activeId=null;
  function syncAttributes(){
    for(const [id,input] of inputs){
      if(!selected.has(id)){input.parentElement.remove();inputs.delete(id);}
    }
    let firstAdded=null;
    let ordinal=0;
    for(const id of selected){
      ordinal++;
      if(!inputs.has(id)){
        const label=document.createElement("label");
        label.style.display="block";
        const caption=document.createElement("span");
        const input=document.createElement("input");
        input.type="text";input.autocomplete="off";
        label.append(caption,input);attributes.append(label);inputs.set(id,input);
        input.onfocus=()=>{activeId=id;draw();};
        input.onkeydown=ev=>{
          if(ev.key!=="Enter"||ev.isComposing)return;
          ev.preventDefault();ev.stopPropagation();
          const ordered=[...inputs.values()];
          const next=ordered[ordered.indexOf(input)+1];
          if(next)next.focus();
          else{canvas.tabIndex=0;canvas.focus();}
        };
        if(!firstAdded)firstAdded=input;
      }
      inputs.get(id).previousElementSibling.textContent=ordinal+". A1 ";
    }
    if(!selected.has(activeId))activeId=null;
    if(firstAdded)firstAdded.focus();
  }
  function draw(rect){
    ctx.putImageData(source,0,0);
    for(const id of selected){
      ctx.beginPath();
      trace.shapes.get(id).points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));
      ctx.closePath();ctx.fillStyle="rgba(0,165,180,.32)";ctx.fill();
      ctx.strokeStyle=id===activeId?"#eb7000":"#007984";ctx.lineWidth=id===activeId?3:1;ctx.stroke();
    }
    if(rect){ctx.strokeStyle="#096ed4";ctx.strokeRect(anchor.x,anchor.y,rect.x-anchor.x,rect.y-anchor.y);}
    status.textContent="Wybrane poligony: "+selected.size;
    save.disabled=busy||!selected.size;
  }
  function analyze(){
    trace=traceLandUses(source.data,mask,w,h,Number(dialog.querySelector("select").value));
    selected.clear();syncAttributes();draw();
  }
  function position(event){
    const r=canvas.getBoundingClientRect();
    return {x:Math.max(0,Math.min(w-1,Math.floor((event.clientX-r.left)*w/r.width))),
            y:Math.max(0,Math.min(h-1,Math.floor((event.clientY-r.top)*h/r.height)))};
  }
  canvas.onpointerdown=ev=>{
    if(busy)return;
    const p=position(ev);
    canvas.setPointerCapture(ev.pointerId);
    if(!ev.shiftKey){anchor=p;return;}
    let nearest=null,distance=10;
    for(const id of selected)for(const v of trace.shapes.get(id).points){
      const d=Math.hypot(v[0]-p.x,v[1]-p.y);
      if(d<distance){distance=d;nearest=v;}
    }
    if(nearest){
      drag=[];
      for(const shape of trace.shapes.values())for(const v of shape.points)
        if(v[0]===nearest[0]&&v[1]===nearest[1])drag.push(v);
    }
  };
  canvas.onpointermove=ev=>{if(drag){const p=position(ev);for(const v of drag){v[0]=p.x;v[1]=p.y;}draw();}else if(anchor)draw(position(ev));};
  canvas.onpointercancel=()=>{anchor=null;drag=null;draw();};
  canvas.onpointerup=ev=>{
    if(drag){drag=null;return;}
    if(!anchor||busy)return;
    const p=position(ev);
    if(Math.hypot(p.x-anchor.x,p.y-anchor.y)<5){
      const id=trace.labels[p.y*w+p.x];
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
    if(busy||!selected.size)return;
    busy=true;save.disabled=close.disabled=dialog.querySelector("select").disabled=true;
    for(const input of inputs.values())input.disabled=true;
    let count=0;
    try{
      for(const id of [...selected]){
        const points=trace.shapes.get(id).points.map(([x,y])=>[-(y-py(0))/k,(x-px(0))/k]);
        await view.add(points,inputs.get(id).value);
        trace.shapes.delete(id);
        selected.delete(id);count++;
      }
      await view.refresh();dialog.close();
    }catch(error){
      try{await view.refresh();}catch{}
      syncAttributes();draw();status.textContent="Dodano: "+count+". "+error.message;
    }finally{
      for(const input of inputs.values())input.disabled=false;
      busy=false;close.disabled=dialog.querySelector("select").disabled=false;save.disabled=!selected.size;
    }
  };
  dialog.showModal();analyze();
}
