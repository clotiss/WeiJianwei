const api = require('../../utils/api');
const names = require('../../config/regions');
const histories={not_started:'尚未开始回填',running:'历史回填中',blocked:'历史回填受阻，等待重试',complete:'首轮回填完成'};
const statuses = {paused:'未启用监控', cooling_down:'更新受阻，等待重试', error:'最近更新失败', active:'监控已启用'};
Page({
  data:{sources:[], loading:true, loadError:false, errorText:'', provinceCount:0, enabledCount:0},
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
      const sources = inventory.sources.map(item => {
        const state = runtime.get(item.id);
        const date = state && state.last_success ? new Date(state.last_success * 1000) : null;
        const lastSuccess = date ? `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}` : '暂无完整采集记录';
        return {id:item.id, name:item.name, regionName:names[item.region] || item.region,
          documents:state ? state.documents || 0 : 0, history:state ? histories[state.history_state] || '状态待确认' : '尚未接通', historyPages:state ? state.history_pages || 0 : 0,
          kind:item.kind === 'interpretation' ? '政策解读' : '规范性文件',
          validation:item.status === 'sample_pass' ? '采样验证通过' : item.status === 'blocked' ? '接入受阻' : '待验证',
          status:state ? (statuses[state.status] || '状态待确认') : '未启用监控', lastSuccess};
      });
      this.setData({sources, loading:false, provinceCount:inventory.provinces.length, enabledCount:coverage.filter(item => item.enabled).length});
    }).catch(error => {
      if (id === this._request) this.setData({loading:false, loadError:true, errorText:api.errorMessage(error)});
    });
  }
});
