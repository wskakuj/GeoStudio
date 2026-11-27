import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {handleAdmin} from "./admin.mjs";
globalThis.crypto ||= webcrypto;

const now=1770000000000,project="test-geostudio",owner="owner-id",target="user-id";
const a="a".repeat(64),b="b".repeat(64);
const env={PROJECT_ID:project,ADMIN_UID:owner,FIREBASE_WEB_API_KEY:"fake_web_api_key_for_tests"};
const jwt=(uid=owner,claims={})=>"header."+Buffer.from(JSON.stringify({
  sub:uid,aud:project,iss:"https://securetoken.google.com/"+project,
  exp:now/1000+3600,auth_time:now/1000-60,admin:uid===owner,...claims
})).toString("base64url")+".signature";
const req=(body,token=jwt())=>new Request("https://example.invalid/",{
  method:"POST",headers:{Authorization:"Bearer "+token,"Content-Type":"application/json"},
  body:JSON.stringify(body)
});
const fields={active:{booleanValue:true},expiresAt:{nullValue:null},
  deviceLimit:{integerValue:"2"},offlineHours:{integerValue:"72"},
  devices:{arrayValue:{values:[{stringValue:a}]}},name:{stringValue:"Test"},notes:{stringValue:""}};
const doc=(uid,f=fields)=>({name:"projects/"+project+"/databases/(default)/documents/geostudio_access/"+uid,
  updateTime:"2026-01-01T00:00:00.000000Z",fields:f});
const users=[
  {localId:owner,email:"owner@example.invalid",customAttributes:'{"admin":true}',validSince:String(now/1000-120)},
  {localId:target,email:"user@example.invalid",lastLoginAt:String(now-100000),passwordHash:"never_return_hash"}
];
function mock(opts={}){
  const calls=[],writes=[];
  let activityDoc=null;
  const fetcher=async(url,o={})=>{
    const u=new URL(url),method=o.method||"GET",payload=o.body?JSON.parse(o.body):undefined;
    calls.push({url:u,method,headers:o.headers,payload,redirect:o.redirect});
    assert.equal(o.redirect,"manual");
    const isUser=o.headers.Authorization!=="Bearer google-test";
    const path=u.pathname;
    if(isUser){
      if(opts.denyUser)return new Response(null,{status:403});
      if(opts.redirect)return new Response(null,{status:302,headers:{Location:"https://elsewhere.invalid/"}});
      return Response.json(doc(path.split("/").pop(),opts.ownFields||fields));
    }
    if(path.endsWith(":lookup")){
      const user=users.find(x=>x.localId===payload.localId[0]);
      const updated=user?.localId===owner?{...user,...opts.ownerChanges}:user;
      return Response.json({users:updated?[updated]:[]});
    }
    if(path.endsWith(":batchGet")){
      if(opts.pages&&!u.searchParams.get("nextPageToken"))
        return Response.json({users:[users[0]],nextPageToken:"next"});
      return Response.json({users:opts.pages?[users[1]]:users});
    }
    if(path.endsWith("/geostudio_access"))return Response.json({documents:users.map(x=>doc(x.localId))});
    if(path.endsWith("/geostudio_activity"))return Response.json({documents:[]});
    if(path.endsWith("/accounts")&&method==="POST")return Response.json({localId:"new-user",idToken:"never_return_token"});
    if(path.endsWith(":sendOobCode"))return opts.resetFail?new Response(null,{status:503}):Response.json({email:payload.email});
    if(path.endsWith(":delete"))return opts.deleteFail?new Response(null,{status:503}):Response.json({});
    if(path.endsWith(":commit"))return opts.cleanupFail?new Response(null,{status:503}):Response.json({});
    if(path.endsWith(":update"))return Response.json({});
    if(path.includes("/geostudio_activity/")){
      if(method==="GET")return activityDoc?Response.json(activityDoc):new Response(null,{status:404});
      writes.push({url:u,fields:payload.fields});
      activityDoc={fields:payload.fields,updateTime:"2026-01-01T00:00:00Z"};
      return Response.json(activityDoc);
    }
    if(path.includes("/geostudio_access/")){
      if(method==="GET")return Response.json(doc(path.split("/").pop()));
      writes.push({url:u,fields:payload.fields});
      if(opts.conflict)return new Response(null,{status:412});
      return Response.json(doc(path.split("/").pop(),payload.fields));
    }
    assert.fail("Unexpected Google request "+path);
  };
  return {calls,writes,fetcher,run:(body,token=jwt())=>handleAdmin(req(body,token),env,{
    fetcher,now,getToken:async()=>"google-test"
  })};
}
test("no admin action from a regular account or forged claim on a different UID",async()=>{
  const m=mock();
  for(const token of [jwt(target),jwt(target,{admin:true}),jwt(owner,{admin:false})]){
    const r=await m.run({action:"list"},token);
    assert.equal(r.status,403);
  }
  assert.equal(m.calls.length,0);
});
test("unsigned, redirected or inactive Firestore verification cannot reach privileged Google calls",async()=>{
  for(const options of [{denyUser:true},{redirect:true},{ownFields:{...fields,active:{booleanValue:false}}}]){
    const m=mock(options);
    const r=await m.run({action:"list"});
    assert.ok([403,503].includes(r.status));
    assert.equal(m.calls.length,1);
    assert.equal(m.writes.length,0);
  }
});
test("current admin claim and revocation timestamp are enforced on every operation",async()=>{
  for(const ownerChanges of [{customAttributes:"{}"},{disabled:true},{validSince:String(now/1000)}]){
    const m=mock({ownerChanges});
    const r=await m.run({action:"list"});
    assert.equal(r.status,403);
    assert.equal(m.calls.length,2);
  }
});
test("only owner sees sanitized paginated account list and statistics",async()=>{
  const m=mock({pages:true});
  const r=await m.run({action:"list"});
  assert.equal(r.status,200);
  const data=await r.json();
  assert.equal(data.rows.length,2);
  assert.equal(data.stats.active,2);
  assert.equal(data.stats.devices,2);
  assert.equal(data.rows.find(x=>x.uid===owner).owner,true);
  assert.ok(!JSON.stringify(data).includes("never_return_hash"));
  assert.ok(!JSON.stringify(data).includes("customAttributes"));
  assert.ok(m.calls.some(x=>x.url.searchParams.get("nextPageToken")==="next"));
});
const edit={action:"save",uid:target,version:"2026-01-01T00:00:00.000000Z",name:"Nowa nazwa",notes:"notatka",
  active:true,expiresAt:null,deviceLimit:2,offlineHours:72,removeDevices:[a]};
