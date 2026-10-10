const test = require('node:test');
const assert = require('node:assert/strict');
const {normalizeCard} = require('../小程序/utils/view');

test('home and favorites get full pinyin, including compound surnames, without duplication', () => {
  const raw = {id: 1, item: {姓名: '以宁', 拼音带调: 'yǐ níng'}};
  const single = normalizeCard(raw, '李');
  assert.equal(single.item.pinyin, 'lǐ yǐ níng');
  assert.equal(normalizeCard(single, '李').item.pinyin, 'lǐ yǐ níng');
  assert.equal(normalizeCard(single, '王').item.pinyin, 'wáng yǐ níng');
  assert.equal(normalizeCard(raw, '欧阳').item.pinyin, 'ōu yáng yǐ níng');
  assert.equal(normalizeCard(raw, '单').item.pinyin, 'shàn yǐ níng');
  assert.equal(normalizeCard({id: 2, item: {姓名: '克堪', 拼音带调: 'ke4 kan1'}}, '李').item.pinyin, 'lǐ kè kān');
});
