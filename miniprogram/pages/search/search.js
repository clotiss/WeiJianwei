/**
 * ===========================================================================
 * 搜索页 — 关键词搜索政策文件
 * ===========================================================================
 *
 * 功能：
 * 1. 输入关键词搜索（实时输入 + 回车触发搜索）
 * 2. 结果列表展示
 * 3. 上滑加载更多分页
 * 4. 显示搜索结果数量
 * 5. 右滑返回
 *
 * 搜索范围：文件标题 + 发文机关（后端 SQL 模糊匹配）
 *
 * 进入方式：从首页顶部搜索框点击进入
 */

const api = require('../../utils/api');
const swipeBack = require('../../utils/swipe-back');

Page({
  data: {
    keyword: '',       // 搜索关键词
    results: [],       // 搜索结果列表
    total: 0,          // 结果总数
    page: 1,           // 当前页码
    hasMore: false,    // 是否还有更多
    searched: false    // 是否已执行过搜索（用于控制空状态提示的显示）
  },

  onLoad() { swipeBack.initSwipeBack.call(this); },

  // ---- 右滑返回手势 ----
  onTouchStart(e) { swipeBack.onTouchStart.call(this, e); },
  onTouchEnd(e) { swipeBack.onTouchEnd.call(this, e); },

  /**
   * 输入框内容变化时更新 keyword
   */
  onInput(e) {
    this.setData({ keyword: e.detail.value });
  },

  /**
   * 触发搜索（用户回车或点击搜索按钮）
   * 重置页码和结果列表，标记已搜索
   */
  onSearch() {
    this.setData({ page: 1, results: [], searched: true });
    this.doSearch();
  },

  /**
   * 执行搜索请求
   */
  doSearch() {
    const { keyword, page } = this.data;
    // 空关键词不搜索
    if (!keyword.trim()) return;

    api.searchDocuments({ q: keyword, page, page_size: 20 }).then(res => {
      // 合并结果
      const list = this.data.results.concat(res.items);
      this.setData({
        results: list,
        total: res.total,
        hasMore: list.length < res.total
      });
    }).catch(() => {
      wx.showToast({ title: '搜索失败', icon: 'none' });
    });
  },

  /**
   * 加载更多搜索结果
   */
  loadMore() {
    if (!this.data.hasMore) return;
    this.setData({ page: this.data.page + 1 });
    this.doSearch();
  },

  /**
   * 返回上一页
   */
  goBack() { wx.navigateBack(); },

  onShareAppMessage() {
    return { title: "卫健委政策速查", path: "/pages/index/index" };
  },
});
