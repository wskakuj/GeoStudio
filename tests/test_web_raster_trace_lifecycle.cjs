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
  vm.runInContext(source, sandbox, { filename: 'raster_trace.js' });
  const view = {
    shell: { clientWidth: 160, clientHeight: 120, append(overlay) { canvas = overlay; } },
    token: 'test-document',
    worldToScreen: (x, y) => ({ x: x * scale, y: -y * scale }),
    screenToWorld: (x, y) => ({ x: x / scale, y: -y / scale }),
    scale: () => scale, magnetEnabled: () => false, isVisible: () => true,
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
    affine: [0, 1, 0, 1, 0, 0],
  }, view);
  const click = async () => {
    const event = { button: 0, clientX: 50, clientY: 50, pointerId: 1, preventDefault() {} };
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
};

(async () => {
  const selected = process.argv[2];
  if (!cases[selected]) throw Error('Unknown tracing lifecycle scenario: ' + selected);
  await cases[selected]();
  console.log(selected + ': OK');
})().catch(error => { console.error(error); process.exitCode = 1; });
