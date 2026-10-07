const {call} = require('./api');

function shareName(card) {
  const fallback = {title: '从典籍里挑一个好名字｜好名书中来',
    path: '/pages/discover/index', imageUrl: '/assets/share-cover.jpg'};
  if (!card) return fallback;
  const {name, book} = card.item;
  const title = book ? `「${name}」出自《${book}》，你觉得怎么样？` : `「${name}」，你觉得怎么样？`;
  return {...fallback, title, promise: call('shares.create', {material_id: card.id})
    .then(result => ({title, path: `/pages/detail/index?share=${encodeURIComponent(result.token)}`,
      imageUrl: fallback.imageUrl})).catch(() => ({...fallback, title}))};
}

module.exports = {shareName};
