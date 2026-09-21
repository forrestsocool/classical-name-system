function textNode(text) {
  return {type: 'text', text: String(text || '')};
}

function highlightText(source, target) {
  const original = String(source || '');
  const name = String(target || '');
  if (!original || !name) return [textNode(original)];
  const nodes = [];
  let cursor = 0;
  while (cursor < original.length) {
    const index = original.indexOf(name, cursor);
    if (index < 0) {
      nodes.push(textNode(original.slice(cursor)));
      break;
    }
    if (index > cursor) nodes.push(textNode(original.slice(cursor, index)));
    nodes.push({
      name: 'span',
      attrs: {class: 'source-hit', style: 'font-weight:700;color:#182a27;'},
      children: [textNode(name)]
    });
    cursor = index + name.length;
  }
  return nodes.length ? nodes : [textNode(original)];
}

module.exports = {highlightText};
