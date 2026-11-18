const api = require('../../utils/api');
const summaryState = require('../../utils/summary-state');
const reading = require('../../utils/reading');
const storage = require('../../utils/storage'); // V1 only; IDs must never cross databases.
const swipeBack = require('../../utils/swipe-back');
function array(value) {
  try { const parsed = typeof value === 'string' ? JSON.parse(value) : value; return Array.isArray(parsed) ? parsed : []; } catch (_) { return []; }
}
Page({
  data:{activeTab:'要点',largeText:false,doc:{}, summary:[], summaryView:{}, summaryRefreshing:false, summaryError:'', attachments:[], isFav:false, favKnown:false, favBusy:false, favError:'', useV2:false, loading:true, loadError:false, errorText:''},
  onLoad(options) {
    swipeBack.initSwipeBack.call(this);
    this.documentId = Number(options.id);
    this.setData({useV2:api.useV2(),largeText:reading.large()});
    return this.fetchDetail();
  },
  onShow() { this._hidden=false; this.scheduleSummary(); if (this.data.doc.id) return this.refreshFavorite(); },
  onHide() { this._hidden=true; clearTimeout(this._summaryTimer); },
  onUnload() { this._disposed=true; this._detailRequest++; this._favoriteRequest++; clearTimeout(this._summaryTimer); },
  applyDetail(doc) {
    const points = doc.summary_points && doc.summary_points.length ? doc.summary_points : array(doc.summary).map(text => ({text}));
    this.setData({doc, summary:points.map(point => ({...point,expanded:false})), summaryView:summaryState.view(doc.summary_status),
      attachments:array(doc.attachments), loading:false});
    this.scheduleSummary();
  },
  scheduleSummary() {
    clearTimeout(this._summaryTimer);
    if (this._hidden || this._disposed || !this.data.summaryView.poll || (this._summaryPolls || 0) >= 12) return;
    this._summaryTimer=setTimeout(() => {this._summaryPolls=(this._summaryPolls || 0)+1; this.refreshSummary(true);},8000);
  },
  refreshSummary(automatic) {
    if (this.data.summaryRefreshing || this._disposed) return Promise.resolve();
    if (automatic !== true) this._summaryPolls=0;
    const requestId=this._detailRequest=(this._detailRequest || 0)+1;
    this.setData({summaryRefreshing:true,summaryError:''});
    return api.getDocumentDetail(this.documentId).then(doc => {
      if (requestId === this._detailRequest && !this._disposed) this.applyDetail(doc);
    }).catch(() => {
      if (!this._disposed) {this.setData({summaryError:'暂时无法刷新，请稍后再试'});this.scheduleSummary();}
    }).finally(() => {if (!this._disposed) this.setData({summaryRefreshing:false});});
  },
  toggleEvidence(e) {
    const index=Number(e.currentTarget.dataset.index);
    this.setData({summary:this.data.summary.map((point,i) => i === index ? {...point,expanded:!point.expanded} : point)});
  },
  fetchDetail() {
    if (!Number.isSafeInteger(this.documentId) || this.documentId < 1) {
      this.setData({loading:false, loadError:true, errorText:'文件编号无效'});
      return Promise.resolve();
    }
    const requestId = this._detailRequest = (this._detailRequest || 0) + 1;
    this.setData({loading:true, loadError:false});
    return api.getDocumentDetail(this.documentId).then(doc => {
      if (requestId !== this._detailRequest) return;
      this.applyDetail(doc);
      reading.record(doc);
      return this.refreshFavorite();
    }).catch(error => {
      if (requestId === this._detailRequest) this.setData({loading:false, loadError:true, errorText:api.errorMessage(error)});
    });
  },
  refreshFavorite(force = false) {
    if (!this.data.useV2) {
      this.setData({isFav:storage.isFavorited(this.data.doc.id), favKnown:true});
      return Promise.resolve();
    }
    if (this.data.favBusy || (!force && !api.hasV2Session())) return Promise.resolve();
    const requestId = this._favoriteRequest = (this._favoriteRequest || 0) + 1;
    this.setData({favBusy:true, favError:''});
    return api.getV2Favorites().then(items => {
      if (requestId === this._favoriteRequest) this.setData({isFav:items.some(item => item.id === this.data.doc.id), favKnown:true, favBusy:false});
    }).catch(error => {
      if (requestId === this._favoriteRequest) this.setData({favKnown:false, favBusy:false, favError:api.errorMessage(error, '收藏状态读取失败，点击重试')});
    });
  },
  retryFavorite() { return this.refreshFavorite(true); },
  toggleFav() {
    if (this.data.loading || this.data.loadError || this.data.favBusy || !this.data.doc.id) return;
    if (!this.data.useV2) {
      const added = storage.toggleFavorite(this.data.doc);
      this.setData({isFav:added});
      wx.showToast({title:added ? '已加入收藏' : '已取消收藏', icon:'none'});
      return Promise.resolve();
    }
    // When the state is unknown, "收藏" means idempotently save, never accidentally remove.
    const target = this.data.favKnown ? !this.data.isFav : true;
    const requestId = this._favoriteRequest = (this._favoriteRequest || 0) + 1;
    this.setData({favBusy:true, favError:''});
    return api.syncV2Favorite(this.data.doc.id, target).then(() => {
      if (requestId !== this._favoriteRequest) return;
      this.setData({isFav:target, favKnown:true, favBusy:false});
      wx.showToast({title:target ? '已加入账号收藏' : '已取消收藏', icon:'none'});
    }).catch(error => {
      if (requestId !== this._favoriteRequest) return;
      // The write could have reached the server before a network timeout. Re-read before another toggle.
      this.setData({favBusy:false, favKnown:false, favError:api.errorMessage(error, '未能确认收藏结果，请重试读取状态')});
    });
  },
  selectTab(e) {this.setData({activeTab:e.currentTarget.dataset.tab});},
  showBody(){this.setData({activeTab:'正文'});},
  openPlaintext() { wx.navigateTo({url:`/pages/plaintext/plaintext?id=${this.data.doc.id}`}); },
  copyLink(url, title) {
    if (!/^https?:\/\//i.test(url || '')) return;
    wx.showModal({title, content:url, confirmText:'复制链接', cancelText:'关闭', success:res => {
      if (res.confirm) wx.setClipboardData({data:url});
    }});
  },
  openOriginal() { this.copyLink(this.data.doc.original_url, '复制官网链接，在浏览器查看'); },
  openAttachment(e) { this.copyLink(e.currentTarget.dataset.url, '复制附件链接，在浏览器打开'); },
  onTouchStart(e) { swipeBack.onTouchStart.call(this, e); },
  onTouchEnd(e) { swipeBack.onTouchEnd.call(this, e); },
  onShareAppMessage() { return {title:'卫健委政策速查', path:'/pages/index/index'}; }
});
