const api = require('../../utils/api');
const storage = require('../../utils/storage');

Page({
  data: {
    doc: {},
    summary: [],
    attachments: [],
    isFav: false,
    loading: true
  },

  onLoad(options) {
    const id = parseInt(options.id);
    api.getDocumentDetail(id).then(doc => {
      let summary = [];
      let attachments = [];
      try { summary = JSON.parse(doc.summary || '[]'); } catch(e) {}
      try { attachments = JSON.parse(doc.attachments || '[]'); } catch(e) {}

      this.setData({
        doc,
        summary,
        attachments,
        isFav: storage.isFavorited(doc.id),
        loading: false
      });
    }).catch(() => {
      this.setData({ loading: false });
      wx.showToast({ title: '加载失败', icon: 'none' });
    });
  },

  toggleFav() {
    const added = storage.toggleFavorite(this.data.doc);
    this.setData({ isFav: added });
    wx.showToast({
      title: added ? '已加入收藏' : '已取消收藏',
      icon: 'none',
      duration: 1500
    });
  },

  openOriginal() {
    if (this.data.doc.original_url) {
      wx.setClipboardData({
        data: this.data.doc.original_url,
        success: () => wx.showToast({ title: '链接已复制', icon: 'none' })
      });
    }
  },

  openAttachment(e) {
    const url = e.currentTarget.dataset.url;
    wx.setClipboardData({
      data: url,
      success: () => wx.showToast({ title: '链接已复制', icon: 'none' })
    });
  }
});
