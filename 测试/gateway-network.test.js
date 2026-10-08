const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {EventEmitter} = require('node:events');
const {createHandler} = require('../云函数/nameGateway/gateway');
test('upstream timeout waits 18 seconds, destroys the request and clears its timer', async () => {
  const request = new EventEmitter();
  request.end = () => {};
  request.destroy = error => {request.emit('error', error); request.emit('close');};
  const timers = [];
  const sandbox = {module: {exports: {}}, Buffer, URL,
    require: name => name === 'node:https' ? {Agent: class {}, request: () => request} : require(name),
    setTimeout: (callback, delay) => {const timer = {callback, delay}; timers.push(timer); return timer;},
    clearTimeout: timer => {timer.cleared = true;}};
  vm.runInNewContext(fs.readFileSync('云函数/nameGateway/gateway.js', 'utf8'), sandbox);
  const pending = sandbox.module.exports.forward(new URL('https://example.test'), '{}');
  assert.equal(timers[0].delay, 18000);
  const rejected = assert.rejects(pending, error => error.code === 'UPSTREAM_TIMEOUT');
  timers[0].callback();
  await rejected;
  assert.equal(timers[0].cleared, true);
});
test('gateway failure records action and category without logging identity or secrets', async () => {
  const messages = [];
  const original = console.warn;
  console.warn = message => messages.push(JSON.parse(message));
  try {
    const handler = createHandler({getContext: () => ({APPID: 'wx1234567890abcdef', OPENID: 'private-user'}),
      env: {WECHAT_APP_ID: 'wx1234567890abcdef', GATEWAY_SECRET: 'secret-value-32-characters-for-test', CORE_API_URL: 'https://example.test'},
      transport: async () => {const error = new Error('private-secret'); error.code = 'ECONNRESET'; throw error;}});
    const result = await handler({action: 'sources.list'});
    assert.equal(result.status, 503);
    assert.equal(messages[0].action, 'sources.list');
    assert.equal(messages[0].category, 'ECONNRESET');
    assert.doesNotMatch(JSON.stringify(messages), /private-user|private-secret|secret-value/);
  } finally {console.warn = original;}
});
