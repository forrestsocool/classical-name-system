const {call} = require('./api');
const {renderShareImage} = require('./shareCanvas');
const prepared = new Map();
const ready = new Map();
function shareSurname(card) {
  const item = card.item;
  if (item.surname) return item.surname;
  return item.name && item.displayName && item.displayName.endsWith(item.name)
    ? item.displayName.slice(0, -item.name.length) : '';
}
function sharePath(token, card) {
  const surname = shareSurname(card);
  return `/pages/detail/index?share=${encodeURIComponent(token)}` +
    (surname ? `&surname=${encodeURIComponent(surname)}` : '');
}
function shareKey(card) { return JSON.stringify([card.id, shareSurname(card)]); }

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

function prepareShare(card, page) {
  if (!card) return Promise.resolve(null);
  const key = shareKey(card);
  if (prepared.has(key)) return prepared.get(key);
  const local = page && typeof wx !== 'undefined';
  const task = Promise.all([
    call('shares.create', {material_id: card.id, ...(local ? {include_image: false} : {})}),
    local ? renderShareImage(card, page) : Promise.resolve(null)
  ]).then(([result, localImage]) => {
    if (!result.token) throw new Error('分享链接未准备好');
    const share = {token: result.token, imageUrl: localImage || storeShareImage(result)};
    ready.set(key, share);
    return share;
  }).catch(error => {
    prepared.delete(key);
    if (page) page.sharePrepareError = error.message || String(error);
    throw error;
  });
  prepared.set(key, task);
  if (prepared.size > 64) {
    const oldest = prepared.keys().next().value;
    prepared.delete(oldest);
    ready.delete(oldest);
  }
  return task;
}

function shareName(card, page) {
  const fallback = {title: '从典籍里挑一个好名字｜好名书中来',
    path: '/pages/discover/index', imageUrl: '/assets/share-cover.jpg'};
  if (!card) return fallback;
  const name = card.item.displayName || card.item.name;
  const {book} = card.item;
  const title = book ? `「${name}」出自《${book}》，你觉得怎么样？` : `「${name}」，你觉得怎么样？`;
  const cached = ready.get(shareKey(card));
  if (cached) return {title, path: sharePath(cached.token, card),
    imageUrl: cached.imageUrl};
  return {...fallback, title, promise: prepareShare(card, page)
    .then(result => ({title, path: sharePath(result.token, card),
      imageUrl: result.imageUrl || fallback.imageUrl})).catch(() => ({...fallback, title}))};
}

module.exports = {shareName, prepareShare, storeShareImage, sharePath};
