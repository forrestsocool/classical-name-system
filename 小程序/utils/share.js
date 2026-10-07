const {call} = require('./api');
const prepared = new Map();

function storeShareImage(result) {
  if (!result.image_base64 || typeof wx === 'undefined' || !wx.getFileSystemManager) return result.image_url || '/assets/share-cover.jpg';
  if (!/^[A-Za-z0-9_-]{32}$/.test(result.token || '')) return '/assets/share-cover.jpg';
  const path = `${wx.env.USER_DATA_PATH}/share-${result.token}.jpg`;
  try {
    wx.getFileSystemManager().writeFileSync(path, result.image_base64, 'base64');
    return path;
  } catch {
    return '/assets/share-cover.jpg';
  }
}

function prepareShare(card) {
  if (!card) return Promise.resolve(null);
  if (prepared.has(card.id)) return prepared.get(card.id);
  const task = call('shares.create', {material_id: card.id}).then(result => {
    if (!result.token) throw new Error('分享链接未准备好');
    return {...result, imageUrl: storeShareImage(result)};
  }).catch(error => { prepared.delete(card.id); throw error; });
  prepared.set(card.id, task);
  if (prepared.size > 32) prepared.delete(prepared.keys().next().value);
  return task;
}

function shareName(card) {
  const fallback = {title: '从典籍里挑一个好名字｜好名书中来',
    path: '/pages/discover/index', imageUrl: '/assets/share-cover.jpg'};
  if (!card) return fallback;
  const {name, book} = card.item;
  const title = book ? `「${name}」出自《${book}》，你觉得怎么样？` : `「${name}」，你觉得怎么样？`;
  return {...fallback, title, promise: prepareShare(card)
    .then(result => ({title, path: `/pages/detail/index?share=${encodeURIComponent(result.token)}`,
      imageUrl: result.imageUrl || fallback.imageUrl})).catch(() => ({...fallback, title}))};
}

module.exports = {shareName, prepareShare, storeShareImage};
