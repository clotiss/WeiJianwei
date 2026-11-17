const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
for (const name of fs.readdirSync(__dirname).filter(name => name.endsWith('.test.js')).sort()) {
  const result = spawnSync(process.execPath, [path.join(__dirname,name)], {stdio:'inherit', timeout:60000});
  if (result.error) console.error(result.error.message);
  if (result.status !== 0) process.exit(result.status || 1);
}
console.log('All mini-program checks passed');
