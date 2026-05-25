const api = require('../../utils/api');

Page({
  data: {
    category: '',
    docType: '',
    documents: [],
    total: 0,
    page: 1,
    hasMore: false
  },

  onLoad(options) {
    const category = options.category || '全部';
    const docType = options.doc_type || '全部类型';
    this.setData({ category, docType });
    this.fetchList();
  },

  fetchList() {
    const { category, docType, page } = this.data;
    api.getDocuments({ category, doc_type: docType, page, page_size: 20 }).then(res => {
      const list = this.data.documents.concat(res.items);
      this.setData({
        documents: list,
        total: res.total,
        hasMore: list.length < res.total
      });
    });
  },

  loadMore() {
    if (!this.data.hasMore) return;
    this.setData({ page: this.data.page + 1 });
    this.fetchList();
  },

  goBack() { wx.navigateBack(); }
});
