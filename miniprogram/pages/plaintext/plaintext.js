/**
 * ===========================================================================
 * 原文纯文本页 — 以纯文本格式展示政策文件正文内容
 * ===========================================================================
 *
 * 功能：
 * 1. 展示文件标题
 * 2. 展示文件正文内容（保留换行和空格格式）
 * 3. 右滑返回
 *
 * 设计目的：方便用户阅读长文本的政策文件原文，
 * 正文内容通过 white-space: pre-wrap 保留原始排版格式。
 *
 * 进入方式：从详情页点击"查看原文"按钮
 * 路由参数：id={文件ID}
 */

const api = require('../../utils/api');
const swipeBack = require('../../utils/swipe-back');

Page({
  data: {
    title: '',       // 文件标题
    content: ''      // 文件正文内容
  },

  onLoad(options) {
    swipeBack.initSwipeBack.call(this);
    const id = parseInt(options.id);

    // 请求文件详情，只取标题和正文
    api.getDocumentDetail(id).then(doc => {
      this.setData({
        title: doc.title,
        content: doc.content || '暂无原文内容'
      });
    });
  },

  // ---- 右滑返回手势 ----
  onTouchStart(e) { swipeBack.onTouchStart.call(this, e); },
  onTouchEnd(e) { swipeBack.onTouchEnd.call(this, e); },

  onShareAppMessage() {
    return { title: "卫健委政策速查", path: "/pages/index/index" };
  },
});
