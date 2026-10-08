const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

test('bundled name fonts contain the selected GB2312 Han subset only', () => {
  const groups = require('../小程序/assets/share/font-map');
  const info = require('../小程序/assets/share/font-info');
  assert.match(info.family, /WenKai/);
  assert.match(info.id, /^[a-f0-9]{16}$/);
  const characters = Array.from(groups.join(''));
  const kept = new Set(characters);
  assert.equal(kept.size, 6763);
  assert.equal(groups.length, 2);
  assert.equal(characters.length, kept.size);
  assert.ok(characters.every(char => /^\p{Unified_Ideograph}$/u.test(char)));
  for (const char of Array.from('书龙台后宁')) assert.ok(kept.has(char));
  for (const char of Array.from('軎麴齄')) assert.ok(kept.has(char));
  assert.equal(kept.has('𬭶'), false);
  for (const char of Array.from('書龍臺寧ABCabc123，。！？')) assert.equal(kept.has(char), false);
});

test('local canvas draws existing name, source and tags then exports a JPEG without an API', async () => {
  const texts = [], exports = [], outlines = [], curves = [];
  const ctx = new Proxy({measureText: text => ({width: text.length * 20}),
    fillText: text => texts.push(text), moveTo: (...point) => outlines.push(point),
    quadraticCurveTo: (...curve) => curves.push(curve)}, {get: (obj, key) => key in obj ? obj[key] : () => {}});
  const canvas = {getContext: () => ctx, createImage: () => {
    const asset = {};
    Object.defineProperty(asset, 'src', {set: src => {assert.match(src, /background.jpg$/); queueMicrotask(() => asset.onload());}});
    return asset;
  }};
  const query = {in: () => query, select: () => query, fields: () => query,
    exec: done => done([{node: canvas}])};
  // Off-curve points require implied midpoint endpoints, as in the real font.
  const points = Buffer.from([1, 3, 0, 0, 0, 208, 15, 0, 0, 207, 15, 208, 15, 0]).toString('base64');
  const data = {units: 1000, glyphs: Object.fromEntries(['李', '以', '宁'].map(char => [char,
    {advance: 1000, bounds: [0, 0, 1000, 1000], points}]))};
  let unpacked = false, fontRegistrations = 0;
  const wx = {
    env: {USER_DATA_PATH: 'wxfile://usr'},
    createSelectorQuery: () => query,
    base64ToArrayBuffer: text => {const b = Buffer.from(text, 'base64'); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);},
    getFileSystemManager: () => ({
      readFileSync: () => {if (!unpacked) throw new Error('ENOENT'); return JSON.stringify(data);},
      mkdirSync: () => {}, writeFileSync: () => {}, unlinkSync: () => {},
      unzip: args => {unpacked = true; args.success();}
    }),
    loadFontFace: () => {fontRegistrations++; throw new Error('iOS native font unsupported');},
    canvasToTempFilePath: args => {exports.push(args); args.success({tempFilePath: 'wxfile://temp/local.jpg'});}
  };
  const fontRequire = name => name.endsWith('font-info') ? {id: 'wenkai-test'} : ['李以宁', ''];
  fontRequire.async = async () => ({zip_base64: 'emlw'});
  const glyphSandbox = {module: {exports: {}}, require: fontRequire, wx};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../小程序/utils/shareGlyphs.js'), 'utf8'), glyphSandbox);
  const sandbox = {module: {exports: {}}, require: () => glyphSandbox.module.exports, setTimeout, clearTimeout, wx};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../小程序/utils/shareCanvas.js'), 'utf8'), sandbox);
  const result = await sandbox.module.exports.renderShareImage({id: 1,
    item: {name: '以宁', displayName: '李以宁', book: '道德经', chapter: '第三十九章', tags: ['安宁', '持重']}}, {});
  assert.equal(result, 'wxfile://temp/local.jpg');
  assert.deepEqual(texts, ['《道德经》 · 第三十九章', '安宁', '持重']);
  assert.ok(outlines.length >= 2);
  assert.deepEqual(outlines[0], [0, 500]);
  assert.deepEqual(curves[0], [0, 0, 500, 0]);
  assert.equal(curves.length, 9);
  assert.equal(fontRegistrations, 0);
  assert.equal(exports[0].fileType, 'jpg');
  assert.equal(exports[0].destWidth, 750);
  assert.equal(exports[0].destHeight, 600);
});
