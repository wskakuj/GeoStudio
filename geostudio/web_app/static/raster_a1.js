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
    const suggestions=new Map(),candidates=new Map();
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
    function directedOwner(p,direction){
      const located=owner(p);
      if(located&&!located.ambiguous)return located;
      if(!point(p)||!point(direction))return located;
      const length=Math.hypot(...direction);
      if(length<.85||length>1.15)return located;
      const [x,y]=scaled(p),xx=Math.floor(x),yy=Math.floor(y);
      // Zero is an occupied/excluded pixel, not an invitation to find the
      // nearest free polygon. Only a real terminal stroke supplies direction.
      if(xx<0||yy<0||xx>=width||yy>=height||!trace.labels[yy*width+xx])return located;
      const matches=[];
      for(let distance=1;distance<=6;distance++){
        const probe=[p[0]+direction[0]*distance,p[1]+direction[1]*distance];
        const [px,py]=scaled(probe),ix=Math.floor(px),iy=Math.floor(py);
        if(ix<0||iy<0||ix>=width||iy>=height||!trace.labels[iy*width+ix])return located;
        const candidate=owner(probe);
        if(candidate&&!candidate.ambiguous)matches.push(candidate);
      }
      // A tip just on a thick boundary may point unambiguously into a field.
      // Crossing two fields, staying on the boundary or one isolated sample
      // cannot settle ownership; no circle-centre/nearest-field fallback.
      const ids=new Set(matches.map(item=>item.id));
      return matches.length>=2&&ids.size===1?{...matches[0],inferredDirection:true}:located;
    }
    const score=value=>Number.isFinite(Number(value))?Math.max(0,Math.min(1,Number(value))):0;
    function alternatives(items){
      const values=new Map();
      for(const item of items)for(const candidate of [item,...(Array.isArray(item.alternatives)?item.alternatives:[])]){
        if(!candidate||!/^\d{1,8}$/.test(String(candidate.text||"")))continue;
        const text=String(candidate.text),confidence=score(candidate.confidence);
        const previous=values.get(text);
        values.set(text,{text,confidence:Math.max(confidence,previous?.confidence||0),
          votes:Math.max(previous?.votes||0,Math.max(0,Math.min(100,Number(candidate.votes)||0)))});
      }
      return [...values.values()].sort((a,b)=>b.confidence-a.confidence).slice(0,8);
    }
    function add(id,item){
      if(!candidates.has(id))candidates.set(id,[]);
      candidates.get(id).push(item);
    }
    function distinctMark(a,b){
      if(!a.box||!b.box)return false;
      const x=Math.max(0,Math.min(a.box[2],b.box[2])-Math.max(a.box[0],b.box[0]));
      const y=Math.max(0,Math.min(a.box[3],b.box[3])-Math.max(a.box[1],b.box[1]));
      const areaA=(a.box[2]-a.box[0])*(a.box[3]-a.box[1]);
      const areaB=(b.box[2]-b.box[0])*(b.box[3]-b.box[1]);
      return areaA>0&&areaB>0&&x*y<Math.min(areaA,areaB)*.2;
    }
    for(const annotation of result.annotations.slice(0,20000)){
      if(!annotation||typeof annotation!=="object")continue;
      let text=String(annotation.text||"").trim();
      if(text&&!/^\d{1,8}$/.test(text))continue;
      let status=annotation.status==="ok"&&text?"ok":annotation.status==="conflict"?"conflict":"uncertain";
      const textStatus=annotation.textStatus==="ok"||(!annotation.textStatus&&status==="ok")?"ok":"uncertain";
      let reason=String(annotation.reason|| (status==="ok"?"ready":"weak_text"));
      const unreadCallout=reason==="unread_callout"&&annotation.source==="callout"&&
        ["blue","green"].includes(annotation.ink)&&score(annotation.circleConfidence)>=.9;
      let assignmentStatus=annotation.associationStatus==="uncertain"||
        ["possible_circle","detached_leader","missing_leader","branched_leader","leader_network"].includes(reason)
        ?"uncertain":"ok";
      const ends=Array.isArray(annotation.leaderEndpoints)?annotation.leaderEndpoints.filter(point):[];
      // A connected map-line network is not a usable callout. This also
      // protects clients receiving an older OCR result with hundreds of tips.
      if(ends.length>4||annotation.reason==="leader_network")continue;
      const directions=Array.isArray(annotation.leaderDirections)?annotation.leaderDirections:[];
      const endOwners=annotation.hasLeader?ends.map((end,index)=>
        ends.length===1?directedOwner(end,directions[index]):owner(end)).filter(Boolean):[];
      const ids=new Set(endOwners.map(p=>p.id));
      let located=owner(annotation.anchor);
      if(annotation.hasLeader&&ends.length===1&&point(annotation.anchor)&&
        Math.hypot(annotation.anchor[0]-ends[0][0],annotation.anchor[1]-ends[0][1])<1e-4){
        located=endOwners[0]||located;
      }
      const oneFieldFork=annotation.hasLeader&&ends.length>1&&endOwners.length===ends.length&&
        ids.size===1&&endOwners.every(end=>!end.ambiguous)&&
        (!located||ids.has(located.id))&&annotation.reason==="branched_leader";
      if(oneFieldFork){
        located=endOwners[0];assignmentStatus="ok";status=textStatus;
        reason=textStatus==="ok"?"ready":"weak_text";
      }
      // Never substitute a callout centre for a missing/branched leader tip.
      if(annotation.hasLeader&&(!located||!endOwners.length||ids.size>1||ids.size===1&&!ids.has(located.id))){
        for(const end of endOwners)add(end.id,{text,status:"uncertain",textStatus,
          assignmentStatus:"uncertain",reason:"branched_leader",confidence:score(annotation.confidence),
          alternatives:alternatives([annotation]),source:"callout",anchor:end.anchor});
        continue;
      }
      if(!located)continue;
      if(located.ambiguous||endOwners.some(p=>p.ambiguous)){
        assignmentStatus="uncertain";reason="boundary_anchor";
      }
      if(located.inferredDirection||endOwners.some(p=>p.inferredDirection)){
        // The measured terminal points into this field, but no ink exists
        // beyond its tip. Offer the number for review; never preselect this
        // inference as a confirmed field during whole-map tracing.
        status="uncertain";reason="boundary_direction";
        if(annotation.possibleTruncation){text="";reason="partial_text";}
      }
      if(annotation.hasLeader&&ends.length!==1&&!oneFieldFork){assignmentStatus="uncertain";reason="branched_leader";}
      if(assignmentStatus!=="ok")status="uncertain";
      const box=Array.isArray(annotation.box)&&annotation.box.length===4&&annotation.box.every(Number.isFinite)
        ?[annotation.box[0]*sx,annotation.box[1]*sy,annotation.box[2]*sx,annotation.box[3]*sy]:null;
      add(located.id,{text,status,textStatus,assignmentStatus,reason,confidence:score(annotation.confidence),
        unreadCallout,
        alternatives:alternatives([annotation]),
        source:annotation.source==="inside"?"inside":"callout",box,anchor:located.anchor});
    }
    for(const [id,items] of candidates){
      const ready=items.filter(item=>item.status==="ok"&&item.text);
      const values=new Set(ready.map(item=>item.text));
      const choices=alternatives(items);
      if(values.size>1){
        suggestions.set(id,{...ready[0],text:"",status:"conflict",textStatus:"uncertain",
          reason:"conflicting_numbers",alternatives:choices});
      }else if(ready.length){
        // A weak OCR guess must not erase an independently confirmed number.
        const best=ready.sort((a,b)=>b.confidence-a.confidence)[0];
        // Two separate, plausibly read marks with reliable ownership can also
        // reveal a leaked boundary joining different fields. Keep the better
        // number as a review suggestion, without preselecting that polygon.
        const competing=items.find(item=>item.status==="uncertain"&&item.assignmentStatus==="ok"&&
          (item.unreadCallout||item.text!==best.text&&item.text.length>=2&&item.confidence>=.75&&
           item.reason!=="partial_digit")&&distinctMark(item,best));
        suggestions.set(id,{...best,status:competing?"uncertain":"ok",
          reason:competing?(competing.unreadCallout?"unread_field_number":"multiple_field_numbers"):
            best.reason,alternatives:choices});
      }else{
        const anchored=items.filter(item=>item.assignmentStatus==="ok"&&item.text);
        const pool=anchored.length?anchored:items;
        const best=pool.slice().sort((a,b)=>(b.textStatus==="ok")-(a.textStatus==="ok")||
          b.text.length-a.text.length||b.confidence-a.confidence)[0];
        const conflict=items.some(item=>item.status==="conflict");
        suggestions.set(id,{...best,text:conflict?"":best.text,status:conflict?"conflict":"uncertain",
          alternatives:choices,reason:conflict?"conflicting_numbers":best.reason});
      }
    }
    return suggestions;
  }
  root.GeoStudioRasterA1=Object.freeze({assign});
})(typeof globalThis!=="undefined"?globalThis:this);
