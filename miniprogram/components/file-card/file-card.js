const api=require('../../utils/api');
const storage=require('../../utils/storage');
Component({
  properties:{doc:{type:Object,value:{}}},
  data:{summaryText:'',typeLabel:'',isSaved:false,known:false,busy:false},
  observers:{doc(doc) {
    let points=[];try {points=JSON.parse(doc.summary || '[]');} catch (_) {}
    this.setData({summaryText:doc.summary_text || points[0] || '',typeLabel:doc.type_label || (doc.doc_type==='政策解读'?'官方解读':'政策正文')});
    this.refreshFavorite();
  }},
  methods:{
    onTap(){wx.navigateTo({url:`/pages/detail/detail?id=${this.properties.doc.id}`});},
    refreshFavorite(){
      if(!this.properties.doc.id)return;
      if(!api.useV2()){this.setData({isSaved:storage.isFavorited(this.properties.doc.id),known:true});return;}
      if(!api.hasV2Session())return;
      const id=this.properties.doc.id, requestId=this._favoriteRead=(this._favoriteRead || 0)+1;
      api.getV2Favorites().then(items=>{if(this.properties.doc.id===id && this._favoriteRead===requestId)this.setData({isSaved:items.some(item=>item.id===id),known:true});}).catch(()=>{});
    },
    toggleFavorite(){
      if(this.data.busy)return;
      this._favoriteRead=(this._favoriteRead || 0)+1;
      if(!api.useV2()){this.setData({isSaved:storage.toggleFavorite(this.properties.doc),known:true});return;}
      const next=this.data.known?!this.data.isSaved:true;
      this.setData({busy:true});
      return api.syncV2Favorite(this.properties.doc.id,next).then(()=>{this.setData({isSaved:next,known:true,busy:false});wx.showToast({title:next?'已收藏':'已取消收藏',icon:'none'});})
        .catch(error=>{this.setData({busy:false,known:false});wx.showToast({title:api.errorMessage(error,'收藏同步失败，请重试'),icon:'none'});});
    }
  }
});
