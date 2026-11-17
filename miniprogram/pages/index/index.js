const api = require('../../utils/api');
const filters = require('../../utils/filters');

Page({
  data: {
    sheetOpen:false, sheetMode:'region', sheetValue:{}, days:0, filterCount:0, quickTopics:[], useV2:false, categories:[], categoryRow1:[], categoryRow2:[], categoriesError:false,
    regions:[{code:'CN', name:'国家卫健委'}], regionIndex:0, activeRegion:'CN', includeNational:true,
    regionsLoading:false, regionsError:false,
    docTypes:['全部类型', '规范性文件', '政策解读'], activeCategory:'全部', activeType:'全部类型',
    documents:[], total:0, page:1, hasMore:true, loading:true, loadError:false, errorText:'',
    contentStatus:{}, collectionShort:'', collectionUpdate:'', updateNotice:'', latestUpdate:'',
    showChat:false, floatBtnX:0, floatBtnY:0, floatBtnMoving:false
  },
  onLoad() {
    this.setData({useV2:api.useV2()});
    if (this.data.useV2) this.fetchRegions();

  },
  onShow() {
    if (!this.data.categories.length) this.fetchCategories();
    if (this.selectAllComponents) this.selectAllComponents('file-card').forEach(card => card.refreshFavorite());
    if (!this._loaded) { this._loaded=true; this.fetchDocuments({reset:true}); this.fetchLatestUpdate(); }
  },
  onHide() { if(this.data.sheetOpen)this.closeSheet(); },
  onUnload() { this._listRequest++; this._latestRequest++; },
  onPullDownRefresh() {
    return Promise.all([this.fetchDocuments({reset:true}), this.fetchLatestUpdate(),
      this.fetchCategories(), this.data.useV2 ? this.fetchRegions() : Promise.resolve()])
      .finally(() => wx.stopPullDownRefresh());
  },
  currentFilters() {
    return {region:this.data.activeRegion, include_national:this.data.includeNational,
      category:this.data.activeCategory, doc_type:this.data.activeType, published_since:filters.since(this.data.days)};
  },
  fetchRegions() {
    this.setData({regionsLoading:true, regionsError:false});
    return api.getRegions().then(items => {
      const regions = items.filter(item => item.code);
      this.setData({regions, regionIndex:Math.max(0, regions.findIndex(item => item.code === this.data.activeRegion)), regionsLoading:false});
    }).catch(() => this.setData({regionsLoading:false, regionsError:true}));
  },
  fetchCategories() {
    return api.getCategories().then(res => {
      const all = ['全部', ...(res.categories || [])];
      const mid = Math.ceil(all.length / 2);
      this.setData({categories:all, categoryRow1:all.slice(0, mid), categoryRow2:all.slice(mid), quickTopics:all.filter(item => item === '全部' || item === '医疗服务与质量安全' || item === '妇幼健康与人口发展').map(item => ({value:item,label:item === '全部' ? '全部主题' : item === '医疗服务与质量安全' ? '医疗服务' : '妇幼健康'})), categoriesError:false});
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
        loading:false, contentStatus:res.contentStatus || {}, collectionUpdate:stamp, collectionShort:stamp.slice(5),
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
    const next={...this.data,...patch};
    this.setData({...patch, filterCount:(next.activeCategory !== '全部' ? 1 : 0)+(next.activeType !== '全部类型' ? 1 : 0)+(next.days ? 1 : 0), page:1, documents:[], total:0, contentStatus:{}, latestUpdate:'', collectionShort:'', collectionUpdate:'', updateNotice:''});
    return Promise.all([this.fetchDocuments({reset:true}), this.fetchLatestUpdate()]);
  },
  openRegion() { this.openSheet('region'); },
  openFilters() { this.openSheet('filter'); },
  openSheet(mode) { wx.hideTabBar({animation:false}); this.setData({sheetOpen:true, sheetMode:mode, sheetValue:{...this.currentFilters(),days:this.data.days}}); },
  closeSheet() { this.setData({sheetOpen:false}); wx.showTabBar({animation:false}); },
  applySheet(e) {
    const value=e.detail, index=this.data.regions.findIndex(item => item.code === value.region);
    this.closeSheet();
    return this.resetFilters({activeRegion:value.region,regionIndex:Math.max(0,index),includeNational:value.include_national,activeCategory:value.category,activeType:value.doc_type,days:value.days,filterCount:(value.category !== '全部' ? 1 : 0)+(value.doc_type !== '全部类型' ? 1 : 0)+(value.days ? 1 : 0)});
  },
  clearFilters() {return this.resetFilters({activeCategory:'全部',activeType:'全部类型',days:0,filterCount:0});},
  goFollow() { wx.switchTab({url:'/pages/follow/follow'}); },
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
