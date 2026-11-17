// Render isolated acceptance fixtures through the real API and WeChat runtime.
const assert=require('node:assert/strict'),path=require('node:path');
const automator=require(path.resolve(__dirname,'../.runtime/devtools-automation/node_modules/miniprogram-automator'));
const timeout=setTimeout(()=>{console.error('Summary UI verification timed out');process.exit(2);},90000);
async function until(read,test,label){const end=Date.now()+15000;while(Date.now()<end){const value=await read();if(test(value))return value;await new Promise(r=>setTimeout(r,150));}throw Error('Timed out: '+label);}
(async()=>{
 const mini=await automator.connect({wsEndpoint:'ws://127.0.0.1:9420'}),errors=[];
 mini.on('exception',e=>errors.push(e.message||JSON.stringify(e)));
 let original;
 try{
  original=await mini.evaluate(()=>getApp().globalData.API_V2_BASE);
  await mini.evaluate(()=>{getApp().globalData.API_V2_BASE='http://127.0.0.1:8893/api/v2';});
  const states=['ready','queued','generating','retrying','failed','waiting_content','insufficient_content'];
  for(let i=0;i<states.length;i++){
   await mini.reLaunch('/pages/detail/detail?id='+(i+1));
   const page=await until(()=>mini.currentPage(),p=>p&&p.path==='pages/detail/detail','detail route');
   const data=await until(()=>page.data(),d=>!d.loading&&d.doc&&d.doc.id===i+1,states[i]);
   assert.equal(data.summaryView.state,states[i]);assert.equal(data.loadError,false);
   if(i===0){
    assert.ok(data.summary[0].quote.includes('隔离测试'));
    const toggle=await page.$('.evidence-toggle');await toggle.tap();
    const evidence=await until(()=>page.$('.evidence-box'),Boolean,'expanded evidence');
    assert.ok((await evidence.text()).includes(data.summary[0].quote));
    await mini.screenshot({path:path.resolve(__dirname,'../.runtime/summary-evidence-fixture.png')});
    await toggle.tap();assert.equal((await page.data()).summary[0].expanded,false);
   }else{
    assert.equal(data.summary.length,0);assert.ok(data.summaryView.title);
    if(i===1){await page.callMethod('refreshSummary');await mini.screenshot({path:path.resolve(__dirname,'../.runtime/summary-queued-fixture.png')});}
   }
  }
  assert.deepEqual(errors,[]);console.log(JSON.stringify({result:'passed',fixture:'isolated synthetic API, no live AI calls',checks:states.concat('quote expand/collapse','refresh status')},null,2));
 }finally{
  if(original)await mini.evaluate(base=>{getApp().globalData.API_V2_BASE=base;},original);
  await mini.switchTab('/pages/index/index');await mini.disconnect();clearTimeout(timeout);
 }
})().catch(e=>{console.error(e.stack);clearTimeout(timeout);process.exitCode=1;});
