const regions = require('../config/regions');
const V2_TYPES = { '规范性文件': 'policy', '政策解读': 'interpretation' };
const loginFlights = new Map();
const favoritesFlights = new Map();
const globalData = () => getApp().globalData;
const useV2 = () => !!globalData().USE_POLICY_V2;
const sessionKey = () => 'policy_v2_session:' + (globalData().environment || 'default') + ':' + globalData().API_V2_BASE;
function session() { return wx.getStorageSync(sessionKey()) || {}; }
function query(params = {}) {
  return Object.entries(params).filter(([, value]) => value !== '' && value !== undefined && value !== null)
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`).join('&');
}
function send(base, path, options = {}) {
  if (!base) return Promise.reject({ code: 'endpoint_not_configured' });
  const qs = query(options.params);
  return new Promise((resolve, reject) => wx.request({
    url: base + path + (qs ? '?' + qs : ''), method: options.method || 'GET',
    data: options.data, header: options.header || {}, timeout: 15000,
    success(res) { if (res.statusCode >= 200 && res.statusCode < 300) resolve(res.data); else reject(res); },
    fail: reject
  }));
}
const request = (path, options) => send(globalData().API_BASE, path, options);
const requestV2 = (path, options) => send(globalData().API_V2_BASE, path, options);
function loginV2() {
  const key = sessionKey();
  if (loginFlights.has(key)) return loginFlights.get(key);
  const base = globalData().API_V2_BASE;
  if (!base) return Promise.reject({ code: 'endpoint_not_configured' });
  const pending = new Promise((resolve, reject) => wx.login({
    success: result => result.code ? resolve(result.code) : reject({code:'wechat_login_code_missing'}), fail: reject
  })).then(code => send(base, '/auth/wechat', {method:'POST', data:{code}}))
    .then(value => {
      if (!value.access_token) throw {code:'invalid_session'};
      wx.setStorageSync(key, value);
      return value;
    }).finally(() => loginFlights.delete(key));
  loginFlights.set(key, pending);
  return pending;
}
function authorized(path, options = {}) {
  const previous = session();
  const expired = previous.expires_at && Date.parse(previous.expires_at) <= Date.now();
  const initial = !previous.access_token || expired ? loginV2() : Promise.resolve(previous);
  const call = value => requestV2(path, {...options, header:{Authorization:'Bearer ' + value.access_token}});
  return initial.then(value => call(value).catch(error => {
    if (error.statusCode !== 401) throw error;
    // Concurrent 401s reuse an already renewed token, or join the same login.
    const current = session();
    const renewed = current.access_token && current.access_token !== value.access_token
      ? Promise.resolve(current) : loginV2();
    return renewed.then(call); // Retry once; a second 401 is surfaced to the page.
  }));
}
function documentShape(item) {
  const summary = (Array.isArray(item.summary) ? item.summary : [])
    .map(point => typeof point === 'string' ? point : (point.text || '')).filter(Boolean);
  return { id:item.id, title:item.title, region:item.region || '', region_name:regions[item.region] || item.region || '',
    summary_text:summary[0] || '', type_label:item.type === 'interpretation' ? '官方解读' : item.type === 'policy' ? '政策正文' : '其他',
    doc_number:item.document_number || '', issuing_authority:item.authority || '', publish_date:item.published || '',
    category:item.topic || '', doc_type:item.type === 'interpretation' ? '政策解读' : item.type === 'policy' ? '规范性文件' : '其他',
    original_url:item.original_url || '', content:item.body || '', revision:item.revision,
    summary:JSON.stringify(summary), summary_points:(item.summary || []).filter(point => point && typeof point === 'object'),
    summary_status:item.summary_status || {}, attachments:JSON.stringify(item.attachments || []) };
}
function policyParams(params = {}) {
  const page = Math.max(1, Number(params.page) || 1);
  const size = Math.min(100, Math.max(1, Number(params.page_size) || 20));
  return { q:params.q || '', region:params.region === undefined ? 'CN' : params.region, include_national:params.include_national !== false,
    topic:params.category === '全部' ? '' : (params.category || ''),
    published_since:params.published_since || '', content_type:V2_TYPES[params.doc_type] || '', limit:size, offset:(page - 1) * size };
}
function policyList(params) {
  const filters = policyParams(params);
  return requestV2('/policies', {params:filters}).then(res => ({
    items:(res.items || []).map(documentShape), total:res.total || 0,
    page:filters.offset / filters.limit + 1, page_size:filters.limit, freshness:res.freshness || null, contentStatus:res.scope || null
  }));
}
function errorMessage(error, fallback = '加载失败，请重试') {
  if (error && error.code === 'endpoint_not_configured') return '暂时无法连接服务，请稍后再试';
  if (error && error.data && error.data.detail === 'wechat_login_not_configured') return '账号同步暂未开放，请稍后重试';
  if (error && error.statusCode === 401) return '微信登录失效，请重试';
  if (error && error.statusCode === 404) return '内容或服务暂不可用';
  return fallback;
}
module.exports = {
  useV2, errorMessage, loginV2,
  hasV2Session: () => !!session().access_token,
  getDocuments(params) { return useV2() ? policyList(params) : request('/documents', {params}); },
  searchDocuments(params) { return useV2() ? policyList(params) : request('/documents/search', {params}); },
  getDocumentDetail(id) { return useV2() ? requestV2(`/policies/${id}`).then(documentShape) : request(`/documents/${id}`); },
  getLatestUpdate(params = {}) {
    return useV2() ? policyList({...params, page:1, page_size:1})
      .then(res => ({latest_update:res.items.length ? res.items[0].publish_date : ''})) : request('/documents/latest-update');
  },
  getCategories() { return useV2() ? requestV2('/topics').then(categories => ({categories})) : request('/documents/categories'); },
  getRegions() { return requestV2('/regions'); },
  getCoverage() { return requestV2('/coverage'); },
  getSourceInventory() { return requestV2('/source-inventory'); },
  getV2Favorites() {
    const key=sessionKey();
    if (!favoritesFlights.has(key)) favoritesFlights.set(key,authorized('/me/favorites').then(items => items.map(documentShape)).finally(() => favoritesFlights.delete(key)));
    return favoritesFlights.get(key);
  },
  addV2Favorite(id) { return authorized(`/me/favorites/${id}`, {method:'PUT'}); },
  removeV2Favorite(id) { return authorized(`/me/favorites/${id}`, {method:'DELETE'}); },
  syncV2Favorite(id, favorited) { return authorized(`/me/favorites/${id}`, {method:favorited ? 'PUT' : 'DELETE'}); },
  removeV2Follow(id) { return authorized(`/me/follows/${id}`, {method:'DELETE'}); },
  getV2Follows() { return authorized('/me/follows'); },
  addV2Follow(rule) { return authorized('/me/follows', {method:'POST', data:rule}); },
  agentSearch(query, session_id) {
    if (useV2()) return Promise.reject({code:'agent_unavailable', message:'全国政策问答尚未开放'});
    return request('/agent/search', {method:'POST', data:{query, session_id}});
  }
};
