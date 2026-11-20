/* GeoStudio 2.0 — experimental HTML5 map canvas and in-memory GEO-MAP editing.
   World coordinates: horizontal = GEO-MAP easting Y, vertical = -northing X.
   This matches the classic geodetic PySide6 orientation.
   Original MAP files are never overwritten: changes are exported as copies.
*/
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const token = document.querySelector('meta[name="api-token"]').content;
  const canvas = $("map-canvas"), shell = $("canvas-shell");
  let ctx = canvas.getContext("2d");
  const viewportSnapshot=document.createElement("canvas");
  const snapshotContext=viewportSnapshot.getContext("2d");
  const formatter = new Intl.NumberFormat("pl-PL");
  const state = {
    meta: null, features: [], visibleLayers: new Set(), hiddenGrades: new Set(),
    center: {x: 0, y: 0}, scale: 1, tool: "select",
    labels: true, grid: false, active: null, detail: null, pinned: new Set(),
    cartoLibraries: {},
    previewActive:false,previewCamera:null,geometrySnapshotValid:false,
    localMapReady:false,localMapCandidate:false,
    width: 1, height: 1, pixelRatio: 1, isDragging: false, drag: null,
    lastPick: null, scheduled: false, refreshTimer: null, queryCounter: 0,
    queryAbort: null, selectionRequest: 0, limited: false,
    firstLoad: true, inspectorCache: new Map(),
    edit: null, editBusy: false, bulkPreview: null, movePreview: null,
    moveIds: [], moveGhost: null, objectPreview:null,
    drawPoints:[], drawHover:null, drawSnap:null,
    labelHits:[],labelDrag:null,labelSelected:null,
    drawMagnet:true,drawCursorWorld:null,copyIds:[],
    geometryPreview:null,cutIds:[],lineEditId:null,
    snapEnabled: true, sharedNodes: false, vertexDrag: null,
    hoverInsert: null, selectedVertex: null
  };
  const commands = [
    {name:"Otwórz plik GEO-MAP", hint:"Ctrl+O", run:chooseMap},
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
    {name:"Zmień motyw płótna", hint:"◐", run:toggleTheme}
  ];
  let toastTimer;
  let recoveryTimer=null,recoverySavedKey='',recoveryBusy=false;
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
    $("tool-new-polygon").disabled=state.editBusy||!state.meta;
    $("btn-export").disabled=state.editBusy||!state.meta;
    $("btn-layout").disabled=state.editBusy||!state.meta;
    $("tool-export-baked").disabled=state.editBusy||!state.meta;
    $("btn-export").textContent=(
      state.edit.hasReversibleMasks||state.edit.hasVisualStyles)
      ?"↓ Pobierz MAP + JSON":"↓ Pobierz MAP";
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
    scheduleRecovery();
  }
  function scheduleRecovery() {
    clearTimeout(recoveryTimer);
    if(!state.edit?.dirty||!window.pywebview?.api?.save_recovery)return;
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
        const saved=await window.pywebview.api.save_recovery();
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
    if(!window.pywebview?.api?.save_baked_map){
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
      const res=await window.pywebview.api.save_baked_map();
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
      if(window.pywebview?.api?.save_base_map){
        const saved=await window.pywebview.api.save_base_map();
        if(saved&&!saved.cancelled){
          inform("Zapisano kopię MAP bez wycięć: "+saved.path);
          window.alert("Bazowa kopia MAP zapisana w:\n"+saved.path+
            (saved.topologyPath?"\nTopologia: "+saved.topologyPath:""));
        }
        return;
      }
      const params=new URLSearchParams({
        documentToken:state.edit.documentToken,normalizePositive:"true"});
      const response=await fetch("/api/export/map?"+params.toString(),{
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
      if(window.pywebview?.api?.save_map) {
        const saved=await window.pywebview.api.save_map();
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
      const needsPackage=hasMasks||!!state.edit.hasVisualStyles;
      const params=new URLSearchParams({documentToken:state.edit.documentToken,
        normalizePositive:"true"});
      const response=await fetch((needsPackage?"/api/export/package":"/api/export/map")+
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
    // Ordinary cadastral MAP: transfer the whole geometry just ONCE.
    // Zoom and pan then render local Canvas data, without HTTP requests.
    state.localMapCandidate=meta.objectCount<=50000&&
      meta.vertexCount<=750000;
    state.localMapReady=false;
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

  function cartographyMessage(payload) {
    state.cartoLibraries=payload?.libraries||{};
    renderCartographyMatches();
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
    if(window.pywebview?.api?.open_libraries){
      try {
        const result=await window.pywebview.api.open_libraries();
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

  async function chooseMap() {
    // Do NOT hold the entire UI busy while a native dialog is open.
    // The user can always use the independent "Z dysku" label/input,
    // even if Tk or the pywebview JS bridge is unavailable or blocked.
    if(window.pywebview){
      if(window.pywebview.api?.open_map){
        if(!confirmDiscardEdits())return;
        try {
          const answer=await window.pywebview.api.open_map();
          if(answer&&!answer.cancelled&&answer.metadata){
            finishOpeningMap(answer.metadata);
            if(answer.metadata.topologyWarning)
              inform(answer.metadata.topologyWarning,true);
            if(answer.metadata.visualWarning)
              inform(answer.metadata.visualWarning,true);
            if(answer.metadata.recoveryAvailable&&
               window.pywebview.api?.restore_recovery){
              const candidate=answer.metadata.recoveryAvailable;
              const consent=window.confirm(
                "Wykryto kopię awaryjną niezapisanych zmian z "+candidate.savedAt+
                " (wersja "+candidate.revision+").\n\n"+
                "Odtworzyć poprzednią sesję GeoStudio? "+
                "Oryginalny plik MAP pozostanie nienaruszony.");
              if(consent){
                busy(true,"Odzyskiwanie zmian z kopii awaryjnej");
                try{
                  const restored=await window.pywebview.api.restore_recovery();
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
      // Canvas magnetic snap has already chosen the exact same-code edge.
      // Do not perform a second, conflicting server-side correction.
      snapDistance:ghost.snap?0:
        Math.round(Math.min(2,Math.max(0.02,10/state.scale))*1000)/1000
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
  async function applyObject(which,ev) {
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
      const summary=Object.entries(report.codes||{})
        .map(([code,n])=>code+": "+display(n)).join(", ");
      if(!window.confirm("Usunąć "+display(report.selected)+
        " obiektów z kopii roboczej?\nKody: "+summary+
        "\nOryginał na dysku pozostanie nienaruszony; Ctrl+Z cofa."))return;
      if(report.selected>=20&&window.prompt(
          "Dla bezpieczeństwa wpisz USUŃ, aby potwierdzić:",
          "")!=="USUŃ")return;
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
      "Obrys: "+display(state.drawPoints.length)+
      " węzłów. Wybierz kod i atrybuty, a potem sprawdź.";
    invalidateObjectPreview("create");
    $("create-dialog").showModal();
    $("create-code").focus();
  }
  function finishGeometryDrawing() {
    if(state.tool==="draw"){finishDrawPolygon();return;}
    if(state.tool==="cut"){
      if(state.drawPoints.length<2){
        inform("Podział wymaga linii przecinającej poligon.",true);return;
      }
      $("split-summary").textContent="Przed podziałem sprawdź linię.";
      state.geometryPreview=null;$("split-apply").disabled=true;
      $("split-dialog").showModal();return;
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
      inform("Zaznacz istniejącą linię 6900/6000/6301/2364, nie poligon.",true);
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
    ev.preventDefault();
    const current=state.geometryPreview;
    if(!current||current.which!==which||state.editBusy)return;
    const request={...editRequestBody(),
      operation:operationForGeometry(which)};
    if(JSON.stringify(current.request)!==JSON.stringify(request)){
      state.geometryPreview=null;$(which+"-apply").disabled=true;
      inform("Obrys został zmieniony. Sprawdź ponownie.",true);return;
    }
    if(current.report.metadataWarning&&!window.confirm(
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
          "Po scaleniu części mogą być rozłączne. Liczba wysp: "+
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
    const control=$("tool-draw-snap");
    control.classList.toggle("active",state.drawMagnet);
    control.setAttribute("aria-pressed",String(state.drawMagnet));
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
    return helper.snapPoint(world,
      state.features.filter(isVisible),{scale:state.scale,
        enabled:true,bypass:altPressed,vertexPixels:7,edgePixels:5});
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
    // Only snap to other polygons with the SAME native object code. Foreign
    // layers are never targets and are never moved.
    if(!$("opt-snap")?.checked||ids.length>100)return null;
    const group=new Set(ids);
    const moving=state.features.filter(f=>group.has(f.id)&&f.closed);
    const codes=new Set(moving.map(f=>f.code));
    const fixed=state.features.filter(f=>!group.has(f.id)&&
      f.closed&&codes.has(f.code));
    if(!moving.length||!fixed.length)return null;
    const threshold=12/Math.max(.000001,state.scale);
    let best=null,movingCount=0,edgeCount=0;
    for(const obj of moving){
      for(const part of obj.geometry){
        for(const vertex of part){
          if(++movingCount>900)return best;
          const origin=[vertex[0]+rawDy,vertex[1]-rawDx];
          for(const target of fixed){
            if(obj.code!==target.code)continue;
            if(origin[0]<target.bbox[0]-threshold||
               origin[0]>target.bbox[2]+threshold||
               origin[1]<target.bbox[1]-threshold||
               origin[1]>target.bbox[3]+threshold)continue;
            for(const track of target.geometry){
              for(let i=0;i<track.length;i++){
                if(++edgeCount>35000)return best;
                const a=track[i],b=track[(i+1)%track.length];
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
  function resizeCanvas() {
    const rect = shell.getBoundingClientRect();
    state.width = Math.max(1, rect.width); state.height = Math.max(1, rect.height);
    state.pixelRatio = Math.min(2, window.devicePixelRatio || 1);
    const w = Math.round(state.width * state.pixelRatio);
    const h = Math.round(state.height * state.pixelRatio);
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width=w;canvas.height=h;
      state.previewActive=false;state.previewCamera=null;
    }
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
  function beginNavigationPreview() {
    if(state.previewActive||!state.meta||!canvas.width||!canvas.height)return;
    // Cache geometry only: text will be re-painted in fixed CSS pixels.
    if(!state.geometrySnapshotValid){
      viewportSnapshot.width=canvas.width;
      viewportSnapshot.height=canvas.height;
      snapshotContext.setTransform(1,0,0,1,0,0);
      snapshotContext.drawImage(canvas,0,0);
    }
    state.previewCamera={
      center:{...state.center},scale:state.scale,
      width:state.width,height:state.height
    };
    state.previewActive=true;
  }
  function drawNavigationPreview() {
    const c=state.previewCamera;
    if(!state.previewActive||!c||!viewportSnapshot.width)return false;
    const factor=state.scale/c.scale;
    const dx=state.width/2-c.width/2*factor+
      (c.center.x-state.center.x)*state.scale;
    const dy=state.height/2-c.height/2*factor+
      (c.center.y-state.center.y)*state.scale;
    ctx.drawImage(viewportSnapshot,dx,dy,c.width*factor,c.height*factor);
    updateScaleReadout();
    return true;
  }
  function zoomAt(factor, px, py) {
    if (!state.meta) return;
    const origin=screenToWorld(px,py);
    beginNavigationPreview();
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
  function setTool(tool) {
    if(state.editBusy)return;
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
      ["cut","tool-split"],["line","tool-line"],["line-edit","tool-line"],
      ["select","float-select"],["pan","float-pan"],["nodes","float-nodes"],
      ["move","float-move"]
    ])$(id).classList.toggle("active",name===tool);
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
  const hatchCache=new Map();
  function hatchPattern(style) {
    if(!style.hatch)return style.fill;
    const key=style.fill+"|"+style.hatch;
    if(hatchCache.has(key))return hatchCache.get(key);
    const size=12;
    const tile=document.createElement("canvas");
    tile.width=tile.height=size;
    const g=tile.getContext("2d");
    g.clearRect(0,0,size,size);
    g.strokeStyle=style.fill;
    g.fillStyle=style.fill;
    g.lineWidth=1;
    const segment=(x1,y1,x2,y2)=>{
      g.beginPath();g.moveTo(x1,y1);g.lineTo(x2,y2);g.stroke();
    };
    switch(style.hatch){
      case 1:
        for(const x of [1,5,9])for(const y of [1,5,9])
          g.fillRect(x,y,2,2);
        break;
      case 2:
        for(const x of [1,4,7,10])for(const y of [1,4,7,10])
          g.fillRect(x,y,2,2);
        break;
      case 3: segment(0,6,12,6); break;
      case 4: segment(6,0,6,12); break;
      case 5: segment(0,6,12,6);segment(6,0,6,12); break;
      case 6:
        for(const d of [-12,0,12])segment(d,0,d+12,12);
        break;
      case 7:
        for(const d of [0,12,24])segment(d,0,d-12,12);
        break;
      case 8:
        for(const d of [-12,0,12])segment(d,0,d+12,12);
        for(const d of [0,12,24])segment(d,0,d-12,12);
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
    ctx.globalAlpha=Math.min(1,Math.max(0,style.opacity));
    ctx.fill("evenodd");
    ctx.globalAlpha=1;
  }
  function renderStroke(feature) {
    const style=feature.style;
    if(!style.drawStroke)return; // GEO-MAP text anchors aren't printed lines.
    if(feature.geometry.length===1 && feature.geometry[0].length===1) {
      const p=worldToScreen(...feature.geometry[0][0]);
      const segments=style.symbolSegments||[];
      const circles=style.symbolCircles||[];
      ctx.save();
      ctx.strokeStyle=style.stroke;
      ctx.lineWidth=Math.max(.8,Math.min(3,style.strokeWidth||1));
      if(segments.length||circles.length){
        ctx.beginPath();
        for(const [x1,y1,x2,y2] of segments.slice(0,64)){
          ctx.moveTo(p.x+x1*5,p.y-y1*5);
          ctx.lineTo(p.x+x2*5,p.y-y2*5);
        }
        for(const [x,y,radius] of circles.slice(0,32)){
          ctx.moveTo(p.x+x*5+radius*5,p.y-y*5);
          ctx.arc(p.x+x*5,p.y-y*5,radius*5,0,2*Math.PI);
        }
        ctx.stroke();
      }else{
        ctx.fillStyle=style.stroke;ctx.beginPath();
        ctx.arc(p.x,p.y,Math.max(.6,Math.min(2,style.pointSize||1)),
                0,Math.PI*2);
        ctx.fill();
      }
      ctx.restore();
      return;
    }
    addPath(feature.geometry);
    ctx.strokeStyle=style.stroke;
    ctx.lineWidth=Math.max(.5,Math.min(12,style.strokeWidth));
    ctx.lineCap="round";ctx.lineJoin="round";
    ctx.setLineDash(Array.isArray(style.dash)?style.dash:[]);
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
  function labelFontSize(feature,label,selected) {
    // Pixel-perfect, zoom-invariant labels, as requested for classic GIS:
    // at 1:500, 1:5000 and 1:25000 the chosen A1/A2 size is the SAME.
    // Only explicit changes to the *compilation* scale or style editor
    // affect typography. Distant overview clutter is handled by culling
    // geometrically tiny objects, not by magnifying fonts.
    const source=state.edit?.sourceCompilationScale||5000;
    const compilation=state.edit?.compilationScale||source;
    const ratio=Math.max(.1,Math.min(10,compilation/source));
    const base=Math.max(8,Math.min(36,Number(label.size)||16));
    return (Math.round(Math.max(8,Math.min(40,base*ratio))*10)/10)*
      (state.exportFontRatio||1);
  }
  function labelTextRows(label,size) {
    const lines=String(label.text||"").split("\n").slice(0,6);
    return {lines,size,height:lines.length*size*1.20};
  }
  function renderLabels(features) {
    state.labelHits=[];
    if(!state.labels)return;
    const collisions=[];
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
      const selected=feature.id===state.active;
      const box=feature.bbox;
      const w=(box[2]-box[0])*state.scale;
      const h=(box[3]-box[1])*state.scale;
      const sheet=["7900","6900","6000","6301"].includes(feature.code);
      if(!selected&&!sheet){
        if(feature.code==="5310"){
          if(Math.max(w,h)<14)continue;
        }else if(Math.max(w,h)<32||Math.min(w,h)<8)continue;
      }
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
        if(painted>=(state.exportFontRatio?8000:1400)){ctx.restore();return;}
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
        const rect=[p.x-maxWidth/2-3,cy-height/2-3,
                    p.x+maxWidth/2+3,cy+height/2+3];
        if(rect[2]<0||rect[0]>state.width||
           rect[3]<0||rect[1]>state.height)continue;
        // Never let a feature's A1 suppress its OWN independent A2.
        // At working zoom every native building gets BOTH separate
        // labels, even if an unrelated nearby caption would otherwise
        // hide just its A2. At overview scales use collision culling.
        const readableBuilding=feature.code==="5310"&&Math.max(w,h)>=28;
        if(!selected&&!readableBuilding&&collisions.some(item=>
           item.fid!==feature.id&&item.rect[0]<rect[2]&&
           item.rect[2]>rect[0]&&item.rect[1]<rect[3]&&
           item.rect[3]>rect[1]))continue;
        collisions.push({fid:feature.id,rect});
        if((selected||state.tool==="labels")&&
           (label.field==="A1"||label.field==="A2"||
            state.labelSelected?.field===label.field&&
            state.labelSelected?.fid===feature.id)){
          ctx.fillStyle="rgba(27,150,143,.18)";
          ctx.fillRect(rect[0],rect[1],rect[2]-rect[0],rect[3]-rect[1]);
        }
        if(state.tool==="labels"&&state.labelSelected?.fid===feature.id&&
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
          ctx.lineWidth=Math.max(.7,Math.min(2,size*.11));
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
  function draw() {
    state.scheduled=false;
    const isDark=document.body.classList.contains("dark-map");
    ctx.setTransform(state.pixelRatio,0,0,state.pixelRatio,0,0);
    ctx.clearRect(0,0,state.width,state.height);
    ctx.fillStyle=isDark?"#17283b":"#FAFCFD";
    ctx.fillRect(0,0,state.width,state.height);
    drawGrid();
    if(!state.meta)return;
    // Keep the last verified viewport visible while the spatial request
    // catches up to the new camera, avoiding blank flashes on zoom.
    if(drawNavigationPreview()){
      const labelBounds=boundsFromViewport(.05);
      renderLabels(state.features.filter(f=>isVisible(f)&&isInView(f.bbox,labelBounds)));
      return;
    }
    const box=boundsFromViewport(.05);
    const features=state.features.filter(f=>isVisible(f)&&isInView(f.bbox,box));
    // Match the classic QGraphicsScene: paint fills below ALL outlines.
    // Painting fill+stroke for each object separately erased earlier
    // parcel borders beneath later overlapping polygons.
    const priorities={"5216":0,"5220":1,"5230":2,"5310":3,"1246":4};
    features.sort((a,b)=>(priorities[a.code]??3)-(priorities[b.code]??3));
    for(const feature of features) renderFill(feature);
    for(const feature of features) renderStroke(feature);
    renderHighlights(features);drawMoveGhost(features);drawMoveMagnet();
    // Snapshot without labels: bitmap zoom is smooth, text never scales.
    if(viewportSnapshot.width!==canvas.width||viewportSnapshot.height!==canvas.height){
      viewportSnapshot.width=canvas.width;viewportSnapshot.height=canvas.height;
    }
    snapshotContext.setTransform(1,0,0,1,0,0);
    snapshotContext.clearRect(0,0,canvas.width,canvas.height);
    snapshotContext.drawImage(canvas,0,0);
    state.geometrySnapshotValid=true;
    renderLabels(features);drawDraftPolygon();drawMagnetMarker();drawVertexTool();
    updateScaleReadout();
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
    // Full local response up to 50k objects / 750k vertices.
    // Larger maps rely on viewport streaming and the cached bitmap.
    let view=state.localMapCandidate?[...state.meta.bounds]:
      boundsFromViewport();
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
      state.features=res.features;
      state.limited=res.limited;
      state.localMapReady=state.localMapCandidate&&!res.limited&&
        res.total<=50000;
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
    clearTimeout(state.refreshTimer);
    if(state.localMapReady){
      state.refreshTimer=setTimeout(()=>{
        state.previewActive=false;state.previewCamera=null;requestDraw();
      },now?0:110);
      return;
    }
    if(now)refreshViewport();
    else state.refreshTimer=setTimeout(refreshViewport,100);
  }

  // Stage 11: screen layout uses its own physical print scale, independent
  // of the editing camera. Work with bounded viewport pages even on big MAPs.
  function openLayoutDialog(){
    if(!state.meta||!state.edit)return;
    $("layout-title").value=state.meta.name.replace(/\.map$/i,"");
    const denominator=Math.round(cssPixelsPerGroundMetre/state.scale);
    if(Number.isFinite(denominator)&&denominator>=10&&denominator<=100000000)
      $("layout-scale").value=denominator;
    $("layout-summary").textContent=
      "Obraz ma rzeczywistą rozdzielczość dla wybranej skali i DPI. " +
      "Przy drukowaniu ustaw 100% rozmiaru strony, bez dopasowania.";
    $("layout-dialog").showModal();
  }
  function layoutOptions(){
    const source=$("layout-scope").value==="all"
      ?state.meta.bounds:boundsFromViewport(0);
    const bounds=[...source];
    if(bounds.some(value=>!Number.isFinite(value))||
       bounds[2]<=bounds[0]||bounds[3]<=bounds[1])
      throw Error("Nieprawidłowy obszar mapy.");
    const denominator=Number($("layout-scale").value);
    if(!Number.isInteger(denominator)||denominator<10||
       denominator>100000000)
      throw Error("Mianownik skali musi mieścić się w zakresie 10–100000000.");
    const dpi=Number($("layout-dpi").value);
    if(![96,150,300].includes(dpi))
      throw Error("Wybierz poprawną rozdzielczość.");
    const pxPerUnit=dpi/(.0254*denominator);
    const width=Math.ceil((bounds[2]-bounds[0])*pxPerUnit);
    const height=Math.ceil((bounds[3]-bounds[1])*pxPerUnit);
    if(width<1||height<1)throw Error(
      "Obiekt jest za mały dla tej skali i DPI. Użyj większej skali.");
    const mm=value=>Math.round(value*dpi/25.4);
    const margin=mm(13),head=mm(20),foot=mm(21);
    const legend=$("layout-legend").checked?mm(52):0;
    const fullWidth=width+margin*2+legend;
    const fullHeight=height+head+foot;
    if(fullWidth>12000||fullHeight>12000||
       fullWidth*fullHeight>40000000)
      throw Error("Arkusz byłby zbyt duży ("+fullWidth+" × "+
        fullHeight+" px). Zmniejsz DPI, zwiększ mianownik skali "+
        "lub wybierz bieżący widok.");
    return {
      bounds,denominator,dpi,pxPerUnit,width,height,margin,head,foot,
      legend,fullWidth,fullHeight,
      title:$("layout-title").value.trim().slice(0,100)||"Mapa GEO-MAP",
      frame:$("layout-frame").checked,north:$("layout-north").checked,
      scaleBar:$("layout-scalebar").checked,
      showLegend:$("layout-legend").checked,
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
  function renderExportBatch(g,options,features,pass){
    const previous={
      ctx,center:state.center,scale:state.scale,
      width:state.width,height:state.height,pixelRatio:state.pixelRatio,
      exportFontRatio:state.exportFontRatio,labelHits:state.labelHits
    };
    ctx=g;
    state.center={
      x:(options.bounds[0]+options.bounds[2])/2,
      y:(options.bounds[1]+options.bounds[3])/2
    };
    state.scale=options.pxPerUnit;
    state.width=options.width;state.height=options.height;
    state.pixelRatio=1;
    state.exportFontRatio=options.dpi/96;
    g.save();
    try{
      g.translate(options.margin,options.head);
      g.beginPath();g.rect(0,0,options.width,options.height);g.clip();
      const visible=features.filter(isVisible);
      const priority={"5216":0,"5220":1,"5230":2,"5310":3,"1246":4};
      visible.sort((a,b)=>(priority[a.code]??3)-(priority[b.code]??3));
      if(pass==="fills")for(const item of visible)renderFill(item);
      if(pass==="strokes")for(const item of visible)renderStroke(item);
      if(pass==="labels")renderLabels(visible);
    }finally{
      g.restore();
      ctx=previous.ctx;state.center=previous.center;
      state.scale=previous.scale;state.width=previous.width;
      state.height=previous.height;state.pixelRatio=previous.pixelRatio;
      state.exportFontRatio=previous.exportFontRatio;
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
    g.font=Math.round(10*ratio)+"px sans-serif";
    g.fillStyle="#475569";
    g.fillText("Skala 1:"+new Intl.NumberFormat("pl-PL").format(denominator)+
      "  •  "+dpi+" DPI",margin,head+height+opts.foot*.83);
    g.textAlign="right";
    g.fillText("X/Y GEO-MAP • bez transformacji współrzędnych",
      base,head+height+opts.foot*.83);
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
    for(const [pass,label] of [
      ["fills","wypełnienia"],["strokes","linie"],["labels","etykiety"]
    ]){
      exportInfo("Eksport: "+label+"…");
      await forEachExportPage(options.bounds,part=>
        renderExportBatch(g,options,part,pass));
      if(state.edit?.revision!==revision||
         state.edit?.documentToken!==documentToken)
        throw Error("Mapa została zmieniona podczas przygotowania eksportu.");
    }
    paintLayoutFurniture(g,options);
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
  async function downloadLayoutFile(blob,filename){
    // WebView2 may silently ignore browser-only download links. Use the same
    // native Save As mechanism as MAP for a guaranteed chosen Windows path.
    if(window.pywebview?.api?.save_generated_export){
      exportInfo("Wybierz miejsce zapisu w oknie systemu Windows…");
      const extension=filename.split(".").pop().toLowerCase();
      const response=await fetch("/api/export/buffer",{
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
      const saved=await window.pywebview.api.save_generated_export(ticket);
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
    try{options=layoutOptions();}
    catch(error){exportInfo(error.message);inform(error.message,true);return;}
    if(print&&options.format==="dxf"){
      inform("Druk wymaga obrazu. Wybierz PNG, JPG lub TIFF.",true);return;
    }
    button.disabled=true;printButton.disabled=true;
    try{
      const basename=state.meta.name.replace(/\.map$/i,"")
        .replace(/[^a-zA-Z0-9\p{L}\p{N}._ -]+/gu,"_").slice(0,90)||
        "GeoStudio";
      if(!print&&options.format==="dxf"){
        exportInfo("Generowanie edytowalnego DXF…");
        const query=new URLSearchParams({
          documentToken:state.edit.documentToken});
        const response=await fetch("/api/export/dxf?"+query.toString(),{
          headers:{"X-GeoStudio-Token":token},cache:"no-store"});
        if(!response.ok){
          const data=await response.json().catch(()=>({}));
          throw Error(data.detail||"Nie udało się wyeksportować DXF.");
        }
        if(!await downloadLayoutFile(await response.blob(),basename+".dxf")){
          exportInfo("Anulowano zapis DXF.");return;
        }
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

  function buildLayer(name,count) {
    const item=document.createElement("div");item.className="layer-item";
    const row=document.createElement("label");row.className="layer-row";
    const toggle=document.createElement("input");toggle.type="checkbox";toggle.className="layer-toggle";
    toggle.checked=state.visibleLayers.has(name);
    toggle.addEventListener("change",()=>{
      if(toggle.checked)state.visibleLayers.add(name);else state.visibleLayers.delete(name);
      renderCartographyMatches();
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
    updateBulkButton();
    $("tool-move-offset").disabled=!state.meta||state.editBusy||n===0;
    $("tool-copy").disabled=!state.meta||state.editBusy||n===0;
    $("tool-delete-objects").disabled=!state.meta||state.editBusy||n===0;
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
  canvas.addEventListener("pointerdown", ev=>{
    if(ev.button!==0&&ev.button!==1)return;
    canvas.setPointerCapture(ev.pointerId);
    const p=eventCoords(ev);
    state.hoverInsert=null;
    if(state.tool==="labels"&&ev.button===0&&!state.editBusy){
      const hit=pickLabelAt(p);
      if(!hit){inform("Kliknij i przeciągnij tekst A1, A2 lub TX.");return;}
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
    if(["draw","cut","line","line-edit"].includes(state.tool)&&
       ev.button===0&&!state.editBusy&&state.meta){
      state.drag={pointer:ev.pointerId,start:p,last:p,moved:false,draw:true};
      return;
    }
    if(state.tool==="move"&&ev.button===0&&!state.editBusy){
      const world=screenToWorld(p.x,p.y);
      const hits=pick(world),selected=selectedObjectIds();
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
        requestDraw();
      }
    }else if(d.moved){
      if(d.pan||state.tool==="select"){
        beginNavigationPreview();
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
    if(d.label){
      const moving=state.labelDrag;
      state.labelDrag=null;
      if(d.moved&&moving)commitLabelDrag(moving);
      else requestDraw();
      return;
    }
    if(d.draw){
      if(!d.moved){
        const p=eventCoords(ev),world=screenToWorld(p.x,p.y);
        // The actual click is authoritative, not a stale hover target.
        // Alt always bypasses the magnet for the clicked point.
        const snapped=drawingSnapAt(world,ev.altKey);
        if(state.tool==="draw"&&snapped.kind==="start"&&
           state.drawPoints.length>=3){
          state.drawSnap=null;state.drawHover=null;
          finishDrawPolygon();
          // One click on the first corner completes the sketch and runs
          // its normal topology preview; code/A1/A2 still require approval.
          previewObject("create");
          requestDraw();
          return;
        }
        const next=[Math.round(-snapped.point.y*1000)/1000,
                    Math.round(snapped.point.x*1000)/1000];
        state.drawSnap=snapped.kind?snapped:null;
        const last=state.drawPoints[state.drawPoints.length-1];
        if(!last||Math.hypot(next[0]-last[0],next[1]-last[1])>0.003){
          if(state.drawPoints.length<500)state.drawPoints.push(next);
          else inform("Osiągnięto limit 500 węzłów.",true);
        }
        requestDraw();
        inform("Rysowanie: "+state.drawPoints.length+
          " punktów. Esc — cofnij ostatni; kliknij pierwszy punkt — domknij.");
      }
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
    if(["draw","cut","line","line-edit"].includes(state.tool)&&state.meta){
      ev.preventDefault();ev.stopPropagation();finishGeometryDrawing();return;
    }
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
    $(id).addEventListener("input",()=>invalidateObjectPreview("create"));
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

  link("tool-sidecar",()=> $("file-sidecar").click());
  link("tool-cartography",chooseCartographicLibraries);
  link("tool-topology",()=> $("file-topology").click());
  link("tool-undo",()=>historyStep("undo"));
  link("tool-redo",()=>historyStep("redo"));
  link("btn-export",downloadMapCopy);
  link("btn-layout",openLayoutDialog);
  link("layout-close",()=>$("layout-dialog").close());
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
  link("btn-theme",toggleTheme);
  link("btn-command",openCommands);
  link("layers-all",showAllLayers);
  $("layer-search").addEventListener("input",renderLayers);
  $("file-map").addEventListener("change",ev=>openMap(ev.target.files?.[0]));
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
