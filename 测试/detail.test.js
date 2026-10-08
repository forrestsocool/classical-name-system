const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createRequire} = require('node:module');
const {highlightText} = require('../小程序/utils/richText');

async function openDetail(response, surname = '', options = {}) {
  const filename = path.join(__dirname, '../小程序/pages/detail/index.js');
  const realRequire = createRequire(filename);
  let page;
  const requests = [];
  const tabs = [];
  const app = {selectedSurname: surname, selectedCard: {id: 1, item: {
    姓名: '清熙', 原文: '清熙，清熙。', 现代释义: '明净温暖。', 书名: '诗经'
  }}};
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
    require: name => name === '../../utils/api' ? {call: async (action, data) => {
      requests.push({action, data});
      if (typeof response === 'function') return response(action, data);
      if (action === 'shares.create') return {token: 'x'.repeat(32)};
      if (response instanceof Error) throw response;
      return response;
    }} : realRequire(name),
    Page: definition => { page = definition; }, getApp: () => app,
    wx: {getWindowInfo: () => ({statusBarHeight: 44}), switchTab: value => tabs.push(value)}
  });
  page.setData = patch => Object.assign(page.data, patch);
  await page.onLoad(options);
  return {page, data: page.data, requests, tabs, app};
}

test('source highlighting marks every exact given-name occurrence as bold text', () => {
  const nodes = highlightText('清和有余，清和而不盈。', '清和');
  const marked = nodes.filter(node => node.name === 'span');
  assert.equal(marked.length, 2);
  assert.ok(marked.every(node => node.attrs.class === 'source-hit'));
});

test('detail loads only delivered name sources from server and keeps meaning separate', async () => {
  const markup = fs.readFileSync(path.join(__dirname, '../小程序/pages/detail/index.wxml'), 'utf8');
  assert.match(markup, /释义与寓意/);
  assert.match(markup, /elements-section/);
  assert.doesNotMatch(markup, /字源未定|字源 ·/);
  assert.match(markup, /assets\/elements\/\{\{entry\.tone\}\}\.svg/);
  assert.doesNotMatch(markup, /open-type="share"/);
  const elements = [{id:0, char:'李', element:'木', citations:[{book:'说文解字',quote:'李，果也。'}]}];
  const {data, requests} = await openDetail({elements, wuxing: {version:'server-v1', analyzed_name:'李清熙'}}, '李');
  assert.deepEqual(JSON.parse(JSON.stringify(requests.find(x => x.action === 'names.detail'))),
    {action:'names.detail', data:{material_id:1,surname:'李'}});
  assert.equal(data.card.item.displayName, '李清熙');
  assert.equal(data.showElements, true);
  assert.equal(data.elements[0].citations[0].book, '说文解字');
  assert.ok(data.card.item.originalNodes.some(node => node.attrs?.class === 'source-hit'));
});

test('detail hides missing source section and reports request failure', async () => {
  const empty = await openDetail({elements: [], wuxing: {version:'server-v1', analyzed_name:'清熙'}});
  assert.equal(empty.data.showElements, false);
  const failed = await openDetail(new Error('网络错误'));
  assert.equal(failed.data.showElements, false);
  assert.match(failed.data.error, /五行资料暂时无法读取/);
});

test('owner shares only the given name and a direct recipient can save that exact source', async () => {
  const token = 'a'.repeat(32);
  const shared = {id: 1, item: {姓名: '清熙', 书名: '诗经', 原文: '清熙，清熙。', 现代释义: '明净温暖。'}};
  const response = async action => {
    if (action === 'shares.get') return {card: shared, elements: []};
    if (action === 'shares.save') return {saved: true, material_id: 1};
    throw new Error(`unexpected ${action}`);
  };
  const {page, data, requests, tabs, app} = await openDetail(response, '李', {share: token});
  assert.equal(data.card.item.displayName, '清熙');
  assert.equal(data.shareReady, true);
  assert.equal(data.isShared, true);
  assert.deepEqual(JSON.parse(JSON.stringify(requests)), [{action:'shares.get', data:{token, include_image: false}}]);
  assert.equal(page.onShareAppMessage().path, `/pages/detail/index?share=${token}`);
  assert.equal(page.onShareAppMessage().imageUrl, '/assets/share-cover.jpg');
  assert.match(page.onShareAppMessage().title, /「清熙」出自《诗经》/);
  assert.doesNotMatch(page.onShareAppMessage().title, /李/);
  await page.favorite();
  assert.deepEqual(JSON.parse(JSON.stringify(requests[1])), {action:'shares.save', data:{token}});
  assert.equal(app.pendingFavorite.id, 1);
  assert.equal(tabs[0].url, '/pages/discover/index');
});

test('owner prepares a durable detail link and an invalid share shows recovery UI', async () => {
  const owned = await openDetail({elements: [], wuxing: {version:'server-v1', analyzed_name:'李清熙'}}, '李');
  assert.ok(owned.requests.some(x => x.action === 'shares.create' && x.data.material_id === 1));
  assert.equal(owned.page.onShareAppMessage().path, `/pages/detail/index?share=${'x'.repeat(32)}`);
  assert.ok(fs.existsSync(path.join(__dirname, '../小程序/assets/share-cover.jpg')));
  assert.doesNotMatch(owned.page.onShareAppMessage().title, /李/);
  const missing = await openDetail(async () => { throw new Error('分享已失效'); }, '', {share:'z'.repeat(32)});
  assert.equal(missing.data.card, null);
  assert.equal(missing.data.loading, false);
  assert.match(missing.data.loadError, /分享已失效/);
});
