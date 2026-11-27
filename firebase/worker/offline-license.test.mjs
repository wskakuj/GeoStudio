import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {issuePermit} from "./offline-license.mjs";
globalThis.crypto ||= webcrypto;
const now = 1770000000;
const project = "test-geostudio";
const device = "a".repeat(64);
const key = await crypto.subtle.generateKey({name:"ECDSA",namedCurve:"P-256"},true,["sign","verify"]);
const env = {PROJECT_ID:project, SIGNING_KEY_JWK:JSON.stringify(await crypto.subtle.exportKey("jwk",key.privateKey))};
const b64 = obj=>Buffer.from(JSON.stringify(obj)).toString("base64url");
const token = "header."+b64({sub:"tester",aud:project,iss:"https://securetoken.google.com/"+project,
  exp:now+3600,email:"tester@example.invalid"})+".signature";
function req(id=device) {
  return new Request("https://example.invalid/lease",{method:"POST",
    headers:{Authorization:"Bearer "+token},body:JSON.stringify({deviceId:id})});
}
const fields = {active:{booleanValue:true},expiresAt:{nullValue:null},
  offlineHours:{integerValue:"72"},deviceLimit:{integerValue:"2"},
  devices:{arrayValue:{values:[{stringValue:device}]}}};
test("worker signs only an authorized registered device and bounds expiry", async()=>{
  const expiry=now+3600;
  const response=await issuePermit(req(),env,async(url,options)=>{
    assert.match(url,/geostudio_access\/tester$/);
    assert.equal(options.headers.Authorization,"Bearer "+token);
    return Response.json({fields:{...fields,expiresAt:{timestampValue:new Date(expiry*1000).toISOString()}}});
  },now);
  assert.equal(response.status,200);
  const [payload,signature]=(await response.json()).lease.split(".");
  const raw=Buffer.from(payload,"base64url"), sig=Buffer.from(signature,"base64url");
  assert.equal(sig.length,64);
  assert.equal(await crypto.subtle.verify({name:"ECDSA",hash:"SHA-256"},key.publicKey,sig,raw),true);
  assert.deepEqual(JSON.parse(raw),{v:1,project,uid:"tester",device,email:"tester@example.invalid",
    iat:now,exp:expiry,accountExp:expiry,deviceLimit:2,deviceCount:1});
});
test("worker refuses unavailable or denied Firebase and no offline policy", async()=>{
  assert.equal((await issuePermit(req(),env,async()=>new Response(null,{status:403}),now)).status,403);
  assert.equal((await issuePermit(req(),env,async()=>new Response(null,{status:500}),now)).status,503);
  assert.equal((await issuePermit(req("b".repeat(64)),env,async()=>Response.json({fields}),now)).status,403);
  assert.equal((await issuePermit(req(),env,async()=>Response.json({fields:{...fields,offlineHours:{integerValue:"0"}}}),now)).status,403);
});
test("never trusts decoded token without a successful Firestore read",async()=>{
  let called=false;
  const result=await issuePermit(req(),env,async()=>{called=true;return new Response(null,{status:401})},now);
  assert.equal(called,true);
  assert.equal(result.status,403);
  assert.equal((await result.json()).lease,undefined);
});
