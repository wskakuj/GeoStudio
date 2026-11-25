const fs=require("node:fs"),path=require("node:path"),vm=require("node:vm");
const assert=require("node:assert/strict");
const source=fs.readFileSync(path.join(__dirname,"../geostudio/web_app/static/map.js"),"utf8");
function section(start,end){
  const a=source.indexOf(start),b=source.indexOf(end,a);
  assert.ok(a>=0&&b>a,`Missing production section: ${start}`);
  return source.slice(a,b);
}
const client=section("  const api = async", "  // Zabezpieczenie:")+
  section("  function wmsLayersState(", "  async function readUnderlayPrj(")+
  section("  function currentWmsUrl(", "  function openUnderlayDialog(");

function classes(){
  const values=new Set();
  return {toggle(name,on){if(on)values.add(name);else values.delete(name);},
    contains:name=>values.has(name)};
}
function harness(){
  const fields={
    "underlay-preset":{value:"custom"},
    "underlay-url":{value:"https://first.example.test/wms"},
    "underlay-layers":{classList:classes(),textContent:""},
    "underlay-show":{disabled:false},
    "underlay-summary":{classList:classes(),textContent:""},
    "underlay-layer":{options:[],replaceChildren(...options){this.options=options;},
      add(option){this.options.push(option);}},
  };
  const requests=[],timers=new Map();let serial=0;
  const h={fields,requests,timers,URLSearchParams,AbortController,token:"test",
    $:id=>fields[id],inform(){},
    Option:class{constructor(text,value){this.textContent=text;this.value=value;this.dataset={};}},
    setTimeout:(fn,ms)=>{const id=++serial;timers.set(id,{fn,ms});return id;},
    clearTimeout:id=>timers.delete(id),
    documentFetch:(url,options)=>new Promise((resolve,reject)=>{
      const request={url,options,resolve,reject,aborted:false};requests.push(request);
      options.signal?.addEventListener("abort",()=>{
        request.aborted=true;
        reject(Object.assign(new Error("Cancelled"),{name:"AbortError"}));
      });
    }),
    reply(index,id){requests[index].resolve({ok:true,json:async()=>({
      layers:[{id,title:id,epsg:[2180]}]})});},
    deferJSON(index){requests[index].resolve({ok:true,json:()=>new Promise(resolve=>{
      requests[index].finishJSON=id=>resolve({layers:[{id,title:id,epsg:[2180]}]});
    })});},
    fireTimer(ms){
      const entry=[...timers].find(([,timer])=>timer.ms===ms);
      assert.ok(entry,`Missing timer ${ms}`);
      timers.delete(entry[0]);return entry[1].fn();
    },
  };
  vm.createContext(h);vm.runInContext(client,h);return h;
}
async function flush(){for(let n=0;n<20;n++)await Promise.resolve();}

const scenarios={
  async layers_timeout_and_retry(){
    const h=harness(),button=h.fields["underlay-layers"];
    const first=h.loadUnderlayLayers();
    assert.equal(button.classList.contains("is-busy"),true);
    h.fireTimer(40000);await first;
    assert.equal(h.requests[0].aborted,true);
    assert.equal(button.classList.contains("is-busy"),false);
    assert.equal(button.classList.contains("is-error"),true);
    assert.match(h.fields["underlay-summary"].textContent,/40 s/);
    assert.equal(h.timers.size,0);
    const retry=h.loadUnderlayLayers();h.reply(1,"Current");await retry;
    assert.equal(button.classList.contains("is-ok"),true);
    assert.equal(button.classList.contains("is-busy"),false);
    assert.equal(button.classList.contains("is-error"),false);
    assert.equal(h.fields["underlay-layer"].options[0].value,"Current");
    assert.equal(h.timers.size,0);
  },
  async layers_latest_custom_url_wins(){
    const h=harness(),first=h.loadUnderlayLayers();
    const firstParams=new URLSearchParams(h.requests[0].url.split("?")[1]);
    assert.equal(firstParams.get("preset"),"custom");
    assert.equal(firstParams.get("url"),"https://first.example.test/wms");
    h.deferJSON(0);await flush();
    h.fields["underlay-url"].value="https://second.example.test/wms";
    const second=h.loadUnderlayLayers();h.reply(1,"Second URL");await second;
    const secondParams=new URLSearchParams(h.requests[1].url.split("?")[1]);
    assert.equal(secondParams.get("preset"),"custom");
    assert.equal(secondParams.get("url"),"https://second.example.test/wms");
    h.requests[0].finishJSON("First URL");await first;
    assert.equal(h.fields["underlay-layer"].options[0].value,"Second URL");
    assert.equal(h.requests[0].aborted,true);
    assert.equal(h.fields["underlay-layers"].classList.contains("is-ok"),true);
    assert.equal(h.timers.size,0);
  },
  async layers_same_source_second_attempt_wins(){
    const h=harness(),first=h.loadUnderlayLayers();
    h.deferJSON(0);await flush();
    const second=h.loadUnderlayLayers();h.reply(1,"New response");await second;
    h.requests[0].finishJSON("Old response");await first;
    assert.equal(h.fields["underlay-layer"].options[0].value,"New response");
    assert.equal(h.requests[0].aborted,true);
    assert.equal(h.timers.size,0);
  },
  async layers_filter_clears_selection_and_cancels_request(){
    const h=harness(),first=h.loadUnderlayLayers();
    h.deferJSON(0);await flush();
    h.fields["underlay-preset"].value="";
    await h.loadUnderlayLayers();
    assert.equal(h.requests.length,1,"Filtering must not request an empty preset");
    assert.equal(h.requests[0].aborted,true);
    assert.equal(h.fields["underlay-layer"].options[0].value,"");
    assert.equal(h.fields["underlay-show"].disabled,true);
    assert.equal(h.fields["underlay-layers"].disabled,true);
    h.requests[0].finishJSON("Obsolete");await first;
    assert.equal(h.fields["underlay-layer"].options[0].value,"");
    h.fields["underlay-preset"].value="bdl_basic";
    const next=h.loadUnderlayLayers();
    assert.equal(h.fields["underlay-layers"].disabled,false);
    h.reply(1,"Forest");await next;
    assert.equal(h.fields["underlay-layer"].options[0].value,"Forest");
    assert.equal(h.fields["underlay-show"].disabled,false);
    assert.equal(h.timers.size,0);
  },
  async layers_changed_url_without_retry_is_idle(){
    const h=harness(),first=h.loadUnderlayLayers();
    h.fields["underlay-url"].value="https://second.example.test/wms";
    h.reply(0,"First URL");await first;
    assert.equal(h.fields["underlay-layer"].options[0].value,"");
    assert.equal(h.fields["underlay-layers"].classList.contains("is-busy"),false);
    assert.equal(h.fields["underlay-layers"].textContent,"Pobierz warstwy");
    assert.equal(h.timers.size,0);
  },
};
(async()=>{
  const name=process.argv[2];assert.ok(scenarios[name],`Unknown scenario: ${name}`);
  let guard;
  try{
    await Promise.race([scenarios[name](),new Promise((_,reject)=>{
      guard=setTimeout(()=>reject(new Error("Scenario did not finish")),5000);
    })]);
  }finally{clearTimeout(guard);}
})().catch(error=>{console.error(error);process.exitCode=1;});
