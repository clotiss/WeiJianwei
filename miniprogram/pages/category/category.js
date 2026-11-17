const api = require('../../utils/api');
const filters = require('../../utils/filters');
const lists = require('../../utils/paged-list');
const swipeBack = require('../../utils/swipe-back');
Page({
  data:{contentStatus:{},filters:{}, scope:'', documents:[], total:0, page:1, hasMore:false, loading:false, loadError:false, errorText:''},
  onLoad(options) {
    swipeBack.initSwipeBack.call(this);
    const value = filters.fromRoute(options);
    this.setData({filters:value, scope:filters.label(value)});
    return this.fetchList();
  },
  onUnload() { this._listRequest++; },
  fetchList(nextPage = 1) { return lists.load(this, 'documents', page => api.getDocuments({...this.data.filters, page, page_size:20}), typeof nextPage === 'number' ? nextPage : 1); },
  loadMore() { if (!this.data.loading && this.data.hasMore) return this.fetchList(this.data.page + 1); },
  onReachBottom() { return this.loadMore(); },
  onPullDownRefresh() { return this.fetchList().finally(() => wx.stopPullDownRefresh()); },
  onTouchStart(e) { swipeBack.onTouchStart.call(this, e); },
  onTouchEnd(e) { swipeBack.onTouchEnd.call(this, e); },
  goBack() { wx.navigateBack(); },
  onShareAppMessage() { return {title:'卫健委政策速查', path:'/pages/index/index'}; }
});
