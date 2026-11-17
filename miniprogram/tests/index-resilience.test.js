const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const requests = [];
let definition;
const api = {
  getDocuments(params) { return new Promise((resolve, reject) => requests.push({params, resolve, reject})); },
  getLatestUpdate() { return Promise.reject(new Error('offline')); },
  errorMessage() { return '加载失败，请重试'; }
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../pages/index/index.js'), 'utf8'), {
  require: name => name.endsWith('/api') ? api : require('../utils/filters'), getApp: () => ({}),
  Page: value => { definition = value; }, wx: { showToast() {}, stopPullDownRefresh() {} }, setTimeout
});
function page() {
  return {...definition, data: JSON.parse(JSON.stringify(definition.data)),
    setData(value) { Object.assign(this.data, value); }};
}
(async () => {
  const p = page(); p.data.documents = [{id:1}]; p.data.page = 1;
  let pending = p.fetchDocuments({reset:true});
  assert.equal(p.data.documents.length, 1);
  requests.at(-1).reject(new Error('offline')); await pending;
  assert.equal(p.data.documents[0].id, 1); assert.equal(p.data.loadError, true);
  p.data.hasMore = true;
  pending = p.fetchDocuments({nextPage:2}); requests.at(-1).reject(new Error('offline')); await pending;
  assert.equal(p.data.page, 1);
  pending = p.fetchDocuments({nextPage:2});
  assert.equal(requests.at(-1).params.page, 2);
  requests.at(-1).resolve({items:[{id:2}],total:2,freshness:{last_success:1000,unavailable_sources:1}}); await pending;
  assert.equal(p.data.page, 2); assert.equal(p.data.documents.length, 2);
  assert.equal(p.data.hasMore, false); assert.ok(p.data.updateNotice); assert.ok(p.data.collectionUpdate);
  const old = p.fetchDocuments({reset:true}); const older = requests.at(-1);
  p.data.activeType = '政策解读';
  const fresh = p.fetchDocuments({reset:true});
  requests.at(-1).resolve({items:[{id:3}],total:1}); await fresh;
  older.resolve({items:[{id:99}],total:1}); await old;
  assert.equal(p.data.documents[0].id, 3);
  const empty = page(); pending = empty.fetchDocuments();
  requests.at(-1).reject(new Error('offline')); await pending;
  assert.equal(empty.data.loadError, true); assert.equal(empty.data.loading, false);
  await empty.fetchLatestUpdate(); // no unhandled promise rejection on offline refresh
  console.log('Home resilience: refresh, pagination retry, freshness, stale requests, first-load failure passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
