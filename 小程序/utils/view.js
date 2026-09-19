// WXML expressions use ASCII aliases because the production payload keeps
// source fields in Chinese and the WeChat compiler only accepts ASCII names.
function normalizeItem(item = {}, surname = '') {
  const original = item.original || item['原文'] || '';
  const name = item.name || item['姓名'] || '';
  const displayName = surname ? surname + name : (item.displayName || name);
  const rawMaleScore = item.maleScore != null ? item.maleScore : item['男孩适配分'];
  const rawFemaleScore = item.femaleScore != null ? item.femaleScore : item['女孩适配分'];
  const maleScore = Number(rawMaleScore);
  const femaleScore = Number(rawFemaleScore);
  return {
    name,
    displayName,
    pinyin: item.pinyin || item['拼音带调'] || '',
    meaning: item.meaning || item['现代释义'] || '',
    tags: item.tags || item['文化标签'] || [],
    book: item.book || item['书名'] || '',
    chapter: item.chapter || item['篇章'] || '',
    original,
    excerpt: original.length > 46 ? `${original.slice(0, 46)}…` : original,
    extraction: item.extraction || item['取字方式'] || '',
    elements: item.elements || item['五行匹配'] || {},
    popularity: item.popularity || item['热门提示'] || {},
    maleScore: Number.isFinite(maleScore) ? maleScore : 50,
    femaleScore: Number.isFinite(femaleScore) ? femaleScore : 50
  };
}

function normalizeCard(card, surname = '') {
  return card ? { ...card, item: normalizeItem(card.item, surname) } : card;
}

function normalizeCards(cards, surname = '') {
  return Array.isArray(cards) ? cards.map(card => normalizeCard(card, surname)) : [];
}

module.exports = { normalizeCard, normalizeCards };
