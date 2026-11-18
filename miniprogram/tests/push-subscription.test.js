const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const stored={};
let nativeCalled=false, nativeResult='accept', offline=false, calls=[], grantNumber=0;
const api={
 confirmV2Push(value){calls.push({...value});return offline?Promise.reject({statusCode:503}):Promise.resolve({available:true,enabled:value.result==='accept',credits:value.result==='accept'?1:0});},
 hasV2Session:()=>true,
 getV2Push:()=>Promise.resolve({available:true,enabled:true,credits:1}),
 prepareV2Push:()=>Promise.resolve({grant_id:'next-'+(++grantNumber),template_id:'template',expires_at:Date.now()/1000+600}),
 disableV2Push:()=>offline?Promise.reject({statusCode:503}):Promise.resolve({available:true,enabled:false,credits:0})
};
global.getApp=()=>({globalData:{environment:'trial',API_V2_BASE:'https://example.test'}});
global.wx={getStorageSync:key=>stored[key],setStorageSync:(key,value)=>stored[key]=value,removeStorageSync:key=>delete stored[key],
 requestSubscribeMessage(options){nativeCalled=true;options.success({[options.tmplIds[0]]:nativeResult});}};
const moduleValue={exports:{}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../utils/push-subscription.js'),'utf8'),{
 module:moduleValue,require:()=>api,wx:global.wx,getApp:global.getApp,Promise
});
const push=moduleValue.exports;
function follow(){
 let definition;
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../pages/follow/follow.js'),'utf8'),{
  Page:value=>definition=value,Date,wx:global.wx,
  require:spec=>spec.endsWith('/api')?api:spec.endsWith('/push-subscription')?push:{}
 });
 return {...definition,data:JSON.parse(JSON.stringify(definition.data)),setData(value){Object.assign(this.data,value);}};
}
(async()=>{
 const grant={grant_id:'grant-one',template_id:'template',expires_at:Date.now()/1000+600};
 let request=push.request(grant);
 assert.equal(nativeCalled,true,'native subscription call must happen synchronously inside the tap');
 let result=await request;
 assert.equal(result.status.credits,1);assert.equal(calls[0].mini_state,'trial');assert.equal(push.pending(),null);
 offline=true;nativeCalled=false;
 await assert.rejects(push.request(grant));assert.equal(push.pending().grant_id,'grant-one');
 offline=false;await push.syncPending();assert.equal(nativeCalled,true);assert.equal(push.pending(),null);
 assert.equal(calls.at(-1).grant_id,'grant-one','network recovery acknowledges the same grant');
 const page=follow();page.setData({rules:[{id:1}],pushGrant:grant});
 nativeResult='reject';await page.enablePush();
 assert.equal(page.data.pushSaved,false);assert.equal(page.data.pushState.enabled,false);
 assert.ok(page.data.pushGrant,'declining must not leave the subscribe button permanently disabled');
 nativeResult='accept';await page.enablePush();assert.equal(page.data.pushSaved,true);
 assert.equal(page.data.pushState.credits,1);
 offline=true;await page.disablePush();assert.equal(page.data.pushState.enabled,true);
 assert.ok(page.data.pushError.includes('失败'));
 offline=false;await page.disablePush();assert.equal(page.data.pushBusy,false);
 page.setData({pushGrant:{...grant,expires_at:0}});nativeCalled=false;await page.enablePush();
 assert.equal(nativeCalled,false,'expired grant refresh must not trigger a prompt after an await');
 console.log('Push consent: direct gesture, acknowledgement recovery, rejection, pause failure and expiry passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
