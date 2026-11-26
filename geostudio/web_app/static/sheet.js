/* Sheet geometry uses the same logical units on the canvas and in print. */
window.GeoStudioSheet = (() => {
  const sizes={title:[370,142],credits:[290,170],compass:[106,106],symbols:[400,192],species:[410,263]};
  const signs=["conifer","deciduous","clearcut","marsh","power","gas","boundary","path","shared"];
  for(const kind of signs)sizes[kind]=[48,16];
  sizes.compartment=[54,32];
  const normalAngle=value=>((Number(value)+180)%360+360)%360-180;
  function frame(item,project,zoom){
    const centre=project(item.x+item.w/2,item.y+item.h/2);
    const width=item.w*zoom,height=item.h*zoom,rad=Number(item.angle||0)*Math.PI/180;
    const ca=Math.cos(rad),sa=Math.sin(rad);
    const point=(x,y)=>({x:centre.x+x*ca-y*sa,y:centre.y+x*sa+y*ca});
    const local=p=>({x:(p.x-centre.x)*ca+(p.y-centre.y)*sa,
      y:-(p.x-centre.x)*sa+(p.y-centre.y)*ca});
    return {centre,width,height,point,local,
      corners:[point(-width/2,-height/2),point(width/2,-height/2),
        point(width/2,height/2),point(-width/2,height/2)],
      handle:point(0,-Math.max(28,Math.max(width,height)/2+22))};
  }
  function hit(item,p,project,zoom,padding=6){
    const box=frame(item,project,zoom),q=box.local(p);
    return Math.abs(q.x)<=box.width/2+padding&&Math.abs(q.y)<=box.height/2+padding;
  }
  function dragAngle(base,start,current,centre,snap=false){
    if(Math.hypot(current.x-centre.x,current.y-centre.y)<3)return normalAngle(base);
    const bearing=p=>Math.atan2(p.y-centre.y,p.x-centre.x)*180/Math.PI;
    const angle=Number(base||0)+normalAngle(bearing(current)-bearing(start));
    return normalAngle(snap?Math.round(angle/15)*15:Math.round(angle));
  }
  function resize(item,point,minimum=1){
    const box=frame(item,(x,y)=>({x,y}),1),a=box.corners[0],b=box.corners[2];
    const dx=b.x-a.x,dy=b.y-a.y;
    const factor=Math.max(minimum/Math.min(item.w,item.h),
      ((point.x-a.x)*dx+(point.y-a.y)*dy)/(dx*dx+dy*dy));
    const w=item.w*factor,h=item.h*factor;
    const centre={x:a.x+dx*factor/2,y:a.y+dy*factor/2};
    return {...item,x:centre.x-w/2,y:centre.y-h/2,w,h};
  }
  function paintSelection(g,item,project,zoom){
    const box=frame(item,project,zoom);
    g.save();g.strokeStyle="#2664db";g.lineWidth=1.5;
    g.beginPath();box.corners.forEach((p,i)=>i?g.lineTo(p.x,p.y):g.moveTo(p.x,p.y));
    g.closePath();g.stroke();g.fillStyle="#2664db";
    const corner=box.corners[2];g.fillRect(corner.x-5,corner.y-5,10,10);g.restore();
  }
  function defaultText(type,map){
    if(type==="compartment")return "1";
    if(type==="title")return ["Mapa gospodarcza lasu","wsi "+map.replace(/\.map$/i,""),"gm. …   pow. …","woj. …","01.01.2027 – 31.12.2036","Stan na 30.06.2026"].join("\n");
    if(type==="credits")return ["Wykonawca","Agencja Cezar","Pracownia Urządzania Lasu","05-300 Mińsk Mazowiecki · ul. Boczna 28","Kierownik robót · mgr inż. Cezary Piotrkowicz","Taksatorzy · mgr Artur Kwiatkowski","Stanisław Olszewski","Wykreślił · Damian Zieliński"].join("\n");
    return "";
  }
  // Geometria znaków 1:1 z serwerem (sheet_marks.primitives), żeby podgląd
  // przy kursorze pokazywał dokładnie to, co zostanie wpisane do MAP.
  const S=(pts,color,filled=false)=>[pts,color,filled];
  const signPaths={
    conifer:[S([[17,14],[22,2],[27,14]],"#24813b")],
    deciduous:[S([[22,15],[22,11],[18,10],[17,6],[19,2],[24,2],[27,6],[26,10],[22,11]],"#24813b")],
    clearcut:[S([[9,4],[23,4],[23,12],[9,12],[9,4]],"#111111",true),
              S([[23,12],[39,12]],"#111111")],
    marsh:[S([[2,3],[13,3]],"#497842"),S([[2,8],[13,8]],"#497842"),S([[2,13],[13,13]],"#497842"),
           S([[34,3],[45,3]],"#497842"),S([[34,8],[45,8]],"#497842"),S([[34,13],[45,13]],"#497842"),
           S([[15,6],[19,11],[23,6],[27,11],[31,6]],"#3874a0")],
    power:[S([[1,8],[47,8]],"#415c9b"),S([[13,4],[19,8],[13,12]],"#26334a"),
           S([[31,4],[37,8],[31,12]],"#26334a")],
    gas:[S([[1,4],[47,4],[47,12],[1,12],[1,4]],"#edce39",true),
         S([[13,4],[19,8],[13,12]],"#26334a"),S([[31,4],[37,8],[31,12]],"#26334a")],
    boundary:[S([[1,6],[47,6],[47,10],[1,10],[1,6]],"#ce2532",true)],
    path:[S([[1,8],[9,8]],"#444444"),S([[13,8],[21,8]],"#444444"),
          S([[25,8],[33,8]],"#444444"),S([[37,8],[45,8]],"#444444")],
    shared:[S([[1,1],[47,1],[47,15],[1,15],[1,1]],"#45bbbb",true)]
  };
  function signShapes(item){
    const paths=signPaths[item.kind];
    if(!paths)return [];
    // Punkty w przestrzeni 48x16 — paint() sam skaluje do rozmiaru elementu.
    // Wcześniej mnożyłem je tu dodatkowo przez item.w/48, przez co podgląd
    // był o ten czynnik za duży względem znaku wpisanego do MAP.
    return paths.map(([points,color,filled])=>({
      points:points.map(([u,v])=>[u,v]),
      fill:filled?color:null,stroke:color}));
  }
  function baseShapes(item,scale){
    const elements=[],[w,h]=sizes[item.kind],ink="#202020";
    const label=(x,y,text,size,center=false)=>elements.push({text,x,y,size,center});
    const path=(points,fill=null,stroke=ink)=>elements.push({points,fill,stroke});
    const rect=(x,y,w,h,fill=null)=>path([[x,y],[x+w,y],[x+w,y+h],[x,y+h],[x,y]],fill);
    // Znaki wstawione na mapę są już prawdziwą geometrią w MAP — rysujemy je
    // tylko w podglądzie, żeby nie dublować ich na ekranie.
    if(signs.includes(item.kind))return item.id==="__preview__"?signShapes(item):[];
    // Numer 6900: cyfra zajmuje niemal całe pudełko, więc zaznaczenie
    // („softbox") nie ma wokół siebie pustego kwadratu.
    if(item.kind==="compartment"){
      const size=Math.max(4,Math.min(w*1.4,h*.82));
      label(w/2,h*.5+size*.35,item.text,size,true);
    }
    else if(["title","credits"].includes(item.kind)){
      const lines=item.text.split("\n"),title=item.kind==="title";
      if(title){path([[1,1],[w-1,1]]);path([[1,h-1],[w-1,h-1]]);}
      const step=(h-12)/lines.length;
      lines.forEach((line,i)=>label(w/2,6+(i+.75)*step,line,Math.min(i===0&&title?23:i===1?18:12,step*.78, w*1.65/Math.max(1,line.length)),true));
    }else if(item.kind==="compass"){
      for(let i=0;i<4;i++){
        const rotate=(x,y)=>[[53+x,53+y],[53-y,53+x],[53-x,53-y],[53+y,53-x]][i];
        // Róża dwubarwna: czarna połowa i biała połowa Z WYPEŁNIENIEM,
        // obie o wspólnym wierzchołku. Wcześniej biała była tylko obrysem,
        // więc przy ostrym końcu linie się dublowały i grot się „rozwarstwiał".
        path([[0,0],[0,-34],[6,-6],[0,0]].map(p=>rotate(...p)),ink);
        path([[0,0],[0,-34],[-6,-6],[0,0]].map(p=>rotate(...p)),"#ffffff",ink);
        const [x,y]=rotate(0,-44);
        label(x,y+4,["N","E","S","W"][i],13,true);
      }
    }else if(item.kind==="symbols"){
      label(0,14,"Oznaczenia na mapie",16);
      const names=["Płazowina iglasta","Płazowina liściasta","Zrąb","Bagno","Linia energetyczna","Gazociąg","Granice od lasów innych własności","Ścieżki","Lasy we współwłasności z ALP z obowiązującym PUL"];
      names.forEach((name,i)=>{
        const y=30+19*i;
        label(58,y+4,name,11);
        if(i===0)path([[17,y+5],[22,y-6],[27,y+5]],null,"#24813b");
        if(i===1){path([[22,y+7],[22,y+2]],null,"#24813b");path([[17,y],[18,y-5],[22,y-7],[26,y-5],[27,y],[22,y+3],[17,y]],null,"#24813b");}
        if(i===2){rect(10,y-4,13,8,ink);path([[23,y+4],[39,y+4]]);}
        if(i===3){for(const x of [4,33])for(const dy of [-3,3])path([[x,y+dy],[x+9,y+dy]],null,"#497842");path([[14,y-2],[18,y+3],[22,y-2],[26,y+3],[30,y-2]],null,"#3874a0");}
        if(i===4||i===5){if(i===5)rect(2,y-3,44,6,"#edce39");else path([[2,y],[46,y]],null,"#415c9b");for(const x of [13,29])path([[x,y-3],[x+5,y],[x,y+3]]);}
        if(i===6)rect(2,y-2,44,4,"#ce2532");
        if(i===7)for(let x=2;x<45;x+=11)path([[x,y],[x+6,y]]);
        if(i===8)rect(2,y-5,44,10,"#45bbbb");
      });
    }else{
      label(0,14,"Wykaz znaków i kolorów",16);label(301,14,"Skala 1:"+scale,11);
      ["Halizny","I kl. wieku","Przedrębne","Rębne"].forEach((s,i)=>label(135+i*72,37,s,10,true));
      const rows=[["Sosna i modrzew","#c58a4d"],["Świerk","#8883b8"],["Dąb","#868686"],["Brzoza i akacja","#47b8bc"],["Olsza","#76ba76"],["Osika, lipa, wierzba i inne","#d59395"],["Jesion i wiąz","#5f9351"],["Grab","#d59b25"],["Topola","#ca8798"],["Klon i jawor","#789448"],["Buk","#c89726"],["Jodła","#3185ba"]];
      rows.forEach(([name,color],i)=>{
        const y=45+18*i;label(0,y+10,name,name.length>18?8:11);
        for(let c=0;c<4;c++){
          const rgb=[1,3,5].map(p=>parseInt(color.slice(p,p+2),16));
          const tint="#"+rgb.map(v=>Math.round(255-(255-v)*[.35,.35,.65,1][c]).toString(16).padStart(2,"0")).join("");
          rect(100+c*72,y,72,13,tint);
          if(c===0){const x=104;path([[x,y+3],[168,y+3],[168,y+10],[x,y+10],[x,y+3]],"#ffffff",null);}
        }
      });
    }
    return elements;
  }
  const families=["Arial","Times New Roman","Georgia","Verdana","Courier New","Calibri","Cambria","Tahoma","Trebuchet MS","Palatino Linotype","Garamond","Century Gothic","Franklin Gothic Medium","Book Antiqua"];
  const measure=document.createElement("canvas").getContext("2d");
  const fontSpec=s=>(s.italic?"italic ":"")+(s.bold?"bold ":"")+s.size+"px \""+(s.family||"Arial")+"\"";
  function textFor(item,scale){
    return baseShapes(item,scale).filter(s=>s.text!==undefined).map(s=>s.text).join("\n");
  }
  function shapes(item,scale){
    const base=baseShapes(item,scale);
    if(!item.runs?.length)return base;
    const result=[];
    let offset=0;
    for(const s of base){
      if(s.text===undefined){result.push(s);continue;}
      const start=offset,end=start+s.text.length;
      offset=end+1;
      let pos=start;
      const pieces=[];
      function add(to,style={}){
        if(to<=pos)return;
        const part={...s,...style,text:s.text.slice(pos-start,to-start),center:false};
        measure.font=fontSpec(part);
        pieces.push([part,measure.measureText(part.text).width]);pos=to;
      }
      for(const run of item.runs){
        if(run.end<=pos||run.start>=end)continue;
        add(Math.max(pos,run.start));
        add(Math.min(run.end,end),run.style);
      }
      add(end);
      let x=s.x-(s.center?pieces.reduce((n,p)=>n+p[1],0)/2:0);
      for(const [part,width] of pieces){result.push({...part,x});x+=width;}
    }
    return result;
  }
  function paint(g,items,project,zoom,scale,selection){
    for(const item of items){
      const p=project(item.x,item.y),[w,h]=sizes[item.kind];
      const width=item.w*zoom,height=item.h*zoom;
      g.save();g.translate(p.x,p.y);
      if(item.kind==="compartment"){
        // Numer 6900 rysujemy wprost w jego pudełku: rozmiar czcionki wynika
        // z wysokości pudełka, więc cyfra wypełnia je i NIE jest rozciągnięta.
        const px=Math.max(4,height*.78);
        if(item.angle){
          g.translate(width/2,height/2);g.rotate(Number(item.angle)*Math.PI/180);
          g.translate(-width/2,-height/2);
        }
        g.fillStyle="#202020";
        g.font="600 "+px.toFixed(2)+"px Arial, Helvetica, sans-serif";
        g.textAlign="center";g.textBaseline="middle";
        g.fillText(String(item.text||""),width/2,height/2);
        g.restore();
        if(selection===item.id)paintSelection(g,item,project,zoom);
        continue;
      }
      // Obrót w jednostkach ekranu PRZED skalowaniem osi. Tak samo jak
      // natywna geometria MAP, również dla znaku o innym stosunku boków.
      if(item.angle){
        g.translate(width/2,height/2);g.rotate(Number(item.angle)*Math.PI/180);
        g.translate(-width/2,-height/2);
      }
      g.scale(width/w,height/h);g.lineWidth=.65;
      for(const s of shapes(item,scale)){
        if(s.text!==undefined){g.fillStyle="#202020";g.font=fontSpec(s);g.textAlign=s.center?"center":"left";g.fillText(s.text,s.x,s.y);}
        else{g.beginPath();s.points.forEach(([x,y],i)=>i?g.lineTo(x,y):g.moveTo(x,y));if(s.fill){g.fillStyle=s.fill;g.fill();}if(s.stroke){g.strokeStyle=s.stroke;g.stroke();}}
      }
      g.restore();
      if(selection===item.id)paintSelection(g,item,project,zoom);
    }
  }
  return {sizes,signs,defaultText,shapes,paint,textFor,families,normalAngle,frame,hit,dragAngle,resize};
})();
