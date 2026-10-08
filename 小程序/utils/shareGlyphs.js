// Draw the selected font's original TrueType outlines instead of registering a font.
const groups = require('../assets/share/font-map');
const banks = new Map();
function loadBank(bank) {
  if (!banks.has(bank)) banks.set(bank, (async () => {
    const fs = wx.getFileSystemManager();
    const directory = `${wx.env.USER_DATA_PATH}/share-zhenkai-outlines-046-${bank}`;
    try { return JSON.parse(fs.readFileSync(`${directory}/glyphs.json`, 'utf8')); } catch {}
    const data = bank === 0 ? await require.async('../share-font-a/font.js') : await require.async('../share-font-b/font.js');
    try { fs.accessSync(directory); } catch { fs.mkdirSync(directory, true); }
    const zip = `${directory}/glyphs.zip`;
    fs.writeFileSync(zip, data.zip_base64, 'base64');
    await new Promise((resolve, reject) => fs.unzip({zipFilePath: zip, targetPath: directory,
      success: resolve, fail: () => reject(new Error('姓名字形读取失败，请重试'))}));
    const glyphs = JSON.parse(fs.readFileSync(`${directory}/glyphs.json`, 'utf8'));
    try { fs.unlinkSync(zip); } catch {}
    return glyphs;
  })().catch(error => { banks.delete(bank); throw error; }));
  return banks.get(bank);
}
function contours(encoded) {
  const bytes = new Uint8Array(wx.base64ToArrayBuffer(encoded));
  let offset = 0;
  const read = () => {
    let value = 0, shift = 0, byte;
    do {
      if (offset >= bytes.length || shift > 28) throw new Error('姓名字形数据损坏');
      byte = bytes[offset++]; value |= (byte & 127) << shift; shift += 7;
    } while (byte & 128);
    return value;
  };
  const signed = n => n & 1 ? -(n + 1) / 2 : n / 2;
  const count = read(), lengths = Array.from({length: count}, read);
  let x = 0, y = 0;
  return lengths.map(length => Array.from({length}, () => {
    x += signed(read()); y += signed(read());
    if (offset >= bytes.length) throw new Error('姓名字形数据损坏');
    return {x, y, on: !!bytes[offset++]};
  }));
}
function midpoint(a, b) { return {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, on: true}; }
function outline(ctx, points) {
  const first = points[0], last = points[points.length - 1];
  const start = first.on ? first : last.on ? last : midpoint(last, first);
  const remaining = first.on ? points.slice(1) : last.on ? points.slice(0, -1) : points;
  ctx.moveTo(start.x, start.y);
  for (let i = 0; i < remaining.length;) {
    const point = remaining[i];
    if (point.on) { ctx.lineTo(point.x, point.y); i++; }
    else {
      const next = remaining[i + 1] || start;
      const end = next.on ? next : midpoint(point, next);
      ctx.quadraticCurveTo(point.x, point.y, end.x, end.y);
      i += next.on ? 2 : 1;
    }
  }
  ctx.closePath();
}
async function nameGlyphs(name) {
  return Promise.all(Array.from(name).map(async char => {
    const bank = groups.findIndex(group => group.includes(char));
    if (bank < 0) return {char};
    const data = await loadBank(bank), glyph = data.glyphs[char];
    if (!glyph) throw new Error('姓名字形缺失，请重试');
    return {char, ...glyph, units: data.units, contours: contours(glyph.points)};
  }));
}
function drawName(ctx, glyphs) {
  let size = 160, widths;
  do {
    ctx.font = `${size}px serif`;
    widths = glyphs.map(glyph => glyph.units ? glyph.advance * size / glyph.units : ctx.measureText(glyph.char).width);
    if (widths.reduce((a, b) => a + b, 0) <= 400) break;
  } while (--size > 24);
  const known = glyphs.filter(glyph => glyph.units);
  const ymin = known.length ? Math.min(...known.map(glyph => glyph.bounds[1] / glyph.units)) : 0;
  const ymax = known.length ? Math.max(...known.map(glyph => glyph.bounds[3] / glyph.units)) : 0;
  const baseline = 175 + (ymin + ymax) * size / 2;
  let x = 400 - widths.reduce((a, b) => a + b, 0) / 2;
  ctx.fillStyle = '#30493f'; ctx.textAlign = 'left';
  glyphs.forEach((glyph, i) => {
    if (glyph.units) {
      ctx.save(); ctx.translate(x, baseline); ctx.scale(size / glyph.units, -size / glyph.units); ctx.beginPath();
      glyph.contours.forEach(points => outline(ctx, points)); ctx.fill(); ctx.restore();
    } else { ctx.font = `${size}px serif`; ctx.fillText(glyph.char, x, 175); }
    x += widths[i];
  });
  ctx.textAlign = 'center';
}
module.exports = {nameGlyphs, drawName};
