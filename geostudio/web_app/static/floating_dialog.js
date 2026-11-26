/* Small modeless windows: move by the title, keep reachable after resize. */
(function(root,factory){
  const api=factory();
  if(typeof module==="object"&&module.exports)module.exports=api;
  else root.GeoStudioFloatingDialog=api;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";
  function boundedRect(rect,viewport,gutter=8){
    const availableWidth=Math.max(1,viewport.width-2*gutter);
    const availableHeight=Math.max(1,viewport.height-2*gutter);
    const width=Math.min(Math.max(1,rect.width),availableWidth);
    const height=Math.min(Math.max(1,rect.height),availableHeight);
    return {left:Math.max(gutter,Math.min(viewport.width-gutter-width,rect.left)),
      top:Math.max(gutter,Math.min(viewport.height-gutter-height,rect.top)),width,height};
  }
  function attach(dialog,options={}){
    const owner=dialog.ownerDocument.defaultView;
    const handle=dialog.querySelector(".floating-dialog-handle");
    const expand=dialog.querySelector(".floating-dialog-expand");
    const viewport=()=>({width:owner.innerWidth,height:owner.innerHeight});
    let drag=null,savedRect=null;
    function place(rect,resize=false){
      const b=boundedRect(rect,viewport());
      Object.assign(dialog.style,{left:b.left+"px",top:b.top+"px",right:"auto",
        bottom:"auto",margin:"0"});
      if(resize||b.width!==rect.width)dialog.style.width=b.width+"px";
      if(resize||b.height!==rect.height)dialog.style.height=b.height+"px";
      options.onGeometry?.();
      return b;
    }
    function fit(){
      if(!dialog.open)return;
      if(savedRect){const v=viewport();place({left:8,top:8,width:v.width-16,height:v.height-16},true);}
      else place(dialog.getBoundingClientRect());
    }
    function endDrag(){
      if(drag&&handle.hasPointerCapture?.(drag.id))handle.releasePointerCapture(drag.id);
      drag=null;dialog.classList.remove("floating-dialog-moving");
    }
    function toggleExpanded(){
      if(!dialog.open)return;
      if(savedRect){const previous=savedRect;savedRect=null;place(previous,true);}
      else {const r=dialog.getBoundingClientRect();savedRect={left:r.left,top:r.top,width:r.width,height:r.height};fit();}
      dialog.classList.toggle("floating-dialog-expanded",!!savedRect);
      if(expand){expand.textContent=savedRect?"Przywróć okno":"Powiększ okno";
        expand.setAttribute("aria-pressed",String(!!savedRect));}
    }
    handle.addEventListener("pointerdown",ev=>{
      if(ev.button!==0||savedRect||ev.target.closest("button,input,select,textarea,a"))return;
      ev.preventDefault();const r=dialog.getBoundingClientRect();
      drag={id:ev.pointerId,x:ev.clientX,y:ev.clientY,left:r.left,top:r.top,width:r.width,height:r.height};
      handle.setPointerCapture?.(ev.pointerId);handle.focus({preventScroll:true});
      dialog.classList.add("floating-dialog-moving");
    });
    handle.addEventListener("pointermove",ev=>{
      if(!drag||ev.pointerId!==drag.id)return;
      ev.preventDefault();place({...drag,left:drag.left+ev.clientX-drag.x,top:drag.top+ev.clientY-drag.y});
    });
    for(const name of ["pointerup","pointercancel","lostpointercapture"])
      handle.addEventListener(name,ev=>{if(drag?.id===ev.pointerId)endDrag();});
    handle.addEventListener("keydown",ev=>{
      if(ev.target!==handle||savedRect||ev.ctrlKey||ev.altKey||ev.metaKey)return;
      const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[ev.key];
      if(!delta)return;
      ev.preventDefault();ev.stopPropagation();const r=dialog.getBoundingClientRect(),step=ev.shiftKey?1:20;
      place({left:r.left+delta[0]*step,top:r.top+delta[1]*step,width:r.width,height:r.height});
    });
    expand?.addEventListener("click",toggleExpanded);
    dialog.addEventListener("close",endDrag);
    owner.addEventListener("resize",fit);
    const observer=owner.ResizeObserver?new owner.ResizeObserver(()=>{
      if(!dialog.open)return;
      // CSS resize changes both the visible image and the reachable bounds.
      fit();
    }):null;
    observer?.observe(dialog);
    return {show(){if(!dialog.open)dialog.show();fit();},fit,toggleExpanded,
      close(){endDrag();if(dialog.open)dialog.close();},
      dispose(){endDrag();observer?.disconnect();owner.removeEventListener("resize",fit);}};
  }
  return {boundedRect,attach};
});
