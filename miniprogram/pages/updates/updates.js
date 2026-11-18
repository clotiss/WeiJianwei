const api=require('../../utils/api');
Page({
 data:{date:'',documents:[],total:0,loading:true,error:''},
 onLoad(options){this.digestId=options.id || '';return this.loadUpdates();},
 loadUpdates(){
  if(!/^[a-f0-9]{32}$/.test(this.digestId)){this.setData({loading:false,error:'这条更新记录不存在'});return Promise.resolve();}
  this.setData({loading:true,error:''});
  return api.getV2Updates(this.digestId).then(result=>this.setData({date:result.date,documents:result.items,total:result.total,loading:false}))
   .catch(()=>this.setData({loading:false,error:'暂时无法加载，请确认登录后重试'}));
 },
 goFollow(){wx.switchTab({url:'/pages/follow/follow'});}
});
