const api = require('../../utils/api');
const reading = require('../../utils/reading');
const swipeBack = require('../../utils/swipe-back');
Page({
  data:{largeText:false,title:'', content:'', loading:true, loadError:false, errorText:''},
  onLoad(options) { this.setData({largeText:reading.large()}); swipeBack.initSwipeBack.call(this); this.documentId = Number(options.id); return this.fetchContent(); },
  onUnload() { this._request++; },
  fetchContent() {
    const id = this._request = (this._request || 0) + 1;
    this.setData({loading:true, loadError:false});
    return api.getDocumentDetail(this.documentId).then(doc => {
      if (id === this._request) this.setData({title:doc.title, content:doc.content || '暂未收录正文，请返回详情查看官网原文。', loading:false});
    }).catch(error => {
      if (id === this._request) this.setData({loading:false, loadError:true, errorText:api.errorMessage(error)});
    });
  },
  onTouchStart(e) { swipeBack.onTouchStart.call(this, e); },
  onTouchEnd(e) { swipeBack.onTouchEnd.call(this, e); },
  onShareAppMessage() { return {title:'卫健委政策速查', path:'/pages/index/index'}; }
});
