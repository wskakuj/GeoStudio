import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {handleAdmin} from "./admin.mjs";
globalThis.crypto ||= webcrypto;

const now=1770000000000,project="test-geostudio",owner="owner-id",prefix="projects/"+project+"/databases/(default)/documents/";
const env={PROJECT_ID:project,ADMIN_UID:owner,FIREBASE_WEB_API_KEY:"fake_web_api_key_for_tests"};
const jwt=(uid=owner,extra={})=>"header."+Buffer.from(JSON.stringify({
  sub:uid,aud:project,iss:"https://securetoken.google.com/"+project,
  exp:now/1000+3600,auth_time:now/1000-60,admin:uid===owner,
  email:uid+"@example.invalid",email_verified:true,...extra
})).toString("base64url")+".signature";
const decode=token=>JSON.parse(Buffer.from(token.split(".")[1],"base64url"));
const ownerFields={active:{booleanValue:true},expiresAt:{nullValue:null},
  deviceLimit:{integerValue:"0"},offlineHours:{integerValue:"0"},devices:{arrayValue:{values:[]}}};
const template={action:"invite_create",label:"Test",email:"",maxUses:1,validDays:7,
  accountDays:30,deviceLimit:0,offlineHours:-1,approval:false};
const copy=o=>structuredClone(o);
function fixture(options={}){
  const db=new Map(),calls=[];
  let serial=0;
  const stamp=()=>new Date(now+serial++).toISOString();
  const put=(path,fields)=>db.set(path,{name:prefix+path,updateTime:stamp(),fields:copy(fields)});
  put("geostudio_access/"+owner,ownerFields);
  const credentials=new Map([[owner,{localId:owner,email:owner+"@example.invalid",
    emailVerified:true,customAttributes:'{"admin":true}'}]]);
  for(const uid of ["alice","bob","charlie"])credentials.set(uid,{localId:uid,
    email:uid+"@example.invalid",emailVerified:true});
  let beforeCommit=options.beforeCommit||null;
  const fetcher=async(url,o={})=>{
    const u=new URL(url),method=o.method||"GET",payload=o.body?JSON.parse(o.body):undefined;
    calls.push({url,method,payload});
    assert.equal(o.redirect,"manual");
    if(u.hostname==="identitytoolkit.googleapis.com"){
      if(u.pathname==="/v1/accounts:lookup"){
        if(options.badToken)return new Response(null,{status:400});
        const c=decode(payload.idToken),record=credentials.get(c.sub);
        return Response.json({users:record?[record]:[]});
      }
      if(u.pathname.endsWith(":lookup")){
        const record=credentials.get(payload.localId[0]);
        return Response.json({users:record?[record]:[]});
      }
      assert.fail("unexpected identity operation");
    }
    assert.equal(u.hostname,"firestore.googleapis.com");
    const path=u.pathname.split("/documents")[1].replace(/^\//,"");
    if(o.headers.Authorization!=="Bearer google-test"){
      assert.equal(path,"geostudio_access/"+owner);
      return Response.json(db.get(path));
    }
    if(path===":commit"){
      if(beforeCommit){const fn=beforeCommit;beforeCommit=null;await fn(db,put);}
      const writes=payload.writes;
      for(const w of writes){
        const p=w.update.name.slice(prefix.length),old=db.get(p),pre=w.currentDocument;
        if(pre.exists===false?!!old:!old||old.updateTime!==pre.updateTime)
          return new Response(null,{status:409});
      }
      for(const w of writes){
        const p=w.update.name.slice(prefix.length),old=db.get(p);
        put(p,{...old?.fields,...w.update.fields});
      }
      return Response.json({commitTime:stamp()});
    }
    if(method==="PATCH"){
      const old=db.get(path);
      if(u.searchParams.get("currentDocument.exists")==="false"&&old||
        u.searchParams.has("currentDocument.updateTime")&&u.searchParams.get("currentDocument.updateTime")!==old?.updateTime)
        return new Response(null,{status:409});
      put(path,{...old?.fields,...payload.fields});
      return Response.json(db.get(path));
    }
    if(method==="GET"){
      if(db.has(path))return Response.json(db.get(path));
      // Collection listings have an odd number of path segments.
      if(path.split("/").length%2===1){
        const rows=[...db.entries()].filter(([p])=>p.startsWith(path+"/")&&p.split("/").length===path.split("/").length+1).map(([,d])=>d);
        return Response.json({documents:rows});
      }
      return new Response(null,{status:404});
    }
    assert.fail("unexpected Firestore operation "+method);
  };
  const send=(path,body,token,extraEnv={})=>handleAdmin(new Request("https://example.invalid"+path,{
    method:"POST",headers:{"Content-Type":"application/json",...(token?{Authorization:"Bearer "+token}:{})},
    body:JSON.stringify(body)
  }),{...env,...extraEnv},{fetcher,now,getToken:async()=>"google-test"});
  const admin=(body,uid=owner)=>send("/",body,jwt(uid));
  const register=(body,uid,extra={},extraEnv={})=>send("/registration",body,uid?jwt(uid,extra):null,extraEnv);
  return {db,put,credentials,calls,admin,register,
    async enable(){assert.equal((await admin({action:"invite_settings",enabled:true})).status,200);},
    async create(overrides={}){
      const res=await admin({...template,...overrides});
      assert.equal(res.status,200);
      return res.json();
    }};
}
test("owner generates strong one-time-visible codes; non-admin cannot create/list",async()=>{
  const f=fixture();
  assert.equal((await f.admin(template,"alice")).status,403);
  const {code,id}=await f.create();
  assert.match(code,/^GS-(?:[A-F0-9]{4}-){7}[A-F0-9]{4}$/);
  assert.match(id,/^[a-f0-9]{64}$/);
  const stored=f.db.get("geostudio_invites/"+id);
  assert.ok(!JSON.stringify(stored).includes(code));
  assert.equal(stored.fields.used.integerValue,"0");
  assert.notEqual((await f.create()).code,code);
  const res=await f.admin({action:"invites_list"});
  const data=await res.json();
  assert.equal(data.enabled,false);
  assert.equal(data.rows.length,2);
  assert.ok(!JSON.stringify(data).includes(code));
  assert.equal((await f.admin({...template,email:"alice@example.invalid",maxUses:0})).status,400);
});
test("registration is closed by default, invalid/revoked/expired/wrong recipient codes fail",async()=>{
  const f=fixture();
  const {code,id}=await f.create({email:"alice@example.invalid"});
  const check=(email,c=code)=>f.register({action:"invite_check",email,code:c});
  assert.equal((await check("alice@example.invalid")).status,403);
  await f.enable();
  assert.equal((await check("alice@example.invalid")).status,200);
  assert.equal((await check("bob@example.invalid")).status,400);
  assert.equal((await check("alice@example.invalid","GS-bad")).status,400);
  assert.equal((await check("alice@example.invalid","GS-"+"F".repeat(32))).status,400);
  assert.equal((await f.admin({action:"invite_revoke",id})).status,200);
  assert.equal((await check("alice@example.invalid")).status,400);
  const expired=await f.create();
  const path="geostudio_invites/"+expired.id,fields=f.db.get(path).fields;
  f.put(path,{...fields,expiresAt:{timestampValue:new Date(now-1).toISOString()}});
  assert.equal((await check("alice@example.invalid",expired.code)).status,400);
});
test("redemption verifies Firebase token and real verified email, never trusts claimed recipient",async()=>{
  const f=fixture();
  await f.enable();
  const {code,id}=await f.create({email:"alice@example.invalid"});
  const body={action:"invite_redeem",code,email:"alice@example.invalid"};
  assert.equal((await f.register(body)).status,401);
  assert.equal((await f.register(body,"bob")).status,400);
  f.credentials.get("alice").emailVerified=false;
  assert.equal((await f.register(body,"alice")).status,403);
  f.credentials.get("alice").emailVerified=true;
  assert.equal((await f.register(body,"alice",{email_verified:false})).status,403);
  assert.equal((await f.register(body,"alice",{email:"other@example.invalid"})).status,401);
  assert.equal(f.db.get("geostudio_invites/"+id).fields.used.integerValue,"0");
  assert.equal(f.db.has("geostudio_access/alice"),false);
  const forged=fixture({badToken:true});
  assert.equal((await forged.register(body,"alice")).status,401);
});
test("verified redemption applies invitation policy once; existing accounts cannot escalate",async()=>{
  const f=fixture();await f.enable();
  const {code,id}=await f.create({approval:true});
  const body={action:"invite_redeem",code};
  const r=await f.register(body,"alice");
  assert.equal(r.status,200);
  assert.deepEqual(await r.json(),{ok:true,pending:true,active:false});
  const p=f.db.get("geostudio_access/alice").fields;
  assert.equal(p.active.booleanValue,false);
  assert.equal(p.pendingApproval.booleanValue,true);
  assert.equal(p.deviceLimit.integerValue,"0");
  assert.equal(p.offlineHours.integerValue,"-1");
  assert.equal(p.expiresAt.timestampValue,new Date(now+30*86400000).toISOString());
  assert.equal(f.db.get("geostudio_invites/"+id).fields.used.integerValue,"1");
  const history=await f.admin({action:"invite_history",id});
  assert.deepEqual((await history.json()).rows,[{uid:"alice",at:new Date(now).toISOString(),approval:true}]);
  assert.equal((await f.register(body,"bob")).status,400);
  assert.equal((await f.register(body,"alice")).status,200);
  assert.equal(f.db.get("geostudio_invites/"+id).fields.used.integerValue,"1");
  const second=await f.create();
  assert.equal((await f.register({action:"invite_redeem",code:second.code},"alice")).status,409);
  assert.equal((await f.register({action:"invite_redeem",code:second.code},"owner-id")).status,409);
  assert.equal((await (await f.register({action:"invite_status"},"alice")).json()).pending,true);
  const version=f.db.get("geostudio_access/alice").updateTime;
  const approval=await f.admin({action:"save",uid:"alice",version,name:"Alice",notes:"",
    active:true,expiresAt:p.expiresAt.timestampValue,deviceLimit:0,offlineHours:-1,removeDevices:[]});
  assert.equal(approval.status,200);
  assert.equal(f.db.get("geostudio_access/alice").fields.pendingApproval.booleanValue,false);
});
test("one-time code is consumed atomically under concurrent redemptions",async()=>{
  const f=fixture();await f.enable();
  const {code,id}=await f.create();
  const responses=await Promise.all(["alice","bob"].map(uid=>f.register({action:"invite_redeem",code},uid)));
  assert.deepEqual(responses.map(r=>r.status).sort(),[200,400]);
  assert.equal(f.db.get("geostudio_invites/"+id).fields.used.integerValue,"1");
  assert.equal(["alice","bob"].filter(uid=>f.db.has("geostudio_access/"+uid)).length,1);
});
test("concurrent revocation or registration closure stops a stale redemption",async()=>{
  for(const type of ["revoke","close"]){
    const f=fixture({beforeCommit:(db,put)=>{
      if(type==="close")put("geostudio_settings/registration",{enabled:{booleanValue:false}});
      else{
        const [path,doc]=[...db.entries()].find(([p])=>p.startsWith("geostudio_invites/"));
        put(path,{...doc.fields,revoked:{booleanValue:true}});
      }
    }});
    await f.enable();const {code,id}=await f.create();
    const res=await f.register({action:"invite_redeem",code},"alice");
    assert.ok([400,403].includes(res.status));
    assert.equal(f.db.has("geostudio_access/alice"),false);
    assert.equal(f.db.get("geostudio_invites/"+id).fields.used.integerValue,"0");
  }
});
test("optional edge rate limiting rejects before reading privileged Firestore; public path has closed allowlist",async()=>{
  const f=fixture();await f.enable();const {code}=await f.create();
  const before=f.calls.length;
  const res=await f.register({action:"invite_check",email:"alice@example.invalid",code},null,{},
    {REGISTRATION_RATE_LIMITER:{limit:async()=>({success:false})}});
  assert.equal(res.status,429);
  assert.equal(f.calls.length,before);
  assert.equal((await f.register({action:"invites_list"},"owner-id")).status,400);
});
