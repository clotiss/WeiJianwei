/**
 * ===========================================================================
 * 收藏页 — 展示用户收藏的政策文件列表
 * ===========================================================================
 *
 * 功能：
 * 1. 展示已收藏的文件列表
 * 2. 点击文件卡片进入详情
 * 3. 右滑返回手势
 *
 * 数据来源：本地缓存（storage.js 管理的 wx.getStorageSync）
 * 每次 onShow 时重新读取，确保收藏状态实时同步
 *
 * 进入方式：从首页顶部"收藏"按钮点击进入
 */

const storage = require('../../utils/storage');
const swipeBack = require('../../utils/swipe-back');

Page({
  data: {
    favorites: []  // 收藏的文件列表
  },

  onLoad() { swipeBack.initSwipeBack.call(this); },

  // ---- 右滑返回手势 ----
  onTouchStart(e) { swipeBack.onTouchStart.call(this, e); },
  onTouchEnd(e) { swipeBack.onTouchEnd.call(this, e); },

  /**
   * 页面显示时重新读取收藏列表
   * 确保从详情页切换收藏状态后，返回此页能看到最新结果
   */
  onShow() {
    this.setData({ favorites: storage.getFavorites() });
  },

  goBack() { wx.navigateBack(); },

  onShareAppMessage() {
    return { title: "卫健委政策速查", path: "/pages/index/index" };
  },
});
