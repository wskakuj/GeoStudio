import {after,before,beforeEach,test} from "node:test";
import {readFileSync} from "node:fs";
import {initializeTestEnvironment,assertFails,assertSucceeds} from "@firebase/rules-unit-testing";
import {doc,collection,getDoc,getDocs,setDoc,updateDoc,deleteDoc,Timestamp} from "firebase/firestore";

let env;
const a="a".repeat(64),b="b".repeat(64),c="c".repeat(64);
before(async()=>{
  if (!process.env.FIRESTORE_EMULATOR_HOST?.startsWith("127.0.0.1:"))
    throw Error("Run only against local emulator, never production");
  env=await initializeTestEnvironment({projectId:"demo-geostudio",firestore:{
    rules:readFileSync(new URL("../firestore.rules",import.meta.url),"utf8")}});
});
after(async()=>{if(env) await env.cleanup()});
beforeEach(async()=>{
  await env.clearFirestore();
  await env.withSecurityRulesDisabled(async context=>{
    const db=context.firestore();
    const ref=uid=>doc(db,"geostudio_access",uid);
    await setDoc(ref("alice"),{active:true,expiresAt:null,deviceLimit:2,devices:[a],offlineHours:0});
    await setDoc(ref("bob"),{active:false,expiresAt:null,deviceLimit:2,devices:[]});
    await setDoc(ref("expired"),{active:true,expiresAt:Timestamp.fromMillis(0),deviceLimit:2,devices:[]});
    await setDoc(ref("legacy"),{active:true,expiresAt:null});
  });
});
const own=uid=>doc(env.authenticatedContext(uid).firestore(),"geostudio_access",uid);
test("active owner can read, anonymous, cross-account, expired and blocked cannot",async()=>{
  await assertSucceeds(getDoc(own("alice")));
  await assertSucceeds(getDoc(own("legacy")));
  await assertFails(getDoc(own("bob")));
  await assertFails(getDoc(own("expired")));
  await assertFails(getDoc(doc(env.unauthenticatedContext().firestore(),"geostudio_access","alice")));
  await assertFails(getDoc(doc(env.authenticatedContext("bob").firestore(),"geostudio_access","alice")));
  await assertFails(getDocs(collection(env.authenticatedContext("alice").firestore(),"geostudio_access")));
});
test("client can register exactly one new device up to its cap",async()=>{
  const ref=own("alice");
  await assertFails(updateDoc(ref,{devices:[a,b,c]}));
  await assertFails(updateDoc(ref,{devices:[a,a]}));
  await assertFails(updateDoc(ref,{devices:[a,"invalid"]}));
  await assertFails(updateDoc(ref,{devices:[b]}));
  await assertSucceeds(updateDoc(ref,{devices:[a,b]}));
  await assertFails(updateDoc(ref,{devices:[a,b,c]}));
  await assertFails(updateDoc(ref,{devices:[a]}));
  await assertFails(updateDoc(ref,{devices:[a,c]}));
});
test("cannot modify grants, expiry, cap, offline policy or create an entitlement",async()=>{
  const ref=own("alice");
  await assertFails(updateDoc(ref,{active:false}));
  await assertFails(updateDoc(ref,{expiresAt:Timestamp.fromMillis(Date.now()+10000)}));
  await assertFails(updateDoc(ref,{deviceLimit:20}));
  await assertFails(updateDoc(ref,{offlineHours:72}));
  await assertFails(updateDoc(ref,{devices:[a,b],offlineHours:72}));
  await assertFails(updateDoc(own("bob"),{active:true,devices:[a]}));
  await assertFails(updateDoc(own("expired"),{devices:[a]}));
  await assertFails(updateDoc(own("legacy"),{devices:[a],deviceLimit:2}));
  await assertFails(setDoc(own("unknown"),{active:true,expiresAt:null}));
  await assertFails(deleteDoc(ref));
});

test("activity data cannot be read or changed by any client, even a claimed admin",async()=>{
  await env.withSecurityRulesDisabled(async context=>{
    await setDoc(doc(context.firestore(),"geostudio_activity","alice"),{data:"{}"});
  });
  for(const [uid,claims] of [["alice",{}],["bob",{}],["owner",{admin:true}]]){
    const db=env.authenticatedContext(uid,claims).firestore();
    const ref=doc(db,"geostudio_activity","alice");
    await assertFails(getDoc(ref));
    await assertFails(updateDoc(ref,{data:"fake"}));
    await assertFails(deleteDoc(ref));
    await assertFails(setDoc(doc(db,"geostudio_activity",uid),{data:"fake"}));
    await assertFails(getDocs(collection(db,"geostudio_activity")));
  }
});

test("invitation metadata, redemption history and settings are never client-accessible",async()=>{
  const id="a".repeat(64);
  await env.withSecurityRulesDisabled(async context=>{
    const db=context.firestore();
    await setDoc(doc(db,"geostudio_invites",id),{used:0});
    await setDoc(doc(db,"geostudio_invites",id,"redemptions","alice"),{used:true});
    await setDoc(doc(db,"geostudio_settings","registration"),{enabled:true});
  });
  for(const [uid,claims] of [["alice",{}],["owner",{admin:true}]]){
    const db=env.authenticatedContext(uid,claims).firestore();
    for(const ref of [doc(db,"geostudio_invites",id),
      doc(db,"geostudio_invites",id,"redemptions","alice"),
      doc(db,"geostudio_settings","registration")]){
      await assertFails(getDoc(ref));await assertFails(setDoc(ref,{enabled:true}));await assertFails(deleteDoc(ref));
    }
    await assertFails(getDocs(collection(db,"geostudio_invites")));
  }
});
