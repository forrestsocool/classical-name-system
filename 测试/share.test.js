const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadShare(call) {
  const sandbox = {module: {exports: {}}, require: () => ({call})};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../小程序/utils/share.js'), 'utf8'), sandbox);
  return sandbox.module.exports.shareName;
}

test('sharing the visible name resolves to its exact source link', async () => {
  const requests = [];
  const shareName = loadShare(async (action, data) => {
    requests.push({action, data});
    return {token: 'a'.repeat(32), image_url: 'https://name.sensen.li/share-card/test.jpg'};
  });
  const share = shareName({id: 42, item: {name: '清和', book: '诗经'}});
  assert.match(share.title, /清和/);
  assert.match((await share.promise).path, /detail\/index\?share=a{32}$/);
  assert.equal((await share.promise).imageUrl, 'https://name.sensen.li/share-card/test.jpg');
  assert.equal(requests[0].action, 'shares.create');
  assert.equal(requests[0].data.material_id, 42);
  assert.equal(shareName(null).path, '/pages/discover/index');
});

test('share failure retains the name and yields a usable home link', async () => {
  const shareName = loadShare(async () => { throw new Error('offline'); });
  const result = await shareName({id: 42, item: {name: '清和'}}).promise;
  assert.match(result.title, /清和/);
  assert.equal(result.path, '/pages/discover/index');
});
