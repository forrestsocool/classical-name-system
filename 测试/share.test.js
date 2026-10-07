const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadShare(call, wx) {
  const sandbox = {module: {exports: {}}, require: () => ({call}), wx};
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

test('both entry points share a local JPEG received through the cloud response', async () => {
  const writes = [];
  let calls = 0;
  const shareName = loadShare(async () => {
    calls++;
    return {token: 'b'.repeat(32), image_base64: '/9j/2Q==', image_url: 'https://remote/image.jpg'};
  }, {env: {USER_DATA_PATH: 'wxfile://usr'}, getFileSystemManager: () => ({
    writeFileSync: (...args) => writes.push(args)
  })});
  const card = {id: 9, item: {name: '以宁', book: '道德经'}};
  const home = await shareName(card).promise;
  const favorite = await shareName(card).promise;
  assert.equal(home.imageUrl, `wxfile://usr/share-${'b'.repeat(32)}.jpg`);
  assert.equal(favorite.imageUrl, home.imageUrl);
  assert.equal(calls, 1);
  assert.equal(writes[0][2], 'base64');
});

test('file write failure retains a valid share link and packaged cover', async () => {
  const shareName = loadShare(async () => ({token: 'c'.repeat(32), image_base64: '/9j/2Q=='}), {
    env: {USER_DATA_PATH: 'wxfile://usr'}, getFileSystemManager: () => ({
      writeFileSync: () => { throw new Error('disk full'); }
    })
  });
  const result = await shareName({id: 10, item: {name: '以宁'}}).promise;
  assert.equal(result.imageUrl, '/assets/share-cover.jpg');
  assert.match(result.path, /share=c{32}$/);
});

test('share failure retains the name and yields a usable home link', async () => {
  const shareName = loadShare(async () => { throw new Error('offline'); });
  const result = await shareName({id: 42, item: {name: '清和'}}).promise;
  assert.match(result.title, /清和/);
  assert.equal(result.path, '/pages/discover/index');
});
