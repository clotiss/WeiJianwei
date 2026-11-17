// Opt-in check against an already running WeChat Developer Tools simulator.
// Start cli auto --project <miniprogram> --auto-port 9420 first.
const assert = require('node:assert/strict');
const path = require('node:path');
const automator = require(process.env.MINIPROGRAM_AUTOMATOR_PATH || path.resolve(__dirname,'../.runtime/devtools-automation/node_modules/miniprogram-automator'));
const timer = setTimeout(() => {console.error('Simulator verification timed out'); process.exit(2);}, 60000);
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(read, predicate, label) {
  const deadline = Date.now() + 12000;
  while (Date.now() < deadline) {
    const value = await read();
    if (predicate(value)) return value;
    await sleep(150);
  }
  throw new Error('Timed out: ' + label);
}
(async () => {
  const mini = await automator.connect({wsEndpoint:process.env.MINIPROGRAM_AUTOMATOR_WS || 'ws://127.0.0.1:9420'});
  const errors=[];
  mini.on('exception', error => errors.push(error.message || JSON.stringify(error)));
  const current = route => until(() => mini.currentPage(), page => page && page.path === route, route);
  const loaded = page => until(() => page.data(), data => data.loading === false, 'page data');
  const element = (page, selector) => until(() => page.$(selector), Boolean, selector);
  try {
    let home = await mini.reLaunch('/pages/index/index');
    let data = await loaded(home);
    assert.equal(data.useV2,true); assert.equal(data.loadError,false);
    assert.ok(await element(home,'.search-box'), 'search UI must render');
    assert.ok(data.documents.length > 0, 'preview must contain collected documents');
    await until(() => home.data(), value => value.regions.length === 33, '31 provinces plus national/all');
    const regions = await home.data('regions');
    await home.callMethod('onRegionChange',{detail:{value:String(regions.findIndex(item => item.code === 'GD'))}});
    data=await until(() => home.data(), value => value.activeRegion === 'GD' && !value.loading, 'province filter applied'); assert.equal(data.activeRegion,'GD');
    await home.callMethod('onNationalChange',{detail:{value:false}});
    data=await until(() => home.data(), value => value.includeNational === false && !value.loading, 'national filter applied'); assert.equal(data.includeNational,false);
    assert.ok(data.documents.length > 0 && data.documents.every(item => item.region === 'GD'));
    console.log('Homepage and province filters passed');
    const title = data.documents[0].title;
    await home.callMethod('goSearch');
    const search = await current('pages/search/search');
    assert.equal((await search.data('filters')).region,'GD');
    await search.callMethod('onInput',{detail:{value:title.slice(0,10)}});
    await search.callMethod('onSearch');
    data=await until(() => search.data(), value => value.searched && !value.loading, 'search completed'); assert.equal(data.loadError,false); assert.ok(data.results.length > 0);
    console.log('Filtered search passed');
    const card=await element(search,'file-card');
    await card.callMethod('onTap');
    const detail=await current('pages/detail/detail'); data=await loaded(detail);
    assert.equal(data.loadError,false); assert.equal(data.doc.region,'GD'); assert.ok(data.doc.title);
    await detail.callMethod('openPlaintext');
    const body=await current('pages/plaintext/plaintext'); data=await loaded(body);
    assert.equal(data.loadError,false); assert.ok(data.content.length > 20);
    console.log('Detail and body passed');
    await mini.reLaunch('/pages/index/index'); home=await current('pages/index/index'); await loaded(home);
    await home.callMethod('goCoverage');
    const coverage=await current('pages/coverage/coverage'); data=await loaded(coverage);
    assert.equal(data.loadError,false); assert.equal(data.provinceCount,31); assert.equal(data.sources.length,64);
    home=await mini.reLaunch('/pages/index/index'); data=await loaded(home);
    assert.deepEqual(errors,[], 'no runtime exceptions during user flows');
    const screenshot=path.resolve(__dirname,'../.runtime/miniprogram-home-verified.png');
    await mini.screenshot({path:screenshot});
    console.log(JSON.stringify({result:'passed', runtime:'WeChat Developer Tools simulator',
      checks:['homepage render','province handler','national filter handler','filtered search','detail','body','source coverage'],
      total:data.total,regions:data.regions.length,screenshot},null,2));
  } finally {await mini.disconnect();clearTimeout(timer);}
})().catch(error => {console.error(error.stack);clearTimeout(timer);process.exitCode=1;});
