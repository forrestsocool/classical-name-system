const config = require('../config');
function key(kind, user) {
  return `name-page-cache-v1:${config.mode}:${config.envId || config.httpUrl}:${kind}:${user}`;
}
function readCache(kind, user) {
  if (!user) return null;
  try {
    const cached = wx.getStorageSync(key(kind, user));
    return cached && cached.version === 1 ? cached.data : null;
  } catch { return null; }
}
function writeCache(kind, user, data) {
  if (!user) return;
  try { wx.setStorageSync(key(kind, user), {version: 1, data}); } catch {}
}
module.exports = {readCache, writeCache};
