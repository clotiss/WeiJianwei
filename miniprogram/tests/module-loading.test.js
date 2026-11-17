const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const registry = new Map();
let registeredPage;
// The mini-program runtime registers JavaScript modules. It does not provide
// Node's JSON require extension; a .json import is resolved as .json.js.
function load(modulePath) {
  const filename = modulePath.endsWith('.js') ? modulePath : modulePath + '.js';
  if (registry.has(filename)) return registry.get(filename).exports;
  assert.ok(fs.existsSync(filename), 'Mini-program module missing: ' + path.relative(root,filename));
  const module = {exports:{}};
  registry.set(filename,module);
  vm.runInNewContext(fs.readFileSync(filename,'utf8'), {
    module, exports:module.exports,
    require:specifier => load(path.resolve(path.dirname(filename),specifier)),
    Page:definition => {registeredPage=definition;}, App() {}, Component() {},
    getApp:() => ({globalData:{USE_POLICY_V2:true,API_V2_BASE:'http://127.0.0.1:8891/api/v2'}}),
    wx:{}, console, setTimeout, clearTimeout
  }, {filename});
  return module.exports;
}
load(path.join(root,'app'));
for (const route of JSON.parse(fs.readFileSync(path.join(root,'app.json'),'utf8')).pages) {
  registeredPage=undefined;
  load(path.join(root,route));
  assert.ok(registeredPage, route + ' must register successfully before requests start');
  assert.ok(registeredPage.data, route + ' must initialize its view state');
}
console.log('Mini-program JS module loading: app and all page registrations passed');
