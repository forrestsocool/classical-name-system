// Store disabled sources: newly added books remain enabled by default.
function cleanCharacters(value, limit) {
  return [...new Set(String(value || '').replace(/[^\u3400-\u9fff]/g, ''))].slice(0, limit).join('');
}

function normalizeFilters(value = {}) {
  return {
    required: cleanCharacters(value.required, 2),
    excluded: cleanCharacters(value.excluded, 32),
    excluded_sources: [...new Set((Array.isArray(value.excluded_sources) ? value.excluded_sources : [])
      .filter(name => typeof name === 'string' && name.length && name.length <= 100))].sort().slice(0, 256)
  };
}

function filterKey(value) {
  const filters = normalizeFilters(value);
  return JSON.stringify({...filters, required: [...filters.required].sort().join(''), excluded: [...filters.excluded].sort().join('')});
}

function filterError(value) {
  const filters = normalizeFilters(value);
  const conflict = [...filters.required].filter(char => filters.excluded.includes(char));
  return conflict.length ? `「${conflict.join('、')}」不能同时要求包含和避开` : '';
}

function matchesCard(card, filters) {
  const item = card.item;
  const name = item.name || item['名字'] || item['姓名'] || '';
  const book = item.book || item['书名'] || '';
  return !filters.excluded_sources.includes(book)
    && [...filters.required].every(char => name.includes(char))
    && ![...filters.excluded].some(char => name.includes(char));
}

module.exports = {cleanCharacters, normalizeFilters, filterKey, filterError, matchesCard};
