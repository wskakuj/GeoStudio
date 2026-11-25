'use strict';
// Execute the actual worker entry point, including its local script imports.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'../geostudio/web_app/static');
function execute(metricFailure){
  const scope={},messages=[],imports=[];
  Object.assign(scope,{console,
    atob:value=>Buffer.from(value,'base64').toString('binary'),
    postMessage:data=>messages.push(data)});
  const context=vm.createContext(scope);
  vm.runInContext('this.WorkerGlobalScope=class WorkerGlobalScope {}; Object.setPrototypeOf(globalThis,WorkerGlobalScope.prototype); this.self=globalThis;',context);
  scope.importScripts=url=>{
    assert.equal(url,'/raster_trace_metrics.js');imports.push(url);
    if(metricFailure==='missing')throw new Error('Missing optional stroke measurement asset');
    vm.runInContext(fs.readFileSync(path.join(root,url.slice(1)),'utf8'),context,{filename:url});
    if(metricFailure==='failed')scope.GeoStudioRasterTraceMetrics={estimateStrokeRadius(){throw Error('Measurement failure');}};
  };
  vm.runInContext(fs.readFileSync(path.join(root,'raster_trace.js'),'utf8'),context,{filename:'raster_trace.js'});
  const w=160,h=120,source=new Uint8ClampedArray(w*h*4);source.fill(255);
  function mark(x,y){source.set([20,20,20,255],4*(y*w+x));}
  for(let y=19;y<=101;y++)for(let x=19;x<=141;x++)
    if(x<22||x>138||y<22||y>98)mark(x,y);
  scope.onmessage({data:{source,mask:new Uint8ClampedArray(source.length),w,h}});
  scope.onmessage({data:{threshold:5,tolerance:2.5,id:47}});
  assert.equal(messages.length,1);const result=messages[0];
  assert.equal(result.id,47);assert.equal(result.error,undefined);
  assert.equal(result.trace.shapes.size,1,'Recognition helpers cannot break the core raster proposal');
  if(metricFailure)assert.equal(result.trace.strokeMetrics,null);
  else assert.ok(result.trace.strokeMetrics.radiusPixels>=3);
  assert.deepEqual(imports,['/raster_trace_metrics.js']);
  assert.equal(result.trace.a1Suggestions,undefined,'The geometry worker does not rerun OCR or invent A1');
}
execute(process.argv[2]||null);
console.log('Worker assets and optional measurement failure isolation: OK');
