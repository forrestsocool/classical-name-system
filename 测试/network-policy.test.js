const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function client(invoke) {
  const calls = [], delays = [];
  const sandbox = {module: {exports: {}}, require: () => ({mode: 'cloud', envId: 'test', gateway: 'nameGateway'}),
    wx: {cloud: {callFunction: options => {calls.push(options.data); return invoke(options.data);}}},
    setTimeout: (callback, delay) => {delays.push(delay); queueMicrotask(callback);}};
  vm.runInNewContext(fs.readFileSync('小程序/utils/api.js', 'utf8'), sandbox);
  return {api: sandbox.module.exports, calls, delays};
}
test('duplicate reads share one flight while different reads run in parallel', async () => {
  const finish = [];
  const c = client(() => new Promise(resolve => finish.push(resolve)));
  const first = c.api.call('sources.list');
  const same = c.api.call('sources.list');
  const other = c.api.call('favorites.list');
  assert.equal(first, same);
  assert.equal(c.calls.length, 2);
  finish.forEach(resolve => resolve({result: {ok: true, data: {}}}));
  await Promise.all([first, same, other]);
});
test('temporary failures retry once with the same feed receipt and frozen payload', async () => {
  let attempt = 0;
  const c = client(async () => ({result: ++attempt === 1 ? {ok: false, status: 503} : {ok: true, data: {cards: []}}}));
  const data = {request_id: 'same-receipt', count: 8};
  const task = c.api.call('feed.pull', data);
  data.request_id = 'changed';
  await task;
  assert.equal(c.calls.length, 2);
  assert.equal(c.calls[0].data.request_id, 'same-receipt');
  assert.equal(c.calls[1].data.request_id, 'same-receipt');
  assert.equal(c.delays.length, 1);
  assert.ok(c.delays[0] >= 250 && c.delays[0] < 500);
});
test('persistent failure stops after one retry and a later call can try again', async () => {
  const c = client(async () => {throw {errCode: -1, errMsg: 'network timeout'};});
  await assert.rejects(c.api.call('sources.list'), /连接失败/);
  assert.equal(c.calls.length, 2);
  await assert.rejects(c.api.call('sources.list'), /连接失败/);
  assert.equal(c.calls.length, 4);
});
test('invalid requests, denied access and non-idempotent writes never retry', async () => {
  for (const status of [401, 403, 409, 422, 429]) {
    const c = client(async () => ({result: {ok: false, status}}));
    await assert.rejects(c.api.call('sources.list'));
    assert.equal(c.calls.length, 1);
  }
  for (const action of ['feedback.save', 'shares.save', 'favorites.add', 'favorites.remove', 'feed.pull']) {
    const c = client(async () => ({result: {ok: false, status: 503}}));
    await assert.rejects(c.api.call(action, {}));
    assert.equal(c.calls.length, 1);
  }
});
