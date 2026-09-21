const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {highlightText} = require('../小程序/utils/richText');

test('source highlighting marks every exact given-name occurrence as bold text', () => {
  const nodes = highlightText('清和有余，清和而不盈。', '清和');
  const marked = nodes.filter(node => node.name === 'span');
  assert.equal(marked.length, 2);
  assert.ok(marked.every(node => node.attrs.class === 'source-hit'));
  assert.ok(marked.every(node => /font-weight:700/.test(node.attrs.style)));
  assert.deepEqual(marked.map(node => node.children[0].text), ['清和', '清和']);
});

test('detail page renders highlighted original and keeps meaning in one section', () => {
  const markup = fs.readFileSync(path.join(__dirname, '../小程序/pages/detail/index.wxml'), 'utf8');
  const script = fs.readFileSync(path.join(__dirname, '../小程序/pages/detail/index.js'), 'utf8');
  assert.match(markup, /rich-text class="source-quote" nodes="\{\{card\.item\.originalNodes\}\}"/);
  assert.doesNotMatch(markup, /summary-meaning/);
  assert.match(markup, /释义与寓意/);
  assert.match(markup, /class="detail-section" wx:if="\{\{showElements\}\}"/);
  assert.match(script, /showElements: false/);
  assert.match(script, /highlightText\(card\.item\.original, card\.item\.name\)/);
});
