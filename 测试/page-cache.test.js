const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
test('page cache isolates users and environments and ignores unavailable storage', () => {
  const storage = new Map();
  function load(envId) {
    const sandbox = {module: {exports: {}}, require: () => ({mode: 'cloud', envId}),
      wx: {getStorageSync: key => storage.get(key), setStorageSync: (key, value) => storage.set(key, value)}};
    vm.runInNewContext(fs.readFileSync('小程序/utils/pageCache.js', 'utf8'), sandbox);
    return sandbox.module.exports;
  }
  const first = load('env1'), second = load('env2');
  first.writeCache('favorites', 'alice', [1]);
  assert.deepEqual(first.readCache('favorites', 'alice'), [1]);
  assert.equal(first.readCache('favorites', 'bob'), null);
  assert.equal(second.readCache('favorites', 'alice'), null);
  assert.equal(first.readCache('sources', 'alice'), null);
  first.writeCache('sources', '', [2]);
  assert.equal(first.readCache('sources', ''), null);
});
