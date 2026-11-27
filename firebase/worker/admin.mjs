// GeoStudio administration gateway. No service-account key in the desktop app.
// Set PROJECT_ID, ADMIN_UID, FIREBASE_WEB_API_KEY; GOOGLE_SERVICE_ACCOUNT_JSON
// is a Worker secret. Keep request/response logging disabled.
const enc = new TextEncoder();
const dec = new TextDecoder();
const validUid = x => typeof x === "string" && /^[^/\x00-\x1f]{1,128}$/.test(x) && x !== "." && x !== "..";
const validDevice = x => typeof x === "string" && /^[a-f0-9]{64}$/.test(x);
const iso = ms => new Date(ms).toISOString();
const response = (body,status=200) => Response.json(body,{status,headers:{
  "Cache-Control":"no-store","X-Content-Type-Options":"nosniff"
}});
class Failure extends Error {
  constructor(code,status=400) { super(code); this.code=code; this.status=status; }
}
const fail = (code,status=400) => { throw new Failure(code,status); };
const require = (condition,code="invalid_input",status=400) => { if (!condition) fail(code,status); };
const b64 = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");
const b64json = value => b64(enc.encode(JSON.stringify(value)));
function decodeClaims(token) {
  try {
    const parts=token.split(".");
    require(parts.length===3,"auth",401);
    const p=parts[1];
    require(/^[A-Za-z0-9_-]+$/.test(p),"auth",401);
    const raw=atob(p.replace(/-/g,"+").replace(/_/g,"/")+"=".repeat((4-p.length%4)%4));
    return JSON.parse(dec.decode(Uint8Array.from(raw,c=>c.charCodeAt(0))));
  } catch { fail("auth",401); }
}
async function bodyOf(request) {
  require(request.body && /application\/json/i.test(request.headers.get("content-type")||""),"invalid_input");
  const reader=request.body.getReader(), chunks=[];
  let size=0;
  for (;;) {
    const {done,value}=await reader.read();
    if (done) break;
    size+=value.byteLength;
    if (size>16384) { await reader.cancel(); fail("invalid_input",413); }
    chunks.push(value);
  }
  const bytes=new Uint8Array(size);
  let pos=0; for (const chunk of chunks) { bytes.set(chunk,pos); pos+=chunk.length; }
  try {
    const value=JSON.parse(dec.decode(bytes));
    require(value && typeof value==="object" && !Array.isArray(value));
    return value;
  } catch { fail("invalid_input"); }
}
const cleanText = (value,max) => {
  require(typeof value==="string" && value.length<=max && !/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value));
  return value.trim();
};
const emailOf = v => {
  const value=cleanText(v,254);
  require(/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value));
  return value;
};
const stringValue = x => ({stringValue:x});
const integerValue = x => ({integerValue:String(x)});
function readPolicy(doc) {
  if (!doc) return null;
  const f=doc.fields||{};
  const limit=Number(f.deviceLimit?.integerValue??0);
  const devices=(f.devices?.arrayValue?.values||[]).map(x=>x.stringValue);
  require(Number.isInteger(limit)&&limit>=0&&limit<=20&&Array.isArray(devices)
    &&devices.length<=20&&new Set(devices).size===devices.length&&devices.every(validDevice),"invalid_policy",409);
  const expiresAt=f.expiresAt?.timestampValue??null;
  require(Object.hasOwn(f.expiresAt||{},"nullValue") ||
    (typeof expiresAt==="string"&&Number.isFinite(Date.parse(expiresAt))),"invalid_policy",409);
  return {active:f.active?.booleanValue===true,expiresAt,deviceLimit:limit,devices,
    offlineHours:Number(f.offlineHours?.integerValue)===72?72:0,
    name:f.name?.stringValue||"",notes:f.notes?.stringValue||"",
    version:doc.updateTime||""};
}
function active(policy,now) {
  return !!policy && policy.active && (policy.expiresAt===null||Date.parse(policy.expiresAt)>now);
}
function makePolicy(old,input,email,isOwner=false) {
  const name=cleanText(input.name,160), notes=cleanText(input.notes,500);
  const limit=input.deviceLimit, offline=input.offlineHours, expires=input.expiresAt;
  require(typeof input.active==="boolean"&&Number.isInteger(limit)&&limit>=0&&limit<=20
    &&(offline===0||offline===72)&&(!offline||limit>0));
  require(expires===null||(typeof expires==="string"&&expires.length<=40
    &&/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,3})?Z$/.test(expires)
    &&Number.isFinite(Date.parse(expires))));
  const remove=input.removeDevices??[];
  require(Array.isArray(remove)&&remove.length<=20&&remove.every(validDevice));
  const devices=(old?.devices||[]).filter(d=>!remove.includes(d));
  require(!limit||devices.length<=limit,"device_limit");
  // Protect the sole administrator against accidentally locking out their account.
  require(!isOwner||(input.active&&expires===null&&remove.length===0),"owner_protected",403);
  return {email:stringValue(email),name:stringValue(name),notes:stringValue(notes),
    active:{booleanValue:input.active},expiresAt:expires===null?{nullValue:null}:{timestampValue:iso(Date.parse(expires))},
    deviceLimit:integerValue(limit),offlineHours:integerValue(offline),
    devices:{arrayValue:{values:devices.map(stringValue)}}};
}
async function google(fetcher,url,token,method="GET",payload,allowMissing=false) {
  // URLs are constructed only from the fixed Google endpoints and validated IDs.
  // Never follow redirects with credentials.
  let r;
  try {
    r=await fetcher(url,{method,redirect:"manual",headers:{Authorization:"Bearer "+token,
      Accept:"application/json",...(payload!==undefined?{"Content-Type":"application/json"}:{})},
      ...(payload!==undefined?{body:JSON.stringify(payload)}:{})});
  } catch { fail("upstream",503); }
  if (allowMissing&&r.status===404) return null;
  if (!r.ok) {
    if (r.status===429) fail("quota",429);
    if (r.status===409||r.status===412) fail("conflict",409);
    if (r.status===400) {
      // Only fixed codes leave this service. Do not return Google's response.
      let error={};
      try { error=(await r.json()).error||{}; } catch {}
      if (error.status==="FAILED_PRECONDITION"||error.status==="ABORTED") fail("conflict",409);
      if (error.message==="EMAIL_EXISTS") fail("email_exists",409);
      if (error.message==="USER_NOT_FOUND") fail("not_found",404);
      fail("invalid_google_request",400);
    }
    if (r.status===404) fail("not_found",404);
    fail("upstream",503);
  }
  try { return await r.json(); } catch { fail("upstream",503); }
}
// Cache only a completed short-lived access token, never a request-bound promise.
let oauthCache=null;
async function oauth(env,fetcher,now) {
  let key;
  try { key=JSON.parse(env.GOOGLE_SERVICE_ACCOUNT_JSON); } catch { fail("admin_config",503); }
  require(key?.type==="service_account"&&key.project_id===env.PROJECT_ID
    &&typeof key.client_email==="string"&&typeof key.private_key_id==="string"
    &&typeof key.private_key==="string","admin_config",503);
  const id=key.client_email+":"+key.private_key_id;
  if (oauthCache?.id===id&&oauthCache.until>now) return oauthCache.token;
  try {
    const der=Uint8Array.from(atob(key.private_key.replace(/-----BEGIN PRIVATE KEY-----|-----END PRIVATE KEY-----|\s/g,"")),c=>c.charCodeAt(0));
    const signingKey=await crypto.subtle.importKey("pkcs8",der,
      {name:"RSASSA-PKCS1-v1_5",hash:"SHA-256"},false,["sign"]);
    const sec=Math.floor(now/1000);
    const jwt=b64json({alg:"RS256",typ:"JWT",kid:key.private_key_id})+"."+b64json({
      iss:key.client_email,aud:"https://oauth2.googleapis.com/token",iat:sec,exp:sec+300,
      scope:"https://www.googleapis.com/auth/datastore https://www.googleapis.com/auth/identitytoolkit"
    });
    const signed=b64(new Uint8Array(await crypto.subtle.sign("RSASSA-PKCS1-v1_5",signingKey,enc.encode(jwt))));
    const r=await fetcher("https://oauth2.googleapis.com/token",{method:"POST",redirect:"manual",
      headers:{"Content-Type":"application/x-www-form-urlencoded"},
      body:new URLSearchParams({grant_type:"urn:ietf:params:oauth:grant-type:jwt-bearer",assertion:jwt+"."+signed}).toString()});
    if (!r.ok) fail("admin_config",503);
    const t=await r.json();
    require(typeof t.access_token==="string"&&Number(t.expires_in)>120,"admin_config",503);
    oauthCache={id,token:t.access_token,until:now+Math.min(Number(t.expires_in)-60,240)*1000};
    return oauthCache.token;
  } catch { fail("admin_config",503); }
}
function gateway(env,fetcher,token) {
  const project=encodeURIComponent(env.PROJECT_ID);
  const root="https://firestore.googleapis.com/v1/projects/"+project+"/databases/(default)/documents";
  const authRoot="https://identitytoolkit.googleapis.com/v1/projects/"+project+"/accounts";
  const get=(collection,uid,bearer=token)=>google(fetcher,root+"/"+collection+"/"+encodeURIComponent(uid),bearer,"GET",undefined,true);
  async function save(collection,uid,fields,old) {
    const query=new URLSearchParams();
    for (const field of Object.keys(fields)) query.append("updateMask.fieldPaths",field);
    if (old) {
      require(typeof old.updateTime==="string"&&old.updateTime,"conflict",409);
      query.set("currentDocument.updateTime",old.updateTime);
    } else query.set("currentDocument.exists","false");
    return google(fetcher,root+"/"+collection+"/"+encodeURIComponent(uid)+"?"+query,token,"PATCH",{fields});
  }
  async function user(uid) {
    const r=await google(fetcher,authRoot+":lookup",token,"POST",{localId:[uid]});
    const result=r.users?.find(u=>u.localId===uid);
    require(result,"not_found",404);
    return result;
  }
  async function pages(url,key,sizeParam) {
    let next="", all=[];
    for (let i=0;i<5;i++) {
      const q=new URLSearchParams({[sizeParam]:"100"});
      if(next) q.set(sizeParam==="maxResults"?"nextPageToken":"pageToken",next);
      const data=await google(fetcher,url+"?"+q,token);
      all.push(...(data[key]||[]));
      next=data.nextPageToken||"";
      if (!next) return {rows:all,truncated:false};
    }
    return {rows:all,truncated:true};
  }
  async function deleteDocs(uid) {
    const prefix="projects/"+env.PROJECT_ID+"/databases/(default)/documents/";
    return google(fetcher,root+":commit",token,"POST",{writes:[
      {delete:prefix+"geostudio_access/"+uid},{delete:prefix+"geostudio_activity/"+uid}
    ]});
  }
  return {get,save,user,pages,deleteDocs,auth:(suffix,method,payload,query="")=>
    google(fetcher,authRoot+suffix+query,token,method,payload),
    root,authRoot};
}
function dataOf(doc) {
  try {
    const v=JSON.parse(doc?.fields?.data?.stringValue||"{}");
    return {devices:Array.isArray(v.devices)?v.devices.filter(d=>validDevice(d.id)).slice(0,20):[],
      events:Array.isArray(v.events)?v.events.filter(e=>validDevice(e.deviceId)).slice(0,50):[],
      lastActive:typeof v.lastActive==="string"?v.lastActive:null};
  } catch { return {devices:[],events:[],lastActive:null}; }
}
function activityView(doc,now) {
  const d=dataOf(doc);
  const cutoff=now-30*86400000;
  return {...d,events:d.events.filter(e=>Date.parse(e.at)>=cutoff)};
}
function rowOf(user,policy,activity,now,ownerUid) {
  const lastLogin=Number(user.lastLoginAt);
  return {uid:user.localId,email:user.email||"",name:policy?.name||user.displayName||"",
    authDisabled:!!user.disabled,active:!user.disabled&&active(policy,now),
    owner:user.localId===ownerUid,policy,
    lastLogin:Number.isFinite(lastLogin)&&lastLogin>0?iso(lastLogin):null,
    lastActive:activity?.lastActive??null};
}
async function recordActivity(gw,uid,policy,body,now) {
  const device=body.deviceId;
  require(validDevice(device)&&(!policy.deviceLimit||policy.devices.includes(device)),"denied",403);
  const name=cleanText(body.name??"",80);
  const kind=body.kind;
  require(["login","start","heartbeat"].includes(kind));
  for (let attempt=0;attempt<3;attempt++) {
    const doc=await gw.get("geostudio_activity",uid);
    const data=activityView(doc,now);
    const existing=data.devices.find(d=>d.id===device);
    // Bound writes/history even when a client repeatedly calls this endpoint.
    if (Date.parse(data.lastActive)>now-60000 ||
      (kind==="heartbeat"&&existing&&Date.parse(existing.lastSeen)>now-600000)) return {ok:true};
    const current={id:device,name,lastSeen:iso(now),alias:existing?.alias||""};
    data.devices=[current,...data.devices.filter(d=>d.id!==device)].slice(0,20);
    data.lastActive=iso(now);
    if(kind!=="heartbeat")data.events=[{at:iso(now),kind,deviceId:device,name},...data.events].slice(0,50);
    try {
      await gw.save("geostudio_activity",uid,{data:stringValue(JSON.stringify(data))},doc);
      return {ok:true};
    } catch(e) { if(e.code!=="conflict"||attempt===2)throw e; }
  }
}
async function adminAction(gw,env,claims,body,now) {
  const action=body.action;
  if (action==="status") return {ok:true};
  if (action==="list") {
    const users=await gw.pages(gw.authRoot+":batchGet","users","maxResults");
    const policies=await gw.pages(gw.root+"/geostudio_access","documents","pageSize");
    const activity=await gw.pages(gw.root+"/geostudio_activity","documents","pageSize");
    const byId=rows=>new Map(rows.map(d=>[d.name.split("/").pop(),d]));
    const p=byId(policies.rows),a=byId(activity.rows);
    const rows=users.rows.filter(u=>validUid(u.localId)).map(u=>{
      let policy=null,policyError=false;
      try{policy=readPolicy(p.get(u.localId));}catch{policyError=true;}
      return {...rowOf(u,policy,dataOf(a.get(u.localId)),now,env.ADMIN_UID),policyError};
    }).sort((a,b)=>a.email.localeCompare(b.email));
    return {rows,truncated:users.truncated||policies.truncated||activity.truncated,
      stats:{total:rows.length,active:rows.filter(r=>r.active).length,
        blocked:rows.filter(r=>!r.active).length,
        devices:rows.reduce((n,r)=>n+(r.policy?.devices.length||0),0),
        recent:rows.filter(r=>r.active&&Date.parse(r.lastActive)>=now-20*60000).length}};
  }
  if(action==="create") {
    const email=emailOf(body.email);
    const password=body.password||b64(crypto.getRandomValues(new Uint8Array(32)));
    require(typeof password==="string"&&password.length>=12&&password.length<=128);
    require(typeof env.FIREBASE_WEB_API_KEY==="string"&&/^[A-Za-z0-9_-]{20,128}$/.test(env.FIREBASE_WEB_API_KEY),"admin_config",503);
    const fields=makePolicy(null,{name:body.name??"",notes:"",active:true,
      expiresAt:null,deviceLimit:2,offlineHours:0},email);
    const result=await gw.auth("","POST",{email,password,returnSecureToken:false},
      "?key="+encodeURIComponent(env.FIREBASE_WEB_API_KEY));
    require(validUid(result.localId),"upstream",503);
    try {
      await gw.save("geostudio_access",result.localId,fields,null);
    } catch { return {ok:false,partial:"created_without_access",uid:result.localId}; }
    if(body.sendReset===true) {
      try {await gw.auth(":sendOobCode","POST",{requestType:"PASSWORD_RESET",email,returnOobLink:false});}
      catch{return {ok:true,partial:"reset_not_sent",uid:result.localId};}
    }
    return {ok:true,uid:result.localId};
  }
  require(["details","save","rename_device","reset","delete"].includes(action),"invalid_action");
  const uid=body.uid;
  require(validUid(uid));
  const target=await gw.user(uid);
  const owner=uid===env.ADMIN_UID;
  if(action==="details"){
    const doc=await gw.get("geostudio_access",uid);
    const activity=activityView(await gw.get("geostudio_activity",uid),now);
    return {...rowOf(target,readPolicy(doc),activity,now,env.ADMIN_UID),activity};
  }
  if(action==="save"){
    const doc=await gw.get("geostudio_access",uid);
    const policy=readPolicy(doc);
    require((policy?.version||"")===(body.version||""),"conflict",409);
    const fields=makePolicy(policy,body,target.email||"",owner);
    const updated=await gw.save("geostudio_access",uid,fields,doc);
    if(target.disabled && body.active===true && body.enableAuth===true) {
      try { await gw.auth(":update","POST",{localId:uid,disableUser:false}); }
      catch { return {ok:true,partial:"auth_still_disabled",policy:readPolicy(updated)}; }
    }
    return {ok:true,policy:readPolicy(updated)};
  }
  if(action==="rename_device"){
    require(validDevice(body.deviceId));
    const alias=cleanText(body.alias,80);
    const policy=readPolicy(await gw.get("geostudio_access",uid));
    require(policy?.devices.includes(body.deviceId),"not_found",404);
    const doc=await gw.get("geostudio_activity",uid);
    const data=activityView(doc,now);
    const old=data.devices.find(d=>d.id===body.deviceId)||{id:body.deviceId,name:"",lastSeen:null};
    data.devices=[{...old,alias},...data.devices.filter(d=>d.id!==body.deviceId)].slice(0,20);
    await gw.save("geostudio_activity",uid,{data:stringValue(JSON.stringify(data))},doc);
    return {ok:true};
  }
  if(action==="reset"){
    require(!!target.email,"not_found",404);
    await gw.auth(":sendOobCode","POST",{requestType:"PASSWORD_RESET",email:target.email,returnOobLink:false});
    return {ok:true};
  }
  if(action==="delete"){
    require(!owner,"owner_protected",403);
    require(typeof target.email==="string"&&target.email&&body.confirmEmail===target.email,"confirm_delete",400);
    // Deny GeoStudio first. If Auth deletion fails the account remains blocked.
    const doc=await gw.get("geostudio_access",uid);
    if(doc) await gw.save("geostudio_access",uid,{active:{booleanValue:false}},doc);
    else await gw.save("geostudio_access",uid,makePolicy(null,{name:"",notes:"",active:false,
      expiresAt:null,deviceLimit:0,offlineHours:0},target.email),null);
    try { await gw.auth(":delete","POST",{localId:uid}); }
    catch { return {ok:false,partial:"blocked_not_deleted"}; }
    try { await gw.deleteDocs(uid); }
    catch { return {ok:true,partial:"cleanup_pending"}; }
    return {ok:true};
  }
  fail("invalid_action");
}

