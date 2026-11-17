const api = require('../../utils/api');
const storage = require('../../utils/storage');
const swipeBack = require('../../utils/swipe-back');
Page({
  data:{favorites:[], useV2:false, loading:false, loadError:false, errorText:''},
  onLoad() { swipeBack.initSwipeBack.call(this); this.setData({useV2:api.useV2()}); },
  onShow() { return this.fetchFavorites(); },
  onUnload() { this._request++; },
  fetchFavorites() {
    if (!this.data.useV2) { this.setData({favorites:storage.getFavorites()}); return Promise.resolve(); }
    const id = this._request = (this._request || 0) + 1;
    // Do not show a previous account's results while establishing a new session.
    this.setData({loading:true, loadError:false, favorites:[]});
    return api.getV2Favorites().then(favorites => {
      if (id === this._request) this.setData({favorites, loading:false});
    }).catch(error => {
      if (id === this._request) this.setData({loading:false, loadError:true, errorText:api.errorMessage(error, '收藏加载失败，请重试')});
    });
  },
  onPullDownRefresh() { return this.fetchFavorites().finally(() => wx.stopPullDownRefresh()); },
  onTouchStart(e) { swipeBack.onTouchStart.call(this, e); },
  onTouchEnd(e) { swipeBack.onTouchEnd.call(this, e); },
  goBack() { wx.navigateBack(); },
  onShareAppMessage() { return {title:'卫健委政策速查', path:'/pages/index/index'}; }
});
