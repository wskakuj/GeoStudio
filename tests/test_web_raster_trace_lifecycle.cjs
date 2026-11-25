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
  const fitCalls = [], addCalls = [], snapCalls = [];
  const timers = new Map(); let timerID = 0, fitIndex = 0;
  const scale = options.scale || 1;
  const screenOrigin = options.screenOrigin || [0, 0];
  let panel, canvas, featureCalls = 0, closed = 0, added = 0;
  const context = new Proxy({
    clearRect() { draws.count++; },
    getImageData(x, y, width, height) {
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
    console, Worker, Uint8ClampedArray,
    setTimeout(callback) { const id = ++timerID; timers.set(id, callback); return id; },
    clearTimeout(id) { timers.delete(id); },
    window: { devicePixelRatio: 1, GeoStudioDrawingSnap: {
      snapPoint(world, targets) { snapCalls.push(targets); return { point: world, kind: null }; },
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
  vm.runInContext(source, sandbox, { filename: 'raster_trace.js' });
  const view = {
    shell: { clientWidth: 160, clientHeight: 120, append(overlay) { canvas = overlay; } },
    token: 'test-document',
    worldToScreen: (x, y) => ({ x: (x - screenOrigin[0]) * scale, y: -(y - screenOrigin[1]) * scale }),
    screenToWorld: (x, y) => ({ x: x / scale + screenOrigin[0], y: -y / scale + screenOrigin[1] }),
    scale: () => scale, magnetEnabled: () => false, isVisible: options.isVisible || (() => true),
    featuresIn() { return featureLoads[featureCalls++] || Promise.resolve([]); },
    fitOutline: async points => {
      fitCalls.push(points);
      return options.fitLoads?.[fitIndex++] || { points, clipped: false };
    },
    async add(points, a1, fitted) { added++; addCalls.push({ points, a1, fitted }); }, async refresh() {},
    closed() { closed++; },
  };
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
    api, workers, controls, draws, click, fitCalls, addCalls, snapCalls, timers,
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

function mapTracingView(batches) {
  const text = fs.readFileSync(path.join(__dirname, '../geostudio/web_app/static/map.js'), 'utf8');
  const start = text.indexOf('function startRasterTracing(){');
  const stop = text.indexOf('function renderRasterLayers(){', start);
  assert.ok(start >= 0 && stop > start, 'The map integration entry point must be present');
  const requests = [];
  const state = { editBusy: false, edit: { documentToken: 'fixture-map', revision: 7 },
    width: 1000, height: 800, center: { x: 0, y: 0 }, scale: 1 };
  const control = { value: '1', classList: { add() {}, remove() {} }, setAttribute() {} };
  let view;
  const sandbox = {
    URLSearchParams, state, activeTrace: null, shell: {}, raster: { layers: [] },
    $: () => control, rasterEntry: () => ({ id: 1 }), rasterCanShow: () => true,
    setTool() {}, worldToScreen() {}, screenToWorld() {}, zoomAt() {},
    requestDraw() {}, scheduleViewport() {}, toggleDrawMagnet() {}, isVisible: () => false,
    api: async url => { requests.push(new URL(url, 'http://fixture.local')); return batches[requests.length - 1]; },
    openRasterTracing(_entry, callbacks) { view = callbacks; return {}; },
  };
  vm.createContext(sandbox);
  vm.runInContext(text.slice(start, stop), sandbox, { filename: 'map.js:startRasterTracing' });
  sandbox.startRasterTracing();
  return { view, requests, state };
}

const cases = {
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
