// All artwork and text are drawn locally. Only the durable share link needs the API.
const queues = new WeakMap();
const fontGroups = require('../assets/share/font-map');
const fontTasks = new Map();
function bankFor(char) { return fontGroups.findIndex(group => group.includes(char)); }
function fontModule(bank) {
  switch (bank) {
    case 0: return require.async('../share-font-a/font.js');
    case 1: return require.async('../share-font-b/font.js');
    default: return Promise.reject(new Error('字形不在本地字表中'));
  }
}
function loadBank(bank) {
  if (!fontTasks.has(bank)) fontTasks.set(bank, new Promise(resolve => {
    let finished = false;
    const done = value => { if (!finished) { finished = true; resolve(value); } };
    const timer = setTimeout(() => done(false), 12000);
    const loading = fontModule(bank);
    loading.then(({base64}) => {
      try {
        wx.loadFontFace({family: `ShareZhenKai${bank}`, global: true, scopes: ['native'],
          source: `url("data:font/woff2;base64,${base64}")`,
          success: () => { clearTimeout(timer); done(true); },
          fail: () => { clearTimeout(timer); done(false); }});
      } catch { clearTimeout(timer); done(false); }
    }).catch(() => { clearTimeout(timer); done(false); });
  }));
  return fontTasks.get(bank);
}
async function loadFonts(name) {
  const banks = [...new Set(Array.from(name).map(bankFor).filter(bank => bank >= 0))];
  const loaded = await Promise.all(banks.map(loadBank));
  return bank => banks.includes(bank) && loaded[banks.indexOf(bank)];
}
function canvasNode(page) {
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const find = () => wx.createSelectorQuery().in(page).select('#shareCanvas').fields({node: true}).exec(rows => {
      if (rows[0] && rows[0].node) resolve(rows[0].node);
      else if (++attempts < 15) setTimeout(find, 100);
      else reject(new Error('分享画布未准备好，请重试'));
    });
    find();
  });
}
function image(canvas, path) {
  return new Promise((resolve, reject) => {
    const asset = canvas.createImage();
    asset.onload = () => resolve(asset);
    asset.onerror = () => reject(new Error('分享背景读取失败'));
    asset.src = path;
  });
}
function fit(ctx, text, size, width, family) {
  do { ctx.font = `${size}px ${family}`; if (ctx.measureText(text).width <= width) break; size--; } while (size > 12);
  return size;
}
function ellipse(ctx, text, width) {
  if (ctx.measureText(text).width <= width) return text;
  while (text && ctx.measureText(text + '…').width > width) text = text.slice(0, -1);
  return text + '…';
}
function pill(ctx, x, y, width, height) {
  const radius = height / 2;
  ctx.beginPath(); ctx.moveTo(x + radius, y);
  ctx.lineTo(x + width - radius, y); ctx.arc(x + width - radius, y + radius, radius, -Math.PI / 2, Math.PI / 2);
  ctx.lineTo(x + radius, y + height); ctx.arc(x + radius, y + radius, radius, Math.PI / 2, Math.PI * 1.5);
  ctx.closePath(); ctx.fill(); ctx.stroke();
}
async function draw(card, page) {
  const item = card.item;
  const name = Array.from(String(item.name || item['姓名'] || '')).slice(0, 4).join('');
  const [canvas, hasFont] = await Promise.all([canvasNode(page), loadFonts(name)]);
  page.shareFontLoaded = Array.from(name).every(char => hasFont(bankFor(char)));
  canvas.width = 750; canvas.height = 600;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(await image(canvas, '/assets/share/background.jpg'), 0, 0, 750, 600);
  const book = String(item.book || item['书名'] || '');
  const chapter = String(item.chapter || item['篇章'] || '');
  const tags = (item.tags || item['文化标签'] || []).slice(0, 3).map(tag => String(tag).slice(0, 12));
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  const chars = Array.from(name);
  const family = char => hasFont(bankFor(char)) ? `ShareZhenKai${bankFor(char)}` : 'serif';
  let nameSize = 160, nameWidths;
  do {
    nameWidths = chars.map(char => { ctx.font = `${nameSize}px ${family(char)}`; return ctx.measureText(char).width; });
    if (nameWidths.reduce((a, b) => a + b, 0) <= 400) break;
  } while (--nameSize > 24);
  let nameX = 400 - nameWidths.reduce((a, b) => a + b, 0) / 2;
  ctx.textAlign = 'left'; ctx.fillStyle = '#30493f';
  chars.forEach((char, i) => { ctx.font = `${nameSize}px ${family(char)}`; ctx.fillText(char, nameX, 175); nameX += nameWidths[i]; });
  ctx.textAlign = 'center';
  ctx.strokeStyle = '#a83d32'; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(384, 289); ctx.lineTo(416, 289); ctx.stroke();
  const small = '"PingFang SC", "Microsoft YaHei", sans-serif';
  const source = book ? `《${book}》${chapter ? ' · ' + chapter : ''}` : '';
  fit(ctx, source, 22, 480, small); ctx.fillStyle = '#52685b';
  ctx.fillText(ellipse(ctx, source, 480), 400, 327);
  let size = 20, widths;
  do {
    ctx.font = `${size}px ${small}`;
    widths = tags.map(tag => ctx.measureText(tag).width + 30);
    if (widths.reduce((a, b) => a + b, 0) + Math.max(0, tags.length - 1) * 12 <= 480) break;
  } while (--size > 10);
  let x = 400 - (widths.reduce((a, b) => a + b, 0) + Math.max(0, tags.length - 1) * 12) / 2;
  tags.forEach((tag, i) => {
    ctx.fillStyle = '#ebf0e0'; ctx.strokeStyle = '#c4d1bc'; ctx.lineWidth = 1;
    pill(ctx, x, 364, widths[i], 40); ctx.fillStyle = '#46624e'; ctx.fillText(tag, x + widths[i] / 2, 384);
    x += widths[i] + 12;
  });
  return new Promise((resolve, reject) => wx.canvasToTempFilePath({canvas, x: 0, y: 0,
    width: 750, height: 600, destWidth: 750, destHeight: 600, fileType: 'jpg', quality: .92,
    success: result => resolve(result.tempFilePath), fail: () => reject(new Error('分享图片生成失败，请重试'))}, page));
}
function renderShareImage(card, page) {
  const previous = queues.get(page) || Promise.resolve();
  const task = previous.catch(() => {}).then(() => draw(card, page));
  queues.set(page, task);
  return task;
}
module.exports = {renderShareImage};
