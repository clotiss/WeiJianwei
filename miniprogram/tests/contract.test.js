const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const path = require('node:path');
const readline = require('node:readline');
const fs = require('node:fs');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const server = spawn(process.env.POLICY_TEST_PYTHON || path.join(root,'.venv/bin/python'), [path.join(__dirname,'contract-server.py')],
  {cwd:root, env:{...process.env,PYTHONPATH:path.join(root,'backend')}, stdio:['pipe','pipe','inherit']});
const awaiting = new Map(), stored = {};
let serial = 0;
server.on('error', error => { for (const options of awaiting.values()) options.fail(error); });
server.on('exit', () => { for (const options of awaiting.values()) options.fail(new Error('contract server stopped')); });
readline.createInterface({input:server.stdout}).on('line', line => {
  const reply=JSON.parse(line), request=awaiting.get(reply.id); awaiting.delete(reply.id); request.success(reply);
});
global.getApp = () => ({globalData:{USE_POLICY_V2:true,API_V2_BASE:'https://contract.example/api/v2',environment:'develop'}});
global.wx = {
  request(options) {
    const id=++serial; awaiting.set(id,options);
    const url=new URL(options.url);
    server.stdin.write(JSON.stringify({id,method:options.method,path:url.pathname+url.search,data:options.data,header:options.header})+'\n');
  },
  getStorageSync:key=>stored[key], setStorageSync:(key,value)=>{stored[key]=value;},
  login:options=>options.success({code:'test-wechat-code'}), showToast() {}, stopPullDownRefresh() {}
};
const api=require('../utils/api');
function page(name) {
  let definition;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../pages',name,name+'.js'),'utf8'), {
    wx:global.wx, Page:value=>{definition=value;}, setTimeout,
    require:spec=>require(path.resolve(__dirname,'../pages',name,spec))
  });
  return {...definition,data:JSON.parse(JSON.stringify(definition.data)),setData(value){Object.assign(this.data,value);}};
}
(async () => {
  const regions=await api.getRegions(); assert.equal(regions.length,32);
  assert.equal(regions.find(item=>item.code==='GD').name,'广东');
  const home=page('index'); home.onLoad();
  await home.resetFilters({activeRegion:'GD',includeNational:false,activeCategory:'医疗服务与质量安全'});
  assert.equal(home.data.documents.length,1); assert.equal(home.data.documents[0].region_name,'广东');
  await home.onNationalChange({detail:{value:true}});
  assert.equal(home.data.documents.length,2);
  const search=page('search'); search.onLoad({region:'GD',include_national:'false',doc_type:'规范性文件'});
  search.onInput({detail:{value:'医疗正文'}}); await search.onSearch();
  assert.equal(search.data.total,1); const id=search.data.results[0].id;
  const accountRule=await api.addV2Follow({region:'GD',topic:'',include_national:false});
  assert.equal((await api.getV2Follows()).length,1);
  await api.removeV2Follow(accountRule.id); assert.equal((await api.getV2Follows()).length,0);
  assert.equal((await api.searchDocuments({q:'GD发布机构'})).total,1);
  assert.equal((await api.getDocuments({published_since:'2026-11-18'})).total,0);
  const detail=page('detail'); await detail.onLoad({id:String(id)});
  assert.equal(detail.data.doc.doc_number,'GD-1'); assert.equal(detail.data.summary[0],'医疗摘要');
  assert.equal(detail.data.attachments[0].statusLabel,'正文已提取');
  assert.equal(detail.data.doc.issuing_authority,'GD发布机构');
  const plaintext=page('plaintext'); await plaintext.onLoad({id:String(id)});
  assert.ok(plaintext.data.content.includes('真实接口契约测试'));
  await detail.toggleFav(); assert.equal(detail.data.isFav,true);
  const favorites=page('favorites'); favorites.onLoad(); await favorites.onShow();
  assert.equal(favorites.data.favorites[0].region,'GD'); assert.equal(favorites.data.favorites[0].id,id);
  await detail.toggleFav(); await favorites.onShow(); assert.equal(favorites.data.favorites.length,0);
  const coverage=page('coverage'); await coverage.onLoad();
  assert.equal(coverage.data.provinceCount,31); assert.equal(coverage.data.enabledCount,0);
  assert.equal(coverage.data.sources.length,64);
  assert.ok(coverage.data.sources.every(item=>item.status==='未启用监控'));
  const missing=page('detail'); await missing.onLoad({id:'999999'}); assert.equal(missing.data.loadError,true);
  console.log('Real V2 API + pages: regions → filters → body search → detail → favorites → coverage passed');
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(()=>server.stdin.end());
