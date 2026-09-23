const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {createRequire} = require('node:module');
const {highlightText} = require('../小程序/utils/richText');

async function openDetail(response, surname = '') {
  const filename = path.join(__dirname, '../小程序/pages/detail/index.js');
  const realRequire = createRequire(filename);
  let page, requested;
  const app = {selectedSurname: surname, selectedCard: {id: 1, item: {
    姓名: '清熙', 原文: '清熙，清熙。', 现代释义: '明净温暖。'
  }}};
  vm.runInNewContext(fs.readFileSync(filename, 'utf8'), {
    require: name => name === '../../utils/api' ? {call: async (action, data) => {
      requested = {action, data};
      if (response instanceof Error) throw response;
      return response;
    }} : realRequire(name),
    Page: definition => { page = definition; }, getApp: () => app,
    wx: {getWindowInfo: () => ({statusBarHeight: 44})}
  });
  page.setData = patch => Object.assign(page.data, patch);
  await page.onLoad();
  return {data: page.data, requested};
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
  const elements = [{id:0, char:'李', element:'木', citations:[{book:'说文解字',quote:'李，果也。'}]}];
  const {data, requested} = await openDetail({elements, wuxing: {version:'server-v1', analyzed_name:'李清熙'}}, '李');
  assert.deepEqual(JSON.parse(JSON.stringify(requested)), {action:'names.detail', data:{material_id:1,surname:'李'}});
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
