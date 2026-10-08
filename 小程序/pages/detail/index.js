const {call} = require('../../utils/api');
const {normalizeCard} = require('../../utils/view');
const {highlightText} = require('../../utils/richText');
const {storeShareImage, sharePath} = require('../../utils/share');
const {renderShareImage} = require('../../utils/shareCanvas');

Page({
  data: {
    statusBarHeight: 0, card: null, elements: [], showElements: false,
    popularity: '未命中已收录的历史热门资料，不代表实时重名率。',
    busy: false, error: '', loading: false, loadError: '',
    isShared: false, shareToken: '', shareImageUrl: '', shareReady: false, shareLoading: false,
    shareError: '', shareUnavailable: false
  },
  async onLoad(options = {}) {
    const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    this.setData({statusBarHeight: info.statusBarHeight || 0});
    if (wx.hideShareMenu) wx.hideShareMenu({menus: ['shareAppMessage']});
    if (options.share) {
      this.setData({isShared: true, loading: true});
      try {
        const surname = decodeURIComponent(options.surname || '');
        const result = await call('shares.get', {token: options.share, surname, include_image: false});
        this.showCard(result.card, result.elements);
        const imageUrl = wx.createSelectorQuery ? await renderShareImage(this.data.card, this) : storeShareImage({...result, token: options.share});
        this.setData({shareToken: options.share, shareImageUrl: imageUrl, shareReady: true});
        if (wx.showShareMenu) wx.showShareMenu({menus: ['shareAppMessage']});
      } catch (error) {
        this.setData({loadError: error.message || '分享的名字暂时无法打开'});
      } finally {
        this.setData({loading: false});
      }
      return;
    }
    const card = normalizeCard(getApp().selectedCard, getApp().selectedSurname || '');
    if (!card) return;
    this.showCard(card);
    await Promise.all([this.loadOwnDetails(card), this.prepareShare(card.id)]);
  },
  showCard(rawCard, elements = []) {
    const card = normalizeCard(rawCard, this.data.isShared ? '' : getApp().selectedSurname || '');
    const hot = card.item.popularity || {};
    const rawHints = hot.hints || hot['提示'];
    const hints = Array.isArray(rawHints) ? rawHints.join('；') : rawHints;
    this.setData({
      card: {...card, item: {...card.item, originalNodes: highlightText(card.item.original, card.item.name)}},
      popularity: hints ? hints + '。' + (hot.note || hot['说明'] || '') : this.data.popularity,
      elements, showElements: elements.length > 0
    });
  },
  async loadOwnDetails(card) {
    try {
      const result = await call('names.detail', {material_id: card.id, surname: getApp().selectedSurname || ''});
      const elements = Array.isArray(result.elements) ? result.elements : [];
      this.setData({elements, showElements: elements.length > 0,
        card: {...this.data.card, item: {...this.data.card.item, wuxing: result.wuxing}}});
    } catch (error) {
      this.setData({error: '五行资料暂时无法读取：' + (error.message || '请稍后重试')});
    }
  },
  async prepareShare(materialId) {
    if (this.data.shareLoading) return;
    this.setData({shareLoading: true, shareError: ''});
    try {
      const [result, imageUrl] = await Promise.all([
        call('shares.create', {material_id: materialId, include_image: false}),
        wx.createSelectorQuery ? renderShareImage(this.data.card, this) : Promise.resolve('')
      ]);
      this.setData({shareToken: result.token, shareImageUrl: imageUrl || storeShareImage(result), shareReady: true, shareUnavailable: false});
      if (wx.showShareMenu) wx.showShareMenu({menus: ['shareAppMessage']});
    } catch (error) {
      this.setData({shareUnavailable: error.status === 404,
        shareError: error.status === 404 ? '' : '分享暂时没有准备好，轻点重试'});
    } finally {
      this.setData({shareLoading: false});
    }
  },
  retryShare() {
    if (this.data.card && !this.data.isShared) return this.prepareShare(this.data.card.id);
  },
  onShareAppMessage() {
    const card = this.data.card;
    if (!card || !this.data.shareReady) return {
      title: '从典籍里挑一个好名字｜好名书中来', path: '/pages/discover/index',
      imageUrl: '/assets/share-cover.jpg'
    };
    const name = card.item.displayName || card.item.name;
    const book = card.item.book;
    return {title: book ? `「${name}」出自《${book}》，你觉得怎么样？` : `「${name}」，你觉得怎么样？`,
      path: sharePath(this.data.shareToken, card), imageUrl: this.data.shareImageUrl || '/assets/share-cover.jpg'};
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
      if (this.data.isShared) await call('shares.save', {token: this.data.shareToken});
      else await call('favorites.add', {material_id: this.data.card.id});
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
