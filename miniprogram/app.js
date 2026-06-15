/**
 * ===========================================================================
 * 小程序入口文件 — App() 注册
 * ===========================================================================
 *
 * 这是微信小程序的全局应用实例，整个小程序启动时最先执行。
 * App() 函数接收一个配置对象，定义全局数据、生命周期函数等。
 *
 * 关键概念：
 * - onLaunch: 小程序启动时执行一次（类比 main 函数）
 * - globalData: 全局共享数据，任何页面通过 getApp().globalData 访问
 * - wx.getStorageSync: 同步读取本地缓存（微信提供的 API）
 *
 * 数据流：
 *   启动 → 读本地缓存的收藏列表 → 存入 globalData.favorites
 *   页面需要时 → getApp().globalData.API_BASE 获取后端地址
 */

App({
  /**
   * onLaunch — 小程序初始化（启动时执行一次）
   *
   * 初始化时从本地缓存读取收藏列表，确保各页面共享同一份收藏数据。
   * wx.getStorageSync('favorites') 是微信的同步存储 API，
   * 数据存于用户手机本地，卸载小程序后会清除。
   */
  onLaunch() {
    // 从手机本地存储读取收藏的文档列表，如果没有则为空数组
    const favs = wx.getStorageSync('favorites') || [];
    // 存入全局变量，供所有页面访问
    this.globalData.favorites = favs;
  },

  /**
   * globalData — 全局共享数据
   *
   * API_BASE: 后端服务器地址，所有 API 请求都基于这个 URL
   * favorites: 收藏列表（与本地缓存同步）
   */
  globalData: {
    API_BASE: 'https://wjwjwjw.top/api/v1',  // 后端 API 基础地址
    favorites: []                                 // 用户收藏的文件列表
  }
});
