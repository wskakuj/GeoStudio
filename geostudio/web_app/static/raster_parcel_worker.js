/* Dedicated whole-mesh 5216 fitting. The ordinary single-field workflow uses
 * the same helper synchronously; this worker preserves its global decisions
 * while leaving progress, pan and cancel responsive during a large batch. */
"use strict";
let parcelImportError="";
try{importScripts("/raster_parcel_snap.js");}
catch(_error){parcelImportError="Nie wczytano modułu dopasowania 5216. Uruchom program ponownie i ponów analizę.";}

self.onmessage=({data})=>{
  const id=data?.id;
  try{
    if(parcelImportError)throw Error(parcelImportError);
    const {rings,features,options}=data||{};
    if(!Number.isInteger(id)||!Array.isArray(rings)||!rings.length||
       rings.some(ring=>!Array.isArray(ring)||ring.length<3||ring.length>500||
         ring.some(p=>!Array.isArray(p)||p.length!==2||!p.every(Number.isFinite))))
      throw Error("Nieprawidłowa siatka obrysów. Ponów analizę całej mapy.");
    const MAX_SOURCE_VERTICES=50000;
    if(rings.reduce((sum,ring)=>sum+ring.length,0)>MAX_SOURCE_VERTICES)
      throw Error("Siatka źródłowa całego rastra przekracza 50 000 węzłów. Wybierz grubsze kontury lub mocniejsze prostowanie i przeanalizuj ponownie.");
    if(!Array.isArray(features)||!options||!Number.isFinite(options.distance)||
       options.distance<=0||options.distance>20||!Number.isFinite(options.precisionDistance)||
       options.precisionDistance<=0)
      throw Error("Nieprawidłowe ustawienia dopasowania 5216. Ponów analizę całej mapy.");
    const index=self.GeoStudioRasterParcelSnap.buildIndex(features);
    const results=self.GeoStudioRasterParcelSnap.snapRings(rings,index,{
      distance:options.distance,precisionDistance:options.precisionDistance});
    self.postMessage({id,results});
  }catch(error){
    const message=String(error.message||"");
    self.postMessage({id,error:/ponów|przeanalizuj/i.test(message)?message:
      "Nie udało się dopasować granic 5216. Ponów analizę całej mapy; przy złożonym rastrze wybierz grubsze kontury."});
  }
};
