const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {normalizeCard} = require('../小程序/utils/view');

test('mini program contains no packaged five-element corpus or source text', () => {
  const root = path.join(__dirname, '../小程序');
  const files = [];
  function visit(dir) {
    for (const item of fs.readdirSync(dir, {withFileTypes: true})) {
      const file = path.join(dir, item.name);
      if (item.isDirectory()) visit(file);
      else files.push(file);
    }
  }
  visit(root);
  assert.ok(!files.some(file => /wuxing-(kb|sources)\.js$/.test(file)));
  assert.ok(!files.some(file => /wuxingSources\.js$|utils[\\/]wuxing\.js$/.test(file)));
  for (const file of files.filter(file => /\.js$/.test(file))) {
    const source = fs.readFileSync(file, 'utf8');
    assert.doesNotMatch(source, /wuxing-kb|wuxing-sources|semantic_notes|wuxing_knowledge_base/);
  }
});

test('only current-name server analysis is displayed; stale local cache is ignored', () => {
  const original = {id: 1, item: {姓名: '清熙', wuxing: {version: 'old-digest', analyzed_name: '清熙'}}};
  assert.equal(normalizeCard(original).item.wuxing.available, false);
  const result = {version: 'server-v1', analyzed_name: '清熙', available: true, items: []};
  const card = normalizeCard({...original, item: {...original.item, wuxing: result}});
  assert.equal(card.item.wuxing, result);
  assert.equal(normalizeCard(card, '李').item.wuxing.available, false);
  assert.equal(original.item.wuxing.version, 'old-digest');
});

test('home five-element meter is informational and opens no modal', () => {
  const root = path.join(__dirname, '../小程序/pages/discover/index');
  assert.doesNotMatch(fs.readFileSync(root + '.wxml', 'utf8'), /catchtap="showWuxing"|role="button" aria-label="查看姓名五行/);
  assert.doesNotMatch(fs.readFileSync(root + '.js', 'utf8'), /showWuxing\(\)/);
});
