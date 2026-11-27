// GeoStudio offline permit signer. Store SIGNING_KEY_JWK as a Worker secret.
// No Firebase service account is needed: the caller's Firebase ID token is
// used solely to read the caller's entitlement under Firestore rules.
const enc = new TextEncoder();
const json = (body, status = 200) => Response.json(body, {
  status, headers: {"Cache-Control":"no-store", "X-Content-Type-Options":"nosniff"}
});
const b64 = bytes => btoa(String.fromCharCode(...bytes)).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");
function claims(token) {
  const part = token.split(".")[1];
  if (!part || !/^[A-Za-z0-9_-]+$/.test(part)) throw Error("token");
  const raw = atob(part.replace(/-/g,"+").replace(/_/g,"/") + "=".repeat((4-part.length%4)%4));
  return JSON.parse(new TextDecoder().decode(Uint8Array.from(raw,c=>c.charCodeAt(0))));
}

export async function issuePermit(request, env, fetcher=(url,options)=>fetch(url,options), now=Math.floor(Date.now()/1000)) {
  if (request.method !== "POST") return json({error:"method"},405);
  const authorization = request.headers.get("Authorization") || "";
  if (!/^Bearer [A-Za-z0-9_.-]{1,16384}$/.test(authorization)) return json({error:"auth"},401);
  let c, device;
  try {
    c = claims(authorization.slice(7));
    if (!request.body) return json({error:"body"},400);
    const reader = request.body.getReader();
    const parts = [];
    let size = 0;
    for (;;) {
      const {done,value} = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 512) { await reader.cancel(); return json({error:"body"},400); }
      parts.push(value);
    }
    const input = new Uint8Array(size);
    let offset = 0;
    for (const part of parts) { input.set(part,offset); offset += part.byteLength; }
    device = JSON.parse(new TextDecoder().decode(input)).deviceId;
    if (typeof c.sub !== "string" || !/^[^/\x00-\x1f]{1,128}$/.test(c.sub)
        || c.sub === "." || c.sub === ".."
        || c.aud !== env.PROJECT_ID || c.iss !== "https://securetoken.google.com/"+env.PROJECT_ID
        || !Number.isInteger(c.exp) || c.exp <= now
        || typeof device !== "string" || !/^[a-f0-9]{64}$/.test(device)) throw Error("invalid");
  } catch { return json({error:"auth"},401); }
  // Only fixed stage names leave the Worker; never expose exception messages,
  // Firebase credentials, the JWK, response bodies or a signed permit on error.
  let stage = "upstream";
  try {
    // Firestore validates the token (including signature and project) and
    // enforces active entitlement + expiry. Decoded claims alone grant nothing.
    const url = "https://firestore.googleapis.com/v1/projects/"+encodeURIComponent(env.PROJECT_ID)
      +"/databases/(default)/documents/geostudio_access/"+encodeURIComponent(c.sub);
    // Cloudflare Workers does not implement redirect:"error". Use manual
    // and reject every redirect, so the Firebase bearer token is never
    // forwarded to a redirect destination.
    const response = await fetcher(url, {headers:{Authorization:authorization,Accept:"application/json"},
      redirect:"manual"});
    if (response.status >= 300 && response.status < 400)
      return json({error:"upstream"},503);
    if (response.status === 401 || response.status === 403 || response.status === 404)
      return json({error:"denied"},403);
    if (!response.ok) return json({error:"upstream"},503);
    stage = "firestore_response";
    const f = (await response.json()).fields;
    const cap = Number(f.deviceLimit?.integerValue ?? 0);
    const hours = Number(f.offlineHours?.integerValue);
    const devices = (f.devices?.arrayValue?.values || []).map(x=>x.stringValue);
    if (f.active?.booleanValue !== true || ![72,-1].includes(hours)
        || !Number.isInteger(cap) || cap < 0 || cap > 20
        || (cap>0 && (devices.length > cap || new Set(devices).size !== devices.length
          || !devices.includes(device) || devices.some(d=>typeof d!=="string"||!/^[a-f0-9]{64}$/.test(d)))))
      return json({error:"denied"},403);
    let accountExp = null;
    if (!Object.hasOwn(f.expiresAt || {}, "nullValue")) {
      accountExp = Math.floor(Date.parse(f.expiresAt?.timestampValue)/1000);
      if (!Number.isInteger(accountExp) || accountExp <= now) return json({error:"expired"},403);
    }
    const exp = hours===72 ? Math.min(now+72*3600, accountExp ?? Infinity) : accountExp;
    // Keep original capped 72 h permits byte-compatible for previous clients.
    // Other policies require a V2-aware client; old clients fail closed.
    const version = hours===72 && cap>0 ? 1 : 2;
    const payload = enc.encode(JSON.stringify({
      v:version,project:env.PROJECT_ID,uid:c.sub,device,
      email:typeof c.email==="string"?c.email.slice(0,320):"",
      iat:now,exp,accountExp,deviceLimit:cap,deviceCount:cap>0?devices.length:0,
      ...(version===2?{offlineHours:hours}:{})
    }));
    if (typeof env.SIGNING_KEY_JWK !== "string" || !env.SIGNING_KEY_JWK.trim())
      return json({error:"key_missing"},503);
    stage = "key_json";
    const jwk = JSON.parse(env.SIGNING_KEY_JWK.trim());
    stage = "key_import";
    const key = await crypto.subtle.importKey("jwk",jwk,
      {name:"ECDSA",namedCurve:"P-256"},false,["sign"]);
    stage = "key_sign";
    const signature = new Uint8Array(await crypto.subtle.sign({name:"ECDSA",hash:"SHA-256"},key,payload));
    if (signature.length !== 64) return json({error:"signer"},503);
    return json({lease:b64(payload)+"."+b64(signature)});
  } catch { return json({error:stage},503); }
}
export default {fetch: (request, env) => issuePermit(request, env)};
