const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {view}=require('../utils/summary-state');
for (const state of ['pending','queued','generating','retrying','service_paused','failed','not_configured','waiting_content','insufficient_content']) {
 const result=view({state});assert.ok(result.title && result.note);
 assert.equal(result.poll,['pending','queued','generating','retrying'].includes(state));
}
assert.ok(view({state:'ready',scope:'body_excerpt'}).scope.includes('未覆盖全文'));
let definition,timers=new Map(),serial=0,reply,resolve;
const api={useV2:()=>true,hasV2Session:()=>false,getDocumentDetail:()=>reply,errorMessage:()=>''};
vm.runInNewContext(fs.readFileSync(path.resolve(__dirname,'../pages/detail/detail.js'),'utf8'),{
 Page:p=>definition=p,wx:{},
 setTimeout:fn=>{const id=++serial;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id),
 require:spec=>spec.endsWith('/api')?api:spec.endsWith('/reading')?{large:()=>false,record:()=>{}}:spec.endsWith('/swipe-back')?{initSwipeBack(){}}:spec.endsWith('/storage')?{}:require(path.resolve(__dirname,'../pages/detail',spec))
});
const page={...definition,data:JSON.parse(JSON.stringify(definition.data)),setData(v){Object.assign(this.data,v);}};
(async()=>{
 reply=Promise.resolve({id:1,summary:'[]',summary_status:{state:'queued'},attachments:'[]'});
 await page.onLoad({id:'1'});assert.equal(page.data.summaryView.state,'queued');assert.equal(timers.size,1);
 page.onHide();assert.equal(timers.size,0);page.onShow();assert.equal(timers.size,1);
 reply=Promise.resolve({id:1,summary_points:[{text:'要点',quote:'原文完整引句',source_name:'正文'}],summary_status:{state:'ready',scope:'body'},attachments:'[]'});
 await page.refreshSummary();assert.equal(timers.size,0);assert.equal(page.data.summary[0].quote,'原文完整引句');
 page.toggleEvidence({currentTarget:{dataset:{index:0}}});assert.equal(page.data.summary[0].expanded,true);
 reply=Promise.reject(new Error('network'));await page.refreshSummary();assert.ok(page.data.summaryError);assert.equal(page.data.summary.length,1);
 reply=new Promise(r=>resolve=r);const pending=page.refreshSummary();page.onUnload();resolve({id:99});await pending;assert.equal(page.data.doc.id,1);
 console.log('Summary states, evidence expansion, bounded polling, hide/unload and refresh failure passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
