/**
 * ===========================================================================
 * API 请求工具 — 封装 wx.request 的所有后端接口调用
 * ===========================================================================
 */

const app = getApp();

function requestV2(path, options = {}) {
  const { params = {} } = options;
  const qs = Object.entries(params).filter(([, v]) => v !== '' && v !== undefined)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join('&');
  const token = wx.getStorageSync('policy_v2_token');
  const header = path.indexOf('/me/') === 0 && token ? { Authorization: 'Bearer ' + token } : {};
  return new Promise((resolve, reject) => wx.request({
    url: app.globalData.API_V2_BASE + path + (qs ? '?' + qs : ''),
    method: options.method || 'GET', data: options.data, header,
    success(res) { if (res.statusCode >= 200 && res.statusCode < 300) resolve(res.data); else reject(res); },
    fail: reject
  }));
}

const V2_TYPES = { '规范性文件': 'policy', '政策解读': 'interpretation' };
function legacyShape(item) {
  const summary = (item.summary || []).map(point => typeof point === 'string' ? point : (point.text || ''));
  return { id: item.id, title: item.title, doc_number: item.document_number || '',
    issuing_authority: item.authority || '', publish_date: item.published || '',
    category: item.topic || '', doc_type: item.type === 'interpretation' ? '政策解读' : '规范性文件',
    original_url: item.original_url || '', content: item.body || '',
    summary: JSON.stringify(summary.filter(Boolean)), attachments: JSON.stringify(item.attachments || []) };
}

function request(path, options = {}) {
  const { method = 'GET', data, params } = options;
  let url = app.globalData.API_BASE + path;

  if (params) {
    const qs = Object.entries(params)
      .filter(([_, v]) => v !== '' && v !== undefined)
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
      .join('&');
    if (qs) url += '?' + qs;
  }

  return new Promise((resolve, reject) => {
    wx.request({
      url,
      method,
      data,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else {
          reject(res);
        }
      },
      fail(err) {
        reject(err);
      }
    });
  });
}

module.exports = {
  getDocuments(params) {
    if (app.globalData.USE_POLICY_V2) {
      const page = Math.max(1, Number(params.page) || 1), size = Number(params.page_size) || 20;
      return requestV2('/policies', { params: { q: params.q || '', region: params.region || '',
        topic: params.category === '全部' ? '' : (params.category || ''),
        content_type: params.doc_type === '全部类型' ? '' : (V2_TYPES[params.doc_type] || ''),
        limit: size, offset: (page - 1) * size } }).then(res => ({
          items: (res.items || []).map(legacyShape), total: res.total || 0,
          page, page_size: size
        }));
    }
    return request('/documents', { params });
  },
  getDocumentDetail(id) {
    if (app.globalData.USE_POLICY_V2) return requestV2(`/policies/${id}`).then(legacyShape);
    return request(`/documents/${id}`);
  },
  searchDocuments(params) {
    if (app.globalData.USE_POLICY_V2) {
      return requestV2('/policies', { params: { q: params.q || '', limit: params.page_size || 20,
        offset: ((params.page || 1) - 1) * (params.page_size || 20) } }).then(res => ({
          ...res, items: (res.items || []).map(legacyShape), page: params.page || 1,
          page_size: params.page_size || 20
        }));
    }
    return request('/documents/search', { params });
  },
  getLatestUpdate() {
    if (app.globalData.USE_POLICY_V2) return requestV2('/policies', { params: { limit: 1, offset: 0 } })
      .then(res => ({ latest_update: res.items && res.items.length ? res.items[0].published : '' }));
    return request('/documents/latest-update');
  },
  getCategories() {
    if (app.globalData.USE_POLICY_V2) return requestV2('/topics').then(categories => ({ categories }));
    return request('/documents/categories');
  },
  loginV2() {
    return new Promise((resolve, reject) => wx.login({
      success: result => result.code ? resolve(result.code) : reject(new Error('wechat_login_code_missing')),
      fail: reject
    })).then(code => requestV2('/auth/wechat', { method: 'POST', data: { code } }))
      .then(session => { wx.setStorageSync('policy_v2_token', session.access_token); return session; });
  },
  getV2Favorites() { return requestV2('/me/favorites'); },
  addV2Favorite(id) { return requestV2(`/me/favorites/${id}`, { method: 'PUT' }); },
  removeV2Favorite(id) { return requestV2(`/me/favorites/${id}`, { method: 'DELETE' }); },
  syncV2Favorite(id, favorited) {
    const send = () => favorited ? this.addV2Favorite(id) : this.removeV2Favorite(id);
    return send().catch(error => {
      if (!error || error.statusCode !== 401) throw error;
      return this.loginV2().then(send);
    });
  },
  getV2Follows() { return requestV2('/me/follows'); },
  addV2Follow(rule) { return requestV2('/me/follows', { method: 'POST', data: rule }); },
  agentSearch(query, session_id) {
    return request('/agent/search', {
      method: 'POST',
      data: { query, session_id }
    });
  }
};
