/* GeoStudio 2.0 — experimental HTML5 map canvas and in-memory GEO-MAP editing.
   World coordinates: horizontal = GEO-MAP easting Y, vertical = -northing X.
   This matches the classic geodetic PySide6 orientation.
   Original MAP files are never overwritten: changes are exported as copies.
*/
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const token = document.querySelector('meta[name="api-token"]').content;
  const documentId=document.querySelector('meta[name="geostudio-document"]')?.content||"";
  const host=()=>documentId&&window.parent!==window?window.parent.GeoStudioTabs:null;
  if(documentId)document.body.dataset.documentEditor="true";
  const documentFetch=(path,options={})=>{
    if(!documentId)return window.fetch(path,options);
    const headers=new Headers(options.headers||{});
    headers.set("X-GeoStudio-Document",documentId);
    return window.fetch(path,{...options,headers});
  };
  // Never use an unscoped desktop bridge from a document frame. The
  // top-level bridge validates the document ID and the operation allowlist.
  const scopedMethods=["open_map","open_raster","open_libraries","save_recovery","restore_recovery",
    "save_map","save_base_map","save_baked_map","save_tiled_export","save_generated_export"];
  const nativeAPI=()=>{
    if(!documentId)return window.pywebview?.api;
    const bridge=window.parent.pywebview?.api;
    if(typeof bridge?.document_call!=="function")return null;
    return Object.fromEntries(scopedMethods.map(name=>[
      name,async(...args)=>{nativePending++;try{return await bridge.document_call(documentId,name,args);}finally{nativePending--;}}
    ]));
  };
  let pickerBusy=false,newDocumentOnFile=false,nativePending=0;
  const canvas = $("map-canvas"), shell = $("canvas-shell");
  // The label layer lives above the geometry canvas and never participates
  // in its bitmap zoom/pan. One CSS px means the same on every wheel tick.
  const labelCanvas = $("map-labels-canvas");
  const labelCtx = labelCanvas.getContext("2d");
  let ctx = canvas.getContext("2d");
  const formatter = new Intl.NumberFormat("pl-PL");
  const state = {
    meta: null, features: [], visibleLayers: new Set(), hiddenGrades: new Set(),
    hiddenLandUses:new Set(), expandedLandUses:false, expandedForest:false,
    appTheme:"dark", mapBackground:"#FFFFFF",
    center: {x: 0, y: 0}, scale: 1, tool: "select",
    labels: true, grid: false, active: null, detail: null, pinned: new Set(),
    cartoLibraries: {},
    previewActive:false,previewCamera:null,geometrySnapshotValid:false,
    localMapReady:false,localMapCandidate:false,
    width: 1, height: 1, pixelRatio: 1, isDragging: false, drag: null,
    lastPick: null, scheduled: false, refreshTimer: null, queryCounter: 0,
    queryAbort: null, selectionRequest: 0, limited: false,
    firstLoad: true, inspectorCache: new Map(), viewportFeatureCache:new Map(),
    edit: null, editBusy: false, bulkPreview: null, movePreview: null,
    moveIds: [], moveGhost: null, objectPreview:null,
    drawPoints:[], drawHover:null, drawSnap:null,
    labelHits:[],labelDrag:null,labelSelected:null,
    drawMagnet:true,drawCursorWorld:null,copyIds:[],
    geometryPreview:null,cutIds:[],lineEditId:null,
    auditReport:null, auditBusy:false, auditActiveIssue:null,
    snapEnabled: true, sharedNodes: false, vertexDrag: null,
    hoverInsert: null, selectedVertex: null, mapEPSG:""
  };
  // WMS is a read-only background; never part of MAP, geometry or export.
  const underlay = {
    enabled:false, image:null, bounds:null, opacity:.75, preset:"standard",
    layer:"", epsg:null, ticket:0, timer:null, abort:null, visible:true, loading:false
  };
  const raster = {
    image:null,affine:null,epsg:null,boundEPSG:null,opacity:.72,name:"",
    sourceWidth:0,sourceHeight:0,
    ticket:0,pendingWorld:null,visible:true,gcps:[],id:0,
    layers:[],serial:0
  };
  const commands = [
    {name:"Otwórz plik GEO-MAP", hint:"Ctrl+O", run:chooseMap},
    {name:"Podkłady WMS",hint:"Podkłady",run:openUnderlayDialog},
    {name:"Wczytaj raster i skalibruj GCP",hint:"Podkłady",run:openRasterDialog},
    {name:"Sprawdź układ mapy EPSG lub PRJ",hint:"Podkłady",run:openCrsDialog},
    {name:"Wybierz obiekty według kodu, A1, A2", hint:"Ctrl+H", run:openAdvancedSelection},
    {name:"Znajdź obiekt po ID, kodzie lub treści", hint:"F", run:openFindDialog},
    {name:"Zamień fragment w atrybutach z podglądem", hint:"Ctrl+F", run:openReplaceDialog},
    {name:"Edytuj zbiorowo pola A1/A2", hint:"Ctrl+Shift+E", run:openBulkEditor},
    {name:"Przeciągaj wybrane obiekty", hint:"M", run:()=>setTool("move")},
    {name:"Kopiuj obok i przesuń myszą", hint:"Ctrl+D", run:quickDuplicate},
    {name:"Kopiuj z dokładnym przesunięciem", hint:"X/Y", run:openCopyEditor},
    {name:"Scal zaznaczone poligony", hint:"Ctrl+Shift+G", run:mergePolygons},
    {name:"Podziel poligon linią", hint:"Ctrl+Shift+X", run:startSplit},
    {name:"Napraw kierunek obrysu (dodatnia powierzchnia)", hint:"Pole +", run:repairWinding},
    {name:"Rysuj nową linię", hint:"L", run:()=>setTool("line")},
    {name:"Edytuj wybraną linię", hint:"Shift+L", run:startEditLine},
    {name:"Usuń wybrane obiekty", hint:"Ctrl+Delete", run:deleteObjects},
    {name:"Rysuj nowy poligon", hint:"N", run:()=>setTool("draw")},
    {name:"Magnes rysowania — przełącz; Alt chwilowo wyłącza", hint:"G", run:toggleDrawMagnet},
    {name:"Wczytaj plik stylów GeoStudio", hint:"JSON", run:()=> $("file-sidecar").click()},
    {name:"Wczytaj biblioteki kartograficzne GEO-MAP LAY/CDF/SYM", hint:"Etap 7", run:chooseCartographicLibraries},
    {name:"Odtwórz oryginalną geometrię z JSON topologii", hint:"MAP+JSON", run:()=> $("file-topology").click()},
    {name:"Dopasuj całą mapę", hint:"0", run:fitToMap},
    {name:"Edytuj atrybuty aktywnego obiektu", hint:"E", run:()=>toggleInspectorEdit(true)},
    {name:"Cofnij ostatnią zmianę", hint:"Ctrl+Z", run:()=>historyStep("undo")},
    {name:"Ponów zmianę", hint:"Ctrl+Y", run:()=>historyStep("redo")},
    {name:"Pobierz osobną kopię MAP", hint:"Ctrl+Shift+S", run:downloadMapCopy},
    {name:"Eksportuj PNG/JPG/TIFF/DXF lub drukuj mapę", hint:"Ctrl+P", run:openLayoutDialog},
    {name:"Awaryjna kopia MAP bez wycięć", hint:"Baza", run:downloadBaseMapCopy},
    {name:"Zapisz natywne wycięcia MAP i kopię konturów", hint:"6B", run:downloadNativeCutouts},
    {name:"Zaznaczanie obiektów", hint:"S", run:()=>setTool("select")},
    {name:"Odznacz wszystkie obiekty", hint:"Esc", run:clearAdvancedSelection},
    {name:"Edytuj węzły zaznaczonego poligonu", hint:"P", run:()=>setTool("nodes")},
    {name:"Usuń zaznaczony węzeł poligonu", hint:"Delete", run:deleteSelectedVertex},
    {name:"Przesuwanie mapy", hint:"H", run:()=>setTool("pan")},
    {name:"Włącz / wyłącz etykiety", hint:"Aa", run:toggleLabels},
    {name:"Przesuń pojedyncze A1/A2/TX myszą",hint:"Alt+L",run:()=>setTool("labels")},
    {name:"Ustaw opis według kodu",hint:"Ctrl+Alt+L",run:openLabelSettings},
    {name:"Ustaw skalę opracowania",hint:"Ctrl+F5",run:()=> $("compilation-scale").focus()},
    {name:"Ustaw skalę widoku",hint:"Ctrl+M",run:()=> $("view-scale").focus()},
    {name:"Włącz / wyłącz siatkę", hint:"▦", run:toggleGrid},
    {name:"Pokaż wszystkie warstwy", hint:"Warstwy", run:showAllLayers},
    {name:"Przełącz jasny/ciemny motyw programu", hint:"◐", run:toggleTheme},
    {name:"Kontrola poprawności topologii mapy",hint:"Kontrola",run:()=>openTopologyPanel(true)},
    {name:"Pokaż wyniki kontroli geometrii",hint:"Kontrola",run:openTopologyPanel},
    {name:"Wybierz kolor tła mapy", hint:"Paleta", run:()=> $("map-background-menu").open=true}
  ];
  let toastTimer;
  let recoveryTimer=null,recoverySavedKey='',recoveryBusy=false;
  const htmlText = (node, value) => { node.textContent = String(value); };
  const api = async (path, options={}) => {
    const res = await documentFetch(path, {
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
    // Cached viewport geometry is scoped to an edit revision.
    if(state.edit&&(state.edit.revision!==status.revision||
       state.edit.documentToken!==status.documentToken))
      state.viewportFeatureCache.clear();
    if(state.edit&&state.edit.documentToken!==status.documentToken){
      state.exportAreaBounds=null;state.exportAreaPicking=false;
      state.exportAreaDrag=null;
    }
    if(state.auditReport&&(status.revision!==state.auditReport.revision||
       status.documentToken!==state.auditReport.documentToken)){
      state.auditReport=null;state.auditActiveIssue=null;
      if(!$("topology-panel").hidden){
        queueMicrotask(scanTopology);
        $("topology-edit").disabled=true;
        $("topology-delete-duplicate").hidden=true;
      }
    }
    state.edit={
      sheetItems:status.sheetItems||[],
      dirty:!!status.dirty,
      canUndo:!!status.canUndo,
      canRedo:!!status.canRedo,
      hasReversibleMasks:!!status.hasReversibleMasks,
      hasVisualStyles:!!status.hasVisualStyles,
      compilationScale:status.compilationScale||5000,
      sourceCompilationScale:status.sourceCompilationScale||5000,
      revision:status.revision,
      documentToken:status.documentToken,
      undoLabel:status.undoLabel||"",
      redoLabel:status.redoLabel||""
    };
    $("tool-undo").disabled=state.editBusy||!state.edit.canUndo;
    $("tool-redo").disabled=state.editBusy||!state.edit.canRedo;
    $("tool-move-offset").disabled=state.editBusy||!state.meta||!selectedObjectIds().length;
    $("tool-copy").disabled=state.editBusy||!state.meta||!selectedObjectIds().length;
    $("tool-delete-objects").disabled=state.editBusy||!state.meta||!selectedObjectIds().length;
    for(const id of ["tool-new-polygon","float-draw","float-line","float-snap"])
      $(id).disabled=state.editBusy||!state.meta;
    $("btn-export").disabled=state.editBusy||!state.meta;
    $("btn-layout").disabled=state.editBusy||!state.meta;
    $("tool-export-baked").disabled=state.editBusy||!state.meta;
    $("btn-export-label").textContent=(
      state.edit.hasReversibleMasks||state.edit.hasVisualStyles)
      ?"Pobierz MAP + JSON":"Pobierz MAP";
    if(document.activeElement!==$("compilation-scale"))
      $("compilation-scale").value="1:"+state.edit.compilationScale;
    updateBulkButton();
    $("tool-undo").title=state.edit.undoLabel
      ?"Cofnij: "+state.edit.undoLabel+" (Ctrl+Z)":"Cofnij (Ctrl+Z)";
    $("tool-redo").title=state.edit.redoLabel
      ?"Ponów: "+state.edit.redoLabel+" (Ctrl+Y)":"Ponów (Ctrl+Y)";
    const marker=$("dirty-marker");
    marker.textContent=state.edit.dirty?"Niezapisane zmiany w pamięci":"Oryginał chroniony";
    marker.classList.toggle("unsaved",state.edit.dirty);
    notifyHost();
    scheduleRecovery();
  }
  function scheduleRecovery() {
    clearTimeout(recoveryTimer);
    if(!state.edit?.dirty||!nativeAPI()?.save_recovery)return;
    const tokenBefore=state.edit.documentToken;
    const revisionBefore=state.edit.revision;
    const key=tokenBefore+":"+revisionBefore;
    if(key===recoverySavedKey)return;
    recoveryTimer=setTimeout(async()=>{
      if(state.editBusy||recoveryBusy){scheduleRecovery();return;}
      if(!state.edit?.dirty||state.edit.documentToken!==tokenBefore||
         state.edit.revision!==revisionBefore){scheduleRecovery();return;}
      recoveryBusy=true;
      try{
        const saved=await nativeAPI().save_recovery();
        if(saved?.saved){
          recoverySavedKey=key;
          $("dirty-marker").title=
            "Zmiany są w pamięci i w lokalnej kopii awaryjnej: "+
            (saved.savedAt||"teraz")+
            ". Oryginalny MAP pozostaje niezmieniony.";
        }
      }catch(error){
        $("dirty-marker").title="Nie udało się zapisać kopii awaryjnej: "+
          (error.message||String(error));
        inform("Ostrzeżenie: nie zapisano kopii awaryjnej. "+
          (error.message||String(error)),true);
      }finally{
        recoveryBusy=false;
        if(state.edit?.dirty&&
           (state.edit.documentToken+":"+state.edit.revision)!==key)
          scheduleRecovery();
      }
    },1300);
  }

  function editRequestBody() {
    return {documentToken:state.edit?.documentToken,
            revision:state.edit?.revision};
  }
  function editorStatus(){
    return {name:state.meta?.name||"Nowa mapa",loaded:!!state.meta,
      dirty:!!state.edit?.dirty,theme:state.appTheme,
      busy:pickerBusy||nativePending>0||state.editBusy||recoveryBusy||state.auditBusy||
        !$("loading-overlay").hidden||
        !!document.querySelector("dialog[open]")};
  }
  function notifyHost(){
    host()?.status(documentId,editorStatus());
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
  async function downloadNativeCutouts() {
    if(!state.meta||state.editBusy)return;
    if(!nativeAPI()?.save_baked_map){
      inform("Natywny eksport wycięć wymaga okna GeoStudio w Windows. "+
             "Użyj start_web_ui.bat bez --browser.",true);
      return;
    }
    if(!window.confirm(
        "Eksport eksperymentalny 6B\n\n"+
        "Poligony pod nałożonymi obiektami tego samego kodu będą "+
        "faktycznie wycięte w nowym pliku MAP (w tym otwory i wiele wysp).\n"+
        "Obok zapisze się JSON z oryginalną geometrią do odtworzenia.\n\n"+
        "Zachowaj OBA pliki i sprawdź wynik w klasycznym GEO-MAP.\n"+
        "Nie używaj jako danych produkcyjnych przed potwierdzeniem zgodności.\n\n"+
        "Kontynuować?"))return;
    try{
      const res=await nativeAPI().save_baked_map();
      if(res&&!res.cancelled){
        window.alert("Wycięcia GEO-MAP zapisane:\n"+res.path+
          "\n\nKopia oryginalnych konturów:\n"+res.topologyPath+
          "\n\nZachowaj oba pliki. W GEO-MAP sprawdź obrysy i pola.");
        inform("Zapisano natywne wycięcia i odwracalną kopię JSON.");
      }
    }catch(error){inform("Eksport 6B przerwany: "+error.message,true);}
  }
  async function downloadBaseMapCopy() {
    if(!state.meta||!state.edit||state.editBusy)return;
    if(!window.confirm("Zapiszesz MAP z oryginalnymi obrysami bez wycięć. "+
      "Pozostałe zmiany geometrii i atrybutów pozostaną. "+
      "Używaj tej opcji tylko do awaryjnej kopii bazowej."))return;
    try{
      if(nativeAPI()?.save_base_map){
        const saved=await nativeAPI().save_base_map();
        if(saved&&!saved.cancelled){
          inform("Zapisano kopię MAP bez wycięć: "+saved.path);
          window.alert("Bazowa kopia MAP zapisana w:\n"+saved.path+
            (saved.topologyPath?"\nTopologia: "+saved.topologyPath:""));
        }
        return;
      }
      const params=new URLSearchParams({
        documentToken:state.edit.documentToken,normalizePositive:"true"});
      const response=await documentFetch("/api/export/map?"+params.toString(),{
        headers:{"X-GeoStudio-Token":token},cache:"no-store"});
      if(!response.ok){
        const err=await response.json().catch(()=>({}));
        throw Error(err.detail||"Nie można zapisać MAP.");
      }
      const original=state.meta.name.replace(/\\/g,"/").split("/").pop();
      const filename=original.replace(/\.map$/i,"")+
        "_GeoStudio2_kopia_bez_wyciec.MAP";
      const url=URL.createObjectURL(await response.blob());
      const a=document.createElement("a");
      a.href=url;a.download=filename;document.body.append(a);
      a.click();a.remove();
      setTimeout(()=>URL.revokeObjectURL(url),60000);
      inform("Pobrano bazowy MAP bez wycięć: "+filename);
    }catch(error){
      inform("Błąd zapisu bazowego MAP: "+error.message,true);
    }
  }

  async function downloadMapCopy() {
    if(!state.meta||!state.edit||state.editBusy)return;
    try {
      // WebView2 can ignore <a download> and produce no file. Use Windows
      // Save As instead, and display the real path after a successful write.
      if(nativeAPI()?.save_map) {
        const saved=await nativeAPI().save_map();
        if(saved&&!saved.cancelled){
          inform("Zapisano kopię MAP: "+saved.path+
                 " ("+display(saved.bytes)+" bajtów).");
          window.alert("Kopia GEO-MAP została zapisana w:\n"+saved.path+
            (saved.topologyPath?"\n\nPlik odwracalnej topologii:\n"+
            saved.topologyPath+"\nZachowaj oba pliki razem.":"")+
(saved.visualPath?"\n\nUstawienia opisów i skali:\n"+
saved.visualPath+"\nZachowaj obok MAP.":""));
        }
        return;
      }
      const hasMasks=!!state.edit.hasReversibleMasks;
      const needsPackage=hasMasks||!!state.edit.hasVisualStyles||!!state.meta.mapEPSG;
      const params=new URLSearchParams({documentToken:state.edit.documentToken,
        normalizePositive:"true"});
      const response=await documentFetch((needsPackage?"/api/export/package":"/api/export/map")+
        "?"+params.toString(),{
        headers:{"X-GeoStudio-Token":token},cache:"no-store"
      });
      if(!response.ok){
        const problem=await response.json().catch(()=>({}));
        throw Error(problem.detail||"Błąd tworzenia pliku MAP.");
      }
      const blob=await response.blob();
      const original=state.meta.name.replace(/\\/g,"/").split("/").pop();
      const filename=original.replace(/\.map$/i,"")+
        (needsPackage?"_GeoStudio2_z_etykietami.zip":"_GeoStudio2_kopia.MAP");
      const url=URL.createObjectURL(blob);
      const anchor=document.createElement("a");
      anchor.href=url;anchor.download=filename;
      document.body.append(anchor);anchor.click();anchor.remove();
      setTimeout(()=>URL.revokeObjectURL(url),60000);
      inform(needsPackage
        ?"Pobrano ZIP z MAP i ustawieniami etykiet oraz topologii. Zachowaj pliki JSON obok MAP."
        :"Wysłano "+filename+" do pobrania; sprawdź Pobrane (Ctrl+J).");
    }catch(error){inform("Nie udało się zapisać kopii: "+error.message,true);}
  }
  function inform(msg, isError=false) {
    htmlText($("status-message"), msg);
    const toast = $("toast");
    const toastHost=$("raster-dialog")?.open?$("raster-dialog"):document.body;
    if(toast.parentNode!==toastHost)toastHost.append(toast);
    toast.textContent = msg;
    toast.style.borderColor = isError ? "#d98769" : "#3a928d";
    toast.hidden = false; clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, 3900);
  }
  function busy(on, label) {
    $("loading-overlay").hidden = !on;
    if (label) htmlText($("loading-detail"), label);
    notifyHost();
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
    removeUnderlay();removeRaster(true);
    // An EPSG choice belongs to the previously opened map and must
    // NEVER be silently reused for unrelated GEO-MAP coordinates.
    state.meta = meta;
    setMapEPSG(meta.mapEPSG||"");
    updateEditState(meta);
    state.active = null; state.detail = null; state.pinned.clear();
    populateSelectCodes();
    state.vertexDrag=null;state.moveGhost=null;state.movePreview=null;
    state.labelDrag=null;state.labelSelected=null;state.labelHits=[];
    state.previewActive=false;state.previewCamera=null;
    state.geometrySnapshotValid=false;
    state.localMapReady=false;state.localMapCandidate=false;
    state.moveIds=[];state.copyIds=[];state.drawPoints=[];
    state.cutIds=[];state.lineEditId=null;state.geometryPreview=null;
    state.drawHover=null;state.drawSnap=null;state.drawCursorWorld=null;
    state.objectPreview=null;setTool("select");
    state.features = []; state.inspectorCache.clear();
    state.viewportFeatureCache.clear();
    // Ordinary cadastral MAP: transfer the whole geometry just ONCE.
    // Zoom and pan then render local Canvas data, without HTTP requests.
    state.localMapCandidate=meta.objectCount<=50000&&
      meta.vertexCount<=750000;
    state.localMapReady=false;
    // Match the old user's map view: survey markers are opt-in.
    // Their heavy symbol density otherwise hides the parcel boundaries.
    state.visibleLayers = new Set(
      meta.layers.map(layer=>layer.name).filter(name=>name!=="Graniczniki"));
    state.hiddenGrades = new Set();state.hiddenLandUses = new Set();
    state.expandedLandUses=false;state.expandedForest=false; state.firstLoad = false;
    $("empty-state").hidden = true;
    htmlText($("document-title"), meta.name);
    htmlText($("map-status"), meta.name);
    htmlText($("layer-count"), meta.layers.length);
    htmlText($("count-objects"), display(meta.objectCount));
    htmlText($("count-vertices"), display(meta.vertexCount));
    const quality = $("checksum-badge");
    quality.hidden = !!meta.checksumValid;
    quality.textContent = meta.checksumValid ? "✓ CHK poprawna" : "⚠ CHK niezgodna";
    quality.classList.toggle("warning", !meta.checksumValid);
    renderLayers(); updateInspector(); fitToMap(); updateSelectionCount();
    restoreCalibrations();
    cartographyMessage({libraries:meta.cartographicLibraries});
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
      const meta=await api("/api/map");
      updateEditState(meta);
      inform("Wczytano "+result.labelPositions+" pozycji opisów, "+
        result.styleCount+" stylów. Skala opracowania 1:"+result.compilationScale+".");
      await refreshViewport();
    } catch (error) {
      inform("Nie udało się wczytać JSON: " + error.message, true);
    } finally { busy(false); $("file-sidecar").value = ""; }
  }

  async function openTopologyFile(file) {
    if(!file||!state.meta)return;
    if(!file.name.toLowerCase().endsWith(".json")||
       file.size>2*1024*1024){
      inform("Wybierz plik .geostudio-topology.json (do 2 MB).",true);
      return;
    }
    if(state.edit?.dirty){
      inform("Najpierw otwórz oryginalny MAP bez nowych edycji, "+
        "a następnie jego JSON topologii.",true);
      return;
    }
    busy(true,"Odtwarzanie oryginalnych konturów z JSON");
    try{
      const meta=await api("/api/topology",{
        method:"POST",
        headers:{"Content-Type":"application/octet-stream"},
        body:await file.arrayBuffer()
      });
      finishOpeningMap(meta);
      inform("Wczytano MAP+JSON. Odzyskano źródłowe kontury; "+
        "wycięcia pozostają dynamiczne i odwracalne.");
    }catch(error){
      inform("Nie udało się odtworzyć geometrii: "+error.message,true);
    }finally{busy(false);$("file-topology").value="";}
  }

  let cartographyCatalog=null;
  function drawCartographySample(canvas,style){
    const g=canvas.getContext("2d"),w=canvas.width,h=canvas.height;
    g.clearRect(0,0,w,h);g.fillStyle="#f7fafb";g.fillRect(0,0,w,h);
    const color=style.stroke||"#334e60";
    const segments=style.symbolSegments||[],circles=style.symbolCircles||[];
    if(segments.length||circles.length){
      g.strokeStyle=color;g.lineWidth=Math.max(.8,style.strokeWidth||1);
      g.beginPath();
      for(const [x1,y1,x2,y2] of segments.slice(0,64)){
        g.moveTo(w/2+x1*5,h/2-y1*5);
        g.lineTo(w/2+x2*5,h/2-y2*5);
      }
      for(const [x,y,r] of circles.slice(0,32)){
        g.moveTo(w/2+(x+r)*5,h/2-y*5);
        g.arc(w/2+x*5,h/2-y*5,r*5,0,2*Math.PI);
      }
      g.stroke();return;
    }
    if(style.hasFill){
      g.save();g.globalAlpha=Math.min(1,Math.max(0,style.opacity));
      g.fillStyle=hatchPattern(style);
      g.fillRect(8,8,w-16,h-16);g.restore();
    }
    g.lineWidth=Math.max(.5,Math.min(8,style.strokeWidth||1));
    g.strokeStyle=color;
    g.setLineDash(Array.isArray(style.dash)?style.dash:[]);
    g.strokeRect(8,8,w-16,h-16);
    g.setLineDash([]);
  }
  function renderCartographyCatalog(){
    const list=$("carto-catalog-list");list.replaceChildren();
    const catalog=cartographyCatalog;
    if(!catalog)return;
    const pattern=$("carto-catalog-filter").value.trim().toLocaleLowerCase("pl-PL");
    const selected=catalog.items.filter(item=>
      [item.code,item.layer,item.a1,item.a2].some(
        value=>String(value||"").toLocaleLowerCase("pl-PL").includes(pattern)));
    const libraries=Object.entries(catalog.libraries||{})
      .map(([type,item])=>type+": "+(item.filename||"")+" ("+
        item.definitions+" definicji)").join(" · ")||"Nie załadowano bibliotek";
    $("carto-catalog-summary").textContent=
      libraries+" · "+selected.length+" z "+catalog.totalCodes+
      " kodów · katalog przykładów, nie pełna zgodność GEO-MAP.";
    if(!selected.length){
      const text=document.createElement("p");text.className="panel-placeholder";
      text.textContent="Brak kodów odpowiadających filtrowi.";
      list.append(text);return;
    }
    for(const item of selected){
      const card=document.createElement("article");card.className="carto-catalog-row";
      const canvas=document.createElement("canvas");
      canvas.width=112;canvas.height=56;canvas.className="carto-catalog-swatch";
      drawCartographySample(canvas,item.style);
      const info=document.createElement("div");info.className="carto-catalog-info";
      const title=document.createElement("strong");
      title.textContent=item.code+" · "+item.layer+" ("+item.count+" ob.)";
      const sample=document.createElement("span");
      sample.textContent="Przykład: A1 "+(item.a1||"—")+
        ", A2 "+(item.a2||"—");
      const found=document.createElement("span");
      found.textContent="Dopasowano "+
        ((item.style.libraryMatches||[]).join(", ")||"brak")+
        " · użyto "+((item.style.libraryApplied||[]).join(", ")||"styl bazowy")+
        " · kreska "+(item.style.strokeWidth||1)+" px"+
        (item.style.hatch?" · deseń CDF "+item.style.hatch:"");
      info.append(title,sample,found);
      if(item.notes.length){
        const warning=document.createElement("span");
        warning.className="carto-catalog-warning";
        warning.textContent=item.notes.join(" · ");info.append(warning);
      }
      card.append(canvas,info);list.append(card);
    }
  }
  async function loadCartographyCatalog(){
    if(!state.meta){inform("Najpierw otwórz plik MAP.",true);return;}
    $("carto-catalog-summary").textContent="Odczytuję wzorce z mapy i bibliotek…";
    try{
      cartographyCatalog=await api("/api/cartography/catalog?limit=200");
      renderCartographyCatalog();
    }catch(error){
      $("carto-catalog-summary").textContent="Błąd katalogu: "+error.message;
    }
  }
  function openCartographyCatalog(){
    if(!state.meta){inform("Najpierw otwórz plik MAP.",true);return;}
    $("cartography-catalog-dialog").showModal();
    loadCartographyCatalog();
  }
  async function refreshOutlineStyleEditor(){
    const code=$("outline-style-code").value;
    if(!code)return;
    try{
      const setting=await api("/api/cartography/outline?code="+
        encodeURIComponent(code));
      if($("outline-style-code").value!==code)return;
      $("outline-style-color").value=setting.stroke;
      $("outline-style-width").value=String(setting.strokeWidth);
      $("outline-style-summary").textContent=
        (setting.custom?"Własny styl kodu ":"Styl domyślny kodu ")+code+
        " · "+setting.stroke+" · "+setting.strokeWidth+" px.";
    }catch(error){
      $("outline-style-summary").textContent="Nie można odczytać: "+error.message;
    }
  }
  function openOutlineStyleEditor(){
    if(!state.meta){inform("Najpierw otwórz mapę.",true);return;}
    const select=$("outline-style-code");
    const last=select.value;
    select.replaceChildren();
    const supported=new Set(["5214","5216","5220","5230","5310",
      ...Object.keys(state.meta.codes||{})]);
    for(const code of [...supported].sort())
      select.add(new Option(code+" · "+
        display((state.meta.codes||{})[code]||0)+" ob.",code));
    const preferred=state.detail?.code||last||"5310";
    if([...select.options].some(opt=>opt.value===preferred))
      select.value=preferred;
    else if([...select.options].some(opt=>opt.value==="5310"))
      select.value="5310";
    $("outline-style-dialog").showModal();
    refreshOutlineStyleEditor();
  }
  async function saveOutlineStyle(ev,reset=false){
    ev.preventDefault();
    if(state.editBusy||!state.meta)return;
    const code=$("outline-style-code").value;
    const stroke=$("outline-style-color").value;
    const strokeWidth=Number($("outline-style-width").value);
    state.editBusy=true;updateEditState(state.edit);
    $("outline-style-apply").disabled=true;
    $("outline-style-reset").disabled=true;
    try{
      const result=await api("/api/cartography/outline",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...editRequestBody(),code,stroke,strokeWidth,reset})
      });
      updateEditState(result);
      if(result.changed)await refreshViewport();
      if(reset)await refreshOutlineStyleEditor();
      $("outline-style-summary").textContent=reset
        ?"Przywrócono obrys wynikający z MAP / LAY / CDF."
        :"Zapisano obrys kodu "+code+": "+stroke+", "+strokeWidth+
          " px. Dotyczy także nowych poligonów.";
      requestDraw();
    }catch(error){
      $("outline-style-summary").textContent="Nie zapisano: "+error.message;
      inform("Błąd obrysu: "+error.message,true);
    }finally{
      state.editBusy=false;updateEditState(state.edit);
      $("outline-style-apply").disabled=false;
      $("outline-style-reset").disabled=false;
    }
  }
  function cartographyMessage(payload) {
    state.cartoLibraries=payload?.libraries||{};
    cartographyCatalog=null;
    renderCartographyMatches();
    if($("cartography-catalog-dialog").open)loadCartographyCatalog();
  }
  function renderCartographyMatches() {
    const loaded=state.cartoLibraries||{};
    if(!Object.keys(loaded).length){
      $("cartography-status").textContent="Brak bibliotek";
      $("cartography-status").title="Wczytaj oryginalne LAY/CDF/SYM, aby odwzorować znane style GEO-MAP.";
      return;
    }
    const matched={CDF:0,LAY:0,SYM:0},applied={CDF:0,LAY:0,SYM:0};
    for(const feature of state.features){
      if(!isVisible(feature))continue;
      for(const type of feature.style?.libraryMatches||[])
        if(Object.hasOwn(matched,type))matched[type]++;
      for(const type of feature.style?.libraryApplied||[])
        if(Object.hasOwn(applied,type))applied[type]++;
    }
    const summary=Object.entries(loaded).map(([kind,item])=>
      kind+": "+applied[kind]+"/"+matched[kind]).join(" · ");
    const noMatch=Object.keys(loaded).every(type=>!matched[type]);
    $("cartography-status").textContent=summary||
      "Brak dopasowań";
    $("cartography-status").title=
      "W aktualnie wyświetlonej części mapy: ZASTOSOWANIA / DOPASOWANIA. "+
      Object.entries(loaded).map(([kind,item])=>kind+": "+
        (item.definitions||0)+" rozpoznanych definicji, "+
        (matched[kind]||0)+" obiektów pasuje, "+
        (applied[kind]||0)+" wykorzystuje styl.").join(" ")+
      (noMatch?" Wybrane biblioteki mogą nie zawierać kodów widocznej mapy.":"");
  }
  async function chooseCartographicLibraries() {
    if(nativeAPI()?.open_libraries){
      try {
        const result=await nativeAPI().open_libraries();
        if(result&&!result.cancelled){
          cartographyMessage(result.status);
          inform("Załadowano biblioteki kartograficzne: "+
            result.libraries.map(item=>item.kind+" "+item.definitions).join(", "));
          await refreshViewport();
          if(result.libraries.some(x=>x.kind==="SYM")&&
             !state.visibleLayers.has("Graniczniki"))
            inform("Symbole SYM mogą być niewidoczne: warstwa Graniczniki jest ukryta. Włącz ją w panelu warstw.");
        }
      }catch(error){
        inform("Nie można załadować bibliotek: "+error.message,true);
      }
    }else $("file-library").click();
  }
  async function openCartographicFiles(files) {
    const list=Array.from(files||[]);
    if(!list.length)return;
    if(list.length>3){
      inform("Wybierz najwyżej LAY, CDF i SYM (po jednym pliku).",true);return;
    }
    const kinds=new Set();
    for(const file of list){
      const type=file.name.split(".").pop().toUpperCase();
      if(!["LAY","CDF","SYM"].includes(type)||kinds.has(type)||
         file.size>8*1024*1024){
        inform("Nieprawidłowe biblioteki: po jednym LAY/CDF/SYM, max 8 MB.",true);
        return;
      }
      kinds.add(type);
    }
    busy(true,"Wczytywanie bibliotek kartograficznych");
    try{
      for(const file of list){
        await api("/api/cartography/library",{
          method:"POST",
          headers:{"Content-Type":"application/octet-stream",
                   "X-Library-Name":encodeURIComponent(file.name)},
          body:await file.arrayBuffer()
        });
      }
      const status=await api("/api/cartography/status");
      cartographyMessage(status);
      inform("Załadowano "+list.length+" bibliotek. Renderowanie mapy odświeżone.");
      await refreshViewport();
      if(kinds.has("SYM")&&!state.visibleLayers.has("Graniczniki"))
        inform("Włącz warstwę Graniczniki w panelu, by zobaczyć symbole punktowe SYM.");
    }catch(error){
      inform("Błąd biblioteki GEO-MAP: "+error.message,true);
    }finally{busy(false);$("file-library").value="";}
  }

  function chooseStandardMap(newDocument=false){
    newDocumentOnFile=newDocument;
    $("file-map").value="";
    $("file-map").click();
  }
  function showPickerFallback(){
    if(!$("map-picker-fallback").open)$("map-picker-fallback").showModal();
  }
  async function chooseMap(){
    if(pickerBusy||state.editBusy)return;
    // On an already loaded map, open in a NEW tab. Never discard edits.
    if(host()&&state.meta){
      if(nativeAPI()?.open_map)return host().newMap();
      return chooseStandardMap(true);
    }
    return chooseMapHere();
  }
  async function chooseMapHere() {
    if(pickerBusy||state.editBusy)return;
    if(nativeAPI()?.open_map){
      if(!confirmDiscardEdits())return;
      pickerBusy=true;notifyHost();
      try {

          const answer=await nativeAPI().open_map();
          if(answer&&!answer.cancelled&&answer.metadata){
            finishOpeningMap(answer.metadata);
            if(answer.metadata.topologyWarning)
              inform(answer.metadata.topologyWarning,true);
            if(answer.metadata.visualWarning)
              inform(answer.metadata.visualWarning,true);
            if(answer.metadata.recoveryAvailable&&
               nativeAPI()?.restore_recovery){
              const candidate=answer.metadata.recoveryAvailable;
              const consent=window.confirm(
                "Wykryto kopię awaryjną niezapisanych zmian z "+candidate.savedAt+
                " (wersja "+candidate.revision+").\n\n"+
                "Odtworzyć poprzednią sesję GeoStudio? "+
                "Oryginalny plik MAP pozostanie nienaruszony.");
              if(consent){
                busy(true,"Odzyskiwanie zmian z kopii awaryjnej");
                try{
                  const restored=await nativeAPI().restore_recovery();
                  if(restored?.restored){
                    finishOpeningMap(restored.metadata);
                    inform("Odzyskano niezapisane zmiany. "+
                      "Zapisz je jako NOWY MAP; źródło pozostaje chronione.");
                  }
                }catch(error){
                  inform("Nie udało się odzyskać zmian: "+
                    (error.message||String(error)),true);
                }finally{busy(false);}
              }
            }
          }
      }catch(error){
        inform("Nie udało się otworzyć okna wyboru mapy: "+(error?.message||String(error)),true);
        showPickerFallback();
      }finally{pickerBusy=false;notifyHost();}
      return;
    }
    // Standard file input is synchronous on the original user gesture,
    // and does not depend on the optional native bridge or picker API.
    chooseStandardMap(false);
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
  let findList=[],replacePreview=null;
  function openFindDialog(){
    if(!state.meta){inform("Najpierw otwórz mapę MAP.");return;}
    $("find-dialog").showModal();
    $("find-value").focus();
  }
  function openReplaceDialog(){
    if(!state.meta){inform("Najpierw otwórz mapę MAP.");return;}
    $("replace-scope").value="selection";
    invalidateReplacePreview();
    $("replace-dialog").showModal();
    $("replace-needle").focus();
  }
  function findOptions(){
    return {
      code:$("find-code").value.trim(),
      field:$("find-field").value,
      value:$("find-value").value.trim(),
      match:$("find-match").value,
      limit:"120"
    };
  }
  function zoomToSearchResult(result){
    if(!state.meta)return;
    const b=result.bbox||state.meta.bounds;
    const width=Math.max(.2,b[2]-b[0]);
    const height=Math.max(.2,b[3]-b[1]);
    const target=Math.min((state.width-160)/width,
                          (state.height-160)/height)*.75;
    state.center={x:(b[0]+b[2])/2,y:(b[1]+b[3])/2};
    state.scale=Math.max(.000001,Math.min(3500,target));
    state.previewActive=false;state.previewCamera=null;
    state.pinned.clear();state.lastPick=null;
    selectFeature(result.id);
    requestDraw();scheduleViewport();
    $("find-dialog").close();
    canvas.focus({preventScroll:true});
    inform("Znaleziono "+result.code+" · "+(result.uid||result.id)+
      ". Obiekt zaznaczony i wycentrowany.");
  }
  async function submitFind(ev){
    ev.preventDefault();
    const params=new URLSearchParams(findOptions());
    $("find-summary").textContent="Przeszukiwanie całej mapy…";
    $("find-results").replaceChildren();
    $("find-select-all").disabled=true;
    findList=[];
    try{
      const res=await api("/api/find?"+params.toString());
      if(res.documentToken!==state.edit?.documentToken||
         res.revision!==state.edit?.revision)
        throw Error("Mapa zmieniła się podczas wyszukiwania.");
      findList=res.results||[];
      $("find-summary").textContent=
        "Znaleziono "+display(res.count)+" obiektów. "+
        (res.truncated
         ?"Wyświetlono tylko "+display(findList.length)+
          " pierwszych — zawęź wyszukiwanie."
         :"Kliknij wynik, aby go zaznaczyć na mapie.");
      $("find-select-all").disabled=!findList.length;
      for(const result of findList){
        const row=document.createElement("button");
        row.type="button";row.className="geostudio-find-result";
        row.setAttribute("role","listitem");
        const title=document.createElement("strong");
        title.textContent=result.code+" · "+(result.uid||result.id);
        const description=document.createElement("span");
        description.textContent=
          ["A1: "+(result.A1||"—"),
           "A2: "+(result.A2||"—"),
           result.TX?"TX: "+result.TX:""].filter(Boolean).join(" · ");
        row.append(title,description);
        row.addEventListener("click",()=>zoomToSearchResult(result));
        $("find-results").append(row);
      }
    }catch(err){
      $("find-summary").textContent="Nie udało się wyszukać: "+err.message;
      inform("Błąd wyszukiwania: "+err.message,true);
    }
  }
  function selectFindResults(){
    if(!findList.length)return;
    const selected=findList.map(item=>item.id);
    state.pinned=new Set(selected);
    state.active=selected[0]||null;
    $("find-dialog").close();
    updateSelectionCount();
    selectFeature(state.active);
    inform("Zaznaczono "+display(selected.length)+
      " wyświetlonych wyników. Ctrl+H umożliwia pełniejsze filtrowanie.");
  }
  function replaceOperation(){
    return {
      field:$("replace-field").value,
      needle:$("replace-needle").value,
      replacement:$("replace-replacement").value,
      caseSensitive:$("replace-case").checked,
      scope:$("replace-scope").value,
      ids:$("replace-scope").value==="selection"?selectedObjectIds():[],
      code:$("replace-code").value.trim()
    };
  }
  function invalidateReplacePreview(){
    replacePreview=null;
    $("replace-apply").disabled=true;
    $("replace-examples").replaceChildren();
    $("replace-summary").textContent=
      "Podgląd jest wymagany po każdej zmianie kryteriów.";
  }
  async function previewReplacePhrase(){
    if(state.editBusy||!state.meta)return;
    invalidateReplacePreview();
    const operation=replaceOperation();
    if(operation.scope==="selection"&&!operation.ids.length){
      $("replace-summary").textContent=
        "Brak zaznaczenia. Wybierz obiekty przez Ctrl+H "+
        "albo świadomie ustaw zakres «Cała mapa».";
      return;
    }
    const request={...editRequestBody(),operation};
    $("replace-preview").disabled=true;
    $("replace-summary").textContent="Sprawdzanie wszystkich wartości i kodowania CP1250…";
    try{
      const res=await api("/api/replace/preview",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(request)
      });
      if(res.documentToken!==request.documentToken||
         res.revision!==request.revision)
        throw Error("Mapa zmieniła się podczas podglądu.");
      replacePreview={request,report:res};
      $("replace-apply").disabled=!res.canApply;
      $("replace-summary").textContent=
        "Pasujących obiektów: "+display(res.changedObjects)+
        " · Zamienianych wystąpień: "+display(res.occurrences)+
        " · Sprawdzonych: "+display(res.scanned)+
        ". Całość można cofnąć jednym Ctrl+Z.";
      for(const entry of res.examples||[]){
        const row=document.createElement("div");
        row.className="geostudio-find-result replace-preview-row";
        row.setAttribute("role","listitem");
        const title=document.createElement("strong");
        title.textContent=entry.code+" · "+entry.uid;
        const before=document.createElement("span");
        before.textContent="Przed: "+entry.before;
        const after=document.createElement("span");
        after.textContent="Po: "+entry.after;
        row.append(title,before,after);
        $("replace-examples").append(row);
      }
    }catch(err){
      $("replace-summary").textContent="Podgląd nieudany: "+err.message;
      inform("Nie można zamienić: "+err.message,true);
    }finally{$("replace-preview").disabled=false;}
  }
  async function applyReplacePhrase(ev){
    ev.preventDefault();
    if(!replacePreview||state.editBusy)return;
    const current={...editRequestBody(),operation:replaceOperation()};
    if(JSON.stringify(current)!==JSON.stringify(replacePreview.request)){
      invalidateReplacePreview();
      inform("Zmieniono zaznaczenie lub mapę. Wykonaj podgląd ponownie.",true);
      return;
    }
    const report=replacePreview.report;
    if(!report.canApply)return;
    if(!window.confirm("Zamienić "+display(report.occurrences)+
      " fragmentów w "+display(report.changedObjects)+
      " obiektach?\n\nWszystkie zmiany cofniesz jednym Ctrl+Z. "+
      "Oryginalny MAP nie zostanie nadpisany."))return;
    state.editBusy=true;updateEditState(state.edit);
    $("replace-apply").disabled=true;
    try{
      const res=await api("/api/replace/apply",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...current,previewKey:report.previewKey})
      });
      updateEditState(res);
      replacePreview=null;
      $("replace-dialog").close();
      await refreshEditedDocument(state.active);
      inform("Zamieniono "+display(res.occurrences)+" wystąpień w "+
        display(res.changedObjects)+" obiektach. Jedno Ctrl+Z cofa całość.");
    }catch(err){
      invalidateReplacePreview();
      inform("Nie wykonano zamiany: "+err.message,true);
    }finally{
      state.editBusy=false;updateEditState(state.edit);
    }
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
    state.labelSelected=null;
    selectFeature(null);
    $("select-preview").textContent="Wyczyszczono wszystkie zaznaczenia.";
    inform("Odznaczono wszystkie obiekty.");
    requestDraw();
  }
  function selectedObjectIds() {
    const ids=new Set(state.pinned);
    if(state.active)ids.add(state.active);
    return [...ids].sort((a,b)=>{
      const ai=Number(a.slice(1)),bi=Number(b.slice(1));
      return ai-bi;
    });
  }
  function updateBulkButton() {
    $("tool-bulk-edit").disabled=!state.meta||!state.edit||
      state.editBusy||selectedObjectIds().length===0;
  }
  function invalidateBulkPreview() {
    state.bulkPreview=null;
    $("bulk-apply").disabled=true;
    $("bulk-summary").textContent=
      "Wprowadź wartości i kliknij „Sprawdź zmiany” przed zatwierdzeniem.";
    $("bulk-samples").hidden=true;
    $("bulk-samples").replaceChildren();
  }
  function openBulkEditor() {
    if(!state.meta||!state.edit||state.editBusy){
      inform("Najpierw otwórz mapę i wybierz obiekty.",true);return;
    }
    const ids=selectedObjectIds();
    if(!ids.length){
      inform("Zaznacz obiekty przez Ctrl+H albo na mapie.",true);return;
    }
    if(ids.length>5000){
      inform("Edycja zbiorowa obsługuje do 5 000 obiektów na raz. "+
        "Zawęź wybór przez Ctrl+H (A1/A2).",true);return;
    }
    $("bulk-enable-a1").checked=false;
    $("bulk-enable-a2").checked=false;
    $("bulk-value-a1").value="";
    $("bulk-value-a2").value="";
    $("bulk-value-a1").disabled=true;
    $("bulk-value-a2").disabled=true;
    $("bulk-selection-description").textContent=
      "Wybrano "+display(ids.length)+" obiektów z całej mapy. "+
      "Włącz A1 i/lub A2, wpisz nowe wartości i sprawdź podgląd. "+
      "Żaden plik źródłowy nie zostanie nadpisany.";
    invalidateBulkPreview();
    $("bulk-dialog").showModal();
    $("bulk-enable-a1").focus();
  }
  function bulkRequest() {
    const changes={};
    if($("bulk-enable-a1").checked)changes.A1=$("bulk-value-a1").value;
    if($("bulk-enable-a2").checked)changes.A2=$("bulk-value-a2").value;
    if(!Object.keys(changes).length)throw Error(
      "Włącz przynajmniej jedno pole A1 lub A2.");
    return {...editRequestBody(),ids:selectedObjectIds(),changes};
  }
  function showBulkSamples(report) {
    const container=$("bulk-samples");
    container.replaceChildren();
    if(!(report.samples||[]).length){container.hidden=true;return;}
    const table=document.createElement("table");
    const thead=document.createElement("thead");
    const headRow=document.createElement("tr");
    for(const value of ["Kod / ID","Pole","Było","Będzie"]){
      const cell=document.createElement("th");
      cell.textContent=value;headRow.append(cell);
    }
    thead.append(headRow);table.append(thead);
    const tbody=document.createElement("tbody");
    for(const item of report.samples){
      for(const [field,edit] of Object.entries(item.fields)){
        const row=document.createElement("tr");
        for(const text of [item.code+" · "+item.uid,field,
                           edit.before||"∅",edit.after||"∅"]){
          const cell=document.createElement("td");
          cell.textContent=text;row.append(cell);
        }
        tbody.append(row);
      }
    }
    table.append(tbody);container.append(table);container.hidden=false;
  }
  async function previewBulkChanges() {
    if(state.editBusy)return;
    invalidateBulkPreview();
    let payload;
    try{payload=bulkRequest();}
    catch(error){$("bulk-summary").textContent=error.message;return;}
    const button=$("bulk-preview");button.disabled=true;
    $("bulk-summary").textContent="Sprawdzanie wszystkich zaznaczonych obiektów…";
    try{
      const report=await api("/api/bulk/preview",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify(payload)
      });
      if(report.documentToken!==state.edit?.documentToken||
         report.revision!==state.edit?.revision)
        throw Error("Wersja mapy zmieniła się w trakcie podglądu.");
      const missing=Object.entries(report.missingFields||{})
        .map(([key,n])=>key+": "+display(n)).join(", ");
      const unchanged=Object.entries(report.alreadyEqualFields||{})
        .map(([key,n])=>key+": "+display(n)).join(", ");
      const codes=Object.entries(report.codes||{})
        .map(([code,n])=>code+": "+display(n)).join(", ");
      $("bulk-summary").textContent=
        "Zaznaczono: "+display(report.selected)+" obiektów\n"+
        "Zmieni się: "+display(report.changedObjects)+" obiektów / "+
          display(report.changedFields)+" pól\n"+
        "Kody zmienianych obiektów: "+(codes||"brak")+"\n"+
        "Brak pola (zostanie pominięty): "+(missing||"0")+"\n"+
        "Już taka sama wartość (bez zmiany): "+(unchanged||"0")+
        (report.canApply
          ?"\nSprawdź przykłady poniżej, a następnie zatwierdź."
          :"\nBrak faktycznych zmian do wykonania.");
      showBulkSamples(report);
      if(report.canApply){
        state.bulkPreview={payload,previewKey:report.previewKey,report};
        $("bulk-apply").disabled=false;
      }
    }catch(error){
      $("bulk-summary").textContent="Nie można sprawdzić zmian: "+error.message;
      inform("Podgląd edycji zbiorowej: "+error.message,true);
    }finally{button.disabled=false;}
  }
  async function applyBulkChanges(event) {
    event.preventDefault();
    if(state.editBusy||!state.bulkPreview)return;
    const preview=state.bulkPreview;
    if(JSON.stringify(bulkRequest())!==JSON.stringify(preview.payload)){
      invalidateBulkPreview();
      inform("Zmieniono dane po podglądzie. Sprawdź zmiany ponownie.",true);
      return;
    }
    if(preview.report.changedObjects>=100&&!window.confirm(
      "Potwierdź zbiorową zmianę "+display(preview.report.changedObjects)+
      " obiektów. Całą operację można cofnąć Ctrl+Z."))
      return;
    const button=$("bulk-apply");
    state.editBusy=true;updateEditState(state.edit);
    button.disabled=true;$("bulk-preview").disabled=true;
    try{
      const result=await api("/api/bulk/apply",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...preview.payload,previewKey:preview.previewKey})
      });
      state.bulkPreview=null;
      updateEditState(result);
      $("bulk-dialog").close();
      if(result.changed){
        await refreshEditedDocument(state.active);
        inform("Zmieniono "+display(result.changedObjects)+
          " obiektów, "+display(result.changedFields)+
          " pól. Cofnij: Ctrl+Z. Pobierz kopię MAP.");
      }else inform("Nie było żadnych wartości do zmiany.");
    }catch(error){
      invalidateBulkPreview();
      $("bulk-summary").textContent=
        "Nie udało się zastosować zmian: "+error.message+
        ". Ponownie sprawdź podgląd.";
      inform("Edycja zbiorowa: "+error.message,true);
    }finally{
      state.editBusy=false;updateEditState(state.edit);
      button.disabled=true;$("bulk-preview").disabled=false;
    }
  }
  function invalidateMovePreview() {
    state.movePreview=null;
    $("move-apply").disabled=true;
    $("move-summary").textContent="Kliknij „Sprawdź przesunięcie” przed zatwierdzeniem.";
    $("move-samples").hidden=true;
    $("move-samples").replaceChildren();
  }
  function openMoveEditor(ids=selectedObjectIds(),dx=0,dy=0,checkNow=false) {
    if(!state.meta||!state.edit||state.editBusy){
      inform("Najpierw otwórz mapę i wybierz poligony.",true);return;
    }
    if(!ids.length||ids.length>5000){
      inform("Zaznacz od 1 do 5 000 poligonów (Ctrl+H lub kliknięcie).",true);return;
    }
    state.moveIds=ids.slice();
    $("move-dx").value=Number(dx).toFixed(3);
    $("move-dy").value=Number(dy).toFixed(3);
    $("move-detach").checked=true;
    $("move-snap").checked=true;
    $("move-selection-description").textContent=
      "Wybrano "+display(ids.length)+" obiektów. X oznacza północ–południe, "+
      "Y wschód–zachód; dodatnie wartości przesuwają na północ i wschód.";
    invalidateMovePreview();
    $("move-dialog").showModal();
    if(checkNow)previewMoveChanges();
    else $("move-dx").focus();
  }
  function moveRequest() {
    const asNumber=id=>{
      const raw=$(id).value.trim().replace(",",".");
      if(!raw||!Number.isFinite(Number(raw)))throw Error("Podaj liczbę w metrach.");
      return Math.round(Number(raw)*1000)/1000;
    };
    return {...editRequestBody(),ids:state.moveIds.slice(),
      dx:asNumber("move-dx"),dy:asNumber("move-dy"),
      allowDetach:$("move-detach").checked,
      snapDistance:$("move-snap").checked?
        Math.round(Math.min(2,Math.max(0.02,10/state.scale))*1000)/1000:0};
  }
  function showMoveSamples(report) {
    const container=$("move-samples");container.replaceChildren();
    if(!(report.samples||[]).length){container.hidden=true;return;}
    const table=document.createElement("table"),head=document.createElement("tr");
    for(const label of ["Kod / ID","Pierwszy punkt przed (X / Y)","Po przesunięciu (X / Y)"]){
      const th=document.createElement("th");th.textContent=label;head.append(th);
    }
    const thead=document.createElement("thead");thead.append(head);table.append(thead);
    const body=document.createElement("tbody");
    for(const item of report.samples) {
      const tr=document.createElement("tr");
      const values=[item.code+" · "+item.uid,
        item.before.x.toFixed(3)+" / "+item.before.y.toFixed(3),
        item.after.x.toFixed(3)+" / "+item.after.y.toFixed(3)];
      for(const value of values){
        const td=document.createElement("td");td.textContent=value;tr.append(td);
      }
      body.append(tr);
    }
    table.append(body);container.append(table);container.hidden=false;
  }
  async function previewMoveChanges() {
    if(state.editBusy)return;
    invalidateMovePreview();
    let payload;
    try{payload=moveRequest();}
    catch(error){$("move-summary").textContent=error.message;return;}
    const button=$("move-preview");button.disabled=true;
    $("move-summary").textContent="Sprawdzanie geometrii i sąsiedztwa…";
    try{
      const report=await api("/api/move/preview",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(payload)
      });
      if(report.documentToken!==state.edit?.documentToken||
         report.revision!==state.edit?.revision)
        throw Error("Zmieniła się wersja mapy. Powtórz podgląd.");
      const codes=Object.entries(report.codes||{})
        .map(([key,n])=>key+": "+display(n)).join(", ");
      const neighbors=report.topologyConflicts||[];
      const overlaps=report.overlapConflicts||[];
      const examples=neighbors.slice(0,4)
        .map(item=>item.code+" ("+item.movingUid+" ↔ "+item.stationaryUid+")").join("; ");
      $("move-summary").textContent=
        "Wybrano: "+display(report.selected)+" obiektów / "+
          display(report.vertexCount)+" węzłów\n"+
        "Przesunięcie: X "+report.delta.x.toFixed(3)+" m; "+
          "Y "+report.delta.y.toFixed(3)+" m\n"+
        "Kody: "+(codes||"brak")+"\n"+
        "Odwracalne wycinanie na poligonach tego samego kodu: "+
          (overlaps.length?overlaps.map(x=>x.code+" "+x.stationaryUid).join(", "):"brak")+"\n"+
        (report.snapApplied?"Przyciągnięto do krawędzi, korekta "+
           report.snapApplied.distance.toFixed(3)+" m\n":"")+
        "Styki z nieruchomymi poligonami tego samego kodu: "+
          (neighbors.length?examples:"nie wykryto")+"\n"+
        (report.topologyBlocked
          ?"Zablokowano: dodaj sąsiadów do zaznaczenia albo świadomie zaznacz rozłączenie granicy."
          :report.canApply
            ?"Potwierdź odwracalne wycięcie w podglądzie. Źródłowe punkty pozostają zachowane."
            :"Brak przesunięcia (0 m).");
      showMoveSamples(report);
      if(report.canApply){
        state.movePreview={payload,previewKey:report.previewKey,report};
        $("move-apply").disabled=false;
      }
    }catch(error){
      $("move-summary").textContent="Nie można sprawdzić przesunięcia: "+error.message;
      inform("Przesuwanie obiektów: "+error.message,true);
    }finally{button.disabled=false;}
  }
  async function applyMoveChanges(ev) {
    ev.preventDefault();
    if(state.editBusy||!state.movePreview)return;
    const preview=state.movePreview;
    try{
      if(JSON.stringify(moveRequest())!==JSON.stringify(preview.payload)){
        invalidateMovePreview();
        inform("Zmieniono przesunięcie po podglądzie. Sprawdź je jeszcze raz.",true);
        return;
      }
    }catch(error){invalidateMovePreview();inform(error.message,true);return;}
    if((preview.report.selected>=100||preview.report.topologyConflicts?.length)&&
       !window.confirm(
         "Potwierdź przesunięcie "+display(preview.report.selected)+
         " obiektów. Cofnij: Ctrl+Z."))
      return;
    state.editBusy=true;updateEditState(state.edit);
    $("move-apply").disabled=true;$("move-preview").disabled=true;
    try{
      const result=await api("/api/move/apply",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...preview.payload,previewKey:preview.previewKey})
      });
      updateEditState(result);
      state.movePreview=null;
      $("move-dialog").close();
      if(result.changed){
        await refreshEditedDocument(state.active);
        inform("Przesunięto "+display(result.movedObjects)+
          " obiektów. Wycięcia poligonów tego samego kodu są odwracalne.");
      }
    }catch(error){
      invalidateMovePreview();
      $("move-summary").textContent="Nie zastosowano zmian: "+error.message+
        ". Ponów podgląd.";
      inform("Przesunięcie: "+error.message,true);
    }finally{
      state.editBusy=false;updateEditState(state.edit);
      $("move-apply").disabled=true;$("move-preview").disabled=false;
    }
  }
  async function commitDraggedMove(ids,ghost) {
    // Zero dialogs: preview and apply are still separate, revision-guarded
    // server operations. Protect other codes and preserve one undo transaction.
    if(state.editBusy||!state.edit||!ids?.length||!ghost)return;
    const before=editRequestBody();
    const payload={
      ...before,ids:ids.slice(),
      dx:Math.round(ghost.dx*1000)/1000,
      dy:Math.round(ghost.dy*1000)/1000,
      allowDetach:true,
      snapDistance:0
    };
    state.editBusy=true;updateEditState(state.edit);
    try{
      const report=await api("/api/move/preview",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(payload)
      });
      if(report.documentToken!==before.documentToken||
         report.revision!==before.revision)
        throw Error("Mapa zmieniła się podczas przesuwania.");
      if(!report.canApply||report.topologyBlocked)
        throw Error("Nie można wykonać przesunięcia: "+
                    (report.topologyBlocked?"konflikt topologii":"brak zmiany")+".");
      const result=await api("/api/move/apply",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...payload,previewKey:report.previewKey})
      });
      updateEditState(result);
      if(result.changed){
        await refreshEditedDocument(state.active);
        const snap=result.snapApplied?" · przyciągnięto do granicy":
          ghost.snap?" · magnes: "+ghost.snap.kind:"";
        inform("Przesunięto "+display(result.movedObjects)+
          (result.movedObjects===1?" obiekt":" obiektów")+snap+
          ". Cofnij: Ctrl+Z.");
      }
    }catch(error){
      inform("Nie przesunięto obiektów: "+error.message,true);
      scheduleViewport(true);
    }finally{
      state.editBusy=false;
      updateEditState(state.edit);
    }
  }

  function drawMoveGhost(features) {
    if(!state.moveGhost)return;
    const ids=new Set(state.moveGhost.ids);
    ctx.save();
    // Canvas axes: horizontal = GEO-MAP Y, vertical = -GEO-MAP X.
    ctx.translate(state.moveGhost.dy*state.scale,-state.moveGhost.dx*state.scale);
    ctx.setLineDash([7,5]);
    ctx.strokeStyle="#00a3e8";ctx.lineWidth=3;
    for(const feature of features){
      if(!ids.has(feature.id))continue;
      addPath(feature.geometry);ctx.stroke();
    }
    ctx.restore();
  }
  function readOffset(id) {
    const value=$(id).value.trim().replace(",",".");
    if(!value||!Number.isFinite(Number(value)))throw Error("Podaj poprawne X/Y.");
    return Math.round(Number(value)*1000)/1000;
  }
  function objectOperation(which) {
    if(which==="copy")return {
      action:"copy",ids:state.copyIds.slice(),
      dx:readOffset("copy-dx"),dy:readOffset("copy-dy")
    };
    if(which==="create")return {
      action:"create",code:$("create-code").value,
      fields:Object.fromEntries(["a1","a2"].filter(key=>$("create-"+key).value)
        .map(key=>[key.toUpperCase(),$("create-"+key).value])),
      points:state.drawPoints.map(p=>p.slice())
    };
    throw Error("Nieznana operacja.");
  }
  function invalidateObjectPreview(which){
    state.objectPreview=null;
    $(which+"-apply").disabled=true;
    $(which+"-summary").textContent="Sprawdź operację przed zatwierdzeniem.";
  }
  async function quickDuplicate() {
    if(state.editBusy||!state.meta)return;
    const ids=selectedObjectIds();
    if(!ids.length||ids.length>500){
      inform("Wybierz 1–500 poligonów do skopiowania.",true);return;
    }
    const features=ids.map(id=>state.features.find(feature=>feature.id===id));
    if(features.some(x=>!x||!x.closed)){
      inform("Przybliż mapę tak, aby wszystkie zaznaczone poligony były widoczne. "+
             "Albo użyj dokładnego kopiowania przez Ctrl+K.",true);
      return;
    }
    const minY=Math.min(...features.map(f=>f.bbox[0]));
    const maxY=Math.max(...features.map(f=>f.bbox[2]));
    const gap=Math.max(0.15,Math.min(2,14/state.scale));
    const dy=Math.round((maxY-minY+gap)*1000)/1000;
    if(!Number.isFinite(dy)||dy>100000){
      inform("Kopia jest za szeroka, użyj dokładnego kopiowania.",true);return;
    }
    const request={...editRequestBody(),
      operation:{action:"copy",ids,dx:0,dy}};
    state.editBusy=true;updateEditState(state.edit);
    try{
      const report=await api("/api/objects/preview",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(request)
      });
      const result=await api("/api/objects/apply",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...request,previewKey:report.previewKey})
      });
      updateEditState(result);
      const created=result.createdIds||[];
      state.pinned=new Set(created);
      state.active=created[0]||null;
      state.editBusy=false;updateEditState(state.edit);
      setTool("move");
      await refreshEditedDocument(state.active);
      updateSelectionCount();
      inform("Skopiowano "+display(created.length)+
        " poligonów obok oryginału. Tryb M aktywny — przeciągnij je myszą.");
    }catch(error){
      inform("Nie udało się skopiować: "+error.message,true);
    }finally{state.editBusy=false;updateEditState(state.edit);}
  }
  function openCopyEditor() {
    if(state.editBusy||!state.meta)return;
    const ids=selectedObjectIds();
    if(!ids.length||ids.length>500){
      inform("Zaznacz od 1 do 500 poligonów do skopiowania.",true);return;
    }
    state.copyIds=ids;
    $("copy-selection-description").textContent=
      "Wybrano "+display(ids.length)+" obiektów. Każda kopia będzie nowym rekordem MAP.";
    $("copy-dx").value="0,000";$("copy-dy").value="20,000";
    invalidateObjectPreview("copy");
    $("copy-dialog").showModal();$("copy-dy").focus();
  }
  async function previewObject(which) {
    if(state.editBusy)return;
    invalidateObjectPreview(which);
    let operation;
    try{operation=objectOperation(which);}
    catch(err){$(which+"-summary").textContent=err.message;return;}
    const request={...editRequestBody(),operation};
    $(which+"-preview").disabled=true;
    $(which+"-summary").textContent="Sprawdzanie obiektów i mapy…";
    try{
      const report=await api("/api/objects/preview",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(request)
      });
      if(report.documentToken!==state.edit?.documentToken||
         report.revision!==state.edit?.revision)
        throw Error("Zmieniono mapę w trakcie podglądu.");
      const codes=Object.entries(report.codes||{})
        .map(([code,n])=>code+": "+display(n)).join(", ");
      $(which+"-summary").textContent=
        (which==="copy"?"Utworzymy kopie: ":"Utworzymy poligon: ")+
        (which==="copy"?display(report.selected):"1")+
        "\nKody: "+codes+"\nPunkty P: "+display(report.vertexCount)+
        "\nBez zmiany oryginalnych rekordów. Całość można cofnąć Ctrl+Z.";
      state.objectPreview={which,request,report};
      $(which+"-apply").disabled=!report.canApply;
    }catch(error){
      $(which+"-summary").textContent="Błąd walidacji: "+error.message;
      inform(error.message,true);
    }finally{$(which+"-preview").disabled=false;}
  }
  async function quickCreatePolygon(ev){
    ev.preventDefault();
    if(state.editBusy||state.tool!=="draw")return;
    if(state.drawPoints.length<3){
      $("create-summary").textContent="Potrzebne są co najmniej 3 różne węzły.";
      return;
    }
    let request;
    try{request={...editRequestBody(),operation:objectOperation("create")};}
    catch(error){$("create-summary").textContent=error.message;return;}
    state.editBusy=true;updateEditState(state.edit);
    $("create-apply").disabled=true;
    $("create-summary").textContent="Tworzę poligon i sprawdzam topologię…";
    try{
      // Preserve the server-side safety preview+apply transaction. From
      // the user's perspective it is just A1 + Enter, not two clicks.
      const report=await api("/api/objects/preview",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(request)
      });
      if(!report.canApply||!report.previewKey)
        throw Error(report.message||report.reason||"Nieprawidłowy obrys.");
      const result=await api("/api/objects/apply",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...request,previewKey:report.previewKey})
      });
      updateEditState(result);
      $("create-dialog").close();
      state.objectPreview=null;
      state.drawPoints=[];state.drawHover=null;state.drawSnap=null;
      state.pinned.clear();state.active=null;state.detail=null;
      $("create-a1").value="";$("create-a2").value="";
      state.editBusy=false;updateEditState(state.edit);
      // A drawing session continues until the user explicitly presses S,
      // Escape (when no nodes are left), or chooses another tool.
      setTool("draw");
      await refreshEditedDocument(null);
      updateSelectionCount();
      inform("Poligon utworzony. Rysuj następny — tryb N nadal aktywny.");
    }catch(error){
      $("create-summary").textContent="Nie utworzono: "+error.message;
      inform("Błąd tworzenia poligonu: "+error.message,true);
    }finally{
      state.editBusy=false;updateEditState(state.edit);
      $("create-apply").disabled=false;
    }
  }
  async function applyObject(which,ev) {
    if(which==="create")return quickCreatePolygon(ev);
    ev.preventDefault();
    if(state.editBusy||!state.objectPreview||
       state.objectPreview.which!==which)return;
    const seen=state.objectPreview;
    let request;
    try{request={...editRequestBody(),operation:objectOperation(which)};}
    catch(error){invalidateObjectPreview(which);inform(error.message,true);return;}
    if(JSON.stringify(request)!==JSON.stringify(seen.request)){
      invalidateObjectPreview(which);
      inform("Zmodyfikowano dane. Wykonaj podgląd ponownie.",true);return;
    }
    if(which==="copy"&&seen.report.selected>=100&&!window.confirm(
        "Potwierdź utworzenie "+display(seen.report.selected)+" kopii?"))
      return;
    state.editBusy=true;updateEditState(state.edit);
    $(which+"-apply").disabled=true;
    try{
      const result=await api("/api/objects/apply",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...request,previewKey:seen.report.previewKey})
      });
      updateEditState(result);
      $(which+"-dialog").close();
      state.objectPreview=null;
      const newIds=result.createdIds||[];
      state.pinned=new Set(newIds);
      state.active=newIds[0]||null;
      state.drawPoints=[];state.drawHover=null;
      state.editBusy=false;updateEditState(state.edit);
      setTool("select");
      await refreshEditedDocument(state.active);
      updateSelectionCount();
      inform(which==="copy"
        ?"Utworzono "+display(newIds.length)+" kopii. Każda ma nowe ID. Ctrl+Z cofa."
        :"Utworzono poligon. Ctrl+Z cofa; zapisz kopię MAP.");
    }catch(error){
      invalidateObjectPreview(which);
      $(which+"-summary").textContent="Nie zapisano: "+error.message;
      inform("Operacja przerwana: "+error.message,true);
    }finally{
      state.editBusy=false;updateEditState(state.edit);
    }
  }
  async function deleteObjects() {
    if(state.editBusy||!state.meta)return;
    const ids=selectedObjectIds();
    if(!ids.length||ids.length>5000){
      inform("Zaznacz od 1 do 5 000 obiektów do usunięcia.",true);return;
    }
    const request={...editRequestBody(),operation:{action:"delete",ids}};
    state.editBusy=true;updateEditState(state.edit);
    try{
      const report=await api("/api/objects/preview",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(request)
      });
      if(!report.canApply||!report.previewKey)
        throw Error(report.message||"Nie można bezpiecznie usunąć zaznaczenia.");
      const result=await api("/api/objects/apply",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...request,previewKey:report.previewKey})
      });
      updateEditState(result);
      state.pinned.clear();state.active=null;state.detail=null;
      await refreshEditedDocument(null);
      updateSelectionCount();
      inform("Usunięto "+display(report.selected)+
             " obiektów w kopii roboczej. Ctrl+Z przywraca.");
    }catch(error){
      inform("Nie usunięto obiektów: "+error.message,true);
    }finally{state.editBusy=false;updateEditState(state.edit);}
  }
  function finishDrawPolygon() {
    if(state.tool!=="draw"||$("create-dialog").open)return;
    if(state.drawPoints.length<3){
      inform("Poligon wymaga minimum trzech różnych punktów.",true);return;
    }
    $("create-selection-description").textContent=
      "Obrys z "+display(state.drawPoints.length)+
      " węzłów. Wpisz A1 i naciśnij Enter, aby utworzyć poligon.";
    state.objectPreview=null;
    $("create-apply").disabled=false;
    $("create-summary").textContent="Enter — utwórz poligon. "+
      "Sprawdzanie poprawności nastąpi automatycznie.";
    $("create-dialog").showModal();
    $("create-a1").focus({preventScroll:true});
    // WebView2 can autofocus the modal's first toolbar button AFTER it
    // opens. Restore the requested A1 focus on the next paint too.
    requestAnimationFrame(()=>{
      if($("create-dialog").open)$("create-a1").focus({preventScroll:true});
    });
  }
  async function finishGeometryDrawing() {
    if(state.tool==="draw"){finishDrawPolygon();return;}
    if(state.tool==="cut"){
      if(state.drawPoints.length<2){
        inform("Podział wymaga linii przecinającej poligon.",true);return;
      }
      if(state.splitPending||state.editBusy)return;
      state.splitPending=true;
      try{
        await previewGeometryForm("split");
        if(state.geometryPreview?.which==="split"&&state.geometryPreview.report.canApply)
          await applyGeometryForm("split");
      }finally{state.splitPending=false;}
      return;
    }
    if(["line","line-edit"].includes(state.tool)){
      if(state.drawPoints.length<2){
        inform("Linia wymaga przynajmniej dwóch punktów.",true);return;
      }
      const editing=state.tool==="line-edit";
      $("line-dialog-title").textContent=editing?"Edytuj istniejącą linię":"Nowa linia";
      $("line-code").disabled=editing;
      $("line-a1").disabled=editing;
      $("line-a2").disabled=editing;
      $("line-count").textContent=state.drawPoints.length+" węzłów P — "+
        (editing?"zmiana istniejącego obrysu":"nowy obiekt GEO-MAP");
      $("line-apply").textContent=editing?"Zapisz linię":"Utwórz linię";
      $("line-summary").textContent="Sprawdź linię przed zatwierdzeniem.";
      state.geometryPreview=null;$("line-apply").disabled=true;
      $("line-dialog").showModal();
    }
  }
  function startSplit() {
    const ids=selectedObjectIds();
    if(ids.length!==1){
      inform("Najpierw zaznacz dokładnie jeden poligon do podziału.",true);
      return;
    }
    state.cutIds=ids.slice();
    setTool("cut");
    inform("Narysuj linię przez wybrany poligon. Zacznij i zakończ poza jego obrysem. Enter kończy.");
  }
  function startEditLine() {
    const ids=selectedObjectIds();
    if(ids.length!==1){
      inform("Zaznacz dokładnie jedną linię, potem Shift+L.",true);return;
    }
    const feature=state.features.find(f=>f.id===ids[0]);
    if(!feature||feature.closed){
      inform("Zaznacz istniejącą linię 5214 (obręb), 6900 lub innego kodu linii.",true);
      return;
    }
    state.lineEditId=ids[0];
    setTool("line-edit");
    inform("Narysuj nowy przebieg wybranej linii. Enter — sprawdź i zapisz.");
  }
  function operationForGeometry(which) {
    if(which==="split")return {
      action:"split",ids:state.cutIds.slice(),
      points:state.drawPoints.map(p=>p.slice())
    };
    if(which==="line"){
      const points=state.drawPoints.map(p=>p.slice());
      if(state.tool==="line-edit")return {
        action:"edit_line",ids:[state.lineEditId],points
      };
      return {
        action:"create_line",code:$("line-code").value,points,
        fields:Object.fromEntries(["a1","a2"].filter(k=>$("line-"+k).value)
          .map(k=>[k.toUpperCase(),$("line-"+k).value]))
      };
    }
    throw Error("Nieznane polecenie geometrii.");
  }
  async function previewGeometryForm(which) {
    state.geometryPreview=null;
    $(which+"-apply").disabled=true;
    const request={...editRequestBody(),
      operation:operationForGeometry(which)};
    $(which+"-preview").disabled=true;
    $(which+"-summary").textContent="Sprawdzanie topologii i powierzchni…";
    try{
      const report=await api("/api/geometry/preview",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(request)});
      const notes=report.metadataWarning
        ?"\nUWAGA: stare dane powierzchniowe w A4/A6 wymagają sprawdzenia!"
        :"";
      $(which+"-summary").textContent=
        (report.parts?"Liczba części: "+report.parts+"\n":"")+
        (report.beforeArea!==undefined?"Powierzchnia przed: "+
          report.beforeArea+" m², po: "+report.afterArea+" m²\n":"")+
        "Można cofnąć jednym Ctrl+Z."+notes;
      state.geometryPreview={which,report,request};
      $(which+"-apply").disabled=!report.canApply;
    }catch(err){
      $(which+"-summary").textContent="Nie można zastosować: "+err.message;
      inform(err.message,true);
    }finally{$(which+"-preview").disabled=false;}
  }
  async function applyGeometryForm(which,ev) {
    ev?.preventDefault();
    const current=state.geometryPreview;
    if(!current||current.which!==which||state.editBusy)return;
    const request={...editRequestBody(),
      operation:operationForGeometry(which)};
    if(JSON.stringify(current.request)!==JSON.stringify(request)){
      state.geometryPreview=null;$(which+"-apply").disabled=true;
      inform("Obrys został zmieniony. Sprawdź ponownie.",true);return;
    }
    if(which!=="split"&&current.report.metadataWarning&&!window.confirm(
      "Scalenie/podział wymaga ręcznego sprawdzenia danych powierzchniowych "+
      "A4/A6 w GEO-MAP. Czy kontynuować?"))return;
    state.editBusy=true;updateEditState(state.edit);
    try{
      const res=await api("/api/geometry/apply",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...request,previewKey:current.report.previewKey})
      });
      updateEditState(res);
      $(which+"-dialog").close();
      state.geometryPreview=null;
      state.drawPoints=[];state.drawHover=null;
      state.lineEditId=null;state.cutIds=[];
      state.pinned=new Set(res.createdIds||[]);
      state.active=res.createdIds?.[0]||null;
      state.editBusy=false;updateEditState(state.edit);
      setTool("select");
      await refreshEditedDocument(state.active);
      updateSelectionCount();
      inform("Geometria zapisana w kopii roboczej. Ctrl+Z cofa.");
    }catch(error){
      state.geometryPreview=null;
      $(which+"-apply").disabled=true;
      $(which+"-summary").textContent=error.message;
      inform("Nie zapisano geometrii: "+error.message,true);
    }finally{state.editBusy=false;updateEditState(state.edit);}
  }
  async function simpleGeometryAction(action) {
    if(state.editBusy||!state.meta)return;
    const ids=selectedObjectIds();
    if(action==="merge"&&(ids.length<2||ids.length>100)){
      inform("Zaznacz od 2 do 100 poligonów tego samego kodu.",true);return;
    }
    if(action==="repair"&&(!ids.length||ids.length>100)){
      inform("Zaznacz 1–100 poligonów do poprawy kierunku.",true);return;
    }
    const request={...editRequestBody(),operation:{action,ids}};
    state.editBusy=true;updateEditState(state.edit);
    try{
      const report=await api("/api/geometry/preview",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(request)});
      if(!report.canApply){
        inform("Wybrane obrysy już mają prawidłowy kierunek i dodatnią powierzchnię.");
        return;
      }
      const message=action==="repair"
        ?"Odwrócić kolejność punktów w "+report.repairs.length+
          " poligonach, aby w GEO-MAP otrzymać dodatnią powierzchnię?"
        :"Scalić "+display(ids.length)+" poligonów w jeden obiekt GEO-MAP?\n"+
          "Atrybuty wyniku pochodzą z pierwszego poligonu. Liczba wysp: "+
          report.components+", konturów: "+report.rings+".\n"+
          "Suma przed: "+report.beforeArea+" m²; po: "+
          report.afterArea+" m².\n"+
          "UWAGA: dane powierzchniowe A4/A6 trzeba sprawdzić ręcznie.";
      if(!window.confirm(message))return;
      const result=await api("/api/geometry/apply",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...request,previewKey:report.previewKey})
      });
      updateEditState(result);
      state.pinned.clear();state.active=null;
      await refreshEditedDocument(null);
      updateSelectionCount();
      inform(action==="repair"
        ?"Naprawiono kierunek obrysu. GEO-MAP pokaże dodatnią powierzchnię po eksporcie."
        :"Scalono poligony. Sprawdź A4/A6. Ctrl+Z cofa.");
    }catch(error){
      inform("Operacja nieudana: "+error.message,true);
    }finally{state.editBusy=false;updateEditState(state.edit);}
  }
  function mergePolygons(){return simpleGeometryAction("merge");}
  function repairWinding(){return simpleGeometryAction("repair");}
  function toggleDrawMagnet() {
    state.drawMagnet=!state.drawMagnet;
    for(const id of ["tool-draw-snap","float-snap"]){
      const control=$(id);
      control.classList.toggle("active",state.drawMagnet);
      control.setAttribute("aria-pressed",String(state.drawMagnet));
    }
    if(!state.drawMagnet)state.drawSnap=null;
    if(state.drawCursorWorld&&["draw","cut","line","line-edit"].includes(state.tool))
      updateDrawingHover(state.drawCursorWorld,false);
    inform(state.drawMagnet
      ?"Magnes rysowania włączony: 7 px do węzła, 5 px do linii. Alt — bez przyciągania."
      :"Magnes rysowania wyłączony: punkty dokładnie pod kursorem. G — włącz.");
  }
  function drawingSnapAt(world,altPressed=false) {
    const helper=window.GeoStudioDrawingSnap;
    if(!helper||!state.drawMagnet||altPressed)
      return {point:world,kind:null,code:null};
    if(state.tool==="draw"&&state.drawPoints.length>=3){
      const first=state.drawPoints[0];
      const point={x:first[1],y:-first[0]};
      if(Math.hypot(world.x-point.x,world.y-point.y)*state.scale<=10)
        return {point,kind:"start",code:null,targetId:null};
    }
    // Avoid scanning every segment of the entire loaded MAP for every
    // pointermove. A 12px padded bbox contains all 7px vertex / 5px
    // segment snap targets, even at the smallest zoom.
    const pad=12/Math.max(.000001,state.scale);
    const candidates=state.features.filter(f=>isVisible(f)&&
      f.bbox[0]<=world.x+pad&&f.bbox[2]>=world.x-pad&&
      f.bbox[1]<=world.y+pad&&f.bbox[3]>=world.y-pad);
    return helper.snapPoint(world,candidates,{scale:state.scale,
      enabled:true,bypass:altPressed,vertexPixels:7,edgePixels:5});
  }
  function appendDrawingPoint(ev,p){
    if(!state.meta||state.editBusy)return;
    const world=screenToWorld(p.x,p.y);
    const snapped=drawingSnapAt(world,ev.altKey);
    if(state.tool==="draw"&&snapped.kind==="start"&&
       state.drawPoints.length>=3){
      state.drawSnap=null;state.drawHover=null;
      finishDrawPolygon();
      requestDraw();return;
    }
    const next=[Math.round(-snapped.point.y*1000)/1000,
                Math.round(snapped.point.x*1000)/1000];
    const last=state.drawPoints[state.drawPoints.length-1];
    if(!last||Math.hypot(next[0]-last[0],next[1]-last[1])>0.003){
      if(state.drawPoints.length<500)state.drawPoints.push(next);
      else inform("Osiągnięto limit 500 węzłów.",true);
    }
    state.drawSnap=snapped.kind?snapped:null;
    // No blocking toast or deferred pointerup: a vertex appears on the
    // same mouse-down frame and rapid click sequences are not dropped.
    $("status-message").textContent="Rysowanie: "+
      state.drawPoints.length+" punktów · Enter albo pierwszy punkt kończy.";
    requestDraw();
  }
  function updateDrawingHover(world,altPressed=false) {
    state.drawCursorWorld=world;
    const target=drawingSnapAt(world,altPressed);
    state.drawHover={x:-target.point.y,y:target.point.x};
    state.drawSnap=target.kind?target:null;
    requestDraw();
    return target;
  }
  function drawMagnetMarker() {
    if(!state.drawSnap||!["draw","cut","line","line-edit"].includes(state.tool))
      return;
    const p=worldToScreen(state.drawSnap.point.x,state.drawSnap.point.y);
    ctx.save();
    ctx.strokeStyle="#048f8a";ctx.lineWidth=2;
    ctx.beginPath();ctx.arc(p.x,p.y,7.5,0,Math.PI*2);ctx.stroke();
    ctx.beginPath();ctx.moveTo(p.x-11,p.y);ctx.lineTo(p.x+11,p.y);
    ctx.moveTo(p.x,p.y-11);ctx.lineTo(p.x,p.y+11);ctx.stroke();
    const label=(state.drawSnap.kind==="start"?"DOMKNIJ POLIGON":
      state.drawSnap.kind==="węzeł"?"WĘZEŁ":"LINIA")+
      (state.drawSnap.code?" · "+state.drawSnap.code:"");
    ctx.font="600 10px Segoe UI, sans-serif";
    const width=Math.min(160,ctx.measureText(label).width+12);
    const left=Math.max(5,Math.min(state.width-width-5,p.x+13));
    const top=Math.max(5,Math.min(state.height-23,p.y-29));
    ctx.fillStyle="rgba(11,88,84,.94)";ctx.fillRect(left,top,width,19);
    ctx.fillStyle="#ffffff";ctx.fillText(label,left+6,top+13);
    ctx.restore();
  }
  function drawDraftPolygon() {
    if(!["draw","cut","line","line-edit"].includes(state.tool)||
       !state.drawPoints.length)return;
    const points=state.drawPoints.map(p=>[p[1],-p[0]]);
    if(state.drawHover)points.push([state.drawHover.y,-state.drawHover.x]);
    ctx.save();
    ctx.strokeStyle="#0398cb";ctx.lineWidth=2.5;
    ctx.setLineDash([5,4]);
    addPath([points]);ctx.stroke();
    ctx.setLineDash([]);
    for(const p of state.drawPoints) {
      const screen=worldToScreen(p[1],-p[0]);
      ctx.beginPath();ctx.arc(screen.x,screen.y,4,0,Math.PI*2);
      ctx.fillStyle="#f49f41";ctx.fill();
      ctx.strokeStyle="#ffffff";ctx.stroke();
    }
    ctx.restore();
  }
  function magneticMove(ids,rawDx,rawDy) {
    if(!$("opt-snap")?.checked)return null;
    const group=new Set(ids);
    const moving=state.features.filter(f=>group.has(f.id));
    const fixed=state.features.filter(f=>!group.has(f.id)&&isVisible(f));
    if(!moving.length||!fixed.length)return null;
    const threshold=12/Math.max(.000001,state.scale);
    let best=null,movingCount=0,edgeCount=0;
    for(const obj of moving){
      for(const part of obj.geometry){
        for(const vertex of part){
          if(++movingCount>900)return best;
          const origin=[vertex[0]+rawDy,vertex[1]-rawDx];
          for(const target of fixed){
            if(origin[0]<target.bbox[0]-threshold||
               origin[0]>target.bbox[2]+threshold||
               origin[1]<target.bbox[1]-threshold||
               origin[1]>target.bbox[3]+threshold)continue;
            for(const track of target.geometry){
              for(let i=0;i<track.length;i++){
                if(++edgeCount>35000)return best;
                const a=track[i],b=track[i+1]||(target.closed?track[0]:a);
                const u=b[0]-a[0],v=b[1]-a[1];
                const div=u*u+v*v;
                const t=div?Math.max(0,Math.min(1,(
                  (origin[0]-a[0])*u+(origin[1]-a[1])*v)/div)):0;
                for(const [candidate,kind,rank] of [
                  [a,"węzeł",0],[div?[a[0]+u*t,a[1]+v*t]:a,"krawędź",1]]){
                  const dist=Math.hypot(candidate[0]-origin[0],
                                        candidate[1]-origin[1]);
                  if(dist>threshold)continue;
                  // Prefer a matching vertex over an edge at comparable distance.
                  const score=dist+rank*Math.min(threshold*.18,.025);
                  if(best===null||score<best.score){
                    best={dx:Math.round((rawDx+origin[1]-candidate[1])*1000)/1000,
                          dy:Math.round((rawDy+candidate[0]-origin[0])*1000)/1000,
                          point:candidate,kind,score,dist};
                  }
                }
              }
            }
          }
        }
      }
    }
    return best;
  }
  function drawMoveMagnet() {
    const snap=state.moveGhost?.snap;
    if(!snap)return;
    const p=worldToScreen(snap.point[0],snap.point[1]);
    ctx.save();
    ctx.lineWidth=2;ctx.strokeStyle="#dc8500";
    ctx.beginPath();ctx.arc(p.x,p.y,8,0,2*Math.PI);ctx.stroke();
    ctx.beginPath();ctx.moveTo(p.x-12,p.y);ctx.lineTo(p.x+12,p.y);
    ctx.moveTo(p.x,p.y-12);ctx.lineTo(p.x,p.y+12);ctx.stroke();
    ctx.font="600 11px Segoe UI";
    ctx.fillStyle="#c66b00";
    ctx.fillText("MAGNES: "+snap.kind,p.x+15,p.y-12);
    ctx.restore();
  }
  function updateUnderlayStatus(message) {
    $("underlay-summary").textContent=message;
    const rasterReady=[...raster.layers,...(raster.image?[rasterEntry()]:[])]
      .some(item=>rasterCanShow(item));
    const active=[];
    if(underlay.enabled)active.push("WMS · EPSG:"+underlay.epsg);
    if(rasterReady)active.push("Raster lokalny");
    $("underlay-chip").textContent=active.join(" + ")||"Bez podkładu";
  }
  function removeUnderlay(){
    underlay.ticket++;
    clearTimeout(underlay.timer);
    if(underlay.abort)underlay.abort.abort();
    underlay.abort=null;underlay.enabled=false;underlay.loading=false;
    underlay.image=null;underlay.bounds=null;underlay.layer="";
    underlay.epsg=null;
    if($("underlay-summary"))updateUnderlayStatus("Podkład usunięty. MAP pozostaje niezmieniony.");
    renderRasterLayers();
    if(state.meta){state.previewActive=false;state.geometrySnapshotValid=false;requestDraw();}
  }
  async function loadUnderlayLayers(){
    const preset=$("underlay-preset").value;
    const options=$("underlay-layer");
    options.replaceChildren(new Option("Wczytywanie warstw Geoportalu…",""));
    $("underlay-summary").textContent="Pobieranie listy warstw WMS…";
    try{
      const response=await api("/api/underlay/wms/layers?preset="+encodeURIComponent(preset));
      if($("underlay-preset").value!==preset)return;
      options.replaceChildren();
      for(const entry of response.layers){
        const choice=new Option(entry.title+" ("+entry.id+")",entry.id);
        choice.dataset.epsg=entry.epsg.join(",");
        options.add(choice);
      }
      if(!options.options.length)throw Error("Brak warstw obsługujących polskie EPSG.");
      $("underlay-summary").textContent=
        "Wybierz rzeczywisty EPSG otwartej MAP, a następnie włącz podkład.";
    }catch(error){
      if($("underlay-preset").value!==preset)return;
      options.replaceChildren(new Option("Nie udało się pobrać warstw",""));
      $("underlay-summary").textContent=error.message;
      inform("Błąd WMS: "+error.message,true);
    }
  }
  async function readUnderlayPrj(file){
    if(!file||!state.meta)return;
    const documentToken=state.edit?.documentToken;
    try{
      const response=await documentFetch("/api/underlay/crs/prj",{
        method:"POST",headers:{"X-GeoStudio-Token":token,
          "Content-Type":"application/octet-stream"},
        cache:"no-store",body:file
      });
      if(!response.ok){
        const err=await response.json().catch(()=>({}));
        throw Error(err.detail||"Nie można zweryfikować pliku PRJ.");
      }
      const result=await response.json();
      // A slow file read must not set the CRS of a newly opened MAP.
      if(documentToken!==state.edit?.documentToken)return;
      setMapEPSG(String(result.epsg));
      $("underlay-crs-result").textContent=
        "Zweryfikowano układ z PRJ: EPSG:"+result.epsg+
        ". Zastosuj go tylko do odpowiadającego mu pliku MAP.";
    }catch(error){
      $("underlay-crs-result").textContent="PRJ: "+error.message;
      inform(error.message,true);
    }
  }
  async function convertUnderlayCenter(){
    if(!state.meta)return;
    const source=Number($("underlay-epsg").value);
    const target=Number($("underlay-crs-target").value);
    if(![2180,2176,2177,2178,2179].includes(source)){
      inform("Wybierz najpierw prawdziwy EPSG mapy.",true);return;
    }
    const params=new URLSearchParams({
      x:String(-state.center.y),y:String(state.center.x),
      source:String(source),target:String(target)
    });
    try{
      const result=await api("/api/underlay/crs/point?"+params);
      $("underlay-crs-result").textContent=
        "Środek: EPSG:"+source+" X="+(-state.center.y).toFixed(3)+
        " Y="+state.center.x.toFixed(3)+" → EPSG:"+target+
        " X="+result.x.toFixed(3)+" Y="+result.y.toFixed(3)+
        ". Tylko podgląd, MAP bez zmian.";
    }catch(error){
      $("underlay-crs-result").textContent="Nie udało się przeliczyć: "+error.message;
    }
  }
  function probablePolishCRS(bounds){
    // Canvas bounds are [west, -north, east, -south] in native metres.
    if(!bounds || bounds.length!==4 || !bounds.every(Number.isFinite))return "";
    const [west,top,east,bottom]=bounds;
    const north=-top,south=-bottom;
    if(west>east || south>north)return "";
    if(south>=5400000 && north<=6150000){
      const zone=Math.floor(west/1000000);
      if(zone>=5 && zone<=8 && west>=zone*1000000+350000 && east<=zone*1000000+650000)
        return String(2171+zone);
    }
    if(west>=100000 && east<=900000 && south>=100000 && north<=850000)return "2180";
    return "";
  }
  function setMapEPSG(value){
    // Each dialog changes the SAME per-map CRS; never reuse the EPSG of
    // a different MAP. All calibrated backgrounds must match its axes.
    const chosen=String(value||"");
    if(!["","2180","2176","2177","2178","2179"].includes(chosen))return;
    const changed=chosen!==state.mapEPSG;
    state.mapEPSG=chosen;
    for(const id of ["underlay-epsg","raster-epsg","crs-epsg"])
      $(id).value=chosen;
    const displayed=chosen||probablePolishCRS(state.meta?.bounds);
    const option=Array.from($("crs-epsg").options).find(entry=>entry.value===displayed);
    const status=$("status-map-crs");
    status.textContent=displayed && option ? "Układ: "+option.textContent+(chosen?"":" (prawdopodobny)") : "Układ nieustalony";
    status.title=chosen?"Układ ustawiony dla tej mapy.":"Ocena na podstawie zakresu współrzędnych całej mapy. Układ możesz potwierdzić w Podkłady → Układy EPSG.";
    if(!changed)return;
    // A visually calibrated JPG/PNG or a .world raster is positioned in
    // native MAP X/Y. Choosing an EPSG for WMS does not change these XY
    // values, and must not make the already aligned picture disappear.
    // GeoTIFF carrying its own EPSG is shown only if CRS really matches.
    for(const item of [...(raster.layers||[]),raster]){
      if(!item.image||!item.affine)continue;
      if(!item.epsg||Number(chosen)===item.epsg)
        item.boundEPSG=chosen;
    }
    if(underlay.enabled)removeUnderlay();
    if(raster.image||raster.layers.length)
      rasterInfo("Zaktualizowano EPSG bieżącej mapy. Rastry z wizualną "+
        "kalibracją XY pozostają widoczne; GeoTIFF wymaga zgodnego EPSG.");
    state.previewActive=false;state.geometrySnapshotValid=false;requestDraw();
  }
  const wmsPresetUrls={
    standard:"https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolution",
    high:"https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolution",
    kieg:"https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow"
  };
  function showWmsPresetAddress(){
    $("underlay-url").value=wmsPresetUrls[$("underlay-preset").value]||"";
  }
  function openUnderlayDialog(){
    if(!state.meta){inform("Najpierw otwórz mapę MAP.");return;}
    showWmsPresetAddress();
    $("underlay-dialog").showModal();
    if($("underlay-layer").options.length<=1)loadUnderlayLayers();
  }
  function openRasterDialog(){
    if(!state.meta){inform("Najpierw otwórz mapę MAP.");return;}
    $("raster-dialog").showModal();
  }
  async function transformActiveMap(){
    if(state.editBusy||!state.meta)return;
    const source=Number($("crs-epsg").value),target=Number($("underlay-crs-target").value);
    const message=$("underlay-crs-result");
    if(!source||source===target){
      message.textContent="Wskaż układ źródłowy otwartej mapy oraz inny układ docelowy.";
      return;
    }
    const button=$("crs-transform-map");
    button.disabled=true;state.editBusy=true;
    message.textContent="Przeliczanie współrzędnych całej mapy…";
    try{
      const response=await documentFetch("/api/map/reproject",{method:"POST",
        headers:{"Content-Type":"application/json","X-GeoStudio-Token":token},
        body:JSON.stringify({...editRequestBody(),source,target})});
      if(!response.ok)throw Error((await response.json()).detail||"Nie udało się przeliczyć mapy.");
      if(documentId){
        const {id}=await response.json();
        host().openConverted(id);
        message.textContent="Przeliczoną mapę otwarto w nowej zakładce.";
      }else{
        const url=URL.createObjectURL(await response.blob());
        const link=document.createElement("a");
        link.href=url;link.download=state.meta.name.replace(/\.map$/i,"")+"_EPSG"+target+".zip";
        document.body.append(link);link.click();link.remove();
        setTimeout(()=>URL.revokeObjectURL(url),60000);
        message.textContent="Przygotowano kopię MAP z plikiem PRJ.";
      }
      $("crs-dialog").close();
    }catch(error){message.textContent=error.message;}
    finally{state.editBusy=false;button.disabled=false;notifyHost();}
  }
  function openCrsDialog(){
    if(!state.meta){inform("Najpierw otwórz mapę MAP.");return;}
    $("crs-dialog").showModal();
  }
  function activateRibbonTab(id,focus=false){
    const tab=$("ribbon-tab-"+id),panel=$("ribbon-panel-"+id);
    if(!tab||!panel)return;
    document.querySelectorAll("[data-ribbon-tab]").forEach(item=>{
      const active=item===tab;
      item.classList.toggle("active",active);
      item.setAttribute("aria-selected",String(active));
      item.tabIndex=active?0:-1;
    });
    document.querySelectorAll("[data-ribbon-panel]").forEach(item=>{
      item.hidden=item!==panel;
      item.classList.toggle("active",item===panel);
    });
    pendingSheet=null;sheetDrag=null;requestDraw();
    if(focus)tab.focus({preventScroll:true});
  }
  function setupRibbon(){
    const tabs=[...document.querySelectorAll("[data-ribbon-tab]")];
    for(const tab of tabs){
      tab.addEventListener("click",()=>activateRibbonTab(tab.dataset.ribbonTab));
      tab.addEventListener("keydown",event=>{
        if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key))return;
        event.preventDefault();
        const index=tabs.indexOf(tab);
        const next=event.key==="Home"?0:event.key==="End"?tabs.length-1:
          (index+(event.key==="ArrowRight"?1:-1)+tabs.length)%tabs.length;
        activateRibbonTab(tabs[next].dataset.ribbonTab,true);
      });
    }
  }
  function underlayRequestDimensions(bounds){
    // WMS must be requested at screen/HiDPI resolution rather than
    // stretching a single low-resolution bitmap through successive zooms.
    const aspect=(bounds[2]-bounds[0])/(bounds[3]-bounds[1]);
    const dpr=Math.max(1,Math.min(2,state.pixelRatio||1));
    let width=Math.max(128,Math.min(2048,Math.round(state.width*dpr*1.20)));
    let height=Math.round(width/aspect);
    if(height>2048){height=2048;width=Math.round(height*aspect);}
    // Server allows at most three million pixels; preserve aspect ratio.
    if(width*height>2950000){
      const ratio=Math.sqrt(2950000/(width*height));
      width=Math.floor(width*ratio);height=Math.floor(height*ratio);
    }
    return {width:Math.max(128,Math.min(2048,width)),
            height:Math.max(128,Math.min(2048,height))};
  }
  function scheduleUnderlayRefresh(immediate=false){
    if(!underlay.enabled||!state.meta||!underlay.visible)return;
    // A zoom changes the desired BBOX: invalidate any old request now,
    // not after a later debounced request has started.
    underlay.ticket++;
    if(underlay.abort){underlay.abort.abort();underlay.abort=null;}
    clearTimeout(underlay.timer);
    underlay.loading=true;
    underlay.timer=setTimeout(refreshUnderlay,immediate?0:115);
  }
  async function refreshUnderlay(){
    if(!underlay.enabled||!state.meta)return;
    const id=++underlay.ticket;
    if(underlay.abort)underlay.abort.abort();
    const controller=new AbortController();underlay.abort=controller;
    const bounds=boundsFromViewport(.09);
    const size=underlayRequestDimensions(bounds);
    const params=new URLSearchParams({
      preset:underlay.preset,layer:underlay.layer,epsg:String(underlay.epsg),
      xmin:String(bounds[0]),ymin:String(bounds[1]),
      xmax:String(bounds[2]),ymax:String(bounds[3]),
      width:String(size.width),height:String(size.height)
    });
    const documentToken=state.edit?.documentToken;
    try{
      const response=await documentFetch("/api/underlay/wms/map?"+params,{
        headers:{"X-GeoStudio-Token":token},cache:"no-store",signal:controller.signal
      });
      if(!response.ok){
        const err=await response.json().catch(()=>({}));
        throw Error(err.detail||"Geoportal nie zwrócił obrazu.");
      }
      const blob=await response.blob();
      const url=URL.createObjectURL(blob);
      let image;
      try{
        image=await new Promise((resolve,reject)=>{
          const bitmap=new Image();
          bitmap.onload=()=>resolve(bitmap);
          bitmap.onerror=()=>reject(Error("Nie można odczytać obrazu Geoportalu."));
          bitmap.src=url;
        });
      }finally{URL.revokeObjectURL(url);}
      if(!underlay.enabled||id!==underlay.ticket||
         documentToken!==state.edit?.documentToken)return;
      underlay.image=image;underlay.bounds=bounds;underlay.loading=false;
      requestDraw();renderRasterLayers();
      updateUnderlayStatus("WMS ostry dla aktualnego kadru.");
    }catch(error){
      if(error.name==="AbortError"||id!==underlay.ticket)return;
      // Existing WMS stays visible until a new image arrives.
      underlay.loading=false;
      updateUnderlayStatus("WMS nie został odświeżony: "+error.message);
      renderRasterLayers();
    }finally{
      if(underlay.abort===controller)underlay.abort=null;
    }
  }
  function applyUnderlay(){
    if(!state.meta){inform("Najpierw otwórz mapę.");return;}
    const epsg=Number($("underlay-epsg").value);
    const option=$("underlay-layer").selectedOptions[0];
    const layer=option?.value||"";
    const supported=(option?.dataset.epsg||"").split(",");
    if(![2180,2176,2177,2178,2179].includes(epsg)||
       !supported.includes(String(epsg))||!layer){
      inform("Wybierz układ EPSG, który jest zgodny z MAP i warstwą WMS.",true);
      return;
    }
    // No automatic CRS guessing: user explicitly chooses it per MAP.
    underlay.enabled=true;
    underlay.preset=$("underlay-preset").value;
    underlay.layer=layer;underlay.epsg=epsg;
    underlay.image=null;underlay.bounds=null;underlay.visible=true;
    updateUnderlayStatus("Pobieranie obrazu dla EPSG:"+epsg+"…");
    renderRasterLayers();
    scheduleUnderlayRefresh(true);
  }
  function paintUnderlay(){
    if(!underlay.enabled||!underlay.visible||!underlay.image||!underlay.bounds)return;
    const bounds=underlay.bounds;
    const top=worldToScreen(bounds[0],bounds[1]);
    const bottom=worldToScreen(bounds[2],bounds[3]);
    ctx.save();ctx.globalAlpha=underlay.opacity;
    ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality="high";
    ctx.drawImage(underlay.image,top.x,top.y,
                  bottom.x-top.x,bottom.y-top.y);
    ctx.restore();
  }
  function rasterInfo(message){
    const summary=$("raster-summary");
    summary.hidden=false;
    delete summary.dataset.result;
    summary.textContent=message;
    updateUnderlayStatus($("underlay-summary").textContent);
    renderRasterLayers();
  }
  let calibrationWrites=Promise.resolve();
  function rememberCalibration(points){
    const item=rasterEntry(), mapToken=state.edit.documentToken;
    const settings={name:item.name,gcps:points,opacity:item.opacity,digest:item.digest};
    const save=async()=>{
      const json=new TextEncoder().encode(JSON.stringify(settings));
      const header=new ArrayBuffer(4);
      new DataView(header).setUint32(0,json.length);
      const post=file=>api("/api/underlay/calibrations",{method:"POST",
        headers:{"X-Map-Token":mapToken},body:new Blob(file?[header,json,file]:[header,json])});
      if((await post(null)).needsImage){
        if(!item.file)throw Error("Dodaj plik rastra ponownie.");
        await post(item.file);
      }
    };
    calibrationWrites=calibrationWrites.then(save).catch(error=>{
      if(state.edit?.documentToken===mapToken)inform("Kalibracja działa w widoku, ale zapis nie powiódł się: "+error.message,true);
    });
  }
  async function restoreCalibrations(){
    const mapToken=state.edit?.documentToken;
    const headers={"X-Map-Token":mapToken,"X-GeoStudio-Token":token};
    try{
      const records=await api("/api/underlay/calibrations",{headers});
      for(const record of records){
        if(state.edit?.documentToken!==mapToken)return;
        const response=await documentFetch("/api/underlay/calibrations/"+record.digest,{headers});
        if(!response.ok)throw Error("Nie można odczytać "+record.name);
        const image=await imageFromBlob(await response.blob());
        if(state.edit?.documentToken!==mapToken)return;
        const existing=[raster,...raster.layers].find(item=>item.digest===record.digest);
        if(existing?.affine)continue;
        const entry={...record,image,id:++raster.serial,epsg:null,boundEPSG:state.mapEPSG,
          sourceWidth:Number(response.headers.get("X-Raster-Source-Width")),
          sourceHeight:Number(response.headers.get("X-Raster-Source-Height")),
          file:null,visible:true,pendingWorld:null};
        if(existing)Object.assign(existing,{affine:entry.affine,gcps:entry.gcps,boundEPSG:entry.boundEPSG,epsg:null});
        else if(raster.image)raster.layers.push(entry);else assignRaster(entry);
        state.geometrySnapshotValid=false;state.previewActive=false;
        rasterInfo("Przywrócono skalibrowany raster: "+record.name);requestDraw();
      }
    }catch(error){
      if(state.edit?.documentToken===mapToken)inform("Odtworzenie rastra: "+error.message,true);
    }
  }
  function rasterEntry(){
    return {id:raster.id,image:raster.image,affine:raster.affine,file:raster.file,digest:raster.digest,
      epsg:raster.epsg,boundEPSG:raster.boundEPSG,
      opacity:raster.opacity,visible:raster.visible,
      name:raster.name,pendingWorld:raster.pendingWorld,
      sourceWidth:raster.sourceWidth,sourceHeight:raster.sourceHeight,
      gcps:raster.gcps};
  }
  function assignRaster(entry){
    for(const field of ["id","image","affine","epsg","boundEPSG",
      "opacity","visible","name","pendingWorld","gcps","file","digest",
      "sourceWidth","sourceHeight"])
      raster[field]=entry[field];
    $("raster-opacity").value=Math.round(raster.opacity*100);
    $("raster-opacity-value").textContent=Math.round(raster.opacity*100)+"%";
  }
  function selectRasterLayer(id){
    if(id===raster.id)return;
    if(gcpView.open)closeVisualCalibration();
    const index=raster.layers.findIndex(item=>item.id===id);
    if(index<0)return;
    raster.ticket++;
    const selected=raster.layers.splice(index,1)[0];
    if(raster.image)raster.layers.push(rasterEntry());
    assignRaster(selected);
    renderRasterLayers();
  }
  function removeRaster(all=false){
    if(gcpView.open)closeVisualCalibration();
    raster.ticket++;
    if(all)raster.layers=[];
    if(!all&&raster.layers.length)assignRaster(raster.layers.pop());
    else assignRaster({id:0,image:null,affine:null,epsg:null,
      boundEPSG:null,opacity:.72,visible:true,name:"",
      sourceWidth:0,sourceHeight:0,
      pendingWorld:null,gcps:[]});
    if($("raster-summary"))rasterInfo("Raster usunięty. MAP pozostaje bez zmian.");
    if(state.meta){state.previewActive=false;state.geometrySnapshotValid=false;requestDraw();}
  }
  function rasterCanShow(item){
    if(!item.image||!item.affine||!item.visible)return false;
    if(item.boundEPSG!==state.mapEPSG)return false;
    return !item.epsg||item.epsg===Number(state.mapEPSG);
  }
  let activeTrace=null;
  function startRasterTracing(){
    if(activeTrace){activeTrace.close();return;}
    const picker=$("trace-raster-choice");
    const entries=[rasterEntry(),...raster.layers].filter(rasterCanShow);
    const entry=entries.find(e=>String(e.id)===picker.value)||entries[0];
    if(!entry){inform("Dodaj i skalibruj widoczny raster, aby wkreślać 5310.",true);return;}
    if(state.editBusy)return;
    const token=state.edit.documentToken;
    let revision=state.edit.revision;
    setTool("select",true);
    activeTrace=openRasterTracing(entry,{
      shell, token, worldToScreen, screenToWorld, zoomAt,
      scale:()=>state.scale,
      panBy(dx,dy){
        state.center={x:state.center.x-dx/state.scale,y:state.center.y-dy/state.scale};
        requestDraw();scheduleViewport();
      },
      fit(bounds){
        const [x,y,u,v]=bounds;
        state.center={x:(x+u)/2,y:(y+v)/2};
        state.scale=Math.max(.000001,Math.min(3500,.92*state.width/(u-x),.92*state.height/(v-y)));
        requestDraw();scheduleViewport(true);
      },
      closed(){
        activeTrace=null;$("tool-trace-5310").classList.remove("active");
        $("tool-trace-5310").setAttribute("aria-pressed","false");
        canvas.focus({preventScroll:true});requestDraw();
      },
      async featuresIn(bounds){
        const features=[];
        await forEachExportPage(bounds,batch=>features.push(...batch));
        return features;
      },
      magnetEnabled:()=>state.drawMagnet,
      toggleMagnet:toggleDrawMagnet,
      isVisible,
      fitOutline:points=>api("/api/underlay/raster/fit",{method:"POST",
        headers:{"Content-Type":"application/json"},body:JSON.stringify({documentToken:token,revision,points})}),
      async add(points,a1,fitted){
        if(state.editBusy||state.edit.documentToken!==token||state.edit.revision!==revision)
          throw Error("Mapa została zmieniona. Otwórz wykrywanie ponownie.");
        const body={documentToken:token,revision,operation:{action:"create",code:"5310",clipRasterOverlap:true,fields:a1?{A1:a1}:{},points}};
        const post=(path,data)=>api(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
        state.editBusy=true;
        try{
          const preview=await post("/api/objects/preview",body);
          if(preview.adjustedPoints && JSON.stringify(preview.adjustedPoints)!==JSON.stringify(fitted))throw Error("Granica wymaga ponownego dopasowania. Wybierz fragment ponownie.");
          const result=await post("/api/objects/apply",{...body,previewKey:preview.previewKey});
          revision=result.revision;updateEditState(result);
        }finally{state.editBusy=false;updateEditState(state.edit);}
      },
      refresh:()=>refreshEditedDocument(null)
    });
    $("tool-trace-5310").classList.add("active");
    $("tool-trace-5310").setAttribute("aria-pressed","true");
  }
  function renderRasterLayers(){
    const picker=$("trace-raster-choice"),previous=picker.value;
    const choices=[rasterEntry(),...raster.layers].filter(rasterCanShow);
    picker.replaceChildren(...choices.map(e=>new Option(e.name,String(e.id))));
    if(choices.some(e=>String(e.id)===previous))picker.value=previous;
    picker.hidden=choices.length<2;
    const list=$("raster-layers-list");
    if(!list)return;
    list.replaceChildren();
    const items=[];
    if(underlay.enabled)items.push({kind:"wms",id:"wms",
      title:"WMS: "+($("underlay-preset").selectedOptions[0]?.textContent||"Geoportal"),
      visible:underlay.visible,opacity:underlay.opacity,
      status:underlay.loading?"Odświeżanie obrazu…":underlay.image?"Połączono":"Ładowanie…"});
    for(const item of [...raster.layers,...(raster.image?[rasterEntry()]:[])])
      items.push({kind:"raster",id:item.id,title:item.name,
        visible:item.visible,opacity:item.opacity,
        status:item.affine?"Pozycjonowany":"Wymaga kalibracji"});
    $("raster-layer-count").textContent=String(items.length);
    if(!items.length){
      const empty=document.createElement("div");empty.className="panel-placeholder";
      empty.textContent="Brak podkładów. Dodaj WMS lub raster z zakładki Podkłady.";
      list.append(empty);return;
    }
    for(const item of items){
      const root=document.createElement("div");root.className="raster-layer-item";
      const head=document.createElement("div");head.className="raster-layer-head";
      const checkbox=document.createElement("input");checkbox.type="checkbox";
      checkbox.checked=item.visible;checkbox.setAttribute("aria-label","Widoczność "+item.title);
      checkbox.addEventListener("change",()=>{
        if(item.kind==="wms"){
          underlay.visible=checkbox.checked;
          if(underlay.visible)scheduleUnderlayRefresh(true);
          else{underlay.ticket++;clearTimeout(underlay.timer);if(underlay.abort)underlay.abort.abort();}
        }else {
          const target=item.id===raster.id?raster:raster.layers.find(x=>x.id===item.id);
          if(target)target.visible=checkbox.checked;
        }
        requestDraw();renderRasterLayers();
      });
      const info=document.createElement("div");info.className="raster-layer-meta";
      const title=document.createElement("strong");title.textContent=item.title;title.title=item.title;
      const status=document.createElement("span");status.textContent=item.status;
      info.append(title,status);
      head.append(checkbox,info);root.append(head);
      const slider=document.createElement("input");slider.type="range";
      slider.min="0";slider.max="100";slider.step="5";
      slider.value=String(Math.round(item.opacity*100));
      slider.setAttribute("aria-label","Krycie "+item.title);
      slider.addEventListener("input",()=>{
        const value=Number(slider.value)/100;
        if(item.kind==="wms"){
          underlay.opacity=value;
          $("underlay-opacity").value=slider.value;
          $("underlay-opacity-value").textContent=slider.value+"%";
        }else {
          const target=item.id===raster.id?raster:raster.layers.find(x=>x.id===item.id);
          if(target)target.opacity=value;
          if(item.id===raster.id){
            $("raster-opacity").value=slider.value;
            $("raster-opacity-value").textContent=slider.value+"%";
          }
        }
        requestDraw();
      });
      root.append(slider);
      const actions=document.createElement("div");actions.className="raster-layer-actions";
      if(item.kind==="raster"){
        const activate=document.createElement("button");activate.textContent="Kalibruj";
        activate.type="button";activate.addEventListener("click",()=>{
          selectRasterLayer(item.id);openVisualCalibration();
        });actions.append(activate);


      }
      const remove=document.createElement("button");remove.textContent="Usuń";remove.type="button";
      remove.addEventListener("click",()=>{
        if(item.kind==="wms")removeUnderlay();
        else if(item.id===raster.id)removeRaster();
        else{
          raster.layers=raster.layers.filter(x=>x.id!==item.id);
          renderRasterLayers();requestDraw();
        }
      });
      actions.append(remove);root.append(actions);list.append(root);
    }
  }
  function parseWorldFileText(source){
    const rows=source.trim().split(/\r?\n/);
    if(rows.length!==6)throw Error("Plik world musi zawierać 6 wierszy.");
    const values=rows.map(row=>Number(row.trim()));
    if(values.some(v=>!Number.isFinite(v)))throw Error("Nieprawidłowe liczby w pliku world.");
    const [A,D,B,E,C,F]=values;
    if(Math.abs(A*E-B*D)<1e-12)throw Error("Nieprawidłowa transformacja world.");
    // Standard ESRI world: east, north at pixel CENTER.
    // Browser: GeoStudio X=north, Y=east at pixel CORNER.
    return [D,E,F-(D+E)/2,A,B,C-(A+B)/2];
  }
  function rasterGeoValid(){
    // JPG/PNG with visually paired GCPs need no chosen EPSG: both
    // clicked points use the SAME native GEO-MAP coordinate space.
    if(!raster.epsg)return true;
    const epsg=Number(state.mapEPSG);
    if(raster.epsg!==epsg){
      rasterInfo("GeoTIFF: EPSG:"+raster.epsg+
        ". Automatyczna georeferencja wymaga potwierdzonego EPSG mapy; "+
        "alternatywnie użyj wizualnych punktów GCP.");
      return false;
    }
    return true;
  }
  function showRasterIfCalibrated(){
    if(!rasterGeoValid())return;
    if(!raster.image||!raster.affine)return;
    raster.boundEPSG=state.mapEPSG;
    state.previewActive=false;state.geometrySnapshotValid=false;
    requestDraw();
    rasterInfo(raster.name+" — podkład dopasowany do współrzędnych MAP.");
  }
  async function imageFromBlob(blob){
    const url=URL.createObjectURL(blob);
    try{
      return await new Promise((resolve,reject)=>{
        const image=new Image();
        image.onload=()=>resolve(image);
        image.onerror=()=>reject(Error("Nie można odczytać obrazu rastra."));
        image.src=url;
      });
    }finally{URL.revokeObjectURL(url);}
  }
  function reportRasterPlacement(source,warning=""){
    const ready=rasterCanShow(raster);
    const crsMismatch=raster.epsg && raster.epsg!==Number(state.mapEPSG);
    const title=ready?"Raster skalibrowany":crsMismatch?"Sprawdź układ współrzędnych":"Raster wymaga kalibracji";
    const detail=ready?source:crsMismatch
      ?"Wybierz EPSG:"+raster.epsg+" dla mapy lub skalibruj raster wizualnie."
      :"Wybierz „Kalibruj wizualnie” lub wczytaj plik world.";
    rasterInfo([title+" · "+raster.name,detail,warning].filter(Boolean).join(" "));
    const summary=$("raster-summary"),heading=document.createElement("strong");
    heading.className="raster-result-heading";
    heading.textContent=title;
    const description=document.createElement("span");
    description.textContent=[raster.name,detail,warning].filter(Boolean).join(" · ");
    summary.replaceChildren(heading,description);
    summary.dataset.result=ready?"ready":"attention";
    inform(title+" · "+raster.name,Boolean(warning));
  }
  async function openRasterFile(file,world=null,warning=""){
    if(!file||!state.meta)return;
    const ticket=++raster.ticket;
    const documentToken=state.edit?.documentToken;
    if(file.size>48*1024*1024){
      inform("Raster przekracza limit 48 MB.",true);return;
    }
    rasterInfo("Wczytywanie rastra "+file.name+"…");
    try{
      const lower=file.name.toLowerCase();
      // Local decoder creates a bounded preview for all supported image
      // formats and reports ORIGINAL dimensions for GCP and world files.
      if(!/\.(tiff?|png|jpe?g|webp)$/i.test(lower))
        throw Error("Obsługiwane obrazy: PNG, JPG, WebP i TIFF.");
      const response=await documentFetch("/api/underlay/raster/prepare",{
        method:"POST",headers:{"X-GeoStudio-Token":token,
          "Content-Type":"application/octet-stream"},
        body:file,cache:"no-store"
      });
      if(!response.ok){
        const body=await response.json().catch(()=>({}));
        throw Error(body.detail||"Nie można odczytać rastra.");
      }
      const affine=JSON.parse(response.headers.get("x-raster-affine")||"null");
      const epsg=Number(response.headers.get("x-raster-epsg")||0)||null;
      const sourceWidth=Number(response.headers.get("x-raster-source-width")||0);
      const sourceHeight=Number(response.headers.get("x-raster-source-height")||0);
      const decoded=await imageFromBlob(await response.blob());
      const digest=response.headers.get('X-Raster-Digest');
      if(!sourceWidth||!sourceHeight)
        throw Error("Serwer nie podał oryginalnych wymiarów rastra.");
      if(ticket!==raster.ticket||documentToken!==state.edit?.documentToken)return;
      const existing=[raster,...raster.layers].find(item=>digest && item.digest===digest && item.affine);
      if(existing){
        selectRasterLayer(existing.id);raster.file=file;raster.visible=true;
        reportRasterPlacement("Użyto zapisanego dopasowania do tej mapy.");requestDraw();return;
      }
      let worldAffine=raster.image?null:raster.pendingWorld;
      if(world){
        try{worldAffine=parseWorldFileText(world.text);}
        catch(error){warning=world.name+" — "+error.message;}
      }
      if(raster.image)raster.layers.push(rasterEntry());
      raster.pendingWorld=null;
      raster.image=decoded;raster.affine=affine;raster.epsg=epsg;
      raster.sourceWidth=sourceWidth;raster.sourceHeight=sourceHeight;
      raster.boundEPSG=null;raster.gcps=[];raster.visible=true;
      raster.opacity=.72;raster.id=++raster.serial;
      raster.name=file.name;raster.file=file;raster.digest=digest;
      if(worldAffine)raster.affine=worldAffine;
      if(raster.affine)showRasterIfCalibrated();
      const source=worldAffine
        ?(world?"Wczytano "+world.name+".":"Użyto wskazanego pliku world.")
        :"Odczytano współrzędne z pliku rastra.";
      reportRasterPlacement(source,warning);
    }catch(error){
      rasterInfo("Nie udało się otworzyć rastra: "+error.message);
      inform("Błąd rastra: "+error.message,true);
    }
  }
  async function openWorldFile(file){
    if(!file)return;
    try{
      const coeff=parseWorldFileText(await file.text());
      raster.pendingWorld=coeff;
      if(raster.image){
        raster.affine=coeff;
        raster.pendingWorld=null;
        showRasterIfCalibrated();
        reportRasterPlacement("Wczytano "+file.name+".");
      }else{
        rasterInfo("Wczytano world. Wybierz teraz obraz rastra.");
      }
    }catch(error){rasterInfo("World: "+error.message);inform(error.message,true);}
  }
  // Non-modal visual calibration follows the classic Qt workflow:
  // raster pixel click -> matching map click -> 3+ pairs -> affine RMSE.
  const gcpView={waiting:false,pending:null,zoom:1,panX:0,panY:0,
    dragging:null,mapDragging:null,consumeMapUp:null,activeIndex:null,
    fitSerial:0,recalibrationActive:false,open:false};
  function gcpCanvasLayout(){
    const canvas=$("raster-gcp-canvas");
    const w=Math.max(250,canvas.clientWidth||450);
    const h=Math.max(160,canvas.clientHeight||270);
    const img=raster.image;
    if(!img)return {w,h,scale:1,left:0,top:0};
    const scale=Math.min(w/img.width,h/img.height)*gcpView.zoom;
    return {w,h,scale,
      left:(w-img.width*scale)/2+gcpView.panX,
      top:(h-img.height*scale)/2+gcpView.panY};
  }
  // Zoom at cursor: the same raster pixel must remain exactly under
  // the wheel pointer before and after changing the image scale.
  function zoomGcpAt(x,y,deltaY,deltaMode=0){
    if(!raster.image)return;
    const before=gcpCanvasLayout();
    const u=(x-before.left)/before.scale;
    const v=(y-before.top)/before.scale;
    const normalized=deltaY*(deltaMode===1?16:deltaMode===2?before.h:1);
    const next=Math.max(.4,Math.min(35,
      gcpView.zoom*Math.exp(-normalized*.0025)));
    if(next===gcpView.zoom)return;
    gcpView.zoom=next;
    const after=gcpCanvasLayout();
    gcpView.panX+=x-(after.left+u*after.scale);
    gcpView.panY+=y-(after.top+v*after.scale);
    drawGcpCanvas();
  }
  function gcpScreenToSource(x,y){
    const p=gcpCanvasLayout(),img=raster.image;
    return {u:(x-p.left)/p.scale*(raster.sourceWidth||img.width)/img.width,
            v:(y-p.top)/p.scale*(raster.sourceHeight||img.height)/img.height};
  }
  function gcpSourceToScreen(pt){
    const p=gcpCanvasLayout(),img=raster.image;
    return {x:p.left+pt.u*p.scale*img.width/(raster.sourceWidth||img.width),
            y:p.top+pt.v*p.scale*img.height/(raster.sourceHeight||img.height)};
  }
  function gcpNearestRasterPoint(x,y){
    let index=-1,best=12*12;
    raster.gcps.forEach((point,i)=>{
      const pos=gcpSourceToScreen(point);
      const d=(pos.x-x)**2+(pos.y-y)**2;
      if(d<=best){best=d;index=i;}
    });
    return index;
  }
  function gcpNearestMapPoint(x,y){
    let index=-1,best=13*13;
    raster.gcps.forEach((point,i)=>{
      const pos=worldToScreen(point.y,-point.x);
      const d=(pos.x-x)**2+(pos.y-y)**2;
      if(d<=best){best=d;index=i;}
    });
    return index;
  }
  function drawGcpCanvas(){
    if(!raster.image)return;
    const canvas=$("raster-gcp-canvas");
    const pos=gcpCanvasLayout();
    const dpr=Math.max(1,Math.min(2,window.devicePixelRatio||1));
    const w=Math.round(pos.w*dpr),h=Math.round(pos.h*dpr);
    if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
    const g=canvas.getContext("2d");
    g.setTransform(dpr,0,0,dpr,0,0);
    g.clearRect(0,0,pos.w,pos.h);
    g.fillStyle="#102538";g.fillRect(0,0,pos.w,pos.h);
    g.imageSmoothingEnabled=true;g.imageSmoothingQuality="high";
    g.drawImage(raster.image,pos.left,pos.top,
      raster.image.width*pos.scale,raster.image.height*pos.scale);
    const markers=raster.gcps.map((pt,i)=>({u:pt.u,v:pt.v,
      label:String(i+1),color:i===gcpView.activeIndex?"#ffbc57":"#54ead8"}));
    if(gcpView.pending)markers.push({...gcpView.pending,label:"+",color:"#ffbc57"});
    for(const item of markers){
      const x=pos.left+item.u*pos.scale*raster.image.width/
          (raster.sourceWidth||raster.image.width);
      const y=pos.top+item.v*pos.scale*raster.image.height/
          (raster.sourceHeight||raster.image.height);
      g.beginPath();g.arc(x,y,6,0,Math.PI*2);g.fillStyle=item.color;g.fill();
      g.strokeStyle="#092335";g.lineWidth=2;g.stroke();
      g.font="bold 13px sans-serif";g.fillStyle="#fff";g.fillText(item.label,x+9,y-7);
    }
  }
  function updateGcpUi(message){
    $("raster-gcp-cancel").disabled=!gcpView.pending;
    $("raster-gcp-apply").disabled=raster.gcps.length<3;
    $("raster-gcp-undo").disabled=!raster.gcps.length;
    $("raster-visual-status").textContent=message||
      (gcpView.waiting?"Teraz kliknij odpowiednik na mapie lub zmień punkt na obrazie.":
      raster.gcps.length+" par. Kliknij kolejny punkt na obrazie.");
    const list=$("raster-gcp-pairs");list.replaceChildren();
    for(const [i,pt] of raster.gcps.entries()){
      const item=document.createElement("button");item.type="button";
      item.className="gcp-pair-tag";
      item.classList.toggle("selected",i===gcpView.activeIndex);
      item.title="Przeciągnij punkt na rastrze lub mapie";
      item.addEventListener("click",()=>{
        gcpView.activeIndex=i;gcpView.pending=null;gcpView.waiting=false;
        updateGcpUi("Przeciągnij zaznaczony punkt "+(i+1)+" na obrazie lub mapie.");
      });
      item.textContent=(i+1)+". raster "+
        Math.round(pt.u)+","+Math.round(pt.v)+" ↔ mapa "+
        pt.x.toFixed(2)+","+pt.y.toFixed(2);
      list.append(item);
    }
    drawGcpCanvas();requestDraw();
  }
  function openVisualCalibration(){
    if(!raster.image){inform("Najpierw dodaj obraz rastra.",true);return;}
    if($("raster-dialog").open)$("raster-dialog").close();
    gcpView.open=true;gcpView.waiting=false;gcpView.pending=null;
    gcpView.recalibrationActive=!!raster.affine;
    gcpView.activeIndex=null;gcpView.dragging=null;gcpView.mapDragging=null;
    gcpView.zoom=1;gcpView.panX=0;gcpView.panY=0;
    // show(), not showModal(): the MAP behind the window must receive
    // the second click without closing the calibration workspace.
    if(!$("raster-visual-dialog").open)$("raster-visual-dialog").show();
    updateGcpUi(raster.gcps.length+" par. Wskaż punkt charakterystyczny na obrazie.");
  }
  function closeVisualCalibration(){
    gcpView.waiting=false;gcpView.pending=null;gcpView.open=false;
    gcpView.activeIndex=null;gcpView.mapDragging=null;gcpView.dragging=null;
    gcpView.consumeMapUp=null;gcpView.fitSerial++;
    canvas.style.cursor="";
    $("raster-gcp-canvas").style.cursor="crosshair";
    if($("raster-visual-dialog").open)$("raster-visual-dialog").close();
    requestDraw();
  }
  function gcpMapPoint(ev){
    const p=eventCoords(ev),world=screenToWorld(p.x,p.y);
    return {x:-world.y,y:world.x};
  }
  function pickGcpMapPoint(ev){
    if(!gcpView.open||ev.button!==0||!raster.image)return;
    const p=eventCoords(ev),index=gcpNearestMapPoint(p.x,p.y);
    if(index<0&&(!gcpView.waiting||!gcpView.pending))return;
    ev.preventDefault();ev.stopImmediatePropagation();
    gcpView.consumeMapUp=ev.pointerId;
    if(index>=0){
      gcpView.mapDragging={pointer:ev.pointerId,index,moved:false};
      gcpView.activeIndex=index;
      gcpView.pending=null;gcpView.waiting=false;
      canvas.setPointerCapture?.(ev.pointerId);
      updateGcpUi("Przeciągnij punkt "+(index+1)+" po mapie.");
      return;
    }
    raster.gcps.push({...gcpView.pending,...gcpMapPoint(ev)});
    gcpView.activeIndex=raster.gcps.length-1;
    gcpView.waiting=false;gcpView.pending=null;gcpView.fitSerial++;
    updateGcpUi("Dodano parę "+raster.gcps.length+
      ". Kliknij kolejny punkt na obrazie.");
    renderRasterLayers();
  }
  function moveGcpMapPoint(ev){
    const drag=gcpView.mapDragging;
    if(!drag){
      if(gcpView.open&&raster.image){
        const p=eventCoords(ev);
        const close=gcpNearestMapPoint(p.x,p.y)>=0;
        canvas.style.cursor=close?"grab":gcpView.waiting?"crosshair":"";
      }
      return;
    }
    if(drag.pointer!==ev.pointerId)return;
    ev.preventDefault();ev.stopImmediatePropagation();
    if(!raster.gcps[drag.index])return;
    Object.assign(raster.gcps[drag.index],gcpMapPoint(ev));
    drag.moved=true;gcpView.fitSerial++;
    updateGcpUi("Przesuwasz punkt "+(drag.index+1)+" na mapie.");
  }
  function releaseGcpMapPoint(ev){
    const drag=gcpView.mapDragging;
    if(!drag&&gcpView.consumeMapUp!==ev.pointerId)return;
    if(drag&&drag.pointer!==ev.pointerId)return;
    ev.preventDefault();ev.stopImmediatePropagation();
    if(canvas.hasPointerCapture?.(ev.pointerId))
      canvas.releasePointerCapture(ev.pointerId);
    gcpView.mapDragging=null;gcpView.consumeMapUp=null;
    if(drag?.moved)finishGcpAdjustment();
  }
  async function applyVisualGCP(keepOpen=false){
    if(!raster.image||raster.gcps.length<3){
      inform("Do kalibracji potrzebne są minimum trzy pary punktów.",true);return;
    }
    const ticket=raster.ticket,documentToken=state.edit?.documentToken;
    const imageId=raster.id,serial=++gcpView.fitSerial,
      points=raster.gcps.map(item=>({...item}));
    try{
      const result=await api("/api/underlay/gcp",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({points})
      });
      if(serial!==gcpView.fitSerial||ticket!==raster.ticket||
         imageId!==raster.id||documentToken!==state.edit?.documentToken)return;
      raster.affine=result.coefficients;
      gcpView.recalibrationActive=true;
      raster.epsg=null; // visual GCP calibrates against native MAP XY.
      raster.boundEPSG=state.mapEPSG;
      raster.visible=true;raster.pendingWorld=null;
      rememberCalibration(points);
      rasterInfo("Wizualne GCP: "+result.count+" par, RMSE "+
        result.rmse.toFixed(3)+" m. Sprawdź położenie na innych punktach.");
      if(keepOpen)
        updateGcpUi("Zaktualizowano dopasowanie: RMSE "+
          result.rmse.toFixed(3)+" m. Możesz dalej przesuwać punkty.");
      else closeVisualCalibration();
      requestDraw();
    }catch(error){
      if(serial===gcpView.fitSerial)
        updateGcpUi("Kalibracja nie powiodła się: "+error.message+
          ". Sprawdź rozmieszczenie punktów.");
    }
  }
  function finishGcpAdjustment(){
    gcpView.fitSerial++;
    if(raster.gcps.length>=3&&
       (raster.affine||gcpView.recalibrationActive)){
      gcpView.recalibrationActive=true;
      // Never show the old geographic positioning after moving a GCP:
      // keep the raster hidden until the new affine is verified.
      raster.affine=null;
      updateGcpUi("Aktualizuję transformację po przesunięciu punktu…");
      applyVisualGCP(true);
    }else if(raster.gcps.length<3&&raster.affine){
      raster.affine=null;
      rasterInfo("Za mało par GCP. Raster wymaga ponownej kalibracji.");
      updateGcpUi("Potrzebne są co najmniej 3 pary GCP.");
    }else updateGcpUi("Punkt poprawiony. Po dodaniu 3 par oblicz dopasowanie.");
  }
  function setupVisualCalibration(){
    const canvas=$("raster-gcp-canvas");
    canvas.addEventListener("pointerdown",ev=>{
      if(ev.button===2||ev.button===1){
        ev.preventDefault();canvas.setPointerCapture?.(ev.pointerId);
        gcpView.dragging={kind:"pan",id:ev.pointerId,x:ev.clientX,y:ev.clientY};
        return;
      }
      if(ev.button!==0||!raster.image)return;
      const rect=canvas.getBoundingClientRect();
      const x=ev.clientX-rect.left,y=ev.clientY-rect.top;
      const index=gcpNearestRasterPoint(x,y);
      if(index>=0){
        canvas.setPointerCapture?.(ev.pointerId);
        gcpView.dragging={kind:"point",id:ev.pointerId,index,moved:false};
        gcpView.activeIndex=index;
        gcpView.pending=null;gcpView.waiting=false;
        updateGcpUi("Chwycono punkt "+(index+1)+". Przeciągnij go po obrazie.");
        return;
      }
      const point=gcpScreenToSource(x,y);
      const sw=raster.sourceWidth||raster.image.width;
      const sh=raster.sourceHeight||raster.image.height;
      if(point.u<0||point.v<0||point.u>sw||point.v>sh)return;
      // Each image click immediately requests the matching map point.
      // Clicking another image position replaces the pending coordinate.
      gcpView.pending=point;gcpView.waiting=true;gcpView.activeIndex=null;
      updateGcpUi("Teraz kliknij ten sam punkt na mapie. "+
        "Możesz zmienić jego pozycję kolejnym kliknięciem obrazu.");
    });
    canvas.addEventListener("pointermove",ev=>{
      const drag=gcpView.dragging;
      if(!drag){
        const rect=canvas.getBoundingClientRect();
        canvas.style.cursor=gcpNearestRasterPoint(
          ev.clientX-rect.left,ev.clientY-rect.top)>=0?"grab":"crosshair";
        return;
      }
      if(drag.id!==ev.pointerId)return;
      if(drag.kind==="pan"){
        gcpView.panX+=ev.clientX-drag.x;
        gcpView.panY+=ev.clientY-drag.y;
        drag.x=ev.clientX;drag.y=ev.clientY;
        drawGcpCanvas();return;
      }
      if(drag.kind==="point"&&raster.gcps[drag.index]){
        const rect=canvas.getBoundingClientRect();
        const point=gcpScreenToSource(ev.clientX-rect.left,ev.clientY-rect.top);
        const sw=raster.sourceWidth||raster.image.width;
        const sh=raster.sourceHeight||raster.image.height;
        raster.gcps[drag.index].u=Math.max(0,Math.min(sw,point.u));
        raster.gcps[drag.index].v=Math.max(0,Math.min(sh,point.v));
        drag.moved=true;gcpView.fitSerial++;
        updateGcpUi("Przesuwasz punkt "+(drag.index+1)+" na obrazie.");
      }
    });
    function finishImageDrag(ev){
      const drag=gcpView.dragging;
      if(!drag||drag.id!==ev.pointerId)return;
      if(canvas.hasPointerCapture?.(ev.pointerId))
        canvas.releasePointerCapture(ev.pointerId);
      gcpView.dragging=null;
      if(drag.kind==="point"&&drag.moved)finishGcpAdjustment();
    }
    canvas.addEventListener("pointerup",finishImageDrag);
    canvas.addEventListener("pointercancel",finishImageDrag);
    canvas.addEventListener("contextmenu",ev=>ev.preventDefault());
    canvas.addEventListener("wheel",ev=>{
      ev.preventDefault();
      const rect=canvas.getBoundingClientRect();
      zoomGcpAt(ev.clientX-rect.left,ev.clientY-rect.top,
        ev.deltaY,ev.deltaMode);
    },{passive:false});
    link("raster-gcp-cancel",()=>{
      gcpView.pending=null;gcpView.waiting=false;
      updateGcpUi("Anulowano oczekujący punkt. Kliknij nowy na obrazie.");
    });
    link("raster-gcp-undo",()=>{
      raster.gcps.pop();gcpView.waiting=false;gcpView.pending=null;
      gcpView.activeIndex=null;finishGcpAdjustment();
    });
    link("raster-gcp-apply",()=>applyVisualGCP(false));
    link("raster-gcp-fit",()=>{
      gcpView.zoom=1;gcpView.panX=0;gcpView.panY=0;drawGcpCanvas();
    });
    link("raster-visual-close",closeVisualCalibration);
    // Intercept markers before standard select/node/pan handlers.
    canvasMapGcpEvents();
  }
  function canvasMapGcpEvents(){
    const map=$("map-canvas");
    map.addEventListener("pointerdown",pickGcpMapPoint,true);
    map.addEventListener("pointermove",moveGcpMapPoint,true);
    map.addEventListener("pointerup",releaseGcpMapPoint,true);
    map.addEventListener("pointercancel",releaseGcpMapPoint,true);
  }
  function drawGcpMapMarkers(){
    if(!gcpView.open||!raster.gcps?.length)return;
    ctx.save();
    for(const [index,pt] of raster.gcps.entries()){
      const p=worldToScreen(pt.y,-pt.x);
      if(p.x<0||p.y<0||p.x>state.width||p.y>state.height)continue;
      ctx.beginPath();ctx.arc(p.x,p.y,8,0,Math.PI*2);
      ctx.fillStyle=index===gcpView.activeIndex?"#ffbc57":"#00b9a3";
      ctx.fill();
      ctx.lineWidth=2;ctx.strokeStyle="#fff";ctx.stroke();
      ctx.fillStyle="#17465b";ctx.font="bold 13px Arial";
      ctx.fillText(String(index+1),p.x+9,p.y-7);
    }
    ctx.restore();
  }
  function paintRaster(){
    for(const item of [...raster.layers,...(raster.image?[rasterEntry()]:[])]){
      if(!rasterCanShow(item))continue;
      const [a,b,c,d,e,f]=item.affine;
      const sourceX=(item.sourceWidth||item.image.width)/item.image.width;
      const sourceY=(item.sourceHeight||item.image.height)/item.image.height;
      ctx.save();ctx.globalAlpha=item.opacity;
      ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality="high";
      ctx.transform(d*sourceX*state.scale,-a*sourceX*state.scale,
        e*sourceY*state.scale,-b*sourceY*state.scale,
        (f-state.center.x)*state.scale+state.width/2,
        (-c-state.center.y)*state.scale+state.height/2);
      ctx.drawImage(item.image,0,0);
      ctx.restore();
    }
  }
  function resizeCanvas() {
    const rect = shell.getBoundingClientRect();
    state.width = Math.max(1, rect.width); state.height = Math.max(1, rect.height);
    state.pixelRatio = Math.min(2, window.devicePixelRatio || 1);
    const w = Math.round(state.width * state.pixelRatio);
    const h = Math.round(state.height * state.pixelRatio);
    if (canvas.width !== w || canvas.height !== h ||
        labelCanvas.width !== w || labelCanvas.height !== h) {
      canvas.width=w;canvas.height=h;
      labelCanvas.width=w;labelCanvas.height=h;
      state.previewActive=false;state.previewCamera=null;
      state.geometrySnapshotValid=false;
    }
    requestDraw();
    scheduleUnderlayRefresh();
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
  // Same logical-DPI convention as the classic Qt scale selector.
  // This is an APPROXIMATE screen scale, never a claimed source EPSG.
  const cssPixelsPerGroundMetre=96/.0254;
  function scaleDenominator(value,min,max) {
    const raw=String(value||"").replace(/\s/g,"").replace(",",".");
    const parts=raw.split(":");
    if(parts.length>2)return null;
    const n=Number(parts.at(-1));
    return Number.isFinite(n)&&n>=min&&n<=max?n:null;
  }
  function updateScaleReadout() {
    const den=Math.round(cssPixelsPerGroundMetre/state.scale);
    if(Number.isFinite(den)&&den>0&&den<=1e9&&
       document.activeElement!==$("view-scale"))
      $("view-scale").value="1:"+den;
    $("scale-label").textContent="Podgląd: "+
       state.scale.toFixed(state.scale<1?3:1)+" px / jedn.";
  }
  function applyViewScale() {
    if(!state.meta)return;
    const den=scaleDenominator($("view-scale").value,10,10000000);
    if(!den){inform("Skala widoku: wpisz 1:N (10–10000000).",true);return;}
    const next=cssPixelsPerGroundMetre/den;
    if(!(next>1e-6&&next<=3500)){
      inform("Ta skala widoku przekracza zakres GeoStudio.",true);return;
    }
    zoomAt(next/state.scale,state.width/2,state.height/2);
    inform("Przybliżona skala ekranu: 1:"+den+
      ". Współrzędne X/Y i MAP nie zostały zmienione.");
  }
  async function applyCompilationScale() {
    if(!state.meta||state.editBusy)return;
    const den=scaleDenominator($("compilation-scale").value,100,1000000);
    if(!den||!Number.isInteger(den)){
      inform("Skala opracowania musi być 1:N, N od 100 do 1000000.",true);
      return;
    }
    state.editBusy=true;updateEditState(state.edit);
    try{
      const status=await api("/api/compilation-scale",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...editRequestBody(),denominator:den})
      });
      updateEditState(status);
      requestDraw();
      inform("Skala opracowania ustawiona na 1:"+den+
        ". Opisy zmieniają rozmiar; geometria MAP pozostaje bez zmian.");
    }catch(err){
      inform("Nie zmieniono skali opracowania: "+err.message,true);
    }finally{state.editBusy=false;updateEditState(state.edit);}
  }
  let labelConfigFields={},labelConfigTicket=0;
  function fillLabelSettingsForm(){
    const field=$("label-settings-field").value;
    const code=$("label-settings-code").value.trim();
    const spec=labelConfigFields[field]||{};
    const isBuilding=code==="5310";
    $("label-settings-visible").checked=spec.visible!==false;
    $("label-settings-size").value=spec.size||
      (isBuilding?16:code==="5216"?12:11);
    $("label-settings-color").value=spec.color||
      (isBuilding?"#CC202C":code==="5230"||code==="5220"?"#35753A":"#58686F");
    $("label-settings-bold").checked=spec.bold===undefined?isBuilding:!!spec.bold;
  }
  async function refreshLabelSettingsForm(){
    const code=$("label-settings-code").value.trim();
    if(!/^[0-9]{4}$/.test(code)){
      $("label-settings-summary").textContent="Wybierz czterocyfrowy kod.";
      return;
    }
    const ticket=++labelConfigTicket;
    try{
      const data=await api("/api/labels/settings?code="+encodeURIComponent(code));
      if(ticket!==labelConfigTicket)return;
      labelConfigFields=data.fields||{};
      fillLabelSettingsForm();
      $("label-settings-summary").textContent=
        "Zapisz, aby zmienić osobno wybrany opis kodu "+code+
        ". Ctrl+Z cofa konfigurację.";
    }catch(err){
      $("label-settings-summary").textContent="Nie odczytano ustawień: "+err.message;
    }
  }
  function openLabelSettings(){
    if(!state.meta)return;
    const selectedFeature=state.features.find(x=>x.id===state.labelSelected?.fid);
    $("label-settings-code").value=state.detail?.code||
       selectedFeature?.code||"5310";
    $("label-settings-field").value=["A1","A2","TX"].includes(
       state.labelSelected?.field)?state.labelSelected.field:"A1";
    $("label-settings-dialog").showModal();
    refreshLabelSettingsForm();
  }
  async function saveLabelSettings(ev){
    ev.preventDefault();
    if(state.editBusy)return;
    const code=$("label-settings-code").value.trim();
    const field=$("label-settings-field").value;
    const properties={
      visible:$("label-settings-visible").checked,
      size:Number($("label-settings-size").value),
      color:$("label-settings-color").value,
      bold:$("label-settings-bold").checked
    };
    state.editBusy=true;updateEditState(state.edit);
    try{
      const status=await api("/api/labels/settings",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...editRequestBody(),code,field,properties})
      });
      updateEditState(status);
      $("label-settings-dialog").close();
      await refreshViewport();
      inform("Zmieniono "+field+" dla kodu "+code+
        ". A1 i A2 pozostają osobnymi opisami. Ctrl+Z cofa.");
    }catch(err){
      $("label-settings-summary").textContent="Błąd zapisu: "+err.message;
      inform("Nie zapisano stylu opisów: "+err.message,true);
    }finally{state.editBusy=false;updateEditState(state.edit);}
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
  function setTool(tool,quiet=false) {
    if(state.editBusy)return;
    if(activeTrace&&!activeTrace.close())return;
    state.tool=tool;
    state.hoverInsert=null;
    if(tool!=="nodes")state.selectedVertex=null;
    if(tool!=="labels")state.labelSelected=null;
    updateDeleteNodeButton();
    shell.classList.toggle("panning",tool==="pan");
    shell.classList.toggle("nodes-editing",tool==="nodes");
    shell.classList.toggle("moving-objects",tool==="move");
    shell.classList.toggle("drawing-objects",tool==="draw");
    shell.classList.toggle("labels-editing",tool==="labels");
    if(!["draw","cut","line","line-edit"].includes(tool)){
      state.drawPoints=[];state.drawHover=null;
      state.drawSnap=null;state.drawCursorWorld=null;
    }
    $("geometry-help").hidden=tool!=="nodes"||!state.meta;
    updateGeometryHelp();
    for(const [name,id] of [
      ["select","tool-select"],["pan","tool-pan"],["nodes","tool-nodes"],
      ["move","tool-move"],["draw","tool-new-polygon"],
      ["labels","tool-label-move"],
      ["cut","tool-split"],["line","tool-line"],
      ["select","float-select"],["pan","float-pan"],["nodes","float-nodes"],
      ["move","float-move"],["draw","float-draw"],["line","float-line"]
    ])$(id).classList.toggle("active",name===tool||
      (name==="line"&&tool==="line-edit"));
    if(tool==="nodes"&&(!state.detail||!state.detail.closed))
      inform("Tryb P: wybierz zamknięty poligon i przeciągnij jego węzeł.");
    else if(tool==="nodes")
      inform("Tryb P: przeciągnij jeden z węzłów. Ctrl+Z cofa zmianę.");
    else if(["draw","cut","line","line-edit"].includes(tool))
      inform("Klikaj punkty; Enter/dwuklik kończy. Magnes G: "+
        (state.drawMagnet?"włączony":"wyłączony")+
        "; Alt stawia punkt obok linii bez przyciągania.");
    else if(tool==="labels")
      inform("Tryb opisów: przeciągnij osobno A1, A2 lub TX. Esc — zaznaczanie; Ctrl+Z — cofnij.");
    else if(tool==="move")
      inform("Tryb M: przeciągnij punkt, linię, poligon albo całą grupę. Cofnij: Ctrl+Z.");
    else if(!quiet)inform(tool==="select"
      ?"Tryb S: zaznacz obiekt lewym przyciskiem, przesuń etykietę prawym.":"Tryb przesuwania mapy (H).");
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
  const APPEARANCE_KEY="geostudio-appearance-v1";
  const validMapColor=value=>/^#[0-9a-fA-F]{6}$/.test(value);
  let appearanceWriteTimer=null,appearanceRevision=0;
  function persistAppearance(){
    appearanceRevision++;
    const preference={
      theme:state.appTheme,mapBackground:state.mapBackground
    };
    try{
      window.localStorage.setItem(APPEARANCE_KEY,JSON.stringify(preference));
    }catch(_error){ /* Preferences are optional in restricted WebView2. */ }
    // Desktop uses a different local origin each time. Write to the
    // persistent GeoStudio2 preferences.json through the authenticated
    // local API so theme and canvas color survive restarts.
    clearTimeout(appearanceWriteTimer);
    appearanceWriteTimer=setTimeout(()=>{
      api("/api/appearance",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(preference)
      }).catch(()=>{ /* Canvas and theme still work without disk access. */ });
    },160);
  }
  function applyAppearance(){
    document.body.dataset.theme=state.appTheme;
    document.body.classList.remove("dark-map");
    document.documentElement.style.setProperty("--main-bg",state.mapBackground);
    const themeButton=$("btn-theme");
    // Keep the SVG icons mounted; CSS displays the appropriate one.
    themeButton.title=state.appTheme==="dark"
      ?"Włącz jasny motyw programu":"Włącz ciemny motyw programu";
    themeButton.setAttribute("aria-label",themeButton.title);
    themeButton.setAttribute("aria-pressed",String(state.appTheme==="dark"));
    $("map-background-color").value=state.mapBackground;
    $("map-background-value").textContent=state.mapBackground.toUpperCase();
    document.querySelector('meta[name="theme-color"]').content=
      state.appTheme==="dark"?"#111d2d":"#f6f8fb";
    notifyHost();
    requestDraw();
  }
  async function restoreAppearance(){
    try{
      const saved=JSON.parse(window.localStorage.getItem(APPEARANCE_KEY)||"null");
      if(saved?.theme==="light"||saved?.theme==="dark")
        state.appTheme=saved.theme;
      if(validMapColor(saved?.mapBackground))
        state.mapBackground=saved.mapBackground.toUpperCase();
    }catch(_error){ /* Unsupported or malformed local preference. */ }
    applyAppearance();
    const version=appearanceRevision;
    try{
      const stored=await api("/api/appearance");
      // A user's newer click takes precedence over a slow initial GET.
      if(appearanceRevision!==version)return;
      if(stored.theme==="light"||stored.theme==="dark")
        state.appTheme=stored.theme;
      if(validMapColor(stored.mapBackground))
        state.mapBackground=stored.mapBackground.toUpperCase();
      applyAppearance();
    }catch(_error){ /* Local browser preference remains the fallback. */ }
  }
  function toggleTheme(){
    state.appTheme=state.appTheme==="dark"?"light":"dark";
    applyAppearance();
    persistAppearance();
  }
  function changeMapBackground(value){
    if(!validMapColor(value))return;
    state.mapBackground=value.toUpperCase();
    applyAppearance();
    persistAppearance();
  }

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
           !(feature.grade && state.hiddenGrades.has(feature.grade)) &&
           !(feature.layer==="Użytki" &&
             state.hiddenLandUses.has(feature.landUse||""));
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
  const hatchCache=new Map();
  function hatchPattern(style) {
    if(!style.hatch)return style.fill;
    const exportRatio=typeof state!=="undefined"&&state.exporting&&state.exportDpi===600?2:1;
    const key=style.fill+"|"+style.hatch+"|"+exportRatio;
    if(hatchCache.has(key))return hatchCache.get(key);
    // The old Qt renderer uses 8x8 QBrush patterns:
    // 1=Qt.Dense4 (50%), 2=Qt.Dense5 (37.5%), 3–8 directional hatches.
    // Match the grid density/orientation without guessing vendor IDs >8.
    const size=8*exportRatio;
    const tile=document.createElement("canvas");
    tile.width=tile.height=size;
    const g=tile.getContext("2d");
    // Preserve the 8x8 cartographic motif while giving 600 DPI exports
    // twice as many physical pixels per hatch stroke.
    if(exportRatio!==1)g.setTransform(exportRatio,0,0,exportRatio,0,0);
    g.clearRect(0,0,8,8);
    g.strokeStyle=style.fill;g.fillStyle=style.fill;g.lineWidth=1;
    const segment=(x1,y1,x2,y2)=>{
      g.beginPath();g.moveTo(x1,y1);g.lineTo(x2,y2);g.stroke();
    };
    if(style.hatch===1||style.hatch===2){
      const threshold=style.hatch===1?8:6;
      const bayer=[
        [0,8,2,10],[12,4,14,6],[3,11,1,9],[15,7,13,5]
      ];
      for(let y=0;y<8;y++)for(let x=0;x<8;x++)
        if(bayer[y%4][x%4]<threshold)g.fillRect(x,y,1,1);
    }else switch(style.hatch){
      case 3: segment(0,4,8,4); break;
      case 4: segment(4,0,4,8); break;
      case 5: segment(0,4,8,4);segment(4,0,4,8); break;
      case 6:
        for(const d of [-8,0,8])segment(d,0,d+8,8);
        break;
      case 7:
        for(const d of [0,8,16])segment(d,0,d-8,8);
        break;
      case 8:
        for(const d of [-8,0,8])segment(d,0,d+8,8);
        for(const d of [0,8,16])segment(d,0,d-8,8);
        break;
      default:
        return style.fill;
    }
    const pattern=ctx.createPattern(tile,"repeat")||style.fill;
    if(hatchCache.size>128)hatchCache.clear();
    hatchCache.set(key,pattern);
    return pattern;
  }
  function renderFill(feature) {
    const style=feature.style;
    if(!feature.closed||!style.hasFill||style.opacity<=0)return;
    addPath(feature.geometry);
    ctx.fillStyle=hatchPattern(style);
    ctx.globalAlpha=Math.min(
      state.hasVisibleUnderlay&&!state.exporting?.40:1,
      Math.max(0,style.opacity));
    ctx.fill("evenodd");
    ctx.globalAlpha=1;
  }
  function renderStroke(feature) {
    const style=feature.style;
    const exportRatio=state.exporting&&state.exportDpi===600?2:1;
    if(!style.drawStroke)return; // GEO-MAP text anchors aren't printed lines.
    if(feature.geometry.length===1 && feature.geometry[0].length===1) {
      const p=worldToScreen(...feature.geometry[0][0]);
      const segments=style.symbolSegments||[];
      const circles=style.symbolCircles||[];
      ctx.save();
      ctx.strokeStyle=style.stroke;
      ctx.lineWidth=Math.max(.8,Math.min(3,style.strokeWidth||1))*exportRatio;
      if(segments.length||circles.length){
        ctx.beginPath();
        for(const [x1,y1,x2,y2] of segments.slice(0,64)){
          ctx.moveTo(p.x+x1*5*exportRatio,p.y-y1*5*exportRatio);
          ctx.lineTo(p.x+x2*5*exportRatio,p.y-y2*5*exportRatio);
        }
        for(const [x,y,radius] of circles.slice(0,32)){
          ctx.moveTo(p.x+x*5*exportRatio+radius*5*exportRatio,p.y-y*5*exportRatio);
          ctx.arc(p.x+x*5*exportRatio,p.y-y*5*exportRatio,radius*5*exportRatio,0,2*Math.PI);
        }
        ctx.stroke();
      }else{
        ctx.fillStyle=style.stroke;ctx.beginPath();
        ctx.arc(p.x,p.y,Math.max(.6,Math.min(2,style.pointSize||1))*exportRatio,
                0,Math.PI*2);
        ctx.fill();
      }
      ctx.restore();
      return;
    }
    addPath(feature.geometry);
    ctx.strokeStyle=style.stroke;
    ctx.lineWidth=Math.max(.5,Math.min(12,style.strokeWidth))*exportRatio;
    ctx.lineCap="round";ctx.lineJoin="round";
    ctx.setLineDash(Array.isArray(style.dash)?style.dash.map(d=>d*exportRatio):[]);
    ctx.stroke();ctx.setLineDash([]);
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
  let boundaryTimer=0;
  function armNodeBoundary(ev){
    clearTimeout(boundaryTimer);
    const drag=state.vertexDrag;
    if(!drag)return;
    drag.follow=null;
    if(ev.altKey||!state.snapEnabled)return;
    boundaryTimer=setTimeout(()=>{
      if(state.vertexDrag!==drag||state.active!==drag.fid||state.tool!=="nodes"||!state.snapEnabled)return;
      const ring=editableVertices().map(pt=>{const w=nativeWorldPoint(pt);return [w.x,w.y];});
      ring[drag.index]=[drag.preview.x,drag.preview.y];
      const features=state.features.filter(f=>f.id!==drag.fid&&isVisible(f));
      const fit=heldBoundarySide(ring,drag.index,features,state.scale);
      if(!fit)return;
      drag.follow=fit;drag.preview={x:fit.point[0],y:fit.point[1]};drag.snap=null;
      requestDraw();
    },650);
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
    if(drag?.follow){
      const {step,point,between}=drag.follow;
      const fixed=nativeWorldPoint(points[(drag.index+step+points.length)%points.length]);
      ctx.beginPath();
      [[fixed.x,fixed.y],...between,point].forEach(([x,y],i)=>{
        const p=worldToScreen(x,y);if(i)ctx.lineTo(p.x,p.y);else ctx.moveTo(p.x,p.y);
      });
      ctx.strokeStyle="#ff9d21";ctx.lineWidth=3;ctx.stroke();
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
    if(!drag.follow&&Math.hypot(drag.preview.x-before.x,drag.preview.y-before.y)*
       state.scale<.5){requestDraw();return;}
    state.editBusy=true;updateEditState(state.edit);
    try {
      // Native GEO-MAP coordinate order: X=northing, Y=easting.
      const response=await api("/api/object/"+encodeURIComponent(drag.fid)+"/vertex",{
        method:"PATCH", headers:{"Content-Type":"application/json"},
        body:JSON.stringify({...editRequestBody(),index:drag.index,
          x:-drag.preview.y,y:drag.preview.x,shared:state.sharedNodes,
          follow:drag.follow?{step:drag.follow.step,points:drag.follow.between.map(([x,y])=>[-y,x])}:null,
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
  function labelFontSize(feature,label,selected) {
    const source=state.edit?.sourceCompilationScale||5000;
    const compilation=state.edit?.compilationScale||source;
    const ratio=Math.max(.1,Math.min(10,compilation/source));
    const base=Math.max(8,Math.min(36,Number(label.size)||16));
    const styledSize=Math.round(Math.max(8,Math.min(40,base*ratio))*10)/10;
    // Keep the already-correct PNG/JPG/TIFF typography EXACTLY as before.
    // Keep the 300 DPI layout; double text metrics only for 600 DPI exports.
    if(state.exporting)return styledSize*(state.exportDpi===600?2:1);
    // On the interactive map an annotation has a fixed size in MAP world
    // units, NOT a constant pixel size. Calibrate the style editor's 16 px
    // building text to the legible working view around 1:2500. Both its
    // location and glyph height then scale linearly with the map camera:
    // zoom out by 2 -> geometry and A1/A2 text are both 2 times smaller.
    // Do not impose a screen-pixel minimum: that would recreate the bug.
    const worldTextHeight=styledSize*2500*.0254/96;
    return worldTextHeight*state.scale;
  }
  function labelTextRows(label,size) {
    const lines=String(label.text||"").split("\n").slice(0,6);
    return {lines,size,height:lines.length*size*1.20};
  }
  function renderLabels(features,collisions=[]) {
    state.labelHits=[];
    if(!state.labels)return;
    // Screen-space spatial hash, preserving export's cross-batch collision
    // ledger. Checking every prior caption on every wheel frame was O(n²).
    const cell=64,cellIndex=new Map();
    function captionCells(rect){
      const x0=Math.max(0,Math.floor(rect[0]/cell));
      const x1=Math.min(Math.ceil(state.width/cell),Math.floor(rect[2]/cell));
      const y0=Math.max(0,Math.floor(rect[1]/cell));
      const y1=Math.min(Math.ceil(state.height/cell),Math.floor(rect[3]/cell));
      const keys=[];
      for(let x=x0;x<=x1;x++)for(let y=y0;y<=y1;y++)keys.push(x+":"+y);
      return keys;
    }
    function indexCollision(item){
      for(const key of captionCells(item.rect)){
        if(!cellIndex.has(key))cellIndex.set(key,[]);
        cellIndex.get(key).push(item);
      }
    }
    for(const item of collisions)indexCollision(item);
    function overlapsAnother(fid,rect){
      const checked=new Set();
      for(const key of captionCells(rect))for(const item of cellIndex.get(key)||[]){
        if(checked.has(item))continue;
        checked.add(item);
        if(item.fid!==fid&&item.rect[0]<rect[2]&&
           item.rect[2]>rect[0]&&item.rect[1]<rect[3]&&
           item.rect[3]>rect[1])return true;
      }
      return false;
    }
    let painted=0;
    const ordered=[...features].sort((a,b)=>{
      const priority=f=>f.id===state.active?-2:
        state.pinned.has(f.id)?-1:
        f.code==="5310"?0:
        ["7900","6000","6301","6900"].includes(f.code)?1:
        f.code==="5216"?2:3;
      return priority(a)-priority(b);
    });
    ctx.save();
    ctx.textBaseline="alphabetic";
    for(const feature of ordered){
      if(!feature.labels?.length)continue;
      const selected=!state.exporting&&feature.id===state.active;
      const box=feature.bbox;
      const w=(box[2]-box[0])*state.scale;
      const h=(box[3]-box[1])*state.scale;
      const sheet=["7900","6900","6000","6301"].includes(feature.code);
      // 5310 A1 and A2 are mandatory descriptions. Never discard them
      // because of zoom, a neighboring building or a sheet annotation.
      if(!selected&&!sheet&&feature.code!=="5310"&&
         (Math.max(w,h)<32||Math.min(w,h)<8))continue;
      // A1 and A2 are TWO draggable labels with separate collision boxes.
      // Only their *default* vertical positions are stacked for legibility.
      const stack=feature.code==="5310"?feature.labels.filter(
        label=>!label.manuallyPlaced):[];
      const stackSizes=new Map();
      let stackHeight=0;
      for(const label of stack){
        const size=labelFontSize(feature,label,selected);
        if(!size)continue;
        const height=labelTextRows(label,size).height;
        stackSizes.set(label.field,{height,size,center:stackHeight+height/2});
        stackHeight+=height;
      }
      for(const label of feature.labels){
        const mandatory5310=feature.code==="5310"&&
          (label.field==="A1"||label.field==="A2");
        if(!mandatory5310&&painted>=(state.exporting?8000:1400))continue;
        const size=labelFontSize(feature,label,selected);
        if(!size)continue;
        const font=(label.bold?"700":"400")+" "+size+"px '"+
          String(label.fontFamily||"Segoe UI").replace(/["'\\]/g,"")+
          "', sans-serif";
        ctx.font=font;
        const {lines,height}=labelTextRows(label,size);
        const widths=lines.map(line=>ctx.measureText(line.slice(0,100)).width);
        const maxWidth=Math.max(0,...widths);
        let offset=label.manuallyPlaced?0:
          (label.offset||0)*(size/(label.size||16));
        if(stackSizes.has(label.field))
          offset=stackSizes.get(label.field).center-stackHeight/2;
        const p=worldToScreen(label.x,label.y);
        const cy=p.y+offset;
        // Collision padding shrinks/grows with the map as well.
        // The export path retains its existing three-pixel padding.
        const labelPad=state.exporting?3*(state.exportDpi===600?2:1):size*3/16;
        const rect=[p.x-maxWidth/2-labelPad,cy-height/2-labelPad,
                    p.x+maxWidth/2+labelPad,cy+height/2+labelPad];
        if(rect[2]<0||rect[0]>state.width||
           rect[3]<0||rect[1]>state.height)continue;
        // Keep A1 and A2 of the SAME feature together, but never let
        // descriptions of DIFFERENT features overwrite one another.
        // Culling is essential for dense 5310 areas and for export.
        if(!mandatory5310&&!selected&&overlapsAnother(feature.id,rect))continue;
        const collision={fid:feature.id,rect};
        collisions.push(collision);indexCollision(collision);
        if(!state.exporting&&(selected||state.tool==="labels")&&
           (label.field==="A1"||label.field==="A2"||
            state.labelSelected?.field===label.field&&
            state.labelSelected?.fid===feature.id)){
          ctx.fillStyle="rgba(27,150,143,.18)";
          ctx.fillRect(rect[0],rect[1],rect[2]-rect[0],rect[3]-rect[1]);
        }
        if(!state.exporting&&state.tool==="labels"&&state.labelSelected?.fid===feature.id&&
           state.labelSelected?.field===label.field){
          ctx.strokeStyle="#0b9e8f";ctx.lineWidth=1.5;
          ctx.strokeRect(...[rect[0],rect[1],rect[2]-rect[0],rect[3]-rect[1]]);
        }
        ctx.font=font;
        for(let i=0;i<lines.length;i++){
          const line=lines[i].slice(0,100);
          const x=p.x-widths[i]/2;
          const y=cy-height/2+size+(i*size*1.20);
          ctx.strokeStyle=document.body.classList.contains("dark-map")
            ?"#1b2c3d":"#f8fafc";
          // On-screen halo width must shrink with the glyph; an
          // absolute 0.7px floor would dominate tiny zoomed-out text.
          ctx.lineWidth=state.exporting
            ?Math.max(.7,Math.min(2,size*.11)):size*.11;
          ctx.strokeText(line,x,y);
          ctx.fillStyle=label.color||"#4A5056";
          ctx.fillText(line,x,y);
        }
        state.labelHits.push({fid:feature.id,field:label.field,
                              rect,label,feature});
        painted++;
      }
    }
    ctx.restore();
  }
  function renderScreenLabels(features) {
    // Labels use a separate transparent canvas so old text is never
    // resampled from the geometry snapshot. Their positions AND font size
    // derive from state.scale, keeping descriptions bound to the map.
    // devicePixelRatio only improves raster sharpness on HiDPI monitors.
    labelCtx.setTransform(state.pixelRatio,0,0,state.pixelRatio,0,0);
    labelCtx.clearRect(0,0,state.width,state.height);
    const previousContext=ctx;
    ctx=labelCtx;
    try { renderLabels(features); }
    finally { ctx=previousContext; }
  }
  function draw() {
    state.scheduled=false;
    if(activeTrace&&!state.exporting){
      const item=activeTrace.id===raster.id?raster:raster.layers.find(layer=>layer.id===activeTrace.id);
      if(item&&rasterCanShow(item)&&activeTrace.token===state.edit?.documentToken)activeTrace.redraw();
      else activeTrace.close();
    }
    ctx.setTransform(state.pixelRatio,0,0,state.pixelRatio,0,0);
    ctx.clearRect(0,0,state.width,state.height);
    ctx.fillStyle=state.mapBackground;
    ctx.fillRect(0,0,state.width,state.height);
    state.hasVisibleUnderlay=!!(
      (underlay.enabled&&underlay.visible&&underlay.image)||
      [...raster.layers,...(raster.image?[rasterEntry()]:[])]
        .some(item=>rasterCanShow(item)));
    paintUnderlay();paintRaster();drawGrid();
    if(!state.meta){renderScreenLabels([]);return;}
    // Keep the last verified viewport visible while the spatial request
    // catches up to the new camera, avoiding blank flashes on zoom.
    // Render current vector coordinates at the current camera on EVERY
    // frame, even during a pending /api/viewport fetch. A rescaled Canvas
    // snapshot is blurry and can crop previously unseen map fragments.
    state.previewActive=false;state.previewCamera=null;
    const box=boundsFromViewport(.05);
    const features=state.features.filter(f=>isVisible(f)&&isInView(f.bbox,box));
    // Match the classic QGraphicsScene: paint fills below ALL outlines.
    // Painting fill+stroke for each object separately erased earlier
    // parcel borders beneath later overlapping polygons.
    const priorities={"5216":0,"5220":1,"5230":2,"5310":3,"1246":4};
    features.sort((a,b)=>(priorities[a.code]??3)-(priorities[b.code]??3));
    for(const feature of features) renderFill(feature);
    for(const feature of features) renderStroke(feature);
    renderHighlights(features);drawTopologyHighlight(features);
    drawMoveGhost(features);drawMoveMagnet();
    // No bitmap snapshot or resampling is made during a wheel frame.
    // The map remains rendered in native screen-space vector precision.
    renderScreenLabels(features);drawGcpMapMarkers();
    drawSheetItems();
    drawExportAreaOverlay();
    drawDraftPolygon();drawMagnetMarker();drawVertexTool();
    updateScaleReadout();
    $("count-visible").textContent=display(features.length);
    $("render-hint").textContent=state.limited
      ?"Zbyt wiele obiektów · przybliż mapę":display(features.length)+" obiektów";
  }
  function requestDraw() {
    if(!state.scheduled){state.scheduled=true;requestAnimationFrame(draw);}
  }
  async function refreshViewport() {
    if(!state.meta) return;
    const ticket=++state.queryCounter;
    if(state.queryAbort) state.queryAbort.abort();
    const controller=new AbortController();state.queryAbort=controller;
    // Full local response up to 50k objects / 750k vertices.
    // Larger maps rely on viewport streaming and the cached bitmap.
    let view=state.localMapCandidate?[...state.meta.bounds]:
      boundsFromViewport(.65);
    // Bound requests to the actual map extent. This prevents huge spatial
    // index scans when a user zooms far out or pans away from their map.
    const map=state.meta.bounds;
    if(view[2]<map[0]||view[0]>map[2]||view[3]<map[1]||view[1]>map[3]){
      state.features=[];state.limited=false;
      state.previewActive=false;state.previewCamera=null;
      state.geometrySnapshotValid=false;
      requestDraw();return;
    }
    view=[Math.max(view[0],map[0]),Math.max(view[1],map[1]),
          Math.min(view[2],map[2]),Math.min(view[3],map[3])];
    const params=new URLSearchParams({
      xmin:view[0],ymin:view[1],xmax:view[2],ymax:view[3],limit:100000
    });
    try {
      const res=await api("/api/viewport?"+params.toString(),{signal:controller.signal});
      if(ticket!==state.queryCounter)return;
      state.limited=res.limited;
      state.localMapReady=state.localMapCandidate&&!res.limited&&
        res.total<=50000;
      if(state.localMapReady){
        // Entire MAP is resident; never fetch on subsequent zoom/pan.
        state.viewportFeatureCache.clear();state.features=res.features;
      }else{
        // Keep neighboring features already visited instead of dropping
        // them while a new padded viewport request is in flight.
        for(const feature of res.features){
          state.viewportFeatureCache.delete(feature.id);
          state.viewportFeatureCache.set(feature.id,feature);
        }
        while(state.viewportFeatureCache.size>65000)
          state.viewportFeatureCache.delete(state.viewportFeatureCache.keys().next().value);
        state.features=[...state.viewportFeatureCache.values()];
      }
      state.previewActive=false;state.previewCamera=null;
      renderCartographyMatches();
      requestDraw();
    }catch(err){
      if(err.name!=="AbortError"){
        state.previewActive=false;state.previewCamera=null;requestDraw();
        inform("Nie udało się narysować mapy: "+err.message,true);
      }
    }
  }
  function scheduleViewport(now=false) {
    scheduleUnderlayRefresh();
    clearTimeout(state.refreshTimer);
    // Once the complete MAP is local, zoom/pan never needs HTTP or a
    // deferred frame: labels and vectors are recomputed at native precision.
    if(state.localMapReady){requestDraw();return;}
    // For large maps retain sharp known geometry while fetching a
    // spacious surrounding viewport so quick panning rarely hits edges.
    requestDraw();
    if(now)refreshViewport();
    else state.refreshTimer=setTimeout(refreshViewport,85);
  }

  // Stage 11: screen exporter keeps native vector geometry.
  // Stage 14B: export bounds are independent of screen zoom and pan.
  function selectedExportBounds(){
    if($("layout-scope").value==="all"){
      const b=[...state.meta.bounds];
      for(const i of state.edit?.sheetItems||[]){
        b[0]=Math.min(b[0],i.x);b[1]=Math.min(b[1],i.y);
        b[2]=Math.max(b[2],i.x+i.w);b[3]=Math.max(b[3],i.y+i.h);
      }
      return b;
    }
    if($("layout-scope").value==="rect"&&state.exportAreaBounds)
      return [...state.exportAreaBounds];
    throw Error("Najpierw zaznacz prostokąt na mapie.");
  }
  function updateExportFormatControls(){
    $("layout-orientation-row").hidden=$("layout-format").value!=="pdf";
  }
  function updateExportAreaControls(){
    const rectangle=$("layout-scope").value==="rect";
    $("layout-rectangle-tools").hidden=!rectangle;
    const b=state.exportAreaBounds;
    $("layout-area-status").textContent=b
      ?"Wybrano obszar "+(b[2]-b[0]).toFixed(1)+" × "+
         (b[3]-b[1]).toFixed(1)+" m. Możesz zaznaczyć go ponownie."
      :"Nie wybrano obszaru. Przeciągnij prostokąt na mapie.";
    $("layout-choose-area").textContent=b
      ?"▧ Zmień prostokąt":"▧ Zaznacz prostokąt na mapie";
  }
  function openLayoutDialog(resume=false){
    if(!state.meta||!state.edit)return;
    if(resume!==true){
      $("layout-title").value=state.meta.name.replace(/\.map$/i,"");
      // Do not derive export scale from state.scale (current zoom).
      $("layout-scale").value=String(state.edit.compilationScale||5000);
    }
    if(!$("layout-legend-rows").value.trim())
      $("layout-legend-rows").value=(state.meta.layers||[])
        .filter(layer=>state.visibleLayers.has(layer.name))
        .slice(0,40).map(layer=>layer.name+" | "+colorForLayer(layer.name))
        .join("\n");
    updateExportAreaControls();
    updateExportFormatControls();
    $("layout-summary").textContent="Skala opracowania: 1:"+
      $("layout-scale").value+". Cała mapa w jednym pliku.";
    if(!$("layout-dialog").open)$("layout-dialog").showModal();
  }
  function beginExportAreaSelection(){
    if(!state.meta||state.editBusy)return;
    if($("layout-dialog").open)$("layout-dialog").close();
    state.exportAreaPicking=true;
    state.exportAreaDrag=null;
    canvas.style.cursor="crosshair";
    inform("Przytrzymaj mysz i narysuj prostokąt eksportu. Esc — anuluj.");
    requestDraw();
  }
  function finishExportAreaSelection(cancel=false){
    state.exportAreaPicking=false;
    state.exportAreaDrag=null;
    canvas.style.cursor="";
    if(cancel)inform("Anulowano wybieranie prostokąta.");
    openLayoutDialog(true);
    requestDraw();
  }
  function drawExportAreaOverlay(){
    // Only a temporary screen overlay while picking. Export bounds are
    // retained for the dialog but never obscure the editable map.
    if(!state.meta||!state.exportAreaPicking)return;
    let b=state.exportAreaBounds;
    if(state.exportAreaPicking&&state.exportAreaDrag){
      const d=state.exportAreaDrag;
      b=[Math.min(d.start.x,d.end.x),Math.min(d.start.y,d.end.y),
         Math.max(d.start.x,d.end.x),Math.max(d.start.y,d.end.y)];
    }
    if(!b||($("layout-scope").value!=="rect"&&!state.exportAreaPicking))return;
    const a=worldToScreen(b[0],b[1]),z=worldToScreen(b[2],b[3]);
    const x=Math.min(a.x,z.x),y=Math.min(a.y,z.y);
    const w=Math.abs(z.x-a.x),h=Math.abs(z.y-a.y);
    labelCtx.save();
    labelCtx.fillStyle="rgba(0,165,151,.10)";
    labelCtx.fillRect(x,y,w,h);
    labelCtx.lineWidth=2.2;
    labelCtx.strokeStyle="#008c80";
    labelCtx.setLineDash([8,5]);labelCtx.strokeRect(x,y,w,h);
    labelCtx.restore();
  }
  function installExportAreaCapture(){
    const map=$("map-canvas");
    map.addEventListener("pointerdown",ev=>{
      if(!state.exportAreaPicking||ev.button!==0)return;
      ev.preventDefault();ev.stopImmediatePropagation();
      const p=eventCoords(ev),w=screenToWorld(p.x,p.y);
      state.exportAreaDrag={id:ev.pointerId,start:w,end:w,startPx:p};
      map.setPointerCapture(ev.pointerId);requestDraw();
    },true);
    map.addEventListener("pointermove",ev=>{
      if(!state.exportAreaPicking)return;
      ev.preventDefault();ev.stopImmediatePropagation();
      const drag=state.exportAreaDrag;
      if(!drag||drag.id!==ev.pointerId)return;
      const p=eventCoords(ev);
      drag.end=screenToWorld(p.x,p.y);requestDraw();
    },true);
    map.addEventListener("pointerup",ev=>{
      if(!state.exportAreaPicking)return;
      ev.preventDefault();ev.stopImmediatePropagation();
      const drag=state.exportAreaDrag;
      if(!drag||drag.id!==ev.pointerId)return;
      if(map.hasPointerCapture?.(ev.pointerId))
        map.releasePointerCapture(ev.pointerId);
      const p=eventCoords(ev),end=screenToWorld(p.x,p.y);
      if(Math.abs(p.x-drag.startPx.x)<8||
         Math.abs(p.y-drag.startPx.y)<8){
        state.exportAreaDrag=null;
        inform("Prostokąt jest za mały. Spróbuj ponownie.",true);
        requestDraw();return;
      }
      const bounds=state.meta.bounds;
      const rect=[
        Math.max(bounds[0],Math.min(drag.start.x,end.x)),
        Math.max(bounds[1],Math.min(drag.start.y,end.y)),
        Math.min(bounds[2],Math.max(drag.start.x,end.x)),
        Math.min(bounds[3],Math.max(drag.start.y,end.y))
      ];
      if(rect[2]<=rect[0]||rect[3]<=rect[1]){
        state.exportAreaDrag=null;
        inform("Zaznacz obszar wewnątrz mapy.",true);requestDraw();return;
      }
      state.exportAreaBounds=rect;
      $("layout-scope").value="rect";
      finishExportAreaSelection();
    },true);
    map.addEventListener("pointercancel",ev=>{
      if(!state.exportAreaPicking)return;
      ev.preventDefault();ev.stopImmediatePropagation();
      finishExportAreaSelection(true);
    },true);
  }
  function pdfLayoutOptions(){
    const bounds=selectedExportBounds();
    const denominator=Number($("layout-scale").value);
    if(!Number.isInteger(denominator)||denominator<10||denominator>100000000)
      throw Error("Nieprawidłowy mianownik skali PDF.");
    const parseRows=(id,kind,max)=>{
      const text=$(id).value.trim();
      if(!text)return [];
      const lines=text.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
      if(lines.length>max)throw Error("Zbyt wiele wierszy w sekcji "+kind+".");
      return lines.map((line,i)=>{
        const split=line.indexOf("|");
        if(split<0)throw Error("Wiersz "+(i+1)+" sekcji "+kind+
          ": użyj formatu Nazwa | wartość.");
        const first=line.slice(0,split).trim().slice(0,70);
        const second=line.slice(split+1).trim().slice(0,120);
        if(kind==="legenda"){
          if(!/^#[0-9a-fA-F]{6}$/.test(second))
            throw Error("Wiersz "+(i+1)+": kolor legendy musi mieć postać #RRGGBB.");
          return {name:first,color:second};
        }
        return {label:first,value:second};
      });
    };
    const frameWidthMm=Number($("layout-frame-width").value);
    if(!Number.isFinite(frameWidthMm)||frameWidthMm<.1||frameWidthMm>2.5)
      throw Error("Grubość ramki: od 0,1 do 2,5 mm.");
    return {
      format:"pdf",bounds,denominator,
      inserts:(state.edit.sheetItems||[]).map(i=>({
        x:i.x,y:i.y,w:i.w,h:i.h,size:GeoStudioSheet.sizes[i.kind],
        shapes:GeoStudioSheet.shapes(i,denominator)
      })),
      paper:$("layout-paper").value,
      orientation:$("layout-orientation").value,
      title:$("layout-title").value.trim().slice(0,100)||"Mapa GEO-MAP",
      frame:false,
      frameColor:$("layout-frame-color").value,
      frameWidthMm,
      north:false,
      scaleBar:false,
      showLegend:false,
      legendRows:parseRows("layout-legend-rows","legenda",40),
      tableRows:parseRows("layout-table-rows","tabela",8),
      compilationScale:state.edit?.compilationScale||5000,
      sourceCompilationScale:state.edit?.sourceCompilationScale||5000,
      visibleLayers:[...state.visibleLayers],
      hiddenLandUses:[...state.hiddenLandUses],
      hiddenForestClasses:[...state.hiddenGrades]
    };
  }
  function layoutOptions(){
    const bounds=selectedExportBounds();
    if(bounds.some(value=>!Number.isFinite(value))||
       bounds[2]<=bounds[0]||bounds[3]<=bounds[1])
      throw Error("Nieprawidłowy obszar mapy.");
    const denominator=Number($("layout-scale").value);
    if(!Number.isInteger(denominator)||denominator<10||
       denominator>100000000)
      throw Error("Mianownik skali musi mieścić się w zakresie 10–100000000.");
    const dpi=Number($("layout-dpi").value);
    if(![96,150,300,600].includes(dpi))
      throw Error("Wybierz poprawną rozdzielczość.");
    const pxPerUnit=dpi/(.0254*denominator);
    const width=Math.ceil((bounds[2]-bounds[0])*pxPerUnit);
    const height=Math.ceil((bounds[3]-bounds[1])*pxPerUnit);
    if(width<1||height<1)throw Error(
      "Obiekt jest za mały dla tej skali i DPI. Użyj większej skali.");
    const mm=value=>Math.round(value*dpi/25.4);
    const margin=mm(13),head=mm(20),foot=mm(21);
    const legend=0;
    const fullWidth=width+margin*2+legend;
    const fullHeight=height+head+foot;
    // Large print sheets become full-resolution tiled archives.
    const tiled=fullWidth>12000||fullHeight>12000||
      fullWidth*fullHeight>40000000;
    return {
      bounds,denominator,dpi,pxPerUnit,width,height,margin,head,foot,
      legend,fullWidth,fullHeight,tiled,
      orientation:width>=height?"landscape":"portrait",
      title:$("layout-title").value.trim().slice(0,100)||"Mapa GEO-MAP",
      frame:false,north:false,
      scaleBar:false,
      showLegend:false,
      format:$("layout-format").value,
    };
  }
  function exportInfo(message){$("layout-summary").textContent=message;}
  async function forEachExportPage(bounds,callback){
    const limit=4000;
    let offset=0,expected=null;
    for(;;){
      const qs=new URLSearchParams({
        xmin:bounds[0],ymin:bounds[1],xmax:bounds[2],ymax:bounds[3],
        limit,offset
      });
      const data=await api("/api/viewport?"+qs.toString());
      if(expected===null)expected=data.total;
      if(data.total!==expected)
        throw Error("Mapa zmieniła się podczas pobierania geometrii.");
      if(!data.features.length&&offset<expected)
        throw Error("Brak kolejnej partii geometrii.");
      callback(data.features);
      offset+=data.features.length;
      if(offset>=expected)break;
      if(offset>10000000)throw Error("Przekroczono zakres eksportu.");
      await new Promise(resolve=>setTimeout(resolve,0));
    }
  }
  function renderExportBatch(g,options,features,pass,collisions){
    const previous={
      ctx,center:state.center,scale:state.scale,
      width:state.width,height:state.height,pixelRatio:state.pixelRatio,
      exporting:state.exporting,labelHits:state.labelHits,
      exportDpi:state.exportDpi
    };
    ctx=g;
    const full=options.virtualLayout?.full||options;
    state.center={
      x:(full.bounds[0]+full.bounds[2])/2,
      y:(full.bounds[1]+full.bounds[3])/2
    };
    state.scale=full.pxPerUnit;
    state.width=full.width;state.height=full.height;
    state.pixelRatio=1;
    // The PNG/JPG/TIFF bitmap has its own pixel dimensions.
    // Do NOT scale text by DPI a second time.
    state.exporting=true;
    state.exportDpi=options.dpi;
    g.save();
    try{
      g.translate(full.margin-(options.virtualLayout?.x||0),
                  full.head-(options.virtualLayout?.y||0));
      g.beginPath();g.rect(0,0,full.width,full.height);g.clip();
      const visible=features.filter(isVisible);
      const priority={"5216":0,"5220":1,"5230":2,"5310":3,"1246":4};
      visible.sort((a,b)=>(priority[a.code]??3)-(priority[b.code]??3));
      if(pass==="fills")for(const item of visible)renderFill(item);
      if(pass==="strokes")for(const item of visible)renderStroke(item);
      if(pass==="labels")renderLabels(visible,collisions);
    }finally{
      g.restore();
      ctx=previous.ctx;state.center=previous.center;
      state.scale=previous.scale;state.width=previous.width;
      state.height=previous.height;state.pixelRatio=previous.pixelRatio;
      state.exporting=previous.exporting;
      state.exportDpi=previous.exportDpi;
      state.labelHits=previous.labelHits;
    }
  }
  function paintLayoutFurniture(g,opts){
    const ratio=opts.dpi/96;
    const {margin,head,width,height,legend,denominator,dpi}=opts;
    const x=margin,y=head,base=margin+width;
    g.save();
    g.fillStyle="#fff";g.strokeStyle="#25384d";
    g.lineWidth=Math.max(1,ratio);
    g.textBaseline="middle";
    g.font="700 "+Math.round(17*ratio)+"px sans-serif";
    g.fillStyle="#172c40";
    g.fillText(opts.title,margin,head/2,Math.max(50,width*.83));
    if(opts.north){
      const nx=base-15*ratio,ny=head/2;
      g.fillStyle="#172c40";
      g.font="700 "+Math.round(14*ratio)+"px sans-serif";
      g.textAlign="center";g.fillText("N",nx,ny-6*ratio);
      g.beginPath();g.moveTo(nx,ny-4*ratio);
      g.lineTo(nx-7*ratio,ny+9*ratio);
      g.lineTo(nx+7*ratio,ny+9*ratio);g.closePath();g.fill();
      g.textAlign="start";
    }
    if(opts.frame){
      g.strokeStyle="#25384d";g.lineWidth=Math.max(1,ratio);
      g.strokeRect(x,y,width,height);
    }
    const footerY=head+height+opts.foot*.42;
    if(opts.scaleBar){
      const aim=width*.24/opts.pxPerUnit;
      const magnitude=Math.pow(10,Math.floor(Math.log10(Math.max(1e-8,aim))));
      const distance=([1,2,5,10].filter(n=>n*magnitude<=aim).pop()||1)*magnitude;
      const barPixels=distance*opts.pxPerUnit;
      const start=margin+Math.max(0,(width-barPixels)/2);
      const ty=footerY-6*ratio;
      g.strokeStyle="#172c40";g.lineWidth=Math.max(1,ratio);
      for(let i=0;i<2;i++){
        g.fillStyle=i?"#fff":"#172c40";
        g.fillRect(start+i*barPixels/2,ty,barPixels/2,5*ratio);
        g.strokeRect(start+i*barPixels/2,ty,barPixels/2,5*ratio);
      }
      g.fillStyle="#172c40";
      g.textAlign="center";g.font=Math.round(10*ratio)+"px sans-serif";
      g.fillText("0",start,ty-7*ratio);
      g.fillText(new Intl.NumberFormat("pl-PL",{maximumFractionDigits:2})
        .format(distance/2),start+barPixels/2,ty-7*ratio);
      g.fillText(new Intl.NumberFormat("pl-PL",{maximumFractionDigits:2})
        .format(distance)+" m",start+barPixels,ty-7*ratio);
      g.textAlign="start";
    }
    g.textAlign="start";
    if(opts.showLegend&&legend){
      const lx=base+8*ratio;
      const list=state.meta.layers.filter(layer=>
        state.visibleLayers.has(layer.name));
      g.font="700 "+Math.round(13*ratio)+"px sans-serif";
      g.fillStyle="#172c40";g.fillText("LEGENDA",lx,head+15*ratio);
      g.font=Math.round(10*ratio)+"px sans-serif";
      let ly=head+34*ratio;
      for(const layer of list.slice(0,24)){
        if(ly>head+height-12*ratio)break;
        g.fillStyle=colorForLayer(layer.name);
        g.fillRect(lx,ly-7*ratio,10*ratio,10*ratio);
        g.strokeStyle="#44546a";g.lineWidth=ratio*.55;
        g.strokeRect(lx,ly-7*ratio,10*ratio,10*ratio);
        g.fillStyle="#25384d";
        g.fillText(layer.name,lx+15*ratio,ly,
          Math.max(45,legend-20*ratio));
        ly+=21*ratio;
      }
      if(list.length>24)g.fillText("… i pozostałe warstwy",lx,ly);
    }
    g.restore();
  }
  async function renderLayoutCanvas(options){
    const target=document.createElement("canvas");
    target.width=options.fullWidth;target.height=options.fullHeight;
    const g=target.getContext("2d",{willReadFrequently:options.format==="tiff"});
    if(!g)throw Error("Nie można przygotować obrazu.");
    g.fillStyle="#ffffff";g.fillRect(0,0,target.width,target.height);
    const revision=state.edit?.revision;
    const documentToken=state.edit?.documentToken;
    // Keep collision boxes across all 4000-object pages. Without this
    // ledger, labels from later batches can overwrite earlier labels.
    const exportLabelCollisions=[];
    for(const [pass,label] of [
      ["fills","wypełnienia"],["strokes","linie"],["labels","etykiety"]
    ]){
      exportInfo("Eksport: "+label+"…");
      await forEachExportPage(options.queryBounds||options.bounds,part=>
        renderExportBatch(g,options,part,pass,exportLabelCollisions));
      if(state.edit?.revision!==revision||
         state.edit?.documentToken!==documentToken)
        throw Error("Mapa została zmieniona podczas przygotowania eksportu.");
    }
    const page=options.virtualLayout?.full||options;
    const ox=page.margin+page.width/2-(options.virtualLayout?.x||0);
    const oy=page.head+page.height/2-(options.virtualLayout?.y||0);
    g.save();g.beginPath();g.rect(ox-page.width/2,oy-page.height/2,page.width,page.height);g.clip();
    GeoStudioSheet.paint(g,state.edit.sheetItems,(x,y)=>({
      x:ox+(x-(page.bounds[0]+page.bounds[2])/2)*page.pxPerUnit,
      y:oy+(y-(page.bounds[1]+page.bounds[3])/2)*page.pxPerUnit
    }),page.pxPerUnit,page.denominator);
    g.restore();
    if(options.virtualLayout){
      g.save();
      g.translate(-options.virtualLayout.x,-options.virtualLayout.y);
      paintLayoutFurniture(g,options.virtualLayout.full);
      g.restore();
    }else paintLayoutFurniture(g,options);
    return target;
  }
  function makeRGBTiff(target,dpi){
    // Uncompressed baseline TIFF, little endian, one RGB strip.
    const width=target.width,height=target.height;
    const pixels=target.getContext("2d").getImageData(
      0,0,width,height).data;
    const byteCount=width*height*3,buf=new ArrayBuffer(180+byteCount);
    const out=new DataView(buf);
    const u16=(at,value)=>out.setUint16(at,value,true);
    const u32=(at,value)=>out.setUint32(at,value,true);
    out.setUint8(0,0x49);out.setUint8(1,0x49);
    u16(2,42);u32(4,8);u16(8,12);
    let entry=10;
    function tag(id,type,count,value){
      u16(entry,id);u16(entry+2,type);
      u32(entry+4,count);
      if(type===3&&count===1)u16(entry+8,value);
      else u32(entry+8,value);
      entry+=12;
    }
    tag(256,4,1,width);tag(257,4,1,height);tag(258,3,3,158);
    tag(259,3,1,1);tag(262,3,1,2);tag(273,4,1,180);
    tag(277,3,1,3);tag(278,4,1,height);tag(279,4,1,byteCount);
    tag(282,5,1,164);tag(283,5,1,172);tag(296,3,1,2);
    u32(154,0);
    u16(158,8);u16(160,8);u16(162,8);
    u32(164,dpi);u32(168,1);u32(172,dpi);u32(176,1);
    const rgb=new Uint8Array(buf,180);
    for(let p=0,j=0;p<pixels.length;p+=4){
      rgb[j++]=pixels[p];rgb[j++]=pixels[p+1];rgb[j++]=pixels[p+2];
    }
    return new Blob([buf],{type:"image/tiff"});
  }
  function canvasBlob(canvas,mime,quality){
    return new Promise((resolve,reject)=>canvas.toBlob(
      blob=>blob?resolve(blob):reject(Error("Nie można zakodować obrazu.")),
      mime,quality));
  }

  async function withRasterDpi(blob,format,dpi){
    // Canvas encoders normally write 96 DPI even when the requested sheet
    // is 300 DPI. Fix image resolution metadata to preserve print scale in
    // external editors, not just inside GeoStudio's own print dialog.
    const bytes=new Uint8Array(await blob.arrayBuffer());
    if(format==="jpeg"){
      if(bytes[0]!==255||bytes[1]!==216)throw Error("Niepoprawny JPG.");
      let index=2,found=false;
      while(index+4<bytes.length&&bytes[index]===255){
        const marker=bytes[index+1];
        if(marker===218||marker===217)break;
        const size=(bytes[index+2]<<8)|bytes[index+3];
        if(size<2||index+size+2>bytes.length)break;
        if(marker===224&&size>=16&&bytes[index+4]===74&&
           bytes[index+5]===70&&bytes[index+6]===73&&
           bytes[index+7]===70&&bytes[index+8]===0){
          bytes[index+11]=1;
          bytes[index+12]=(dpi>>8)&255;bytes[index+13]=dpi&255;
          bytes[index+14]=(dpi>>8)&255;bytes[index+15]=dpi&255;
          found=true;break;
        }
        index+=size+2;
      }
      if(found)return new Blob([bytes],{type:"image/jpeg"});
      const jfif=new Uint8Array([
        255,224,0,16,74,70,73,70,0,1,2,1,
        (dpi>>8)&255,dpi&255,(dpi>>8)&255,dpi&255,0,0
      ]);
      const patched=new Uint8Array(bytes.length+jfif.length);
      patched.set(bytes.subarray(0,2));patched.set(jfif,2);
      patched.set(bytes.subarray(2),2+jfif.length);
      return new Blob([patched],{type:"image/jpeg"});
    }
    if(format!=="png")return blob;
    const signature=[137,80,78,71,13,10,26,10];
    if(signature.some((value,index)=>bytes[index]!==value))
      throw Error("Niepoprawny PNG.");
    const read32=(buffer,at)=>new DataView(
      buffer.buffer,buffer.byteOffset,buffer.byteLength).getUint32(at,false);
    const write32=(buffer,at,value)=>new DataView(
      buffer.buffer,buffer.byteOffset,buffer.byteLength).setUint32(at,value,false);
    const ppm=Math.round(dpi/.0254);
    const chunk=new Uint8Array(21);
    write32(chunk,0,9);
    chunk.set([112,72,89,115],4); // "pHYs"
    write32(chunk,8,ppm);write32(chunk,12,ppm);chunk[16]=1;
    let crc=0xffffffff;
    for(let i=4;i<17;i++){
      crc^=chunk[i];
      for(let bit=0;bit<8;bit++)
        crc=crc&1?(crc>>>1)^0xedb88320:crc>>>1;
    }
    write32(chunk,17,(crc^0xffffffff)>>>0);
    let offset=8,insertAt=0;
    while(offset+12<=bytes.length){
      const length=read32(bytes,offset);
      if(offset+12+length>bytes.length)break;
      const name=String.fromCharCode(...bytes.subarray(offset+4,offset+8));
      if(name==="IHDR")insertAt=offset+12+length;
      if(name==="pHYs"){
        if(length!==9)throw Error("Nieznany blok rozdzielczości PNG.");
        bytes.set(chunk.subarray(8),offset+8);
        return new Blob([bytes],{type:"image/png"});
      }
      if(name==="IDAT")break;
      offset+=length+12;
    }
    if(!insertAt)throw Error("Niepoprawny nagłówek PNG.");
    const patched=new Uint8Array(bytes.length+chunk.length);
    patched.set(bytes.subarray(0,insertAt),0);
    patched.set(chunk,insertAt);
    patched.set(bytes.subarray(insertAt),insertAt+chunk.length);
    return new Blob([patched],{type:"image/png"});
  }
  function planRasterTiles(options){
    // The full MAP is a single pixel coordinate grid, not the viewport.
    // Partition that grid into balanced cells so adjacent sheets share
    // exact boundaries and their physical DPI remains unchanged.
    const landscape=options.orientation!=="portrait";
    const sheetW=landscape?6500:5600;
    const sheetH=landscape?5600:6500;
    const maxW=sheetW-options.margin*2-options.legend;
    const maxH=sheetH-options.head-options.foot;
    if(maxW<100||maxH<100)throw Error("Za duża oprawa dla kafli eksportu.");
    const columns=Math.max(1,Math.ceil(options.width/maxW));
    const rows=Math.max(1,Math.ceil(options.height/maxH));
    if(columns*rows>256)
      throw Error("Mapa wymaga ponad 256 arkuszy. Wybierz mniejszy "+
        "prostokąt lub niższe DPI. Nie zmniejszono jakości obrazu.");
    const centerX=(options.bounds[0]+options.bounds[2])/2;
    const centerY=(options.bounds[1]+options.bounds[3])/2;
    const tiles=[];
    for(let row=0;row<rows;row++)for(let col=0;col<columns;col++){
      const x0=Math.floor(options.width*col/columns);
      const x1=Math.floor(options.width*(col+1)/columns);
      const y0=Math.floor(options.height*row/rows);
      const y1=Math.floor(options.height*(row+1)/rows);
      const width=x1-x0,height=y1-y0;
      const px=options.pxPerUnit;
      const bounds=[
        centerX+(x0-options.width/2)/px,
        centerY+(y0-options.height/2)/px,
        centerX+(x1-options.width/2)/px,
        centerY+(y1-options.height/2)/px
      ];
      const item={...options,bounds,width,height,
        fullWidth:width+options.margin*2+options.legend,
        fullHeight:height+options.head+options.foot,
        tiled:false,partLabel:"Arkusz "+(tiles.length+1)+"/"+(rows*columns)};
      if(item.fullWidth*item.fullHeight>40000000||
         item.fullWidth>12000||item.fullHeight>12000)
        throw Error("Wewnętrzny limit pojedynczego arkusza.");
      tiles.push(item);
    }
    return {columns,rows,tiles};
  }
  function tiledExportManifest(options,plan){
    const lines=[
      "GeoStudio 2.0 — eksport dużej mapy",
      "Mapę podzielono na arkusze bez obniżania rozdzielczości.",
      "Kolejność: najpierw wiersze z góry na dół, potem kolumny od lewej.",
      "Opracowanie 1:"+options.denominator+", "+
        options.dpi+" DPI, format "+options.format.toUpperCase(),
      "Łączny obraz mapy: "+options.width+" x "+options.height+" pikseli",
      "Arkusze: "+plan.columns+" kolumn, "+plan.rows+" wierszy",
      "Zakres (osie ekranu GEO-MAP): "+options.bounds.join(", "),
      "Arkusze zawierają własne ramki, legendy i inne wybrane dodatki.",
      "",
      "Plik; xmin; ymin; xmax; ymax"
    ];
    const ext={jpeg:"jpg",tiff:"tif",png:"png"}[options.format];
    for(let i=0;i<plan.tiles.length;i++){
      const tile=plan.tiles[i];
      const r=Math.floor(i/plan.columns)+1,c=i%plan.columns+1;
      lines.push("mapa_r"+String(r).padStart(3,"0")+"_c"+
        String(c).padStart(3,"0")+"."+ext+"; "+tile.bounds.join("; "));
    }
    return lines.join("\n");
  }
  async function encodeLayoutRaster(image,options){
    const raw=options.format==="tiff"
      ?makeRGBTiff(image,options.dpi)
      :await canvasBlob(image,options.format==="jpeg"?"image/jpeg":"image/png",
        options.format==="jpeg"?.96:undefined);
    return options.format==="tiff"?raw:
      withRasterDpi(raw,options.format==="jpeg"?"jpeg":"png",options.dpi);
  }
  async function saveTiledArchive(ticket,filename){
    if(nativeAPI()?.save_tiled_export){
      exportInfo("Wybierz miejsce zapisu dużej mapy ZIP…");
      const result=await nativeAPI().save_tiled_export(ticket);
      if(!result||result.cancelled)return false;
      inform("Zapisano arkusze mapy: "+result.path+".");
      return true;
    }
    const response=await documentFetch("/api/export/tiles/"+ticket+"/download",{
      headers:{"X-GeoStudio-Token":token},cache:"no-store"
    });
    if(!response.ok){
      const message=await response.json().catch(()=>({}));
      throw Error(message.detail||"Nie można pobrać archiwum ZIP.");
    }
    if(window.showSaveFilePicker&&response.body){
      const handle=await window.showSaveFilePicker({
        suggestedName:filename,
        types:[{description:"Archiwum ZIP",accept:{"application/zip":[".zip"]}}]
      });
      const file=await handle.createWritable();
      try{
        await response.body.pipeTo(file);
      }catch(error){
        await file.abort().catch(()=>{});
        throw error;
      }
      return true;
    }
    const blob=await response.blob();
    const url=URL.createObjectURL(blob);
    const a=document.createElement("a");
    a.href=url;a.download=filename;document.body.append(a);
    a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
    return true;
  }
  async function exportTiledLayout(options,basename){
    const plan=planRasterTiles(options);
    const session=await api("/api/export/tiles/start",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        documentToken:state.edit.documentToken,
        revision:state.edit.revision,
        filename:basename,format:options.format,
        columns:plan.columns,rows:plan.rows,
        manifest:tiledExportManifest(options,plan)
      })
    });
    const ticket=session.ticket;
    const tokenAtStart=state.edit.documentToken;
    const revisionAtStart=state.edit.revision;
    for(let i=0;i<plan.tiles.length;i++){
      if(state.edit?.documentToken!==tokenAtStart||
         state.edit?.revision!==revisionAtStart)
        throw Error("Mapa zmieniła się podczas eksportu. Spróbuj ponownie.");
      const tile=plan.tiles[i];
      exportInfo("Arkusz "+(i+1)+"/"+plan.tiles.length+
        " · "+tile.width+" × "+tile.height+" px · "+options.dpi+" DPI");
      const raster=await renderLayoutCanvas(tile);
      const blob=await encodeLayoutRaster(raster,options);
      // Each upload is bounded to at most 120 MB; the ZIP is assembled
      // on disk and never passed through the small-image Save As buffer.
      await api("/api/export/tiles/"+ticket+"/part/"+i,{
        method:"POST",body:blob
      });
      raster.width=0;raster.height=0;
    }
    const complete=await api("/api/export/tiles/"+ticket+"/finish",{
      method:"POST"
    });
    exportInfo("Gotowe: "+complete.tiles+" arkuszy. Wybierz zapis ZIP.");
    return saveTiledArchive(ticket,complete.filename);
  }

  function planSingleTiffTiles(options){
    // A TIFF is ONE global sheet. Tiles exist only during rendering;
    // margins, legend, title, frame and A1/A2 stay global and continuous.
    const tileWidth=2048,tileHeight=2048;
    const columns=Math.ceil(options.fullWidth/tileWidth);
    const rows=Math.ceil(options.fullHeight/tileHeight);
    if(columns*rows>1024)
      throw Error("Pojedynczy TIFF wymaga ponad 1024 fragmentów. "+
        "Zmniejsz zakres lub DPI.");
    const centerX=(options.bounds[0]+options.bounds[2])/2;
    const centerY=(options.bounds[1]+options.bounds[3])/2;
    const pixelWorld=x=>centerX+
      (x-options.margin-options.width/2)/options.pxPerUnit;
    const pixelWorldY=y=>centerY+
      (y-options.head-options.height/2)/options.pxPerUnit;
    const overlap=512; // Neighboring labels/lines cross internal tile edges.
    const tiles=[];
    for(let row=0;row<rows;row++)for(let col=0;col<columns;col++){
      const x=col*tileWidth,y=row*tileHeight;
      const width=Math.min(tileWidth,options.fullWidth-x);
      const height=Math.min(tileHeight,options.fullHeight-y);
      tiles.push({
        ...options,fullWidth:width,fullHeight:height,
        queryBounds:[
          pixelWorld(x-overlap),pixelWorldY(y-overlap),
          pixelWorld(x+width+overlap),pixelWorldY(y+height+overlap)
        ],
        virtualLayout:{x,y,full:options}
      });
    }
    return {tileWidth,tileHeight,columns,rows,tiles};
  }
  function mosaicRGBBlob(canvas){
    // Transfer only RGB bytes of a small bounded canvas; no TIFF tile
    // wrappers or duplicated 13mm margins appear in the final image.
    const {width,height}=canvas;
    const pixels=canvas.getContext("2d",{willReadFrequently:true})
      .getImageData(0,0,width,height).data;
    const rgb=new Uint8Array(width*height*3);
    for(let i=0,j=0;i<pixels.length;i+=4){
      rgb[j++]=pixels[i];rgb[j++]=pixels[i+1];rgb[j++]=pixels[i+2];
    }
    return new Blob([rgb],{type:"application/octet-stream"});
  }
  async function saveSingleMosaicTiff(ticket,filename){
    if(nativeAPI()?.save_tiled_export){
      exportInfo("Wybierz miejsce zapisu jednego obrazu…");
      const result=await nativeAPI().save_tiled_export(ticket);
      if(!result||result.cancelled)return false;
      inform("Zapisano całą mapę do pliku: "+result.path+".");
      return true;
    }
    // Browser mode streams to disk; it must not buffer a gigabyte TIFF Blob.
    if(!window.showSaveFilePicker)
      throw Error("Zapis dużego obrazu wymaga aplikacji GeoStudio Windows "+
        "lub przeglądarki obsługującej zapis strumieniowy.");
    const handle=await window.showSaveFilePicker({
      suggestedName:filename,
      types:[{description:"Obraz mapy",accept:{[{"tif":"image/tiff","jpg":"image/jpeg","png":"image/png"}[filename.split(".").pop()]]:["."+filename.split(".").pop()]}}]
    });
    const response=await documentFetch("/api/export/mosaic/"+ticket+"/download",{
      headers:{"X-GeoStudio-Token":token},cache:"no-store"
    });
    if(!response.ok||!response.body){
      const message=await response.json().catch(()=>({}));
      throw Error(message.detail||"Nie można pobrać dużego obrazu.");
    }
    const file=await handle.createWritable();
    try{
      await response.body.pipeTo(file);
    }catch(error){
      await file.abort().catch(()=>{});
      throw error;
    }
    return true;
  }
  async function exportSingleMosaicTiff(options,basename){
    const plan=planSingleTiffTiles(options);
    const start=await api("/api/export/mosaic/start",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({
        documentToken:state.edit.documentToken,
        revision:state.edit.revision,
        filename:basename,width:options.fullWidth,
        height:options.fullHeight,dpi:options.dpi,
        format:options.format,tileWidth:plan.tileWidth,tileHeight:plan.tileHeight
      })
    });
    const ticket=start.ticket,documentToken=state.edit.documentToken;
    const revision=state.edit.revision;
    for(let i=0;i<plan.tiles.length;i++){
      if(state.edit?.documentToken!==documentToken||
         state.edit?.revision!==revision)
        throw Error("Mapa zmieniła się podczas eksportu TIFF.");
      exportInfo("Pełny obraz · składanie obrazu "+(i+1)+"/"+
        plan.tiles.length+" · "+options.dpi+" DPI");
      const canvasTile=await renderLayoutCanvas(plan.tiles[i]);
      const blob=mosaicRGBBlob(canvasTile);
      canvasTile.width=0;canvasTile.height=0;
      await api("/api/export/mosaic/"+ticket+"/part/"+i,{
        method:"POST",body:blob
      });
    }
    const finished=await api("/api/export/mosaic/"+ticket+"/finish",{
      method:"POST"
    });
    exportInfo("Gotowy obraz "+options.fullWidth+" × "+
      options.fullHeight+" px. Wybierz miejsce zapisu.");
    return saveSingleMosaicTiff(ticket,finished.filename);
  }

  async function downloadLayoutFile(blob,filename){
    // WebView2 may silently ignore browser-only download links. Use the same
    // native Save As mechanism as MAP for a guaranteed chosen Windows path.
    if(nativeAPI()?.save_generated_export){
      exportInfo("Wybierz miejsce zapisu w oknie systemu Windows…");
      const extension=filename.split(".").pop().toLowerCase();
      const response=await documentFetch("/api/export/buffer",{
        method:"POST",
        headers:{
          "X-GeoStudio-Token":token,
          "X-Export-Name":encodeURIComponent(filename),
          "X-Export-Format":extension,
          "X-Document-Token":state.edit.documentToken,
          "X-Document-Revision":String(state.edit.revision)
        },
        body:blob,cache:"no-store"
      });
      if(!response.ok){
        const problem=await response.json().catch(()=>({}));
        throw Error(problem.detail||"Nie udało się przygotować zapisu.");
      }
      const {ticket}=await response.json();
      const saved=await nativeAPI().save_generated_export(ticket);
      if(!saved||saved.cancelled)return false;
      inform("Zapisano eksport: "+saved.path+" ("+display(saved.bytes)+" B).");
      return true;
    }
    const uri=URL.createObjectURL(blob),a=document.createElement("a");
    a.href=uri;a.download=filename;document.body.append(a);
    a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(uri),60000);
    return true;
  }
  async function printLayoutImage(blob,options){
    // A print iframe is separate from map Canvas; the map stays editable.
    const uri=URL.createObjectURL(blob);
    const iframe=document.createElement("iframe");
    iframe.title="GeoStudio — wydruk arkusza";
    iframe.style.position="fixed";iframe.style.width="1px";
    iframe.style.height="1px";iframe.style.left="-10000px";
    iframe.style.top="0";iframe.style.border="0";
    document.body.append(iframe);
    const doc=iframe.contentDocument;
    doc.open();doc.write("<!DOCTYPE html><html><head><title>GeoStudio - mapa</title></head><body></body></html>");doc.close();
    doc.body.style.margin="0";
    const img=doc.createElement("img");
    img.alt="Arkusz mapy GeoStudio";
    img.style.display="block";img.style.width=
      (options.fullWidth*25.4/options.dpi).toFixed(2)+"mm";
    img.style.height=
      (options.fullHeight*25.4/options.dpi).toFixed(2)+"mm";
    img.onload=()=>{
      setTimeout(()=>{
        try{iframe.contentWindow.focus();iframe.contentWindow.print();}
        catch(err){inform("Okno druku zablokowane: "+err.message,true);}
      },150);
    };
    img.onerror=()=>inform("Nie udało się przygotować podglądu wydruku.",true);
    doc.body.append(img);img.src=uri;
    const cleanup=()=>{setTimeout(()=>{
      iframe.remove();URL.revokeObjectURL(uri);
    },1500);};
    iframe.contentWindow.addEventListener("afterprint",cleanup,{once:true});
    setTimeout(cleanup,90000);
  }
  async function exportLayout(print=false){
    if(!state.meta||!state.edit||state.editBusy)return;
    const button=$("layout-export"),printButton=$("layout-print");
    let options;
    try{
      options=$("layout-format").value==="pdf"
        ?pdfLayoutOptions():layoutOptions();
    }catch(error){exportInfo(error.message);inform(error.message,true);return;}
    if(print&&options.format==="dxf"){
      inform("Druk wymaga obrazu. Wybierz PNG, JPG, TIFF lub PDF.",true);return;
    }
    if(print&&options.tiled){
      inform("Wielkoformatowy druk wykonaj z PDF wektorowego; "+
        "eksport zapisze całą mapę w jednym obrazie.",true);
      return;
    }
    button.disabled=true;printButton.disabled=true;
    try{
      const basename=state.meta.name.replace(/\.map$/i,"")
        .replace(/[^a-zA-Z0-9\p{L}\p{N}._ -]+/gu,"_").slice(0,90)||
        "GeoStudio";
      if(options.format==="pdf"){
        exportInfo("Generowanie wektorowego PDF z mapą, legendą i ramką…");
        const response=await documentFetch("/api/export/pdf",{
          method:"POST",
          headers:{"X-GeoStudio-Token":token,
                   "Content-Type":"application/json"},
          body:JSON.stringify({
            documentToken:state.edit.documentToken,options
          }),
          cache:"no-store"
        });
        if(!response.ok){
          const data=await response.json().catch(()=>({}));
          throw Error(data.detail||"Nie można wygenerować arkusza PDF.");
        }
        const ok=await downloadLayoutFile(await response.blob(),
          basename+"_arkusz.pdf");
        if(!ok){exportInfo("Anulowano zapis PDF.");return;}
        if(print)inform("Zapisano wektorowy PDF. Otwórz go i drukuj "+
          "w rozmiarze 100% bez dopasowania do papieru.");
      }else if(!print&&options.format==="dxf"){
        exportInfo("Generowanie edytowalnego DXF…");
        const query=new URLSearchParams({
          documentToken:state.edit.documentToken,
          bounds:JSON.stringify(selectedExportBounds())});
        const response=await documentFetch("/api/export/dxf?"+query.toString(),{
          headers:{"X-GeoStudio-Token":token},cache:"no-store"});
        if(!response.ok){
          const data=await response.json().catch(()=>({}));
          throw Error(data.detail||"Nie udało się wyeksportować DXF.");
        }
        if(!await downloadLayoutFile(await response.blob(),basename+".dxf")){
          exportInfo("Anulowano zapis DXF.");return;
        }
      }else if(options.tiled){
        const saved=await exportSingleMosaicTiff(options,basename);
        if(!saved){exportInfo("Anulowano zapis eksportu.");return;}
      }else{
        const raster=await renderLayoutCanvas(options);
        const raw=(print||options.format==="png")
          ?await canvasBlob(raster,"image/png")
          :options.format==="jpeg"
            ?await canvasBlob(raster,"image/jpeg",.96)
            :makeRGBTiff(raster,options.dpi);
        const blob=(print||options.format==="png")
          ?await withRasterDpi(raw,"png",options.dpi)
          :options.format==="jpeg"
            ?await withRasterDpi(raw,"jpeg",options.dpi):raw;
        if(print)await printLayoutImage(blob,options);
        else if(!await downloadLayoutFile(blob,basename+"."+
          (options.format==="jpeg"?"jpg":options.format==="tiff"?"tif":"png"))){
          exportInfo("Anulowano zapis obrazu.");return;
        }
      }
      // Clear successful export selection, leaving the working map intact.
      state.exportAreaBounds=null;state.exportAreaDrag=null;state.exportAreaPicking=false;
      $("layout-scope").value="all";updateExportAreaControls();requestDraw();
      exportInfo(print
        ?"Przekazano arkusz do okna drukowania. Wybierz skalowanie 100%."
        :"Wysłano plik do pobrania. Oryginalny MAP nie został zmieniony.");
      inform(print?"Otworzono wydruk. Sprawdź skalowanie 100% przed zatwierdzeniem."
        :"Przygotowano eksport "+options.format.toUpperCase()+".");
    }catch(error){
      exportInfo("Eksport nieudany: "+error.message);
      inform("Eksport nieudany: "+error.message,true);
    }finally{button.disabled=false;printButton.disabled=false;}
  }

  // Stage 15: non-destructive map audit; all positions are normal Canvas world
  // coordinates (easting Y, -northing X), never native P record mutations.
  const auditNames={
    duplicate:"Duplikat",overlap:"Nakładka",gap:"Szczelina",
    open:"Otwarty obrys",invalid:"Niepoprawny obrys",node:"Wspólny węzeł"
  };
  function openTopologyPanel(scan=false){
    $("topology-panel").hidden=false;
    if(!state.meta){
      $("topology-status").textContent="Najpierw otwórz plik MAP.";
      return;
    }
    if(scan||!state.auditReport)scanTopology();
    else renderTopologyIssues();
  }
  function closeTopologyPanel(){
    $("topology-panel").hidden=true;
    state.auditActiveIssue=null;
    requestDraw();
  }
  async function scanTopology(){
    if(!state.meta||!state.edit){
      inform("Najpierw otwórz mapę do kontroli.",true);return;
    }
    if(state.auditBusy)return;
    const tokenAtStart=state.edit.documentToken;
    const revisionAtStart=state.edit.revision;
    state.auditBusy=true;
    $("topology-rescan").disabled=true;
    $("tool-topology-scan").disabled=true;
    $("topology-status").textContent="Sprawdzam geometrię i topologię kodu 5310…";
    $("topology-issues").replaceChildren();
    $("topology-edit").disabled=true;
    $("topology-delete-duplicate").hidden=true;
    try{
      const query=new URLSearchParams({
        documentToken:tokenAtStart,revision:String(revisionAtStart),
        limit:"600"
      });
      const report=await api("/api/topology/audit?"+query);
      if(state.edit?.documentToken!==tokenAtStart||
         state.edit?.revision!==revisionAtStart)
        return;
      state.auditReport=report;
      state.auditActiveIssue=null;
      $("topology-found").textContent=display(report.detected);
      $("topology-checked").textContent=display(report.checked);
      const partial=report.truncated||report.skippedObjects>0;
      $("topology-status").textContent=
        "Znaleziono "+display(report.detected)+" potencjalnych problemów."+
        (partial?" Raport częściowy — osiągnięto limit analizy.":"")+
        " Kliknij wynik, aby go zobaczyć na mapie.";
      renderTopologyIssues();
    }catch(error){
      $("topology-status").textContent="Nie można ukończyć kontroli: "+error.message;
      inform("Kontrola mapy: "+error.message,true);
    }finally{
      state.auditBusy=false;
      if(!$("topology-panel").hidden && (state.edit?.revision!==revisionAtStart || state.edit?.documentToken!==tokenAtStart))queueMicrotask(scanTopology);
      $("topology-rescan").disabled=false;
      $("tool-topology-scan").disabled=false;
    }
  }
  function renderTopologyIssues(){
    const list=$("topology-issues");
    list.replaceChildren();
    const report=state.auditReport;
    if(!report)return;
    const filter=$("topology-filter").value;
    const shown=report.issues.filter(issue=>
      filter==="all"||issue.kind===filter);
    if(!shown.length){
      const message=document.createElement("p");
      message.className="topology-empty";
      message.textContent=report.issues.length
        ?"Brak wyników tego typu. Wybierz inny filtr."
        :"Nie znaleziono błędów w sprawdzonym zakresie.";
      list.append(message);
      return;
    }
    for(const issue of shown){
      const button=document.createElement("button");
      button.type="button";button.className="topology-issue";
      button.classList.toggle("active",state.auditActiveIssue?.id===issue.id);
      button.dataset.kind=issue.kind;
      button.setAttribute("aria-label",issue.title+
        ". Kod "+issue.code+". "+issue.description);
      const top=document.createElement("span");
      top.className="topology-issue-top";
      const kind=document.createElement("span");
      kind.className="topology-type";kind.textContent=auditNames[issue.kind]||issue.kind;
      const code=document.createElement("span");
      code.className="topology-code";code.textContent="Kod "+issue.code;
      top.append(kind,code);
      const title=document.createElement("strong");title.textContent=issue.title;
      const detail=document.createElement("span");
      detail.className="topology-issue-detail";
      detail.textContent=issue.description;
      const ids=document.createElement("small");
      ids.textContent="Obiekty: "+issue.ids.join(", ")+
        (Number.isFinite(issue.areaM2)?" · "+issue.areaM2+" m²":"");
      button.append(top,title,detail,ids);
      button.addEventListener("click",()=>focusTopologyIssue(issue));
      list.append(button);
    }
  }
  async function focusTopologyIssue(issue){
    if(!state.meta||!state.auditReport||
       state.edit?.revision!==state.auditReport.revision||
       state.edit?.documentToken!==state.auditReport.documentToken){
      inform("Raport jest nieaktualny. Uruchom kontrolę ponownie.",true);
      return;
    }
    state.auditActiveIssue=issue;
    const box=issue.bounds;
    if(Array.isArray(box)&&box.length===4){
      const dx=Math.max(.05,box[2]-box[0]);
      const dy=Math.max(.05,box[3]-box[1]);
      state.center={
        x:(box[0]+box[2])/2,
        y:(box[1]+box[3])/2
      };
      let target=Math.min(
        Math.max(100,state.width-120)/dx,
        Math.max(100,state.height-120)/dy
      );
      if(["gap","node"].includes(issue.kind)){
        if(issue.location){
          state.center={x:issue.location.x,y:issue.location.y};
        }
        target=Math.max(target,Math.min(1000,Math.max(12,state.scale)));
      }
      state.scale=Math.max(.000001,Math.min(3500,target));
      requestDraw();
      scheduleViewport(true);
    }
    // For duplicates always select the SECOND instance so the first remains
    // the protected reference in the explicit "Usuń duplikat" workflow.
    const fid=issue.canDeleteDuplicate&&issue.ids.length===2
      ?issue.ids[1]:issue.ids[0];
    state.pinned.clear();
    await selectFeature(fid);
    renderTopologyIssues();
    $("topology-edit").disabled=issue.kind==="open";
    const remove=$("topology-delete-duplicate");
    remove.hidden=!issue.canDeleteDuplicate;
    remove.disabled=!issue.canDeleteDuplicate||state.editBusy;
    $("topology-action-hint").textContent=
      issue.canDeleteDuplicate
        ?"Wskazano drugi, powielony obiekt. Możesz go usunąć w kopii roboczej. Ctrl+Z cofa."
        :issue.kind==="open"
          ?"Obrys nie jest zamknięty. Sprawdź linię i popraw jej geometrię w narzędziach rysowania."
          :"Przejdź do edycji węzłów (P), sprawdź połączenie i popraw ręcznie. Ctrl+Z cofa.";
  }
  function editTopologyIssue(){
    const issue=state.auditActiveIssue;
    if(!issue||state.editBusy)return;
    if(issue.kind==="open"){
      inform("Ten obiekt jest otwarty. Zweryfikuj, czy powinien być linią czy poligonem.",true);
      return;
    }
    setTool("nodes");
    inform("Edycja problemu topologicznego: użyj trybu P, "+
      "wspólnych węzłów wyłącznie dla tego samego kodu i Ctrl+Z.");
  }
  async function removeTopologyDuplicate(){
    const issue=state.auditActiveIssue;
    const report=state.auditReport;
    if(!issue||!issue.canDeleteDuplicate||issue.ids.length!==2||
       !report||state.edit?.revision!==report.revision||
       state.edit?.documentToken!==report.documentToken){
      inform("Najpierw ponów kontrolę mapy.",true);
      return;
    }
    if(state.editBusy)return;
    // Deleting through the existing preview/apply workflow preserves
    // the same MAP transaction history and undo rules as the Del key.
    const revision=state.edit.revision;
    state.pinned.clear();
    const fid=issue.ids[1];
    await selectFeature(fid);
    if(state.edit?.revision!==revision)return;
    await deleteObjects();
    if(state.edit?.revision!==revision){
      $("topology-action-hint").textContent=
        "Usunięto wskazany duplikat w kopii roboczej. Ctrl+Z przywraca.";
      await scanTopology();
    }
  }
  function drawTopologyHighlight(features){
    const issue=state.auditActiveIssue;
    if(!issue||!state.auditReport||
       state.auditReport.revision!==state.edit?.revision)return;
    const marked=new Set(issue.ids);
    ctx.save();
    ctx.lineWidth=3.3;ctx.strokeStyle="#f06438";
    ctx.setLineDash([9,5]);
    for(const feature of features){
      if(!marked.has(feature.id))continue;
      for(const part of feature.geometry){
        if(!part.length)continue;
        ctx.beginPath();
        const first=worldToScreen(part[0][0],part[0][1]);
        ctx.moveTo(first.x,first.y);
        for(let i=1;i<part.length;i++){
          const p=worldToScreen(part[i][0],part[i][1]);
          ctx.lineTo(p.x,p.y);
        }
        if(feature.closed)ctx.closePath();
        ctx.stroke();
      }
    }
    ctx.setLineDash([]);
    if(issue.location){
      const pos=worldToScreen(issue.location.x,issue.location.y);
      ctx.beginPath();ctx.arc(pos.x,pos.y,10,0,Math.PI*2);
      ctx.fillStyle="#fff";ctx.fill();
      ctx.lineWidth=3;ctx.strokeStyle="#e84b23";ctx.stroke();
      ctx.beginPath();ctx.moveTo(pos.x-16,pos.y);ctx.lineTo(pos.x+16,pos.y);
      ctx.moveTo(pos.x,pos.y-16);ctx.lineTo(pos.x,pos.y+16);
      ctx.lineWidth=1.5;ctx.stroke();
    }
    ctx.restore();
  }

  function layerDisclosure(details,expanded,onToggle,label){
    const button=document.createElement("button");
    button.type="button";button.className="layer-disclosure";
    button.setAttribute("aria-controls",details.id);
    const update=()=>{
      details.hidden=!expanded;
      button.setAttribute("aria-expanded",String(expanded));
      button.setAttribute("aria-label",(expanded?"Zwiń ":"Rozwiń ")+label);
    };
    // CSS chevron uses currentColor and rotates with aria-expanded.
    const arrow=document.createElement("span");arrow.className="layer-chevron";
    arrow.setAttribute("aria-hidden","true");button.append(arrow);
    button.addEventListener("click",()=>{
      expanded=!expanded;onToggle(expanded);update();
    });
    update();return button;
  }
  function buildLayer(name,count,filter="") {
    const item=document.createElement("div");
    item.className="layer-item";
    const row=document.createElement("div");row.className="layer-row";
    const main=document.createElement("label");main.className="layer-main";
    const toggle=document.createElement("input");
    toggle.type="checkbox";toggle.className="layer-toggle";
    toggle.checked=state.visibleLayers.has(name);
    const landUses=name==="Użytki"?(state.meta?.landUseClasses||[]):[];
    const visibleCount=()=>landUses.reduce((n,entry)=>
      n+(state.hiddenLandUses.has(entry.key)?0:entry.count),0);
    toggle.indeterminate=!!landUses.length&&toggle.checked&&
      visibleCount()<count;
    toggle.setAttribute("aria-label","Pokaż lub ukryj warstwę "+name);
    toggle.addEventListener("change",()=>{
      if(toggle.checked)state.visibleLayers.add(name);
      else state.visibleLayers.delete(name);
      toggle.indeterminate=!!landUses.length&&toggle.checked&&
        visibleCount()<count;
      item.classList.toggle("layer-muted",!toggle.checked);
      renderCartographyMatches();requestDraw();refreshInspectorVisibility();
    });
    const swatch=document.createElement("span");swatch.className="layer-swatch";
    const hue=colorForLayer(name);
    swatch.style.backgroundColor=hue;swatch.style.borderColor=hue;
    const label=document.createElement("span");label.className="layer-name";
    label.textContent=name;
    const countBadge=document.createElement("span");
    countBadge.className="layer-count";
    const refreshCount=()=>{
      countBadge.textContent=landUses.length&&visibleCount()<count
        ?display(visibleCount())+"/"+display(count)
        :display(count);
    };
    refreshCount();
    main.append(toggle,swatch,label,countBadge);
    row.append(main);
    item.append(row);
    item.classList.toggle("layer-muted",!toggle.checked);

    if(landUses.length){
      const expanded=state.expandedLandUses||!!filter;
      const details=document.createElement("div");
      details.className="landuse-list";details.id="landuse-classes-list";
      details.hidden=!expanded;
      row.append(layerDisclosure(details,expanded,
        value=>{state.expandedLandUses=value;},"klasy użytków"));
      const heading=document.createElement("div");
      heading.className="landuse-list-heading";
      heading.textContent="KLASY BONITACYJNE A2 · "+landUses.length;
      details.append(heading);
      for(const landUse of landUses){
        if(filter&&!landUse.label.toLocaleLowerCase("pl-PL").includes(filter)&&
           !name.toLocaleLowerCase("pl-PL").includes(filter))continue;
        const line=document.createElement("label");
        line.className="landuse-row";
        const checkbox=document.createElement("input");
        checkbox.type="checkbox";checkbox.className="grade-toggle landuse-toggle";
        checkbox.checked=!state.hiddenLandUses.has(landUse.key);
        checkbox.setAttribute("aria-label","Pokaż użytek "+landUse.label);
        const className=document.createElement("span");
        className.className="landuse-class-name";
        className.textContent=landUse.label;
        const amount=document.createElement("span");
        amount.className="landuse-count";
        amount.textContent=display(landUse.count);
        checkbox.addEventListener("change",()=>{
          if(checkbox.checked)state.hiddenLandUses.delete(landUse.key);
          else state.hiddenLandUses.add(landUse.key);
          toggle.indeterminate=toggle.checked&&visibleCount()<count;
          refreshCount();
          renderCartographyMatches();requestDraw();refreshInspectorVisibility();
        });
        line.append(checkbox,className,amount);
        details.append(line);
      }
      item.append(details);
    }
    if(name==="Użytki Leśne"&&state.meta&&
       Object.keys(state.meta.forestClasses).length){
      const grades=document.createElement("div");
      grades.className="layer-grades";grades.id="forest-classes-list";
      row.append(layerDisclosure(grades,state.expandedForest||!!filter,
        value=>{state.expandedForest=value;},"klasy użytków leśnych"));
      for(const [grade,amount] of Object.entries(state.meta.forestClasses)){
        if(filter&&!grade.toLocaleLowerCase("pl-PL").includes(filter)&&
           !name.toLocaleLowerCase("pl-PL").includes(filter))continue;
        const line=document.createElement("label");line.className="grade-row";
        const input=document.createElement("input");
        input.type="checkbox";input.className="grade-toggle";
        input.checked=!state.hiddenGrades.has(grade);
        input.addEventListener("change",()=>{
          if(input.checked)state.hiddenGrades.delete(grade);
          else state.hiddenGrades.add(grade);
          renderCartographyMatches();requestDraw();refreshInspectorVisibility();
        });
        const nameNode=document.createElement("b");nameNode.textContent=grade;
        const badge=document.createElement("em");
        badge.textContent=display(amount);
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
      const matchesName=layer.name.toLocaleLowerCase("pl-PL").includes(needle);
      const matchesUse=layer.name==="Użytki"&&
        (state.meta.landUseClasses||[]).some(item=>
          item.label.toLocaleLowerCase("pl-PL").includes(needle));
      const matchesForest=layer.name==="Użytki Leśne"&&
        Object.keys(state.meta.forestClasses||{}).some(grade=>
          grade.toLocaleLowerCase("pl-PL").includes(needle));
      if(needle&&!matchesName&&!matchesUse&&!matchesForest)continue;
      list.append(buildLayer(layer.name,layer.count,needle));found++;
    }
    if(!found){
      const message=document.createElement("div");
      message.className="panel-placeholder";
      message.textContent="Brak warstw lub klas użytków pasujących do wyszukiwania.";
      list.append(message);
    }
  }
  function showAllLayers() {
    if(!state.meta)return;
    state.visibleLayers=new Set(state.meta.layers.map(layer=>layer.name));
    state.hiddenGrades.clear();state.hiddenLandUses.clear();
    renderLayers();renderCartographyMatches();requestDraw();
    inform("Wszystkie warstwy i klasy użytków są widoczne.");
  }
  function refreshInspectorVisibility() {
    if(state.detail&&(!state.visibleLayers.has(state.detail.layer)||
       (state.detail.grade&&state.hiddenGrades.has(state.detail.grade))||
       (state.detail.layer==="Użytki"&&state.hiddenLandUses.has(
         String(state.detail.fields?.A2||"").trim().toLocaleLowerCase("pl-PL"))))){
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
    updateBulkButton();
    $("tool-move-offset").disabled=!state.meta||state.editBusy||n===0;
    $("tool-copy").disabled=!state.meta||state.editBusy||n===0;
    $("tool-delete-objects").disabled=!state.meta||state.editBusy||n===0;
  }
  function togglePickedFeature(fid){
      const selection=new Set(state.pinned);
      if(state.active)selection.add(state.active);
      const wasSelected=selection.has(fid);
      if(wasSelected)selection.delete(fid);else selection.add(fid);
      state.pinned=selection;
      const next=wasSelected?
        (selection.has(state.active)?state.active:
          (selection.values().next().value||null)):fid;
      selectFeature(next);
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
  function pickLabelAt(screen) {
    return state.labelHits.filter(hit=>
      screen.x>=hit.rect[0]-5&&screen.x<=hit.rect[2]+5&&
      screen.y>=hit.rect[1]-5&&screen.y<=hit.rect[3]+5
    ).sort((a,b)=>{
      const rank=item=>item.fid===state.active?0:1;
      const cx=item=>(item.rect[0]+item.rect[2])/2;
      const cy=item=>(item.rect[1]+item.rect[3])/2;
      return rank(a)-rank(b)||
        Math.hypot(screen.x-cx(a),screen.y-cy(a))-
        Math.hypot(screen.x-cx(b),screen.y-cy(b));
    })[0]||null;
  }
  async function commitLabelDrag(drag) {
    if(!drag||state.editBusy)return;
    const x=Math.round(-drag.label.y*1000)/1000;
    const y=Math.round(drag.label.x*1000)/1000;
    const body={...editRequestBody(),
      fid:drag.fid,field:drag.field,x,y};
    state.editBusy=true;updateEditState(state.edit);
    try{
      const result=await api("/api/labels/move",{
        method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify(body)
      });
      updateEditState(result);
      await refreshEditedDocument(drag.fid);
      inform("Przeniesiono osobną etykietę "+drag.field+
        " na X: "+x.toFixed(3)+", Y: "+y.toFixed(3)+
        ". Ctrl+Z cofa. Zapisz MAP i towarzyszący JSON.");
    }catch(error){
      drag.label.x=drag.origin.x;drag.label.y=drag.origin.y;
      drag.label.offset=drag.origin.offset;
      drag.label.manuallyPlaced=drag.origin.manuallyPlaced;
      inform("Etykieta nie została przeniesiona: "+error.message,true);
      scheduleViewport(true);
    }finally{
      state.editBusy=false;updateEditState(state.edit);
      requestDraw();
    }
  }

  function eventCoords(ev){
    const box=canvas.getBoundingClientRect();
    return {x:ev.clientX-box.left,y:ev.clientY-box.top};
  }
  let pendingSheet=null,selectedSheet=null,sheetDrag=null,sheetSaving=false,sheetSize=1;
  const insertMode=()=>!$("ribbon-panel-insert").hidden;
  function sheetItems(){
    return (state.edit?.sheetItems||[]).map(i=>sheetDrag?.item.id===i.id?sheetDrag.item:i);
  }
  function drawSheetItems(){
    const items=sheetItems(),selected=items.find(i=>i.id===selectedSheet);
    $("sheet-edit").disabled=!selected||GeoStudioSheet.signs.includes(selected.kind);
    $("sheet-remove").disabled=!selected;
    GeoStudioSheet.paint(ctx,items,worldToScreen,state.scale,state.edit?.compilationScale||5000,insertMode()?selectedSheet:null);
  }
  async function saveSheet(items){
    if(sheetSaving||state.editBusy)return;
    sheetSaving=true;
    try{
      const res=await api("/api/sheet-items",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({...editRequestBody(),items})});
      if(res.documentToken===state.edit?.documentToken){updateEditState(res);await refreshEditedDocument(null);return true;}
    }catch(err){inform(err.message,true);}
    finally{sheetSaving=false;requestDraw();}
  }
  let numberPlacement=null;
  $("sheet-number-cancel").onclick=()=>$("sheet-number-dialog").close("cancel");
  $("sheet-number-dialog").addEventListener("close",()=>{
    const placed=numberPlacement;numberPlacement=null;
    if(!placed||$("sheet-number-dialog").returnValue!=="save"||placed.token!==state.edit?.documentToken)return;
    placed.item.text=$("sheet-number").value.trim();
    if(placed.item.text){placed.item.h=Number($("sheet-number-size").value)/12*GeoStudioSheet.sizes.compartment[1]/state.scale;placed.item.w=GeoStudioSheet.sizes.compartment[0]/GeoStudioSheet.sizes.compartment[1]*placed.item.h;saveSheet([...sheetItems(),placed.item]);}
  });
  $("sheet-size-factor").oninput=e=>{sheetSize=Number(e.target.value);$("sheet-size-value").value=Math.round(sheetSize*100)+"%";};
  $("sheet-place-sign").onclick=()=>{
    if(!state.meta)return inform("Najpierw otwórz mapę.",true);
    pendingSheet=$("sheet-sign").value;inform("Klikaj mapę, aby wstawiać kolejne oznaczenia. Naciśnij Esc lub wybierz inne narzędzie, aby zakończyć.");
  };
  for(const btn of document.querySelectorAll("[data-sheet]"))btn.addEventListener("click",()=>{
    if(!state.meta)return inform("Najpierw otwórz mapę.",true);
    pendingSheet=btn.dataset.sheet;inform("Klikaj mapę, aby wstawiać kolejne elementy. Naciśnij Esc, aby zakończyć.");
  });
  canvas.addEventListener("pointerdown",ev=>{
    if(!insertMode()||!state.meta||ev.button!==0)return;
    const p=eventCoords(ev),world=screenToWorld(p.x,p.y),items=sheetItems();
    const hit=items.slice().reverse().find(i=>{
      const a=worldToScreen(i.x,i.y);
      return p.x>=a.x-5&&p.y>=a.y-5&&p.x<=a.x+i.w*state.scale+6&&p.y<=a.y+i.h*state.scale+6;
    });
    if(!pendingSheet&&!hit){selectedSheet=null;requestDraw();return;}
    ev.stopImmediatePropagation();ev.preventDefault();
    if(sheetSaving||state.editBusy)return;
    if(pendingSheet){
      const kind=pendingSheet,[w,h]=GeoStudioSheet.sizes[kind];
      const factor=kind==="compartment"?Number($("sheet-number-size").value)/12:sheetSize;
      const item={id:crypto.randomUUID(),kind,x:world.x,y:world.y,w:w*factor/state.scale,h:h*factor/state.scale,text:GeoStudioSheet.defaultText(kind,state.meta.name)};
      selectedSheet=item.id;
      if(kind==="compartment"){
        numberPlacement={item,token:state.edit.documentToken};
        $("sheet-number").value=String(1+items.filter(i=>i.kind==="compartment").length);
        $("sheet-number-size").value=String(Math.max(1,item.h*12));
        $("sheet-number-dialog").returnValue="cancel";
        $("sheet-number-dialog").showModal();$("sheet-number").select();return;
      }
      saveSheet([...items,item]);
      inform("Klikaj dalej, aby wstawić następne. Esc kończy wstawianie.");return;
    }
    selectedSheet=hit.id;
    const corner=worldToScreen(hit.x+hit.w,hit.y+hit.h);
    sheetDrag={id:ev.pointerId,token:state.edit.documentToken,start:world,base:hit,item:{...hit},resize:Math.hypot(corner.x-p.x,corner.y-p.y)<12};
    canvas.setPointerCapture(ev.pointerId);requestDraw();
  },true);
  canvas.addEventListener("pointermove",ev=>{
    if(sheetDrag?.id!==ev.pointerId)return;
    ev.stopImmediatePropagation();
    const p=eventCoords(ev),w=screenToWorld(p.x,p.y),d=sheetDrag;
    const dx=w.x-d.start.x,dy=w.y-d.start.y;
    if(d.resize){
      const {w,h}=d.base;
      const factor=Math.max(8/(state.scale*Math.min(w,h)),1+(dx*w+dy*h)/(w*w+h*h));
      d.item.w=w*factor;d.item.h=h*factor;
    }
    else{d.item.x=d.base.x+dx;d.item.y=d.base.y+dy;}
    requestDraw();
  },true);
  for(const event of ["pointerup","pointercancel"])canvas.addEventListener(event,ev=>{
    if(sheetDrag?.id!==ev.pointerId)return;
    ev.stopImmediatePropagation();const d=sheetDrag;sheetDrag=null;
    if(event==="pointerup"&&d.token===state.edit?.documentToken&&JSON.stringify(d.base)!==JSON.stringify(d.item))
      saveSheet(sheetItems().map(i=>i.id===d.item.id?d.item:i));
    requestDraw();
  },true);
  $("sheet-remove").addEventListener("click",()=>saveSheet(sheetItems().filter(i=>i.id!==selectedSheet)));
  let fontDraft=null;
  const sheetLines=$("sheet-lines");
  function fontRuns(){
    const runs=[];
    fontDraft.styles.forEach((style,index)=>{
      if(!style||!Object.keys(style).length)return;
      const last=runs.at(-1);
      if(last&&last.end===index&&JSON.stringify(last.style)===JSON.stringify(style))last.end++;
      else runs.push({start:index,end:index+1,style});
    });
    return runs;
  }
  function draftItem(){
    const i={...fontDraft.item,runs:fontRuns()};
    if(!sheetLines.readOnly)i.text=sheetLines.value;
    return i;
  }
  function previewSheetFont(){
    const i=draftItem(),c=$("sheet-sample"),g=c.getContext("2d"),[w,h]=GeoStudioSheet.sizes[i.kind];
    g.clearRect(0,0,c.width,c.height);
    const z=Math.min((c.width-10)/w,(c.height-10)/h);
    GeoStudioSheet.paint(g,[{...i,w,h}],()=>({x:5,y:5}),z,state.edit.compilationScale);
  }
  function formatSheetRange(key,value){
    if(!fontDraft)return;
    let a=sheetLines.selectionStart,b=sheetLines.selectionEnd;
    if(a===b){a=0;b=sheetLines.value.length;}
    if(value===undefined)value=!fontDraft.styles.slice(a,b).every(s=>s?.[key]);
    for(let n=a;n<b;n++)fontDraft.styles[n]={...fontDraft.styles[n],[key]:value};
    previewSheetFont();sheetLines.focus();
  }
  $("sheet-font").onchange=e=>{if(e.target.value)formatSheetRange("family",e.target.value);e.target.value="";};
  $("sheet-size").onchange=e=>{const v=e.target.valueAsNumber;if(Number.isInteger(v)&&v>=4&&v<=144)formatSheetRange("size",v);};
  $("sheet-bold").onclick=()=>formatSheetRange("bold");
  $("sheet-italic").onclick=()=>formatSheetRange("italic");
  sheetLines.oninput=()=>{
    const prev=fontDraft.text,next=sheetLines.value;
    let a=0,b=0;
    while(a<prev.length&&a<next.length&&prev[a]===next[a])a++;
    while(b<prev.length-a&&b<next.length-a&&prev[prev.length-1-b]===next[next.length-1-b])b++;
    fontDraft.styles.splice(a,prev.length-a-b,...Array(next.length-a-b).fill(fontDraft.styles[a]||fontDraft.styles[a-1]||null));
    fontDraft.text=next;previewSheetFont();
  };
  $("sheet-edit").addEventListener("click",()=>{
    const i=sheetItems().find(i=>i.id===selectedSheet);if(!i)return;
    const text=GeoStudioSheet.textFor(i,state.edit.compilationScale);
    sheetLines.readOnly=!["title","credits","compartment"].includes(i.kind);
    sheetLines.value=text;fontDraft={item:i,text,styles:Array(text.length).fill(null)};
    for(const run of i.runs||[])fontDraft.styles.fill(run.style,run.start,run.end);
    $("sheet-font").value="";$("sheet-size").value="";
    previewSheetFont();$("sheet-text-dialog").returnValue="cancel";$("sheet-text-dialog").showModal();
    sheetLines.setSelectionRange(0,0);
  });
  $("sheet-text-dialog").addEventListener("close",()=>{
    if(fontDraft&&$("sheet-text-dialog").returnValue==="save"){
      const item=draftItem();
      saveSheet(sheetItems().map(i=>i.id===item.id?item:i));
    }
    fontDraft=null;
  });
  canvas.addEventListener("dblclick",ev=>{
    if(!insertMode()||!state.meta)return;
    const p=eventCoords(ev),w=screenToWorld(p.x,p.y),items=sheetItems();
    const item=items.slice().reverse().find(i=>{const a=worldToScreen(i.x,i.y);return p.x>=a.x&&p.y>=a.y&&p.x<=a.x+i.w*state.scale&&p.y<=a.y+i.h*state.scale;});
    if(!item)return;
    ev.preventDefault();ev.stopImmediatePropagation();selectedSheet=item.id;pendingSheet=null;
    if(item.kind==="compartment"){
      numberPlacement={item:{...item},token:state.edit.documentToken,editing:true};
      $("sheet-number").value=item.text;$("sheet-number-size").value=String(Math.max(1,item.h*12*state.scale/GeoStudioSheet.sizes.compartment[1]));
      $("sheet-number-dialog").returnValue="cancel";$("sheet-number-dialog").showModal();$("sheet-number").select();
    }else if(["title","credits"].includes(item.kind))$("sheet-edit").click();
    requestDraw();
  },true);
  document.addEventListener("keydown",ev=>{
    if(ev.key==="Escape"&&pendingSheet){pendingSheet=null;inform("Wstawianie zakończone.");requestDraw();return;}
    if((ev.key==="Delete"||ev.key==="Backspace")&&insertMode()&&selectedSheet&&!/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName||"")){
      ev.preventDefault();saveSheet(sheetItems().filter(i=>i.id!==selectedSheet));selectedSheet=null;requestDraw();
    }
  },true);
  canvas.addEventListener("pointerdown", ev=>{
    if(state.tool==="nodes"&&(ev.button===2||ev.button===1)){
      ev.preventDefault();
      if(state.editBusy||state.drag)return;
      const p=eventCoords(ev);
      canvas.setPointerCapture(ev.pointerId);
      state.drag={pointer:ev.pointerId,start:p,last:p,moved:false,pan:ev.button===1,auxNode:ev.button};
      return;
    }
    const rightLabel=state.tool==="select"&&ev.button===2;
    if(ev.button!==0&&ev.button!==1&&!rightLabel)return;
    if(state.drag)return;
    const p=eventCoords(ev);
    state.hoverInsert=null;
    if(((state.tool==="labels"&&ev.button===0)||rightLabel)&&!state.editBusy){
      const hit=pickLabelAt(p);
      if(!hit){if(!rightLabel)inform("Kliknij i przeciągnij tekst A1, A2 lub TX.");return;}
      ev.preventDefault();
      canvas.setPointerCapture(ev.pointerId);
      const label=hit.label;
      state.labelSelected={fid:hit.fid,field:hit.field};
      state.labelDrag={
        fid:hit.fid,field:hit.field,label,start:p,
        origin:{x:label.x,y:label.y,offset:label.offset,
                manuallyPlaced:label.manuallyPlaced}
      };
      state.drag={pointer:ev.pointerId,start:p,last:p,moved:false,label:true};
      if(state.active!==hit.fid){state.pinned.clear();selectFeature(hit.fid);}
      requestDraw();return;
    }
    if(rightLabel)return;
    if(["draw","cut","line","line-edit"].includes(state.tool)&&
       ev.button===0&&!state.editBusy&&state.meta){
      appendDrawingPoint(ev,p);
      return;
    }
    canvas.setPointerCapture(ev.pointerId);
    if(state.tool==="move"&&ev.button===0&&!state.editBusy){
      const world=screenToWorld(p.x,p.y);
      const hits=pick(world),selected=selectedObjectIds();
      if(ev.ctrlKey){
        const fid=hits[0];
        if(fid)togglePickedFeature(fid);
        return;
      }
      const fid=hits.find(id=>selected.includes(id))||hits[0];
      const feature=state.features.find(item=>item.id===fid);
      if(!feature||!feature.geometry?.length){
        inform("Kliknij punkt, linię lub poligon, aby go przesunąć.",true);
        return;
      }
      const ids=selected.includes(fid)?selected:[fid];
      if(!selected.includes(fid)){state.pinned.clear();selectFeature(fid);}
      state.moveGhost={ids,dx:0,dy:0};
      state.drag={pointer:ev.pointerId,start:p,last:p,moved:false,moveIds:ids};
      requestDraw();return;
    }
    if(state.tool==="nodes"&&ev.button===0&&!state.editBusy){
      const index=closestEditableVertex(p);
      if(index>=0){
        const world=nativeWorldPoint(editableVertices()[index]);
        state.selectedVertex=index;
        updateDeleteNodeButton();
        state.vertexDrag={fid:state.active,code:state.detail.code,
                          index,preview:world,snap:null};
        state.drag={pointer:ev.pointerId,start:p,last:p,moved:false,node:true};
        armNodeBoundary(ev);
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
    if(["draw","cut","line","line-edit"].includes(state.tool)&&!state.editBusy){
      updateDrawingHover(world,ev.altKey);
    }
    if(!state.drag&&state.tool==="nodes"&&!state.editBusy){
      state.hoverInsert=closestEditableSegment(p);
      requestDraw();
    }
    if(!state.drag||state.drag.pointer!==ev.pointerId)return;
    const d=state.drag;
    if(Math.hypot(p.x-d.start.x,p.y-d.start.y)>4)d.moved=true;
    if(d.label&&state.labelDrag){
      const moving=state.labelDrag;
      if(d.moved){
        moving.label.x=moving.origin.x+(p.x-d.start.x)/state.scale;
        moving.label.y=moving.origin.y+(p.y-d.start.y)/state.scale;
        moving.label.offset=0;
        moving.label.manuallyPlaced=true;
        requestDraw();
      }
    }else if(d.moveIds&&state.moveGhost){
      let dx=Math.round((d.start.y-p.y)/state.scale*1000)/1000;
      let dy=Math.round((p.x-d.start.x)/state.scale*1000)/1000;
      const snap=magneticMove(d.moveIds,dx,dy);
      if(snap){dx=snap.dx;dy=snap.dy;}
      state.moveGhost.dx=dx;state.moveGhost.dy=dy;
      state.moveGhost.snap=snap;
      requestDraw();
    }else if(d.node&&state.vertexDrag){
      if(d.moved){
        const snap=previewSnap(world);
        state.vertexDrag.preview=snap.point;
        state.vertexDrag.snap=snap.kind?snap:null;
        armNodeBoundary(ev);
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
    const d=state.drag;
    if(!d||ev.pointerId!==d.pointer)return;
    state.drag=null;shell.classList.remove("dragging");
    if(d.auxNode){
      if(!d.moved&&state.tool==="nodes"&&!state.editBusy){
        const p=eventCoords(ev);
        if(d.auxNode===2){
          const edge=closestEditableSegment(p);
          if(edge)insertVertexAtSegment(edge);
        }else{
          const index=closestEditableVertex(p);
          if(index>=0){state.selectedVertex=index;deleteSelectedVertex();}
        }
      }else if(d.pan)scheduleViewport();
      return;
    }
    if(d.label){
      const moving=state.labelDrag;
      state.labelDrag=null;
      if(d.moved&&moving)commitLabelDrag(moving);
      else requestDraw();
      return;
    }
    if(d.moveIds){
      const ghost=state.moveGhost;
      state.moveGhost=null;requestDraw();
      if(d.moved&&ghost&&(ghost.dx||ghost.dy)){
        // Dragging is a single action. Keep a guarded server preview/apply
        // but no interrupting dialog or extra confirmation window.
        commitDraggedMove(d.moveIds,ghost);
      }
      return;
    }
    if(d.node){
      const moving=state.vertexDrag;
      state.vertexDrag=null;requestDraw();
      if((d.moved||moving?.follow)&&moving)commitVertexDrag(moving);
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
    if(!hits.length){clearAdvancedSelection();return;}
    let index=0;
    if(state.lastPick&&Math.hypot(state.lastPick.p.x-p.x,
       state.lastPick.p.y-p.y)<8&&hits.includes(state.lastPick.fid))
       index=(hits.indexOf(state.lastPick.fid)+1)%hits.length;
    const fid=hits[index];
    state.lastPick={p,fid};
    if(ev.ctrlKey||ev.shiftKey){
      // Ctrl/Shift-click adds or removes objects without losing the rest
      // of the multi-selection. Subsequent clicks cycle overlapping hits.
      togglePickedFeature(fid);

    }else selectFeature(fid);
  });
  canvas.addEventListener("dblclick",ev=>{
    // Double-click is often produced by two fast point placements.
    // It must NEVER end polygon drawing: use Enter or the first vertex.
    if(["cut","line","line-edit"].includes(state.tool)&&state.meta){
      ev.preventDefault();ev.stopPropagation();finishGeometryDrawing();return;
    }
    if(state.tool==="draw")return;
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
    if(state.drawHover){
      state.drawHover=null;state.drawSnap=null;state.drawCursorWorld=null;
      requestDraw();
    }
  });
  canvas.addEventListener("pointercancel",()=>{
    if(state.labelDrag){
      const moving=state.labelDrag;
      Object.assign(moving.label,moving.origin);
      state.labelDrag=null;
    }
    state.drag=null;state.vertexDrag=null;state.moveGhost=null;
    shell.classList.remove("dragging");requestDraw();
  });
  canvas.addEventListener("wheel",ev=>{
    if(!state.meta)return;
    ev.preventDefault();
    const p=eventCoords(ev);
    zoomAt(Math.exp(-ev.deltaY*.00125),p.x,p.y);
  },{passive:false});
  canvas.addEventListener("auxclick",ev=>{if(state.tool==="nodes")ev.preventDefault();});
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
    if(activeTrace && !document.querySelector("dialog[open]")){
      if(ev.key==="Escape"){ev.preventDefault();activeTrace.close();}
      else if(ev.key==="Enter"&&!ev.isComposing&&!ev.repeat&&
              (ev.target===document.body||ev.target===canvas||ev.target.matches(".trace-map-overlay,.trace-a1,.trace-save"))){
        ev.preventDefault();activeTrace.submit();
      }
      return;
    }
    if(state.exportAreaPicking&&ev.key==="Escape"){
      ev.preventDefault();finishExportAreaSelection(true);return;
    }
    if(state.exportAreaPicking)return;
    const typing=ev.target.matches("input,textarea,[contenteditable]");
    if((ev.ctrlKey||ev.metaKey)&&ev.key.toLowerCase()==="k"){
      ev.preventDefault();openCommands();return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.key.toLowerCase()==="o"){
      ev.preventDefault();chooseMap();return;
    }
    if((ev.ctrlKey||ev.metaKey)&&!ev.shiftKey&&ev.key.toLowerCase()==="p"){
      ev.preventDefault();openLayoutDialog();return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.key.toLowerCase()==="h"){
      ev.preventDefault();openAdvancedSelection();return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.shiftKey&&ev.key.toLowerCase()==="e"){
      ev.preventDefault();openBulkEditor();return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.altKey&&ev.key.toLowerCase()==="l"){
      ev.preventDefault();openLabelSettings();return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.key.toLowerCase()==="m"&&
       !ev.shiftKey&&!ev.altKey){
      ev.preventDefault();$("view-scale").focus();$("view-scale").select();return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.key==="F5"){
      ev.preventDefault();
      $("compilation-scale").focus();$("compilation-scale").select();return;
    }
    if(ev.altKey&&!ev.ctrlKey&&!ev.metaKey&&ev.key.toLowerCase()==="l"){
      ev.preventDefault();setTool("labels");return;
    }
    if($("line-dialog").open||$("split-dialog").open||
       $("copy-dialog").open||$("create-dialog").open||$("move-dialog").open||
       $("bulk-dialog").open||$("select-dialog").open||
       $("label-settings-dialog").open||
       $("find-dialog").open||$("replace-dialog").open)return;
    if((ev.ctrlKey||ev.metaKey)&&!ev.shiftKey&&!ev.altKey&&
       ev.key.toLowerCase()==="f"){
      ev.preventDefault();openReplaceDialog();return;
    }
    if(typing)return;
    if(!ev.ctrlKey&&!ev.metaKey&&!ev.altKey&&ev.key.toLowerCase()==="f"){
      ev.preventDefault();openFindDialog();return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.shiftKey&&ev.key.toLowerCase()==="g"){
      ev.preventDefault();mergePolygons();return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.shiftKey&&ev.key.toLowerCase()==="x"){
      ev.preventDefault();startSplit();return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.key==="Delete"){
      ev.preventDefault();deleteObjects();return;
    }
    if((ev.ctrlKey||ev.metaKey)&&ev.key.toLowerCase()==="d"){
      ev.preventDefault();quickDuplicate();return;
    }
    if(["draw","cut","line","line-edit"].includes(state.tool)&&ev.key==="Enter"){
      ev.preventDefault();finishGeometryDrawing();return;
    }
    if(state.tool==="nodes"&&state.detail&&state.selectedVertex!==null&&
       !ev.ctrlKey&&!ev.metaKey&&!ev.altKey&&
       (ev.key==="Delete"||ev.key==="Backspace")){
      ev.preventDefault();deleteSelectedVertex();return;
    }
    if(ev.key==="Delete"&&!ev.ctrlKey&&!ev.metaKey&&!ev.altKey&&
       selectedObjectIds().length){
      ev.preventDefault();deleteObjects();return;
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
      if(dialog.open){dialog.close();return;}
      if(["draw","cut","line","line-edit"].includes(state.tool)){
        ev.preventDefault();
        if(state.drawPoints.length){
          state.drawPoints.pop();
          state.drawSnap=null;
          requestDraw();
          inform("Cofnięto ostatni punkt. Pozostało "+
            state.drawPoints.length+". Rysuj dalej; S kończy narzędzie.");
        }else{
          setTool("select");
          inform("Rysowanie anulowane — szkic nie miał punktów.");
        }
        return;
      }
      if(["nodes","move","labels"].includes(state.tool)){
        state.vertexDrag=null;state.labelDrag=null;setTool("select");
      }
      clearAdvancedSelection();
      return;
    }
    if(!ev.ctrlKey&&!ev.metaKey&&!ev.altKey&&
       ev.key.toLowerCase()==="g"&&
       ["draw","cut","line","line-edit"].includes(state.tool)){
      ev.preventDefault();toggleDrawMagnet();return;
    }
    if(ev.key.toLowerCase()==="s")setTool("select");
    if(ev.key.toLowerCase()==="m")setTool("move");
    if(ev.key.toLowerCase()==="n")setTool("draw");
    if(ev.key.toLowerCase()==="l"){
      if(ev.shiftKey)startEditLine();else setTool("line");
    }
    if(ev.key.toLowerCase()==="h")setTool("pan");
    if(ev.key.toLowerCase()==="b")pinActive();
    if(ev.key==="0")fitToMap();
    if(ev.key==="/"){ev.preventDefault();$("layer-search").focus();}
  });

  const toolbar=document.querySelector(".toolbar");
  toolbar.addEventListener("wheel",ev=>{
    if(toolbar.scrollWidth>toolbar.clientWidth &&
       Math.abs(ev.deltaY)>Math.abs(ev.deltaX)){
      ev.preventDefault();
      toolbar.scrollLeft+=ev.deltaY;
    }
  },{passive:false});
  const link=(id,callback)=>$(id).addEventListener("click",callback);
  link("btn-open",chooseMap);
  link("tool-open",chooseMap);
  link("empty-open",chooseMap);
  link("tool-advanced-select",openAdvancedSelection);
  link("tool-clear-selection",clearAdvancedSelection);
  link("tool-find",openFindDialog);
  link("tool-replace-phrase",openReplaceDialog);
  link("find-close",()=>$("find-dialog").close());
  link("find-select-all",selectFindResults);
  $("find-form").addEventListener("submit",submitFind);
  for(const id of ["find-code","find-field","find-value","find-match"])
    $(id).addEventListener("input",()=>{
      findList=[];
      $("find-select-all").disabled=true;
      $("find-results").replaceChildren();
      $("find-summary").textContent="Kryteria zmienione. Kliknij Szukaj.";
    });
  link("replace-close",()=>$("replace-dialog").close());
  link("replace-preview",previewReplacePhrase);
  $("replace-form").addEventListener("submit",applyReplacePhrase);
  for(const id of ["replace-field","replace-scope","replace-needle",
                   "replace-replacement","replace-code","replace-case"])
    $(id).addEventListener("input",invalidateReplacePreview);
  link("tool-bulk-edit",openBulkEditor);
  link("tool-move",()=>setTool("move"));
  link("tool-label-move",()=>setTool("labels"));
  link("tool-label-config",openLabelSettings);
  link("tool-new-polygon",()=>setTool("draw"));
  link("tool-draw-snap",toggleDrawMagnet);
  link("tool-merge",mergePolygons);
  link("tool-split",startSplit);
  link("tool-winding",repairWinding);
  link("tool-line",()=>setTool("line"));
  link("line-close",()=>$("line-dialog").close());
  link("line-back",()=>$("line-dialog").close());
  link("line-preview",()=>previewGeometryForm("line"));
  $("line-form").addEventListener("submit",ev=>applyGeometryForm("line",ev));
  for(const key of ["line-code","line-a1","line-a2"])
    $(key).addEventListener("input",()=>{state.geometryPreview=null;
      $("line-apply").disabled=true;});
  link("split-close",()=>$("split-dialog").close());
  link("split-back",()=>$("split-dialog").close());
  link("split-preview",()=>previewGeometryForm("split"));
  $("split-form").addEventListener("submit",ev=>applyGeometryForm("split",ev));
  link("tool-copy",quickDuplicate);
  link("tool-delete-objects",deleteObjects);
  link("copy-close",()=>$("copy-dialog").close());
  link("create-close",()=>$("create-dialog").close());
  link("create-back",()=>$("create-dialog").close());
  link("copy-preview",()=>previewObject("copy"));
  link("create-preview",()=>previewObject("create"));
  $("copy-form").addEventListener("submit",ev=>applyObject("copy",ev));
  $("create-form").addEventListener("submit",ev=>applyObject("create",ev));
  for(const id of ["copy-dx","copy-dy"])
    $(id).addEventListener("input",()=>invalidateObjectPreview("copy"));
  for(const id of ["create-code","create-a1","create-a2"])
    $(id).addEventListener("input",()=>{
      state.objectPreview=null;
      $("create-apply").disabled=false;
    });
  link("float-move",()=>setTool("move"));
  link("tool-move-offset",()=>openMoveEditor());
  link("move-close",()=>$("move-dialog").close());
  link("move-preview",previewMoveChanges);
  $("move-form").addEventListener("submit",applyMoveChanges);
  for(const id of ["move-dx","move-dy","move-detach","move-snap"])
    $(id).addEventListener("input",invalidateMovePreview);
  link("bulk-close",()=>$("bulk-dialog").close());
  link("bulk-preview",previewBulkChanges);
  $("bulk-form").addEventListener("submit",applyBulkChanges);
  for(const field of ["a1","a2"]){
    const toggle=$("bulk-enable-"+field),value=$("bulk-value-"+field);
    toggle.addEventListener("change",()=>{
      value.disabled=!toggle.checked;invalidateBulkPreview();
      if(toggle.checked)value.focus();
    });
    value.addEventListener("input",invalidateBulkPreview);
  }
  link("select-close",()=>$("select-dialog").close());
  link("select-clear",clearAdvancedSelection);
  $("select-form").addEventListener("submit",applyAdvancedSelection);

  setupRibbon();
  const updateWorkspaceTop=()=>{
    // The active ribbon can wrap onto two rows on smaller windows.
    // Keep responsive dock panels below the actual toolbar height.
    document.documentElement.style.setProperty("--geo-workspace-top",
      Math.ceil($("main-ribbon").getBoundingClientRect().bottom)+"px");
  };
  const ribbonResizeObserver=new ResizeObserver(updateWorkspaceTop);
  ribbonResizeObserver.observe($("main-ribbon"));
  ribbonResizeObserver.observe(document.querySelector(".topbar"));
  updateWorkspaceTop();
  link("tool-underlay",openUnderlayDialog);
  link("tool-raster",openRasterDialog);
  link("tool-crs",openCrsDialog);
  link("tool-layout-ribbon",openLayoutDialog);
  link("tool-map-copy-ribbon",downloadMapCopy);
  link("underlay-close",()=>$("underlay-dialog").close());
  link("underlay-close-bottom",()=>$("underlay-dialog").close());
  link("raster-close",()=>$("raster-dialog").close());
  link("raster-close-bottom",()=>$("raster-dialog").close());
  link("crs-close",()=>$("crs-dialog").close());
  link("crs-close-bottom",()=>$("crs-dialog").close());
  link("underlay-layers",loadUnderlayLayers);
  link("underlay-crs-convert",convertUnderlayCenter);
  link("crs-transform-map",transformActiveMap);
  $("underlay-prj-file").addEventListener("change",ev=>{
    readUnderlayPrj(ev.target.files?.[0]);ev.target.value="";
  });
  link("underlay-show",applyUnderlay);
  link("underlay-remove",removeUnderlay);
  $("underlay-preset").addEventListener("change",()=>{
    removeUnderlay();showWmsPresetAddress();loadUnderlayLayers();
  });
  for(const id of ["underlay-epsg","raster-epsg","crs-epsg"])
    $(id).addEventListener("change",ev=>setMapEPSG(ev.target.value));
  const rasterInput=$("underlay-raster-file");
  $("choose-raster").onclick=()=>rasterInput.click();
  $("choose-world").onclick=()=>$("underlay-world-file").click();
  let rasterPickerBusy=false;
  rasterInput.addEventListener("click",async ev=>{
    const api=nativeAPI();
    if(!api?.open_raster)return;
    ev.preventDefault();
    if(rasterPickerBusy)return;
    rasterPickerBusy=true;
    const documentToken=state.edit?.documentToken;
    try{
      const result=await api.open_raster();
      if(result.cancelled||documentToken!==state.edit?.documentToken)return;
      const binary=atob(result.data);
      const bytes=new Uint8Array(binary.length);
      for(let i=0;i<binary.length;i++)bytes[i]=binary.charCodeAt(i);
      await openRasterFile(new File([bytes],result.name),result.world,result.warning);
    }catch(error){inform("Nie udało się wczytać rastra: "+error.message,true);}
    finally{rasterPickerBusy=false;}
  });
  rasterInput.addEventListener("change",async ev=>{
    const files=Array.from(ev.target.files||[]);
    ev.target.value="";
    const images=files.filter(file=>/\.(png|jpe?g|webp|tiff?)$/i.test(file.name));
    if(images.length!==1){if(files.length)inform("Wybierz jeden raster i opcjonalnie jego plik world.",true);return;}
    const file=images[0], name=file.name.toLowerCase();
    const dot=name.lastIndexOf("."), stem=name.slice(0,dot), ext=name.slice(dot+1);
    const short={png:"pgw",jpg:"jgw",jpeg:"jgw",tif:"tfw",tiff:"tfw",webp:"wpw"};
    const sidecar=[short[ext],ext+"w","wld"].map(suffix=>
      files.find(item=>item.name.toLowerCase()===stem+"."+suffix)).find(Boolean);
    const documentToken=state.edit?.documentToken;
    let world=null,warning="";
    if(sidecar){
      try{
        if(sidecar.size>8192)throw Error("Plik world przekracza 8 KB.");
        world={name:sidecar.name,text:await sidecar.text()};
      }catch(error){warning=sidecar.name+" — "+error.message;}
    }
    if(documentToken===state.edit?.documentToken)await openRasterFile(file,world,warning);
  });
  $("underlay-world-file").addEventListener("change",ev=>{
    openWorldFile(ev.target.files?.[0]);ev.target.value="";
  });
  link("raster-remove",removeRaster);
  link("raster-calibrate",openVisualCalibration);
  setupVisualCalibration();
  installExportAreaCapture();
  // Visual calibration installs its own GCP capture handlers.
  $("raster-opacity").addEventListener("input",ev=>{
    raster.opacity=Number(ev.target.value)/100;
    $("raster-opacity-value").textContent=ev.target.value+"%";
    requestDraw();renderRasterLayers();
  });
  $("underlay-opacity").addEventListener("input",ev=>{
    underlay.opacity=Number(ev.target.value)/100;
    $("underlay-opacity-value").textContent=ev.target.value+"%";
    requestDraw();renderRasterLayers();
  });
  link("tool-sidecar",()=> $("file-sidecar").click());
  link("tool-cartography",chooseCartographicLibraries);
  link("tool-carto-catalog",openCartographyCatalog);
  link("tool-trace-5310",startRasterTracing);
  link("tool-outline-style",openOutlineStyleEditor);
  link("outline-style-close",()=>$("outline-style-dialog").close());
  link("outline-style-reset",ev=>saveOutlineStyle(ev,true));
  $("outline-style-code").addEventListener("change",refreshOutlineStyleEditor);
  $("outline-style-form").addEventListener("submit",ev=>saveOutlineStyle(ev,false));
  link("carto-catalog-refresh",loadCartographyCatalog);
  link("carto-catalog-close",()=>$("cartography-catalog-dialog").close());
  link("carto-catalog-close-bottom",()=>$("cartography-catalog-dialog").close());
  $("carto-catalog-filter").addEventListener("input",renderCartographyCatalog);
  link("tool-topology",()=> $("file-topology").click());
  link("tool-undo",()=>historyStep("undo"));
  link("tool-redo",()=>historyStep("redo"));
  link("btn-export",downloadMapCopy);
  link("btn-layout",openLayoutDialog);
  link("layout-close",()=>$("layout-dialog").close());
  $("layout-format").addEventListener("change",updateExportFormatControls);
  $("layout-dialog").addEventListener("close",()=>requestDraw());
  link("layout-choose-area",beginExportAreaSelection);
  $("layout-scope").addEventListener("change",()=>{
    updateExportAreaControls();
    if($("layout-scope").value==="rect"&&!state.exportAreaBounds)
      beginExportAreaSelection();
    else requestDraw();
  });
  $("layout-form").addEventListener("submit",event=>{event.preventDefault();exportLayout(false);});
  link("layout-print",()=>exportLayout(true));
  link("tool-export-baked",downloadNativeCutouts);
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
  link("float-line",()=>setTool("line"));
  link("float-draw",()=>setTool("draw"));
  link("float-snap",toggleDrawMagnet);
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
  link("label-settings-close",()=>$("label-settings-dialog").close());
  link("label-settings-cancel",()=>$("label-settings-dialog").close());
  $("label-settings-code").addEventListener("change",refreshLabelSettingsForm);
  $("label-settings-field").addEventListener("change",fillLabelSettingsForm);
  $("label-settings-form").addEventListener("submit",saveLabelSettings);
  $("view-scale").addEventListener("change",applyViewScale);
  $("compilation-scale").addEventListener("change",applyCompilationScale);
  for(const id of ["view-scale","compilation-scale"])
    $(id).addEventListener("keydown",ev=>{
      if(ev.key==="Enter"){ev.preventDefault();$(id).blur();}
    });
  link("tool-topology-scan",()=>openTopologyPanel(true));
  link("topology-close",closeTopologyPanel);
  link("topology-rescan",scanTopology);
  link("topology-edit",editTopologyIssue);
  link("topology-delete-duplicate",removeTopologyDuplicate);
  $("topology-filter").addEventListener("change",renderTopologyIssues);
    link("btn-theme",toggleTheme);
  $("map-background-color").addEventListener("input",ev=>
    changeMapBackground(ev.target.value));
  document.querySelectorAll("[data-map-bg]").forEach(button=>{
    button.addEventListener("click",()=>{
      changeMapBackground(button.dataset.mapBg);
      $("map-background-menu").open=false;
    });
  });
  document.addEventListener("pointerdown",ev=>{
    if($("map-background-menu").open&&
       !ev.target.closest("#map-background-menu"))
      $("map-background-menu").open=false;
  });
  link("btn-command",openCommands);
  link("layers-all",showAllLayers);
  function activateLayerTab(which){
    const rasterTab=which==="raster";
    $("vectors-layer-panel").hidden=rasterTab;
    $("rasters-layer-panel").hidden=!rasterTab;
    $("layers-vectors-tab").classList.toggle("active",!rasterTab);
    $("layers-rasters-tab").classList.toggle("active",rasterTab);
    $("layers-vectors-tab").setAttribute("aria-selected",String(!rasterTab));
    $("layers-rasters-tab").setAttribute("aria-selected",String(rasterTab));
    if(rasterTab)renderRasterLayers();
  }
  link("layers-vectors-tab",()=>activateLayerTab("vector"));
  link("layers-rasters-tab",()=>activateLayerTab("raster"));
  link("raster-layers-add",openRasterDialog);
  $("layer-search").addEventListener("input",renderLayers);
  $("file-map").addEventListener("change",async ev=>{
    const file=ev.target.files?.[0], toNew=newDocumentOnFile;
    newDocumentOnFile=false;
    if(toNew&&host()){
      ev.target.value="";
      if(file)await host().openFileInNew(file);
    }else await openMap(file);
  });
  link("map-picker-cancel",()=>$("map-picker-fallback").close());
  link("map-picker-retry",()=>{
    $("map-picker-fallback").close();
    chooseStandardMap(!!(host()&&state.meta));
  });
  $("file-sidecar").addEventListener("change",ev=>openStyles(ev.target.files?.[0]));
  $("file-library").addEventListener("change",ev=>openCartographicFiles(ev.target.files));
  $("file-topology").addEventListener("change",ev=>openTopologyFile(ev.target.files?.[0]));

  document.addEventListener("dragover",ev=>{
    if(ev.dataTransfer&&Array.from(ev.dataTransfer.types).includes("Files"))ev.preventDefault();
  });
  document.addEventListener("drop",ev=>{
    if(ev.dataTransfer?.files?.length){
      ev.preventDefault();
      const files=Array.from(ev.dataTransfer.files);
      const map=files.find(file=>file.name.toLowerCase().endsWith(".map"));
      const style=files.find(file=>file.name.toLowerCase().endsWith(".json"));
      if(map&&host()&&state.meta)host().openFileInNew(map,style);
      else if(map)openMap(map).then(ok=>{if(ok&&style)openStyles(style);});
      else if(style)openStyles(style);
    }
  });

  if(documentId){
    window.GeoStudioDocument={
      status:editorStatus,openPicker:chooseMapHere,
      openFile:async(file,style)=>{
        if(state.meta)throw Error("Zakładka ma już otwartą mapę.");
        const ok=await openMap(file,true);
        if(ok&&style)await openStyles(style);
        return ok;
      }
    };
  }
  window.addEventListener("beforeunload",ev=>{
    if(!documentId&&state.edit?.dirty){
      ev.preventDefault();ev.returnValue="";
    }
  });
  new ResizeObserver(()=>{resizeCanvas();if(state.meta)scheduleViewport();}).observe(shell);
  new ResizeObserver(()=>{if(gcpView.open)drawGcpCanvas();})
    .observe($("raster-gcp-canvas"));
  restoreAppearance();
  resizeCanvas();renderRasterLayers();
  api("/api/map").then(meta=>{
    if(meta.loaded){
      state.meta=meta;
      setMapEPSG(meta.mapEPSG||"");
      state.localMapCandidate=meta.objectCount<=50000&&meta.vertexCount<=750000;
      state.localMapReady=false;state.viewportFeatureCache.clear();
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
      renderLayers();fitToMap();restoreCalibrations();
    }
  }).catch(err=>inform("Błąd lokalnej usługi: "+err.message,true)).finally(notifyHost);
})();
