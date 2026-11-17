const api=require('../../utils/api');
const lists=require('../../utils/paged-list');
const names=require('../../config/regions');
Page({
 data:{regions:[{code:'',name:'全国'}],topics:['全部主题'],regionIndex:0,topicIndex:0,includeNational:true,rules:[],activeId:0,documents:[],page:1,total:0,hasMore:false,loading:false,loadError:false,errorText:'',accountError:'',loggedIn:false,busy:false,dictError:false},
 onLoad(){return this.loadDictionaries();},
 onShow(){if(api.useV2() && api.hasV2Session())return this.refreshRules();},
 onUnload(){this._listRequest++;},
 loadDictionaries(){return Promise.all([api.getRegions(),api.getCategories()]).then(([regions,res])=>this.setData({regions:[{code:'',name:'全国'},...regions],topics:['全部主题',...res.categories],dictError:false})).catch(()=>this.setData({dictError:true}));},
 labelRule(rule){return {...rule,label:(names[rule.region] || '全国')+(rule.region && rule.region!=='CN' && rule.include_national?' + 国家':'')+' · '+(rule.topic || '全部主题')};},
 refreshRules(){this.setData({busy:true,accountError:''});return api.getV2Follows().then(rules=>{const selected=rules.find(rule=>rule.id===this.data.activeId)||rules[0];this.setData({rules:rules.map(rule=>this.labelRule(rule)),loggedIn:true,busy:false,activeId:selected?selected.id:0});if(selected)return this.fetchList();this.setData({documents:[],total:0,hasMore:false});}).catch(error=>this.setData({busy:false,accountError:api.errorMessage(error)}));},
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
