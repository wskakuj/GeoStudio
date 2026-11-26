// Exercise the actual batch tracing UI and map callbacks, using the same
// deterministic DOM/Worker boundary as the single-field lifecycle tests.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm');
const { executeParcelWorker } = require('./test_web_raster_parcel_worker.cjs');
const {
  createUI, sampleTrace, adjacentTrace, rectangle5216, pointer, tick, deferred, mapTracingView,
} = require('./test_web_raster_trace_lifecycle.cjs');

const plain = value => JSON.parse(JSON.stringify(value));
const button = (ui, name) => ui.controls.get('.trace-batch-' + name);
const rows = ui => button(ui, 'list').children.map(row => ({
  row, check: row.children[0], locate: row.children[1], input: row.children[2], state: row.children[3],
}));
function numbered(trace = adjacentTrace(), numbers = ['17', '18']) {
  trace.a1Suggestions = new Map([...trace.shapes.keys()].map((id, index) => [id,
    { text: numbers[index], status: 'ok', assignmentStatus: 'ok' }]));
  return trace;
}
function sixFields(){
  const labels=new Int32Array(160*120),shapes=new Map();
  for(let id=1;id<=6;id++){
    const left=10+(id-1)*23,right=left+23;
    for(let y=20;y<100;y++)for(let x=left;x<right;x++)labels[y*160+x]=id;
    shapes.set(id,{points:[[left,20],[right,20],[right,100],[left,100]],
      bounds:[left,20,right,100],suggested:true});
  }
  return numbered({labels,shapes,tolerance:2.5},['17','18','','','19','20']);
}
function recognized() {
  return { width: 160, height: 120, annotations: [
    { text: '17', status: 'ok', confidence: .99, anchor: [40, 50], source: 'inside', hasLeader: false },
    { text: '18', status: 'ok', confidence: .99, anchor: [80, 50], source: 'inside', hasLeader: false },
  ] };
}
function report(items, patch = {}) {
  return { items: items.map(item => ({ ...item, status: item.a1 ? 'ready' : 'needsA1',
    clipped: false, snapped: false, reason: '', ...patch })) };
}
async function start(ui, trace = numbered()) {
  await tick();
  button(ui, 'start').onclick();
  await tick();
  const worker = ui.workers.find(item => !item.terminated);
  worker.result(trace);
  await tick();
  return worker;
}
function setNumber(row, value) {
  row.input.value = value;
  row.input.oninput();
}
function selectedItems() {
  return [{ id: 1, points: [[20, 20], [20, 60], [100, 60], [100, 20]], a1: '17' },
    { id: 2, points: [[20, 60], [20, 100], [100, 100], [100, 60]], a1: '18' }];
}
function approved(items = selectedItems()) {
  return { canApply: true, previewKey: 'reviewed-batch', ...report(items) };
}
function approvedWithoutA1(items){
  const preview=approved(items);preview.withoutA1=true;
  for(const item of preview.items)item.status='ready';
  return preview;
}
const saved = { documentToken: 'fixture-map', revision: 8, changed: true, createdCount: 2 };
function label(hints) {
  const context = {};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../geostudio/web_app/static/raster_trace_batch.js'), 'utf8'), context);
  return context.GeoStudioRasterTraceBatch.label(hints);
}
function printedParcelFixture() {
  // Synthetic scan: two tinted forestry fields, a real thin red divider,
  // two thin printed parcel lines and one-pixel printed digit counters.
  const width=360,height=200,pixels=new Uint8ClampedArray(width*height*4);
  pixels.fill(255);
  const put=(x,y,color)=>pixels.set([...color,255],4*(y*width+x));
  for(let y=20;y<=180;y++)for(let x=20;x<=340;x++)put(x,y,[210,230,180]);
  const black=[25,25,25];
  function stroke(a,b,color,radius=0){
    const steps=Math.max(Math.abs(b[0]-a[0]),Math.abs(b[1]-a[1]));
    for(let i=0;i<=steps;i++)for(let dy=-radius;dy<=radius;dy++)for(let dx=-radius;dx<=radius;dx++)
      put(Math.round(a[0]+(b[0]-a[0])*i/steps)+dx,Math.round(a[1]+(b[1]-a[1])*i/steps)+dy,color);
  }
  for(const [a,b] of [[[20,20],[340,20]],[[340,20],[340,180]],[[340,180],[20,180]],[[20,180],[20,20]]])
    stroke(a,b,black,1);
  stroke([180,20],[180,180],[175,30,35]);
  for(const x of [100,260])stroke([x,20],[x,180],black);
  for(const [x,y] of [[60,70],[220,90]])for(const [a,b] of [
    [[x,y],[x+8,y]],[[x+8,y],[x+8,y+14]],[[x+8,y+14],[x,y+14]],[[x,y+14],[x,y]],
  ])stroke(a,b,black);
  const context={};vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../geostudio/web_app/static/raster_trace.js'),'utf8'),context);
  return {width,height,analyze:settings=>context.traceLandUses(pixels,
    new Uint8ClampedArray(pixels.length),width,height,settings.threshold,settings.tolerance)};
}

