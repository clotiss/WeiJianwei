const api=require('../../utils/api');
const reading=require('../../utils/reading');
const storage=require('../../utils/storage');
Page({
 data:{loggedIn:false,favoriteCount:'—',followCount:'—',historyCount:0,largeText:false,busy:false,errorText:'',showHistory:false,history:[]},
 onShow(){this.setData({loggedIn:api.useV2() && api.hasV2Session(),historyCount:reading.history().length,largeText:reading.large()});return this.loadCounts();},
 loadCounts(){
   if(!api.useV2()){this.setData({favoriteCount:storage.getFavorites().length});return Promise.resolve();}
   if(!api.hasV2Session())return Promise.resolve();
   return Promise.all([api.getV2Favorites(),api.getV2Follows()]).then(([favorites,follows])=>this.setData({favoriteCount:favorites.length,followCount:follows.length,loggedIn:true,errorText:''})).catch(error=>this.setData({errorText:api.errorMessage(error)}));
 },
 login(){if(this.data.busy)return;this.setData({busy:true,errorText:''});return api.loginV2().then(()=>this.loadCounts()).catch(error=>this.setData({errorText:api.errorMessage(error)})).finally(()=>this.setData({busy:false}));},
 goFavorites(){wx.navigateTo({url:'/pages/favorites/favorites'});},
 goFollow(){wx.switchTab({url:'/pages/follow/follow'});},
 goCoverage(){wx.navigateTo({url:'/pages/coverage/coverage'});},
 changeReading(e){reading.setLarge(e.detail.value);this.setData({largeText:!!e.detail.value});},
 toggleHistory(){this.setData({showHistory:!this.data.showHistory,history:reading.history()});},
 openHistory(e){wx.navigateTo({url:'/pages/detail/detail?id='+e.currentTarget.dataset.id});}
});
