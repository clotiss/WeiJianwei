const api = require('../../utils/api');
const storage = require('../../utils/storage');
const app = getApp();

Page({
  data: {
    categories: ['全部', '医政管理', '疾控', '妇幼健康', '基层卫生', '药政', '医管', '其他'],
    docTypes: ['全部类型', '规范性文件', '政策解读', '通知公告'],
    activeCategory: '全部',
    activeType: '全部类型',
    documents: [],
    page: 1,
    hasMore: true,
    loading: true,
    latestUpdate: ''
  },

  onShow() {
    this.setData({ page: 1, documents: [], hasMore: true });
    this.fetchDocuments();
    this.fetchLatestUpdate();
  },

  onPullDownRefresh() {
    this.setData({ page: 1, documents: [], hasMore: true });
    Promise.all([this.fetchDocuments(), this.fetchLatestUpdate()])
      .finally(() => wx.stopPullDownRefresh());
  },

  fetchDocuments() {
    this.setData({ loading: true });
    const { activeCategory, activeType, page } = this.data;
    return api.getDocuments({
      category: activeCategory,
      doc_type: activeType,
      page,
      page_size: 20
    }).then(res => {
      const docs = this.data.documents.concat(res.items);
      this.setData({
        documents: docs,
        hasMore: docs.length < res.total,
        loading: false
      });
    }).catch(() => {
      this.setData({ loading: false });
      wx.showToast({ title: '网络异常', icon: 'none' });
    });
  },

  fetchLatestUpdate() {
    return api.getLatestUpdate().then(res => {
      this.setData({ latestUpdate: res.latest_update || '' });
    });
  },

  onCategoryTap(e) {
    const cat = e.currentTarget.dataset.category;
    this.setData({ activeCategory: cat, page: 1, documents: [] });
    this.fetchDocuments();
  },

  onTypeTap(e) {
    const type = e.currentTarget.dataset.type;
    this.setData({ activeType: type, page: 1, documents: [] });
    this.fetchDocuments();
  },

  loadMore() {
    if (!this.data.hasMore) return;
    this.setData({ page: this.data.page + 1 });
    this.fetchDocuments();
  },

  goSearch() {
    wx.navigateTo({ url: '/pages/search/search' });
  },
  goFavorites() {
    wx.navigateTo({ url: '/pages/favorites/favorites' });
  },
  goCategory() {
    wx.navigateTo({
      url: `/pages/category/category?category=${this.data.activeCategory}&doc_type=${this.data.activeType}`
    });
  }
});
