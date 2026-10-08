const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness() {
  const timers = [], requests = [], registrations = [];
  const fakeRequire = () => {};
  fakeRequire.async = async name => {requests.push(name); return {base64: 'd09GRg=='};};
  const sandbox = {module: {exports: {}}, require: fakeRequire,
    setTimeout: (fn, ms) => {const timer = {fn, ms}; timers.push(timer); return timer;},
    clearTimeout: timer => {timer.cancelled = true;},
    wx: {loadFontFace: options => registrations.push(options)}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../小程序/utils/nameFont.js'), 'utf8'), sandbox);
  const page = {data: {}, setData: data => Object.assign(page.data, data)};
  return {...sandbox.module.exports, timers, requests, registrations, page};
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('name font never blocks first paint and downloads serially after the delay', async () => {
  const h = harness();
  h.warmNameFont(h.page);
  assert.equal(h.page.data.nameFontReady, undefined);
  assert.equal(h.requests.length, 0);
  assert.equal(h.timers[0].ms, 2000);
  h.timers[0].fn();
  await flush();
  assert.equal(h.requests.length, 1);
  for (let i = 0; i < 3; i++) {
    const registration = h.registrations[i];
    assert.equal(registration.scopes[0], 'webview');
    assert.match(registration.source, /data:font\/woff;/);
    assert.equal(h.page.data.nameFontReady, undefined);
    registration.success();
    await flush();
  }
  assert.equal(h.page.data.nameFontReady, true);
  const second = {data: {}, setData: data => Object.assign(second.data, data)};
  h.warmNameFont(second);
  assert.equal(second.data.nameFontReady, true);
  assert.equal(h.requests.length, 3);
});

test('font failure or leaving the page preserves the system font without blocking interaction', async () => {
  const h = harness();
  h.warmNameFont(h.page); h.timers[0].fn(); await flush();
  h.registrations[0].fail(); await flush();
  assert.equal(h.page.data.nameFontReady, undefined);
  assert.equal(h.page.nameFontQueued, false);
  const closed = harness();
  closed.warmNameFont(closed.page); closed.page.closed = true; closed.timers[0].fn();
  assert.equal(closed.requests.length, 0);
});
