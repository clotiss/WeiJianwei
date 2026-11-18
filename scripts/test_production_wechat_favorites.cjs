// Opt-in integration test: real wx.login via the official developer SDK and HTTPS API.
// Requires the repository's developer tool on port 9420. Never prints codes or tokens.
const assert = require('node:assert/strict');
const path = require('node:path');
const automator = require(path.resolve(__dirname, '../.runtime/devtools-automation/node_modules/miniprogram-automator'));
const base = 'https://wjwjwjw.top/api/v2';
async function request(route, token, method='GET', data) {
  const response = await fetch(base + route, {method,
    headers:{'Content-Type':'application/json', ...(token ? {Authorization:'Bearer '+token} : {})},
    body: data === undefined ? undefined : JSON.stringify(data), signal:AbortSignal.timeout(30000)});
  const value = await response.json();
  if (!response.ok) throw new Error('API HTTP '+response.status+': '+String(value.detail || 'request_failed'));
  return value;
}
(async () => {
  let mini, token, documentId, originallySaved=false, changed=false;
  try {
    mini=await automator.connect({wsEndpoint:'ws://127.0.0.1:9420'});
    const account=await mini.callWxMethod('getAccountInfoSync');
    assert.equal(account.miniProgram.appId,'wx2672b8c409de2b18');
    async function login() {
      const result=await mini.callWxMethod('login');
      assert.ok(result.code,'wx.login must provide a real code');
      const session=await request('/auth/wechat',null,'POST',{code:result.code});
      assert.ok(session.access_token && session.expires_at,'Backend must establish an account session');
      return session.access_token;
    }
    token=await login();
    console.log('Real WeChat login: PASS');
    const before=await request('/me/favorites',token);
    const policies=await request('/policies?limit=100');
    const candidate=policies.items.find(d=>!before.some(f=>f.id===d.id)) || policies.items[0];
    assert.ok(candidate,'Need an existing policy for reversible favorite verification');
    documentId=candidate.id;
    originallySaved=before.some(d=>d.id===documentId);
    changed=true; // Restore even if a response is lost after the server writes.
    await request('/me/favorites/'+documentId,token,'PUT');
    let saved=await request('/me/favorites',token);
    assert.equal(saved.filter(d=>d.id===documentId).length,1);
    await request('/me/favorites/'+documentId,token,'PUT');
    saved=await request('/me/favorites',token);
    assert.equal(saved.filter(d=>d.id===documentId).length,1,'Repeated save must be idempotent');
    console.log('Favorite add/read/idempotency: PASS');
    const renewedToken=await login();
    saved=await request('/me/favorites',renewedToken);
    assert.ok(saved.some(d=>d.id===documentId),'A fresh login must see the same account favorites');
    await request('/me/favorites/'+documentId,renewedToken,'DELETE');
    const removed=await request('/me/favorites',token);
    assert.ok(!removed.some(d=>d.id===documentId));
    console.log('Fresh-login persistence and favorite removal: PASS');
  } finally {
    try {
      if (changed && token && documentId) {
        await request('/me/favorites/'+documentId,token,originallySaved?'PUT':'DELETE');
        const restored=await request('/me/favorites',token);
        assert.equal(restored.some(d=>d.id===documentId),originallySaved);
        console.log('Original favorite state restored: PASS');
      }
    } finally {
      if (mini) await mini.disconnect();
    }
  }
})().catch(error=>{
  // SDK/provider error objects may contain credentials; print only recognized safe messages.
  const message=String(error.message||'');
  console.error(/^API HTTP \d+: [a-z_]+$/.test(message)?message:'Integration test failed ('+(error.name||'Error')+'); no credentials logged.');
  process.exitCode=1;
});
