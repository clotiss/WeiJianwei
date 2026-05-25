const storage = require('../../utils/storage');

Page({
  data: { favorites: [] },

  onShow() {
    this.setData({ favorites: storage.getFavorites() });
  },

  goBack() { wx.navigateBack(); }
});
