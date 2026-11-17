function historyKey(){const data=getApp().globalData;return 'policy_history:'+ (data.USE_POLICY_V2 ? data.API_V2_BASE : data.API_BASE);}
function history(){const items=wx.getStorageSync(historyKey());return Array.isArray(items)?items:[];}
function record(doc){const item={id:doc.id,title:doc.title,region_name:doc.region_name || '',publish_date:doc.publish_date || '',category:doc.category || '',doc_type:doc.doc_type || '',issuing_authority:doc.issuing_authority || ''};wx.setStorageSync(historyKey(),[item,...history().filter(old=>old.id!==doc.id)].slice(0,50));}
function large(){return !!wx.getStorageSync('policy_reader_large');}
function setLarge(value){wx.setStorageSync('policy_reader_large',!!value);}
module.exports={history,record,large,setLarge};
