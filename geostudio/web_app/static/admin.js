/* GeoStudio administration UI. All privileges are checked by the Worker.
 * No ID token, service account, password or user data is persisted in JS. */
(() => {
  "use strict";
  const $=id=>document.getElementById(id);
  const dialog=$("admin-dialog");
  if(!dialog)return;
  const token=document.querySelector('meta[name="api-token"]').content;
  let allowed=false,busy=false,epoch=0,rows=[],current=null;
  let adminTab="users",inviteRows=[],selectedInvite=null;
  const PARTIAL={
    created_without_access:"Konto utworzone, lecz bez uprawnień. Wybierz je i zapisz dostęp.",
    reset_not_sent:"Konto utworzone. E-mail nie został wysłany; ponów reset hasła.",
    auth_still_disabled:"Uprawnienia zapisano, lecz konto Authentication nadal jest wyłączone.",
    blocked_not_deleted:"Konto zostało zablokowane, ale nie usunięte. Ponów usuwanie.",
    cleanup_pending:"Konto Authentication usunięte. Usuń pozostały dokument dostępu/historii w Firestore."
  };
  const displayDate=v=>v&&Number.isFinite(Date.parse(v))?new Date(v).toLocaleString("pl-PL"):"—";
  const node=(tag,text,cls)=>{
    const el=document.createElement(tag);if(text!==undefined)el.textContent=String(text);if(cls)el.className=cls;return el;
  };
  const button=(text,action,cls="admin-button")=>{
    const b=node("button",text,cls);b.type="button";b.addEventListener("click",action);return b;
  };
  function notice(text="",bad=false){
    $("admin-notice").textContent=text;
    $("admin-notice").classList.toggle("bad",bad);
  }
  async function rpc(action,data={}){
    const res=await fetch("/auth/admin",{method:"POST",cache:"no-store",
      headers:{"X-GeoStudio-Token":token,"Content-Type":"application/json"},
      body:JSON.stringify({action,...data})});
    const body=await res.json().catch(()=>({}));
    if(!res.ok){
      // A stale local claim cannot keep the panel open after a server denial.
      if(res.status===401||res.status===403){
        const detail=typeof body.detail==="string"?body.detail:"Brak uprawnień administratora.";
        clear();if(dialog.open)dialog.close();allowed=false;
        window.dispatchEvent(new CustomEvent("geostudio-admin-denied",{detail}));
      }
      throw Error(typeof body.detail==="string"?body.detail:"Nie udało się wykonać operacji.");
    }
    return body;
  }
  function disabled(){
    dialog.classList.toggle("busy",busy);
    $("admin-close").disabled=busy;
    $("admin-refresh").disabled=busy;
    $("admin-add").disabled=busy;
    // inert stops changes while an operation is in progress, without changing
    // permanent owner protections or the expiry input's disabled state.
    $("admin-users-body").inert=busy;
    $("admin-invites-body").inert=busy;
    $("admin-users-tab").disabled=busy;
    $("admin-invites-tab").disabled=busy;
    $("admin-search").disabled=busy;$("admin-filter").disabled=busy;
    dialog.setAttribute("aria-busy",String(busy));
  }
  async function run(fn){
    if(busy||!allowed||!dialog.open)return;
    const generation=epoch;busy=true;disabled();notice("Łączenie z usługą…");
    try{const msg=await fn(()=>generation===epoch&&dialog.open&&allowed);
      if(generation===epoch&&dialog.open&&allowed)notice(msg?.text||"",!!msg?.bad);
    }catch(e){if(generation===epoch&&dialog.open)notice(e.message||"Operacja nie powiodła się.",true);}
    finally{busy=false;disabled();}
  }
  function clear(){
    epoch++;rows=[];current=null;inviteRows=[];selectedInvite=null;
    $("invite-code").value="";$("invite-result").hidden=true;
    $("invite-create-form").reset();$("invite-rows").replaceChildren();$("invite-history").replaceChildren();
    $("invite-detail").hidden=true;$("invite-detail-title").textContent="";$("invite-detail-policy").textContent="";
    $("invite-registration-enabled").checked=false;
    switchTab("users");
    $("admin-new-password").value="";$("admin-confirm-email").value="";
    $("admin-rows").replaceChildren();$("admin-stats").replaceChildren();
    $("admin-devices").replaceChildren();$("admin-history").replaceChildren();
    $("admin-edit-form").reset();$("admin-create-form").reset();
    $("admin-account-name").textContent="";$("admin-account-email").textContent="";
    $("admin-account-login").textContent="";
    $("admin-search").value="";$("admin-filter").value="all";
    $("admin-create-form").hidden=true;$("admin-selected").hidden=true;$("admin-placeholder").hidden=false;
    notice();
  }
  function drawRows(){
    const filter=$("admin-filter").value,q=$("admin-search").value.trim().toLocaleLowerCase("pl");
    const list=rows.filter(r=>(filter==="all"||(filter==="pending"?!!r.policy?.pendingApproval:
      filter==="active"?!!r.active:!r.active&&!r.policy?.pendingApproval))&&
      ((r.email||"")+" "+(r.name||"")).toLocaleLowerCase("pl").includes(q));
    const root=$("admin-rows");root.replaceChildren();$("admin-empty").hidden=list.length>0;
    for(const r of list){
      const tr=node("tr");if(current?.uid===r.uid)tr.classList.add("selected");
      const td=node("td"),pick=button(r.name||r.email||"Konto bez adresu",()=>choose(r.uid),"admin-user-link");
      pick.append(node("small",(r.name?r.email:"")+(r.owner?" · administrator":"")));
      td.append(pick);tr.append(td);
      const status=r.policyError?"Błędne dane":r.policy?.pendingApproval?"Oczekujące":r.authDisabled?"Auth wyłączone":r.active?"Aktywne":r.policy?"Nieaktywne":"Brak dostępu";
      const s=node("td");s.append(node("span",status,"admin-status "+(r.active?"good":r.policy?.pendingApproval?"pending":"bad")));tr.append(s);
      tr.append(node("td",r.policy?(r.policy.deviceLimit?(r.policy.devices.length+"/"+r.policy.deviceLimit):"Bez limitu"):"—"));
      tr.append(node("td",displayDate(r.lastActive)));root.append(tr);
    }
  }
  function drawStats(stats,truncated){
    const root=$("admin-stats");root.replaceChildren();
    for(const [label,value] of [["Konta",stats.total],["Aktywne",stats.active],["Nieaktywne",stats.blocked],
      ["Oczekujące",stats.pending??0],["Rejestracje",stats.devices],["Połączenie ≤ 20 min",stats.recent]]){
      const tile=node("div",undefined,"admin-stat");
      tile.append(node("small",label),node("strong",value??0));root.append(tile);
    }
    if(truncated)root.append(node("p","Niepełna lista: maksymalnie 500 wyników na kolekcję; statystyki przybliżone.","admin-muted"));
  }
  async function loadList(live){
    const result=await rpc("list");
    if(!live())return;
    rows=Array.isArray(result.rows)?result.rows:[];drawStats(result.stats||{},result.truncated);drawRows();
  }
  function localInput(value){
    const d=new Date(value);if(!value||!Number.isFinite(d.getTime()))return "";
    const local=new Date(d.getTime()-d.getTimezoneOffset()*60000);
    return local.toISOString().slice(0,16);
  }
  function displayDetails(r){
    current=r;$("admin-create-form").hidden=true;$("admin-placeholder").hidden=true;$("admin-selected").hidden=false;
    $("admin-account-name").textContent=r.name||r.email||"Konto";
    $("admin-account-email").textContent=(r.email||"")+(r.owner?" · Administrator (chronione konto)":"");
    $("admin-account-login").textContent="Ostatnie logowanie Firebase: "+displayDate(r.lastLogin)+" · Ostatnie połączenie: "+displayDate(r.lastActive);
    const p=r.policy||{name:"",notes:"",active:false,expiresAt:null,deviceLimit:2,devices:[],offlineHours:0,version:""};
    $("admin-pending-approval").hidden=!p.pendingApproval;
    $("admin-name").value=p.name||r.name||"";$("admin-notes").value=p.notes||"";
    $("admin-active").checked=r.owner||!!p.active;$("admin-active").disabled=!!r.owner;
    $("admin-limit").value=p.deviceLimit;$("admin-unlimited").checked=r.owner||!p.expiresAt;
    $("admin-unlimited").disabled=!!r.owner;$("admin-expiry").value=localInput(p.expiresAt);
    $("admin-expiry").disabled=$("admin-unlimited").checked;
    $("admin-offline").value=String(p.offlineHours);
    $("admin-offline-warning").hidden=p.offlineHours!==-1;
    $("admin-enable-auth-row").hidden=!r.authDisabled;$("admin-enable-auth").checked=false;
    $("admin-delete-section").hidden=!!r.owner;$("admin-confirm-email").value="";
    const list=$("admin-devices");list.replaceChildren();
    const seen=new Map((r.activity?.devices||[]).map(d=>[d.id,d]));
    const all=[...new Set([...(p.devices||[]),...seen.keys()])];
    if(!all.length)list.append(node("p","Brak zarejestrowanych komputerów.","admin-muted"));
    for(const id of all){
      const data=seen.get(id)||{},registered=p.devices.includes(id);
      const row=node("div",undefined,"admin-device");
      const info=node("div",undefined,"admin-device-info");
      info.append(node("strong",data.alias||data.name||("Komputer "+id.slice(0,12))),
        node("small",(registered?"Zarejestrowany":"Zaobserwowany")+" · "+id.slice(0,12)+" · "+displayDate(data.lastSeen)));
      if(data.alias&&data.name)info.append(node("small","Nazwa systemowa: "+data.name));
      row.append(info);
      if(registered){
        const alias=node("input");alias.maxLength=80;alias.value=data.alias||"";alias.placeholder="Własna nazwa";
        alias.setAttribute("aria-label","Nazwa komputera "+id.slice(0,12));
        row.append(alias,button("Nazwij",()=>run(async live=>{
          await rpc("rename_device",{uid:r.uid,deviceId:id,alias:alias.value});
          if(live())await loadDetail(r.uid,live);
          return {text:"Nazwa komputera zapisana."};
        })));
        if(!r.owner){
          const label=node("label",undefined,"admin-check");const cb=node("input");cb.type="checkbox";cb.dataset.removeDevice=id;
          label.append(cb,node("span","Usuń"));row.append(label);
        }
      }
      list.append(row);
    }
    const hist=$("admin-history");hist.replaceChildren();
    const events=r.activity?.events||[];
    if(!events.length)hist.append(node("p","Brak historii dla tego konta.","admin-muted"));
    else{
      const table=node("table",undefined,"admin-table");
      const head=node("thead"),tr=node("tr");
      for(const h of ["Data i godzina","Zdarzenie","Komputer"])tr.append(node("th",h));head.append(tr);table.append(head);
      const tbody=node("tbody");
      for(const e of events){const row=node("tr");
        const device=seen.get(e.deviceId);
        row.append(node("td",displayDate(e.at)),node("td",e.kind==="login"?"Logowanie":"Uruchomienie"),
          node("td",device?.alias||e.name||e.deviceId.slice(0,12)));tbody.append(row);}
      table.append(tbody);hist.append(table);
    }
    drawRows();
  }
  async function loadDetail(uid,live){const r=await rpc("details",{uid});if(live())displayDetails(r);}
  function choose(uid){run(async live=>{await loadDetail(uid,live);});}
  function showCreate(){
    current=null;$("admin-create-form").reset();$("admin-new-password").value="";
    $("admin-create-form").hidden=false;$("admin-placeholder").hidden=true;$("admin-selected").hidden=true;drawRows();
    $("admin-new-email").focus();
  }
  function partial(result,success){return {text:PARTIAL[result.partial]||success,bad:!!result.partial};}
  $("admin-add").addEventListener("click",showCreate);
  $("admin-cancel-create").addEventListener("click",()=>{
    $("admin-new-password").value="";$("admin-create-form").hidden=true;$("admin-placeholder").hidden=false;
  });
  $("admin-refresh").addEventListener("click",()=>run(async live=>{
    const uid=current?.uid;await loadList(live);if(live()&&uid&&rows.some(r=>r.uid===uid))await loadDetail(uid,live);
    return {text:"Lista odświeżona."};
  }));
  $("admin-search").addEventListener("input",drawRows);$("admin-filter").addEventListener("change",drawRows);
  $("admin-offline").addEventListener("change",()=>{
    $("admin-offline-warning").hidden=$("admin-offline").value!=="-1";
  });
  $("admin-unlimited").addEventListener("change",()=>{
    $("admin-expiry").disabled=$("admin-unlimited").checked;
  });
  $("admin-create-form").addEventListener("submit",event=>{
    event.preventDefault();
    const password=$("admin-new-password").value,sendReset=$("admin-new-reset").checked;
    if(!password&&!sendReset){notice("Wpisz hasło lub zaznacz wysłanie wiadomości ustawienia hasła.",true);return;}
    const payload={email:$("admin-new-email").value.trim(),name:$("admin-new-name").value,password,sendReset};
    $("admin-new-password").value="";
    run(async live=>{
      const r=await rpc("create",payload);
      if(live()){await loadList(live);if(live()&&r.uid)await loadDetail(r.uid,live);}
      return partial(r,"Konto utworzone.");
    });
  });
  $("admin-edit-form").addEventListener("submit",event=>{
    event.preventDefault();if(!current)return;
    const p=current.policy;
    const limit=Number($("admin-limit").value),offline=Number($("admin-offline").value);
    if(!Number.isInteger(limit)||limit<0||limit>20||![0,72,-1].includes(offline)){
      notice("Limit: 0–20 (0 = bez limitu). Wybierz poprawny tryb offline.",true);return;
    }
    let expiresAt=null;
    if(!$("admin-unlimited").checked){
      const date=new Date($("admin-expiry").value);
      if(!Number.isFinite(date.getTime())){notice("Wybierz datę i godzinę ważności.",true);return;}
      expiresAt=date.toISOString();
    }
    const removeDevices=[...$("admin-devices").querySelectorAll("[data-remove-device]:checked")].map(x=>x.dataset.removeDevice);
    const uid=current.uid;
    const payload={uid,version:p?.version||"",name:$("admin-name").value,notes:$("admin-notes").value,
      active:$("admin-active").checked,expiresAt,deviceLimit:limit,offlineHours:offline,
      removeDevices,enableAuth:$("admin-enable-auth").checked};
    if(offline===-1&&(p?.offlineHours!==-1||(p?.expiresAt&&!expiresAt))&&!window.confirm(
      "Nadać dostęp offline bez limitu czasu? Będzie ograniczony wyłącznie ważnością konta. Licencji nie można cofnąć zdalnie, dopóki komputer nie połączy się z internetem."))return;
    if((removeDevices.length||!payload.active)&&!window.confirm("Zapisać zmianę dostępu lub usunąć zaznaczone rejestracje?"))return;
    run(async live=>{
      const r=await rpc("save",payload);
      if(live()){await loadList(live);if(live())await loadDetail(uid,live);}
      return partial(r,"Uprawnienia zapisane.");
    });
  });
  $("admin-reset").addEventListener("click",()=>{
    if(!current||!window.confirm("Wysłać wiadomość resetowania hasła do wybranego konta?"))return;
    const uid=current.uid;
    run(async()=>{await rpc("reset",{uid});return {text:"Wysłano żądanie wysłania e-maila resetowania hasła."};});
  });
  $("admin-delete").addEventListener("click",()=>{
    if(!current||current.owner)return;
    const uid=current.uid,confirmEmail=$("admin-confirm-email").value.trim();
    if(confirmEmail!==current.email){notice("Wpisz dokładny e-mail wybranego konta.",true);return;}
    if(!window.confirm("Trwale usunąć to konto i jego historię? Tej operacji nie można cofnąć."))return;
    run(async live=>{
      const r=await rpc("delete",{uid,confirmEmail});
      if(live()){
        current=null;$("admin-selected").hidden=true;$("admin-placeholder").hidden=false;$("admin-confirm-email").value="";
        await loadList(live);
      }
      return partial(r,"Konto usunięte.");
    });
  });

  function switchTab(tab){
    adminTab=tab;
    const users=tab==="users";
    for(const id of ["admin-stats","admin-users-toolbar","admin-users-body"])$(id).hidden=!users;
    $("admin-invites-body").hidden=users;
    $("admin-users-tab").classList.toggle("primary",users);
    $("admin-invites-tab").classList.toggle("primary",!users);
    $("admin-users-tab").setAttribute("aria-pressed",String(users));
    $("admin-invites-tab").setAttribute("aria-pressed",String(!users));
    if(users){$("invite-code").value="";$("invite-result").hidden=true;}
  }
  const inviteStatus={active:"Aktywny",revoked:"Unieważniony",expired:"Wygasły",used:"Wykorzystany"};
  const offlineLabel={0:"Wyłączona",72:"72 godziny","-1":"Bezterminowo"};
  function drawInvites(){
    const root=$("invite-rows");root.replaceChildren();
    $("invite-empty").hidden=inviteRows.length!==0;
    for(const r of inviteRows){
      const tr=node("tr");
      if(selectedInvite?.id===r.id)tr.classList.add("selected");
      const td=node("td"),pick=button(r.label||"Zaproszenie",()=>chooseInvite(r.id),"admin-user-link");
      pick.append(node("small","…"+r.hint+(r.email?" · "+r.email:"")));
      td.append(pick);tr.append(td);
      const state=node("td");
      state.append(node("span",inviteStatus[r.status]||"—","admin-status "+(r.status==="active"?"good":"bad")));
      tr.append(state,node("td",r.used+" / "+(r.maxUses||"∞")),
        node("td",r.expiresAt?displayDate(r.expiresAt):"Bezterminowo"));
      root.append(tr);
    }
  }
  async function loadInvites(live){
    const data=await rpc("invites_list");
    if(!live())return;
    inviteRows=Array.isArray(data.rows)?data.rows:[];
    $("invite-registration-enabled").checked=!!data.enabled;
    $("invite-truncated").hidden=!data.truncated;
    if(selectedInvite){
      selectedInvite=inviteRows.find(r=>r.id===selectedInvite.id)||null;
      if(!selectedInvite)$("invite-detail").hidden=true;
      else $("invite-revoke").disabled=selectedInvite.status!=="active";
    }
    drawInvites();
  }
  async function loadInviteDetail(id,live){
    const inv=inviteRows.find(r=>r.id===id);
    if(!inv)return;
    const hist=await rpc("invite_history",{id});
    if(!live())return;
    selectedInvite=inv;$("invite-detail").hidden=false;
    $("invite-detail-title").textContent=inv.label||("Kod …"+inv.hint);
    $("invite-detail-policy").textContent="Konto: "+(inv.accountDays?inv.accountDays+" dni":"bezterminowo")
      +" · Komputery: "+(inv.deviceLimit||"bez limitu")+" · Offline: "+offlineLabel[inv.offlineHours]
      +" · "+(inv.approval?"Wymaga akceptacji":"Automatyczny dostęp");
    $("invite-revoke").disabled=inv.status!=="active";
    const root=$("invite-history");root.replaceChildren();
    const records=Array.isArray(hist.rows)?hist.rows:[];
    if(!records.length)root.append(node("p","Kod nie został jeszcze wykorzystany.","admin-muted"));
    for(const record of records){
      const u=rows.find(x=>x.uid===record.uid);
      const item=node("div",undefined,"invite-history-row");
      item.append(node("strong",u?.email||"Konto "+record.uid),
        node("small",displayDate(record.at)+(record.approval?" · wymagało akceptacji":"")));
      root.append(item);
    }
    if(hist.truncated)root.append(node("p","Historia ograniczona do 500 wpisów.","admin-muted"));
    drawInvites();
  }
  function chooseInvite(id){run(async live=>{await loadInviteDetail(id,live);});}
  $("admin-users-tab").addEventListener("click",()=>{
    if(busy)return;
    switchTab("users");run(async live=>{await loadList(live);});
  });
  $("admin-invites-tab").addEventListener("click",()=>{
    if(busy)return;
    switchTab("invites");run(async live=>{await loadInvites(live);});
  });
  $("invite-refresh").addEventListener("click",()=>run(async live=>{
    const id=selectedInvite?.id;await loadInvites(live);
    if(live()&&id)await loadInviteDetail(id,live);
    return {text:"Lista zaproszeń odświeżona."};
  }));
  $("invite-settings-save").addEventListener("click",()=>{
    const enabled=$("invite-registration-enabled").checked;
    run(async live=>{
      await rpc("invite_settings",{enabled});
      if(live())await loadInvites(live);
      return {text:enabled?"Rejestracja włączona.":"Rejestracja wyłączona."};
    });
  });
  $("invite-email").addEventListener("input",()=>{
    if($("invite-email").value.trim())$("invite-max-uses").value="1";
  });
  $("invite-create-form").addEventListener("submit",event=>{
    event.preventDefault();
    const payload={label:$("invite-label").value,email:$("invite-email").value.trim(),
      maxUses:Number($("invite-max-uses").value),validDays:Number($("invite-valid-days").value),
      accountDays:Number($("invite-account-days").value),deviceLimit:Number($("invite-device-limit").value),
      offlineHours:Number($("invite-offline").value),approval:$("invite-approval").checked};
    if(payload.email&&payload.maxUses!==1){notice("Kod przypisany do e-maila musi być jednorazowy.",true);return;}
    if((!payload.maxUses||payload.offlineHours===-1)&&!window.confirm(
      "Kod ma nieograniczoną liczbę użyć lub umożliwia długotrwały offline. Utworzyć go?"))return;
    if($("invite-code").value&&!window.confirm("Nowy kod zastąpi poprzedni na ekranie. Czy skopiowałeś poprzedni kod?"))return;
    run(async live=>{
      const r=await rpc("invite_create",payload);
      if(live()){
        $("invite-code").value=r.code||"";$("invite-result").hidden=false;
        $("invite-code").focus();$("invite-code").select();
        await loadInvites(live);
      }
      return {text:"Zaproszenie utworzone. Skopiuj pełny kod."};
    });
  });
  $("invite-copy").addEventListener("click",async()=>{
    const code=$("invite-code").value;
    if(!code)return;
    $("invite-code").select();
    try{
      if(navigator.clipboard)await navigator.clipboard.writeText(code);
      else if(!document.execCommand("copy"))throw Error();
      notice("Kod skopiowany. Przekaż go wyłącznie zaproszonej osobie.");
    }catch{notice("Zaznaczyłem kod. Naciśnij Ctrl+C, aby go skopiować.");}
  });
  $("invite-revoke").addEventListener("click",()=>{
    if(!selectedInvite||selectedInvite.status!=="active"||
      !window.confirm("Unieważnić kod? Istniejące konta zachowają przyznane uprawnienia."))return;
    const id=selectedInvite.id;
    run(async live=>{
      await rpc("invite_revoke",{id});
      if(live()){await loadInvites(live);if(live())await loadInviteDetail(id,live);}
      return {text:"Zaproszenie unieważnione."};
    });
  });

  $("admin-close").addEventListener("click",()=>{if(!busy)dialog.close();});
  dialog.addEventListener("cancel",e=>{if(busy)e.preventDefault();});
  dialog.addEventListener("close",clear);
  window.GeoStudioAdmin={
    syncAccess(data){
      allowed=!!data.admin&&!!data.active&&!data.offline;
      if(!allowed&&dialog.open){clear();dialog.close();}
    },
    open(){
      if(!allowed||busy||dialog.open)return;
      clear();dialog.showModal();
      run(async live=>{await loadList(live);});
    }
  };
})();