'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const {createHandler, signedHeaders} = require('../云函数/nameGateway/gateway');
const view = require('../小程序/utils/view');
const swipe = require('../小程序/utils/swipe');

const env = {
  CORE_API_URL: 'https://core.example.com',
  GATEWAY_SECRET: 'test-gateway-secret-2026-32-characters',
  WECHAT_APP_ID: 'wx1234567890abcdef'
};
const context = {APPID: env.WECHAT_APP_ID, OPENID: 'trusted-user'};

test('gateway forwards only trusted platform identity to fixed endpoint', async () => {
  let seen;
  const handler = createHandler({
    getContext: () => context,
    env,
    transport: async (url, body, headers) => {
      seen = {url, body, headers};
      return {status: 200, data: {cards: []}};
    }
  });
  const result = await handler({
    action: 'feed.pull',
    data: {name_length: 2, count: 8, request_id: crypto.randomUUID()},
    openid: 'victim',
    appid: 'wrong',
    url: 'https://evil.example',
    headers: {'X-Admin-Key': 'bad'}
  });
  assert.equal(result.ok, true);
  assert.equal(seen.url.href, 'https://core.example.com/internal/v1/dispatch');
  const forwarded = JSON.parse(seen.body);
  assert.equal(forwarded.appid, context.APPID);
  assert.equal(forwarded.openid, context.OPENID);
  assert.equal(forwarded.data.name_length, 2);
  assert.equal(forwarded.data.surname, undefined);
  assert.equal(seen.headers['Content-Length'], Buffer.byteLength(seen.body));
  assert.equal(seen.headers['X-Admin-Key'], undefined);
  const digest = crypto.createHash('sha256').update(seen.body).digest('hex');
  const expected = crypto.createHmac('sha256', env.GATEWAY_SECRET)
    .update(`v1\n${seen.headers['X-Gateway-Timestamp']}\n${seen.headers['X-Gateway-Nonce']}\n${digest}`)
    .digest('hex');
  assert.equal(seen.headers['X-Gateway-Signature'], expected);
});

test('gateway adds the trusted OpenID only to the caller session response', async () => {
  const handler = createHandler({
    getContext: () => context,
    env,
    transport: async () => ({status: 200, data: {user_id: 'hashed-user'}})
  });
  const session = await handler({action: 'session.get'});
  assert.deepEqual(session.data, {user_id: 'hashed-user', openid: context.OPENID});
  const feed = await createHandler({
    getContext: () => context,
    env,
    transport: async () => ({status: 200, data: {cards: []}})
  })({action: 'feed.pull'});
  assert.equal(feed.data.openid, undefined);
});

test('gateway rejects missing identity, unexpected app, admin actions and oversized input', async () => {
  const transport = () => { throw new Error('must not forward'); };
  assert.equal((await createHandler({getContext: () => ({}), env, transport})({action: 'session.get'})).status, 401);
  assert.equal((await createHandler({getContext: () => ({...context, APPID: 'another'}), env, transport})({action: 'session.get'})).status, 401);
  const handler = createHandler({getContext: () => context, env, transport});
  assert.equal((await handler({action: 'admin.metrics'})).status, 404);
  assert.equal((await handler({action: 'feed.pull', data: {x: '字'.repeat(10000)}})).status, 413);
  assert.equal((await handler({action: 'feed.pull', data: []})).status, 422);
});

test('gateway rejects redirects/config errors and hides upstream secrets', async () => {
  for (const url of ['http://core.example.com', 'https://user:pass@core.example.com', 'https://core.example.com/path', 'https://core.example.com?target=evil']) {
    assert.equal((await createHandler({getContext: () => context, env: {...env, CORE_API_URL: url}})({action: 'session.get'})).status, 503);
  }
  for (const status of [302, 500]) {
    const handler = createHandler({getContext: () => context, env, transport: async () => ({status, data: {detail: 'secret-db-url'}})});
    const result = await handler({action: 'session.get'});
    assert.equal(result.status, 503);
    assert.ok(!result.message.includes('secret'));
  }
});

test('signature changes with body and timestamp', () => {
  const a = signedHeaders('中文', env.GATEWAY_SECRET, '1789640000', 'a'.repeat(32));
  const b = signedHeaders('中文 ', env.GATEWAY_SECRET, '1789640000', 'a'.repeat(32));
  assert.notEqual(a['X-Gateway-Signature'], b['X-Gateway-Signature']);
});

