'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const view = require('../小程序/utils/view');

const card = (id, name = '清和') => ({id, item: {
  姓名: name, 拼音带调: 'qīng hé', 现代释义: '清润平和，温雅从容。',
  书名: '诗经', 篇章: '小雅', 原文: '清和有余。',
  文化标签: ['温润'], 男孩适配分: 50, 女孩适配分: 50
}});
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

test('custom favorite validates given names, prevents duplicates and refreshes after success', async () => {
  const pending = deferred();
  const actions = [];
  const {page, events} = harness((action, data) => {
    actions.push({action, data});
    if (action === 'favorites.custom') return pending.promise;
    return Promise.resolve({cards: [{...card(90), item: {...card(90).item, 书名: '用户自定义'}}]});
  });
  page.toggleCustom();
  page.inputCustom({detail: {value: 'abc'}});
  await page.saveCustom();
  assert.equal(actions.length, 0);
  assert.ok(page.data.customError);
  page.inputCustom({detail: {value: '清和'}});
  const save = page.saveCustom();
  await page.saveCustom();
  assert.equal(actions.length, 1);
  assert.equal(actions[0].data.name, '清和');
  pending.resolve({saved: true});
  await save;
  assert.equal(page.data.customSaving, false);
  assert.equal(page.data.customOpen, false);
  assert.equal(page.data.cards[0].item.isCustom, true);
  assert.equal(events.toasts[0].title, '已加入收藏');
});

test('failed custom enrichment retains input and allows retry', async () => {
  const {page} = harness(async () => {throw new Error('补全失败');});
  page.toggleCustom();
  page.inputCustom({detail: {value: '清和'}});
  await page.saveCustom();
  assert.equal(page.data.customName, '清和');
  assert.equal(page.data.customOpen, true);
  assert.equal(page.data.customSaving, false);
  assert.equal(page.data.customError, '补全失败');
});
function harness(call, surname = '赵', prepareShare) {
  let page;
  const app = {session: async () => 'user-A', namePreferences: {surname}};
  const events = {refreshStopped: 0, navigations: [], toasts: [], tabs: []};
  const storage = new Map();
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../小程序/pages/favorites/index.js'), 'utf8'), {
    Page: definition => { page = definition; },
    getApp: () => app,
    wx: {
      getWindowInfo: () => ({windowWidth: 375}),
      getStorageSync: () => ({surname}),
      stopPullDownRefresh: () => events.refreshStopped++,
      navigateTo: data => events.navigations.push(data),
      switchTab: data => events.tabs.push(data),
      showToast: data => events.toasts.push(data)
    },
    require: name => name.includes('/pageCache') ? {
      readCache: (kind, user) => storage.get(kind + ':' + user),
      writeCache: (kind, user, data) => storage.set(kind + ':' + user, JSON.parse(JSON.stringify(data)))
    } : name.includes('/view') ? view : name.includes('/share') ? {prepareShare} : {call, preferenceKey: value => value},
    Promise, Date, Set, console
  });
  page.data = JSON.parse(JSON.stringify(page.data));
  page.setData = patch => Object.assign(page.data, patch);
  page.onLoad();
  return {page, app, events, storage};
}
test('cached favorites appear before refresh finishes and refresh failure stays silent', async () => {
  const pending = deferred();
  const {page, app, storage} = harness(() => pending.promise);
  app.userId = 'user-A';
  storage.set('favorites:user-A', {cards: [card(7)], nextCursor: 7});
  const refresh = page.onShow();
  assert.equal(page.data.cards[0].id, 7);
  assert.equal(page.data.refreshing, false);
  await Promise.resolve();
  pending.reject(new Error('offline'));
  await refresh;
  assert.equal(page.data.error, '');
  assert.equal(page.data.cards[0].id, 7);
  assert.equal(page.data.nextCursor, 7);
});

test('successful silent refresh replaces cached favorites and persists the new result', async () => {
  const {page, app, storage} = harness(async () => ({cards: [card(9)], next_cursor: null}));
  app.userId = 'user-A';
  storage.set('favorites:user-A', {cards: [card(7)], nextCursor: 7});
  await page.onShow();
  assert.deepEqual(Array.from(page.data.cards, card => card.id), [9]);
  assert.equal(storage.get('favorites:user-A').cards[0].id, 9);
  assert.equal(storage.get('favorites:user-A').nextCursor, null);
});

