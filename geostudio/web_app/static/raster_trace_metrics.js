/* Measure ink around detected raster sides before choosing the initial snap
 * range. Pure worker helper; coordinates and radii here are image pixels. */
(function(root){
  "use strict";
  const WINDOW=24,MAX_EDGES=512;
  const finitePoint=p=>Array.isArray(p)&&p.length>=2&&Number.isFinite(p[0])&&Number.isFinite(p[1]);
  function quantile(values,fraction){
    const ordered=values.slice().sort((a,b)=>a-b);
    return ordered[Math.min(ordered.length-1,Math.max(0,Math.ceil(fraction*ordered.length)-1))];
  }
  function estimateStrokeRadius(pixels,width,height,shapes,tolerance=2.5,mask=null){
    if(!Number.isInteger(width)||!Number.isInteger(height)||width<3||height<3||
      !pixels||pixels.length<width*height*4)return null;
    const limit=Number.isFinite(Number(tolerance))?Math.max(0,Math.min(10,Number(tolerance))):2.5;
    const minimumLength=Math.max(12,4*limit),rings=[];
    const values=shapes&&typeof shapes.values==="function"?shapes.values():[];
    for(const shape of values){
      const ring=Array.isArray(shape)?shape:shape?.points;
      if(Array.isArray(ring)&&ring.length>=3&&ring.every(finitePoint))rings.push(ring);
    }
    function visit(callback){
      for(const ring of rings)for(let i=0;i<ring.length;i++){
        const a=ring[i],b=ring[(i+1)%ring.length],length=Math.hypot(b[0]-a[0],b[1]-a[1]);
        if(length>=minimumLength)callback(a,b,length);
      }
    }
    let count=0;visit(()=>count++);
    if(!count)return null;
    const masked=mask&&mask.length>=width*height*4;
    function ink(x,y){
      const u=Math.floor(x),v=Math.floor(y);
      if(u<0||v<0||u>=width||v>=height)return -1;
      const i=4*(v*width+u);
      if(masked&&mask[i+3]>=128)return 0;
      const r=pixels[i],g=pixels[i+1],b=pixels[i+2],hi=Math.max(r,g,b),lo=Math.min(r,g,b);
      return hi<155&&hi-lo<48||r-g>22&&r-b>18&&g-b<(r-g)*.65?1:0;
    }
    const search=Math.min(8,Math.max(2,Math.ceil(limit)+1));
    function measure(x,y,nx,ny){
      const samples=[];
      for(let at=-WINDOW;at<=WINDOW;at++)samples.push(ink(x+nx*at,y+ny*at));
      let seed=-1;
      for(let offset=0;offset<=search&&seed<0;offset++)for(const sign of offset?[-1,1]:[1]){
        const i=WINDOW+offset*sign;if(samples[i]===1){seed=i;break;}
      }
      if(seed<0)return null;
      let lo=seed,hi=seed;
      while(lo>0&&samples[lo-1]===1)lo--;
      while(hi<samples.length-1&&samples[hi+1]===1)hi++;
      // A solid patch, an image edge or a stroke wider than the bounded search
      // is not a trustworthy width measurement. Never turn it into a huge
      // automatic magnetic range.
      if(lo===0||hi===samples.length-1||samples[lo-1]<0||samples[hi+1]<0)return null;
      return {half:(hi-lo)/2,radius:Math.max(Math.abs(lo-WINDOW),Math.abs(hi-WINDOW))};
    }
    const stride=Math.max(1,count/MAX_EDGES),radii=[],widths=[];
    let next=stride===1?0:stride/2,at=0,samples=0;
    visit((a,b,length)=>{
      if(at++<next)return;
      next+=stride;
      const nx=-(b[1]-a[1])/length,ny=(b[0]-a[0])/length,runs=[];
      for(const fraction of [.1,.3,.5,.7,.9]){
        const run=measure(a[0]+fraction*(b[0]-a[0]),a[1]+fraction*(b[1]-a[1]),nx,ny);
        if(run)runs.push(run);
      }
      // One letter crossing a boundary cannot define the range for the map.
      // Require ink at most sample locations and use its median per side.
      if(runs.length<3)return;
      radii.push(quantile(runs.map(run=>run.radius),.5));
      widths.push(quantile(runs.map(run=>run.half),.5));
      samples+=runs.length;
    });
    if(radii.length<2||samples<6)return null;
    const observedRadiusPixels=quantile(radii,.9),halfWidthPixels=quantile(widths,.9);
    // The measured reach includes any displacement of the fitted side from
    // the ink centre. The simplification limit covers unsampled pen wobble;
    // one extra pixel covers raster quantization at the two stroke edges.
    return {radiusPixels:Math.max(3,observedRadiusPixels+limit+1),
      halfWidthPixels,observedRadiusPixels,samples,edges:radii.length};
  }
  root.GeoStudioRasterTraceMetrics={estimateStrokeRadius};
})(typeof globalThis!=="undefined"?globalThis:this);
