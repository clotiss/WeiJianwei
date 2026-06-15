/**
 * ===========================================================================
 * 本地存储工具 — 收藏功能的本地数据管理
 * ===========================================================================
 *
 * 本文件封装了微信小程序的本地缓存（Storage）操作，用于管理用户收藏列表。
 *
 * 为什么用本地存储而不是服务端？
 * - 当前没有用户登录系统，无法区分不同用户的收藏
 * - 本地存储无需网络请求，响应即时
 * - 数据存于手机本地，卸载小程序后自动清除
 *
 * 存储格式：
 *   Key: "favorites"
 *   Value: [{id, title, publish_date, category, ...}, ...]  (完整文档对象数组)
 *
 * 核心方法：
 * - getFavorites()    → 读取收藏列表
 * - setFavorites()    → 写入收藏列表
 * - isFavorited()     → 判断某文件是否已收藏
 * - toggleFavorite()  → 切换收藏状态（收藏↔取消）
 */

// 本地存储的键名（统一管理，避免拼写错误）
const FAVORITES_KEY = 'favorites';

/**
 * 获取收藏列表
 * @returns {Array} 收藏的文件对象数组
 */
function getFavorites() {
  try {
    // wx.getStorageSync 是微信的同步存储 API
    // 第二个参数 || [] 确保首次使用（无缓存）时返回空数组
    return wx.getStorageSync(FAVORITES_KEY) || [];
  } catch (e) {
    return [];  // 读取失败时返回空数组（兜底）
  }
}

/**
 * 保存收藏列表（覆盖写入）
 * @param {Array} favs - 收藏的文件对象数组
 */
function setFavorites(favs) {
  wx.setStorageSync(FAVORITES_KEY, favs);
}

/**
 * 判断某文件是否已收藏
 * @param {number} docId - 文件 ID
 * @returns {boolean}
 */
function isFavorited(docId) {
  const favs = getFavorites();
  // Array.some() 检查数组中是否有任意元素的 id === docId
  return favs.some(f => f.id === docId);
}

/**
 * 切换收藏状态
 *
 * 逻辑：
 * 1. 读取当前收藏列表
 * 2. 如果已收藏 → 从列表中移除（取消收藏）
 * 3. 如果未收藏 → 添加到列表末尾（收藏）
 * 4. 写回本地存储
 *
 * @param {object} doc - 完整的文档对象
 * @returns {boolean} — true 表示已收藏，false 表示已取消收藏
 *
 * 调用方根据返回值更新 UI 并显示 Toast 提示
 */
function toggleFavorite(doc) {
  let favs = getFavorites();
  // 查找当前文档在收藏列表中的位置
  const idx = favs.findIndex(f => f.id === doc.id);

  if (idx >= 0) {
    // 已收藏 → 取消：从数组中移除该元素
    favs.splice(idx, 1);
    setFavorites(favs);
    return false;  // 返回 false 表示已取消收藏
  } else {
    // 未收藏 → 收藏：将完整文档对象加入数组
    favs.push(doc);
    setFavorites(favs);
    return true;   // 返回 true 表示已收藏
  }
}

// 导出所有方法
module.exports = { getFavorites, setFavorites, isFavorited, toggleFavorite };
