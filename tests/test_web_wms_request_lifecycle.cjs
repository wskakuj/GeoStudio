/* Execute production WMS functions, without DOM layout or a real WMS server. */
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const assert=require("node:assert/strict");

const source=fs.readFileSync(path.join(__dirname,"../geostudio/web_app/static/map.js"),"utf8");
function section(start,end){
  const a=source.indexOf(start),b=source.indexOf(end,a);
  assert.ok(a>=0&&b>a,`Missing production section: ${start}`);
  return source.slice(a,b);
}
const client=section("  function underlayRequestDimensions(","  function paintUnderlay(){")+
  section("  function boundsFromViewport(","  function fitToMap()")+
  section("  function removeUnderlay(","  function wmsLayersState(")+
  section("  function resizeCanvas()", "  function worldToScreen(")+
  section("  function scheduleViewport(", "  // Stage 11:");

function harness({autoDecode=true}={}){
  const fetches=[],images=[],statuses=[],timers=new Map(),clock={now:Date.now()};
  let timerId=0;
  const item={kind:"wms",id:"wms1",title:"Orto",visible:true,preset:"standard",
    layer:"Raster",epsg:2180,ticket:0,image:null,bounds:null,loading:false,error:""};
  const state={meta:{},edit:{documentToken:"map-A"},center:{x:500000,y:-400000},
    width:1000,height:800,scale:1,pixelRatio:1,localMapReady:true};
  const underlay={enabled:true,loading:false,epsg:2180,ticket:0,activeId:item.id};
  const fields={
    "underlay-epsg":{value:"2180"},"underlay-preset":{value:"standard"},
    "underlay-layer":{selectedOptions:[{value:"Raster",textContent:"Orto",dataset:{epsg:"2180"}}]},
    "underlay-opacity":{value:"75"},"underlay-summary":{},
  };
  const rect={width:1000,height:800};
  const h={state,underlay,underlays:[item],underlaySerial:1,item,fields,fetches,images,statuses,timers,clock,rect,
    URLSearchParams,AbortController,Date:class extends Date{static now(){return clock.now;}},
    performance,token:"test",timePresets:new Set(),
    window:{devicePixelRatio:1},shell:{getBoundingClientRect:()=>rect},
    canvas:{width:1000,height:800},labelCanvas:{width:1000,height:800},
    $:id=>fields[id],currentWmsUrl:()=>"",inform(){},requestDraw(){},renderRasterLayers(){},
    updateUnderlayStatus:message=>statuses.push(message),
    setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;},
    clearTimeout:id=>timers.delete(id),
    documentFetch:(url,options)=>new Promise((resolve,reject)=>{
      const request={url,options,resolve,reject,aborted:false};fetches.push(request);
      options.signal.addEventListener("abort",()=>{
        request.aborted=true;
        reject(Object.assign(new Error("Cancelled"),{name:"AbortError"}));
      });
    }),
    URL:{createObjectURL:()=>"blob:test",revokeObjectURL(){}},
    Image:class{
      set src(_url){images.push(this);if(autoDecode)queueMicrotask(()=>this.onload());}
    },
    respond(index){fetches[index].resolve({ok:true,blob:async()=>({})});},
    fireTimer(ms){
      const entry=[...timers].find(([,timer])=>timer.ms===ms);
      assert.ok(entry,`Missing timer ${ms}`);
      timers.delete(entry[0]);return entry[1].fn();
    },
  };
  vm.createContext(h);vm.runInContext(client,h);
  return h;
}
async function flush(){for(let n=0;n<20;n++)await Promise.resolve();}
async function loaded(h){const work=h.refreshUnderlay();h.respond(0);await work;}
function rasterLayerUI(h){
  function element(){
    return {children:[],listeners:{},value:"",setAttribute(){},
      append(...children){this.children.push(...children);},
      replaceChildren(...children){this.children=children;},
      addEventListener(name,callback){this.listeners[name]=callback;}};
  }
  for(const id of ["trace-raster-choice","raster-layers-list","raster-layer-count"])
    h.fields[id]=element();
  h.document={createElement:element};h.Option=class{};
  h.raster={layers:[]};h.rasterEntry=()=>null;h.rasterCanShow=()=>false;
  h.underlayTitle=item=>item.title;
  vm.runInContext(section("  function renderRasterLayers(){", "  function parseWorldFileText("),h);
  return checked=>{
    h.renderRasterLayers();
    const checkbox=h.fields["raster-layers-list"].children[0].children[0].children[0];
    checkbox.checked=checked;checkbox.listeners.change();
  };
}

