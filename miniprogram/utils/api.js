/**
 * ===========================================================================
 * API 请求工具 — 封装 wx.request 的所有后端接口调用
 * ===========================================================================
 *
 * 本文件是小程序与后端通信的唯一入口，提供以下接口：
 * - getDocuments(params)      → 分页获取文件列表
 * - getDocumentDetail(id)     → 获取单篇文件详情
 * - searchDocuments(params)   → 按关键词搜索文件
 * - getLatestUpdate()         → 获取最新入库文件的日期
 * - getCategories()           → 获取所有分类列表
 *
 * 设计原则：
 * 1. 统一错误处理 — 所有请求共用 request() 函数
 * 2. 查询参数自动过滤空值 — 避免向后端发送无意义的空参数
 * 3. Promise 封装 — 将回调式的 wx.request 转为 Promise，支持 async/await
 */

// 获取全局 App 实例（访问 globalData.API_BASE）
const app = getApp();

/**
 * 通用请求函数 — 封装 wx.request
 *
 * @param {string} path    - API 路径（如 '/documents/search'）
 * @param {object} options - 配置项 { method, data, params }
 *   - method: HTTP 方法（GET/POST/DELETE），默认 GET
 *   - data: 请求体（POST 请求用）
 *   - params: URL 查询参数对象（自动拼接在 URL 后）
 *
 * @returns {Promise} — 成功时 resolve 响应数据，失败时 reject 错误
 *
 * 示例：
 *   request('/documents/search', { params: { q: '传染病', page: 1 } })
 *   → GET https://106.52.159.38/api/v1/documents/search?q=传染病&page=1
 */
function request(path, options = {}) {
  // 解构参数，设置默认值
  const { method = 'GET', data, params } = options;

  // 拼接完整 URL：基础地址 + 路径
  let url = app.globalData.API_BASE + path;

  // 处理查询参数：转换为 URL 查询字符串
  if (params) {
    // 过滤掉空值和 undefined 的参数（避免 ?category=&doc_type=）
    const qs = Object.entries(params)
      .filter(([_, v]) => v !== '' && v !== undefined)
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)  // 对中文等特殊字符编码
      .join('&');
    if (qs) url += '?' + qs;  // 拼接在 URL 后面
  }

  // 返回 Promise：将回调式的 wx.request 包装为 Promise
  return new Promise((resolve, reject) => {
    wx.request({
      url,
      method,
      data,
      // 成功回调
      success(res) {
        // HTTP 状态码 2xx 视为成功
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);          // 返回响应数据
        } else {
          reject(res);                 // 非 2xx 视为失败
        }
      },
      // 失败回调（网络错误等）
      fail(err) {
        reject(err);
      }
    });
  });
}

// ===========================================================================
// 导出的 API 方法 — 每个方法对应一个后端接口
// ===========================================================================
module.exports = {
  /**
   * 获取文件列表（分页 + 筛选）
   * @param {object} params - { category, doc_type, page, page_size }
   */
  getDocuments(params) {
    return request('/documents', { params });
  },

  /**
   * 获取单篇文件详情
   * @param {number} id - 文件 ID
   */
  getDocumentDetail(id) {
    return request(`/documents/${id}`);
  },

  /**
   * 搜索文件
   * @param {object} params - { q: 关键词, page, page_size }
   */
  searchDocuments(params) {
    return request('/documents/search', { params });
  },

  /**
   * 获取最新入库文件的日期
   */
  getLatestUpdate() {
    return request('/documents/latest-update');
  },

  /**
   * 获取所有文件分类列表
   */
  getCategories() {
    return request('/documents/categories');
  }
};
