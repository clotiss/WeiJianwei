const { resolveEnvironment } = require('./config/environments');

App({
  onLaunch() {
    let version = 'release';
    try { version = wx.getAccountInfoSync().miniProgram.envVersion; } catch (_) {}
    Object.assign(this.globalData, resolveEnvironment(version));
  },
  globalData: resolveEnvironment('release')
});
