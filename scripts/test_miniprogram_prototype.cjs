// Validate prototype-specific sheets, detail tabs, and bottom navigation in WeChat.
const assert=require('node:assert/strict'),path=require('node:path');
const automator=require(process.env.MINIPROGRAM_AUTOMATOR_PATH || path.resolve(__dirname,'../.runtime/devtools-automation/node_modules/miniprogram-automator'));
const timer=setTimeout(()=>{console.error('Prototype verification timed out');process.exit(2);},90000);
async function until(read,test,label){const end=Date.now()+15000;while(Date.now()<end){const value=await read();if(test(value))return value;await new Promise(r=>setTimeout(r,150));}throw Error('Timed out: '+label);}
(async()=>{
 const mini=await automator.connect({wsEndpoint:'ws://127.0.0.1:9420'}), errors=[];
 mini.on('exception',e=>errors.push(e.message || JSON.stringify(e)));
 const current=route=>until(()=>mini.currentPage(),p=>p&&p.path===route,route);
 const loaded=p=>until(()=>p.data(),d=>d.loading===false,'data loaded');
 const element=(p,s)=>until(()=>p.$(s),Boolean,s);
 const shot=name=>mini.screenshot({path:path.resolve(__dirname,'../.runtime/'+name+'.png')});
 try {
  await mini.switchTab('/pages/index/index');let home=await current('pages/index/index');await loaded(home);
  await home.callMethod('openRegion');const sheet=await element(home,'filter-sheet');await element(sheet,'.overlay');
  await shot('prototype-region-actual');
  await sheet.callMethod('choose',{currentTarget:{dataset:{key:'region',value:'GD'}}});
  await sheet.callMethod('national',{detail:{value:false}});await sheet.callMethod('apply');
  let data=await until(()=>home.data(),d=>d.activeRegion==='GD'&&!d.loading&&!d.sheetOpen,'region sheet applied');assert.ok(data.documents.every(item=>item.region==='GD'));
  await home.callMethod('openFilters');await element(sheet,'.overlay');
  await sheet.callMethod('choose',{currentTarget:{dataset:{key:'days',value:7}}});await shot('prototype-filter-actual');await sheet.callMethod('apply');
  data=await until(()=>home.data(),d=>d.days===7&&!d.loading&&!d.sheetOpen,'date filter applied');assert.equal(data.loadError,false);assert.equal(data.filterCount,1);
  const since=new Date();since.setDate(since.getDate()-7);const cutoff=since.toISOString().slice(0,10);assert.ok(data.documents.every(item=>item.publish_date>=cutoff));
  await home.callMethod('clearFilters');await loaded(home);
  await home.callMethod('onRegionChange',{detail:{value:'0'}});data=await until(()=>home.data(),d=>d.activeRegion==='CN'&&!d.loading,'national region restored');
  assert.ok(data.documents.length);const id=data.documents[0].id;
  await mini.navigateTo('/pages/detail/detail?id='+id);let detail=await current('pages/detail/detail');await loaded(detail);await element(detail,'.detail-actions');await shot('prototype-detail-actual');
  await detail.callMethod('selectTab',{currentTarget:{dataset:{tab:'正文'}}});const body=await element(detail,'.article-body');assert.ok((await body.text()).length>20);
  await detail.callMethod('selectTab',{currentTarget:{dataset:{tab:'附件'}}});assert.equal(await detail.data('activeTab'),'附件');
  await mini.switchTab('/pages/follow/follow');const follow=await current('pages/follow/follow');await element(follow,'.add-group');await until(()=>follow.data(),d=>d.regions.length===32,'follow dictionaries');await shot('prototype-follow-actual');
  await mini.switchTab('/pages/mine/mine');const mine=await current('pages/mine/mine');await element(mine,'.profile-head');const original=await mine.data('largeText');assert.ok((await mine.data('historyCount'))>0);
  await mine.callMethod('changeReading',{detail:{value:true}});await shot('prototype-mine-actual');
  await mini.navigateTo('/pages/detail/detail?id='+id);detail=await current('pages/detail/detail');await loaded(detail);assert.equal(await detail.data('largeText'),true);
  await mini.switchTab('/pages/mine/mine');await (await current('pages/mine/mine')).callMethod('changeReading',{detail:{value:original}});
  await mini.switchTab('/pages/index/index');home=await current('pages/index/index');data=await loaded(home);await element(home,'.briefing');
  const card=await element(home,'file-card'),bookmark=await element(card,'.bookmark');
  assert.equal(await bookmark.style('margin-left'),'0px','Native button margins must not shift card metadata');
  await shot('prototype-home-actual');
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({result:'passed',checks:['region sheet apply','date filter sheet','detail tabs','follow tab','mine tab','reading settings','local history'],total:data.total,screenshots:'.runtime/prototype-*-actual.png'},null,2));
 } finally {await mini.disconnect();clearTimeout(timer);}
})().catch(e=>{console.error(e.stack);clearTimeout(timer);process.exitCode=1;});