function touch(id, x, y, timeStamp) {
  return {currentTarget: {dataset: {id}}, touches: [{clientX: x, clientY: y}],
    changedTouches: [{clientX: x, clientY: y}], timeStamp};
}
const tap = id => ({currentTarget: {dataset: {id}}});
function openRow(page, id) {
  page.touchStart(touch(id, 95, 150, 1000));
  page.touchMove(touch(id, 20, 154, 1400));
  page.touchEnd(touch(id, 20, 154, 1500));
}
async function until(condition) {
  for (let i = 0; i < 30 && !condition(); i++) await Promise.resolve();
  assert.ok(condition(), 'expected async step did not start');
}

test('favorites left swipe reveals removal without removing; right swipe, vertical scroll and touch cancellation are safe', async () => {
  const actions = [];
  const {page} = harness(async action => { actions.push(action); return {cards: [card(2), card(1)]}; });
  await page.onShow();
  openRow(page, 2);
  assert.equal(page.data.openId, 2);
  assert.equal(page.data.slideX, -89);
  assert.deepEqual(actions, ['favorites.list']);
  page.detail(tap(2));
  page.touchStart(touch(2, 20, 150, 2000));
  page.touchMove(touch(2, 100, 151, 2400));
  page.touchEnd(touch(2, 100, 151, 2500));
  assert.equal(page.data.openId, null);
  page.touchStart(touch(1, 20, 150, 3000));
  page.touchMove(touch(1, 26, 240, 3300));
  page.touchEnd(touch(1, 26, 240, 3400));
  assert.equal(page.data.slideX, 0);
  openRow(page, 2);
  openRow(page, 1);
  assert.equal(page.data.openId, 1);
  page.touchCancel();
  assert.equal(page.data.openId, null);
});

test('failed share preparation can be tapped again and enables sharing after success', async () => {
  let attempts = 0;
  const {page, events} = harness(async () => ({}), '赵', async () => {
    if (++attempts === 1) throw new Error('连接失败');
    return {token: 'a'.repeat(32)};
  });
  page.data.cards = [card(9)];
  const event = {currentTarget: {dataset: {id: '9'}}};
  await page.prepareFavoriteShare(event);
  assert.equal(page.data.cards[0].sharePreparing, false);
  assert.equal(page.data.cards[0].shareReady, undefined);
  assert.equal(events.toasts.length, 0);
  await page.prepareFavoriteShare(event);
  assert.equal(page.data.cards[0].shareReady, true);
  assert.equal(attempts, 2);
  const markup = fs.readFileSync(path.join(__dirname, '../小程序/pages/favorites/index.wxml'), 'utf8');
  const button = markup.match(/<button class="favorite-share-button"[^>]*>/)[0];
  assert.match(button, /open-type="share"/);
  assert.doesNotMatch(button, /disabled=|shareReady/);
});

test('warming a large favorites list prepares only the first two and removal never blocks sharing', async () => {
  const requested = [];
  const {page} = harness(async () => ({}), '赵', async card => {
    requested.push(card.id);
    return {token: 'a'.repeat(32)};
  });
  page.data.cards = Array.from({length: 30}, (_, index) => card(index + 1));
  await page.warmShares(page.data.cards);
  assert.deepEqual(requested, [1, 2]);
  page.data.removingId = 1;
  await page.prepareFavoriteShare({currentTarget: {dataset: {id: '30'}}});
  assert.deepEqual(requested, [1, 2, 30]);
});

test('short swipe rebounds; a fast left flick reveals the button and leaving the tab closes it', async () => {
  const {page} = harness(async () => ({cards: [card(1)]}));
  await page.onShow();
  page.touchStart(touch(1, 20, 100, 1000));
  page.touchMove(touch(1, 42, 102, 1400));
  page.touchEnd(touch(1, 42, 102, 1500));
  assert.equal(page.data.openId, null);
  page.touchStart(touch(1, 95, 100, 2000));
  page.touchMove(touch(1, 57, 102, 2060));
  page.touchEnd(touch(1, 57, 102, 2070));
  assert.equal(page.data.openId, 1);
  page.onHide();
  assert.equal(page.data.openId, null);
});

