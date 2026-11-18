const api=require('../../utils/api');
const lists=require('../../utils/paged-list');
const names=require('../../config/regions');
const push=require('../../utils/push-subscription');
Page({
 data:{pushState:{available:false,enabled:false,credits:0},pushGrant:null,pushBusy:false,pushError:'',pushSaved:false,contentStatus:{},regions:[{code:'CN',name:'国家卫健委'}],topics:['全部主题'],regionIndex:0,topicIndex:0,includeNational:true,rules:[],activeId:0,documents:[],page:1,total:0,hasMore:false,loading:false,loadError:false,errorText:'',accountError:'',loggedIn:false,busy:false,dictError:false},
 onLoad(){return this.loadDictionaries();},
 onShow(){if(api.useV2() && api.hasV2Session())return this.refreshRules();},
 onUnload(){this._listRequest++;},
 loadDictionaries(){return Promise.all([api.getRegions(),api.getCategories()]).then(([regions,res])=>this.setData({regions:regions.filter(item=>item.code),topics:['全部主题',...res.categories],dictError:false})).catch(()=>this.setData({dictError:true}));},
 labelRule(rule){return {...rule,label:(names[rule.region] || '全部地区（历史关注）')+(rule.region && rule.region!=='CN' && rule.include_national?' + 国家':'')+' · '+(rule.topic || '全部主题')};},
 refreshRules(){this.setData({busy:true,accountError:''});return api.getV2Follows().then(rules=>{const selected=rules.find(rule=>rule.id===this.data.activeId)||rules[0];this.setData({rules:rules.map(rule=>this.labelRule(rule)),loggedIn:true,busy:false,activeId:selected?selected.id:0});const list=selected?this.fetchList():Promise.resolve(this.setData({documents:[],total:0,hasMore:false}));return Promise.all([list,this.refreshPush()]);}).catch(error=>this.setData({busy:false,accountError:api.errorMessage(error)}));},
 refreshPush(){
  if(!api.hasV2Session())return Promise.resolve();
  this.setData({pushError:'',pushGrant:null});
  return push.syncPending().then(()=>api.getV2Push()).then(state=>{
   this.setData({pushState:state});
   if(state.available && this.data.rules.length)return api.prepareV2Push().then(grant=>this.setData({pushGrant:grant}));
  }).catch(()=>this.setData({pushError:'提醒设置暂未同步，请点击重试'}));
 },
 enablePush(){
  if(this.data.pushBusy)return;
  const grant=this.data.pushGrant;
  if(!grant || grant.expires_at*1000<=Date.now()){
   this.setData({pushError:'正在更新提醒设置，请稍后再次点击'});return this.refreshPush();
  }
  this.setData({pushBusy:true,pushError:'',pushSaved:false});
  return push.request(grant).then(result=>{
   this.setData({pushState:result.status,pushGrant:null,pushSaved:result.answer==='accept',pushError:result.answer==='accept'?'':'未开启微信提醒，你仍可查看关注内容'});
   return api.prepareV2Push().then(next=>this.setData({pushGrant:next}));
  }).catch(()=>this.setData({pushError:push.pending()?'授权结果尚未保存，请点击重试':'未能开启提醒，请重试或检查微信订阅设置'})).finally(()=>this.setData({pushBusy:false}));
 },
 disablePush(){
  if(this.data.pushBusy)return;
  this.setData({pushBusy:true,pushError:'',pushSaved:false});
  return api.disableV2Push().then(state=>this.setData({pushState:state,pushGrant:null})).then(()=>this.refreshPush())
   .catch(()=>this.setData({pushError:'暂停提醒失败，请重试'})).finally(()=>this.setData({pushBusy:false}));
 },
 regionChanged(e){this.setData({regionIndex:Number(e.detail.value)});},
 topicChanged(e){this.setData({topicIndex:Number(e.detail.value)});},
 nationalChanged(e){this.setData({includeNational:!!e.detail.value});},
 addRule(){
  if(this.data.busy || this.data.dictError)return;
  if(!api.useV2()){this.setData({accountError:'关注功能将在新版服务上线后开放'});return;}
  const region=this.data.regions[this.data.regionIndex].code,topic=this.data.topicIndex?this.data.topics[this.data.topicIndex]:'';
  this.setData({busy:true,accountError:''});return api.addV2Follow({region,topic,include_national:this.data.includeNational}).then(rule=>{this.setData({activeId:rule.id});return this.refreshRules();}).catch(error=>this.setData({busy:false,accountError:api.errorMessage(error,'关注保存失败，请重试')}));
 },
 removeRule(e){if(this.data.busy)return;this.setData({busy:true,accountError:''});return api.removeV2Follow(Number(e.currentTarget.dataset.id)).then(()=>this.refreshRules()).catch(error=>this.setData({busy:false,accountError:api.errorMessage(error,'取消关注失败，请重试')}));},
 selectRule(e){this.setData({activeId:Number(e.currentTarget.dataset.id),documents:[],page:1});return this.fetchList();},
 fetchList(next=1){const rule=this.data.rules.find(item=>item.id===this.data.activeId);if(!rule)return Promise.resolve();return lists.load(this,'documents',page=>api.getDocuments({region:rule.region,include_national:rule.include_national,category:rule.topic,page,page_size:20}),typeof next==='number'?next:1);},
 loadMore(){if(!this.data.loading && this.data.hasMore)return this.fetchList(this.data.page+1);},
 onPullDownRefresh(){return Promise.all([this.loadDictionaries(),this.data.loggedIn?this.refreshRules():Promise.resolve()]).finally(()=>wx.stopPullDownRefresh());}
});
