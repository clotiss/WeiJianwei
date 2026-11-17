const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const routes = [], calls = [], stored = {favorites:[{id:7,title:'legacy'}]};
let mode = 'success', writes = 0, v2 = true;
global.getApp = () => ({globalData:{USE_POLICY_V2:true,API_V2_BASE:'https://api.example/v2'}});
global.wx = {getStorageSync:key => stored[key], setStorageSync:(key,value) => {stored[key]=value;},
  showToast() {}, navigateTo:options => routes.push(options.url), stopPullDownRefresh() {}};
const pending = () => new Promise((resolve,reject) => calls.push({resolve,reject}));
const api = {
  useV2:() => v2, hasV2Session:() => true, errorMessage:() => '加载失败，请重试',
  getDocuments(params) { const promise=pending(); calls.at(-1).params=params; return promise; },
  searchDocuments(params) { return this.getDocuments(params); },
  getLatestUpdate:() => Promise.resolve({latest_update:''}),
  getDocumentDetail:() => Promise.resolve({id:7,title:'广东文件',summary:'[]',attachments:'[]'}),
  getV2Favorites:() => mode === 'success' ? Promise.resolve([{id:7}]) : Promise.reject(new Error('offline')),
  syncV2Favorite() { writes++; return mode === 'success' ? Promise.resolve({}) : Promise.reject(new Error('offline')); }
};
function page(name) {
  let definition;
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../pages',name,name+'.js'),'utf8'), {
    Page:value => {definition=value;}, wx:global.wx, setTimeout,
    require:spec => spec.endsWith('/api') ? api : require(path.resolve(__dirname,'../pages',name,spec))
  });
  return {...definition,data:JSON.parse(JSON.stringify(definition.data)),setData(value) {Object.assign(this.data,value);}};
}
(async () => {
  const home=page('index'); home.setData({activeRegion:'GD',includeNational:false,activeCategory:'医疗 & 质量'});
  home.goSearch(); home.goCategory();
  assert.ok(routes.every(url => url.includes('region=GD') && url.includes('include_national=false') && url.includes('%26')));
  const search=page('search');
  search.onLoad({region:'GD',include_national:'false',category:encodeURIComponent('医疗 & 质量'),doc_type:encodeURIComponent('政策解读')});
  search.onInput({detail:{value:'旧查询'}}); let first=search.onSearch(), old=calls.at(-1);
  search.onInput({detail:{value:'新查询'}}); let second=search.onSearch();
  assert.equal(calls.at(-1).params.region,'GD'); assert.equal(calls.at(-1).params.include_national,false);
  calls.at(-1).resolve({items:[{id:2}],total:2}); await second;
  old.resolve({items:[{id:1}],total:99}); await first;
  assert.equal(search.data.results[0].id,2);
  search.onInput({detail:{value:'未提交的文字'}});
  const failed=search.loadMore(); assert.equal(calls.at(-1).params.q,'新查询');
  calls.at(-1).reject(new Error('offline')); await failed;
  assert.equal(search.data.page,1); assert.equal(search.data.results[0].id,2); assert.equal(search.data.loadError,true);
  const retry=search.loadMore(); assert.equal(calls.at(-1).params.page,2);
  calls.at(-1).resolve({items:[{id:3}],total:2}); await retry;
  assert.equal(search.data.page,2); assert.equal(search.data.hasMore,false);
  // Clearing the query invalidates pending responses.
  search.setData({keyword:'pending'}); first=search.onSearch(); old=calls.at(-1);
  search.setData({keyword:'  '}); search.onSearch(); old.resolve({items:[{id:9}],total:1}); await first;
  assert.equal(search.data.searched,false); assert.equal(search.data.results.length,0);
  const category=page('category'); first=category.onLoad({region:'BJ',include_national:'false'});
  calls.at(-1).reject(new Error('offline')); await first; assert.equal(category.data.loadError,true); assert.equal(category.data.page,1);
  const detail=page('detail'); await detail.onLoad({id:'7'});
  assert.equal(detail.data.isFav,true); mode='failure'; await detail.toggleFav();
  assert.equal(detail.data.isFav,true, 'failed cloud write must not show success');
  assert.equal(detail.data.favKnown,false); assert.ok(detail.data.favError);
  assert.equal(writes,1); assert.equal(stored.favorites[0].title,'legacy');
  mode='success'; await detail.refreshFavorite(); await detail.toggleFav(); assert.equal(detail.data.isFav,false);
  const invalid=page('detail'); await invalid.onLoad({id:'7x'}); assert.equal(invalid.data.loadError,true);
  const favorites=page('favorites'); favorites.onLoad(); mode='failure'; await favorites.onShow();
  assert.equal(favorites.data.loadError,true); assert.equal(favorites.data.favorites.length,0);
  mode='success'; await favorites.fetchFavorites(); assert.equal(favorites.data.favorites[0].id,7);
  const plaintext=page('plaintext'); await plaintext.onLoad({id:'7'}); assert.ok(plaintext.data.content.includes('暂未收录'));
  v2=false; const legacyDetail=page('detail'); await legacyDetail.onLoad({id:'7'});
  const cloudWrites=writes; assert.equal(legacyDetail.data.isFav,true);
  await legacyDetail.toggleFav(); assert.equal(stored.favorites.length,0); assert.equal(writes,cloudWrites);
  const legacyFavorites=page('favorites'); legacyFavorites.onLoad(); await legacyFavorites.onShow(); assert.equal(legacyFavorites.data.favorites.length,0);
  console.log('V2 page flows: filter routing, search races, pagination recovery, favorite failure, empty body passed');
})().catch(error => {console.error(error); process.exitCode=1;});
