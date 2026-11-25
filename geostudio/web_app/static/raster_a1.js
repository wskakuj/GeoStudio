/* Assign local OCR annotations to raster fields. Coordinates received from
 * Python refer to the normalized PNG preview, never original PDF/source pixels.
 * This helper contains no recognition model and performs no network requests. */
(function(root){
  "use strict";
  const point=p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite);
  function contains(p,ring){
    let inside=false;
    for(let i=0,j=ring.length-1;i<ring.length;j=i++){
      const a=ring[j],b=ring[i];
      if((a[1]>p[1])!==(b[1]>p[1])&&p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0])inside=!inside;
    }
    return inside;
  }
  function assign(result,trace,width,height){
    const suggestions=new Map();
    if(!trace?.labels||!trace.shapes||!Number.isFinite(result?.width)||!Number.isFinite(result?.height)||
      result.width<=0||result.height<=0||!Array.isArray(result.annotations))return suggestions;
    const sx=width/result.width,sy=height/result.height;
    const scaled=p=>[p[0]*sx,p[1]*sy];
    function owner(p){
      if(!point(p))return null;
      const [x,y]=scaled(p);
      if(x<0||y<0||x>=width||y>=height)return null;
      const id=trace.labels[Math.floor(y)*width+Math.floor(x)],shape=trace.shapes.get(id);
      if(!shape||!contains([x,y],shape.points))return null;
      // Do not decide a boundary endpoint by the rounding direction of a
      // single pixel. Ambiguous near-border tips remain suggestions to review.
      let ambiguous=false;
      for(let dy=-1;dy<=1;dy++)for(let dx=-1;dx<=1;dx++){
        const xx=Math.floor(x)+dx,yy=Math.floor(y)+dy;
        if(xx<0||yy<0||xx>=width||yy>=height)continue;
        const other=trace.labels[yy*width+xx];
        if(other!==id&&trace.shapes.has(other))ambiguous=true;
      }
      return {id,ambiguous,anchor:[x,y]};
    }
    function add(id,item){
      const previous=suggestions.get(id);
      if(!previous){suggestions.set(id,item);return;}
      if(previous.status==="conflict")return;
      if(previous.text&&item.text&&previous.text!==item.text){
        suggestions.set(id,{...previous,text:"",status:"conflict"});return;
      }
      if(previous.status!=="ok"||item.status!=="ok"){
        suggestions.set(id,{...previous,text:previous.text||item.text,status:"uncertain"});return;
      }
      if(item.confidence>previous.confidence)suggestions.set(id,item);
    }
    for(const annotation of result.annotations.slice(0,20000)){
      if(!annotation||typeof annotation!=="object")continue;
      const text=String(annotation.text||"").trim();
      if(text&&!/^\d{1,8}$/.test(text))continue;
      let status=annotation.status==="ok"&&text?"ok":annotation.status==="conflict"?"conflict":"uncertain";
      const ends=Array.isArray(annotation.leaderEndpoints)?annotation.leaderEndpoints.filter(point):[];
      const endOwners=annotation.hasLeader?ends.map(owner).filter(Boolean):[];
      const ids=new Set(endOwners.map(p=>p.id));
      const located=owner(annotation.anchor);
      // Never substitute a callout centre for a missing/branched leader tip.
      if(annotation.hasLeader&&(!located||ids.size>1||ids.size===1&&!ids.has(located.id))){
        for(const end of endOwners)add(end.id,{text,status:"uncertain",confidence:0,
          source:"callout",anchor:end.anchor});
        continue;
      }
      if(!located)continue;
      if(located.ambiguous||endOwners.some(p=>p.ambiguous))status="uncertain";
      const box=Array.isArray(annotation.box)&&annotation.box.length===4&&annotation.box.every(Number.isFinite)
        ?[annotation.box[0]*sx,annotation.box[1]*sy,annotation.box[2]*sx,annotation.box[3]*sy]:null;
      add(located.id,{text,status,confidence:Number(annotation.confidence)||0,
        source:annotation.source==="inside"?"inside":"callout",box,anchor:located.anchor});
    }
    return suggestions;
  }
  root.GeoStudioRasterA1=Object.freeze({assign});
})(typeof globalThis!=="undefined"?globalThis:this);
