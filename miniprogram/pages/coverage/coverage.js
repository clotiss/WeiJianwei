const api = require('../../utils/api');
const names = require('../../config/regions');
Page({
  data:{sources:[], loading:true, loadError:false, errorText:''},
  onLoad() { return this.fetchCoverage(); },
  onUnload() { this._request++; },
  onPullDownRefresh() { return this.fetchCoverage().finally(() => wx.stopPullDownRefresh()); },
  fetchCoverage() {
    const id = this._request = (this._request || 0) + 1;
    if (!api.useV2()) { this.setData({loading:false, loadError:true, errorText:'来源详情将在新版中开放'}); return Promise.resolve(); }
    this.setData({loading:true, loadError:false});
    return Promise.all([api.getSourceInventory(), api.getCoverage()]).then(([inventory, coverage]) => {
      if (id !== this._request) return;
      const runtime = new Map(coverage.map(item => [item.id, item]));
      const sources = inventory.sources.filter(item => (runtime.get(item.id) || {}).documents > 0).map(item => {
        const state = runtime.get(item.id);
        return {id:item.id, name:item.name, regionName:names[item.region] || item.region,
          documents:state.documents,
          kind:item.kind === 'interpretation' ? '政策解读' : '规范性文件'};
      });
      this.setData({sources, loading:false});
    }).catch(error => {
      if (id === this._request) this.setData({loading:false, loadError:true, errorText:api.errorMessage(error)});
    });
  }
});
