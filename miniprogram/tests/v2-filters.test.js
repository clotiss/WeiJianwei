const assert = require('node:assert/strict');
const calls = [];
global.getApp = () => ({globalData: {USE_POLICY_V2:true, API_V2_BASE:'https://api.example/v2'}});
global.wx = {getStorageSync() {}, request(options) {
  calls.push(options);
  options.success({statusCode:200, data:{items:[{id:1, region:'GD', type:'policy'}],total:1}});
}};
const api = require('../utils/api');
(async () => {
  const filters = {q:'医保', region:'GD', include_national:false, category:'医疗服务与质量安全', doc_type:'政策解读', page:2, published_since:'2026-11-01'};
  const list = await api.getDocuments(filters);
  let query = new URL(calls.at(-1).url).searchParams;
  assert.equal(query.get('include_national'), 'false', '关闭国家级内容后必须传给后端');
  assert.equal(list.items[0].region, 'GD', '列表必须保留采集地区');
  await api.searchDocuments(filters);
  query = new URL(calls.at(-1).url).searchParams;
  assert.equal(query.get('region'), 'GD', '搜索必须保留省份');
  assert.equal(query.get('include_national'), 'false');
  assert.equal(query.get('content_type'), 'interpretation');
  assert.equal(query.get('offset'), '20');
  assert.equal(query.get('published_since'),'2026-11-01');
  assert.ok(require('../utils/filters').label(filters).includes('2026-11-01 起'));
  console.log('V2 filter propagation passed');
})().catch(error => { console.error(error); process.exitCode=1; });
