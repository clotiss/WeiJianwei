const assert = require('node:assert/strict');
const {resolveEnvironment} = require('../config/environments');
const calls = [], stored = {};
let loginCount = 0, failures = 0, denyAll = false;
const state = {API_BASE:'https://api.example/v1', API_V2_BASE:'https://api.example/v2', USE_POLICY_V2:true, environment:'develop'};
global.getApp = () => ({globalData:state});
global.wx = {
  getStorageSync:key => stored[key], setStorageSync:(key, value) => { stored[key] = value; },
  login(options) { loginCount++; setImmediate(() => options.success({code:'mock-code'})); },
  request(options) {
    calls.push(options);
    const path = new URL(options.url).pathname;
    const statusCode = path.includes('/me/') && (denyAll || failures-- > 0) ? 401 : 200;
    const data = path.endsWith('/auth/wechat') ? {access_token:'token-' + loginCount, expires_at:'2099-01-01T00:00:00Z'} :
      path.endsWith('/me/favorites') ? [{id:7,region:'GD',title:'广东政策',type:'policy'}] :
      path.endsWith('/policies/285') ? {id:285,body:'2026\n年\n10\n月\n20\n日',display_body:'2026年10月20日'} :
      path.endsWith('/policies/286') ? {id:286,body:'保留旧接口正文'} :
      path.endsWith('/topics') ? ['基层医疗'] : {items:[], total:0};
    setImmediate(() => options.success({statusCode, data}));
  }
};
const api = require('../utils/api');
(async () => {
  // No anonymous V1 data is migrated into V2, and the previous unscoped token is ignored.
  stored.favorites = [{id:7, title:'旧库另一个文件'}]; stored.policy_v2_token = 'unscoped-legacy-token';
  const favorites = await api.getV2Favorites();
  assert.equal(loginCount, 1);
  assert.equal(favorites[0].region_name, '广东');
  assert.equal(favorites[0].title, '广东政策');
  assert.equal(calls.at(-1).header.Authorization, 'Bearer token-1');
  assert.deepEqual(stored.favorites, [{id:7, title:'旧库另一个文件'}]);
  // Public requests never include a bearer token.
  await api.getDocuments({}); assert.deepEqual(calls.at(-1).header, {});
  assert.equal((await api.getDocumentDetail(285)).content, '2026年10月20日');
  assert.equal((await api.getDocumentDetail(286)).content, '保留旧接口正文');
  failures = 2;
  await Promise.all([api.getV2Favorites(), api.addV2Favorite(7)]);
  assert.equal(loginCount, 2, 'concurrent 401 requests share one login');
  assert.equal(calls.at(-1).header.Authorization, 'Bearer token-2');
  // Retry is bounded even when the refreshed token is rejected.
  denyAll = true;
  const before = calls.length;
  await assert.rejects(api.getV2Favorites(), error => error.statusCode === 401);
  assert.equal(calls.length - before, 3);
  denyAll = false;
  const previousLogins = loginCount;
  state.API_V2_BASE = 'https://staging.example/v2';
  assert.equal(api.hasV2Session(), false);
  await Promise.all([api.getV2Favorites(), api.getV2Favorites()]);
  assert.equal(loginCount, previousLogins + 1, 'different environment must establish its own session');
  assert.ok(Object.keys(stored).filter(key => key.startsWith('policy_v2_session:')).length === 2);
  assert.deepEqual(await api.getCategories(), {categories:['基层医疗']});
  await assert.rejects(api.agentSearch('广东'), error => error.code === 'agent_unavailable');
  Object.assign(state, resolveEnvironment('trial'));
  state.API_V2_BASE = '';
  const beforeMissing = calls.length;
  await assert.rejects(api.getDocuments({}), error => error.code === 'endpoint_not_configured');
  await assert.rejects(api.getV2Favorites(), error => error.code === 'endpoint_not_configured');
  assert.equal(calls.length, beforeMissing, 'unconfigured trial must not hit production');
  assert.equal(resolveEnvironment('develop').USE_POLICY_V2, true);
  assert.equal(resolveEnvironment('unknown').USE_POLICY_V2, true);
  for (const environment of ['develop', 'trial', 'release']) {
    assert.equal(resolveEnvironment(environment).API_V2_BASE, 'https://wjwjwjw.top/api/v2');
  }
  Object.assign(state, resolveEnvironment('release'));
  await api.getDocuments({page:1}); assert.ok(calls.at(-1).url.startsWith('https://wjwjwjw.top/api/v2/policies'));
  console.log('V2 auth, account favorites, environment isolation, production routing passed');
})().catch(error => {console.error(error); process.exitCode=1;});
