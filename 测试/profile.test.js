const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const filters = require('../小程序/utils/filters');

function harness(saved = {}, catalog = [{name: '诗经', kind: '古籍'}, {name: '东亚年号', kind: '年号'}]) {
  let page, offline = false;
  const storage = new Map([['prefs:user', saved]]);
  const app = {session: async () => 'user', openid: 'test-openid'};
  const toasts = [], navigations = [];
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../小程序/pages/profile/index.js'), 'utf8'), {
    Page: value => { page = value; }, getApp: () => app,
    wx: {getStorageSync: key => storage.get(key), setStorageSync: (key, value) => storage.set(key, JSON.parse(JSON.stringify(value))),
      showToast: value => toasts.push(value), switchTab: value => navigations.push(value)},
    require: name => name.endsWith('/filters') ? filters : name.endsWith('/build') ? {version: 'test'} : {
      preferenceKey: user => 'prefs:' + user,
      call: async action => { assert.equal(action, 'sources.list'); if (offline) throw new Error('offline'); return {sources: catalog}; }
    }
  });
  page.data = JSON.parse(JSON.stringify(page.data));
  page.setData = data => Object.assign(page.data, data);
  return {page, storage, app, toasts, navigations, setOffline: value => { offline = value; }};
}
const input = (page, field, value) => page.characterInput({currentTarget: {dataset: {field}}, detail: {value}});

test('source switches default on, persist independently and preserve homepage preferences', async () => {
  const {page, storage} = harness({surname: '李', gender: 'female'});
  await page.onShow();
  assert.equal(page.data.enabledCount, 2);
  page.sourceChange({currentTarget: {dataset: {name: '东亚年号'}}, detail: {value: false}});
  assert.equal(page.data.enabledCount, 1);
  assert.deepEqual(storage.get('prefs:user').excluded_sources, ['东亚年号']);
  assert.equal(storage.get('prefs:user').surname, '李');
  assert.equal(storage.get('prefs:user').gender, 'female');
  await page.onShow();
  assert.equal(page.data.sources.find(source => source.name === '东亚年号').enabled, false);
});

test('character edits save automatically while conflicts retain the last valid settings', async () => {
  const {page, storage, navigations, toasts} = harness();
  await page.onShow();
  assert.equal(input(page, 'required', '清1清'), '清');
  input(page, 'excluded', '清');
  assert.match(page.data.inputError, /不能同时/);
  assert.equal(storage.get('prefs:user').excluded, '');
  page.chooseNames();
  assert.equal(navigations.length, 0);
  assert.equal(toasts.length, 1);
  input(page, 'excluded', '和');
  assert.equal(page.data.inputError, '');
  assert.equal(storage.get('prefs:user').excluded, '和');
  page.chooseNames();
  assert.equal(navigations[0].url, '/pages/discover/index');
});

test('catalog failure is recoverable and does not erase filters; new sources default on', async () => {
  const {page, storage, setOffline} = harness({required: '宁', excluded_sources: ['诗经']});
  setOffline(true);
  await page.onShow();
  assert.equal(page.data.sourceLoading, false);
  assert.equal(page.data.sourceError, 'offline');
  assert.equal(page.data.required, '宁');
  setOffline(false);
  await page.loadSources();
  assert.equal(page.data.enabledCount, 1);
  assert.equal(page.data.sources.find(source => source.name === '东亚年号').enabled, true);
  assert.deepEqual(storage.get('prefs:user').excluded_sources, ['诗经']);
});

test('profile markup keeps only individual source switches and puts name filters below them', () => {
  const markup = fs.readFileSync(path.join(__dirname, '../小程序/pages/profile/index.wxml'), 'utf8');
  assert.ok(markup.indexOf('名字来源') < markup.indexOf('名字用字'));
  assert.ok(markup.indexOf('名字用字') < markup.indexOf('继续寻名'));
  assert.ok(markup.indexOf('继续寻名') < markup.indexOf('千千嘉名'));
  for (const hidden of ['全开', '全关', '默认全部开启', '从喜欢的典籍与年号中寻找名字', '当前偏好', 'OpenID', '隐私与同步', '名字释义由模型辅助整理']) {
    assert.doesNotMatch(markup, new RegExp(hidden));
  }
  assert.doesNotMatch(markup, /enableAllSources|disableAllSources/);
});
