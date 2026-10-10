let fontTask;
let ready = false;
function moduleFor(index) {
  if (index === 0) return require.async('../page-font-a/font.js');
  if (index === 1) return require.async('../page-font-b/font.js');
  return require.async('../page-font-c/font.js');
}
function register(index, base64) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('姓名字体加载超时')), 15000);
    wx.loadFontFace({family: `PageWenKai${index}`, global: true, scopes: ['webview'],
      desc: {weight: '500', style: 'normal'}, source: `url("data:font/woff;base64,${base64}")`,
      success: () => { clearTimeout(timer); resolve(); },
      fail: () => { clearTimeout(timer); reject(new Error('姓名字体暂不可用')); }});
  });
}
function loadNameFont() {
  if (!fontTask) fontTask = (async () => {
    // Serial background loads avoid three simultaneous font downloads.
    for (let index = 0; index < 3; index++) {
      const data = await moduleFor(index);
      await register(index, data.base64);
    }
    ready = true;
  })().catch(error => {fontTask = null; throw error;});
  return fontTask;
}
function warmNameFont(page) {
  if (page.nameFontQueued || page.closed) return;
  if (ready) { page.setData({nameFontReady: true}); return; }
  page.nameFontQueued = true;
  // Start only after cards are visible, never from onLaunch or before feed data.
  setTimeout(() => {
    if (page.closed) return;
    loadNameFont().then(() => {
      const apply = () => {
        if (page.closed) return;
        if (page.data.animating || page.data.dragging) {setTimeout(apply, 150); return;}
        page.setData({nameFontReady: true});
      };
      apply();
    }).catch(() => {page.nameFontQueued = false;});
  }, 2000);
}
module.exports = {warmNameFont};
