Component({
  properties: {
    doc: { type: Object, value: {} }
  },
  methods: {
    onTap() {
      wx.navigateTo({
        url: `/pages/detail/detail?id=${this.properties.doc.id}`
      });
    }
  }
});
