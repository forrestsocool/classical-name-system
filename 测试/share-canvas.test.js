const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('bundled name fonts map only Han, including rare standard characters', () => {
  const groups = require('../小程序/assets/share/font-map');
  const characters = Array.from(groups.join(''));
  const kept = new Set(characters);
  assert.equal(kept.size, 16538);
  assert.equal(characters.length, kept.size);
  assert.ok(characters.every(char => /^\p{Unified_Ideograph}$/u.test(char)));
  for (const char of Array.from('书龙台后宁𬭶')) assert.ok(kept.has(char));
  for (const char of Array.from('書龍臺後寧ABCabc123，。！？')) assert.equal(kept.has(char), false);
});

test('local canvas draws existing name, source and tags then exports a JPEG without an API', async () => {
  const texts = [], exports = [], fonts = [];
  const ctx = new Proxy({measureText: text => ({width: text.length * 20}),
    fillText: text => texts.push(text)}, {get: (obj, key) => key in obj ? obj[key] : () => {}});
  const canvas = {getContext: () => ctx, createImage: () => {
    const asset = {};
    Object.defineProperty(asset, 'src', {set: src => {assert.match(src, /background.jpg$/); queueMicrotask(() => asset.onload());}});
    return asset;
  }};
  const query = {in: () => query, select: () => query, fields: () => query,
    exec: done => done([{node: canvas}])};
  const fontRequire = () => ['以宁', ''];
  fontRequire.async = async () => ({base64: 'Zm9udA=='});
  const sandbox = {module: {exports: {}}, require: fontRequire, setTimeout, clearTimeout, wx: {
    createSelectorQuery: () => query,
    getFileSystemManager: () => ({readFileSync: () => '{"base64":"Zm9udA=="}'}),
    loadSubpackage: args => args.success(),
    loadFontFace: args => {fonts.push(args); args.success();},
    canvasToTempFilePath: args => {exports.push(args); args.success({tempFilePath: 'wxfile://temp/local.jpg'});}
  }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../小程序/utils/shareCanvas.js'), 'utf8'), sandbox);
  const result = await sandbox.module.exports.renderShareImage({id: 1,
    item: {name: '以宁', displayName: '李以宁', book: '道德经', chapter: '第三十九章', tags: ['安宁', '持重']}}, {});
  assert.equal(result, 'wxfile://temp/local.jpg');
  assert.deepEqual(texts, ['以', '宁', '《道德经》 · 第三十九章', '安宁', '持重']);
  assert.equal(exports[0].fileType, 'jpg');
  assert.equal(exports[0].destWidth, 750);
  assert.equal(exports[0].destHeight, 600);
  assert.equal(fonts[0].scopes[0], 'native');
});
