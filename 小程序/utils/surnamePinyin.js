const readings = require('../assets/surname-pinyin');
const special = {
  '单': 'shàn', '区': 'ōu', '仇': 'qiú', '解': 'xiè', '曾': 'zēng', '查': 'zhā',
  '乐': 'yuè', '朴': 'piáo', '缪': 'miào', '任': 'rén', '华': 'huà',
  '盖': 'gě', '种': 'chóng', '秘': 'bì', '折': 'shé', '繁': 'pó', '员': 'yùn',
  '欧阳': 'ōu yáng', '尉迟': 'yù chí', '万俟': 'mò qí', '长孙': 'zhǎng sūn',
  '令狐': 'líng hú', '诸葛': 'zhū gě', '司马': 'sī mǎ', '夏侯': 'xià hóu'
};
function surnamePinyin(surname = '') {
  return special[surname] || Array.from(surname).map(char => special[char] || readings[char] || char).join(' ');
}
function markedPinyin(text = '') {
  const marks = {a: 'āáǎà', e: 'ēéěè', i: 'īíǐì', o: 'ōóǒò', u: 'ūúǔù', 'ü': 'ǖǘǚǜ'};
  return text.replace(/[a-züv:]+[1-5]/gi, word => {
    const tone = Number(word.slice(-1));
    const syllable = word.slice(0, -1).toLowerCase().replace(/u:|v/g, 'ü');
    if (tone === 5) return syllable;
    let index = syllable.indexOf('a');
    if (index < 0) index = syllable.indexOf('e');
    if (index < 0 && syllable.includes('ou')) index = syllable.indexOf('o');
    if (index < 0) for (let i = syllable.length - 1; i >= 0; i--) if (marks[syllable[i]]) {index = i; break;}
    return index < 0 ? syllable : syllable.slice(0, index) + marks[syllable[index]][tone - 1] + syllable.slice(index + 1);
  });
}
module.exports = {surnamePinyin, markedPinyin};
