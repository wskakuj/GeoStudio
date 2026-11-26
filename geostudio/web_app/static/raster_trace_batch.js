// Whole-sheet proposal selection. Geometry stays in the tracing module so the
// single-field and batch workflows use the same calibrated, shared boundaries.
(function(root){
  "use strict";
  function label(hints){
    const usable=hints.filter(Boolean),certain=usable.filter(h=>h.status==="ok"&&h.assignmentStatus==="ok"&&/^\d{1,8}$/.test(String(h.text||"")));
    // Keep the actual readings available for an explicit human choice even
    // when automatic assignment must abstain. Never use a variant by default.
    const alternatives=[...new Set(usable.flatMap(h=>[String(h.text||""),
      ...(Array.isArray(h.alternatives)?h.alternatives:[]).map(a=>String(a?.text||""))]))]
      .filter(text=>/^\d{1,8}$/.test(text)).slice(0,8);
    const values=new Set(certain.map(h=>String(h.text)));
    if(values.size>1||usable.some(h=>h.status==="conflict"))return {text:"",status:"conflict",alternatives};
    if(values.size===1){
      const text=[...values][0],competing=usable.some(h=>h.assignmentStatus==="ok"&&h.text&&String(h.text)!==text);
      return {text,status:competing?"uncertain":"ok",reason:competing?"selected_field_numbers":"ready",alternatives};
    }
    const tentative=usable.filter(h=>h.assignmentStatus==="ok"&&/^\d{1,8}$/.test(String(h.text||"")));
    const guesses=new Set(tentative.map(h=>String(h.text)));
    return {text:guesses.size===1?[...guesses][0]:"",status:usable.length?"uncertain":"missing",
      reason:usable.some(h=>h.reason==="multiple_field_numbers")?"multiple_field_numbers":
        usable.some(h=>h.reason==="unread_field_number")?"unread_field_number":"weak_text",alternatives};
  }
  function boundsOf(points){
    const bounds=[Infinity,Infinity,-Infinity,-Infinity];
    for(const [x,y] of points){
      bounds[0]=Math.min(bounds[0],x);bounds[1]=Math.min(bounds[1],y);
      bounds[2]=Math.max(bounds[2],x);bounds[3]=Math.max(bounds[3],y);
    }
    return bounds;
  }
  function boundsMeet(a,b){return a[0]<=b[2]&&a[2]>=b[0]&&a[1]<=b[3]&&a[3]>=b[1];}
  function edgesOf(rings){
    const edges=[];
    for(const ring of rings)for(let i=0,j=ring.length-1;i<ring.length;j=i++)edges.push([ring[j],ring[i]]);
    return edges;
  }
  function segmentsMeet(a,b,c,d){
    if(!boundsMeet(boundsOf([a,b]),boundsOf([c,d])))return false;
    const cross=(p,q,r)=>(q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0]);
    const abC=cross(a,b,c),abD=cross(a,b,d),cdA=cross(c,d,a),cdB=cross(c,d,b);
    if(((abC<0&&abD>0)||(abC>0&&abD<0))&&((cdA<0&&cdB>0)||(cdA>0&&cdB<0)))return true;
    const on=(p,q,r,value)=>Math.abs(value)<=1e-8*Math.max(1,Math.hypot(q[0]-p[0],q[1]-p[1]))&&
      r[0]>=Math.min(p[0],q[0])&&r[0]<=Math.max(p[0],q[0])&&
      r[1]>=Math.min(p[1],q[1])&&r[1]<=Math.max(p[1],q[1]);
    return on(a,b,c,abC)||on(a,b,d,abD)||on(c,d,a,cdA)||on(c,d,b,cdB);
  }
  function meetsFootprint(points,seed,references,pointInRings){
    const bounds=boundsOf(points),edges=edgesOf([points]);
    return references.some(reference=>{
      if(!boundsMeet(bounds,reference.bounds))return false;
      // Containment is even/odd across every native ring, so a field wholly
      // inside a parcel's hole remains outside the footprint.
      if(pointInRings(seed,reference.rings)||points.some(point=>pointInRings(point,reference.rings)))return true;
      if(reference.points.some(point=>pointInRings(point,[points])))return true;
      // Crossing strips can have neither a seed nor a vertex inside a parcel.
      return edges.some(([a,b])=>reference.edges.some(([c,d])=>segmentsMeet(a,b,c,d)));
    });
  }
  function collect({trace,referenceFeatures,worldAt,regionSeed,pointInRings,withinParcels=true}){
    const references=referenceFeatures.filter(f=>f.code==="5216"&&f.closed).map(feature=>{
      const rings=feature.nativeGeometry||feature.geometry,points=rings.flat();
      return {rings,points,bounds:boundsOf(points),edges:edgesOf(rings)};
    });
    const items=[];let outside=0,occupied=0,unmarked=0;
    for(const [id,shape] of trace.shapes){
      const suggestion=trace.a1Suggestions?.get(id),hint=label([suggestion]);
      const assignedCallout=suggestion?.assignmentStatus==="ok"&&
        (suggestion.unreadCallout===true||suggestion.status==="conflict");
      if(!shape.suggested&&!hint.text&&!assignedCallout){unmarked++;continue;}
      const seed=regionSeed(id,shape);
      if(!seed){occupied++;continue;}
      if(withinParcels&&references.length){
        const points=shape.points.map(([x,y])=>{const p=worldAt(x,y);return [p.x,p.y];});
        const at=worldAt(...seed);
        if(!meetsFootprint(points,[at.x,at.y],references,pointInRings)){
          outside++;continue;
        }
      }
      items.push({id,seed,shape,a1:hint.text,a1Status:hint.status,a1Reason:hint.reason,alternatives:hint.alternatives,
        chosen:hint.status==="ok",manual:false});
    }
    if(items.length>1000)throw Error("Wykryto "+items.length+" propozycji. Limit testowego trybu to 1000. Wybierz grubsze kontury lub ogranicz analizę do obszaru działek 5216.");
    return {items,outside,occupied,unmarked,references:references.length};
  }
  function counts(items){
    const ready=items.filter(item=>item.status!=="rejected"&&item.a1.trim());
    return {total:items.length,selected:ready.filter(item=>item.chosen).length,
      confident:ready.filter(item=>item.a1Status==="ok"&&!item.manual).length,
      review:items.filter(item=>item.status!=="rejected"&&(!item.a1.trim()||item.a1Status!=="ok"&&!item.manual&&!item.confirmed)).length,
      rejected:items.filter(item=>item.status==="rejected").length};
  }
  root.GeoStudioRasterTraceBatch={label,collect,counts};
})(globalThis);
