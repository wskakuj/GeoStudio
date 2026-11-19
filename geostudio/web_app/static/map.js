/* GeoStudio 2.0 — read-only HTML5 map canvas.
   World coordinates: horizontal = GEO-MAP easting Y, vertical = -northing X.
   This matches the classic geodetic PySide6 orientation.
   No MAP editing code runs in this preview.
*/
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const token = document.querySelector('meta[name="api-token"]').content;
  const canvas = $("map-canvas"), shell = $("canvas-shell"), ctx = canvas.getContext("2d");
  const formatter = new Intl.NumberFormat("pl-PL");
  const state = {
    meta: null, features: [], visibleLayers: new Set(), hiddenGrades: new Set(),
    center: {x: 0, y: 0}, scale: 1, tool: "select",
    labels: true, grid: true, active: null, detail: null, pinned: new Set(),
    width: 1, height: 1, pixelRatio: 1, isDragging: false, drag: null,
    lastPick: null, scheduled: false, refreshTimer: null, queryCounter: 0,
    queryAbort: null, selectionRequest: 0, limited: false,
    firstLoad: true, inspectorCache: new Map()
  };
  const commands = [
    {name:"Otwórz plik GEO-MAP", hint:"Ctrl+O", run:()=> $("file-map").click()},
    {name:"Wczytaj plik stylów GeoStudio", hint:"JSON", run:()=> $("file-sidecar").click()},
    {name:"Dopasuj całą mapę", hint:"0", run:fitToMap},
    {name:"Zaznaczanie obiektów", hint:"S", run:()=>setTool("select")},
    {name:"Przesuwanie mapy", hint:"H", run:()=>setTool("pan")},
    {name:"Włącz / wyłącz etykiety", hint:"Aa", run:toggleLabels},
    {name:"Włącz / wyłącz siatkę", hint:"▦", run:toggleGrid},
    {name:"Pokaż wszystkie warstwy", hint:"Warstwy", run:showAllLayers},
    {name:"Zmień motyw płótna", hint:"◐", run:toggleTheme}
  ];
  let toastTimer;
  const htmlText = (node, value) => { node.textContent = String(value); };
  const api = async (path, options={}) => {
    const res = await fetch(path, {
      ...options,
      headers: {"X-GeoStudio-Token":token, ...(options.headers || {})},
      cache: "no-store"
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw Error(error.detail || ("Błąd HTTP " + res.status));
    }
    return res.json();
  };
  function inform(msg, isError=false) {
    htmlText($("status-message"), msg);
    const toast = $("toast"); toast.textContent = msg;
    toast.style.borderColor = isError ? "#d98769" : "#3a928d";
    toast.hidden = false; clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 3900);
  }
  function busy(on, label) {
    $("loading-overlay").hidden = !on;
    if (label) htmlText($("loading-detail"), label);
  }
  function display(n) { return n === undefined || n === null ? "—" : formatter.format(n); }
  function colorForLayer(layer) {
    if (layer === "Budynki") return "#cf947b";
    if (layer === "Działki") return "#83a5ca";
    if (layer === "Użytki Leśne") return "#57b69d";
    if (layer === "Użytki") return "#78ab89";
    if (layer === "Graniczniki") return "#d4b56e";
    return "#8ea4b7";
  }

  async function openMap(file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".map")) {
      inform("Wybierz plik z rozszerzeniem .MAP.", true);
      return;
    }
    busy(true,"Wczytywanie " + file.name);
    try {
      const meta = await api("/api/map", {
        method: "POST",
        headers: {"Content-Type":"application/octet-stream",
                  "X-Map-Name":encodeURIComponent(file.name)},
        body: file
      });
      state.meta = meta;
      state.active = null; state.detail = null; state.pinned.clear();
      state.features = []; state.inspectorCache.clear();
      state.visibleLayers = new Set(meta.layers.map(layer=>layer.name));
      state.hiddenGrades = new Set(); state.firstLoad = false;
      $("empty-state").hidden = true;
      htmlText($("document-title"), meta.name);
      htmlText($("map-status"), meta.name);
      htmlText($("layer-count"), meta.layers.length);
      htmlText($("count-objects"), display(meta.objectCount));
      htmlText($("count-vertices"), display(meta.vertexCount));
      const quality = $("checksum-badge");
      quality.hidden = false;
      quality.textContent = meta.checksumValid ? "✓ CHK poprawna" : "⚠ CHK niezgodna";
      quality.classList.toggle("warning", !meta.checksumValid);
      renderLayers(); updateInspector(); fitToMap(); updateSelectionCount();
      inform("Wczytano " + display(meta.objectCount) +
             " obiektów. Podgląd jest tylko do odczytu.");
    } catch (error) {
      inform("Nie udało się otworzyć MAP: " + error.message, true);
    } finally { busy(false); $("file-map").value = ""; }
  }
  async function openStyles(file) {
    if (!file) return;
    busy(true,"Wczytywanie dodatkowych stylów");
    try {
      const result = await api("/api/styles", {
        method:"POST", headers:{"Content-Type":"application/json"}, body:file
      });
      inform("Wczytano " + result.styleCount + " ustawień stylu (tylko podgląd).");
      await refreshViewport();
    } catch (error) {
      inform("Nie udało się wczytać JSON: " + error.message, true);
    } finally { busy(false); $("file-sidecar").value = ""; }
  }

  function resizeCanvas() {
    const rect = shell.getBoundingClientRect();
    state.width = Math.max(1, rect.width); state.height = Math.max(1, rect.height);
    state.pixelRatio = Math.min(2, window.devicePixelRatio || 1);
    const w = Math.round(state.width * state.pixelRatio);
    const h = Math.round(state.height * state.pixelRatio);
    if (canvas.width !== w || canvas.height !== h) { canvas.width=w; canvas.height=h; }
    requestDraw();
  }
  function worldToScreen(x,y) {
    return {x:(x-state.center.x)*state.scale + state.width/2,
            y:(y-state.center.y)*state.scale + state.height/2};
  }
  function screenToWorld(x,y) {
    return {x:(x-state.width/2)/state.scale + state.center.x,
            y:(y-state.height/2)/state.scale + state.center.y};
  }
  function boundsFromViewport(pad=0.22) {
    const dx=state.width/(2*state.scale), dy=state.height/(2*state.scale);
    return [state.center.x-dx*(1+pad),state.center.y-dy*(1+pad),
            state.center.x+dx*(1+pad),state.center.y+dy*(1+pad)];
  }
  function fitToMap() {
    if (!state.meta || !state.meta.bounds) return;
    const b=state.meta.bounds;
    const w=Math.max(.01,b[2]-b[0]), h=Math.max(.01,b[3]-b[1]);
    state.center={x:(b[0]+b[2])/2,y:(b[1]+b[3])/2};
    state.scale=Math.min((state.width-116)/w,(state.height-112)/h);
    if (!Number.isFinite(state.scale) || state.scale<=0) state.scale=1;
    state.scale=Math.max(.000001,Math.min(3500,state.scale));
    requestDraw(); scheduleViewport(true);
  }
  function zoomAt(factor, px, py) {
    if (!state.meta) return;
    const origin=screenToWorld(px,py);
    state.scale=Math.max(.000001,Math.min(3500,state.scale*factor));
    state.center={
      x:origin.x-(px-state.width/2)/state.scale,
      y:origin.y-(py-state.height/2)/state.scale
    };
    requestDraw(); scheduleViewport();
  }
  function setTool(tool) {
    state.tool=tool;
    shell.classList.toggle("panning",tool==="pan");
    for (const [name, id] of [["select","tool-select"],["pan","tool-pan"],
                              ["select","float-select"],["pan","float-pan"]])
      $(id).classList.toggle("active",name===tool);
    inform(tool==="select" ? "Tryb zaznaczania obiektów (S)." : "Tryb przesuwania mapy (H).");
  }
  function toggleLabels() {
    state.labels=!state.labels;
    $("tool-labels").classList.toggle("active",state.labels);
    requestDraw();
  }
  function toggleGrid() {
    state.grid=!state.grid;
    $("tool-grid").classList.toggle("active",state.grid);
    requestDraw();
  }
  function toggleTheme() { document.body.classList.toggle("dark-map"); requestDraw(); }

  function drawGrid() {
    if (!state.grid) return;
    const stepPixels=85, raw=stepPixels/state.scale;
    const power=Math.pow(10,Math.floor(Math.log10(Math.max(raw,1e-8))));
    const multiplier=[1,2,5,10].find(value=>value*power>=raw) || 10;
    const step=power*multiplier, view=boundsFromViewport(0);
    const xStart=Math.ceil(view[0]/step)*step,yStart=Math.ceil(view[1]/step)*step;
    const countX=Math.min(140,Math.ceil((view[2]-view[0])/step)+1);
    const countY=Math.min(140,Math.ceil((view[3]-view[1])/step)+1);
    ctx.lineWidth=1; ctx.strokeStyle=getComputedStyle(document.documentElement)
      .getPropertyValue("--map-grid").trim() || "rgba(75,98,120,.09)";
    ctx.beginPath();
    for(let i=0;i<countX;i++){
      const x=worldToScreen(xStart+i*step,0).x+.5;
      ctx.moveTo(x,0);ctx.lineTo(x,state.height);
    }
    for(let i=0;i<countY;i++){
      const y=worldToScreen(0,yStart+i*step).y+.5;
      ctx.moveTo(0,y);ctx.lineTo(state.width,y);
    }
    ctx.stroke();
  }
  function isVisible(feature) {
    return state.visibleLayers.has(feature.layer) &&
           !(feature.grade && state.hiddenGrades.has(feature.grade));
  }
  function isInView(box, view) {
    return box[0]<=view[2]&&box[2]>=view[0]&&box[1]<=view[3]&&box[3]>=view[1];
  }
  function addPath(parts) {
    ctx.beginPath();
    for(const part of parts) {
      if (!part.length) continue;
      let p=worldToScreen(part[0][0],part[0][1]);
      ctx.moveTo(p.x,p.y);
      if(part.length===1){ ctx.arc(p.x,p.y,2.8,0,Math.PI*2); continue; }
      for(let i=1;i<part.length;i++){
        p=worldToScreen(part[i][0],part[i][1]);ctx.lineTo(p.x,p.y);
      }
      if (part.length>=4 &&
          part[0][0]===part[part.length-1][0] &&
          part[0][1]===part[part.length-1][1]) ctx.closePath();
    }
  }
  function renderFeature(feature) {
    const style=feature.style;
    addPath(feature.geometry);
    if(feature.closed && feature.code!=="7900" && feature.code!=="6000"){
      ctx.globalAlpha=Math.max(0,Math.min(.9,style.opacity));
      ctx.fillStyle=style.fill;
      ctx.fill("evenodd");ctx.globalAlpha=1;
    }
    ctx.strokeStyle=style.stroke;
    ctx.lineWidth=Math.max(.65,Math.min(6,style.strokeWidth));
    ctx.lineCap="round";ctx.lineJoin="round";ctx.stroke();
    if(feature.geometry.length===1 && feature.geometry[0].length===1){
      const p=worldToScreen(...feature.geometry[0][0]);
      ctx.fillStyle=style.stroke;ctx.beginPath();ctx.arc(p.x,p.y,3.1,0,Math.PI*2);ctx.fill();
    }
  }
  function renderHighlights(features) {
    const selected=new Set(state.pinned);
    if(state.active!==null) selected.add(state.active);
    if(!selected.size) return;
    for(const feature of features) {
      if(!selected.has(feature.id)) continue;
      addPath(feature.geometry);
      ctx.strokeStyle=state.active===feature.id?"#f28b4b":"#04ac9b";
      ctx.lineWidth=state.active===feature.id?3.5:2.4;
      ctx.shadowBlur=7;ctx.shadowColor="#ffffff";
      ctx.stroke();ctx.shadowBlur=0;
    }
  }
  function renderLabels(features) {
    if(!state.labels) return;
    let painted=0;
    const collisions=[];
    for(const feature of features){
      if(!feature.labels?.length) continue;
      const box=feature.bbox;
      const w=(box[2]-box[0])*state.scale,h=(box[3]-box[1])*state.scale;
      if(feature.code!=="7900"&&Math.max(w,h)<11) continue;
      for(const label of feature.labels){
        if(painted>=750) return;
        const p=worldToScreen(label.x,label.y);
        const row=String(label.text).split("\n")[0].slice(0,80);
        if(!row.trim())continue;
        const size=Math.max(10,Math.min(22,label.size||12));
        ctx.font="600 "+size+"px Segoe UI, sans-serif";
        const width=ctx.measureText(row).width;
        const px=p.x-width/2, py=p.y+(label.offset||0);
        const rect=[px-3,py-size-2,px+width+3,py+5];
        if(rect[2]<0||rect[0]>state.width||rect[3]<0||rect[1]>state.height)continue;
        if(collisions.some(r=>r[0]<rect[2]&&r[2]>rect[0]&&r[1]<rect[3]&&r[3]>rect[1]))continue;
        collisions.push(rect);
        ctx.textBaseline="alphabetic";
        ctx.strokeStyle=document.body.classList.contains("dark-map")?"#1b2c3d":"#f6f9fa";
        ctx.lineWidth=3.4;ctx.strokeText(row,px,py);
        ctx.fillStyle=label.color||"#274259";ctx.fillText(row,px,py);
        painted++;
      }
    }
  }
  function draw() {
    state.scheduled=false;
    const isDark=document.body.classList.contains("dark-map");
    ctx.setTransform(state.pixelRatio,0,0,state.pixelRatio,0,0);
    ctx.clearRect(0,0,state.width,state.height);
    ctx.fillStyle=isDark?"#17283b":"#edf3f6";
    ctx.fillRect(0,0,state.width,state.height);
    drawGrid();
    if(!state.meta) return;
    const box=boundsFromViewport(.05);
    const features=state.features.filter(f=>isVisible(f)&&isInView(f.bbox,box));
    // Parcel beneath land uses; buildings and survey markers above.
    const priorities={"5216":0,"5220":1,"5230":2,"5310":3,"1246":4};
    features.sort((a,b)=>(priorities[a.code]??3)-(priorities[b.code]??3));
    for(const feature of features) renderFeature(feature);
    renderHighlights(features);renderLabels(features);
    $("scale-label").textContent="Podgląd: "+state.scale.toFixed(state.scale<1?3:1)+" px / jedn.";
    $("count-visible").textContent=display(features.length);
    $("render-hint").textContent=state.limited
      ?"Zbyt wiele obiektów · przybliż mapę":"HTML Canvas · "+display(features.length)+" obiektów";
  }
  function requestDraw() {
    if(!state.scheduled){state.scheduled=true;requestAnimationFrame(draw);}
  }
  async function refreshViewport() {
    if(!state.meta) return;
    const ticket=++state.queryCounter;
    if(state.queryAbort) state.queryAbort.abort();
    const controller=new AbortController();state.queryAbort=controller;
    let view=boundsFromViewport();
    // Bound requests to the actual map extent. This prevents huge spatial
    // index scans when a user zooms far out or pans away from their map.
    const map=state.meta.bounds;
    if(view[2]<map[0]||view[0]>map[2]||view[3]<map[1]||view[1]>map[3]){
      state.features=[];state.limited=false;requestDraw();return;
    }
    view=[Math.max(view[0],map[0]),Math.max(view[1],map[1]),
          Math.min(view[2],map[2]),Math.min(view[3],map[3])];
    const params=new URLSearchParams({
      xmin:view[0],ymin:view[1],xmax:view[2],ymax:view[3],limit:25000
    });
    try {
      const res=await api("/api/viewport?"+params.toString(),{signal:controller.signal});
      if(ticket!==state.queryCounter)return;
      state.features=res.features;
      state.limited=res.limited;
      requestDraw();
    }catch(err){
      if(err.name!=="AbortError")inform("Nie udało się narysować mapy: "+err.message,true);
    }
  }
  function scheduleViewport(now=false) {
    clearTimeout(state.refreshTimer);
    if(now)refreshViewport();
    else state.refreshTimer=setTimeout(refreshViewport,150);
  }
  function buildLayer(name,count) {
    const item=document.createElement("div");item.className="layer-item";
    const row=document.createElement("label");row.className="layer-row";
    const toggle=document.createElement("input");toggle.type="checkbox";toggle.className="layer-toggle";
    toggle.checked=state.visibleLayers.has(name);
    toggle.addEventListener("change",()=>{
      if(toggle.checked)state.visibleLayers.add(name);else state.visibleLayers.delete(name);
      requestDraw();refreshInspectorVisibility();
    });
    const color=document.createElement("span");color.className="layer-swatch";
    const hue=colorForLayer(name);color.style.backgroundColor=hue;color.style.borderColor=hue;
    const text=document.createElement("span");text.className="layer-name";text.textContent=name;
    const qty=document.createElement("span");qty.className="layer-count";qty.textContent=display(count);
    row.append(toggle,color,text,qty);item.append(row);
    if(name==="Użytki Leśne"&&state.meta&&Object.keys(state.meta.forestClasses).length){
      const grades=document.createElement("div");grades.className="layer-grades";
      for(const [grade,amount] of Object.entries(state.meta.forestClasses)){
        const line=document.createElement("label");line.className="grade-row";
        const input=document.createElement("input");input.type="checkbox";input.className="grade-toggle";
        input.checked=!state.hiddenGrades.has(grade);
        input.addEventListener("change",()=>{
          if(input.checked)state.hiddenGrades.delete(grade);else state.hiddenGrades.add(grade);
          requestDraw();refreshInspectorVisibility();
        });
        const nameNode=document.createElement("b");nameNode.textContent=grade;
        const badge=document.createElement("em");badge.textContent=amount;
        line.append(input,nameNode,badge);grades.append(line);
      }
      item.append(grades);
    }
    return item;
  }
  function renderLayers() {
    const list=$("layers-list");list.replaceChildren();
    if(!state.meta)return;
    const needle=$("layer-search").value.toLocaleLowerCase("pl-PL").trim();
    let found=0;
    for(const layer of state.meta.layers){
      if(needle&&!layer.name.toLocaleLowerCase("pl-PL").includes(needle))continue;
      list.append(buildLayer(layer.name,layer.count));found++;
    }
    if(!found){
      const message=document.createElement("div");message.className="panel-placeholder";
      message.textContent="Brak warstw pasujących do wyszukiwania.";
      list.append(message);
    }
  }
  function showAllLayers() {
    if(!state.meta)return;
    state.visibleLayers=new Set(state.meta.layers.map(layer=>layer.name));
    state.hiddenGrades.clear();renderLayers();requestDraw();inform("Wszystkie warstwy są widoczne.");
  }
  function refreshInspectorVisibility() {
    if(state.detail&&(!state.visibleLayers.has(state.detail.layer)||
       state.detail.grade&&state.hiddenGrades.has(state.detail.grade))){
      state.active=null;state.detail=null;updateInspector();
    }
    updateSelectionCount();
  }
  function addField(target,key,value) {
    const row=document.createElement("div");row.className="inspector-field";
    const label=document.createElement("span");label.className="key";label.textContent=key;
    const val=document.createElement("span");val.className="value";val.textContent=String(value);
    row.append(label,val);target.append(row);
  }
  function updateInspector() {
    const detail=state.detail;
    $("inspector-empty").hidden=!!detail;
    $("inspector-data").hidden=!detail;
    document.body.classList.toggle("has-inspector",!!detail);
    if(!detail)return;
    $("inspector-code").textContent=detail.code;
    $("inspector-layer").textContent=detail.layer;
    $("inspector-uid").textContent=detail.sourceUid||detail.id;
    const fields=$("inspector-fields");fields.replaceChildren();
    const list=Object.entries(detail.fields).filter(([key])=>key!=="ID");
    if(!list.length)addField(fields,"Info","Brak atrybutów");
    for(const [key,value] of list)addField(fields,key,value||"—");
    const geom=$("inspector-geometry");geom.replaceChildren();
    addField(geom,"Typ",detail.closed?"Poligon":"Linia / punkt");
    addField(geom,"Punkty",detail.pointCount);
    if(detail.areaM2!==null)addField(geom,"Powierzchnia",display(Math.round(detail.areaM2*100)/100)+" m²");
    if(detail.grade)addField(geom,"Klasoużytek",detail.grade);
    if(detail.geometryTruncated)addField(geom,"Uwaga","Wyświetlono tylko pierwsze 500 punktów.");
    if(detail.points.length)addField(geom,"X / Y",
      detail.points[0].x.toFixed(3)+" / "+detail.points[0].y.toFixed(3));
  }
  function updateSelectionCount(){
    const n=state.pinned.size+(state.active&&!state.pinned.has(state.active)?1:0);
    $("selection-count").textContent="Zaznaczonych: "+n;
  }
  async function selectFeature(fid) {
    state.active=fid;state.detail=null;updateInspector();
    updateSelectionCount();requestDraw();
    if(fid===null)return;
    const ticket=++state.selectionRequest;
    try{
      const detail=state.inspectorCache.get(fid)||await api("/api/object/"+encodeURIComponent(fid));
      if(ticket!==state.selectionRequest||state.active!==fid)return;
      state.inspectorCache.set(fid,detail);state.detail=detail;
      updateInspector();
      $("map-status").textContent=detail.code+" · "+detail.layer;
    }catch(error){inform("Nie można odczytać obiektu: "+error.message,true);}
  }
  function pinActive(){
    if(!state.active){inform("Najpierw wybierz obiekt na mapie.");return;}
    if(state.pinned.has(state.active))state.pinned.delete(state.active);
    else state.pinned.add(state.active);
    inform("Utrwalone zaznaczenie: "+state.pinned.size+" (B dodaje/usuwa).");
    updateSelectionCount();requestDraw();
  }

  function containsPoint(part,x,y){
    let inside=false;for(let i=0,j=part.length-1;i<part.length;j=i++){
      const a=part[i],b=part[j];
      if((a[1]>y)!==(b[1]>y)&&
         x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])inside=!inside;
    }return inside;
  }
  function edgeDist(part,x,y){
    if(part.length===1)return Math.hypot(x-part[0][0],y-part[0][1]);
    let best=Infinity;
    for(let i=1;i<part.length;i++){
      const a=part[i-1],b=part[i],dx=b[0]-a[0],dy=b[1]-a[1];
      const sq=dx*dx+dy*dy;
      const t=sq?Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/sq)):0;
      best=Math.min(best,Math.hypot(x-a[0]-t*dx,y-a[1]-t*dy));
    }return best;
  }
  function pick(world) {
    const radius=9/state.scale;
    const candidates=[];
    for(const f of state.features){
      if(!isVisible(f))continue;
      const b=f.bbox;
      if(world.x<b[0]-radius||world.x>b[2]+radius||
         world.y<b[1]-radius||world.y>b[3]+radius)continue;
      const dist=Math.min(...f.geometry.map(p=>edgeDist(p,world.x,world.y)));
      const inside=f.closed&&f.geometry.some(p=>p.length>=4&&containsPoint(p,world.x,world.y));
      if(inside||dist<=radius){
        candidates.push({fid:f.id,code:f.code,dist,inside,
                         area:(b[2]-b[0])*(b[3]-b[1])});
      }
    }
    candidates.sort((a,b)=>{
      const priority=p=>p.code==="5216"?0:p.code==="5230"?1:2;
      return priority(a)-priority(b)||(a.inside?1:0)-(b.inside?1:0)||
             a.dist-b.dist||a.area-b.area;
    });
    return candidates.map(c=>c.fid);
  }
  function eventCoords(ev){
    const box=canvas.getBoundingClientRect();
    return {x:ev.clientX-box.left,y:ev.clientY-box.top};
  }
  canvas.addEventListener("pointerdown", ev=>{
    if(ev.button!==0&&ev.button!==1)return;
    canvas.setPointerCapture(ev.pointerId);
    const p=eventCoords(ev);
    state.drag={pointer:ev.pointerId,start:p,last:p,moved:false,
                pan:ev.button===1||state.tool==="pan"};
  });
  canvas.addEventListener("pointermove", ev=>{
    const p=eventCoords(ev),world=screenToWorld(p.x,p.y);
    $("cursor-coords").textContent="X: "+(-world.y).toFixed(3)+
                                   "   Y: "+world.x.toFixed(3);
    if(!state.drag||state.drag.pointer!==ev.pointerId)return;
    const d=state.drag;
    if(Math.hypot(p.x-d.start.x,p.y-d.start.y)>4)d.moved=true;
    if(d.moved){
      if(d.pan||state.tool==="select"){
        state.center.x-=(p.x-d.last.x)/state.scale;
        state.center.y-=(p.y-d.last.y)/state.scale;
        shell.classList.add("dragging");requestDraw();
      }
    }
    d.last=p;
  });
  canvas.addEventListener("pointerup", ev=>{
    const d=state.drag;state.drag=null;shell.classList.remove("dragging");
    if(!d||ev.pointerId!==d.pointer)return;
    if(d.moved){scheduleViewport();return;}
    if(d.pan)return;
    const p=eventCoords(ev),world=screenToWorld(p.x,p.y),hits=pick(world);
    if(!hits.length){selectFeature(null);state.lastPick=null;return;}
    let index=0;
    if(state.lastPick&&Math.hypot(state.lastPick.p.x-p.x,
       state.lastPick.p.y-p.y)<8&&hits.includes(state.lastPick.fid))
       index=(hits.indexOf(state.lastPick.fid)+1)%hits.length;
    const fid=hits[index];
    state.lastPick={p,fid};selectFeature(fid);
  });
  canvas.addEventListener("pointercancel",()=>{state.drag=null;shell.classList.remove("dragging");});
  canvas.addEventListener("wheel",ev=>{
    if(!state.meta)return;
    ev.preventDefault();
    const p=eventCoords(ev);
    zoomAt(Math.exp(-ev.deltaY*.00125),p.x,p.y);
  },{passive:false});
  canvas.addEventListener("contextmenu",ev=>ev.preventDefault());

  const dialog=$("command-dialog"),input=$("command-input");
  function openCommands(){
    renderCommands("");
    if(!dialog.open)dialog.showModal();input.value="";input.focus();
  }
  function renderCommands(query){
    const target=$("command-results");target.replaceChildren();
    for(const command of commands.filter(c=>c.name.toLocaleLowerCase("pl-PL")
                   .includes(query.toLocaleLowerCase("pl-PL")))){
      const row=document.createElement("button");row.className="command-row";
      const title=document.createElement("span");title.textContent=command.name;
      const hint=document.createElement("span");hint.textContent=command.hint;
      row.append(title,hint);row.addEventListener("click",()=>{
        dialog.close();command.run();
      });target.append(row);
    }
  }
  input.addEventListener("input",()=>renderCommands(input.value));
  input.addEventListener("keydown",ev=>{
    if(ev.key==="Enter"){
      const item=$("command-results").querySelector(".command-row");
      if(item){item.click();ev.preventDefault();}
    }
  });

  document.addEventListener("keydown",ev=>{
    const typing=ev.target.matches("input,textarea,[contenteditable]");
    if((ev.ctrlKey||ev.metaKey)&&ev.key.toLowerCase()==="k"){
      ev.preventDefault();openCommands();return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.key.toLowerCase()==="o"){
      ev.preventDefault();$("file-map").click();return;
    }
    if(typing)return;
    if(ev.key==="Escape"){
      if(dialog.open)dialog.close();
      else selectFeature(null);
      return;
    }
    if(ev.key.toLowerCase()==="s")setTool("select");
    if(ev.key.toLowerCase()==="h")setTool("pan");
    if(ev.key.toLowerCase()==="b")pinActive();
    if(ev.key==="0")fitToMap();
    if(ev.key==="/"){ev.preventDefault();$("layer-search").focus();}
  });

  const link=(id,callback)=>$(id).addEventListener("click",callback);
  link("btn-open",()=> $("file-map").click());
  link("tool-open",()=> $("file-map").click());
  link("empty-open",()=> $("file-map").click());
  link("tool-sidecar",()=> $("file-sidecar").click());
  link("tool-select",()=>setTool("select"));
  link("tool-pan",()=>setTool("pan"));
  link("tool-fit",fitToMap);
  link("float-select",()=>setTool("select"));
  link("float-pan",()=>setTool("pan"));
  link("float-plus",()=>zoomAt(1.35,state.width/2,state.height/2));
  link("float-minus",()=>zoomAt(1/1.35,state.width/2,state.height/2));
  link("float-fit",fitToMap);
  link("tool-grid",toggleGrid);
  link("tool-labels",toggleLabels);
  link("btn-theme",toggleTheme);
  link("btn-command",openCommands);
  link("layers-all",showAllLayers);
  $("layer-search").addEventListener("input",renderLayers);
  $("file-map").addEventListener("change",ev=>openMap(ev.target.files?.[0]));
  $("file-sidecar").addEventListener("change",ev=>openStyles(ev.target.files?.[0]));

  document.addEventListener("dragover",ev=>{
    if(ev.dataTransfer&&Array.from(ev.dataTransfer.types).includes("Files"))ev.preventDefault();
  });
  document.addEventListener("drop",ev=>{
    if(ev.dataTransfer?.files?.length){
      ev.preventDefault();
      const files=Array.from(ev.dataTransfer.files);
      const map=files.find(file=>file.name.toLowerCase().endsWith(".map"));
      const style=files.find(file=>file.name.toLowerCase().endsWith(".json"));
      if(map)openMap(map).then(()=>{if(style)openStyles(style);});
      else if(style)openStyles(style);
    }
  });

  new ResizeObserver(()=>{resizeCanvas();if(state.meta)scheduleViewport();}).observe(shell);
  resizeCanvas();
  api("/api/map").then(meta=>{
    if(meta.loaded){
      state.meta=meta;
      state.visibleLayers=new Set(meta.layers.map(layer=>layer.name));
      state.firstLoad=false;
      $("empty-state").hidden=true;
      $("document-title").textContent=meta.name;
      $("map-status").textContent=meta.name;
      $("layer-count").textContent=meta.layers.length;
      $("count-objects").textContent=display(meta.objectCount);
      $("count-vertices").textContent=display(meta.vertexCount);
      renderLayers();fitToMap();
    }
  }).catch(err=>inform("Błąd lokalnej usługi: "+err.message,true));
})();
