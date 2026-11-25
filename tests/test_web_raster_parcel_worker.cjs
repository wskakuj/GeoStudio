'use strict';
// Execute the genuine worker script and its imported global topology helper.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../geostudio/web_app/static');

function executeParcelWorker(data, failure = '') {
  const messages = [], imports = [];
  let calls = 0;
  const scope = { console, postMessage: message => messages.push(structuredClone(message)) };
  const context = vm.createContext(scope);
  vm.runInContext('this.self=globalThis;', context);
  scope.importScripts = url => {
    assert.equal(url, '/raster_parcel_snap.js');
    imports.push(url);
    if (failure === 'import') throw Error('Synthetic missing fitting asset');
    vm.runInContext(fs.readFileSync(path.join(root, url.slice(1)), 'utf8'), context, { filename: url });
    const actual = scope.GeoStudioRasterParcelSnap.snapRings;
    scope.GeoStudioRasterParcelSnap.snapRings = (...args) => {
      calls++;
      if (failure === 'run') throw Error('Synthetic fitter failure');
      return actual(...args);
    };
  };
  vm.runInContext(fs.readFileSync(path.join(root, 'raster_parcel_worker.js'), 'utf8'), context,
                  { filename: 'raster_parcel_worker.js' });
  scope.onmessage({ data: structuredClone(data) });
  return { messages, imports, calls };
}

function request() {
  return { id: 7, rings: [
    [[20, 20], [30, 20], [30, 100], [20, 100]],
    [[30, 20], [130, 20], [130, 100], [30, 100]],
  ], features: [{ code: '5216', closed: false, geometry: [[[32, 10], [32, 110]]] }],
  options: { distance: 3, precisionDistance: 3 } };
}

const cases = {
  actual_import_preserves_global_shared_boundary_veto() {
    const input = request(), run = executeParcelWorker(input);
    assert.deepEqual(run.imports, ['/raster_parcel_snap.js']);
    assert.equal(run.calls, 1, 'the entire mesh must enter one shared-boundary decision');
    assert.equal(run.messages.length, 1);
    const output = run.messages[0];
    assert.equal(output.id, input.id);
    assert.equal(output.error, undefined);
    assert.deepEqual(output.results.map(result => result.points), input.rings);
    const [thin, wide] = output.results.map(result => result.points);
    assert.deepEqual(thin.filter(p => wide.some(q => p[0] === q[0] && p[1] === q[1])), [[30, 20], [30, 100]]);
  },
  native_5216_paths_and_diagnostics_survive_worker_messages() {
    const input = request();
    input.rings = [[[20, 20], [100, 20], [100, 100], [20, 100]]];
    input.features = [{ code: '5216', closed: true,
      geometry: [[[500, 500], [600, 500], [600, 600], [500, 600]]],
      nativeGeometry: [[[21, 21], [61, 21], [101, 21], [101, 101], [21, 101]]] }];
    const output = executeParcelWorker(input).messages[0];
    assert.equal(output.error, undefined);
    assert.equal(output.results.length, 1);
    assert.ok(output.results[0].points.some(([x, y]) => x === 61 && y === 21));
    assert.equal(output.results[0].points.length, output.results[0].sourceIndices.length);
    assert.ok(output.results[0].diagnostics.matchedSides > 0);
  },
  import_or_calculation_failure_returns_retry_error_without_geometry() {
    for (const failure of ['import', 'run']) {
      const output = executeParcelWorker(request(), failure).messages[0];
      assert.equal(output.id, 7);
      assert.match(output.error, /ponów|Ponów/);
      assert.equal(output.results, undefined, 'failure cannot silently return an unfitted fallback');
    }
  },
  complete_source_mesh_limit_is_checked_before_running_the_fitter() {
    const input = request();
    input.rings = Array.from({ length: 101 }, () => Array.from({ length: 500 }, (_, i) => [i, i % 3]));
    const run = executeParcelWorker(input);
    assert.equal(run.calls, 0);
    assert.match(run.messages[0].error, /Siatka źródłowa.*50 000/);
    assert.equal(run.messages[0].results, undefined);
  },
  the_source_mesh_may_include_more_than_one_thousand_unselected_neighbours() {
    const input = request();
    input.features = [];
    input.rings = Array.from({ length: 1200 }, (_, i) => [[i * 10, 0], [i * 10 + 2, 0], [i * 10, 2]]);
    const run = executeParcelWorker(input);
    assert.equal(run.messages[0].error, undefined);
    assert.equal(run.messages[0].results.length, 1200);
    assert.equal(run.calls, 1, 'the proposal cap must not omit neighbours needed by global topology');
  },
  malformed_messages_do_not_reach_the_fitting_algorithm() {
    for (const patch of [
      { rings: [] }, { rings: [[[0, 0], [1, 0], [NaN, 1]]] },
      { rings: [Array.from({ length: 501 }, () => [0, 0])] },
      { options: { distance: 21, precisionDistance: 3 } },
      { options: { distance: 3, precisionDistance: Infinity } }, { features: null },
    ]) {
      const run = executeParcelWorker({ ...request(), ...patch });
      assert.equal(run.calls, 0);
      assert.ok(run.messages[0].error);
      assert.equal(run.messages[0].results, undefined);
    }
  },
};

module.exports = { executeParcelWorker };
if (require.main === module) {
  const scenario = process.argv[2];
  assert.ok(cases[scenario], 'Unknown parcel worker scenario: ' + scenario);
  cases[scenario]();
  console.log(scenario + ': OK');
}
