/* Host keep-alive frames: each editor owns its camera, UI and scoped API. */
(() => {
  "use strict";
  const $=id=>document.getElementById(id);
  const token=document.querySelector('meta[name="api-token"]').content;
  const tabs=new Map();
  let active=null, limit=10, creating=false, errorTimer=null, ready=false;
  async function request(path,options={}) {
    const response=await fetch(path,{...options,headers:{
      "X-GeoStudio-Token":token,...(options.headers||{})},cache:"no-store"});
    if(!response.ok){
      const error=await response.json().catch(()=>({}));
      throw Error(error.detail||("HTTP "+response.status));
    }
    return response.json();
  }
  function error(message){
    $("tab-error").textContent=String(message);
    $("tab-error").hidden=false;
    clearTimeout(errorTimer);
    errorTimer=setTimeout(()=>$("tab-error").hidden=true,7000);
  }
  function getStatus(tab){
    try{return tab.frame.contentWindow.GeoStudioDocument?.status()||tab.status;}
    catch(_){return tab.status;}
  }
  function syncTheme(tab){
    const value=getStatus(tab).theme;
    if(value==="light"||value==="dark")document.documentElement.dataset.theme=value;
  }
  function updateControls(){
    $("add-tab").disabled=!ready||creating||tabs.size>=limit;
    $("tab-count").textContent=tabs.size+" / "+limit;
  }
  function select(id){
    if(!tabs.has(id))return;
    active=id;
    for(const [key,tab] of tabs){
      const selected=key===id;
      tab.node.classList.toggle("active",selected);
      tab.select.setAttribute("aria-selected",String(selected));
      tab.select.tabIndex=selected?0:-1;
      tab.frame.classList.toggle("active",selected);
      tab.frame.setAttribute("aria-hidden",String(!selected));
      tab.frame.inert=!selected;
    }
    const tab=tabs.get(id);
    tab.node.scrollIntoView({block:"nearest",inline:"nearest"});
    syncTheme(tab);
    // Keyboard shortcuts remain inside the active map editor, not the host.
    try{tab.frame.contentWindow.focus();}catch(_){}
  }
  function status(id,data){
    const tab=tabs.get(id);
    if(!tab)return;
    tab.status={...tab.status,...data};
    const name=tab.status.name||"Nowa mapa";
    tab.name.textContent=name;
    tab.select.title=name+(tab.status.dirty?" — niezapisane zmiany":"");
    tab.node.classList.toggle("dirty",!!tab.status.dirty);
    tab.node.classList.toggle("empty",!tab.status.loaded);
    tab.close.setAttribute("aria-label","Zamknij "+name);
    if(active===id)syncTheme(tab);
  }
  function append(id){
    const node=document.createElement("div");node.className="tab empty";
    const pick=document.createElement("button");pick.type="button";pick.className="tab-select";
    pick.setAttribute("role","tab");
    pick.setAttribute("aria-controls","editor-"+id);
    pick.addEventListener("click",()=>select(id));
    const dot=document.createElement("span");dot.className="tab-dot";dot.setAttribute("aria-hidden","true");
    const name=document.createElement("span");name.className="tab-name";name.textContent="Nowa mapa";
    pick.append(dot,name);
    pick.addEventListener("keydown",event=>{
      if(!["ArrowLeft","ArrowRight","Home","End"].includes(event.key))return;
      const keys=[...tabs.keys()],index=keys.indexOf(id);
      const next=event.key==="Home"?keys[0]:event.key==="End"?keys[keys.length-1]:
        keys[(index+(event.key==="ArrowRight"?1:-1)+keys.length)%keys.length];
      event.preventDefault();select(next);tabs.get(next).select.focus();
    });
    const close=document.createElement("button");close.type="button";close.className="tab-close";
    close.textContent="×";close.title="Zamknij zakładkę";
    close.setAttribute("aria-label","Zamknij nową mapę");
    close.addEventListener("click",()=>closeTab(id));
    node.append(pick,close);
    const frame=document.createElement("iframe");frame.className="editor-frame";
    frame.id="editor-"+id;frame.title="Edytor mapy";frame.setAttribute("allow","fullscreen");
    const tab={id,node,select:pick,close,name,frame,status:{loaded:false,dirty:false,theme:document.documentElement.dataset.theme}};
    // Register before loading: the editor sends its status to its parent.
    tab.loaded=new Promise(resolve=>frame.addEventListener("load",resolve,{once:true}));
    tabs.set(id,tab);
    frame.src="/document/"+encodeURIComponent(id);
    $("tab-list").append(node);$("editors").append(frame);
    updateControls();
    return tab;
  }
  async function newTab(openNative=false,file=null,style=null){
    if(creating){error("Trwa otwieranie nowej zakładki.");return false;}
    if(tabs.size>=limit){error("Limit: "+limit+" otwarte mapy. Zamknij jedną zakładkę.");return false;}
    creating=true;updateControls();
    try{
      const {id}=await request("/api/documents",{method:"POST"});
      const tab=append(id);select(id);
      await tab.loaded;
      const editor=tab.frame.contentWindow.GeoStudioDocument;
      if(!editor)throw Error("Nie udało się uruchomić edytora zakładki.");
      if(file)await editor.openFile(file,style);
      else if(openNative)await editor.openPicker();
      return true;
    }catch(e){error(e.message);return false;}
    finally{creating=false;updateControls();}
  }
  async function closeTab(id){
    const tab=tabs.get(id);if(!tab)return;
    const snapshot=getStatus(tab);
    if(snapshot.busy){
      // Zablokowana zakładka nie może być ślepą uliczką: po potwierdzeniu
      // zamykamy ją mimo to, bo inaczej użytkownik zostaje bez wyjścia.
      const forced=window.confirm(
        "Mapa zgłasza trwającą operację.\n\n"+
        "Zamknąć zakładkę mimo to? Niezapisane zmiany przepadną.");
      if(!forced){error("Poczekaj na zakończenie operacji w tej mapie.");return;}
    }
    const dirty=!!snapshot.dirty;
    if(dirty&&!window.confirm("Mapa "+(snapshot.name||"")+" ma niezapisane zmiany. Zamknąć bez zapisu?"))return;
    tab.close.disabled=true;
    try{
      await request("/api/documents/"+encodeURIComponent(id)+"?discard="+(dirty?"true":"false"),{method:"DELETE"});
      const keys=[...tabs.keys()],index=keys.indexOf(id);
      tab.node.remove();tab.frame.remove();tabs.delete(id);
      if(active===id)active=null;
      if(!active&&tabs.size)select(keys[index+1]&&tabs.has(keys[index+1])?keys[index+1]:[...tabs.keys()].at(-1));
      updateControls();
      if(!tabs.size)await newTab();
    }catch(e){error(e.message);tab.close.disabled=false;}
  }
  window.GeoStudioTabs={status,openConverted(id){append(id);select(id);},newMap:()=>newTab(true),openFileInNew:(file,style)=>newTab(false,file,style)};
  $("add-tab").addEventListener("click",()=>newTab());
  window.addEventListener("beforeunload",event=>{
    if([...tabs.values()].some(tab=>getStatus(tab).dirty)){
      event.preventDefault();event.returnValue="";
    }
  });
  async function boot(){
    try{
      const result=await request("/api/documents");
      limit=result.limit||10;
      ready=true;
      for(const id of result.documents)append(id);
      if(tabs.size)select([...tabs.keys()][0]);else await newTab();
      updateControls();
    }catch(e){error(e.message);}
  }
  boot();
})();
