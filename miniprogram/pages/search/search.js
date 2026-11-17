const api = require('../../utils/api');
const filters = require('../../utils/filters');
const lists = require('../../utils/paged-list');
const swipeBack = require('../../utils/swipe-back');
Page({
  data:{keyword:'', query:'', filters:{}, scope:'', results:[], total:0, page:1, hasMore:false, searched:false, loading:false, loadError:false, errorText:''},
  onLoad(options) {
    swipeBack.initSwipeBack.call(this);
    const value = filters.fromRoute(options);
    this.setData({filters:value, scope:filters.label(value)});
  },
  onUnload() { this._listRequest++; },
  onInput(e) { this.setData({keyword:e.detail.value}); },
  onSearch() {
    const query = this.data.keyword.trim();
    this._listRequest = (this._listRequest || 0) + 1;
    this.setData({query, page:1, results:[], total:0, hasMore:false, searched:!!query, loading:false, loadError:false});
    if (query) return this.doSearch();
  },
  doSearch(nextPage = 1) {
    if (!this.data.query) return Promise.resolve();
    return lists.load(this, 'results', page => api.searchDocuments({...this.data.filters, q:this.data.query, page, page_size:20}), typeof nextPage === 'number' ? nextPage : 1);
  },
  loadMore() { if (!this.data.loading && this.data.hasMore) return this.doSearch(this.data.page + 1); },
  onReachBottom() { return this.loadMore(); },
  onTouchStart(e) { swipeBack.onTouchStart.call(this, e); },
  onTouchEnd(e) { swipeBack.onTouchEnd.call(this, e); },
  goBack() { wx.navigateBack(); },
  onShareAppMessage() { return {title:'卫健委政策速查', path:'/pages/index/index'}; }
});
