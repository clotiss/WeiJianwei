const assert = require('node:assert/strict');

const calls = [];
const stored = {};
let failFavoriteOnce = false;
global.getApp = () => ({ globalData: {
  API_BASE: 'https://api.example/v1', API_V2_BASE: 'https://api.example/v2', USE_POLICY_V2: true
} });
global.wx = { request(options) {
  calls.push(options);
  const data = options.url.includes('/auth/wechat') ? { access_token: 'mock-token' } : options.url.includes('/topics') ? ['基层医疗'] : {
    items: [{ id: 7, title: '政策标题', document_number: '国卫办发〔2026〕1号',
      authority: '国家卫健委', published: '2026-11-16', type: 'interpretation',
      topic: '基层医疗', original_url: 'https://official.example/a.shtml',
      summary: [{ text: '要点', quote: '原文证据' }], attachments: [] }],
    total: 1
  };
  const statusCode = failFavoriteOnce && options.url.includes('/me/favorites/') ? 401 : 200;
  if (statusCode === 401) failFavoriteOnce = false;
  options.success({ statusCode, data });
}, getStorageSync(key) { return stored[key]; }, setStorageSync(key, value) { stored[key] = value; },
login(options) { options.success({ code: 'mock-code' }); } };

const api = require('../utils/api');
(async () => {
  const list = await api.getDocuments({ category: '基层医疗', doc_type: '政策解读', page: 1, page_size: 20 });
  assert.equal(calls[0].url, 'https://api.example/v2/policies?topic=%E5%9F%BA%E5%B1%82%E5%8C%BB%E7%96%97&content_type=interpretation&limit=20&offset=0');
  assert.equal(list.total, 1);
  assert.equal(list.items[0].doc_type, '政策解读');
  assert.equal(JSON.parse(list.items[0].summary)[0], '要点');
  assert.deepEqual(await api.getCategories(), { categories: ['基层医疗'] });
  await api.loginV2();
  assert.equal(stored.policy_v2_token, 'mock-token');
  await api.getV2Favorites();
  assert.equal(calls[calls.length - 1].header.Authorization, 'Bearer mock-token');
  stored.policy_v2_token = '';
  failFavoriteOnce = true;
  const beforeRetry = calls.length;
  await api.syncV2Favorite(7, true);
  assert.equal(calls.length - beforeRetry, 3); // 401 → wx.login → retry
  assert.equal(calls[calls.length - 1].method, 'PUT');
  console.log('V2 mini-program API adapter: 6 checks passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
