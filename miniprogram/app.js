App({
  onLaunch() {
    const favs = wx.getStorageSync('favorites') || [];
    this.globalData.favorites = favs;
  },
  globalData: {
    API_BASE: 'http://localhost:8000/api/v1',
    favorites: []
  }
});