const scenarios={
  async same_view_does_not_restart_debounce(){
    const h=harness();h.scheduleUnderlayRefresh();
    const scheduled=h.underlay.timer;
    for(let n=0;n<20;n++)h.scheduleUnderlayRefresh();
    assert.equal(h.underlay.timer,scheduled,"Redundant triggers must not postpone the same pending frame");
    const request=h.fireTimer(380);h.respond(0);await request;
    h.scheduleUnderlayRefresh();
    assert.equal(h.timers.size,0);
    assert.equal(h.fetches.length,1);
  },
  async unchanged_resize_does_not_schedule_fetch(){
    const h=harness();
    h.resizeCanvas();
    assert.equal(h.timers.size,0,"A layout callback without a size change is not a new WMS view");
    assert.equal(h.underlay.loading,false);
    h.rect.width=1100;
    assert.equal(h.resizeCanvas(),true);
    const request=h.fireTimer(380);h.respond(0);await request;
    h.resizeCanvas();
    assert.equal(h.timers.size,0);
    assert.equal(h.fetches.length,1);
  },
  async same_view_after_error_does_not_retry(){
    const h=harness();h.scheduleUnderlayRefresh();
    const request=h.fireTimer(380);
    h.fetches[0].reject(new Error("Request failed"));await request;
    const failure=h.item.error;
    h.clock.now+=6000;
    for(let n=0;n<10;n++)h.scheduleViewport();
    assert.equal(h.timers.size,0,"Unchanged geometry refresh must not retry a failed WMS image");
    assert.equal(h.fetches.length,1);
    assert.equal(h.item.error,failure);
    assert.equal(h.underlay.loading,false);
  },
  async client_timeout_finishes_loading_without_retry(){
    const h=harness();h.scheduleUnderlayRefresh();
    const request=h.fireTimer(380);
    h.fireTimer(40000);await request;
    assert.equal(h.fetches[0].aborted,true);
    assert.equal(h.item.loading,false);
    assert.equal(h.underlay.loading,false);
    assert.equal(h.item.request,null);
    assert.match(h.item.error,/40 s/);
    assert.match(h.statuses.at(-1),/błąd/);
    h.clock.now+=60000;h.scheduleViewport();
    assert.equal(h.timers.size,0,"Timeout must not schedule an implicit retry");
    assert.equal(h.fetches.length,1);
  },
  async client_timeout_during_decode_allows_manual_retry(){
    const h=harness({autoDecode:false});h.scheduleUnderlayRefresh();
    const request=h.fireTimer(380);h.respond(0);await flush();
    assert.equal(h.images.length,1);
    h.fireTimer(40000);await request;
    assert.equal(h.item.image,null);
    assert.equal(h.item.loading,false);
    assert.equal(h.underlay.loading,false);
    assert.match(h.item.error,/40 s/);
    h.images[0].onload();await flush();
    assert.equal(h.item.image,null,"A decode completing after the deadline cannot publish an image");
    h.applyUnderlayUnsafe();
    const retry=h.fireTimer(0);h.respond(1);await flush();
    h.images[1].onload();await retry;
    assert.equal(h.item.image,h.images[1]);
    assert.equal(h.item.error,"");
    assert.equal(h.timers.size,0);
  },
  async show_after_timeout_bypasses_cooldown(){
    const h=harness(),setVisible=rasterLayerUI(h);
    h.scheduleUnderlayRefresh();const request=h.fireTimer(380);
    h.fireTimer(40000);await request;
    assert.ok(h.item.retryAfter>h.clock.now);
    setVisible(false);setVisible(true);
    assert.equal(h.item.retryAfter,0,"Showing a failed layer is an explicit retry");
    assert.equal(h.item.error,"");
    const retry=h.fireTimer(0);
    assert.equal(h.fetches.length,2,"The visibility checkbox must retry before cooldown expires");
    h.respond(1);await retry;
    assert.ok(h.item.image);
    assert.equal(h.item.loading,false);
    assert.equal(h.underlay.loading,false);
    assert.equal(h.timers.size,0);
  },
  async hidpi_zoom_cancels_obsolete_image(){
    const h=harness();
    h.state.width=400;h.state.height=300;h.state.pixelRatio=2;
    h.scheduleUnderlayRefresh();
    assert.equal(h.fetches.length,0,"Wait for the pan/zoom debounce");
    const first=h.fireTimer(380);
    const firstParams=new URLSearchParams(h.fetches[0].url.split("?")[1]);
    assert.equal(+firstParams.get("width"),800);
    assert.equal(+firstParams.get("height"),600);
    const firstSpan=+firstParams.get("xmax")- +firstParams.get("xmin");
    h.state.scale*=2;
    h.scheduleUnderlayRefresh();
    assert.equal(h.fetches.length,1);
    const zoomed=h.fireTimer(380);await flush();
    assert.equal(h.fetches.length,2);
    assert.equal(h.fetches[0].aborted,true,"Zoom must replace an insufficiently sharp pending image");
    assert.equal(h.fetches[1].aborted,false);
    assert.equal(h.item.loading,true);
    assert.equal(h.underlay.loading,true);
    const nextParams=new URLSearchParams(h.fetches[1].url.split("?")[1]);
    assert.equal(+nextParams.get("width"),800);
    assert.equal(+nextParams.get("xmax")- +nextParams.get("xmin"),firstSpan/2);
    h.respond(1);await Promise.all([first,zoomed]);
    assert.equal(h.item.image,h.images[0]);
    assert.equal(h.item.bounds[0],+nextParams.get("xmin"));
    assert.equal(h.item.bounds[2],+nextParams.get("xmax"));
    assert.equal(h.item.loading,false);
    assert.equal(h.underlay.loading,false);
  },
  async cached_small_pan(){
    const h=harness();await loaded(h);
    const originalImage=h.item.image,originalBounds=h.item.bounds;
    // Repeating the same camera and short pans must reuse the padded image.
    await h.refreshUnderlay();
    h.state.center.x+=10;h.state.center.y-=10;
    await h.refreshUnderlay();
    assert.equal(h.fetches.length,1);
    assert.equal(h.item.image,originalImage);
    assert.equal(h.item.bounds,originalBounds);
    assert.equal(h.item.loading,false);
    assert.equal(h.underlay.loading,false);
    // No speculative request is scheduled after the foreground image is ready.
    assert.equal(h.timers.size,0);
  },
  async zoom_requests_sharper_image(){
    const h=harness();await loaded(h);
    const density=h.item.density;
    h.state.scale*=2;
    const work=h.refreshUnderlay();
    assert.equal(h.fetches.length,2,"Containment alone must not reuse blurry pixels");
    h.respond(1);await work;
    assert.equal(h.item.density,2*density);
  },
  async pending_small_pans_share_download(){
    const h=harness(),work=[h.refreshUnderlay()];
    for(let n=0;n<10;n++){
      h.state.center.x+=1;
      h.scheduleUnderlayRefresh();
      work.push(h.fireTimer(380));
    }
    assert.equal(h.fetches.length,1);
    assert.equal(h.fetches[0].aborted,false);
    assert.equal(h.underlay.loading,true);
    h.respond(0);await Promise.all(work);
    assert.ok(h.item.image);
    assert.equal(h.underlay.loading,false);
    assert.equal(h.item.request,null);
    assert.equal(h.timers.size,0);
  },
  async aborted_batch_cannot_finish_new_status(){
    const h=harness(),first=h.refreshUnderlay();
    h.state.center.x+=500;
    const second=h.refreshUnderlay();
    await flush();await first;
    assert.equal(h.fetches.length,2);
    assert.equal(h.fetches[0].aborted,true);
    assert.equal(h.fetches[1].aborted,false);
    assert.equal(h.underlay.loading,true,"Old finally must not finish the new batch");
    assert.equal(h.item.loading,true);
    assert.equal(h.statuses.length,0);
    assert.deepEqual([...h.timers.values()].map(timer=>timer.ms),[40000],
      "Only the current request deadline may remain; no prefetch or stale deadline");
    h.respond(1);await second;
    assert.ok(h.item.image);
    assert.equal(h.underlay.loading,false);
    assert.equal(h.statuses.length,1);
  },
  async late_decode_cannot_replace_current_image(){
    const h=harness({autoDecode:false}),first=h.refreshUnderlay();
    h.respond(0);await flush();
    assert.equal(h.images.length,1);
    h.state.center.x+=500;
    const second=h.refreshUnderlay();h.respond(1);await flush();
    assert.equal(h.images.length,2);
    h.images[1].onload();await second;
    const currentBounds=h.item.bounds;
    h.images[0].onload();await first;
    assert.equal(h.item.image,h.images[1]);
    assert.equal(h.item.bounds,currentBounds);
    assert.equal(h.statuses.length,1);
  },
  async return_to_cached_view_cancels_unneeded_request(){
    const h=harness();await loaded(h);
    const image=h.item.image;
    h.state.center.x+=1000;
    const away=h.refreshUnderlay();
    h.state.center.x-=1000;
    await h.refreshUnderlay();await away;
    assert.equal(h.fetches.length,2);
    assert.equal(h.fetches[1].aborted,true);
    assert.equal(h.item.image,image);
    assert.equal(h.item.request,null);
    assert.equal(h.item.loading,false);
    assert.equal(h.underlay.loading,false);
  },
  async manual_retry_bypasses_cooldown(){
    const h=harness(),failed=h.refreshUnderlay();
    h.fetches[0].reject(new Error("Temporary upstream failure"));await failed;
    assert.ok(h.item.retryAfter>Date.now());
    await h.refreshUnderlay();assert.equal(h.fetches.length,1);
    h.applyUnderlayUnsafe();
    assert.equal(h.item.retryAfter,0);
    assert.equal(h.item.error,"");
    const retry=h.fireTimer(0);
    assert.equal(h.fetches.length,2);
    h.respond(1);await retry;
    assert.ok(h.item.image);
    assert.equal(h.item.loading,false);
  },
  async return_to_cached_view_clears_obsolete_error(){
    const h=harness();await loaded(h);
    h.state.center.x+=1000;
    const away=h.refreshUnderlay();
    h.fetches[1].reject(new Error("Temporary upstream failure"));await away;
    assert.ok(h.item.error);
    h.state.center.x-=1000;await h.refreshUnderlay();
    assert.equal(h.fetches.length,2);
    assert.equal(h.item.error,"");
    assert.equal(h.item.retryAfter,0);
    assert.match(h.statuses.at(-1),/Podkład gotowy/);
  },
  async remove_cancels_request(){
    const h=harness(),work=h.refreshUnderlay();
    h.removeUnderlay(h.item.id);await work;
    assert.equal(h.fetches[0].aborted,true);
    assert.equal(h.underlays.length,0);
    assert.equal(h.underlay.enabled,false);
    assert.equal(h.underlay.loading,false);
    assert.equal(h.item.image,null);
    assert.equal(h.item.request,null);
    assert.equal(h.timers.size,0);
  },
  async remove_keeps_other_layer_refresh(){
    // Remove A before the debounced A+B refresh has started: B still loads.
    const queued=harness();
    const remaining={...queued.item,id:"wms2",layer:"other"};
    queued.underlays.push(remaining);
    queued.scheduleUnderlayRefresh();
    queued.removeUnderlay(queued.item.id);
    assert.equal(queued.underlay.loading,true);
    const load=queued.fireTimer(0);
    assert.equal(queued.fetches.length,1);
    queued.respond(0);await load;
    assert.ok(remaining.image);
    assert.equal(queued.item.image,null);
    assert.equal(queued.underlay.loading,false);
    assert.match(queued.statuses.at(-1),/Podkład gotowy/);

    // Remove A while B is already downloading: keep B's request and status.
    const active=harness();
    const pending={...active.item,id:"wms2",layer:"other"};
    active.underlays.push(pending);
    const original=active.refreshUnderlay();
    active.removeUnderlay(active.item.id);
    const refresh=active.fireTimer(0);
    await flush();
    assert.equal(active.fetches.length,2);
    assert.equal(active.fetches[0].aborted,true);
    assert.equal(active.fetches[1].aborted,false);
    assert.equal(active.underlay.loading,true);
    active.respond(1);await Promise.all([original,refresh]);
    assert.ok(pending.image);
    assert.equal(active.underlay.loading,false);
    assert.match(active.statuses.at(-1),/Podkład gotowy/);
  },
  async visible_layers_load_independently(){
    const h=harness();
    const other={...h.item,id:"wms2",preset:"kieg",layer:"dzialki"};
    h.underlays.push(other);
    const work=h.refreshUnderlay();
    assert.equal(h.fetches.length,2);
    h.item.visible=false;h.cancelUnderlayRequest(h.item);
    await flush();
    assert.equal(h.fetches[0].aborted,true);
    assert.equal(h.fetches[1].aborted,false);
    assert.equal(h.underlay.loading,true);
    h.respond(1);await work;
    assert.ok(other.image);
    assert.equal(h.item.image,null);
    assert.equal(h.underlay.loading,false);
  },
};

(async()=>{
  const name=process.argv[2];assert.ok(scenarios[name],`Unknown scenario: ${name}`);
  // An unresolved Promise alone would let Node exit successfully. Fail instead.
  let guard;
  try{
    await Promise.race([scenarios[name](),new Promise((_,reject)=>{
      guard=setTimeout(()=>reject(new Error("Scenario did not finish")),5000);
    })]);
  }finally{clearTimeout(guard);}
})().catch(error=>{console.error(error);process.exitCode=1;});
