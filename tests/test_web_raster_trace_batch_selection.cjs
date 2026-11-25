// Synthetic footprint geometry through the actual selection and containment helpers.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const sandbox = vm.createContext({});
for (const file of ['raster_trace.js', 'raster_trace_batch.js']) {
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../geostudio/web_app/static', file), 'utf8'), sandbox);
}
const rectangle = (l,t,r,b) => [[l,t],[r,t],[r,b],[l,b]];
const parcel = (...rings) => ({code:'5216',closed:true,geometry:rings});
function collect(points, seed, references, options={}) {
  return sandbox.GeoStudioRasterTraceBatch.collect({
    trace:{shapes:new Map([[1,{suggested:true,points}]])},
    referenceFeatures:references, worldAt:(x,y)=>({x,y}),
    regionSeed:()=>seed, pointInRings:sandbox.tracePointInRings, ...options,
  });
}
function kept(result) {
  assert.equal(result.items.length,1);
  assert.equal(result.outside,0);
  assert.equal(result.items[0].chosen,false,'a retained outline without A1 still requires review');
}

const scenarios = {
  enclosed_parcel_is_retained_without_a_field_vertex_or_seed_inside() {
    kept(collect(rectangle(-10,-1,10,1),[0,0],[parcel(rectangle(4,-.5,6,.5))]));
  },
  crossing_strips_are_retained_when_neither_ring_has_an_inside_vertex() {
    kept(collect(rectangle(-10,-1,10,1),[0,0],[parcel(rectangle(4,-5,6,5))]));
  },
  a_field_wholly_inside_a_native_hole_is_outside_the_footprint() {
    const reference=parcel(rectangle(-20,-20,20,20),rectangle(-8,-8,8,8));
    const result=collect(rectangle(-3,-1,3,1),[0,0],[reference]);
    assert.equal(result.items.length,0);
    assert.equal(result.outside,1);
    kept(collect(rectangle(-3,-1,3,1),[0,0],[reference],{withinParcels:false}));
  },
  a_field_crossing_the_hole_boundary_or_a_separate_part_is_retained() {
    const reference=parcel(rectangle(-20,-20,20,20),rectangle(-8,-8,8,8),rectangle(30,-5,35,5));
    kept(collect(rectangle(7,-1,9,1),[7.5,0],[reference]));
    kept(collect(rectangle(25,-1,40,1),[26,0],[reference]));
  },
  native_geometry_and_calibrated_world_coordinates_drive_intersection() {
    const worldAt=(x,y)=>({x:7520000+2*y,y:-5850000+3*x});
    const transformed=rectangle(4,-5,6,5).map(([x,y])=>{const p=worldAt(x,y);return [p.x,p.y];});
    const reference={...parcel(rectangle(100,100,110,110)),nativeGeometry:[transformed]};
    kept(collect(rectangle(-10,-1,10,1),[0,0],[reference],{worldAt}));
  },
  boundary_contacts_are_kept_but_disjoint_geometry_is_filtered() {
    const reference=parcel(rectangle(0,0,10,10));
    kept(collect(rectangle(10,2,15,5),[12,3],[reference]));
    const result=collect(rectangle(11,2,15,5),[12,3],[reference]);
    assert.equal(result.items.length,0);
    assert.equal(result.outside,1);
  },
  reliably_located_unread_or_conflicting_callouts_keep_white_fields_for_review() {
    const points=rectangle(0,0,10,10);
    for(const suggestion of [
      {status:'uncertain',assignmentStatus:'ok',unreadCallout:true,text:'',reason:'unread_field_number'},
      {status:'conflict',assignmentStatus:'ok',text:''},
    ]) {
      const trace={shapes:new Map([[1,{suggested:false,points}]]),a1Suggestions:new Map([[1,suggestion]])};
      const result=collect(points,[5,5],[parcel(rectangle(-1,-1,11,11))],{trace});
      kept(result);
      assert.equal(result.items[0].a1,'');
      assert.equal(result.unmarked,0);
      if(suggestion.unreadCallout)assert.equal(result.items[0].a1Reason,'unread_field_number');
    }
  },
  unassigned_unread_callouts_do_not_invent_white_field_proposals() {
    const points=rectangle(0,0,10,10);
    const trace={shapes:new Map([[1,{suggested:false,points}]]),a1Suggestions:new Map([[1,
      {status:'uncertain',assignmentStatus:'uncertain',unreadCallout:true,text:'',reason:'unread_field_number'}]])};
    const result=collect(points,[5,5],[parcel(rectangle(-1,-1,11,11))],{trace});
    assert.equal(result.items.length,0);
    assert.equal(result.unmarked,1);
  },
};

const selected=process.argv[2];
if(selected){assert.ok(scenarios[selected],`Unknown scenario: ${selected}`);scenarios[selected]();}
else for(const scenario of Object.values(scenarios))scenario();
