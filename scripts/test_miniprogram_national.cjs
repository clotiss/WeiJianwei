// End-to-end check against the persistent national service and actual WeChat runtime.
const assert=require('node:assert/strict'),path=require('node:path');
const automator=require(process.env.MINIPROGRAM_AUTOMATOR_PATH || path.resolve(__dirname,'../.runtime/devtools-automation/node_modules/miniprogram-automator'));
const timer=setTimeout(()=>{console.error('National UI verification timed out');process.exit(2);},120000);
async function until(read,test,label){const end=Date.now()+15000;while(Date.now()<end){const value=await read();if(test(value))return value;await new Promise(r=>setTimeout(r,150));}throw Error('Timed out: '+label);}
(async()=>{
 const mini=await automator.connect({wsEndpoint:process.env.MINIPROGRAM_AUTOMATOR_WS || 'ws://127.0.0.1:9420'}),errors=[];
 mini.on('exception',e=>errors.push(e.message||JSON.stringify(e)));
 try{
  await mini.reLaunch('/pages/index/index');
  const home=await until(()=>mini.currentPage(),p=>p&&p.path==='pages/index/index','home');
  let data=await until(()=>home.data(),d=>!d.loading&&d.regions.length===32,'default loaded');
  assert.equal(data.activeRegion,'CN');assert.equal(data.regions[0].name,'国家卫健委');
  assert.ok(!data.regions.some(r=>!r.code||r.name==='全国'));
  assert.ok(data.documents.length&&data.documents.every(d=>d.region==='CN'));
  const counts={};
  for(const region of data.regions){
   await home.callMethod('resetFilters',{activeRegion:region.code,regionIndex:data.regions.findIndex(r=>r.code===region.code),includeNational:false,activeCategory:'全部',activeType:'全部类型',days:0});
   const result=await until(()=>home.data(),d=>!d.loading&&d.activeRegion===region.code,region.code);
   assert.equal(result.loadError,false);
   if(['HE','SD','QH'].includes(region.code)){
    assert.equal(result.total,0);assert.equal(result.contentStatus.state,'not_connected');
    const title=await home.$('.empty-title');assert.equal(await title.text(),'该地区来源尚未接通');
    if(region.code==='HE')await mini.screenshot({path:path.resolve(__dirname,'../.runtime/national-unconnected-actual.png')});
   }else{assert.ok(result.total>0,region.code+' must contain imported documents');assert.ok(result.documents.every(d=>d.region===region.code));counts[region.code]=result.total;}
  }
  await home.callMethod('resetFilters',{activeRegion:'CN',regionIndex:0,days:0});
  await until(()=>home.data(),d=>!d.loading,'national restored');
  await mini.screenshot({path:path.resolve(__dirname,'../.runtime/national-home-actual.png')});
  await home.callMethod('goCoverage');
  const coverage=await until(()=>mini.currentPage(),p=>p&&p.path==='pages/coverage/coverage','coverage');
  const state=await until(()=>coverage.data(),d=>!d.loading,'coverage loaded');
  assert.equal(state.enabledCount,58);assert.equal(state.sources.length,64);
  assert.equal(state.sources.filter(s=>s.documents>0).length,58);
  await mini.screenshot({path:path.resolve(__dirname,'../.runtime/national-coverage-actual.png')});
  await mini.switchTab('/pages/index/index');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({result:'passed',default:'CN',regionsWithData:Object.keys(counts).length,counts,enabledSources:state.enabledCount,blocked:['HE','SD','QH']},null,2));
 }finally{await mini.disconnect();clearTimeout(timer);}
})().catch(e=>{console.error(e.stack);clearTimeout(timer);process.exitCode=1;});
