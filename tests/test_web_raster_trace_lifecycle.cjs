// Run the actual tracing UI with a deterministic DOM/Worker boundary.
// No user-supplied raster or MAP data is embedded in this test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../geostudio/web_app/static/raster_trace.js'), 'utf8');
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

function createUI(featureLoads = [], options = {}) {
  const workers = [], controls = new Map(), draws = { count: 0 };
  const fitCalls = [], fitOptions = [], addCalls = [], snapCalls = [], snapOptions = [], imageCaptures = [];
  const timers = new Map(); let timerID = 0, fitIndex = 0;
  const scale = options.scale || 1;
  const screenOrigin = options.screenOrigin || [0, 0];
  let panel, canvas, featureCalls = 0, closed = 0, added = 0, currentPath = [];
  const context = new Proxy({
    clearRect() { draws.count++; draws.rings = []; },
    beginPath() { currentPath = []; },
    moveTo(x,y) { currentPath.push([x,y]); },
    lineTo(x,y) { currentPath.push([x,y]); },
    stroke() { if(currentPath.length>=3)draws.rings.push(currentPath.slice()); },
    getImageData(x, y, width, height) {
      imageCaptures.push((draws.rings||[]).map(ring=>ring.slice()));
      // Workers are the mocked boundary here; do not allocate 12M real pixels.
      return { data: new Uint8ClampedArray(4) };
    },
  }, { get(target, name) { return target[name] || (() => {}); } });
  function element() {
    return {
      value: '', checked: false, disabled: false, textContent: '', removed: false,
      setAttribute() {}, focus() {}, setPointerCapture() {},
      getBoundingClientRect() { return { left: 0, top: 0 }; },
      remove() { this.removed = true; },
      getContext() { return context; },
      querySelector(selector) {
        if (!controls.has(selector)) {
          const control = element();
          if (selector === 'select') control.value = '5';
          if (selector === '.trace-tolerance') control.value = '2.5';
          if (selector === '.trace-quality') control.value = '12000000';
          if (selector === '.trace-merge-a1') control.checked = true;
          controls.set(selector, control);
        }
        return controls.get(selector);
      },
    };
  }
  class Worker {
    constructor(url) {
      assert.equal(url, '/raster_trace.js');
      this.messages = [];
      this.terminated = false;
      workers.push(this);
      assert.equal(workers.filter(worker => !worker.terminated).length, 1,
        'only one image-analysis worker may remain alive');
    }
    postMessage(data) {
      assert.equal(this.terminated, false);
      this.messages.push(data);
    }
    terminate() { this.terminated = true; }
    analysisID() { return this.messages.filter(message => 'threshold' in message).at(-1).id; }
    result(trace, id = this.analysisID()) {
      const sheet = this.messages.find(message => message.source);
      this.onmessage({ data: { id, trace: trace || sampleTrace(sheet.w, sheet.h) } });
    }
  }
  const sandbox = {
    console, Worker, Uint8ClampedArray, AbortController,
    setTimeout(callback) { const id = ++timerID; timers.set(id, callback); return id; },
    clearTimeout(id) { timers.delete(id); },
    window: { devicePixelRatio: 1, GeoStudioDrawingSnap: {
      snapPoint(world, targets, snapSettings) { snapCalls.push(targets); snapOptions.push(snapSettings); return { point: world, kind: null }; },
    } },
    ResizeObserver: class { observe() {} disconnect() {} },
    document: {
      createElement(tag) {
        const result = element();
        if (tag === 'section') panel = result;
        return result;
      },
    },
  };
  vm.createContext(sandbox);
  const parcelSource = fs.readFileSync(path.join(__dirname, '../geostudio/web_app/static/raster_parcel_snap.js'), 'utf8');
  vm.runInContext(parcelSource, sandbox, { filename: 'raster_parcel_snap.js' });
  // In a browser globalThis and window are the same global object. The narrow
  // DOM fixture keeps window separate, so expose the actual helper on both.
  sandbox.window.GeoStudioRasterParcelSnap = sandbox.GeoStudioRasterParcelSnap;
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../geostudio/web_app/static/raster_a1.js'), 'utf8'),sandbox);
  vm.runInContext(source, sandbox, { filename: 'raster_trace.js' });
  const view = {
    shell: { clientWidth: 160, clientHeight: 120, append(overlay) { canvas = overlay; } },
    token: 'test-document',
    worldToScreen: (x, y) => ({ x: (x - screenOrigin[0]) * scale, y: -(y - screenOrigin[1]) * scale }),
    screenToWorld: (x, y) => ({ x: x / scale + screenOrigin[0], y: -y / scale + screenOrigin[1] }),
    scale: () => scale, magnetEnabled: () => false, isVisible: options.isVisible || (() => true),
    featuresIn() { return featureLoads[featureCalls++] || Promise.resolve([]); },
    fitOutline: async (points, settings) => {
      fitCalls.push(points);
      fitOptions.push(settings);
      return options.fitLoads?.[fitIndex++] || { points, clipped: false };
    },
    async add(points, a1, fitted) { added++; addCalls.push({ points, a1, fitted }); }, async refresh() {},
    closed() { closed++; },
  };
  const a1Requests=[];
  if(options.a1Load)view.recognizeA1=signal=>{a1Requests.push(signal);return options.a1Load;};
  const api = sandbox.openRasterTracing({
    id: 1, image: { width: options.width || 160, height: options.height || 120 },
    sourceWidth: options.sourceWidth, sourceHeight: options.sourceHeight,
    affine: options.affine || [0, 1, 0, 1, 0, 0],
  }, view);
  const click = async (clientX = 50, clientY = 50) => {
    const event = { button: 0, clientX, clientY, pointerId: 1, preventDefault() {} };
    canvas.onpointerdown(event);
    canvas.onpointerup(event);
    await tick();
    controls.get('.trace-a1').value = '17';
    controls.get('.trace-a1').oninput();
  };
  return {
    api, workers, controls, draws, click, fitCalls, fitOptions, addCalls, snapCalls, snapOptions, imageCaptures, a1Requests, timers,
    canvas: () => canvas,
    status: () => controls.get('[role=status]').textContent,
    panel: () => panel,
    added: () => added,
    closed: () => closed,
    featureCalls: () => featureCalls,
  };
}

function sampleTrace(width = 160, height = 120) {
  const points = [[width / 8, height / 6], [width * 5 / 8, height / 6],
    [width * 5 / 8, height * 5 / 6], [width / 8, height * 5 / 6]];
  // A deterministic single-region worker output; full raster segmentation is
  // separately exercised by test_web_raster_trace_geometry/annotations.
  const labels = new Proxy({}, { get: () => 1 });
  return { labels, shapes: new Map([[1, { points, bounds: [points[0][0], points[0][1],
    points[2][0], points[2][1]], suggested: true }]]) };
}

function closePoints(actual, expected) {
  assert.equal(actual.length, expected.length);
  for (let i = 0; i < actual.length; i++) for (let j = 0; j < 2; j++)
    assert.ok(Math.abs(actual[i][j] - expected[i][j]) < 1e-8,
      'MAP coordinates must remain unchanged when analysis resolution changes');
}

