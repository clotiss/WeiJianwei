const api = require('../../utils/api');

Page({
  data: {
    keyword: '',
    results: [],
    total: 0,
    page: 1,
    hasMore: false,
    searched: false
  },

  onInput(e) { this.setData({ keyword: e.detail.value }); },

  onSearch() {
    this.setData({ page: 1, results: [], searched: true });
    this.doSearch();
  },

  doSearch() {
    const { keyword, page } = this.data;
    if (!keyword.trim()) return;
    api.searchDocuments({ q: keyword, page, page_size: 20 }).then(res => {
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

  loadMore() {
    if (!this.data.hasMore) return;
    this.setData({ page: this.data.page + 1 });
    this.doSearch();
  },

  goBack() { wx.navigateBack(); }
});
