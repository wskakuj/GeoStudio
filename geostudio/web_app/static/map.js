/* GeoStudio 2.0 — experimental HTML5 map canvas and in-memory GEO-MAP editing.
   World coordinates: horizontal = GEO-MAP easting Y, vertical = -northing X.
   This matches the classic geodetic PySide6 orientation.
   Original MAP files are never overwritten: changes are exported as copies.
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
    labels: true, grid: false, active: null, detail: null, pinned: new Set(),
    width: 1, height: 1, pixelRatio: 1, isDragging: false, drag: null,
    lastPick: null, scheduled: false, refreshTimer: null, queryCounter: 0,
    queryAbort: null, selectionRequest: 0, limited: false,
    firstLoad: true, inspectorCache: new Map(),
    edit: null, editBusy: false,
    snapEnabled: true, sharedNodes: false, vertexDrag: null,
    hoverInsert: null, selectedVertex: null
  };
  const commands = [
    {name:"Otwórz plik GEO-MAP", hint:"Ctrl+O", run:chooseMap},
    {name:"Wybierz obiekty według kodu, A1, A2", hint:"Ctrl+H", run:openAdvancedSelection},
    {name:"Wczytaj plik stylów GeoStudio", hint:"JSON", run:()=> $("file-sidecar").click()},
    {name:"Dopasuj całą mapę", hint:"0", run:fitToMap},
    {name:"Edytuj atrybuty aktywnego obiektu", hint:"E", run:()=>toggleInspectorEdit(true)},
    {name:"Cofnij ostatnią zmianę", hint:"Ctrl+Z", run:()=>historyStep("undo")},
    {name:"Ponów zmianę", hint:"Ctrl+Y", run:()=>historyStep("redo")},
    {name:"Pobierz osobną kopię MAP", hint:"Ctrl+Shift+S", run:downloadMapCopy},
    {name:"Zaznaczanie obiektów", hint:"S", run:()=>setTool("select")},
    {name:"Edytuj węzły zaznaczonego poligonu", hint:"P", run:()=>setTool("nodes")},
    {name:"Usuń zaznaczony węzeł poligonu", hint:"Delete", run:deleteSelectedVertex},
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
  function updateEditState(status) {
    if(!status)return;
    state.edit={
      dirty:!!status.dirty,
      canUndo:!!status.canUndo,
      canRedo:!!status.canRedo,
      revision:status.revision,
      documentToken:status.documentToken,
      undoLabel:status.undoLabel||"",
      redoLabel:status.redoLabel||""
    };
    $("tool-undo").disabled=state.editBusy||!state.edit.canUndo;
    $("tool-redo").disabled=state.editBusy||!state.edit.canRedo;
    $("btn-export").disabled=state.editBusy||!state.meta;
    $("tool-undo").title=state.edit.undoLabel
      ?"Cofnij: "+state.edit.undoLabel+" (Ctrl+Z)":"Cofnij (Ctrl+Z)";
    $("tool-redo").title=state.edit.redoLabel
      ?"Ponów: "+state.edit.redoLabel+" (Ctrl+Y)":"Ponów (Ctrl+Y)";
    const marker=$("dirty-marker");
    marker.textContent=state.edit.dirty?"Niezapisane zmiany w pamięci":"Oryginał chroniony";
    marker.classList.toggle("unsaved",state.edit.dirty);
  }
  function editRequestBody() {
    return {documentToken:state.edit?.documentToken,
            revision:state.edit?.revision};
  }
  function confirmDiscardEdits() {
    return !state.edit?.dirty || window.confirm(
      "W kopii roboczej są niezapisane zmiany. Otworzenie kolejnej mapy "+
      "usunie je z pamięci. Czy chcesz kontynuować?");
  }
  function toggleInspectorEdit(on) {
    if(!state.detail||!state.meta)return;
    const supported=state.detail.editableFields||[];
    if(on&&!supported.length) {
      inform("Ten obiekt nie ma istniejących pól, które można bezpiecznie edytować.",true);
      return;
    }
    $("inspector-edit").hidden=!on;
    $("inspector-fields").hidden=!!on;
    $("inspector-edit-toggle").textContent=on?"Zamknij":"✎ Edytuj";
    if(!on)return;
    const list=$("inspector-edit-fields");
    list.replaceChildren();
    for(const key of supported) {
      const row=document.createElement("div");
      row.className="inspector-edit-field";
      const label=document.createElement("label");
      label.textContent=key;
      const input=document.createElement("input");
      input.type="text"; input.dataset.field=key; input.id="edit-field-"+key;
      input.value=state.detail.fields[key]??"";
      input.maxLength=512;
      label.htmlFor=input.id;
      row.append(label,input);list.append(row);
    }
    const first=list.querySelector("input");
    if(first)first.focus();
  }
  async function refreshEditedDocument(activeId) {
    const oldLayers=new Set(state.meta.layers.map(item=>item.name));
    const refreshed=await api("/api/map");
    state.meta=refreshed;
    updateEditState(refreshed);
    for(const layer of refreshed.layers) {
      if(!oldLayers.has(layer.name))state.visibleLayers.add(layer.name);
    }
    $("layer-count").textContent=refreshed.layers.length;
    $("count-objects").textContent=display(refreshed.objectCount);
    $("count-vertices").textContent=display(refreshed.vertexCount);
    state.inspectorCache.clear();
    renderLayers();
    await refreshViewport();
    if(activeId)await selectFeature(activeId);
    else {state.detail=null;updateInspector();}
  }
  async function saveAttributeChanges(event) {
    event.preventDefault();
    if(state.editBusy||!state.edit||!state.detail)return;
    const fid=state.detail.id;
    const changes={};
    for(const input of $("inspector-edit-fields").querySelectorAll("input[data-field]")){
      const field=input.dataset.field;
      if(input.value!==(state.detail.fields[field]??""))changes[field]=input.value;
    }
    if(!Object.keys(changes).length) {
      toggleInspectorEdit(false);
      inform("Nie wprowadzono zmian.");
      return;
    }
    state.editBusy=true;updateEditState(state.edit);
    $("inspector-apply").disabled=true;
    try {
      const response=await api("/api/object/"+encodeURIComponent(fid)+"/fields",{
        method:"PATCH",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...editRequestBody(),changes})
      });
      updateEditState(response);
      await refreshEditedDocument(fid);
      inform("Zmieniono atrybuty kopii roboczej. Ctrl+Z cofa; pobierz nową kopię MAP.");
    } catch(error){
      inform("Nie można zmienić atrybutów: "+error.message,true);
    } finally {
      state.editBusy=false;$("inspector-apply").disabled=false;
      updateEditState(state.edit);
    }
  }
  async function historyStep(direction) {
    if(state.editBusy||!state.edit)return;
    if(direction==="undo"&&!state.edit.canUndo)return;
    if(direction==="redo"&&!state.edit.canRedo)return;
    state.editBusy=true;updateEditState(state.edit);
    try {
      const response=await api("/api/edit/"+direction,{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(editRequestBody())
      });
      updateEditState(response);
      if(response.changed) {
        await refreshEditedDocument(state.active);
        inform(direction==="undo"?"Cofnięto zmianę w kopii.":"Ponowiono zmianę w kopii.");
      }
    }catch(error){
      inform("Nie można wykonać operacji historii: "+error.message,true);
    }finally{state.editBusy=false;updateEditState(state.edit);}
  }
  async function downloadMapCopy() {
    if(!state.meta||!state.edit||state.editBusy)return;
    try {
      const params=new URLSearchParams({documentToken:state.edit.documentToken});
      const response=await fetch("/api/export/map?"+params.toString(),{
        headers:{"X-GeoStudio-Token":token},cache:"no-store"
      });
      if(!response.ok){
        const problem=await response.json().catch(()=>({}));
        throw Error(problem.detail||"Błąd tworzenia pliku MAP.");
      }
      const blob=await response.blob();
      const original=state.meta.name.replace(/\\/g,"/").split("/").pop();
      const filename=original.replace(/\.map$/i,"")+"_GeoStudio2_kopia.MAP";
      const url=URL.createObjectURL(blob);
      const anchor=document.createElement("a");
      anchor.href=url;anchor.download=filename;
      document.body.append(anchor);anchor.click();anchor.remove();
      setTimeout(()=>URL.revokeObjectURL(url),6000);
      inform("Przygotowano nowy plik MAP do pobrania. Oryginał pozostaje bez zmian.");
    }catch(error){inform("Nie udało się przygotować kopii: "+error.message,true);}
  }
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

  function finishOpeningMap(meta) {
    state.meta = meta;
    updateEditState(meta);
    state.active = null; state.detail = null; state.pinned.clear();
    populateSelectCodes();
    state.vertexDrag=null;setTool("select");
    state.features = []; state.inspectorCache.clear();
    // Match the old user's map view: survey markers are opt-in.
    // Their heavy symbol density otherwise hides the parcel boundaries.
    state.visibleLayers = new Set(
      meta.layers.map(layer=>layer.name).filter(name=>name!=="Graniczniki"));
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
           " obiektów. Oryginalny plik jest chroniony.");
    return true;
  }
  async function openMap(file, alreadyConfirmed=false) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".map")) {
      inform("Wybierz plik z rozszerzeniem .MAP.", true);
      return;
    }
    if(!alreadyConfirmed&&!confirmDiscardEdits()){$("file-map").value="";return false;}
    busy(true,"Wczytywanie " + file.name);
    try {
      const meta = await api("/api/map", {
        method: "POST",
        headers: {"Content-Type":"application/octet-stream",
                  "X-Map-Name":encodeURIComponent(file.name)},
        body: file
      });
      return finishOpeningMap(meta);
    } catch (error) {
      inform("Nie udało się otworzyć MAP: " + error.message, true);
      return false;
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

  async function chooseMap() {
    // Do NOT hold the entire UI busy while a native dialog is open.
    // The user can always use the independent "Z dysku" label/input,
    // even if Tk or the pywebview JS bridge is unavailable or blocked.
    if(window.pywebview){
      if(window.pywebview.api?.open_map){
        if(!confirmDiscardEdits())return;
        try {
          const answer=await window.pywebview.api.open_map();
          if(answer&&!answer.cancelled&&answer.metadata)
            finishOpeningMap(answer.metadata);
        }catch(error){
          const message=error?.message||String(error);
          inform("Nie udało się otworzyć okna z ostatniego folderu: "+
            message+". Kliknij Z dysku, aby wybrać mapę standardowo.",true);
        }
        return;
      }
      // Bridge might not be ready when a WebView2 window first appears.
      // Fall back synchronously on the ORIGINAL click, preserving the
      // user gesture needed to display the Windows file chooser.
      $("file-map").click();
      return;
    }
    if(typeof window.showOpenFilePicker==="function"){
      if(!confirmDiscardEdits())return;
      try{
        const handles=await window.showOpenFilePicker({
          id:"geostudio-map-folder",multiple:false,
          types:[{description:"Mapa GEO-MAP",accept:{
            "application/octet-stream":[".map"]
          }}]
        });
        if(handles.length)await openMap(await handles[0].getFile(),true);
      }catch(error){
        if(error.name==="AbortError")return;
        // After an awaited browser call, triggering input.click() might
        // be blocked due to loss of transient user activation. Explain
        // that "Z dysku" is an immediate click-based alternative.
        inform("Przeglądarka nie otworzyła wyboru pliku. "+
          "Kliknij Z dysku, aby użyć standardowego okna.",true);
      }
      return;
    }
    $("file-map").click();
  }

  function populateSelectCodes() {
    const box=$("select-code");
    if(!box)return;
    const old=box.value;
    box.replaceChildren(new Option("Wszystkie kody (z filtrem A1/A2)",""));
    for(const [code,count] of Object.entries(state.meta?.codes||{})
       .sort((a,b)=>Number(a[0])-Number(b[0]))){
      box.add(new Option(code+" · "+display(count)+" obiektów",code));
    }
    if([...box.options].some(x=>x.value===old))box.value=old;
  }
  function openAdvancedSelection() {
    if(!state.meta){inform("Najpierw wczytaj mapę MAP.",true);return;}
    const dialog=$("select-dialog");
    if(dialog.open)return;
    populateSelectCodes();
    // Default to the selected object's code, never auto-filter A1/A2.
    if(state.detail?.code&&[...$("select-code").options]
       .some(o=>o.value===state.detail.code))
      $("select-code").value=state.detail.code;
    $("select-preview").textContent=
      "Przeszukuje całą mapę, nie tylko bieżący widok.";
    dialog.showModal();
    $("select-code").focus();
  }
  async function applyAdvancedSelection(event) {
    event.preventDefault();
    if(!state.meta)return;
    const code=$("select-code").value;
    const a1=$("select-a1").value.trim();
    const a2=$("select-a2").value.trim();
    const match=$("select-match").value;
    const action=$("select-action").value;
    if(!code&&!a1&&!a2){
      $("select-preview").textContent=
        "Podaj kod albo wartość A1/A2, aby uniknąć zaznaczenia całej mapy.";
      return;
    }
    const button=$("select-apply");button.disabled=true;
    const tokenAtStart=state.edit?.documentToken;
    const revisionAtStart=state.edit?.revision;
    $("select-preview").textContent="Sprawdzanie obiektów…";
    try {
      const params=new URLSearchParams({code,a1,a2,match});
      const result=await api("/api/select?"+params);
      if(result.documentToken!==tokenAtStart||
         result.revision!==revisionAtStart||
         state.edit?.documentToken!==tokenAtStart||
         state.edit?.revision!==revisionAtStart)
        throw Error("Mapa zmieniła się w trakcie wyszukiwania. Spróbuj ponownie.");
      const previous=new Set(state.pinned);
      if(state.active)previous.add(state.active);
      const matches=new Set(result.ids);
      if(action==="replace")state.pinned=matches;
      else if(action==="add")for(const id of matches)previous.add(id);
      else if(action==="subtract")for(const id of matches)previous.delete(id);
      if(action!=="replace")state.pinned=previous;
      const selected=state.pinned.has(state.active)?state.active:
        (state.pinned.values().next().value||null);
      state.lastPick=null;
      $("select-dialog").close();
      await selectFeature(selected);
      inform("Wyszukano "+display(result.count)+" obiektów. Aktualne zaznaczenie: "+
        display(state.pinned.size)+".");
      requestDraw();
    }catch(error){
      $("select-preview").textContent="Nie udało się zaznaczyć: "+error.message;
      inform("Zaznaczanie: "+error.message,true);
    }finally{button.disabled=false;}
  }
  function clearAdvancedSelection() {
    state.pinned.clear();
    state.lastPick=null;
    selectFeature(null);
    $("select-preview").textContent="Wyczyszczono wszystkie zaznaczenia.";
    requestDraw();
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
  function updateGeometryHelp() {
    if(state.tool!=="nodes")return;
    const code=state.detail?.code||"brak aktywnego obiektu";
    const link=state.sharedNodes
      ?"Wspólne węzły i przyciąganie: tylko kod "+code
      :"Wspólne węzły: wyłączone";
    $("geometry-help").textContent="P · Aktywny kod: "+code+
      ". Kliknij węzeł + Delete, aby usunąć; przeciągnij, żeby przesunąć; "+
      "dwuklik na krawędzi dodaje węzeł. "+link+". Inne kody bez zmian.";
  }
  function updateDeleteNodeButton() {
    const enabled=state.tool==="nodes"&&state.meta&&state.detail?.closed&&
      state.selectedVertex!==null&&!state.editBusy;
    $("tool-delete-node").disabled=!enabled;
    $("tool-delete-node").title=enabled
      ?"Usuń węzeł nr "+(state.selectedVertex+1)+" (Delete)"
      :"Kliknij węzeł w trybie P, następnie naciśnij Delete";
  }
  function setTool(tool) {
    if(state.editBusy)return;
    state.tool=tool;
    state.hoverInsert=null;
    if(tool!=="nodes")state.selectedVertex=null;
    updateDeleteNodeButton();
    shell.classList.toggle("panning",tool==="pan");
    shell.classList.toggle("nodes-editing",tool==="nodes");
    $("geometry-help").hidden=tool!=="nodes"||!state.meta;
    updateGeometryHelp();
    for(const [name,id] of [
      ["select","tool-select"],["pan","tool-pan"],["nodes","tool-nodes"],
      ["select","float-select"],["pan","float-pan"],["nodes","float-nodes"]
    ])$(id).classList.toggle("active",name===tool);
    if(tool==="nodes"&&(!state.detail||!state.detail.closed))
      inform("Tryb P: wybierz zamknięty poligon i przeciągnij jego węzeł.");
    else if(tool==="nodes")
      inform("Tryb P: przeciągnij jeden z węzłów. Ctrl+Z cofa zmianę.");
    else inform(tool==="select"
      ?"Tryb zaznaczania obiektów (S).":"Tryb przesuwania mapy (H).");
    requestDraw();
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
  function renderFill(feature) {
    const style=feature.style;
    if(!feature.closed||!style.hasFill||style.opacity<=0)return;
    addPath(feature.geometry);
    ctx.fillStyle=style.fill;
    ctx.globalAlpha=Math.min(1,Math.max(0,style.opacity));
    ctx.fill("evenodd");
    ctx.globalAlpha=1;
  }
  function renderStroke(feature) {
    const style=feature.style;
    if(!style.drawStroke)return; // GEO-MAP text anchors aren't printed lines.
    if(feature.geometry.length===1 && feature.geometry[0].length===1) {
      const p=worldToScreen(...feature.geometry[0][0]);
      const radius=Math.max(.6,Math.min(2,style.pointSize||1));
      ctx.fillStyle=style.stroke;ctx.beginPath();
      ctx.arc(p.x,p.y,radius,0,Math.PI*2);ctx.fill();
      return;
    }
    addPath(feature.geometry);
    ctx.strokeStyle=style.stroke;
    ctx.lineWidth=Math.max(.5,Math.min(12,style.strokeWidth));
    ctx.lineCap="round";ctx.lineJoin="round";ctx.stroke();
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
  function nativeWorldPoint(point) {
    return {x:point.y,y:-point.x};
  }
  function editableVertices() {
    if(!state.detail||!state.detail.closed||state.detail.geometryTruncated)
      return [];
    const pts=state.detail.points||[];
    return pts.length>1?pts.slice(0,-1):[];
  }
  function closestEditableVertex(screen) {
    let index=-1,best=11*11;
    const pts=editableVertices();
    for(let i=0;i<pts.length;i++){
      const p=worldToScreen(...Object.values(nativeWorldPoint(pts[i])));
      const dist=(screen.x-p.x)**2+(screen.y-p.y)**2;
      if(dist<best){best=dist;index=i;}
    }
    return index;
  }
  function closestEditableSegment(screen, radius=9) {
    // Use native, full-precision P order from the selected object, NEVER
    // visually-overlapping features from another code. Closing edge included.
    if(!state.detail?.closed||state.detail.geometryTruncated)return null;
    const pts=state.detail.points||[];
    let best=null;
    for(let i=0;i<pts.length-1;i++){
      if(pts[i].type===0)continue; // no hidden P0 component connector
      const a=nativeWorldPoint(pts[i]),b=nativeWorldPoint(pts[i+1]);
      const pa=worldToScreen(a.x,a.y),pb=worldToScreen(b.x,b.y);
      const dx=pb.x-pa.x,dy=pb.y-pa.y;
      const len2=dx*dx+dy*dy;
      if(len2<16*16)continue; // zoom in before adding to a short edge
      const t=((screen.x-pa.x)*dx+(screen.y-pa.y)*dy)/len2;
      if(t<=0||t>=1)continue;
      const px=pa.x+t*dx,py=pa.y+t*dy;
      if(Math.hypot(screen.x-px,screen.y-py)>radius)continue;
      if(Math.min(Math.hypot(px-pa.x,py-pa.y),
                  Math.hypot(px-pb.x,py-pb.y))<8)continue;
      const dist=Math.hypot(screen.x-px,screen.y-py);
      if(!best||dist<best.distance){
        best={segmentIndex:i,world:screenToWorld(px,py),
              screen:{x:px,y:py},distance:dist};
      }
    }
    return best;
  }
  function previewSnap(world) {
    if(!state.snapEnabled)return {point:world,kind:null,code:null};
    const radius=11/state.scale;
    let bestVertex=null,bestEdge=null;
    for(const feature of state.features){
      if(feature.id===state.active)continue;
      // Shared-node mode must never snap a 5310 corner onto 5220.
      // Python enforces the same restriction on the entire source MAP.
      if(state.sharedNodes&&feature.code!==state.detail?.code)continue;
      // The neighbor that moves together with a dragged corner cannot be
      // the snap target of its own OLD, stationary boundary.
      if(state.sharedNodes&&state.vertexDrag){
        const activePoint=editableVertices()[state.vertexDrag.index];
        if(activePoint){
          const original=nativeWorldPoint(activePoint), bb=feature.bbox;
          if(original.x>=bb[0]-.002&&original.x<=bb[2]+.002&&
             original.y>=bb[1]-.002&&original.y<=bb[3]+.002&&
             sameCodeNeighborPreview(feature,original,original))
            continue;
        }
      }
      const b=feature.bbox;
      if(world.x<b[0]-radius||world.x>b[2]+radius||
         world.y<b[1]-radius||world.y>b[3]+radius)continue;
      for(const part of feature.geometry){
        for(let i=0;i<part.length;i++){
          const point=part[i];
          const dist=Math.hypot(point[0]-world.x,point[1]-world.y);
          if(dist<=radius&&(!bestVertex||dist<bestVertex.dist))
            bestVertex={dist,point:{x:point[0],y:point[1]},kind:"węzeł",code:feature.code};
          if(i===0)continue;
          const a=part[i-1], b=point;
          const dx=b[0]-a[0],dy=b[1]-a[1],len=dx*dx+dy*dy;
          if(!len)continue;
          const t=Math.max(0,Math.min(1,
            ((world.x-a[0])*dx+(world.y-a[1])*dy)/len));
          const px=a[0]+t*dx,py=a[1]+t*dy;
          const d=Math.hypot(px-world.x,py-world.y);
          if(d<=radius&&(!bestEdge||d<bestEdge.dist))
            bestEdge={dist:d,point:{x:px,y:py},kind:"krawędź",code:feature.code};
        }
      }
    }
    const match=bestVertex||bestEdge;
    if(match&&state.sharedNodes){
      const active=editableVertices()[state.vertexDrag?.index];
      if(active){
        const original=nativeWorldPoint(active);
        if(Math.hypot(original.x-match.point.x,
                      original.y-match.point.y)<=.002)
          return {point:world,kind:null,code:null};
      }
    }
    return match?{point:match.point,kind:match.kind,code:match.code}
                :{point:world,kind:null,code:null};
  }
  function sameCodeNeighborPreview(feature, source, destination) {
    // Display the SAME-CODE topology that will be committed to native MAP.
    // A neighbor may not have a vertex at the shared T-junction yet; the
    // backend inserts it at the original point before the move.
    let touched=false;
    const parts=feature.geometry.map(part=>{
      let changed=false;
      const changedPart=[];
      for(let i=0;i<part.length;i++){
        const node=part[i];
        const near=Math.hypot(node[0]-source.x,node[1]-source.y)<=.0015;
        if(near){
          changedPart.push([destination.x,destination.y]);
          changed=true;
        }else{
          if(i>0){
            const prev=part[i-1],dx=node[0]-prev[0],dy=node[1]-prev[1];
            const len=dx*dx+dy*dy;
            if(len>1e-12){
              const t=((source.x-prev[0])*dx+(source.y-prev[1])*dy)/len;
              const px=prev[0]+Math.max(0,Math.min(1,t))*dx;
              const py=prev[1]+Math.max(0,Math.min(1,t))*dy;
              if(t>0&&t<1&&
                 Math.hypot(px-source.x,py-source.y)<=.0015&&
                 Math.hypot(px-prev[0],py-prev[1])>.005&&
                 Math.hypot(px-node[0],py-node[1])>.005){
                changedPart.push([destination.x,destination.y]);
                changed=true;
              }
            }
          }
          changedPart.push(node);
        }
      }
      if(changed)touched=true;
      return changedPart;
    });
    return touched?parts:null;
  }
  function drawVertexTool() {
    if(state.tool!=="nodes"||!state.detail?.closed)return;
    const points=editableVertices();
    if(!points.length)return;
    const drag=state.vertexDrag;
    if(drag&&state.sharedNodes){
      const source=nativeWorldPoint(points[drag.index]);
      for(const feature of state.features){
        if(feature.id===drag.fid||feature.code!==drag.code||!isVisible(feature))
          continue;
        if(source.x<feature.bbox[0]-.002||source.x>feature.bbox[2]+.002||
           source.y<feature.bbox[1]-.002||source.y>feature.bbox[3]+.002)
          continue;
        const preview=sameCodeNeighborPreview(feature,source,drag.preview);
        if(preview){
          addPath(preview);
          ctx.strokeStyle="#05a989";
          ctx.lineWidth=2.4;
          ctx.setLineDash([5,3]);
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }
    }
    if(drag){
      ctx.beginPath();
      for(let i=0;i<points.length;i++){
        const world=i===drag.index?drag.preview:nativeWorldPoint(points[i]);
        const p=worldToScreen(world.x,world.y);
        if(i===0)ctx.moveTo(p.x,p.y);else ctx.lineTo(p.x,p.y);
      }
      ctx.closePath();
      ctx.strokeStyle="#0b958b";
      ctx.lineWidth=2.2;
      ctx.setLineDash([6,4]);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    for(let i=0;i<points.length;i++){
      const world=drag&&drag.index===i?drag.preview:nativeWorldPoint(points[i]);
      const p=worldToScreen(world.x,world.y);
      if(p.x< -10||p.x>state.width+10||p.y< -10||p.y>state.height+10)continue;
      ctx.beginPath();ctx.arc(p.x,p.y,i===drag?.index?6:4,0,2*Math.PI);
      ctx.fillStyle=i===drag?.index?"#ffc263":
        i===state.selectedVertex?"#ffd86a":"#f8ffff";
      ctx.fill();ctx.lineWidth=i===state.selectedVertex?3:2;
      ctx.strokeStyle=i===state.selectedVertex?"#d34b22":"#078d89";ctx.stroke();
    }
    if(!drag&&state.hoverInsert){
      const p=state.hoverInsert.screen;
      ctx.save();
      ctx.beginPath();ctx.arc(p.x,p.y,8,0,2*Math.PI);
      ctx.fillStyle="#edfff9";ctx.fill();
      ctx.lineWidth=2;ctx.strokeStyle="#0b958b";ctx.stroke();
      ctx.strokeStyle="#0b958b";ctx.lineWidth=2;
      ctx.beginPath();ctx.moveTo(p.x-4,p.y);ctx.lineTo(p.x+4,p.y);
      ctx.moveTo(p.x,p.y-4);ctx.lineTo(p.x,p.y+4);ctx.stroke();
      ctx.restore();
    }
    if(drag?.snap){
      const p=worldToScreen(drag.preview.x,drag.preview.y);
      ctx.beginPath();ctx.arc(p.x,p.y,10,0,2*Math.PI);
      ctx.lineWidth=1.5;ctx.strokeStyle="#dc8c32";ctx.stroke();
      if(drag.snap.code){
        const foreign=drag.snap.code!==drag.code;
        const note=foreign
          ?"PRZYCIĄGANIE DO "+drag.snap.code+" · bez zmiany "+drag.snap.code
          :"PRZYCIĄGANIE · "+drag.snap.code;
        ctx.save();
        ctx.font="bold 11px Segoe UI, sans-serif";
        const width=Math.min(315,ctx.measureText(note).width+18);
        const left=Math.max(12,Math.min(state.width-width-12,p.x+14));
        const top=Math.max(12,Math.min(state.height-35,p.y-39));
        ctx.fillStyle=foreign?"#244459":"#136f65";
        ctx.fillRect(left,top,width,27);
        ctx.fillStyle="#ffffff";
        ctx.textBaseline="middle";ctx.fillText(note,left+9,top+13);
        ctx.restore();
      }
    }
  }
  async function insertVertexAtSegment(segment) {
    if(state.editBusy||!state.edit||!state.active||!state.detail?.closed)
      return;
    const fid=state.active,code=state.detail.code;
    state.hoverInsert=null;
    state.editBusy=true;
    updateEditState(state.edit);
    try {
      const response=await api("/api/object/"+
        encodeURIComponent(fid)+"/vertices",{
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body:JSON.stringify({...editRequestBody(),
            segmentIndex:segment.segmentIndex,
            x:-segment.world.y,y:segment.world.x,
            shared:state.sharedNodes,
            edgeRadius:Math.max(.001,Math.min(50,9/state.scale))})
        });
      updateEditState(response);
      const affected=response.affectedObjects||[];
      if(response.sourceCode!==code||
         response.foreignCodesProtected!==true||
         affected.some(item=>item.code!==code)){
        inform("Nieprawidłowy raport edycji. Sprawdź wynik przed zapisem.",true);
        await refreshEditedDocument(fid);
        return;
      }
      state.selectedVertex=response.insertedVertexIndex;
      await refreshEditedDocument(fid);
      inform("Dodano wierzchołek "+code+
        (response.insertedSameCodeVertices
          ?" oraz "+response.insertedSameCodeVertices+
            " w sąsiednich poligonach "+code:"")+
        ". Ctrl+Z — cofnięcie.");
    }catch(error){
      inform("Nie można dodać wierzchołka: "+error.message,true);
    }finally{
      state.editBusy=false;
      updateEditState(state.edit);
      updateDeleteNodeButton();
      requestDraw();
    }
  }
  async function deleteSelectedVertex() {
    if(state.tool!=="nodes"||!state.detail?.closed||!state.edit||
       state.editBusy)return;
    const index=state.selectedVertex;
    if(index===null||!Number.isInteger(index)){
      inform("Najpierw kliknij konkretny węzeł poligonu w trybie P.");
      return;
    }
    const fid=state.active,code=state.detail.code;
    state.editBusy=true;updateEditState(state.edit);
    updateDeleteNodeButton();
    try {
      const response=await api("/api/object/"+
        encodeURIComponent(fid)+"/vertices/"+index,{
        method:"DELETE",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...editRequestBody(),shared:state.sharedNodes})
      });
      updateEditState(response);
      const affected=response.affectedObjects||[];
      if(response.sourceCode!==code||
         response.foreignCodesProtected!==true||
         affected.some(o=>o.code!==code)){
        inform("Nieprawidłowa odpowiedź edytora. Sprawdź kopię MAP.",true);
        await refreshEditedDocument(fid);return;
      }
      state.selectedVertex=null;
      await refreshEditedDocument(fid);
      inform("Usunięto węzeł "+code+
        (response.removedSameCodeVertices
          ?" i "+response.removedSameCodeVertices+" wspólnych węzłów "+code:"")+
        ". Ctrl+Z przywraca węzły.");
    }catch(error){
      inform("Nie udało się usunąć węzła: "+error.message,true);
    }finally{
      state.editBusy=false;updateEditState(state.edit);
      updateDeleteNodeButton();requestDraw();
    }
  }
  async function commitVertexDrag(drag) {
    if(state.editBusy||!state.edit||!state.active)return;
    if(state.detail?.code!==drag.code||state.active!==drag.fid){
      inform("Zmienił się aktywny obiekt. Ponownie wybierz poligon przed edycją.",true);
      return;
    }
    const before=nativeWorldPoint(editableVertices()[drag.index]);
    if(!before)return;
    if(Math.hypot(drag.preview.x-before.x,drag.preview.y-before.y)*
       state.scale<.5){requestDraw();return;}
    state.editBusy=true;updateEditState(state.edit);
    try {
      // Native GEO-MAP coordinate order: X=northing, Y=easting.
      const response=await api("/api/object/"+encodeURIComponent(drag.fid)+"/vertex",{
        method:"PATCH", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...editRequestBody(),index:drag.index,
          x:-drag.preview.y,y:drag.preview.x,shared:state.sharedNodes,
          snapRadius:state.snapEnabled?Math.min(50,11/state.scale):0})
      });
      updateEditState(response);
      if(response.changed){
        const affected=response.affectedObjects||[];
        const wrongCode=affected.some(item=>item.code!==drag.code);
        if(response.sourceCode!==drag.code||wrongCode||
           response.foreignCodesProtected!==true){
          inform("Nieprawidłowy raport kodów. Sprawdź kopię mapy przed dalszą edycją.",true);
          await refreshEditedDocument(drag.fid);
          return;
        }
        await refreshEditedDocument(drag.fid);
        const snappedForeign=response.snap?.code&&response.snap.code!==drag.code;
        const added=response.insertedSameCodeVertices||0;
        inform("Przesunięto "+affected.length+" obiektów kodu "+drag.code+
          (added?" (uzupełniono "+added+" węzłów na sąsiednich bokach).":"")+
          ". "+(snappedForeign
            ?"Przyciągnięto do "+response.snap.code+" (bez zmiany jego geometrii). "
            :"")+ "Ctrl+Z cofa.");
      }
    }catch(error){
      inform("Nie udało się przesunąć węzła: "+error.message,true);
      requestDraw();
    }finally{state.editBusy=false;updateEditState(state.edit);}
  }
  function renderLabels(features) {
    if(!state.labels) return;
    let painted=0;
    const collisions=[];
    // Source annotations have their own text height stored in GEO-MAP.
    // Parcel numbers are suppressed at map overview scale, but appear
    // when zoomed enough to read them. Building labels remain prioritized.
    const ordered=[...features].sort((a,b)=>{
      // Active object's A1/A2 should not be hidden by competing labels.
      const priority=f=>f.id===state.active?-2:
        state.pinned.has(f.id)?-1:
        f.code==="5310"?0:
        ["7900","6000","6301","6900"].includes(f.code)?1:
        f.code==="5216"?2:3;
      return priority(a)-priority(b);
    });
    for(const feature of ordered) {
      if(!feature.labels?.length)continue;
      const box=feature.bbox;
      const w=(box[2]-box[0])*state.scale;
      const h=(box[3]-box[1])*state.scale;
      const special=["7900","6900","6000","6301"].includes(feature.code);
      const building=feature.code==="5310";
      if(!special&&!building&&(Math.max(w,h)<34||Math.min(w,h)<9))continue;
      if(building&&Math.max(w,h)<9)continue;
      for(const label of feature.labels){
        if(painted>=1100)return;
        const p=worldToScreen(label.x,label.y);
        const lines=String(label.text).split("\n").slice(0,6);
        const nativeSize=label.worldTextHeight;
        const size=nativeSize!==null&&nativeSize!==undefined
          ? Math.max(4,Math.min(50,nativeSize*state.scale))
          : Math.max(9,Math.min(36,label.size||12));
        const weight=label.bold?"700":"400";
        const family=String(label.fontFamily||"Segoe UI").replace(/["'\\]/g,"");
        ctx.font=weight+" "+size+"px '"+family+"', sans-serif";
        const widths=lines.map(line=>ctx.measureText(line.slice(0,100)).width);
        const maxWidth=Math.max(...widths,0);
        const lineHeight=size*1.13;
        const left=p.x-maxWidth/2;
        const baseline=p.y+(label.offset||0);
        const rect=[left-2,baseline-size-2,left+maxWidth+2,
                    baseline+(lines.length-1)*lineHeight+4];
        if(rect[2]<0||rect[0]>state.width||
           rect[3]<0||rect[1]>state.height)continue;
        // Avoid pretending that a dense cadastral overview should show
        // thousands of overlapping labels; classic Qt scales these.
        if(collisions.some(r=>r[0]<rect[2]&&r[2]>rect[0]&&
                              r[1]<rect[3]&&r[3]>rect[1]))continue;
        collisions.push(rect);
        const showSelectedLabel=feature.id===state.active&&
          (label.field==="A1"||label.field==="A2");
        if(showSelectedLabel){
          // When a polygon 5310 is active, highlight BOTH corresponding
          // description strings, not just the geometry outline.
          ctx.fillStyle="rgba(27,150,143,.23)";
          ctx.fillRect(rect[0]-2,rect[1]-2,
            rect[2]-rect[0]+4,rect[3]-rect[1]+4);
        }
        ctx.textBaseline="alphabetic";
        for(let j=0;j<lines.length;j++){
          const line=lines[j].slice(0,100);
          const px=p.x-widths[j]/2;
          const py=baseline+j*lineHeight;
          ctx.strokeStyle=document.body.classList.contains("dark-map")
            ?"#1b2c3d":"#f8fafc";
          ctx.lineWidth=Math.min(2.2,Math.max(.8,size*.14));
          ctx.strokeText(line,px,py);
          ctx.fillStyle=label.color||"#4A5056";
          ctx.fillText(line,px,py);
        }
        painted++;
      }
    }
  }
  function draw() {
    state.scheduled=false;
    const isDark=document.body.classList.contains("dark-map");
    ctx.setTransform(state.pixelRatio,0,0,state.pixelRatio,0,0);
    ctx.clearRect(0,0,state.width,state.height);
    ctx.fillStyle=isDark?"#17283b":"#FAFCFD";
    ctx.fillRect(0,0,state.width,state.height);
    drawGrid();
    if(!state.meta) return;
    const box=boundsFromViewport(.05);
    const features=state.features.filter(f=>isVisible(f)&&isInView(f.bbox,box));
    // Match the classic QGraphicsScene: paint fills below ALL outlines.
    // Painting fill+stroke for each object separately erased earlier
    // parcel borders beneath later overlapping polygons.
    const priorities={"5216":0,"5220":1,"5230":2,"5310":3,"1246":4};
    features.sort((a,b)=>(priorities[a.code]??3)-(priorities[b.code]??3));
    for(const feature of features) renderFill(feature);
    for(const feature of features) renderStroke(feature);
    renderHighlights(features);renderLabels(features);drawVertexTool();
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
    $("inspector-edit").hidden=true;
    $("inspector-fields").hidden=false;
    $("inspector-edit-toggle").textContent="✎ Edytuj";
    if(!detail)return;
    $("inspector-edit-toggle").disabled=!(detail.editableFields||[]).length;
    $("inspector-code").textContent=detail.code;
    updateGeometryHelp();
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
    if(state.active!==fid)state.selectedVertex=null;
    state.active=fid;state.detail=null;updateDeleteNodeButton();updateInspector();
    updateSelectionCount();requestDraw();
    if(fid===null)return;
    const ticket=++state.selectionRequest;
    try{
      const detail=state.inspectorCache.get(fid)||await api("/api/object/"+encodeURIComponent(fid));
      if(ticket!==state.selectionRequest||state.active!==fid)return;
      state.inspectorCache.set(fid,detail);state.detail=detail;
      if(state.selectedVertex!==null&&
         state.selectedVertex>=Math.max(0,detail.pointCount-1))
        state.selectedVertex=null;
      updateDeleteNodeButton();updateInspector();
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
      // While editing one code, do not silently switch the active object
      // to an overlapping 5220 on a subsequent canvas click.
      if(state.tool==="nodes"&&state.detail?.code&&
         f.code!==state.detail.code)continue;
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
      // Put visible buildings first; repeated clicks still cycle all hits.
      const priority=p=>p.code==="5310"?0:p.code==="5230"?1:
        p.code==="5220"?2:p.code==="5216"?3:4;
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
    state.hoverInsert=null;
    if(state.tool==="nodes"&&ev.button===0&&!state.editBusy){
      const index=closestEditableVertex(p);
      if(index>=0){
        const world=nativeWorldPoint(editableVertices()[index]);
        state.selectedVertex=index;
        updateDeleteNodeButton();
        state.vertexDrag={fid:state.active,code:state.detail.code,
                          index,preview:world,snap:null};
        state.drag={pointer:ev.pointerId,start:p,last:p,moved:false,node:true};
        requestDraw();return;
      }
    }
    state.drag={pointer:ev.pointerId,start:p,last:p,moved:false,
                pan:ev.button===1||state.tool==="pan"};
  });
  canvas.addEventListener("pointermove", ev=>{
    const p=eventCoords(ev),world=screenToWorld(p.x,p.y);
    $("cursor-coords").textContent="X: "+(-world.y).toFixed(3)+
                                   "   Y: "+world.x.toFixed(3);
    if(!state.drag&&state.tool==="nodes"&&!state.editBusy){
      state.hoverInsert=closestEditableSegment(p);
      requestDraw();
    }
    if(!state.drag||state.drag.pointer!==ev.pointerId)return;
    const d=state.drag;
    if(Math.hypot(p.x-d.start.x,p.y-d.start.y)>4)d.moved=true;
    if(d.node&&state.vertexDrag){
      if(d.moved){
        const snap=previewSnap(world);
        state.vertexDrag.preview=snap.point;
        state.vertexDrag.snap=snap.kind?snap:null;
        requestDraw();
      }
    }else if(d.moved){
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
    if(d.node){
      const moving=state.vertexDrag;
      state.vertexDrag=null;requestDraw();
      if(d.moved&&moving)commitVertexDrag(moving);
      else if(moving)inform("Zaznaczono węzeł "+(moving.index+1)+". Delete — usuń.");
      return;
    }
    if(d.moved){scheduleViewport();return;}
    if(d.pan)return;
    const p=eventCoords(ev);
    // Single-clicking the selected polygon's edge in P keeps it selected.
    // Otherwise the second click in a double-click may cycle to a
    // visually overlapping 5220 before our dblclick handler can insert.
    if(state.tool==="nodes"&&closestEditableSegment(p))return;
    const world=screenToWorld(p.x,p.y),hits=pick(world);
    if(!hits.length){selectFeature(null);state.lastPick=null;return;}
    let index=0;
    if(state.lastPick&&Math.hypot(state.lastPick.p.x-p.x,
       state.lastPick.p.y-p.y)<8&&hits.includes(state.lastPick.fid))
       index=(hits.indexOf(state.lastPick.fid)+1)%hits.length;
    const fid=hits[index];
    state.lastPick={p,fid};
    if(ev.ctrlKey||ev.shiftKey){
      // Ctrl/Shift-click adds or removes objects without losing the rest
      // of the multi-selection. Subsequent clicks cycle overlapping hits.
      const selection=new Set(state.pinned);
      if(state.active)selection.add(state.active);
      const wasSelected=selection.has(fid);
      if(wasSelected)selection.delete(fid);else selection.add(fid);
      state.pinned=selection;
      const next=wasSelected?
        (selection.has(state.active)?state.active:
          (selection.values().next().value||null)):fid;
      selectFeature(next);
    }else selectFeature(fid);
  });
  canvas.addEventListener("dblclick",ev=>{
    if(state.tool!=="nodes"||!state.meta)return;
    ev.preventDefault();ev.stopPropagation();
    if(state.editBusy||state.vertexDrag)return;
    const segment=closestEditableSegment(eventCoords(ev));
    if(!segment){
      inform("Dwuklik: wybierz środek krawędzi zaznaczonego poligonu "+
        "(nie istniejący węzeł). W razie potrzeby przybliż mapę.");
      return;
    }
    insertVertexAtSegment(segment);
  });
  canvas.addEventListener("pointerleave",()=>{
    if(state.hoverInsert){state.hoverInsert=null;requestDraw();}
  });
  canvas.addEventListener("pointercancel",()=>{state.drag=null;state.vertexDrag=null;shell.classList.remove("dragging");requestDraw();});
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
      ev.preventDefault();chooseMap();return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.key.toLowerCase()==="h"){
      ev.preventDefault();openAdvancedSelection();return;
    }
    if(typing)return;
    if(state.tool==="nodes"&&state.detail&&!ev.ctrlKey&&!ev.metaKey&&!ev.altKey&&
       (ev.key==="Delete"||ev.key==="Backspace")){
      ev.preventDefault();deleteSelectedVertex();return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.key.toLowerCase()==="z"){
      ev.preventDefault();historyStep("undo");return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.key.toLowerCase()==="y"){
      ev.preventDefault();historyStep("redo");return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.shiftKey&&ev.key.toLowerCase()==="s"){
      ev.preventDefault();downloadMapCopy();return;
    }
    if(!ev.ctrlKey&&!ev.metaKey&&!ev.altKey&&ev.key.toLowerCase()==="e"&&state.detail){
      // Prevent the original E keypress from entering the newly focused A1.
      ev.preventDefault();
      ev.stopPropagation();
      toggleInspectorEdit(true);
      return;
    }
    if(!ev.ctrlKey&&!ev.metaKey&&!ev.altKey&&ev.key.toLowerCase()==="p"){
      ev.preventDefault();setTool("nodes");return;
    }
    if(ev.key==="Escape"){
      if(dialog.open)dialog.close();
      else if(state.tool==="nodes"){
        state.vertexDrag=null;setTool("select");
      }else selectFeature(null);
      return;
    }
    if(ev.key.toLowerCase()==="s")setTool("select");
    if(ev.key.toLowerCase()==="h")setTool("pan");
    if(ev.key.toLowerCase()==="b")pinActive();
    if(ev.key==="0")fitToMap();
    if(ev.key==="/"){ev.preventDefault();$("layer-search").focus();}
  });

  const link=(id,callback)=>$(id).addEventListener("click",callback);
  link("btn-open",chooseMap);
  link("tool-open",chooseMap);
  link("empty-open",chooseMap);
  link("tool-advanced-select",openAdvancedSelection);
  link("select-close",()=>$("select-dialog").close());
  link("select-clear",clearAdvancedSelection);
  $("select-form").addEventListener("submit",applyAdvancedSelection);

  link("tool-sidecar",()=> $("file-sidecar").click());
  link("tool-undo",()=>historyStep("undo"));
  link("tool-redo",()=>historyStep("redo"));
  link("btn-export",downloadMapCopy);
  link("inspector-edit-toggle",()=>{
    toggleInspectorEdit($("inspector-edit").hidden);
  });
  link("inspector-cancel",()=>toggleInspectorEdit(false));
  $("inspector-edit-form").addEventListener("submit",saveAttributeChanges);
  link("tool-select",()=>setTool("select"));
  link("tool-pan",()=>setTool("pan"));
  link("tool-nodes",()=>setTool("nodes"));
  link("tool-delete-node",deleteSelectedVertex);
  link("float-nodes",()=>setTool("nodes"));
  $("opt-snap").addEventListener("change",ev=>{state.snapEnabled=ev.target.checked;});
  $("opt-shared").addEventListener("change",ev=>{
    state.sharedNodes=ev.target.checked;updateGeometryHelp();
  });
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
      if(map)openMap(map).then(ok=>{if(ok&&style)openStyles(style);});
      else if(style)openStyles(style);
    }
  });

  window.addEventListener("beforeunload",ev=>{
    if(state.edit?.dirty){
      ev.preventDefault();ev.returnValue="";
    }
  });
  new ResizeObserver(()=>{resizeCanvas();if(state.meta)scheduleViewport();}).observe(shell);
  resizeCanvas();
  api("/api/map").then(meta=>{
    if(meta.loaded){
      state.meta=meta;
      updateEditState(meta);
      state.visibleLayers=new Set(
        meta.layers.map(layer=>layer.name).filter(name=>name!=="Graniczniki"));
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
