// UI-only fixture: intercept every wx.request; never grant or send production notifications.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const automator=require(path.resolve(__dirname,'../.runtime/devtools-automation/node_modules/miniprogram-automator'));
const timer=setTimeout(()=>{console.error('Push UI check timed out');process.exit(2);},45000);
async function until(read,predicate){for(let i=0;i<60;i++){const data=await read();if(predicate(data))return data;await new Promise(r=>setTimeout(r,150));}throw new Error('UI state did not settle');}
(async()=>{
 const mini=await automator.connect({wsEndpoint:'ws://127.0.0.1:9420'});
 const output=path.resolve(__dirname,'../.runtime/notifications/ui');fs.mkdirSync(output,{recursive:true});
 let original;
 try{
  original=await mini.evaluate(()=>({...getApp().globalData}));
  await mini.evaluate(()=>{
   const data=getApp().globalData;data.API_V2_BASE='https://policy-push-ui-fixture.invalid/api/v2';data.environment='trial';
   wx.setStorageSync('policy_v2_session:trial:'+data.API_V2_BASE,{access_token:'fixture-only'});
   getApp().pushFixtureCredits=0;
  });
  await mini.mockWxMethod('request',options=>{
   const pathname=options.url.split('/api/v2')[1].split('?')[0];
   const item={id:1,title:'关于加强医疗质量管理的通知',region:'CN',authority:'国家卫生健康委',published:'2026-11-18',type:'policy',topic:'医疗服务与质量安全'};
   const state=()=>({available:true,enabled:getApp().pushFixtureCredits>0,credits:getApp().pushFixtureCredits});
   let data;
   if(pathname==='/regions')data=[{code:'CN',name:'国家卫健委'}];
   else if(pathname==='/topics')data=['医疗服务与质量安全'];
   else if(pathname==='/me/follows')data=[{id:1,region:'CN',topic:'',include_national:true}];
   else if(pathname==='/me/push/prepare')data={grant_id:'fixture-01234567890123456789',template_id:'fixture-template',expires_at:Date.now()/1000+600};
   else if(pathname==='/me/push/confirm'){if(options.data.result==='accept')getApp().pushFixtureCredits++;data=state();}
   else if(pathname==='/me/push'){if(options.method==='DELETE')getApp().pushFixtureCredits=0;data=state();}
   else if(pathname.startsWith('/me/updates/'))data={date:'2026-11-18',total:1,items:[item]};
   else if(pathname==='/policies')data={total:1,items:[item]};
   else return {statusCode:404,data:{detail:'fixture_route_missing'}};
   return {statusCode:200,data};
  });
  await mini.mockWxMethod('requestSubscribeMessage',{'fixture-template':'accept'});
  await mini.reLaunch('/pages/follow/follow');let page=await mini.currentPage();
  await until(()=>page.data(),d=>d.pushGrant&&!d.busy);
  await mini.screenshot({path:path.join(output,'before.png')});
  await (await page.$('.push-card .app-button')).tap();
  let data=await until(()=>page.data(),d=>d.pushSaved&&!d.pushBusy);
  assert.equal(data.pushState.credits,1);assert.equal(data.pushError,'');
  await mini.screenshot({path:path.join(output,'enabled.png')});
  await (await page.$('.push-pause')).tap();
  data=await until(()=>page.data(),d=>!d.pushBusy&&!d.pushState.enabled);
  assert.equal(data.pushState.credits,0);
  await mini.navigateTo('/pages/updates/updates?id=0123456789abcdef0123456789abcdef');page=await mini.currentPage();
  data=await until(()=>page.data(),d=>!d.loading);
  assert.equal(data.total,1);assert.equal(data.documents[0].title,'关于加强医疗质量管理的通知');
  await mini.screenshot({path:path.join(output,'updates.png')});
  console.log(JSON.stringify({status:'passed',mode:'isolated UI fixture',checks:['follow authorization UI','accepted state','pause','notification landing page']}));
 }finally{
  await mini.restoreWxMethod('request');await mini.restoreWxMethod('requestSubscribeMessage');
  if(original)await mini.evaluate(value=>{const data=getApp().globalData;wx.removeStorageSync('policy_v2_session:trial:'+data.API_V2_BASE);Object.assign(data,value);delete getApp().pushFixtureCredits;},original);
  await mini.reLaunch('/pages/index/index');await mini.disconnect();clearTimeout(timer);
 }
})().catch(error=>{console.error(error.stack);clearTimeout(timer);process.exitCode=1;});
