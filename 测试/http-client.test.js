'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function client(responseFor) {
  const requests = [];
  let logins = 0;
  const wx = {
    login({success}) { logins += 1; queueMicrotask(() => success({code: `code-${logins}`})); },
    request(options) {
      requests.push(options);
      queueMicrotask(() => options.success(responseFor(options.data)));
    }
  };
  const module = {exports: {}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../小程序/utils/api.js'), 'utf8'), {
    wx, module, Promise, Error, Math, queueMicrotask, setTimeout,
    require(file) {
      if (file === '../config') return {mode: 'http', httpUrl: 'https://example.test/v1/functions/nameGateway'};
      throw new Error(`unexpected import: ${file}`);
    }
  });
  return {api: module.exports, requests, get logins() { return logins; }};
}

test('HTTP client shares one WeChat login over the configured gateway', async () => {
  const c = client(payload => payload.action === 'session.get'
    ? {statusCode: 200, data: {ok: true, data: {user_id: 'u', sessionToken: 'signed-session'}}}
    : {statusCode: 200, data: {ok: true, data: {cards: []}}});
  const [a, b] = await Promise.all([c.api.call('feed.pull', {}), c.api.call('sources.list', {})]);
  assert.equal(c.logins, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(a)), {cards: []});
  assert.deepEqual(JSON.parse(JSON.stringify(b)), {cards: []});
  assert.equal(c.requests.length, 3);
  for (const request of c.requests) {
    assert.equal(request.header.Authorization, undefined);
    assert.equal(request.url, 'https://example.test/v1/functions/nameGateway');
  }
  assert.equal(c.requests[1].data.sessionToken, 'signed-session');
});

test('production config routes through the HTTPS CDN instead of a cloud function', () => {
  const config = require('../小程序/config');
  assert.equal(config.mode, 'http');
  assert.equal(config.httpUrl, 'https://name.wxapp.655567.xyz/api/v1/dispatch');
  assert.equal(config.envId, undefined);
  assert.equal(config.gateway, undefined);
});

test('HTTP client renews an expired session once before retrying', async () => {
  let firstFeed = true;
  const c = client(payload => {
    if (payload.action === 'session.get')
      return {statusCode: 200, data: {ok: true, data: {user_id: 'u', sessionToken: 'session'}}};
    if (firstFeed) {
      firstFeed = false;
      return {statusCode: 200, data: {ok: false, status: 401, message: 'expired'}};
    }
    return {statusCode: 200, data: {ok: true, data: {cards: []}}};
  });
  await c.api.call('feed.pull');
  assert.equal(c.logins, 2);
  assert.equal(c.requests.filter(request => request.data.action === 'feed.pull').length, 2);
});