test("edits use preconditions and enforce owner protection and offline/device limit",async()=>{
  const m=mock();
  let r=await m.run(edit);
  assert.equal(r.status,200);
  assert.equal(m.writes[0].url.searchParams.get("currentDocument.updateTime"),edit.version);
  assert.deepEqual(m.writes[0].fields.devices.arrayValue.values,[]);
  for(const body of [{...edit,uid:owner,active:false},{...edit,uid:owner},{...edit,deviceLimit:0},
    {...edit,version:"stale"},{...edit,offlineHours:99}]){
    r=await m.run(body);
    assert.ok([400,403,409].includes(r.status));
  }
  assert.equal(m.writes.length,1);
  assert.equal((await mock({conflict:true}).run(edit)).status,409);
});
test("create never returns password or token; partial failures are explicit",async()=>{
  let m=mock();
  const r=await m.run({action:"create",email:"new@example.invalid",name:"Test",password:"initial-password-123",sendReset:true});
  assert.equal(r.status,200);
  const result=await r.json();
  assert.deepEqual(result,{ok:true,uid:"new-user"});
  assert.equal(m.writes[0].fields.deviceLimit.integerValue,"2");
  assert.equal(m.writes[0].url.searchParams.get("currentDocument.exists"),"false");
  assert.ok(m.calls.some(x=>x.url.pathname.endsWith(":sendOobCode")));
  m=mock({resetFail:true});
  assert.equal((await (await m.run({action:"create",email:"new@example.invalid",sendReset:true})).json()).partial,"reset_not_sent");
  m=mock({conflict:true});
  assert.equal((await (await m.run({action:"create",email:"new@example.invalid"})).json()).partial,"created_without_access");
});
test("delete requires exact email, forbids owner deletion and blocks before Auth deletion",async()=>{
  const m=mock();
  assert.equal((await m.run({action:"delete",uid:owner,confirmEmail:users[0].email})).status,403);
  assert.equal((await m.run({action:"delete",uid:target,confirmEmail:"wrong@example.invalid"})).status,400);
  const r=await m.run({action:"delete",uid:target,confirmEmail:users[1].email});
  assert.deepEqual(await r.json(),{ok:true});
  assert.equal(m.writes[0].fields.active.booleanValue,false);
  const block=m.calls.findIndex(x=>x.method==="PATCH");
  const del=m.calls.findIndex(x=>x.url.pathname.endsWith(":delete"));
  const cleanup=m.calls.findIndex(x=>x.url.pathname.endsWith(":commit"));
  assert.ok(block>=0&&block<del&&del<cleanup);
  const bad=mock({deleteFail:true});
  assert.equal((await (await bad.run({action:"delete",uid:target,confirmEmail:users[1].email})).json()).partial,"blocked_not_deleted");
  assert.ok(!bad.calls.some(x=>x.url.pathname.endsWith(":commit")));
});
test("activity only accepts the caller's registered device and bounds repeated writes",async()=>{
  const m=mock();
  const body={action:"activity",deviceId:a,name:"TEST-PC",kind:"login",uid:owner};
  assert.equal((await m.run(body,jwt(target))).status,200);
  assert.equal(m.writes.length,1);
  assert.ok(m.writes[0].url.pathname.endsWith("/geostudio_activity/"+target));
  const data=JSON.parse(m.writes[0].fields.data.stringValue);
  assert.equal(data.events[0].name,"TEST-PC");
  assert.equal(data.events[0].at,new Date(now).toISOString());
  assert.equal((await m.run({...body,deviceId:b},jwt(target))).status,403);
  assert.equal((await m.run(body,jwt(target))).status,200);
  assert.equal(m.writes.length,1);
  assert.ok(!m.calls.some(x=>x.url.pathname.endsWith(":lookup")));
});
test("admin password reset and device aliases target only specified real accounts",async()=>{
  const m=mock();
  assert.equal((await m.run({action:"reset",uid:target})).status,200);
  assert.equal(m.calls.find(x=>x.url.pathname.endsWith(":sendOobCode")).payload.email,users[1].email);
  assert.equal((await m.run({action:"rename_device",uid:target,deviceId:b,alias:"x"})).status,404);
  assert.equal((await m.run({action:"rename_device",uid:target,deviceId:a,alias:"Biuro"})).status,200);
  assert.equal(JSON.parse(m.writes[0].fields.data.stringValue).devices[0].alias,"Biuro");
});
