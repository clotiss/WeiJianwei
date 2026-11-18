// Opt-in regression against a freshly compiled WeChat Developer Tools project.
// cli auto --project <miniprogram> --auto-port 9420
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const automator = require(path.resolve(__dirname, '../.runtime/devtools-automation/node_modules/miniprogram-automator'));
const timer = setTimeout(() => { console.error('Search layout check timed out'); process.exit(2); }, 45000);
async function until(read, predicate) {
  for (let attempt = 0; attempt < 60; attempt++) {
    const value = await read();
    if (predicate(value)) return value;
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  throw new Error('Search did not finish');
}
(async () => {
  const mini = await automator.connect({wsEndpoint: 'ws://127.0.0.1:' + (process.env.WECHAT_AUTO_PORT || '9420')});
  const output = path.resolve(__dirname, '../.runtime/search-input-fix');
  fs.mkdirSync(output, {recursive: true});
  try {
    await mini.reLaunch('/pages/search/search?region=CN');
    const page = await mini.currentPage();
    await page.waitFor('.search-input');
    const input = await page.$('.search-input');
    const size = await input.size();
    const fontSize = parseFloat(await input.style('font-size'));
    const lineHeight = parseFloat(await input.style('line-height')) || fontSize * 1.4;
    const padding = parseFloat(await input.style('padding-top')) + parseFloat(await input.style('padding-bottom'));
    const contentHeight = Number(size.height) - padding;
    console.log(JSON.stringify({height: size.height, contentHeight, fontSize, lineHeight}));
    assert.ok(contentHeight >= lineHeight, 'Input must fit a complete text line without vertical clipping');
    assert.ok(Number(size.height) >= 44, 'Search field must be easy to tap');
    await mini.screenshot({path: path.join(output, 'empty.png')});
    const keyword = '医疗质量管理2026';
    await input.input(keyword);
    assert.equal(await page.data('keyword'), keyword);
    await mini.screenshot({path: path.join(output, 'typed.png')});
    await input.trigger('confirm', {value: keyword});
    let data = await until(() => page.data(), d => d.searched && !d.loading);
    assert.equal(data.query, keyword);
    assert.equal(data.loadError, false);
    await input.input('护理');
    await (await page.$('.search-action')).tap();
    data = await until(() => page.data(), d => d.query === '护理' && !d.loading);
    assert.equal(data.loadError, false);
    assert.ok(data.total > 0, 'Known policy keyword returns real search results');
    await mini.screenshot({path: path.join(output, 'results.png')});
    console.log(JSON.stringify({status: 'passed', checks: ['unclipped text line', 'tap area', 'Chinese/numeric input', 'keyboard confirm', 'search button'], results: data.total}));
  } finally { await mini.disconnect(); clearTimeout(timer); }
})().catch(error => { console.error(error.stack); clearTimeout(timer); process.exitCode = 1; });
