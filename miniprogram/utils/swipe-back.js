/**
 * ===========================================================================
 * 右滑返回手势 — Mixin 模式增强页面功能
 * ===========================================================================
 *
 * 本文件实现了一个"右滑返回上一页"的手势识别功能。
 * 类似 iOS 原生的滑动返回，用户从屏幕左边缘向右滑动即可返回。
 *
 * 工作原理：
 * 1. onTouchStart — 记录手指按下的起始坐标 (touchStartX, touchStartY)
 * 2. onTouchEnd — 计算滑动距离，判断是否为"右滑返回"手势
 * 3. 判定条件：右滑距离 > 80px 且水平移动 > 2×垂直移动（排除斜滑）
 *
 * 使用方式（在任意页面的 Page({}) 中）：
 *   const swipeBack = require('../../utils/swipe-back');
 *   Page({
 *     onLoad() { swipeBack.initSwipeBack.call(this); },
 *     onTouchStart(e) { swipeBack.onTouchStart.call(this, e); },
 *     onTouchEnd(e) { swipeBack.onTouchEnd.call(this, e); }
 *   });
 *
 * 同时需要在 wxml 根容器上绑定：
 *   <view bindtouchstart="onTouchStart" bindtouchend="onTouchEnd">
 *
 * 为什么用 .call(this)？
 * - 将工具函数中的 this 指向页面实例，使 _touchStartX/Y 保存到页面实例上
 * - 这是 JavaScript Mixin 模式的一种实现方式
 */

module.exports = {
  /**
   * 初始化手势状态
   * 在页面 onLoad 中调用，重置触摸起始坐标
   */
  initSwipeBack() {
    this._touchStartX = 0;  // 手指按下时的 X 坐标
    this._touchStartY = 0;  // 手指按下时的 Y 坐标
  },

  /**
   * 触摸开始 — 记录起始位置
   * 需要绑定到 wxml 的 bindtouchstart 事件
   */
  onTouchStart(e) {
    // e.touches[0] 是第一个触摸点的坐标
    this._touchStartX = e.touches[0].pageX;
    this._touchStartY = e.touches[0].pageY;
  },

  /**
   * 触摸结束 — 判断是否为右滑返回手势
   * 需要绑定到 wxml 的 bindtouchend 事件
   */
  onTouchEnd(e) {
    // 计算水平滑动距离（结束 X - 起始 X，正值 = 右滑）
    const deltaX = e.changedTouches[0].pageX - this._touchStartX;
    // 计算垂直滑动距离的绝对值
    const deltaY = Math.abs(e.changedTouches[0].pageY - this._touchStartY);

    // 判定条件：
    // 1. 水平右滑超过 80px（避免误触）
    // 2. 水平移动距离 > 垂直移动距离 × 2（确保是水平滑动而非斜滑/上下滑）
    if (deltaX > 80 && deltaX > deltaY * 2) {
      // 调用微信导航 API 返回上一页
      wx.navigateBack({ delta: 1 });
    }
  }
};
