/**
 * ===========================================================================
 * 首页 — 政策文件列表 + 分类筛选 + 搜索入口
 * ===========================================================================
 *
 * 本页面是小程序的首页（主入口），功能包括：
 * 1. 文件列表展示（分页加载，上滑加载更多）
 * 2. 分类标签筛选（顶部横向滚动的领域标签）
 * 3. 文件类型切换（规范性文件 / 政策解读 / 全部）
 * 4. 最新发布时间提示
 * 5. 订阅消息引导（首次打开弹窗）
 * 6. 下拉刷新
 *
 * 页面生命周期：
 *   onLoad → onShow → [用户交互] → onHide → onShow → ...
 *
 * 数据流：
 *   后端 API → setData → WXML 自动渲染 → 用户操作 → 重新请求
 */

const api = require('../../utils/api');          // API 请求工具
const storage = require('../../utils/storage');   // 本地存储工具
const app = getApp();                             // 全局 App 实例

Page({
  /**
   * data — 页面的响应式数据
   * 修改 data 必须通过 this.setData({...}) 触发 WXML 重新渲染
   */
  data: {
    categories: [],                // 所有分类名称数组
    docTypes: ['全部类型', '规范性文件', '政策解读'],  // 类型筛选选项
    activeCategory: '全部',        // 当前选中的分类
    activeType: '全部类型',        // 当前选中的文件类型
    documents: [],                 // 当前显示的文件列表
    page: 1,                       // 当前页码
    hasMore: true,                 // 是否还有更多数据
    loading: true,                 // 是否正在加载中
    latestUpdate: ''               // 最新文件发布时间
  },

  // =========================================================================
  // 生命周期：页面加载时执行（只执行一次）
  // =========================================================================
  onLoad() {
    // 页面初始化时先加载分类列表
    this.fetchCategories();
  },

  // =========================================================================
  // 生命周期：页面显示时执行（每次切换到该页面都会触发）
  // 包括首次进入、从其他页面返回、从后台切回前台
  // =========================================================================
  onShow() {
    // 分类列表为空时重试（可能首次加载失败）
    if (this.data.categories.length === 0) {
      this.fetchCategories();
    }

    // ---- 首次打开引导订阅消息 ----
    // 检查本地标记，只在用户首次使用时展示
    const hasShownGuide = wx.getStorageSync('subscription_guide_shown');
    if (!hasShownGuide) {
      wx.showModal({
        title: '开启新文件提醒',
        content: '每日上午9:00推送昨日新增政策文件，不再错过重要通知',
        cancelText: '暂不需要',
        confirmText: '去开启',
        success: (res) => {
          if (res.confirm) {
            // 用户点击"去开启"，请求订阅消息授权
            // 注意：YOUR_TEMPLATE_ID 需要替换为微信公众平台申请的模板 ID
            wx.requestSubscribeMessage({
              tmplIds: ['YOUR_TEMPLATE_ID'],
              success: () => {},
              fail: () => wx.showToast({ title: '订阅失败', icon: 'none' })
            });
          }
          // 无论用户是否订阅，都标记"已展示引导"，下次不再弹出
          wx.setStorageSync('subscription_guide_shown', true);
        }
      });
    }

    // 每次显示页面时重新加载数据（确保数据新鲜）
    // 重置为第 1 页，清空现有列表
    this.setData({ page: 1, documents: [], hasMore: true });
    this.fetchDocuments();       // 加载文件列表
    this.fetchLatestUpdate();    // 加载最新发布时间
  },

  // =========================================================================
  // 下拉刷新 — 用户从顶部下拉时触发
  // 需要配合 index.json 中设置 enablePullDownRefresh: true
  // =========================================================================
  onPullDownRefresh() {
    // 重置为第 1 页
    this.setData({ page: 1, documents: [], hasMore: true });
    // Promise.all 并行请求，两个都完成后再停止下拉动画
    Promise.all([this.fetchDocuments(), this.fetchLatestUpdate()])
      .finally(() => wx.stopPullDownRefresh());
  },

  // =========================================================================
  // 数据获取方法
  // =========================================================================

  /**
   * 获取分类列表
   * 从后端获取所有已有分类，拆分为两行用于首页布局
   */
  fetchCategories() {
    api.getCategories().then(res => {
      // 在分类列表前面加上"全部"选项
      const all = ['全部', ...(res.categories || [])];
      // 将分类列表分为两行（首页双行横向滚动布局）
      const mid = Math.ceil(all.length / 2);
      this.setData({
        categories: all,
        categoryRow1: all.slice(0, mid),   // 第一行
        categoryRow2: all.slice(mid)        // 第二行
      });
    }).catch(() => {});  // 加载失败静默处理
  },

  /**
   * 获取文件列表（分页）
   * 首页显示和筛选/分页切换都调用此方法
   */
  fetchDocuments() {
    this.setData({ loading: true });
    const { activeCategory, activeType, page } = this.data;

    return api.getDocuments({
      category: activeCategory,
      doc_type: activeType,
      page,
      page_size: 20    // 每页 20 条
    }).then(res => {
      // 将新数据追加到现有列表末尾（上滑加载更多时）
      const docs = this.data.documents.concat(res.items);
      this.setData({
        documents: docs,
        hasMore: docs.length < res.total,  // 当前数量 < 总数 = 还有更多
        loading: false
      });
    }).catch(() => {
      this.setData({ loading: false });
      wx.showToast({ title: '网络异常', icon: 'none' });
    });
  },

  /**
   * 获取最新文件发布时间
   * 展示在首页顶部，让用户感知数据新鲜度
   */
  fetchLatestUpdate() {
    return api.getLatestUpdate().then(res => {
      const ts = res.latest_update || '';
      // 只取日期部分（前 10 字符 YYYY-MM-DD）
      this.setData({ latestUpdate: ts ? ts.slice(0, 10) : '' });
    });
  },

  // =========================================================================
  // 用户交互事件
  // =========================================================================

  /**
   * 分类标签点击
   * e.currentTarget.dataset.category 从 wxml 的 data-category 属性获取
   */
  onCategoryTap(e) {
    const cat = e.currentTarget.dataset.category;
    // 切换分类时重置页码并清空列表
    this.setData({ activeCategory: cat, page: 1, documents: [] });
    this.fetchDocuments();  // 重新加载
  },

  /**
   * 文件类型切换（全部 / 规范性文件 / 政策解读）
   */
  onTypeTap(e) {
    const type = e.currentTarget.dataset.type;
    this.setData({ activeType: type, page: 1, documents: [] });
    this.fetchDocuments();
  },

  /**
   * 上滑加载更多
   * 增加页码 → 调用 fetchDocuments() 追加数据
   */
  loadMore() {
    if (!this.data.hasMore) return;  // 没有更多了就返回
    this.setData({ page: this.data.page + 1 });  // 页码+1
    this.fetchDocuments();                          // 加载下一页
  },

  /**
   * 打开订阅消息授权
   */
  openSubscribe() {
    wx.requestSubscribeMessage({
      tmplIds: ['YOUR_TEMPLATE_ID'],
      success: () => wx.showToast({ title: '订阅成功', icon: 'success' }),
      fail: () => wx.showToast({ title: '订阅失败', icon: 'none' })
    });
  },

  // =========================================================================
  // 页面跳转
  // =========================================================================
  goSearch() {
    wx.navigateTo({ url: '/pages/search/search' });
  },
  goFavorites() {
    wx.navigateTo({ url: '/pages/favorites/favorites' });
  },
  goCategory() {
    // 跳转到分类列表页，携带当前筛选条件
    wx.navigateTo({
      url: `/pages/category/category?category=${this.data.activeCategory}&doc_type=${this.data.activeType}`
    });
  }
});
