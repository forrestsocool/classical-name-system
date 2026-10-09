const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadShare(call, wx, renderShareImage) {
  const sandbox = {module: {exports: {}}, require: name => name === './shareCanvas' ? {renderShareImage} : {call}, wx};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../小程序/utils/share.js'), 'utf8'), sandbox);
  return sandbox.module.exports.shareName;
}

test('custom names share their exact link with an honest user-defined source title', async () => {
  const share = loadShare(async () => ({token: 'c'.repeat(32)}));
  const result = share({id: 91, item: {name: '清和', displayName: '李清和', surname: '李', book: '用户自定义'}});
  assert.match(result.title, /用户自定义/);
  assert.doesNotMatch(result.title, /出自|《/);
  const resolved = await result.promise;
  assert.match(resolved.path, /share=c{32}&surname=/);
});

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

test('a tap during preparation reuses the in-flight work, then cached shares return immediately', async () => {
  let finishImage;
  let imageCalls = 0, linkCalls = 0;
  const image = new Promise(resolve => {finishImage = resolve;});
  const share = loadShare(async () => {
    linkCalls++;
    return {token: 'e'.repeat(32)};
  }, {}, () => {imageCalls++; return image;});
  const card = {id: 42, item: {name: '清和', displayName: '李清和', surname: '李'}};
  const page = {};
  const first = share(card, page);
  const repeated = share(card, page);
  assert.equal(linkCalls, 1);
  assert.equal(imageCalls, 1);
  finishImage('wxfile://share.jpg');
  assert.equal((await repeated.promise).imageUrl, 'wxfile://share.jpg');
  await first.promise;
  assert.equal(share(card, page).promise, undefined);
});

test('image failure keeps the exact full-name link shareable', async () => {
  const share = loadShare(async () => ({token: 'f'.repeat(32)}), {},
    async () => {throw new Error('canvas unavailable');});
  const result = await share({id: 42, item: {name: '清和', surname: '李', displayName: '李清和'}}, {}).promise;
  assert.match(result.path, /detail\/index\?share=f{32}&surname=/);
  assert.equal(result.imageUrl, '/assets/share-cover.jpg');
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
  const favorite = shareName(card);
  assert.equal(favorite.promise, undefined);
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

test('sharing preserves the full surname and changing surname cannot reuse an old cache', async () => {
  let requests = 0;
  const share = loadShare(async () => {requests++; return {token: 'd'.repeat(32)};});
  const li = {id: 42, item: {name: '以宁', surname: '李', displayName: '李以宁'}};
  const wang = {id: 42, item: {name: '以宁', surname: '王', displayName: '王以宁'}};
  const first = await share(li).promise;
  const second = await share(wang).promise;
  assert.match(first.title, /李以宁/);
  assert.ok(first.path.endsWith('&surname=' + encodeURIComponent('李')));
  assert.ok(second.path.endsWith('&surname=' + encodeURIComponent('王')));
  assert.equal(requests, 2);
  assert.equal(share(li).promise, undefined);
});
