const api = require('../../utils/api');
const filters = require('../../utils/filters');

Page({
  data: {
    useV2:false, categories:[], categoryRow1:[], categoryRow2:[], categoriesError:false,
    regions:[{code:'', name:'全国'}], regionIndex:0, activeRegion:'', includeNational:true,
    regionsLoading:false, regionsError:false,
    docTypes:['全部类型', '规范性文件', '政策解读'], activeCategory:'全部', activeType:'全部类型',
    documents:[], total:0, page:1, hasMore:true, loading:true, loadError:false, errorText:'',
    collectionUpdate:'', updateNotice:'', latestUpdate:'',
    showChat:false, floatBtnX:0, floatBtnY:0, floatBtnMoving:false
  },
  onLoad() {
    this.setData({useV2:api.useV2()});
    if (this.data.useV2) this.fetchRegions();
    else {
      const sys = wx.getSystemInfoSync();
      this.setData({floatBtnX:sys.windowWidth - 72, floatBtnY:sys.windowHeight - 176});
    }
  },
  onShow() {
    if (!this.data.categories.length) this.fetchCategories();
    this.fetchDocuments({reset:true});
    this.fetchLatestUpdate();
  },
  onUnload() { this._listRequest++; this._latestRequest++; },
  onPullDownRefresh() {
    return Promise.all([this.fetchDocuments({reset:true}), this.fetchLatestUpdate(),
      this.fetchCategories(), this.data.useV2 ? this.fetchRegions() : Promise.resolve()])
      .finally(() => wx.stopPullDownRefresh());
  },
  currentFilters() {
    return {region:this.data.activeRegion, include_national:this.data.includeNational,
      category:this.data.activeCategory, doc_type:this.data.activeType};
  },
  fetchRegions() {
    this.setData({regionsLoading:true, regionsError:false});
    return api.getRegions().then(items => {
      const regions = [{code:'', name:'全国'}, ...items];
      this.setData({regions, regionIndex:Math.max(0, regions.findIndex(item => item.code === this.data.activeRegion)), regionsLoading:false});
    }).catch(() => this.setData({regionsLoading:false, regionsError:true}));
  },
  fetchCategories() {
    return api.getCategories().then(res => {
      const all = ['全部', ...(res.categories || [])];
      const mid = Math.ceil(all.length / 2);
      this.setData({categories:all, categoryRow1:all.slice(0, mid), categoryRow2:all.slice(mid), categoriesError:false});
    }).catch(() => this.setData({categoriesError:true}));
  },
  fetchDocuments({reset = false, nextPage} = {}) {
    const requestId = this._listRequest = (this._listRequest || 0) + 1;
    const page = reset ? 1 : (nextPage || this.data.page);
    this.setData({loading:true, loadError:false, errorText:''});
    return api.getDocuments({...this.currentFilters(), page, page_size:20}).then(res => {
      if (requestId !== this._listRequest) return;
      const docs = page === 1 ? res.items : this.data.documents.concat(res.items);
      const freshness = res.freshness || {};
      const checked = freshness.last_success ? new Date(freshness.last_success * 1000) : null;
      const stamp = checked ? `${checked.getFullYear()}-${String(checked.getMonth() + 1).padStart(2, '0')}-${String(checked.getDate()).padStart(2, '0')} ${String(checked.getHours()).padStart(2, '0')}:${String(checked.getMinutes()).padStart(2, '0')}` : '';
      this.setData({documents:docs, total:res.total, page, hasMore:docs.length < res.total && res.items.length > 0,
        loading:false, collectionUpdate:stamp,
        updateNotice:freshness.unavailable_sources ? '部分来源更新暂时失败，已收录内容仍可阅读' : ''});
    }).catch(error => {
      if (requestId !== this._listRequest) return;
      this.setData({loading:false, loadError:true, errorText:api.errorMessage(error)});
      wx.showToast({title:this.data.documents.length ? '更新失败，保留已加载内容' : api.errorMessage(error), icon:'none'});
    });
  },
  retryDocuments() { return this.fetchDocuments({reset:true}); },
  fetchLatestUpdate() {
    const requestId = this._latestRequest = (this._latestRequest || 0) + 1;
    return api.getLatestUpdate(this.currentFilters()).then(res => {
      if (requestId !== this._latestRequest) return;
      this.setData({latestUpdate:(res.latest_update || '').slice(0, 10)});
    }).catch(() => {});
  },
  resetFilters(patch) {
    this.setData({...patch, page:1, documents:[], total:0, latestUpdate:'', collectionUpdate:'', updateNotice:''});
    return Promise.all([this.fetchDocuments({reset:true}), this.fetchLatestUpdate()]);
  },
  onRegionChange(e) {
    const index = Number(e.detail.value), region = this.data.regions[index];
    if (region) return this.resetFilters({regionIndex:index, activeRegion:region.code});
  },
  onNationalChange(e) { return this.resetFilters({includeNational:!!e.detail.value}); },
  onCategoryTap(e) { return this.resetFilters({activeCategory:e.currentTarget.dataset.category}); },
  onTypeTap(e) { return this.resetFilters({activeType:e.currentTarget.dataset.type}); },
  loadMore() { if (!this.data.loading && this.data.hasMore) return this.fetchDocuments({nextPage:this.data.page + 1}); },
  onReachBottom() { return this.loadMore(); },
  onFloatBtnTap() { if (!this.data.useV2 && !this.data.floatBtnMoving) this.setData({showChat:true}); },
  onFloatBtnMove(e) { this.setData({floatBtnX:e.detail.x, floatBtnY:e.detail.y, floatBtnMoving:true}); },
  onFloatBtnEnd() { setTimeout(() => this.setData({floatBtnMoving:false}), 200); },
  onChatClose() { this.setData({showChat:false}); },
  goSearch() { wx.navigateTo({url:'/pages/search/search?' + filters.toQuery(this.currentFilters())}); },
  goFavorites() { wx.navigateTo({url:'/pages/favorites/favorites'}); },
  goCategory() { wx.navigateTo({url:'/pages/category/category?' + filters.toQuery(this.currentFilters())}); },
  goCoverage() { wx.navigateTo({url:'/pages/coverage/coverage'}); },
  onShareAppMessage() { return {title:'卫健委政策速查', path:'/pages/index/index'}; }
});