function card(id, name) {
  return {id, item: {姓名: name, 拼音带调: 'qīng hé', 现代释义: '清润平和，温雅从容。', 文化标签: ['清雅'], 书名: '诗经', 篇章: '小雅', 男孩适配分: 62, 女孩适配分: 38}};
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

function pageHarness(call, user = 'user-A', saved = {}) {
  let page;
  const storage = new Map(Object.entries(saved));
  const app = {selectedCard: null, namePreferences: {surname: '', gender: 'any'}, session: async () => user};
  const events = {navigations: [], vibrations: 0};
  const wx = {
    getWindowInfo: () => ({windowWidth: 375}),
    getSystemInfoSync: () => ({windowWidth: 375}),
    getStorageSync: key => storage.get(key),
    setStorageSync: (key, value) => storage.set(key, JSON.parse(JSON.stringify(value))),
    navigateTo: value => events.navigations.push(value),
    vibrateShort: () => { events.vibrations += 1; }
  };
  const sandbox = {
    Page: definition => { page = definition; },
    getApp: () => app,
    wx,
    require: modulePath => {
      if (modulePath.includes('/utils/view')) return view;
      if (modulePath.includes('/utils/swipe')) return swipe;
      return {call, requestId: () => crypto.randomUUID(), storageKey: value => `cache:${value}`, preferenceKey: value => `prefs:${value}`};
    },
    setInterval: () => 1,
    clearInterval() {},
    setTimeout: callback => { queueMicrotask(callback); return 1; },
    Date,
    Promise,
    Set,
    console
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../小程序/pages/discover/index.js'), 'utf8'), sandbox);
  page.data = JSON.parse(JSON.stringify(page.data));
  page.setData = patchData => Object.assign(page.data, patchData);
  return {page, storage, app, events};
}

test('mini app opens directly on a double-name deck and sends no surname filters', async () => {
  const requests = [];
  const {page} = pageHarness(async (action, data) => {
    requests.push({action, data});
    return {cards: [card(1, '清和'), card(2, '景行')]};
  });
  await page.onLoad();
  assert.equal(page.data.ready, true);
  assert.equal(page.data.nameLength, 2);
  assert.equal(page.data.current.item.name, '清和');
  assert.equal(page.data.next.item.name, '景行');
  assert.deepEqual(Object.keys(requests[0].data).sort(), ['count', 'gender', 'name_length', 'request_id']);
  assert.equal(requests[0].data.name_length, 2);
  assert.equal(requests[0].data.gender, 'any');
  assert.equal(requests[0].data.surname, undefined);
  assert.equal(requests[0].data.count, 8);
});

test('mini app reuses the same request ID after an uncertain pull failure', async () => {
  const ids = [];
  let fail = true;
  const {page, storage} = pageHarness(async (action, data) => {
    ids.push(data.request_id);
    if (fail) { fail = false; throw new Error('offline'); }
    return {cards: [card(1, '清和')]};
  });
  await page.onLoad();
  const cached = storage.get('cache:user-A');
  assert.equal(cached.pools['any:2'].pending.request_id, ids[0]);
  await page.retry();
  assert.equal(ids[0], ids[1]);
  assert.equal(page.data.current.id, 1);
  assert.equal(storage.get('cache:user-A').pools['any:2'].pending, null);
});

test('favorite failure returns the card and blocks a second action', async () => {
  const save = deferred();
  let saves = 0;
  const {page} = pageHarness(async (action) => {
    if (action === 'feed.pull') return {cards: [card(1, '清和'), card(2, '景行')]};
    saves += 1;
    return save.promise;
  });
  await page.onLoad();
  const first = page.favorite();
  assert.equal(page.data.saving, true);
  assert.equal(page.data.animating, true);
  await page.favorite();
  assert.equal(saves, 1);
  save.reject(new Error('offline'));
  await first;
  assert.equal(page.data.current.id, 1);
  assert.equal(page.data.animating, false);
  assert.match(page.data.error, /留在原位/);
});

test('successful favorite advances once and prefetches without duplicate actions', async () => {
  const save = deferred();
  let saves = 0;
  const {page, events} = pageHarness(async (action) => {
    if (action === 'feed.pull') return {cards: [card(1, '清和'), card(2, '景行'), card(3, '令仪'), card(4, '攸宁')]};
    saves += 1;
    return save.promise;
  });
  await page.onLoad();
  const first = page.favorite();
  await page.skip();
  assert.equal(saves, 1);
  save.resolve({favorite: true});
  await first;
  assert.equal(page.data.current.id, 2);
  assert.equal(events.vibrations, 1);
});

test('favorite from detail removes the matching card before showing the next one', async () => {
  const {page} = pageHarness(async (action) => {
    if (action === 'feed.pull') return {cards: [card(1, '清和'), card(2, '景行')]};
    return {favorite: true};
  });
  await page.onLoad();
  assert.equal(page.completeFavoriteFromDetail(1), true);
  assert.equal(page.data.current.id, 2);
  assert.equal(page.completeFavoriteFromDetail(999), false);
});

test('late single-name response cannot replace the active double-name deck', async () => {
  const single = deferred();
  const {page, storage} = pageHarness(async (action, data) => {
    if (data.name_length === 1) return single.promise;
    return {cards: [card(21, '清和'), card(22, '景行'), card(23, '令仪'), card(24, '攸宁')]};
  });
  await page.onLoad();
  const switching = page.lengthChange({currentTarget: {dataset: {length: 1}}});
  assert.equal(page.data.nameLength, 1);
  await page.lengthChange({currentTarget: {dataset: {length: 2}}});
  assert.equal(page.data.current.item.name, '清和');
  single.resolve({cards: [card(11, '宁')]});
  await switching;
  assert.equal(page.data.nameLength, 2);
  assert.equal(page.data.current.item.name, '清和');
  assert.equal(storage.get('cache:user-A').pools['any:1'].cards[0].item.name, '宁');
});

test('cache is scoped to the OpenID-derived user and restores each length independently', async () => {
  const cached = {
    version: 3,
    selectedLength: 1,
    pools: {
      'any:1': {cards: [card(7, '宁'), card(8, '安'), card(9, '和'), card(10, '清')], pending: null, retryAt: 0},
      'any:2': {cards: [card(11, '清和')], pending: null, retryAt: 0}
    }
  };
  let calls = 0;
  const {page} = pageHarness(async () => { calls += 1; return {cards: []}; }, 'user-B', {'cache:user-A': cached, 'cache:user-B': cached});
  await page.onLoad();
  assert.equal(page.data.nameLength, 1);
  assert.equal(page.data.current.item.name, '宁');
  assert.equal(calls, 0);
});

test('surname changes display only and gender switch pulls an isolated deck', async () => {
  const requests = [];
  const {page, storage} = pageHarness(async (action, data) => {
    requests.push(data);
    if (data.gender === 'female') return {cards: [card(20, '令仪')]};
    return {cards: [card(1, '清和'), card(2, '景行')]};
  });
  await page.onLoad();
  page.onSurnameInput({detail: {value: '赵1'}});
  assert.equal(page.data.current.item.displayName, '赵清和');
  assert.equal(storage.get('prefs:user-A').surname, '赵');
  assert.equal(requests[0].surname, undefined);
  await page.genderChange({detail: {value: '2'}});
  assert.equal(page.data.gender, 'female');
  assert.equal(page.data.current.item.displayName, '赵令仪');
  assert.equal(requests[1].gender, 'female');
});

test('next advances without writing a favorite', async () => {
  const actions = [];
  const {page} = pageHarness(async (action) => {
    actions.push(action);
    return {cards: [card(1, '清和'), card(2, '景行'), card(3, '令仪'), card(4, '攸宁')]};
  });
  await page.onLoad();
  await page.next();
  assert.equal(page.data.current.id, 2);
  assert.equal(actions.filter(action => action === 'favorites.add').length, 0);
});

test('drag math follows the finger, reveals direction and rejects vertical or short gestures', () => {
  const right = swipe.dragState(96, 20, 375);
  assert.match(right.cardStyle, /translate3d\(96px,3.6px,0\)/);
  assert.ok(right.likeOpacity > 0.9);
  assert.equal(right.skipOpacity, 0);
  assert.equal(swipe.releaseDirection(100, 12, 500, 375), 1);
  assert.equal(swipe.releaseDirection(-42, 3, 55, 375), -1);
  assert.equal(swipe.releaseDirection(28, 2, 70, 375), 0);
  assert.equal(swipe.releaseDirection(120, 118, 180, 375), 0);
});

test('discover markup matches the brand controls and omits advanced character filters', () => {
  const markup = fs.readFileSync(path.join(__dirname, '../小程序/pages/discover/index.wxml'), 'utf8');
  const script = fs.readFileSync(path.join(__dirname, '../小程序/pages/discover/index.js'), 'utf8');
  assert.match(markup, /千千嘉名/);
  assert.match(markup, /catchtouchmove="touchMove"/);
  assert.match(markup, /正在翻阅收藏/);
  assert.match(markup, /next && !saving/);
  assert.match(markup, /单字/);
  assert.match(markup, /双字/);
  assert.match(markup, /姓氏/);
  assert.match(script, /男孩/);
  assert.match(script, /女孩/);
  assert.doesNotMatch(markup, /固定字|避用字/);
  assert.match(script, /completeFavoriteFromDetail/);
});