const cases = {
  async one_click_prepares_all_fields_and_uses_the_batch_callback() {
    const ui = createUI();
    ui.controls.get('select').value = '7';
    ui.controls.get('.trace-tolerance').value = '4';
    await start(ui);
    assert.equal(ui.controls.get('.trace-quality').value, '14000000');
    assert.equal(ui.workers[1].messages.at(-1).threshold, 7,
      'whole-map analysis must retain the chosen contour width');
    assert.equal(ui.workers[1].messages.at(-1).tolerance, 4,
      'whole-map analysis must retain the chosen straightening tolerance');
    assert.equal(ui.workers.length, 2);
    assert.equal(ui.workers[0].terminated, true, 'the prior analysis worker must release its image buffers');
    assert.equal(ui.batchFitCalls.length, 1);
    assert.equal(ui.fitCalls.length, 0, 'whole-map analysis must not simulate individual user clicks');
    assert.deepEqual(plain(ui.batchFitCalls[0].map(item => item.id)), [1, 2]);
    assert.deepEqual(plain(ui.batchFitCalls[0].map(item => item.a1)), ['17', '18']);
    assert.ok(ui.batchFitCalls[0].every(item => item.seedPoints.length === 1));
    assert.equal(rows(ui).length, 2);
    assert.ok(rows(ui).every(row => row.check.checked));
    assert.equal(button(ui, 'save').disabled, false);
    assert.equal(ui.controls.get('.trace-save').disabled, true);
    assert.match(button(ui, 'summary').textContent, /pewne A1: 2/);
    ui.api.close();
  },

  async whole_map_defaults_ignore_thin_print_but_preserve_red_dividers_and_explicit_choices() {
    const fixture=printedParcelFixture(),ui=createUI([],{width:fixture.width,height:fixture.height});
    await tick();
    async function analyze(){
      button(ui,'start').onclick();await tick();
      const worker=ui.workers.find(item=>!item.terminated),settings=worker.messages.at(-1);
      const trace=fixture.analyze(settings);worker.result(trace);await tick();
      return {settings,trace};
    }
    const initial=await analyze();
    assert.equal(initial.settings.threshold,0);
    assert.equal(initial.settings.tolerance,2.5);
    assert.equal(rows(ui).length,2,
      'default whole-map tracing must ignore thin printed parcel lines and digits');
    assert.ok([...initial.trace.shapes.values()].every(shape=>
      shape.points.every(([x])=>x<=181)||shape.points.every(([x])=>x>=179)),
    'a real thin red boundary still separates the two forestry fields');
    ui.controls.get('select').value='5';
    const thick=await analyze();
    assert.equal(thick.settings.threshold,5);
    assert.equal(rows(ui).length,2,'explicit thick-contour mode must remain available');
    ui.controls.get('select').value='3';ui.controls.get('.trace-tolerance').value='4';
    const thin=await analyze();
    assert.equal(thin.settings.threshold,3);
    assert.equal(thin.settings.tolerance,4);
    assert.equal(rows(ui).length,4,'explicit thin-contour mode must remain available');
    ui.controls.get('select').value='7';ui.controls.get('.trace-tolerance').value='1';
    const coarse=await analyze();
    assert.equal(coarse.settings.threshold,7);
    assert.equal(coarse.settings.tolerance,1);
    assert.equal(rows(ui).length,2,'repeated whole-map analysis must retain both changed controls');
    ui.controls.get('select').value='0';
    const automatic=await analyze();
    assert.equal(automatic.settings.threshold,0);
    assert.equal(automatic.settings.tolerance,1);
    assert.equal(rows(ui).length,2,'returning to automatic contours must not split a known field by thin print');
    ui.api.close();
  },

  reliable_competing_uncertain_number_requires_review() {
    const result = label([{ text: '175', status: 'ok', assignmentStatus: 'ok' },
      { text: '176', status: 'uncertain', assignmentStatus: 'ok' }]);
    assert.equal(result.text, '175');
    assert.equal(result.status, 'uncertain');
  },
  unreliable_competing_assignment_does_not_replace_a_confirmed_number() {
    const result = label([{ text: '175', status: 'ok', assignmentStatus: 'ok' },
      { text: '176', status: 'uncertain', assignmentStatus: 'uncertain' }]);
    assert.equal(result.text, '175');
    assert.equal(result.status, 'ok');
  },
  matching_uncertain_number_does_not_erase_independent_confirmation() {
    const result = label([{ text: '175', status: 'ok', assignmentStatus: 'ok' },
      { text: '175', status: 'uncertain', assignmentStatus: 'ok' }]);
    assert.equal(result.text, '175');
    assert.equal(result.status, 'ok');
  },
  two_different_confirmed_numbers_require_explicit_conflict_resolution() {
    const result = label([{ text: '175', status: 'ok', assignmentStatus: 'ok' },
      { text: '176', status: 'ok', assignmentStatus: 'ok' }]);
    assert.equal(result.text, '');
    assert.equal(result.status, 'conflict');
    assert.deepEqual(plain(result.alternatives), ['175','176']);
  },

  variant_choices_are_bounded_numeric_values_without_automatic_assignment() {
    const result=label([{text:'175',status:'uncertain',assignmentStatus:'uncertain',
      alternatives:[null,{text:'<script>'},{text:'175'},{text:'123456789'},
        ...Array.from({length:20},(_,i)=>({text:String(i)}))]}]);
    assert.equal(result.text,'');
    assert.equal(result.status,'uncertain');
    assert.deepEqual(plain(result.alternatives),['175','0','1','2','3','4','5','6']);
  },

  async several_numbers_in_one_field_warn_about_the_missing_boundary() {
    for (const batch of [false, true]) {
      const trace = numbered();
      trace.a1Suggestions.set(1, { text: '175', status: 'uncertain', assignmentStatus: 'ok',
        reason: 'multiple_field_numbers', alternatives: [{ text: '175' }, { text: '176' }] });
      const ui = createUI();
      if (batch) {
        await start(ui, trace);
        assert.equal(rows(ui)[0].check.checked, false);
        assert.match(rows(ui)[0].state.textContent, /różne numery.*brakującą granicę/);
        setNumber(rows(ui)[0], '175a');
        assert.match(rows(ui)[0].state.textContent, /brakującą granicę/,
          'changing the number alone cannot remove a known geometry warning');
      } else {
        await tick();
        ui.workers[0].result(trace);
        ui.canvas().onpointerdown(pointer(40, 50));
        ui.canvas().onpointerup(pointer(40, 50));
        await tick();
        assert.equal(ui.controls.get('.trace-a1').value, '175');
        assert.match(ui.controls.get('.trace-a1-status').textContent, /A1 do sprawdzenia.*brakującą granicę/);
      }
      ui.api.close();
    }
  },

  async full_image_budget_preserves_original_calibrated_coordinates() {
    const ui = createUI([], { width: 4000, height: 3500, sourceWidth: 8000, sourceHeight: 7000 });
    await tick();
    const initial = ui.workers[0].messages[0];
    assert.ok(initial.w * initial.h <= 12000000);
    const trace = numbered(sampleTrace(4000, 3500), ['27']);
    await start(ui, trace);
    const complete = ui.workers[1].messages[0];
    assert.equal(complete.w, 4000);
    assert.equal(complete.h, 3500);
    assert.equal(complete.w * complete.h, 14000000);
    assert.deepEqual(plain(ui.batchFitCalls[0][0].points), trace.shapes.get(1).points.map(([x, y]) => [y * 2, x * 2]));
    ui.api.close();
  },

  async batch_waits_for_ocr_and_assigns_late_labels_to_the_current_analysis() {
    const ocr = deferred(), ui = createUI([], { a1Load: ocr.promise });
    const worker = await start(ui, adjacentTrace());
    assert.equal(ui.batchFitCalls.length, 0);
    assert.equal(button(ui, 'save').disabled, true);
    assert.match(button(ui, 'summary').textContent, /Odczytuję/);
    ui.controls.get('.trace-tolerance').value = '1';
    ui.controls.get('.trace-tolerance').onchange();
    const latest = adjacentTrace();
    latest.shapes = new Map([...latest.shapes].map(([id, shape]) => [id + 2, shape]));
    latest.labels = Int32Array.from(latest.labels, id => id ? id + 2 : 0);
    worker.result(latest);
    ocr.resolve(recognized());
    await tick();
    assert.equal(ui.a1Requests.length, 1, 'one OCR operation serves all analysis generations');
    assert.equal(ui.batchFitCalls.length, 1);
    assert.deepEqual(plain(ui.batchFitCalls[0].map(item => [item.id, item.a1])), [[3, '17'], [4, '18']]);
    assert.ok(rows(ui).every(row => row.check.checked));
    ui.api.close();
  },

  async uncertain_a1_is_prefilled_but_requires_explicit_selection() {
    const trace = numbered();
    trace.a1Suggestions.set(2, { text: '175', status: 'uncertain', assignmentStatus: 'ok',
      alternatives: [{ text: '175' }, { text: '178' }] });
    const ui = createUI();
    await start(ui, trace);
    const [certain, uncertain] = rows(ui);
    assert.equal(certain.check.checked, true);
    assert.equal(uncertain.input.value, '175');
    assert.equal(uncertain.check.checked, false);
    assert.match(uncertain.state.textContent, /Sprawdź A1/);
    assert.deepEqual(uncertain.row.children[4].children.slice(1).map(child=>child.textContent), ['175','178']);
    assert.match(button(ui, 'save').textContent, /\(1\)/);
    uncertain.check.checked = true;
    uncertain.check.onchange();
    assert.match(button(ui, 'save').textContent, /\(2\)/);
    ui.api.close();
  },

  async explicit_batch_variant_resolves_missing_a1_and_is_retained_after_refit() {
    const trace=numbered();
    trace.a1Suggestions.set(2,{text:'',status:'conflict',assignmentStatus:'ok',
      alternatives:[{text:'175'},{text:'178'}]});
    const ui=createUI();await start(ui,trace);
    const row=rows(ui)[1],oldChoice=row.row.children[4].children[2];
    assert.equal(row.input.value,'');assert.equal(row.check.checked,false);
    oldChoice.onclick();
    assert.equal(row.input.value,'178');assert.equal(row.check.checked,true);
    assert.match(row.state.textContent,/ręcznie/);
    ui.controls.get('.trace-parcel-distance').value='5';ui.controls.get('.trace-parcel-distance').onchange();await tick();
    assert.equal(rows(ui)[1].input.value,'178');assert.equal(rows(ui)[1].check.checked,true);
    setNumber(rows(ui)[1],'180');oldChoice.onclick();
    assert.equal(rows(ui)[1].input.value,'180','A removed row cannot overwrite the current proposal');
    await button(ui,'save').onclick();
    assert.deepEqual(plain(ui.batchAddCalls[0].map(item=>item.a1)),['17','180']);ui.api.close();
  },

  async rejected_batch_geometry_blocks_variant_selection() {
    const trace=numbered();
    trace.a1Suggestions.set(2,{text:'',status:'conflict',assignmentStatus:'ok',alternatives:[{text:'178'}]});
    const fit={items:selectedItems().map((item,index)=>({...item,a1:index?'':'17',
      status:index?'rejected':'ready',reason:index?'Synthetic overlap':''}))};
    const ui=createUI([],{batchFits:[Promise.resolve(fit)]});await start(ui,trace);
    const row=rows(ui)[1],choice=row.row.children[4].children[1];
    assert.equal(choice.disabled,true);choice.onclick();assert.equal(row.input.value,'');
    assert.equal(row.check.checked,false);ui.api.close();
  },

  async confirmed_tentative_a1_survives_refits_and_changed_ocr_retry() {
    const initial = recognized(), retry = deferred();
    initial.annotations[0].status = 'uncertain';
    const first = Promise.resolve(initial);
    const ui = createUI([], { a1Load: first, a1Loads: [first, retry.promise] });
    await start(ui, adjacentTrace());
    assert.equal(rows(ui)[0].check.checked, false);
    assert.ok(ui.draws.labels.includes('17 ?'));
    rows(ui)[0].check.checked = true;
    rows(ui)[0].check.onchange();
    assert.equal(rows(ui)[0].state.textContent, 'A1 potwierdzony.');
    assert.match(rows(ui)[0].row.className, /ready/);
    assert.ok(ui.draws.labels.includes('17') && !ui.draws.labels.includes('17 ?'));
    ui.controls.get('.trace-parcel-distance').value = '5';
    ui.controls.get('.trace-parcel-distance').onchange();
    await tick();
    assert.equal(rows(ui)[0].input.value, '17');
    assert.equal(rows(ui)[0].state.textContent, 'A1 potwierdzony.');
    rows(ui)[0].check.checked = false;
    rows(ui)[0].check.onchange();
    ui.controls.get('.trace-a1-retry').onclick();
    const changed = recognized();
    changed.annotations[0].text = '999';
    retry.resolve(changed);
    await tick();
    assert.equal(rows(ui)[0].input.value, '17', 'explicitly accepted numbering must survive a different later OCR guess');
    assert.equal(rows(ui)[0].state.textContent, 'A1 potwierdzony.');
    assert.equal(rows(ui)[0].check.checked, false, 'unchecking excludes save but retains the accepted value');
    assert.equal(ui.batchFitCalls.at(-1)[0].a1, '17');
    assert.match(button(ui, 'summary').textContent, /do sprawdzenia \/ uzupełnienia: 0/);
    ui.api.close();
  },

  async failed_ocr_keeps_batch_editable_and_retry_preserves_manual_a1() {
    const first = deferred(), retry = deferred();
    const ui = createUI([], { a1Load: first.promise, a1Loads: [first.promise, retry.promise] });
    await start(ui, adjacentTrace());
    first.reject(new Error('Synthetic OCR unavailable'));
    await tick();
    assert.equal(rows(ui).length, 2);
    assert.ok(rows(ui).every(row => !row.input.disabled && !row.check.checked));
    assert.equal(button(ui, 'save').disabled, true);
    setNumber(rows(ui)[0], '178a');
    assert.equal(button(ui, 'save').disabled, false);
    ui.controls.get('.trace-a1-retry').onclick();
    assert.equal(button(ui, 'save').disabled, true);
    retry.resolve(recognized());
    await tick();
    assert.deepEqual(rows(ui).map(row => row.input.value), ['178a', '18']);
    assert.ok(rows(ui).every(row => row.check.checked));
    assert.equal(ui.a1Requests.length, 2);
    ui.api.close();
  },

  async manual_a1_and_explicit_unchecking_survive_snap_refitting() {
    const ui = createUI([Promise.resolve([rectangle5216()]), Promise.resolve([rectangle5216()])]);
    await start(ui);
    setNumber(rows(ui)[0], '178a');
    rows(ui)[1].check.checked = false;
    rows(ui)[1].check.onchange();
    ui.controls.get('.trace-parcel-distance').value = '6';
    ui.controls.get('.trace-parcel-distance').onchange();
    await tick();
    assert.equal(ui.batchFitCalls.length, 2);
    assert.equal(ui.batchFitCalls[1][0].a1, '178a');
    assert.equal(ui.batchFitOptions[1].snapDistance, 6);
    assert.equal(rows(ui)[0].input.value, '178a');
    assert.equal(rows(ui)[0].check.checked, true);
    assert.match(rows(ui)[0].state.textContent, /ręcznie/);
    assert.equal(rows(ui)[1].check.checked, false, 'a refit must preserve deliberate exclusions');
    ui.controls.get('.trace-parcel-snap').checked = false;
    ui.controls.get('.trace-parcel-snap').onchange();
    await tick();
    assert.equal(rows(ui)[0].input.value, '178a');
    assert.equal(rows(ui)[1].check.checked, false);
    ui.api.close();
  },

  async global_parcel_fit_keeps_the_same_shared_path_for_both_batch_neighbours() {
    const feature = { code: '5216', closed: false, geometry: [[[32, -10], [32, -110]]] };
    const trace = adjacentTrace();
    trace.shapes.get(1).points = [[20, 20], [30, 20], [30, 100], [20, 100]];
    trace.shapes.get(1).bounds = [20, 20, 30, 100];
    trace.shapes.get(2).points = [[30, 20], [130, 20], [130, 100], [30, 100]];
    trace.shapes.get(2).bounds = [30, 20, 130, 100];
    for (let y = 20; y < 100; y++) for (let x = 20; x < 130; x++) trace.labels[y * 160 + x] = x < 30 ? 1 : 2;
    const ui = createUI([Promise.resolve([feature]), Promise.resolve([feature])]);
    await start(ui, numbered(trace));
    const [thin, wide] = plain(ui.batchFitCalls[0].map(item => item.points));
    const shared = thin.filter(point => wide.some(other => point[0] === other[0] && point[1] === other[1]));
    assert.deepEqual(shared, [[20, 30], [100, 30]],
      'a narrow field veto must preserve the very same shared edge in its wider neighbour');
    ui.api.close();
  },

  async parcel_worker_yields_before_backend_and_caches_only_current_results() {
    const feature = rectangle5216();
    feature.nativeGeometry = feature.geometry;
    feature.geometry = rectangle5216(500, 500, 600, 600).geometry;
    const ui = createUI([Promise.resolve([feature]), Promise.resolve([feature])], { manualParcelWorkers: true });
    await start(ui);
    assert.equal(ui.parcelWorkers.length, 1);
    assert.equal(ui.batchFitCalls.length, 0, 'backend fitting waits for global 5216 fitting');
    assert.equal(ui.parcelOptions.length, 0, 'the batch path must never run snapRings on the main thread');
    assert.equal(button(ui, 'save').disabled, true);
    assert.equal(button(ui, 'cancel').disabled, false);
    assert.match(button(ui, 'summary').textContent, /Dopasowuję/);
    const worker = ui.parcelWorkers[0], job = worker.messages[0];
    assert.equal(job.rings.length, 2);
    assert.deepEqual(job.features[0].geometry, feature.nativeGeometry);
    assert.equal(job.options.distance, 3);
    worker.complete();
    await tick();
    assert.equal(worker.terminated, true);
    assert.equal(ui.batchFitCalls.length, 1);
    assert.ok(rows(ui).every(row => row.check.checked));
    button(ui, 'parcels').checked = false;
    button(ui, 'parcels').onchange();
    await tick();
    assert.equal(ui.parcelWorkers.length, 1, 'selection-only changes reuse the completed mesh cache');
    assert.equal(ui.batchFitCalls.length, 2);
    ui.api.close();
  },

  async cancel_or_close_terminates_pending_parcel_work_and_ignores_late_callbacks() {
    for (const action of ['cancel', 'close']) {
      const refs = [rectangle5216()], ui = createUI([Promise.resolve(refs), Promise.resolve(refs)],
        { manualParcelWorkers: true });
      await start(ui);
      const worker = ui.parcelWorkers[0], late = worker.onmessage;
      const output = executeParcelWorker(worker.messages[0]).messages[0];
      if (action === 'cancel') button(ui, 'cancel').onclick();
      else ui.api.close();
      assert.equal(worker.terminated, true);
      assert.equal(worker.onmessage, null);
      await tick();
      const draws = ui.draws.count;
      late({ data: output });
      await tick();
      assert.equal(ui.batchFitCalls.length, 0);
      assert.equal(ui.draws.count, draws);
      assert.equal(rows(ui).length, 0);
      ui.api.close();
    }
  },

  async changed_settings_quality_or_analysis_replaces_parcel_jobs_without_cache_poisoning() {
    for (const change of ['settings', 'quality', 'analysis']) {
      const refs = [rectangle5216()];
      const ui = createUI([Promise.resolve(refs), Promise.resolve(refs), Promise.resolve(refs)],
        { manualParcelWorkers: true });
      await start(ui);
      const old = ui.parcelWorkers[0], late = old.onmessage, lateError = old.onerror;
      const poisoned = executeParcelWorker(old.messages[0]).messages[0];
      for (const result of poisoned.results) for (const point of result.points) { point[0] += 1000; point[1] += 1000; }
      if (change === 'settings') {
        ui.controls.get('.trace-parcel-distance').value = '6';
        ui.controls.get('.trace-parcel-distance').onchange();
      } else if (change === 'quality') {
        ui.controls.get('.trace-quality').value = '6000000';
        ui.controls.get('.trace-quality').onchange();
        await tick();
        ui.workers.find(worker => !worker.terminated).result(numbered());
      } else {
        ui.controls.get('.trace-tolerance').value = '4';
        ui.controls.get('.trace-tolerance').onchange();
        ui.workers.find(worker => !worker.terminated).result(numbered());
      }
      await tick();
      assert.equal(old.terminated, true);
      assert.equal(ui.parcelWorkers.length, 2);
      const current = ui.parcelWorkers[1];
      poisoned.id = current.messages[0].id;
      late({ data: poisoned });
      lateError();
      await tick();
      assert.equal(current.terminated, false, 'an old callback cannot cancel the replacement worker');
      assert.equal(ui.batchFitCalls.length, 0);
      current.complete();
      await tick();
      assert.equal(ui.batchFitCalls.length, 1);
      assert.ok(ui.batchFitCalls[0].every(item => item.points.every(p => p.every(value => value < 200))));
      button(ui, 'cancel').onclick();
      await ui.click(40, 50);
      assert.ok(ui.fitCalls.at(-1).every(p => p.every(value => value < 200)),
        'a stale worker cannot poison the cache reused by single-field tracing');
      ui.api.close();
    }
  },

  async parcel_worker_failure_never_silently_uses_unfitted_geometry() {
    for (const failure of ['runtime', 'malformed', 'import']) {
      const refs = [rectangle5216()], ui = createUI([Promise.resolve(refs), Promise.resolve(refs)],
        { manualParcelWorkers: true, parcelWorkerFailure: failure === 'import' ? 'import' : '' });
      await start(ui);
      const worker = ui.parcelWorkers[0];
      if (failure === 'runtime') worker.onerror();
      else if (failure === 'malformed') worker.complete({ id: worker.messages[0].id, results: [] });
      else worker.complete();
      await tick();
      assert.equal(worker.terminated, true);
      assert.equal(ui.batchFitCalls.length, 0);
      assert.equal(rows(ui).length, 0);
      assert.equal(button(ui, 'save').disabled, true);
      assert.equal(button(ui, 'start').disabled, false, 'a failed job can be explicitly retried');
      assert.match(button(ui, 'summary').textContent, /[Pp]onów/);
      ui.api.close();
    }
  },

  async source_mesh_work_guard_includes_unselected_shapes_before_creating_a_worker() {
    const trace = numbered();
    for (let id = 100; id < 200; id++) trace.shapes.set(id, {
      points: Array.from({ length: 500 }, (_, j) => [40 + 10 * Math.cos(2 * Math.PI * j / 500),
        50 + 10 * Math.sin(2 * Math.PI * j / 500)]), bounds: [30, 40, 50, 60], suggested: false,
    });
    const refs = [rectangle5216()], ui = createUI([Promise.resolve(refs), Promise.resolve(refs)]);
    await start(ui, trace);
    assert.equal(ui.parcelWorkers.length, 0);
    assert.equal(ui.parcelOptions.length, 0);
    assert.equal(ui.batchFitCalls.length, 0);
    assert.match(button(ui, 'summary').textContent, /Siatka źródłowa.*50 000.*grubsze kontury/);
    assert.equal(button(ui, 'save').disabled, true);
    ui.controls.get('.trace-parcel-snap').checked = false;
    ui.controls.get('.trace-parcel-snap').onchange();
    await tick();
    assert.equal(ui.batchFitCalls[0].length, 2,
      'disabling 5216 avoids global mesh work and may retain a small valid selected payload');
    ui.api.close();
  },

  async rejected_and_missing_a1_cannot_enter_the_saved_selection() {
    const fitting = deferred(), trace = numbered();
    trace.a1Suggestions.delete(2);
    const ui = createUI([], { batchFits: [fitting.promise] });
    await start(ui, trace);
    const result = report(ui.batchFitCalls[0]);
    Object.assign(result.items[0], { status: 'rejected', reason: 'Existing 5310 conflict' });
    fitting.resolve(result);
    await tick();
    const [rejected, missing] = rows(ui);
    assert.equal(rejected.check.disabled, true);
    assert.equal(missing.check.disabled, true);
    assert.equal(button(ui, 'save').disabled, true);
    await button(ui, 'save').onclick();
    assert.equal(ui.batchAddCalls.length, 0);
    setNumber(rejected, '900');
    assert.equal(rejected.check.checked, false);
    setNumber(missing, '901');
    assert.equal(missing.check.checked, true);
    await button(ui, 'save').onclick();
    assert.equal(ui.batchAddCalls.length, 1);
    assert.deepEqual(plain(ui.batchAddCalls[0].map(item => [item.id, item.a1])), [[2, '901']]);
    assert.equal(ui.addCalls.length, 0);
    assert.equal(button(ui, 'list').children.length, 0);
    ui.api.close();
  },

  async a_batch_save_submits_exact_fitted_points_once_and_disables_mutation() {
    const fitting = deferred(), saving = deferred();
    const ui = createUI([], { batchFits: [fitting.promise], batchAddResult: saving.promise });
    await start(ui);
    const canonical = report(ui.batchFitCalls[0]);
    canonical.items[0].points = [[21, 21], [21, 60], [101, 60], [101, 21]];
    canonical.items[1].points = [[21, 60], [21, 101], [101, 101], [101, 60]];
    fitting.resolve(canonical);
    await tick();
    const first = button(ui, 'save').onclick();
    await tick();
    await button(ui, 'save').onclick();
    assert.equal(ui.batchAddCalls.length, 1);
    assert.deepEqual(plain(ui.batchAddCalls[0].map(item => item.points)), plain(canonical.items.map(item => item.points)));
    assert.equal(button(ui, 'save').disabled, true);
    assert.equal(button(ui, 'cancel').disabled, true);
    assert.equal(ui.controls.get('.trace-close').disabled, true);
    assert.ok(rows(ui).every(row => row.input.disabled && row.check.disabled));
    assert.equal(ui.api.close(), false, 'a committing batch must not be disposed halfway through');
    saving.resolve({ changed: true });
    await first;
    assert.equal(button(ui, 'list').children.length, 0);
    assert.equal(ui.workers.filter(worker => !worker.terminated).length, 1);
    assert.equal(ui.addCalls.length, 0);
    ui.api.close();
  },

  async save_all_without_a1_uses_every_valid_outline_and_no_numbers(){
    const trace=sixFields(),fitting=deferred(),saving=deferred();
    trace.a1Suggestions.set(2,{text:'18',status:'uncertain',assignmentStatus:'ok'});
    trace.a1Suggestions.delete(3);
    trace.a1Suggestions.set(4,{text:'',status:'conflict',assignmentStatus:'ok',
      alternatives:[{text:'40'},{text:'41'}]});
    const ui=createUI([],{batchFits:[fitting.promise],batchAddResult:saving.promise});
    await start(ui,trace);
    const fitted=report(ui.batchFitCalls[0]);
    Object.assign(fitted.items[5],{status:'rejected',reason:'Existing 5310 conflict'});
    fitting.resolve(fitted);await tick();
    const before=rows(ui);before[0].check.checked=false;before[0].check.onchange();
    setNumber(before[4],'305');before[4].check.checked=false;before[4].check.onchange();
    assert.equal(before[1].check.checked,false);assert.equal(before[2].input.value,'');
    assert.equal(before[3].input.value,'');assert.equal(button(ui,'save-empty').disabled,false);
    assert.match(button(ui,'save-empty').textContent,/Wkreśl wszystkie bez A1 \(5\)/);
    const savingAll=button(ui,'save-empty').onclick();
    await button(ui,'save-empty').onclick();await button(ui,'save').onclick();
    assert.equal(ui.batchAddCalls.length,1,'Both save actions share the same committing guard');
    assert.deepEqual(plain(ui.batchAddCalls[0]),plain(fitted.items.slice(0,5).map(({id,points})=>({id,points,a1:''}))));
    assert.deepEqual(plain(ui.batchAddOptions[0]),{withoutA1:true});
    assert.deepEqual(rows(ui).map(row=>row.input.value),['17','18','','','305','20'],
      'Preparing the blank payload must not modify the editable A1 drafts');
    assert.equal(button(ui,'save').disabled,true);assert.equal(button(ui,'save-empty').disabled,true);
    assert.equal(button(ui,'cancel').disabled,true);assert.equal(ui.api.close(),false);
    assert.ok(rows(ui).every(row=>row.input.disabled&&row.check.disabled));
    saving.resolve({changed:true});await savingAll;
    assert.equal(rows(ui).length,0);assert.match(ui.status(),/Dodano 5 wydzieleń 5310 bez A1/);
    assert.equal(ui.addCalls.length,0);ui.api.close();
  },

  async failed_no_a1_save_preserves_drafts_and_normal_selected_save(){
    const failure=deferred(),options={batchAddResult:failure.promise},ui=createUI([],options);
    await start(ui);
    rows(ui)[0].check.checked=false;rows(ui)[0].check.onchange();setNumber(rows(ui)[1],'902');
    const original=rows(ui).map(row=>({value:row.input.value,chosen:row.check.checked}));
    const savingAll=button(ui,'save-empty').onclick();failure.reject(Error('Synthetic save failure'));
    await savingAll;
    assert.deepEqual(rows(ui).map(row=>({value:row.input.value,chosen:row.check.checked})),original);
    assert.match(button(ui,'summary').textContent,/Synthetic save failure/);
    assert.equal(button(ui,'save-empty').disabled,false);assert.equal(button(ui,'save').disabled,false);
    options.batchAddResult=Promise.resolve({changed:true});await button(ui,'save').onclick();
    assert.deepEqual(plain(ui.batchAddCalls[0].map(({id,a1})=>[id,a1])),[[1,''],[2,'']]);
    assert.deepEqual(plain(ui.batchAddCalls[1].map(({id,a1})=>[id,a1])),[[2,'902']]);
    assert.equal(ui.batchAddOptions[1],undefined,'Ordinary selected saving must not enable blank A1');
    assert.match(ui.status(),/Dodano 1 wydzieleń 5310 z A1/);ui.api.close();
  },

  async no_a1_save_cannot_use_pending_cancelled_or_rejected_geometry(){
    for(const action of ['cancel','close','reject','unknown']){
      const fitting=deferred(),ui=createUI([],{batchFits:[null,fitting.promise]});
      await start(ui);
      ui.controls.get('.trace-parcel-distance').value='5';ui.controls.get('.trace-parcel-distance').onchange();
      assert.equal(button(ui,'save-empty').disabled,true);await button(ui,'save-empty').onclick();
      assert.equal(ui.batchAddCalls.length,0);
      const response=report(ui.batchFitCalls[1]);
      if(action==='cancel')button(ui,'cancel').onclick();else if(action==='close')ui.api.close();
      else if(action==='reject')for(const item of response.items)Object.assign(item,{status:'rejected',reason:'Overlap'});
      else {delete response.items[0].status;response.items[1].status='not-ready';}
      fitting.resolve(response);await tick();
      await button(ui,'save-empty').onclick();assert.equal(ui.batchAddCalls.length,0);
      if(action==='reject'||action==='unknown'){
        assert.equal(button(ui,'save-empty').disabled,true);
        assert.match(button(ui,'save-empty').textContent,/\(0\)/);
      }
      ui.api.close();
    }
    const ocr=deferred(),ui=createUI([],{a1Load:ocr.promise});await start(ui,adjacentTrace());
    assert.equal(button(ui,'save-empty').disabled,true);await button(ui,'save-empty').onclick();
    assert.equal(ui.batchAddCalls.length,0);
    ocr.reject(Error('OCR is unavailable'));await tick();await tick();
    assert.equal(button(ui,'save').disabled,true);assert.equal(button(ui,'save-empty').disabled,false);
    await button(ui,'save-empty').onclick();
    assert.deepEqual(plain(ui.batchAddCalls[0].map(item=>item.a1)),['','']);ui.api.close();
  },

  async cancelling_a_pending_fit_aborts_it_and_ignores_its_late_result() {
    for (const action of ['cancel', 'close']) {
      const fitting = deferred(), ui = createUI([], { batchFits: [fitting.promise] });
      await start(ui);
      const output = report(ui.batchFitCalls[0]);
      if (action === 'cancel') button(ui, 'cancel').onclick();
      else ui.api.close();
      assert.equal(ui.batchFitOptions[0].signal.aborted, true);
      const draws = ui.draws.count;
      fitting.resolve(output);
      await tick();
      assert.equal(rows(ui).length, 0);
      assert.equal(ui.batchAddCalls.length, 0);
      assert.equal(ui.draws.count, draws, 'a cancelled fit must not repaint a replaced or closed proposal');
      ui.api.close();
    }
  },

  async cancelling_or_closing_while_ocr_waits_never_starts_a_late_batch() {
    for (const action of ['cancel', 'close']) {
      const ocr = deferred(), ui = createUI([], { a1Load: ocr.promise });
      await start(ui, adjacentTrace());
      if (action === 'cancel') button(ui, 'cancel').onclick();
      else ui.api.close();
      ocr.resolve(recognized());
      await tick();
      assert.equal(ui.batchFitCalls.length, 0);
      assert.equal(rows(ui).length, 0);
      if (action === 'close') assert.equal(ui.a1Requests[0].aborted, true);
      ui.api.close();
    }
  },

  async reanalysis_ignores_old_fit_and_old_worker_deliveries() {
    const fitting = deferred(), ui = createUI([], { batchFits: [fitting.promise] });
    const worker = await start(ui);
    const oldAnalysis = worker.analysisID(), oldResult = report(ui.batchFitCalls[0]);
    ui.controls.get('.trace-tolerance').value = '4';
    ui.controls.get('.trace-tolerance').onchange();
    assert.equal(ui.batchFitOptions[0].signal.aborted, true);
    worker.result(numbered(adjacentTrace(), ['901', '902']));
    await tick();
    fitting.resolve(oldResult);
    worker.result(numbered(adjacentTrace(), ['old', 'old']), oldAnalysis);
    await tick();
    assert.equal(ui.batchFitCalls.length, 2);
    assert.deepEqual(rows(ui).map(row => row.input.value), ['901', '902']);
    ui.api.close();
  },

  async failed_refit_removes_old_rows_and_all_hidden_selected_geometry() {
    const failure = deferred(), ui = createUI([], { batchFits: [null, failure.promise] });
    await start(ui);
    assert.equal(rows(ui).length, 2);
    ui.controls.get('.trace-parcel-distance').value = '5';
    ui.controls.get('.trace-parcel-distance').onchange();
    assert.equal(button(ui, 'save').disabled, true);
    assert.ok(rows(ui).every(row => row.check.disabled));
    failure.reject(new Error('Synthetic batch failure'));
    await tick();
    assert.equal(rows(ui).length, 0);
    assert.equal(button(ui, 'save').disabled, true);
    assert.match(button(ui, 'summary').textContent, /Synthetic batch failure/);
    assert.equal(ui.draws.rings.length, 0, 'failed proposals cannot remain drawn as a hidden saved selection');
    await button(ui, 'save').onclick();
    assert.equal(ui.batchAddCalls.length, 0);
    ui.api.close();
  },

  async missing_backend_item_is_a_visible_error_and_cannot_save_partial_results() {
    const fitting = deferred(), ui = createUI([], { batchFits: [fitting.promise] });
    await start(ui);
    fitting.resolve(report(ui.batchFitCalls[0].slice(0, 1)));
    await tick();
    assert.equal(rows(ui).length, 0);
    assert.equal(button(ui, 'save').disabled, true);
    assert.match(button(ui, 'summary').textContent, /wszystkich propozycji/);
    ui.api.close();
  },

  async occupied_regions_and_the_parcel_footprint_filter_are_applied_to_the_whole_batch() {
    const occupied = { ...rectangle5216(20, 20, 60, 100), code: '5310' };
    const boundary = rectangle5216(20, 20, 59, 100);
    const ui = createUI([Promise.resolve([occupied, boundary]), Promise.resolve([occupied, boundary])]);
    await start(ui);
    assert.equal(ui.batchFitCalls.length, 0, 'one region is occupied and the other is outside the parcel footprint');
    assert.equal(rows(ui).length, 0);
    button(ui, 'parcels').checked = false;
    button(ui, 'parcels').onchange();
    await tick();
    assert.deepEqual(plain(ui.batchFitCalls[0].map(item => item.id)), [2]);
    ui.api.close();
  },

  async actual_map_fit_callback_sends_document_revision_snap_and_abort_signal() {
    const items = selectedItems(), map = mapTracingView([report(items)]), controller = new AbortController();
    await map.view.fitBatch(items, { snapDistance: 4.5, signal: controller.signal });
    const call = map.apiCalls[0];
    assert.equal(call.url, '/api/underlay/raster/batch/fit');
    assert.equal(call.options.signal, controller.signal);
    assert.deepEqual(JSON.parse(call.options.body), { documentToken: 'fixture-map', revision: 7,
      items, snapDistance: 4.5 });
    map.state.edit.revision = 8;
    await assert.rejects(map.view.fitBatch(items), /Mapa została zmieniona/);
    assert.equal(map.apiCalls.length, 1);
  },

  async actual_map_late_fit_response_is_rejected_after_a_document_change() {
    const pending = deferred(), items = selectedItems(), map = mapTracingView([pending.promise]);
    const fitting = map.view.fitBatch(items, { snapDistance: 3 });
    await tick();
    const changed = { documentToken: 'another-map', revision: 0 };
    map.state.edit = changed;
    pending.resolve(report(items));
    await assert.rejects(fitting, /Mapa została zmieniona/);
    assert.deepEqual(map.state.edit, changed);
    assert.equal(map.apiCalls.length, 1);
  },

  async actual_map_save_uses_one_exact_preview_and_one_atomic_apply() {
    const items = selectedItems(), map = mapTracingView([approved(items), saved]);
    const result = await map.view.addBatch(items);
    assert.equal(result.createdCount, 2);
    assert.deepEqual(map.apiCalls.map(call => call.url), [
      '/api/underlay/raster/batch/preview', '/api/underlay/raster/batch/apply',
    ]);
    assert.deepEqual(JSON.parse(map.apiCalls[0].options.body), { documentToken: 'fixture-map', revision: 7, items });
    assert.deepEqual(JSON.parse(map.apiCalls[1].options.body), {
      documentToken: 'fixture-map', revision: 7, previewKey: 'reviewed-batch',
    });
    assert.equal(map.state.edit.revision, 8);
    assert.equal(map.state.editBusy, false);
  },

  async actual_map_save_rejects_changed_coordinates_and_unready_preview_without_apply() {
    const items = selectedItems();
    const moved = approved(items);
    moved.items[0] = { ...moved.items[0], points: [[21, 20], ...items[0].points.slice(1)] };
    const missing = { ...approved(items), canApply: false,
      items: [{ ...report(items).items[0], status: 'needsA1', reason: 'Missing A1' }] };
    for (const response of [moved, missing]) {
      const map = mapTracingView([response]);
      await assert.rejects(map.view.addBatch(items), /ponownego sprawdzenia|ponownego dopasowania|Nie zapisano partii/);
      assert.equal(map.apiCalls.length, 1);
      assert.equal(map.state.editBusy, false);
    }
    const stale = mapTracingView([]);
    stale.state.edit.documentToken = 'another-map';
    await assert.rejects(stale.view.addBatch(items), /Mapa została zmieniona/);
    assert.equal(stale.apiCalls.length, 0);
  },

  async actual_map_save_rechecks_context_after_asynchronous_preview() {
    for (const changed of [{ documentToken: 'another-map', revision: 0 },
                           { documentToken: 'fixture-map', revision: 8 }]) {
      const pending = deferred(), items = selectedItems(), map = mapTracingView([pending.promise, saved]);
      const saving = map.view.addBatch(items);
      await tick();
      map.state.edit = changed;
      pending.resolve(approved(items));
      await assert.rejects(saving, /Mapa została zmieniona|zmieniła/);
      assert.equal(map.apiCalls.length, 1, 'a stale preview must never initiate the apply request');
      assert.deepEqual(map.state.edit, changed);
    }
  },

  async actual_map_late_apply_cannot_replace_the_state_of_another_document() {
    const pending = deferred(), items = selectedItems(), map = mapTracingView([approved(items), pending.promise]);
    const saving = map.view.addBatch(items);
    await tick();
    assert.equal(map.apiCalls.length, 2);
    const changed = { documentToken: 'another-map', revision: 0 };
    map.state.edit = changed;
    pending.resolve(saved);
    await assert.rejects(saving, /Mapa została zmieniona|zmieniła/);
    assert.deepEqual(map.state.edit, changed, 'late old-document status must never overwrite a newly loaded MAP');
  },

  async actual_map_preview_must_preserve_the_approved_a1_numbers() {
    const items = selectedItems(), response = approved(items);
    response.items[0].a1 = '999';
    const map = mapTracingView([response, saved]);
    await assert.rejects(map.view.addBatch(items), /ponownego|zmieni|A1|Numer/);
    assert.equal(map.apiCalls.length, 1, 'a preview changing a reviewed A1 must not be applied');
  },

  async actual_map_no_a1_save_binds_the_mode_to_the_exact_preview(){
    const items=selectedItems().map(item=>({...item,a1:''})),preview=approvedWithoutA1(items);
    const map=mapTracingView([preview,saved]);await map.view.addBatch(items,{withoutA1:true});
    assert.deepEqual(JSON.parse(map.apiCalls[0].options.body),{documentToken:'fixture-map',revision:7,items,withoutA1:true});
    assert.deepEqual(JSON.parse(map.apiCalls[1].options.body),{documentToken:'fixture-map',revision:7,previewKey:'reviewed-batch'});
    assert.equal(map.apiCalls.length,2);assert.equal(map.state.edit.revision,8);
  },

  async actual_map_no_a1_save_rejects_preview_inserting_a_number(){
    const items=selectedItems().map(item=>({...item,a1:''})),preview=approvedWithoutA1(items);
    preview.items[1].a1='999';
    const map=mapTracingView([preview,saved]);
    await assert.rejects(map.view.addBatch(items,{withoutA1:true}),/ponownego|zmieni|A1|Numer/);
    assert.equal(map.apiCalls.length,1);
  },

  async actual_map_no_a1_save_rejects_a_stale_document_or_revision(){
    for(const change of [{documentToken:'another-map',revision:0},{documentToken:'fixture-map',revision:8}]){
      const pending=deferred(),items=selectedItems().map(item=>({...item,a1:''})),preview=approvedWithoutA1(items);
      const map=mapTracingView([pending.promise,saved]),saving=map.view.addBatch(items,{withoutA1:true});
      await tick();map.state.edit=change;pending.resolve(preview);
      await assert.rejects(saving,/Mapa została zmieniona|zmieniła/);
      assert.equal(map.apiCalls.length,1);assert.deepEqual(map.state.edit,change);
    }
  },

  async actual_map_save_requires_the_preview_to_keep_the_requested_a1_mode(){
    for(const withoutA1 of [false,true]){
      const items=selectedItems().map(item=>({...item,a1:withoutA1?'':item.a1}));
      const preview=withoutA1?approvedWithoutA1(items):approved(items);
      preview.withoutA1=!withoutA1;
      const map=mapTracingView([preview,saved]);
      await assert.rejects(map.view.addBatch(items,{withoutA1}),/tryb|A1|ponownie/i);
      assert.equal(map.apiCalls.length,1,'An opposite preview mode must not reach apply');
    }
  },
};

(async () => {
  const scenario = process.argv[2];
  assert.ok(cases[scenario], 'Unknown batch scenario: ' + scenario);
  await cases[scenario]();
  console.log(scenario + ': OK');
})().catch(error => { console.error(error); process.exitCode = 1; });