test('pull-to-refresh failure preserves displayed cards and stops the native spinner, then permits retry', async () => {
  let fail = false;
  const {page, events} = harness(async () => {
    if (fail) throw new Error('offline');
    return {cards: [card(8)], next_cursor: 8};
  });
  await page.onShow();
  fail = true;
  await page.onPullDownRefresh();
  assert.equal(page.data.cards[0].id, 8);
  assert.equal(page.data.nextCursor, 8);
  assert.equal(page.data.error, 'offline');
  assert.equal(events.refreshStopped, 1);
  assert.equal(page.data.refreshing, false);
  fail = false;
  await page.onPullDownRefresh();
  assert.equal(page.data.error, '');
  assert.equal(events.refreshStopped, 2);
});

test('refresh during pagination waits and replaces from the first page; append deduplicates records', async () => {
  const more = deferred();
  const requests = [];
  const {page} = harness(async (action, data) => {
    requests.push(data);
    if (requests.length === 1) return {cards: [card(8)], next_cursor: 8};
    if (data.before_id) return more.promise;
    return {cards: [card(12, '景行')], next_cursor: null};
  });
  await page.onShow();
  const pagination = page.onReachBottom();
  await until(() => requests.length === 2);
  const refresh = page.onPullDownRefresh();
  more.resolve({cards: [card(8), card(7)], next_cursor: 7});
  await pagination;
  await refresh;
  assert.equal(requests.length, 3);
  assert.equal(requests[1].before_id, 8);
  assert.equal(requests[2].before_id, undefined);
  assert.deepEqual(Array.from(page.data.cards, item => item.id), [12]);
  assert.equal(page.data.nextCursor, null);
});

test('pagination appends unique cards and ends after the last cursor', async () => {
  let requests = 0;
  const {page} = harness(async () => ++requests === 1
    ? {cards: [card(8)], next_cursor: 8}
    : {cards: [card(8), card(7)], next_cursor: null});
  await page.onShow();
  await page.onReachBottom();
  await page.onReachBottom();
  assert.deepEqual(Array.from(page.data.cards, item => item.id), [8, 7]);
  assert.equal(requests, 2);
});

test('removal requires the revealed button, prevents duplicate submits and preserves the name on failure', async () => {
  const deletion = deferred();
  let removes = 0;
  const {page} = harness(async action => {
    if (action === 'favorites.list') return {cards: [card(2)]};
    removes++;
    return deletion.promise;
  });
  await page.onShow();
  await page.remove(tap(2));
  assert.equal(removes, 0);
  openRow(page, 2);
  const first = page.remove(tap(2));
  await until(() => removes === 1);
  await page.remove(tap(2));
  deletion.reject(new Error('offline'));
  await first;
  assert.equal(removes, 1);
  assert.equal(page.data.cards[0].id, 2);
  assert.equal(page.data.openId, 2);
  assert.equal(page.data.removingId, null);
  assert.match(page.data.error, /名字已保留/);
});

test('refresh waits for removal so a stale list cannot resurrect a removed favorite', async () => {
  const deletion = deferred();
  let deleted = false, reads = 0;
  const {page, events} = harness(async action => {
    if (action === 'favorites.list') { reads++; return {cards: deleted ? [] : [card(2)]}; }
    await deletion.promise;
    deleted = true;
    return {removed: true};
  });
  await page.onShow();
  openRow(page, 2);
  const removal = page.remove(tap(2));
  const refresh = page.onPullDownRefresh();
  assert.equal(reads, 1);
  deletion.resolve();
  await Promise.all([removal, refresh]);
  assert.equal(reads, 2);
  assert.equal(page.data.cards.length, 0);
  assert.equal(events.refreshStopped, 1);
  assert.equal(events.toasts[0].title, '已取消收藏');
});

test('source action opens details with the surname and complete source; empty-state action opens discovery', async () => {
  const {page, app, events} = harness(async () => ({cards: [card(2)]}));
  await page.onShow();
  page.detail(tap(2));
  assert.equal(app.selectedSurname, '赵');
  assert.equal(app.selectedCard.item.displayName, '赵清和');
  assert.equal(app.selectedCard.item.original, '清和有余。');
  assert.equal(events.navigations[0].url, '/pages/detail/index');
  page.goDiscover();
  assert.equal(events.tabs[0].url, '/pages/discover/index');
});
