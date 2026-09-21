const {call} = require('../../utils/api');
const {normalizeCard} = require('../../utils/view');
const {highlightText} = require('../../utils/richText');

Page({
  data: {
    statusBarHeight: 0, card: null, elements: [], unknown: '', showElements: false,
    popularity: '未命中已收录的历史热门资料，不代表实时重名率。',
    busy: false, error: ''
  },
  onLoad() {
    const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    const card = normalizeCard(getApp().selectedCard, getApp().selectedSurname || '');
    this.setData({statusBarHeight: info.statusBarHeight || 0});
    if (!card) return;
    const elements = card.item.elements || {};
    const hot = card.item.popularity || {};
    const rawHints = hot.hints || hot['提示'];
    const hints = Array.isArray(rawHints) ? rawHints.join('；') : rawHints;
    this.setData({
      card: {...card, item: {...card.item, originalNodes: highlightText(card.item.original, card.item.name)}},
      elements: Object.entries(elements.known || elements['已知字符'] || {}).map(([char, element]) => ({char, element})),
      unknown: (elements.unknown || elements['未知字符'] || []).join('、'),
      popularity: hints ? hints + '。' + (hot.note || hot['说明'] || '') : this.data.popularity
    });
  },
  goBack() {
    if (getCurrentPages().length > 1) wx.navigateBack();
    else wx.switchTab({url: '/pages/discover/index'});
  },
  continueChoosing() { wx.switchTab({url: '/pages/discover/index'}); },
  async favorite() {
    if (this.data.busy || !this.data.card) return;
    this.setData({busy: true, error: ''});
    try {
      await call('favorites.add', {material_id: this.data.card.id});
      getApp().pendingFavorite = {id: this.data.card.id};
      wx.switchTab({url: '/pages/discover/index'});
    } catch (error) {
      this.setData({error: error.message});
      this.setData({busy: false});
    }
  },
  feedback() {
    if (this.data.busy || !this.data.card) return;
    const kinds = ['出处问题', '释义问题'];
    wx.showActionSheet({itemList: kinds, success: async result => {
      this.setData({busy: true, error: ''});
      try {
        await call('feedback.save', {material_id: this.data.card.id, kind: kinds[result.tapIndex]});
        wx.showToast({title: '感谢反馈', icon: 'success'});
      } catch (error) {
        this.setData({error: error.message});
      } finally {
        this.setData({busy: false});
      }
    }});
  }
});