export async function handleAdmin(request,env,{fetcher=(url,options)=>fetch(url,options),now=Date.now(),getToken=oauth}={}) {
  if(request.method!=="POST")return response({error:"method"},405);
  try{
    require(/^[a-z][a-z0-9-]{4,28}[a-z0-9]$/.test(env.PROJECT_ID||"")&&validUid(env.ADMIN_UID),"admin_config",503);
    const header=request.headers.get("Authorization")||"";
    require(/^Bearer [A-Za-z0-9_.-]{1,16384}$/.test(header),"auth",401);
    const token=header.slice(7), c=decodeClaims(token);
    require(validUid(c.sub)&&c.aud===env.PROJECT_ID&&c.iss==="https://securetoken.google.com/"+env.PROJECT_ID
      &&Number.isInteger(c.exp)&&c.exp>now/1000&&Number.isInteger(c.auth_time)&&c.auth_time<=now/1000+120,"auth",401);
    const body=await bodyOf(request);
    const activity=body.action==="activity";
    // Decoded claims are a cheap rejection filter only. Firestore verifies
    // the actual token signature and access to the caller's own document.
    if(!activity)require(c.sub===env.ADMIN_UID&&c.admin===true,"denied",403);
    const ownUrl="https://firestore.googleapis.com/v1/projects/"+encodeURIComponent(env.PROJECT_ID)
      +"/databases/(default)/documents/geostudio_access/"+encodeURIComponent(c.sub);
    let own;
    try{
      const r=await fetcher(ownUrl,{headers:{Authorization:header,Accept:"application/json"},redirect:"manual"});
      if([401,403,404].includes(r.status))fail("denied",403);
      if(!r.ok)fail("upstream",503);
      own=readPolicy(await r.json());
    }catch(e){if(e instanceof Failure)throw e;fail("upstream",503);}
    require(active(own,now),"denied",403);
    if(activity)require(validDevice(body.deviceId)&&(!own.deviceLimit||own.devices.includes(body.deviceId)),"denied",403);
    const gw=gateway(env,fetcher,await getToken(env,fetcher,now));
    if(activity)return response(await recordActivity(gw,c.sub,own,body,now));
    // Check the *current* account/claim and revoked refresh-token timestamp
    // for every administrative request, not just the cached ID token.
    const user=await gw.user(c.sub);
    let current={};
    try{current=JSON.parse(user.customAttributes||"{}");}catch{}
    require(!user.disabled&&current?.admin===true
      &&Number.isFinite(Number(user.validSince??0))&&c.auth_time>=Number(user.validSince??0),"denied",403);
    return response(await adminAction(gw,env,c,body,now));
  }catch(e){
    // No raw exception text, URLs, password, OAuth token or Google responses.
    return e instanceof Failure?response({error:e.code},e.status):response({error:"unavailable"},503);
  }
}
export default {fetch:(request,env)=>handleAdmin(request,env)};
