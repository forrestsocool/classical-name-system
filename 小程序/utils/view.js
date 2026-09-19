// WXML expressions use ASCII aliases because the production payload keeps
// source fields in Chinese and the WeChat compiler only accepts ASCII names.
function normalizeItem(item = {}) {
  const original = item.original || item['原文'] || '';
  return {
    name: item.name || item['姓名'] || '',
    pinyin: item.pinyin || item['拼音带调'] || '',
    meaning: item.meaning || item['现代释义'] || '',
    tags: item.tags || item['文化标签'] || [],
    book: item.book || item['书名'] || '',
    chapter: item.chapter || item['篇章'] || '',
    original,
    excerpt: original.length > 46 ? `${original.slice(0, 46)}…` : original,
    extraction: item.extraction || item['取字方式'] || '',
    elements: item.elements || item['五行匹配'] || {},
    popularity: item.popularity || item['热门提示'] || {}
  };
}

function normalizeCard(card) {
  return card ? { ...card, item: normalizeItem(card.item) } : card;
}

function normalizeCards(cards) {
  return Array.isArray(cards) ? cards.map(normalizeCard) : [];
}

module.exports = { normalizeCard, normalizeCards };
