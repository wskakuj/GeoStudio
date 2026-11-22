/* Sheet geometry uses the same logical units on the canvas and in print. */
window.GeoStudioSheet = (() => {
  const sizes={title:[370,142],credits:[290,170],compass:[106,106],symbols:[400,192],species:[410,263]};
  function defaultText(type,map){
    if(type==="title")return ["Mapa gospodarcza lasu","wsi "+map.replace(/\.map$/i,""),"gm. …   pow. …","woj. …","01.01.2027 – 31.12.2036","Stan na 30.06.2026"].join("\n");
    if(type==="credits")return ["Wykonawca","Agencja Cezar","Pracownia Urządzania Lasu","05-300 Mińsk Mazowiecki · ul. Boczna 28","Kierownik robót · mgr inż. Cezary Piotrkowicz","Taksatorzy · mgr Artur Kwiatkowski","Stanisław Olszewski","Wykreślił · Damian Zieliński"].join("\n");
    return "";
  }
  function shapes(item,scale){
    const elements=[],[w,h]=sizes[item.kind],ink="#202020";
    const label=(x,y,text,size,center=false)=>elements.push({text,x,y,size,center});
    const path=(points,fill=null,stroke=ink)=>elements.push({points,fill,stroke});
    const rect=(x,y,w,h,fill=null)=>path([[x,y],[x+w,y],[x+w,y+h],[x,y+h],[x,y]],fill);
    if(["title","credits"].includes(item.kind)){
      const lines=item.text.split("\n"),title=item.kind==="title";
      if(title){path([[1,1],[w-1,1]]);path([[1,h-1],[w-1,h-1]]);}
      const step=(h-12)/lines.length;
      lines.forEach((line,i)=>label(w/2,6+(i+.75)*step,line,Math.min(i===0&&title?23:i===1?18:12,step*.78, w*1.65/Math.max(1,line.length)),true));
    }else if(item.kind==="compass"){
      for(let i=0;i<4;i++){
        const rotate=(x,y)=>[[53+x,53+y],[53-y,53+x],[53-x,53-y],[53+y,53-x]][i];
        path([[0,0],[0,-34],[6,-6],[0,0]].map(p=>rotate(...p)),ink);
        path([[0,0],[0,-34],[-6,-6],[0,0]].map(p=>rotate(...p)));
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
  function paint(g,items,project,zoom,scale,selection){
    for(const item of items){
      const p=project(item.x,item.y),[w,h]=sizes[item.kind];
      const width=item.w*zoom,height=item.h*zoom;
      g.save();g.translate(p.x,p.y);g.scale(width/w,height/h);g.lineWidth=.65;
      for(const s of shapes(item,scale)){
        if(s.text!==undefined){g.fillStyle="#202020";g.font=s.size+"px Arial, sans-serif";g.textAlign=s.center?"center":"left";g.fillText(s.text,s.x,s.y);}
        else{g.beginPath();s.points.forEach(([x,y],i)=>i?g.lineTo(x,y):g.moveTo(x,y));if(s.fill){g.fillStyle=s.fill;g.fill();}if(s.stroke){g.strokeStyle=s.stroke;g.stroke();}}
      }
      g.restore();
      if(selection===item.id){
        g.save();g.strokeStyle="#2664db";g.strokeRect(p.x,p.y,width,height);g.fillStyle="#2664db";g.fillRect(p.x+width-5,p.y+height-5,10,10);g.restore();
      }
    }
  }
  return {sizes,defaultText,shapes,paint};
})();