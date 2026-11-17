// Acceptance against real, already generated summaries. Never enqueues AI work.
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const automator = require(path.resolve(__dirname, '../.runtime/devtools-automation/node_modules/miniprogram-automator'));
const ids = process.argv.slice(2).map(Number);
assert.ok(ids.length > 0 && ids.length <= 5 && ids.every(Number.isSafeInteger));
const timer = setTimeout(() => process.exit(2), 90000);
async function until(read, test) {
  const end = Date.now() + 15000;
  while (Date.now() < end) {
    const value = await read();
    if (test(value)) return value;
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  throw Error('Live summary UI timed out');
}
(async () => {
  const mini = await automator.connect({wsEndpoint: 'ws://127.0.0.1:' + (process.env.WECHAT_AUTO_PORT || '9420')});
  const errors = [], results = [];
  mini.on('exception', e => errors.push(e.message || String(e)));
  try {
    assert.equal(await mini.evaluate(() => getApp().globalData.API_V2_BASE), 'http://127.0.0.1:8892/api/v2');
    for (const id of ids) {
      await mini.reLaunch('/pages/detail/detail?id=' + id);
      const page = await until(() => mini.currentPage(), p => p && p.path === 'pages/detail/detail');
      const data = await until(() => page.data(), d => !d.loading && d.doc && d.doc.id === id);
      assert.equal(data.loadError, false);
      assert.equal(data.summaryView.state, 'ready');
      assert.ok(data.summary.length >= 1 && data.summary.length <= 3);
      const toggles = await page.$$('.evidence-toggle');
      assert.equal(toggles.length, data.summary.length);
      for (let i = 0; i < toggles.length; i++) {
        await toggles[i].tap();
        const box = await until(() => page.$('.evidence-box'), Boolean);
        assert.ok((await box.text()).includes(data.summary[i].quote));
        if (i === 0) await mini.screenshot({path: path.resolve(__dirname, '../.runtime/summary-live-' + id + '.png')});
        await toggles[i].tap();
        assert.equal((await page.data()).summary[i].expanded, false);
      }
      await page.callMethod('refreshSummary');
      const refreshed = await until(() => page.data(), d => !d.summaryRefreshing);
      assert.equal(refreshed.summaryView.state, 'ready');
      assert.deepEqual(refreshed.summary.map(p => p.text), data.summary.map(p => p.text));
      results.push({id, title: data.doc.title, points: data.summary.length, evidence: 'expand/collapse passed', refresh: 'passed'});
    }
    assert.deepEqual(errors, []);
    const report = {checked_at: new Date().toISOString(), result: 'passed', api: 'local national service, real AI results', results};
    fs.writeFileSync(path.resolve(__dirname, '../.runtime/summary-live-ui.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await mini.disconnect();
    clearTimeout(timer);
  }
})().catch(e => {console.error(e.stack); clearTimeout(timer); process.exitCode = 1;});
