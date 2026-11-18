const api = require('./api');
function key() {
  const data = getApp().globalData;
  return 'policy_push_consent:' + data.environment + ':' + data.API_V2_BASE;
}
function pending() { return wx.getStorageSync(key()) || null; }
function syncPending() {
  const value = pending();
  if (!value) return Promise.resolve();
  return api.confirmV2Push(value).then(result => { wx.removeStorageSync(key()); return result; }).catch(error => {
    const code = error && error.data && error.data.detail;
    if (['grant_expired','grant_not_found','grant_cancelled'].includes(code)) wx.removeStorageSync(key());
    throw error;
  });
}
function request(grant) {
  // This call stays synchronous within the user's tap handler. Do not put an
  // HTTP/login await in front of wx.requestSubscribeMessage (iOS gesture rule).
  return new Promise((resolve, reject) => {
    if (!wx.requestSubscribeMessage) { reject({code:'subscription_not_supported'}); return; }
    wx.requestSubscribeMessage({tmplIds:[grant.template_id], success(result) {
      const answer = result[grant.template_id];
      if (!['accept','reject','ban'].includes(answer)) { reject({code:'subscription_not_accepted'}); return; }
      const environment = getApp().globalData.environment;
      const value = {grant_id:grant.grant_id, result:answer,
        mini_state:environment === 'develop' ? 'developer' : environment === 'trial' ? 'trial' : 'formal'};
      wx.setStorageSync(key(), value);
      syncPending().then(status => resolve({answer,status}), reject);
    }, fail:reject});
  });
}
module.exports = {pending, syncPending, request};