function adjacentTrace() {
  const labels = new Int32Array(160 * 120);
  for (let y = 20; y < 100; y++) for (let x = 20; x < 100; x++)
    labels[y * 160 + x] = x < 60 ? 1 : 2;
  const shapes = new Map();
  for (const [id, left, right] of [[1, 20, 60], [2, 60, 100]]) shapes.set(id, {
    points: [[left, 20], [right, 20], [right, 100], [left, 100]],
    bounds: [left, 20, right, 100], suggested: true,
  });
  return { labels, shapes, tolerance: 2.5 };
}

function thinAndWideTrace() {
  const labels = new Int32Array(160 * 120);
  for (let y = 20; y < 100; y++) for (let x = 20; x < 130; x++)
    labels[y * 160 + x] = x < 30 ? 1 : 2;
  const shapes = new Map();
  for (const [id, left, right] of [[1, 20, 30], [2, 30, 130]]) shapes.set(id, {
    points: [[left, 20], [right, 20], [right, 100], [left, 100]],
    bounds: [left, 20, right, 100], suggested: true,
  });
  return { labels, shapes, tolerance: 2.5 };
}

function ringArea(points) {
  let sum = 0;
  points.forEach((p, i) => {
    const q = points[(i + 1) % points.length];
    sum += p[0] * q[1] - p[1] * q[0];
  });
  return Math.abs(sum / 2);
}

function sameRing(actual, expected) {
  assert.equal(actual.length, expected.length, 'The fitted outline must keep the expected corners');
  for (const point of expected) assert.ok(actual.some(candidate =>
    Math.hypot(point[0] - candidate[0], point[1] - candidate[1]) < 1e-8),
  `The fitted outline must contain the exact MAP corner ${point}`);
}

function rectangle5216(left = 21, top = 21, right = 101, bottom = 101) {
  return { code: '5216', closed: true, geometry: [[
    [left, -top], [right, -top], [right, -bottom], [left, -bottom], [left, -top],
  ]] };
}

const originalNative = [[20, 20], [20, 100], [100, 100], [100, 20]];
const fittedNative = [[21, 21], [21, 101], [101, 101], [101, 21]];

function pointer(clientX, clientY, extra = {}) {
  return { button: 0, clientX, clientY, pointerId: 1,
    preventDefault() {}, stopPropagation() {}, ...extra };
}

function mapTracingView(batches, ocrResponses=[]) {
  const text = fs.readFileSync(path.join(__dirname, '../geostudio/web_app/static/map.js'), 'utf8');
  const start = text.indexOf('function startRasterTracing(){');
  const stop = text.indexOf('function renderRasterLayers(){', start);
  assert.ok(start >= 0 && stop > start, 'The map integration entry point must be present');
  const requests = [],fetchRequests=[];
  const entry={id:1,digest:'a'.repeat(64),file:{name:'synthetic.png'}};
  const state = { editBusy: false, edit: { documentToken: 'fixture-map', revision: 7 },
    width: 1000, height: 800, center: { x: 0, y: 0 }, scale: 1 };
  const control = { value: '1', classList: { add() {}, remove() {} }, setAttribute() {} };
  let view;
  const sandbox = {
    URLSearchParams, state, activeTrace: null, shell: {}, raster: { layers: [] },token:'test-api-token',
    $: () => control, rasterEntry: () => entry, rasterCanShow: () => true,
    setTool() {}, worldToScreen() {}, screenToWorld() {}, zoomAt() {},
    requestDraw() {}, scheduleViewport() {}, toggleDrawMagnet() {}, isVisible: () => false,
    api: async url => { requests.push(new URL(url, 'http://fixture.local')); return batches[requests.length - 1]; },
    documentFetch:async (url,options)=>{fetchRequests.push({url,options});return ocrResponses[fetchRequests.length-1];},
    openRasterTracing(_entry, callbacks) { view = callbacks; return {}; },
  };
  vm.createContext(sandbox);
  vm.runInContext(text.slice(start, stop), sandbox, { filename: 'map.js:startRasterTracing' });
  sandbox.startRasterTracing();
  return { view, requests, state, fetchRequests,entry };
}

