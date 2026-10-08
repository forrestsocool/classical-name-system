// WXML expressions use ASCII aliases because the production payload keeps
// source fields in Chinese and the WeChat compiler only accepts ASCII names.
const LABELS = ['金', '木', '水', '火', '土'];
const KEYS = ['jin', 'mu', 'shui', 'huo', 'tu'];
const {surnamePinyin, markedPinyin} = require('./surnamePinyin');
function pendingWuxing(name) {
  return {version: 'pending', analyzed_name: name, available: false, status: '正在读取五行资料',
    explanation: '正在读取五行资料，请稍后再试。',
    items: LABELS.map((label, i) => ({key: KEYS[i], label, percent: null,
      description: `${label}，正在读取`, cells: [0,1,2,3,4].map(id => ({id, fill: 0}))}))};
}
function normalizeItem(item = {}, surname = '') {
  const original = item.original || item['原文'] || '';
  const name = item.name || item['姓名'] || '';
  const selectedSurname = surname || item.surname || '';
  const displayName = selectedSurname ? selectedSurname + name : (item.displayName || name);
  const givenPinyin = markedPinyin(item.givenPinyin || item['拼音带调'] || item.pinyin || '');
  const rawMaleScore = item.maleScore != null ? item.maleScore : item['男孩适配分'];
  const rawFemaleScore = item.femaleScore != null ? item.femaleScore : item['女孩适配分'];
  const maleScore = Number(rawMaleScore);
  const femaleScore = Number(rawFemaleScore);
  const book = item.book || item['书名'] || '';
  return {
    name,
    displayName,
    surname: selectedSurname,
    givenPinyin,
    wuxing: item.wuxing && item.wuxing.version === 'server-v1' && item.wuxing.analyzed_name === displayName
      ? item.wuxing : pendingWuxing(displayName),
    pinyin: [surnamePinyin(selectedSurname), givenPinyin].filter(Boolean).join(' '),
    meaning: item.meaning || item['现代释义'] || '',
    tags: item.tags || item['文化标签'] || [],
    book,
    isGaokao: book === '历年高考状元',
    chapter: item.chapter || item['篇章'] || '',
    examSources: item.examSources || item['高考来源'] || [],
    original,
    excerpt: original.length > 46 ? `${original.slice(0, 46)}…` : original,
    extraction: item.extraction || item['取字方式'] || '',
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
