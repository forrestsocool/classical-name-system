const {call} = require('../../utils/api');
const {normalizeCard} = require('../../utils/view');
const {highlightText} = require('../../utils/richText');

Page({
  data: {
    statusBarHeight: 0, card: null, elements: [], showElements: false,
    popularity: '未命中已收录的历史热门资料，不代表实时重名率。',
    busy: false, error: ''
  },
  async onLoad() {
    const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    const card = normalizeCard(getApp().selectedCard, getApp().selectedSurname || '');
    this.setData({statusBarHeight: info.statusBarHeight || 0});
    if (!card) return;
    const hot = card.item.popularity || {};
    const rawHints = hot.hints || hot['提示'];
    const hints = Array.isArray(rawHints) ? rawHints.join('；') : rawHints;
    this.setData({
      card: {...card, item: {...card.item, originalNodes: highlightText(card.item.original, card.item.name)}},
      popularity: hints ? hints + '。' + (hot.note || hot['说明'] || '') : this.data.popularity
    });
    try {
      const result = await call('names.detail', {material_id: card.id, surname: getApp().selectedSurname || ''});
      const elements = Array.isArray(result.elements) ? result.elements : [];
      this.setData({elements, showElements: elements.length > 0,
        card: {...this.data.card, item: {...this.data.card.item, wuxing: result.wuxing}}});
    } catch (error) {
      this.setData({error: '五行资料暂时无法读取：' + (error.message || '请稍后重试')});
    }
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