const cases = {
  async asynchronous_a1_fills_current_field_and_never_overwrites_manual_input() {
    const result={width:160,height:120,annotations:[
      {text:'178',status:'ok',confidence:.98,anchor:[40,50],source:'callout',hasLeader:true,leaderEndpoints:[[40,50]]},
      {text:'175',status:'ok',confidence:.98,anchor:[80,50],source:'inside',hasLeader:false}]};
    for(const manual of [false,true]){
      const ocr=deferred(),ui=createUI([Promise.resolve([])],{a1Load:ocr.promise});await tick();
      ui.workers[0].result(adjacentTrace());
      ui.canvas().onpointerdown(pointer(40,50));ui.canvas().onpointerup(pointer(40,50));await tick();
      assert.equal(ui.controls.get('.trace-a1').value,'');
      assert.match(ui.controls.get('.trace-a1-status').textContent,/Odczytuję/);
      if(manual){ui.controls.get('.trace-a1').value='178a';ui.controls.get('.trace-a1').oninput();}
      ocr.resolve(result);await tick();
      assert.equal(ui.controls.get('.trace-a1').value,manual?'178a':'178');
      assert.equal(ui.a1Requests.length,1,'OCR runs once per raster, not once per click');
      ui.api.close();
    }
    const ocr=deferred(),ui=createUI([Promise.resolve([])],{a1Load:ocr.promise});await tick();ui.workers[0].result(adjacentTrace());
    for(const x of [40,40,80]){ui.canvas().onpointerdown(pointer(x,50));ui.canvas().onpointerup(pointer(x,50));await tick();}
    ocr.resolve(result);await tick();
    assert.equal(ui.controls.get('.trace-a1').value,'175','A late sheet result is assigned to the currently selected field');
    ui.api.close();
  },

  async cached_a1_is_available_on_first_click_and_late_closed_result_is_ignored() {
    const result={width:160,height:120,annotations:[{text:'178',status:'ok',anchor:[50,50],hasLeader:false}]};
    const ui=createUI([Promise.resolve([])],{a1Load:Promise.resolve(result)});await tick();ui.workers[0].result();
    ui.canvas().onpointerdown(pointer(50,50));ui.canvas().onpointerup(pointer(50,50));
    assert.equal(ui.controls.get('.trace-a1').value,'178','Cached recognition fills A1 in the first-click handler');
    ui.api.close();
    const deferredOCR=deferred(),closed=createUI([Promise.resolve([])],{a1Load:deferredOCR.promise});await tick();
    closed.api.close();const draws=closed.draws.count,description=closed.controls.get('.trace-a1-status').textContent;
    assert.equal(closed.a1Requests[0].aborted,true);
    deferredOCR.resolve(result);await tick();
    assert.equal(closed.draws.count,draws);assert.equal(closed.controls.get('.trace-a1-status').textContent,description);
  },

  async unavailable_a1_keeps_manual_drawing_usable() {
    const ocr=deferred(),ui=createUI([Promise.resolve([])],{a1Load:ocr.promise});await tick();ui.workers[0].result();
    ui.canvas().onpointerdown(pointer(50,50));ui.canvas().onpointerup(pointer(50,50));await tick();
    ocr.reject(new Error('Local OCR failed'));await tick();
    assert.match(ui.controls.get('.trace-a1-status').textContent,/niedostępny/);
    ui.controls.get('.trace-a1').value='17';ui.controls.get('.trace-a1').oninput();
    assert.equal(ui.controls.get('.trace-save').disabled,false);await ui.api.submit();
    assert.equal(ui.addCalls[0].a1,'17');assert.equal(ui.a1Requests.length,1);
    ui.api.close();
  },

  async a1_api_uses_document_tokens_and_only_restores_an_explicit_cache_miss() {
    const digest='a'.repeat(64),result={digest,width:160,height:120,annotations:[]};
    const response=(status,body,headers={})=>({status,ok:status===200,json:async()=>body,
      headers:{get:key=>headers[key]},arrayBuffer:async()=>new ArrayBuffer(0)});
    const map=mapTracingView([], [response(404,{code:'raster_preview_missing'}),
      response(200,null,{'X-Raster-Digest':digest}),response(200,result)]);
    const controller=new AbortController();
    assert.equal(await map.view.recognizeA1(controller.signal),result);
    assert.deepEqual(map.fetchRequests.map(r=>r.url),['/api/underlay/raster/a1','/api/underlay/raster/prepare','/api/underlay/raster/a1']);
    for(const {options} of map.fetchRequests){
      assert.equal(options.headers['X-GeoStudio-Token'],'test-api-token');
      assert.equal(options.headers['X-Map-Token'],'fixture-map');assert.equal(options.signal,controller.signal);
    }
    assert.equal(map.fetchRequests[1].options.body,map.entry.file,'Reuse the original local File, not a newly encoded raster');
    assert.equal(JSON.parse(map.fetchRequests[0].options.body).digest,digest);
    for(const status of [404,503]){
      const failed=mapTracingView([], [response(status,{detail:'Unavailable'})]);
      await assert.rejects(failed.view.recognizeA1(controller.signal),/Unavailable/);
      assert.equal(failed.fetchRequests.length,1,'Never retry missing documents or failed OCR as if they were an evicted preview');
    }
    const wrong=mapTracingView([], [response(200,{...result,digest:'b'.repeat(64)})]);
    await assert.rejects(wrong.view.recognizeA1(controller.signal),/innego rastra/);
  },

  async neighbour_fitted_manual_corner_and_node_survive_merging() {
    for(const parcels of [false,true])for(const inserted of [false,true]){
      const fitted=[[20,15],[20,60],[100,60],[100,15]];
      if(inserted)fitted.push([60,15]);
      const ui=createUI([Promise.resolve(parcels?[rectangle5216(20,20,100,100)]:[])],
        {fitLoads:[{points:fitted,clipped:false,snapped:true}]});
      await tick();const trace=adjacentTrace();trace.strokeMetrics={radiusPixels:8};ui.workers[0].result(trace);
      await ui.click(40,50);
      const from=inserted?[15,60]:[15,20],to=inserted?[12,62]:[10,18];
      ui.canvas().onpointerdown(pointer(...from));
      ui.canvas().onpointermove(pointer(...to,{altKey:true}));
      ui.canvas().onpointerup(pointer(...to,{altKey:true}));await tick();
      assert.ok(ui.fitCalls.at(-1).some(([north,east])=>north===to[1]&&east===to[0]));
      await ui.click(80,50);
      assert.ok(ui.fitCalls.at(-1).some(([north,east])=>north===to[1]&&east===to[0]),
        'Manual correction of a5310-fitted vertex must survive addition of a neighbour');
      assert.equal(ui.fitOptions.at(-1).snapDistance,8,'Newly added parts still fit their existing neighbours');
      assert.ok(ui.fitOptions.at(-1).lockedPoints.some(([north,east])=>north===to[1]&&east===to[0]),
        'Inherited manual corrections are explicit locks during the combined fit');
      ui.controls.get('.trace-parcel-snap').checked=false;ui.controls.get('.trace-parcel-snap').onchange();await tick();
      assert.equal(ui.fitOptions.at(-1).snapDistance,0,'An accepted manual draft is stable under settings changes');
      await ui.api.submit();
      assert.ok(ui.addCalls[0].points.some(([north,east])=>north===to[1]&&east===to[0]));
      ui.api.close();
    }
  },

  async neighbour_bridge_origins_do_not_replace_manual_corners_on_next_union() {
    // Both manually moved endpoints stay as vertices. The backend adds a
    // short bridge to each one so that the middle follows the real 5310.
    // Those new endpoints project onto the same original corner identities;
    // they must not overwrite the edits merely because they occur later.
    const withBridges = [[20,22],[20,100],[100,100],[100,22],[100,20],[20,20]];
    const ui = createUI([Promise.resolve([rectangle5216(20,20,140,100)])], {
      fitLoads: [undefined, undefined, undefined,
        {points:withBridges,clipped:false,snapped:true}],
    });
    await tick();
    const trace = adjacentTrace();
    for(let y=20;y<100;y++)for(let x=100;x<140;x++)trace.labels[y*160+x]=3;
    trace.shapes.set(3,{points:[[100,20],[140,20],[140,100],[100,100]],
      bounds:[100,20,140,100],suggested:true});
    ui.workers[0].result(trace);
    await ui.click(40,50);
    for(const y of [20,100]){
      ui.canvas().onpointerdown(pointer(20,y));
      ui.canvas().onpointermove(pointer(22,y,{altKey:true}));
      ui.canvas().onpointerup(pointer(22,y,{altKey:true}));
      await tick();
    }
    await ui.click(80,50);
    assert.equal(ui.fitCalls.length,4);
    assert.equal(ui.fitOptions.at(-1).lockedPoints.length,2);
    sameRing(ui.draws.rings[0],withBridges.map(([north,east])=>[east,north]));
    await ui.click(120,50);
    const combined = ui.fitCalls.at(-1),locks=ui.fitOptions.at(-1).lockedPoints;
    for(const point of [[20,22],[100,22]]){
      assert.ok(combined.some(p=>p[0]===point[0]&&p[1]===point[1]),
        'A newly inserted reference bridge must not replace a manual endpoint in the next union');
      assert.ok(locks.some(p=>p[0]===point[0]&&p[1]===point[1]),
        'Both original manual endpoints remain protected during the next fit');
    }
    await ui.api.submit();
    for(const point of [[20,22],[100,22]])assert.ok(ui.addCalls[0].points.some(p=>
      p[0]===point[0]&&p[1]===point[1]),'The final saved outline preserves both manual corrections');
    ui.api.close();
  },

  async rejected_hidden_vertices_cannot_be_dragged_back_into_a_proposal() {
    const failure=deferred(),ui=createUI([Promise.resolve([])],{fitLoads:[failure.promise]});
    await tick();ui.workers[0].result();
    ui.canvas().onpointerdown(pointer(50,50));ui.canvas().onpointerup(pointer(50,50));
    failure.reject(new Error('Zajęty obszar.'));await tick();
    assert.equal(ui.draws.rings.length,0);
    // Shift suppresses a replacement region selection and isolates the hidden
    // node hit-test, which used to start a drag despite the rejected preview.
    ui.canvas().onpointerdown(pointer(20,20,{shiftKey:true}));
    ui.canvas().onpointermove(pointer(23,23,{shiftKey:true}));
    ui.canvas().onpointerup(pointer(23,23,{shiftKey:true}));await tick();
    assert.equal(ui.fitCalls.length,1);
    assert.equal(ui.draws.rings.length,0);
    ui.canvas().onpointerdown(pointer(50,20,{button:2}));
    ui.canvas().onpointerup(pointer(50,20,{button:2}));await tick();
    assert.equal(ui.fitCalls.length,1,'Invisible rejected sides cannot accept inserted vertices');
    ui.api.close();
  },

  async first_useful_stroke_measurement_initializes_the_range() {
    const ui=createUI([Promise.resolve([])]);await tick();ui.workers[0].result();
    assert.equal(Number(ui.controls.get('.trace-parcel-distance').value),3);
    ui.controls.get('select').onchange();
    const trace=sampleTrace();trace.strokeMetrics={radiusPixels:8};ui.workers[0].result(trace);
    assert.equal(Number(ui.controls.get('.trace-parcel-distance').value),8);
    ui.controls.get('select').onchange();trace.strokeMetrics.radiusPixels=14;ui.workers[0].result(trace);
    assert.equal(Number(ui.controls.get('.trace-parcel-distance').value),8);
    ui.api.close();
  },

  async forest_reference_classes_do_not_occupy_the_trace_mask() {
    const rings=code=>({code,closed:true,layer:'Użytki Leśne',
      geometry:[[[20,-20],[100,-20],[100,-100],[20,-100],[20,-20]]]});
    const ui=createUI([Promise.resolve([rings('5220'),rings('5230'),rings('5216')])]);
    await tick();
    assert.equal(ui.imageCaptures[1].length,0,'Forest/parcel reference areas must remain drawable');
    ui.workers[0].result();await ui.click();
    assert.equal(ui.fitCalls.length,1);
    ui.api.close();
    const existing={...rings('5310'),visible:false,geometry:[],nativeGeometry:rings('5310').geometry};
    const blocked=createUI([Promise.resolve([rings('5220'),existing])]);await tick();
    assert.equal(blocked.imageCaptures[1].length,1,'Only full native5310 geometry is painted, even when hidden');
    sameRing(blocked.imageCaptures[1][0],[[20,20],[100,20],[100,100],[20,100],[20,20]]);
    blocked.api.close();
  },

  async first_click_fills_a1_and_preserves_manual_corrections() {
    const ui=createUI([Promise.resolve([])]);await tick();
    const trace=adjacentTrace();
    trace.a1Suggestions=new Map([[1,{text:'178',confidence:.99,source:'callout',status:'ok'}],
      [2,{text:'178',confidence:.99,source:'inside',status:'ok'}]]);
    ui.workers[0].result(trace);
    ui.canvas().onpointerdown(pointer(40,50));ui.canvas().onpointerup(pointer(40,50));await tick();
    assert.equal(ui.controls.get('.trace-a1').value,'178','The first proposal must already have the recognized A1');
    assert.equal(ui.controls.get('.trace-save').disabled,false);
    assert.match(ui.controls.get('.trace-a1-status').textContent,/A1 z rastra: 178/);
    ui.controls.get('.trace-a1').value='178a';ui.controls.get('.trace-a1').oninput();
    ui.controls.get('.trace-parcel-snap').checked=false;ui.controls.get('.trace-parcel-snap').onchange();await tick();
    assert.equal(ui.controls.get('.trace-a1').value,'178a');
    ui.canvas().onpointerdown(pointer(80,50));ui.canvas().onpointerup(pointer(80,50));await tick();
    assert.equal(ui.controls.get('.trace-a1').value,'178a','Adding a fragment must not replace a manual A1');
    await ui.api.submit();assert.equal(ui.addCalls[0].a1,'178a');
    assert.equal(ui.controls.get('.trace-a1').value,'','Saved number must not leak to the next field');
    ui.api.close();
  },

  async uncertain_or_conflicting_a1_is_not_guessed() {
    for(const status of ['uncertain','conflict']){
      const ui=createUI([Promise.resolve([])]);await tick();
      const trace=sampleTrace();trace.a1Suggestions=new Map([[1,{text:'18',confidence:.99,source:'callout',status}]]);
      ui.workers[0].result(trace);
      ui.canvas().onpointerdown(pointer(50,50));ui.canvas().onpointerup(pointer(50,50));await tick();
      assert.equal(ui.controls.get('.trace-a1').value,'');
      assert.equal(ui.controls.get('.trace-save').disabled,true);ui.api.close();
    }
    const ui=createUI([Promise.resolve([])]);await tick();
    const trace=adjacentTrace();trace.a1Suggestions=new Map([[1,{text:'17',status:'ok'}],[2,{text:'18',status:'ok'}]]);
    ui.workers[0].result(trace);
    ui.canvas().onpointerdown(pointer(40,50));ui.canvas().onpointerup(pointer(40,50));await tick();
    assert.equal(ui.controls.get('.trace-a1').value,'17');
    ui.canvas().onpointerdown(pointer(80,50));ui.canvas().onpointerup(pointer(80,50));await tick();
    assert.equal(ui.controls.get('.trace-a1').value,'','Two different raster numbers require an explicit choice');
    assert.match(ui.controls.get('.trace-a1-status').textContent,/różne lub niejednoznaczne/);
    ui.api.close();
  },

  async stroke_width_sets_initial_range_once_and_respects_manual_override() {
    const ui=createUI([Promise.resolve([]),Promise.resolve([])]);await tick();
    const trace=sampleTrace();trace.strokeMetrics={radiusPixels:8.2,samples:20,edges:4};ui.workers[0].result(trace);
    assert.equal(Number(ui.controls.get('.trace-parcel-distance').value),8.2);
    ui.controls.get('.trace-quality').value='6000000';ui.controls.get('.trace-quality').onchange();await tick();
    const other=sampleTrace();other.strokeMetrics={radiusPixels:14,samples:20,edges:4};ui.workers[1].result(other);
    assert.equal(Number(ui.controls.get('.trace-parcel-distance').value),8.2,'Quality changes must preserve the chosen metre range');
    ui.api.close();
    const manual=createUI([Promise.resolve([])]);await tick();
    manual.controls.get('.trace-parcel-distance').value='1.5';manual.controls.get('.trace-parcel-distance').onchange();
    manual.workers[0].result(trace);
    assert.equal(Number(manual.controls.get('.trace-parcel-distance').value),1.5,'Early manual range is never replaced by an analyser');
    manual.api.close();
  },

  async occupied_click_is_blocked_using_hidden_full_geometry() {
    const full=[[[20,-20],[60,-20],[60,-100],[20,-100],[20,-20]]];
    const ui=createUI([Promise.resolve([{code:'5310',closed:true,geometry:[],nativeGeometry:full,visible:false}])]);
    await tick();ui.workers[0].result();
    ui.canvas().onpointerdown(pointer(50,50));ui.canvas().onpointerup(pointer(50,50));
    await tick();
    assert.equal(ui.fitCalls.length,0,'Do not even request a proposal for an occupied click');
    assert.equal(ui.draws.rings.length,0,'No red outline may appear over an existing5310');
    assert.match(ui.status(),/zajmuje już poligon 5310/);
    assert.equal(ui.controls.get('.trace-save').disabled,true);
    ui.canvas().onpointerdown(pointer(80,50));ui.canvas().onpointerup(pointer(80,50));
    await tick();
    assert.equal(ui.fitCalls.length,1,'A free neighbouring click still works');
    assert.deepEqual(Array.from(ui.fitOptions[0].seedPoints[0]),[50,80]);
    assert.ok(ui.fitOptions[0].snapDistance>0);
    ui.api.close();
  },

  async failed_automatic_fit_hides_proposal_and_prevents_save() {
    const fit=deferred(),ui=createUI([Promise.resolve([])],{fitLoads:[fit.promise]});
    await tick();ui.workers[0].result();
    ui.canvas().onpointerdown(pointer(50,50));ui.canvas().onpointerup(pointer(50,50));
    fit.reject(new Error('Całe zaznaczenie zajmuje już istniejący 5310.'));
    await tick();
    ui.controls.get('.trace-a1').value='17';ui.controls.get('.trace-a1').oninput();
    assert.equal(ui.draws.rings.length,0,'A rejected ring is not offered as a red proposal');
    assert.equal(ui.controls.get('.trace-save').disabled,true);
    await ui.api.submit();assert.equal(ui.added(),0);
    ui.api.close();
  },

  async neighbour_fit_saves_exact_preview_and_manual_edit_is_not_resnapped() {
    const ui=createUI([Promise.resolve([])],{fitLoads:[{points:fittedNative,clipped:false,snapped:true}]});
    await tick();ui.workers[0].result();await ui.click();
    sameRing(ui.draws.rings[0],[[21,21],[101,21],[101,101],[21,101]]);
    assert.match(ui.status(),/Dopasowano do istniejących 5310/);
    ui.canvas().onpointerdown(pointer(21,21));
    ui.canvas().onpointermove(pointer(24,25,{altKey:true}));
    ui.canvas().onpointerup(pointer(24,25,{altKey:true}));await tick();
    assert.equal(ui.fitOptions.at(-1).snapDistance,0,'A deliberate manual correction is authoritative');
    assert.equal(ui.fitOptions.at(-1).seedPoints.length,0);
    await ui.api.submit();
    closePoints(ui.addCalls[0].points,ui.addCalls[0].fitted);
    assert.ok(ui.addCalls[0].points.some(([north,east])=>north===25&&east===24));
    ui.api.close();
  },

  async magnet_uses_native_vertices_and_prioritizes_nodes() {
    const native=[[[0,0],[40,-20],[100,-100]]],feature={code:'5216',closed:false,
      geometry:[[[0,0],[100,-100]]],nativeGeometry:native};
    const ui=createUI([Promise.resolve([feature])]);await tick();ui.workers[0].result();await ui.click();
    ui.controls.get('.trace-magnet').checked=true;
    ui.canvas().onpointerdown(pointer(20,20));ui.canvas().onpointermove(pointer(35,22));
    assert.deepEqual(ui.snapCalls.at(-1)[0].geometry,native,'Clipped display geometry must not hide reference nodes');
    assert.equal(ui.snapOptions.at(-1).preferVertices,true);
    assert.equal(ui.snapOptions.at(-1).vertexPixels,26);
    assert.equal(ui.snapOptions.at(-1).releasePixels,34);
    ui.canvas().onpointercancel();ui.api.close();
  },

  async close_during_prepare() {
    for (const fail of [false, true]) {
      const load = deferred(), ui = createUI([load.promise]);
      assert.equal(ui.api.close(), true);
      const before = ui.status(), draws = ui.draws.count;
      if (fail) load.reject(new Error('late fetch failure'));
      else load.resolve([]);
      await tick();
      assert.equal(ui.workers.length, 0, 'closing a pending preparation must not start a worker');
      assert.equal(ui.status(), before, 'late failures must not mutate a removed panel');
      assert.equal(ui.draws.count, draws);
      assert.equal(ui.closed(), 1);
      assert.equal(ui.panel().removed, true);
    }
  },

  async worker_replaced_after_save() {
    const reload = deferred(), ui = createUI([Promise.resolve([]), reload.promise]);
    await tick();
    const first = ui.workers[0];
    const lateMessage = first.onmessage, lateError = first.onerror;
    first.result();
    await ui.click();
    assert.equal(ui.controls.get('.trace-save').disabled, false);
    const saving = ui.api.submit();
    await tick();
    assert.equal(ui.controls.get('.trace-quality').disabled, true);
    assert.equal(ui.controls.get('.trace-tolerance').disabled, true);
    assert.equal(ui.controls.get('.trace-parcel-snap').disabled, true);
    assert.equal(ui.controls.get('.trace-parcel-distance').disabled, true);
    assert.equal(ui.added(), 1);
    assert.equal(first.terminated, true, 'release the old image buffers before waiting for refreshed MAP geometry');
    assert.equal(first.onmessage, null);
    assert.equal(first.onerror, null);
    const pending = ui.status();
    lateMessage({ data: { id: first.analysisID(), trace: sampleTrace() } });
    lateError();
    assert.equal(ui.status(), pending, 'a queued event from the previous worker must be ignored');
    reload.resolve([]);
    await saving;
    assert.equal(ui.controls.get('.trace-quality').disabled, false);
    assert.equal(ui.controls.get('.trace-tolerance').disabled, false);
    assert.equal(ui.controls.get('.trace-parcel-snap').disabled, false);
    assert.equal(ui.controls.get('.trace-parcel-distance').disabled, false);
    const second = ui.workers[1];
    second.result();
    await ui.click();
    const ready = ui.status();
    lateMessage({ data: { id: second.analysisID(), error: 'old worker spoofed current ID' } });
    lateError();
    assert.equal(ui.status(), ready);
    assert.equal(ui.controls.get('.trace-save').disabled, false);
    await ui.api.submit();
    assert.equal(ui.added(), 2);
    assert.equal(second.terminated, true);
    assert.equal(ui.workers.length, 3);
    assert.equal(ui.workers.filter(worker => !worker.terminated).length, 1);
    ui.api.close();
    assert.ok(ui.workers.every(worker => worker.terminated));
  },

  async latest_analysis_only() {
    const ui = createUI(); await tick();
    const worker = ui.workers[0], previousID = worker.analysisID();
    assert.equal(worker.messages.at(-1).tolerance, 2.5);
    ui.controls.get('select').value = '3';
    ui.controls.get('select').onchange();
    const intermediateID = worker.analysisID();
    ui.controls.get('.trace-tolerance').value = '1';
    ui.controls.get('.trace-tolerance').onchange();
    const currentID = worker.analysisID();
    assert.equal(worker.messages.at(-1).tolerance, 1);
    assert.notEqual(currentID, intermediateID);
    assert.notEqual(currentID, previousID);
    const pending = ui.status();
    worker.result(sampleTrace(), previousID);
    worker.result(sampleTrace(), intermediateID);
    assert.equal(ui.status(), pending);
    assert.ok(ui.controls.get('.trace-save').disabled);
    worker.result();
    await ui.click();
    const ready = ui.status();
    assert.equal(ui.controls.get('.trace-save').disabled, false);
    worker.onmessage({ data: { id: previousID, error: 'obsolete analysis' } });
    worker.onmessage({ data: { id: currentID, error: 'duplicate delivery' } });
    worker.onerror();
    assert.equal(ui.status(), ready, 'late or duplicate results must not replace the currently edited shape');
    assert.equal(ui.controls.get('.trace-a1').value, '17');
    assert.equal(ui.controls.get('.trace-save').disabled, false);
    ui.api.close();
  },

  async current_error_and_closed_callbacks() {
    const ui = createUI(); await tick();
    const worker = ui.workers[0], lateMessage = worker.onmessage, lateError = worker.onerror;
    worker.onerror();
    assert.match(ui.status(), /Nie udało się rozpoznać/);
    assert.ok(ui.controls.get('.trace-save').disabled);
    const failed = ui.status();
    worker.result();
    assert.equal(ui.status(), failed, 'a failed analysis cannot later publish a successful draft');
    ui.api.close();
    const draws = ui.draws.count;
    lateMessage({ data: { id: worker.analysisID(), trace: sampleTrace() } });
    lateError();
    assert.equal(ui.status(), failed);
    assert.equal(ui.draws.count, draws);
    assert.equal(worker.terminated, true);
  },

  async quality_prepare_race() {
    const initial = deferred(), faster = deferred(), precise = deferred();
    const ui = createUI([initial.promise, faster.promise, precise.promise], { width: 4000, height: 4000 });
    const quality = ui.controls.get('.trace-quality');
    quality.value = '6000000'; quality.onchange();
    quality.value = '12000000'; quality.onchange();
    precise.resolve([]); await tick();
    assert.equal(ui.workers.length, 1);
    const worker = ui.workers[0], sheet = worker.messages[0];
    assert.ok(sheet.w * sheet.h > 11000000 && sheet.w * sheet.h <= 12000000);
    worker.result();
    const ready = ui.status();
    initial.resolve([]); faster.reject(new Error('outdated MAP fetch failed'));
    await tick();
    assert.equal(ui.workers.length, 1, 'obsolete feature requests must not replace the current worker');
    assert.equal(ui.status(), ready);
    quality.value = '6000000'; quality.onchange();
    assert.equal(worker.terminated, true);
    await tick();
    const second = ui.workers[1], newSheet = second.messages[0];
    assert.ok(newSheet.w * newSheet.h > 5500000 && newSheet.w * newSheet.h <= 6000000);
    assert.equal(ui.workers.filter(value => !value.terminated).length, 1);
    ui.api.close();
  },

  async quality_preserves_native_geometry_and_completed_snap() {
    const ui = createUI([], { width: 4000, height: 4000, sourceWidth: 8000, sourceHeight: 6000, scale: .02 });
    await tick();
    ui.workers.at(-1).result(); await ui.click();
    const original = ui.fitCalls.at(-1).map(point => Array.from(point));
    closePoints(original, [[1000, 1000], [1000, 5000], [5000, 5000], [5000, 1000]]);
    const quality = ui.controls.get('.trace-quality');
    quality.value = '6000000'; quality.onchange();
    assert.equal(ui.controls.get('.trace-a1').value, '');
    assert.ok(ui.controls.get('.trace-save').disabled, 'old draft must disappear before the new raster grid is ready');
    await tick(); ui.workers.at(-1).result(); await ui.click();
    closePoints(ui.fitCalls.at(-1), original);
    await ui.api.submit();
    closePoints(ui.addCalls[0].points, original);
    quality.value = '12000000'; quality.onchange();
    await tick(); ui.workers.at(-1).result(); await ui.click();
    closePoints(ui.fitCalls.at(-1), original);
    // A saved polygon is also a snapping target. Its world coordinates must
    // survive both grid changes, not just the currently selected draft.
    ui.controls.get('.trace-magnet').checked = true;
    const event = { button: 0, clientX: 20, clientY: 20, pointerId: 1,
      preventDefault() {}, stopPropagation() {} };
    ui.canvas().onpointerdown(event);
    const moved = { ...event, clientX: 23, clientY: 23 };
    ui.canvas().onpointermove(moved);
    const target = ui.snapCalls.at(-1)[0].geometry[0];
    const expected = original.map(([north, east]) => [east, -north]); expected.push(expected[0]);
    closePoints(target, expected);
    ui.canvas().onpointerup(moved); await tick();
    ui.api.close();
  },

  async analysis_change_cancels_drag_and_fit() {
    const fitting = deferred(), ui = createUI([], { fitLoads: [fitting.promise] });
    await tick(); const worker = ui.workers[0];
    worker.result(); await ui.click();
    await ui.api.submit(); // Queued while the original shape is still fitting.
    ui.controls.get('.trace-tolerance').value = '1';
    ui.controls.get('.trace-tolerance').onchange();
    const pending = ui.status();
    fitting.resolve({ points: [[999, 999], [999, 1099], [1099, 1099]], clipped: true });
    await tick();
    assert.equal(ui.status(), pending, 'an old fitting response must not replace a newly analyzed draft');
    assert.equal(ui.added(), 0, 'an obsolete queued save must be cancelled');
    worker.result(); await ui.click();
    ui.controls.get('.trace-magnet').checked = true;
    const event = { button: 0, clientX: 20, clientY: 20, pointerId: 1,
      preventDefault() {}, stopPropagation() {} };
    ui.canvas().onpointerdown(event);
    assert.equal(ui.timers.size, 1);
    ui.controls.get('select').onchange();
    assert.equal(ui.timers.size, 0, 'a new analysis must cancel the hold-to-snap callback');
    ui.canvas().onpointerup(event);
    assert.equal(ui.added(), 0);
    worker.result(); await ui.click();
    ui.canvas().onpointerdown(event);
    assert.equal(ui.timers.size, 1);
    ui.api.close();
    assert.equal(ui.timers.size, 0, 'closing must release the pending hold callback and its draft');
  },

  async parcel_snap_uses_hidden_native_geometry_and_saves_preview() {
    const feature = rectangle5216();
    feature.nativeGeometry = feature.geometry;
    feature.geometry = rectangle5216(300, 300, 400, 400).geometry;
    const untouched = JSON.stringify(feature);
    const ui = createUI([Promise.resolve([feature])], { isVisible: () => false });
    await tick(); ui.workers[0].result(); await ui.click();
    assert.equal(ui.controls.get('.trace-parcel-snap').checked, true);
    sameRing(ui.fitCalls.at(-1), fittedNative);
    assert.equal(ui.featureCalls(), 1, 'Selection reuses the complete map geometry loaded for tracing');
    const preview = ui.fitCalls.at(-1).map(point => Array.from(point));
    await ui.api.submit();
    closePoints(ui.addCalls[0].points, preview);
    closePoints(ui.addCalls[0].fitted, preview);
    assert.equal(ui.addCalls[0].a1, '17');
    assert.equal(JSON.stringify(feature), untouched, 'Reference parcels must remain immutable');
    ui.api.close();
  },

  async parcel_controls_refit_without_reanalysis_or_losing_a1() {
    const ui = createUI([Promise.resolve([rectangle5216()])]);
    await tick(); const worker = ui.workers[0];
    worker.result(); await ui.click();
    sameRing(ui.fitCalls.at(-1), fittedNative);
    const count = worker.messages.length;
    const distance = ui.controls.get('.trace-parcel-distance');
    distance.value = '.25'; distance.onchange(); await tick();
    sameRing(ui.fitCalls.at(-1), originalNative);
    assert.equal(ui.controls.get('.trace-a1').value, '17');
    distance.value = '3'; distance.onchange(); await tick();
    sameRing(ui.fitCalls.at(-1), fittedNative);
    const enabled = ui.controls.get('.trace-parcel-snap');
    enabled.checked = false; enabled.onchange(); await tick();
    sameRing(ui.fitCalls.at(-1), originalNative);
    assert.equal(distance.disabled, false, 'Neighbour 5310 fitting still has an adjustable range when 5216 fitting is off');
    assert.equal(ui.fitOptions.at(-1).snapDistance, 3, 'Disabling 5216 must not disable adjoining 5310 fitting');
    enabled.checked = true; enabled.onchange(); await tick();
    sameRing(ui.fitCalls.at(-1), fittedNative);
    assert.equal(worker.messages.length, count, 'Changing the reference fit must not analyze the raster again');
    assert.equal(ui.workers.length, 1);
    assert.equal(ui.featureCalls(), 1, 'No additional feature fetch is needed for a tolerance change');
    assert.equal(ui.controls.get('.trace-a1').value, '17');
    assert.equal(ui.controls.get('.trace-save').disabled, false);
    ui.api.close();
  },

  async parcel_manual_correction_survives_settings_and_save() {
    const ui = createUI([Promise.resolve([rectangle5216()])]);
    await tick(); ui.workers[0].result(); await ui.click();
    sameRing(ui.fitCalls.at(-1), fittedNative);
    ui.canvas().onpointerdown(pointer(21, 21));
    ui.canvas().onpointermove(pointer(26, 25, { altKey: true }));
    ui.canvas().onpointerup(pointer(26, 25, { altKey: true }));
    await tick();
    const manual = ui.fitCalls.at(-1).map(point => Array.from(point));
    sameRing(manual, [[25, 26], ...fittedNative.slice(1)]);
    const enabled = ui.controls.get('.trace-parcel-snap');
    enabled.checked = false; enabled.onchange(); await tick();
    closePoints(ui.fitCalls.at(-1), manual);
    const distance = ui.controls.get('.trace-parcel-distance');
    distance.value = '10'; distance.onchange(); await tick();
    enabled.checked = true; enabled.onchange(); await tick();
    closePoints(ui.fitCalls.at(-1), manual);
    await ui.api.submit();
    closePoints(ui.addCalls[0].points, manual);
    closePoints(ui.addCalls[0].fitted, manual);
    ui.api.close();
  },

  async parcel_snap_handles_merged_fragments_and_retains_manual_corner() {
    for (const manual of [false, true]) {
      const ui = createUI([Promise.resolve([rectangle5216()])]);
      await tick(); ui.workers[0].result(adjacentTrace()); await ui.click(40, 50);
      sameRing(ui.fitCalls.at(-1), [[21, 21], [21, 60], [101, 60], [101, 21]]);
      if (manual) {
        ui.canvas().onpointerdown(pointer(21, 21));
        ui.canvas().onpointermove(pointer(26, 25, { altKey: true }));
        ui.canvas().onpointerup(pointer(26, 25, { altKey: true }));
        await tick();
      }
      await ui.click(80, 50); // Add the adjacent raster fragment to one 5310.
      const merged = ui.fitCalls.at(-1);
      if (!manual) sameRing(merged, fittedNative);
      else assert.ok(merged.some(([north, east]) => north === 25 && east === 26),
        'The edited snapped corner must remain attached to its original raster corner on merge');
      assert.ok(merged.every(([, east], i) => Math.abs(east - 60) > 1e-8 ||
        Math.abs(merged[(i + 1) % merged.length][1] - 60) > 1e-8),
      'The internal fragment divider must disappear; a genuine outer bend after manual editing may remain');
      assert.equal(ui.featureCalls(), 1);
      ui.api.close();
    }
  },

  async parcel_shared_boundary_veto_is_consistent_for_neighbors_and_union() {
    const feature = { code: '5216', closed: false, geometry: [[[32, -10], [32, -110]]] };
    const ui = createUI([Promise.resolve([feature])]);
    await tick(); const worker = ui.workers[0];
    worker.result(thinAndWideTrace());
    const analysisMessages = worker.messages.length;
    await ui.click(25, 50);
    const thin = ui.fitCalls.at(-1).map(point => Array.from(point));
    sameRing(thin, [[20, 20], [20, 30], [100, 30], [100, 20]]);
    await ui.click(25, 50); // Deselect the thin field before selecting its neighbor.
    await ui.click(80, 50);
    const wide = ui.fitCalls.at(-1).map(point => Array.from(point));
    sameRing(wide, [[20, 30], [20, 130], [100, 130], [100, 30]]);
    const shared = thin.filter(([north, east]) => wide.some(point => point[0] === north && point[1] === east));
    assert.equal(shared.length, 2, 'Both fields must keep exactly the same ends of the common side');
    await ui.click(25, 50); // Select both; the common side must cancel from the union.
    const merged = ui.fitCalls.at(-1);
    sameRing(merged, [[20, 20], [20, 130], [100, 130], [100, 20]]);
    assert.equal(ringArea(thin) + ringArea(wide), ringArea(merged),
      'Rejected fitting on one neighbor must not leave a gap or overlap in their combined area');
    assert.equal(ringArea(merged), 8800);
    assert.equal(ui.featureCalls(), 1);
    assert.equal(worker.messages.length, analysisMessages);
    ui.api.close();
  },

  async parcel_inserted_reference_node_edit_survives_merging() {
    const feature = { code: '5216', closed: true, geometry: [[
      [21, -25], [40, -25], [101, -25], [101, -101], [21, -101], [21, -25],
    ]] };
    const ui = createUI([Promise.resolve([feature])]);
    await tick(); ui.workers[0].result(adjacentTrace());
    const distance = ui.controls.get('.trace-parcel-distance');
    distance.value = '6'; distance.onchange(); await tick();
    await ui.click(40, 55);
    assert.ok(ui.fitCalls.at(-1).some(([north, east]) => north === 25 && east === 40),
      'The exact intermediate parcel node must be inserted on the fitted side');
    ui.canvas().onpointerdown(pointer(40, 25));
    ui.canvas().onpointermove(pointer(43, 29, { altKey: true }));
    ui.canvas().onpointerup(pointer(43, 29, { altKey: true }));
    await tick();
    assert.ok(ui.fitCalls.at(-1).some(([north, east]) => north === 29 && east === 43));
    await ui.click(80, 55);
    assert.ok(ui.fitCalls.at(-1).some(([north, east]) => north === 29 && east === 43),
      'An inserted reference node edited beyond the simplification tolerance must survive fragment merge');
    await ui.api.submit();
    assert.ok(ui.addCalls[0].points.some(([north, east]) => north === 29 && east === 43));
    ui.api.close();
  },

  async parcel_snap_preserves_calibrated_coordinates_across_quality_and_zoom() {
    // North/east source-pixel calibration has rotation, shear, nonuniform
    // source/preview resolution and a large map-coordinate origin.
    const affine = [.1, .5, 5800000, .4, -.08, 7500000];
    const sourceCorners = [[1000, 1000], [5000, 1000], [5000, 5000], [1000, 5000]];
    const native = sourceCorners.map(([x, y]) => [
      affine[0] * x + affine[1] * y + affine[2],
      affine[3] * x + affine[4] * y + affine[5],
    ]);
    const expected = native.map(([north, east]) => [north + .4, east + .6]);
    const geometry = expected.map(([north, east]) => [east, -north]);
    geometry.push(geometry[0]);
    const features = [{ code: '5216', closed: true, geometry: [geometry] }];
    for (const scale of [.02, .05]) {
      const ui = createUI([Promise.resolve(features), Promise.resolve(features), Promise.resolve(features)], {
        width: 4000, height: 4000, sourceWidth: 8000, sourceHeight: 6000, scale, affine,
        screenOrigin: [7500000, -5800000],
      });
      await tick(); ui.workers.at(-1).result();
      const distance = ui.controls.get('.trace-parcel-distance');
      const initialDistance = Number(distance.value);
      // A source position well inside the proposed region, transformed to
      // the test screen. Neither zoom level changes the source geometry.
      const east = affine[3] * 2500 + affine[4] * 2500 + affine[5];
      const north = affine[0] * 2500 + affine[1] * 2500 + affine[2];
      const click = () => ui.click((east - 7500000) * scale, (north - 5800000) * scale);
      await click();
      sameRing(ui.fitCalls.at(-1), expected);
      const quality = ui.controls.get('.trace-quality');
      quality.value = '6000000'; quality.onchange();
      await tick(); ui.workers.at(-1).result(); await click();
      sameRing(ui.fitCalls.at(-1), expected);
      assert.equal(Number(distance.value), initialDistance, 'Ground tolerance must not change with the analysis grid');
      quality.value = '12000000'; quality.onchange();
      await tick(); ui.workers.at(-1).result(); await click();
      sameRing(ui.fitCalls.at(-1), expected);
      assert.equal(Number(distance.value), initialDistance);
      ui.api.close();
    }
  },

  async parcel_option_change_invalidates_pending_fit_and_queued_save() {
    const oldFit = deferred();
    const ui = createUI([Promise.resolve([rectangle5216()])], { fitLoads: [oldFit.promise] });
    await tick(); ui.workers[0].result(); await ui.click();
    sameRing(ui.fitCalls[0], fittedNative);
    await ui.api.submit(); // Queue saving while the initial backend fit is pending.
    const enabled = ui.controls.get('.trace-parcel-snap');
    enabled.checked = false; enabled.onchange(); await tick();
    sameRing(ui.fitCalls.at(-1), originalNative);
    const status = ui.status();
    oldFit.resolve({ points: fittedNative, clipped: true });
    await tick();
    assert.equal(ui.status(), status, 'A stale response must not overwrite the new reference settings');
    assert.equal(ui.added(), 0, 'Changing the intended geometry cancels an obsolete queued save');
    assert.equal(ui.controls.get('.trace-a1').value, '17');
    await ui.api.submit();
    sameRing(ui.addCalls[0].points, originalNative);
    sameRing(ui.addCalls[0].fitted, originalNative);
    ui.api.close();
  },

  async parcel_reference_fetch_paginates_full_native_extent() {
    const first = Array.from({ length: 4000 }, (_, i) => ({ id: i + 1, code: '5216' }));
    const second = [{ id: 4001, code: '5310' }, { id: 4002, code: '5216' }];
    const map = mapTracingView([{ features: first, total: 4002 }, { features: second, total: 4002 }]);
    const bounds = [100, 200, 110, 220];
    const features = await map.view.featuresIn(bounds);
    assert.equal(features.length, 4002);
    assert.equal(features.at(-1).id, 4002, 'Parcel references from later pages must not be omitted');
    assert.equal(map.requests.length, 2);
    for (const [i, url] of map.requests.entries()) {
      assert.equal(url.pathname, '/api/viewport');
      assert.equal(url.searchParams.get('native'), '1');
      assert.equal(url.searchParams.get('limit'), '4000');
      assert.equal(url.searchParams.get('offset'), String(i * 4000));
      assert.deepEqual(['xmin', 'ymin', 'xmax', 'ymax'].map(key => Number(url.searchParams.get(key))),
        [80, 180, 130, 240], 'Load references within the maximum ground snap range outside the raster');
    }
    assert.deepEqual(bounds, [100, 200, 110, 220], 'Fetching references must not enlarge the raster itself');
    map.view.fit(bounds);
    assert.equal(map.state.center.x, 105);
    assert.equal(map.state.center.y, 210);
    assert.equal(map.state.scale, 36.8, 'Cały raster must fit the image extent without the fetch margin');
  },

  async parcel_reference_fetch_rejects_incomplete_pagination() {
    const map = mapTracingView([
      { features: [{ id: 1, code: '5216' }], total: 2 },
      { features: [], total: 2 },
    ]);
    await assert.rejects(map.view.featuresIn([100, 200, 110, 220]), /wszystkich granic mapy/);
    assert.equal(map.requests.length, 2);
    assert.equal(map.requests[1].searchParams.get('offset'), '1');
  },
};

(async () => {
  const selected = process.argv[2];
  if (!cases[selected]) throw Error('Unknown tracing lifecycle scenario: ' + selected);
  await cases[selected]();
  console.log(selected + ': OK');
})().catch(error => { console.error(error); process.exitCode = 1; });
