/**
 * ===========================================================================
 * 分类列表页 — 按分类/类型展示文件列表
 * ===========================================================================
 *
 * 功能：
 * 1. 展示指定分类和文件类型的列表
 * 2. 上滑加载更多分页
 * 3. 右滑返回手势
 *
 * 进入方式：从首页点击"查看更多→"
 * 路由参数：category={分类名}&doc_type={文件类型}
 */

const api = require('../../utils/api');
const swipeBack = require('../../utils/swipe-back');

Page({
  data: {
    category: '',      // 当前分类
    docType: '',       // 当前文件类型
    documents: [],     // 文件列表
    total: 0,          // 总数量
    page: 1,           // 当前页码
    hasMore: false     // 是否还有更多
  },

  /**
   * 页面加载
   * 从路由参数获取分类和类型，默认值为"全部"/"全部类型"
   */
  onLoad(options) {
    swipeBack.initSwipeBack.call(this);
    const category = options.category || '全部';
    const docType = options.doc_type || '全部类型';
    this.setData({ category, docType });
    this.fetchList();  // 立即加载数据
  },

  /**
   * 获取文件列表
   * 追加模式：每次加载新数据会拼接到现有列表末尾
   */
  fetchList() {
    const { category, docType, page } = this.data;
    api.getDocuments({ category, doc_type: docType, page, page_size: 20 }).then(res => {
      // 合并已有列表和新数据
      const list = this.data.documents.concat(res.items);
      this.setData({
        documents: list,
        total: res.total,
        hasMore: list.length < res.total  // 判断是否还有更多
      });
    });
  },

  // ---- 右滑返回手势 ----
  onTouchStart(e) { swipeBack.onTouchStart.call(this, e); },
  onTouchEnd(e) { swipeBack.onTouchEnd.call(this, e); },

  /**
   * 加载更多 — 页数 +1 后重新请求
   */
  loadMore() {
    if (!this.data.hasMore) return;
    this.setData({ page: this.data.page + 1 });
    this.fetchList();
  },

  /**
   * 返回上一页
   */
  goBack() { wx.navigateBack(); }
});
