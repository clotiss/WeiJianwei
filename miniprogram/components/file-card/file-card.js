/**
 * ===========================================================================
 * file-card 组件 — 文件列表卡片
 * ===========================================================================
 *
 * 这是一个可复用的自定义组件，用于在多个页面中展示文件条目。
 *
 * 组件（Component）vs 页面（Page）：
 * - 页面：完整的应用页面，有自己的路由
 * - 组件：可被多个页面引用的 UI 单元，通过 properties 接收数据
 *
 * 使用方式（在父页面 json 中注册后）：
 *   <file-card wx:for="{{documents}}" doc="{{item}}" />
 *
 * 使用场景：
 * - 首页文件列表
 * - 搜索结果列表
 * - 分类列表页
 * - 收藏列表页
 */

Component({
  /**
   * properties — 组件对外暴露的属性（父页面传入的数据）
   * doc: 文件信息对象 {id, title, doc_number, publish_date, ...}
   */
  properties: {
    doc: {
      type: Object,   // 数据类型
      value: {}       // 默认值
    }
  },

  /**
   * methods — 组件的方法
   */
  methods: {
    /**
     * 卡片点击事件 → 跳转到文件详情页
     * 通过 this.properties.doc 获取传入的文件数据
     */
    onTap() {
      wx.navigateTo({
        url: `/pages/detail/detail?id=${this.properties.doc.id}`
      });
    }
  }
});
