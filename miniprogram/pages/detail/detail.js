/**
 * ===========================================================================
 * 文件详情页 — 展示单篇政策文件的完整信息
 * ===========================================================================
 *
 * 功能：
 * 1. 展示文件标题、发文字号、发布日期、发文机关、分类
 * 2. AI 关键要点摘要（从 summary JSON 字段解析）
 * 3. 附件列表展示
 * 4. 收藏/取消收藏（★/☆ 切换）
 * 5. 查看原文纯文本
 * 6. 复制原文链接
 * 7. 右滑返回
 *
 * 进入方式：从首页/搜索结果/分类页面点击文件卡片进入
 * 路由参数：id={文件ID}
 */

const api = require('../../utils/api');            // API 请求工具
const storage = require('../../utils/storage');     // 本地收藏管理
const swipeBack = require('../../utils/swipe-back'); // 右滑返回手势

Page({
  /**
   * data — 页面数据
   */
  data: {
    doc: {},          // 文件完整信息对象
    summary: [],      // AI 提取的关键要点列表
    attachments: [],  // 附件列表 [{name, url}, ...]
    isFav: false,     // 是否已收藏
    loading: true     // 是否加载中
  },

  /**
   * onLoad — 页面加载
   * @param {object} options — 路由参数，options.id 为文件 ID
   */
  onLoad(options) {
    // 初始化右滑返回手势
    swipeBack.initSwipeBack.call(this);

    // 从路由参数获取文件 ID（转为整数）
    const id = parseInt(options.id);

    // 请求文件详情
    api.getDocumentDetail(id).then(doc => {
      // 解析 summary 字段（JSON 字符串 → 数组）
      let summary = [];
      let attachments = [];
      try {
        summary = JSON.parse(doc.summary || '[]');
      } catch(e) {}
      try {
        attachments = JSON.parse(doc.attachments || '[]');
      } catch(e) {}

      // 更新页面数据
      this.setData({
        doc,
        summary,                              // AI 要点列表
        attachments,                          // 附件列表
        isFav: storage.isFavorited(doc.id),   // 检查收藏状态
        loading: false                         // 关闭加载态
      });
    }).catch(() => {
      this.setData({ loading: false });
      wx.showToast({ title: '加载失败', icon: 'none' });
    });
  },

  // ---- 右滑返回手势 ----
  onTouchStart(e) { swipeBack.onTouchStart.call(this, e); },
  onTouchEnd(e) { swipeBack.onTouchEnd.call(this, e); },

  /**
   * 切换收藏状态
   *
   * 流程图：
   * 用户点击 ☆ → toggleFavorite → 写入本地缓存 → 更新 UI → 显示 Toast
   * 用户点击 ★ → toggleFavorite → 从缓存删除 → 更新 UI → 显示 Toast
   */
  toggleFav() {
    const added = storage.toggleFavorite(this.data.doc);
    // 更新星标状态
    this.setData({ isFav: added });
    // 提示用户操作结果
    wx.showToast({
      title: added ? '已加入收藏' : '已取消收藏',
      icon: 'none',
      duration: 1500
    });
  },

  /**
   * 打开原文纯文本页面
   */
  openPlaintext() {
    wx.navigateTo({ url: `/pages/plaintext/plaintext?id=${this.data.doc.id}` });
  },

  /**
   * 打开原文链接弹窗
   * 显示原始 URL，用户可选择复制链接
   */
  openOriginal() {
    const url = this.data.doc.original_url;
    if (!url) return;  // 无链接则返回

    wx.showModal({
      title: '原文链接及附件',
      content: url,
      confirmText: '复制链接',
      cancelText: '关闭',
      success: (res) => {
        if (res.confirm) {
          // 用户点击"复制链接"，将 URL 写入剪贴板
          wx.setClipboardData({
            data: url,
            success: () => wx.showToast({ title: '链接已复制', icon: 'none' })
          });
        }
      }
    });
  },

  /**
   * 打开附件链接
   * 附件在微信小程序中无法直接下载，提供复制链接功能让用户在浏览器中打开
   */
  openAttachment(e) {
    const url = e.currentTarget.dataset.url;
    if (!url) return;

    wx.showModal({
      title: '附件',
      content: url,
      confirmText: '复制链接',
      cancelText: '关闭',
      success: (res) => {
        if (res.confirm) {
          wx.setClipboardData({
            data: url,
            success: () => wx.showToast({
              title: '链接已复制，请在浏览器中打开',
              icon: 'none'
            })
          });
        }
      }
    });
  }
});
