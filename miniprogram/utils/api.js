/**
 * ===========================================================================
 * API 请求工具 — 封装 wx.request 的所有后端接口调用
 * ===========================================================================
 */

const app = getApp();

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
    return request('/documents', { params });
  },
  getDocumentDetail(id) {
    return request(`/documents/${id}`);
  },
  searchDocuments(params) {
    return request('/documents/search', { params });
  },
  getLatestUpdate() {
    return request('/documents/latest-update');
  },
  getCategories() {
    return request('/documents/categories');
  },
  agentSearch(query, session_id) {
    return request('/agent/search', {
      method: 'POST',
      data: { query, session_id }
    });
  }
};
