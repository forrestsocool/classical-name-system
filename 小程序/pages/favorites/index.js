const {call, preferenceKey} = require('../../utils/api');
const {normalizeCards} = require('../../utils/view');
const {shareName, prepareShare} = require('../../utils/share');

Page({
  data: {
    cards: [], nextCursor: null, loading: false, refreshing: false,
    removingId: null, error: '', initialized: false,
    openId: null, slideX: 0, dragging: false
  },
  onLoad() {
    const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    this.actionWidth = (info.windowWidth || 375) * 178 / 750;
  },
  onShow() {
    if (this.getTabBar && this.getTabBar()) this.getTabBar().setData({selected: 1});
    return this.reload();
  },
  onHide() { this.closeRow(); },
  onShareAppMessage(event = {}) {
    const id = event.target && event.target.dataset.id;
    const card = event.from === 'button'
      ? this.data.cards.find(item => String(item.id) === String(id)) : null;
    return shareName(card);
  },
  onUnload() { this.closed = true; this.touch = null; },
  async onPullDownRefresh() {
    try { await this.reload(); }
    finally { wx.stopPullDownRefresh(); }
  },
  onReachBottom() {
    if (this.data.nextCursor && !this.refreshTask && !this.data.error) return this.fetchPage();
  },

  reload() {
    if (this.closed) return Promise.resolve();
    if (this.refreshTask) return this.refreshTask;
    this.closeRow();
    this.setData({refreshing: true, error: ''});
    // Finish in-flight work before replacing the list, so a deleted card cannot reappear.
    const task = Promise.resolve().then(async () => {
      if (this.listTask) await this.listTask;
      if (this.removeTask) await this.removeTask;
      if (!this.closed) await this.fetchPage(true);
    }).finally(() => {
      this.refreshTask = null;
      if (!this.closed) this.setData({refreshing: false});
    });
    this.refreshTask = task;
    return task;
  },
  fetchPage(reset = false) {
    if (this.closed || this.removeTask || (!reset && this.refreshTask)) return Promise.resolve();
    if (this.listTask) return this.listTask;
    this.setData({loading: true, error: ''});
    const cursor = reset ? null : this.data.nextCursor;
    const task = Promise.resolve().then(async () => {
      try {
        const user = await getApp().session();
        const preferences = wx.getStorageSync(preferenceKey(user)) || getApp().namePreferences || {};
        const surname = preferences.surname || '';
        const response = await call('favorites.list', cursor ? {before_id: cursor} : {});
        if (this.closed) return;
        this.surname = surname;
        const cards = reset ? [] : this.data.cards.slice();
        const ids = new Set(cards.map(card => card.id));
        for (const card of normalizeCards(response.cards, surname)) {
          if (!ids.has(card.id)) { cards.push(card); ids.add(card.id); }
        }
        this.setData({cards, nextCursor: response.next_cursor || null, initialized: true});
        if (prepareShare) this.warmShares(cards);
      } catch (error) {
        if (!this.closed) this.setData({error: error.message || '收藏暂时没有送达，请重试'});
      } finally {
        this.listTask = null;
        if (!this.closed) this.setData({loading: false});
      }
    });
    this.listTask = task;
    return task;
  },
  retry() { return this.reload(); },
  async warmShares(cards) {
    for (let offset = 0; offset < cards.length && !this.closed; offset += 2) {
      await Promise.all(cards.slice(offset, offset + 2).map(card =>
        this.prepareFavoriteShare({currentTarget: {dataset: {id: card.id}}}, true)));
    }
  },
  async prepareFavoriteShare(event, silent = false) {
    const id = String(event.currentTarget.dataset.id);
    const card = this.data.cards.find(item => String(item.id) === id);
    if (!card || card.shareReady || card.sharePreparing || this.data.removingId) return;
    const update = patch => {
      if (!this.closed) this.setData({cards: this.data.cards.map(item =>
        String(item.id) === id ? {...item, ...patch} : item)});
    };
    update({sharePreparing: true});
    try {
      await prepareShare(card);
      update({shareReady: true});
      if (!silent) wx.showToast({title: '已准备好，请再点分享', icon: 'none'});
    } catch (error) {
      if (!silent) wx.showToast({title: error.message || '分享准备失败，请重试', icon: 'none'});
    } finally {
      update({sharePreparing: false});
    }
  },
  goDiscover() { wx.switchTab({url: '/pages/discover/index'}); },
  detail(event) {
    if (this.data.removingId || Date.now() < (this.ignoreTapUntil || 0)) return;
    const card = this.data.cards.find(item => item.id === Number(event.currentTarget.dataset.id));
    if (!card) return;
    this.closeRow();
    getApp().selectedCard = card;
    getApp().selectedSurname = this.surname || '';
    wx.navigateTo({url: '/pages/detail/index'});
  },

  closeOnTap() {
    if (Date.now() >= (this.ignoreTapUntil || 0)) this.closeRow();
  },
  closeRow() {
    this.touch = null;
    if (!this.closed) this.setData({openId: null, slideX: 0, dragging: false});
  },
  touchStart(event) {
    if (this.data.removingId || this.data.refreshing || event.touches.length !== 1) return;
    const id = Number(event.currentTarget.dataset.id);
    if (!this.data.cards.some(card => card.id === id)) return;
    if (this.data.openId !== id) this.closeRow();
    const point = event.touches[0];
    this.touch = {
      id, x: point.clientX, y: point.clientY, time: event.timeStamp || Date.now(),
      base: this.data.openId === id ? this.data.slideX : 0, axis: null
    };
  },
  touchMove(event) {
    if (!this.touch) return;
    if (event.touches.length !== 1) return this.closeRow();
    const point = event.touches[0], start = this.touch;
    const dx = point.clientX - start.x, dy = point.clientY - start.y;
    if (!start.axis && Math.max(Math.abs(dx), Math.abs(dy)) > 8) {
      start.axis = Math.abs(dx) > Math.abs(dy) * 1.15 ? 'x' : 'y';
    }
    // Keep vertical gestures native for page scrolling and pull-to-refresh.
    if (start.axis !== 'x') return;
    this.ignoreTapUntil = Date.now() + 350;
    this.setData({
      openId: start.id, dragging: true,
      slideX: Math.round(Math.max(-this.actionWidth, Math.min(0, start.base + dx)))
    });
  },
  touchEnd(event) {
    const start = this.touch;
    this.touch = null;
    if (!start || start.axis !== 'x') return;
    const point = event.changedTouches && event.changedTouches[0];
    if (!point) return this.closeRow();
    const dx = point.clientX - start.x;
    const elapsed = (event.timeStamp || Date.now()) - start.time;
    const fast = elapsed > 0 && elapsed < 350 && Math.abs(dx) > 28 && Math.abs(dx) / elapsed > .4;
    const open = fast ? dx < 0 : start.base + dx <= -this.actionWidth * .45;
    this.ignoreTapUntil = Date.now() + 350;
    this.setData({openId: open ? start.id : null, slideX: open ? -this.actionWidth : 0, dragging: false});
  },
  touchCancel() { this.closeRow(); },

  async remove(event) {
    const id = Number(event.currentTarget.dataset.id);
    if (this.closed || this.listTask || this.refreshTask || this.removeTask || this.data.openId !== id) return;
    if (!this.data.cards.some(card => card.id === id)) return;
    this.setData({removingId: id, error: ''});
    const task = Promise.resolve().then(async () => {
      try {
        await call('favorites.remove', {material_id: id});
        if (this.closed) return;
        this.setData({cards: this.data.cards.filter(card => card.id !== id)});
        this.closeRow();
        wx.showToast({title: '已取消收藏', icon: 'none'});
      } catch (error) {
        if (!this.closed) this.setData({error: '取消收藏未成功，名字已保留，请重试。'});
      } finally {
        this.removeTask = null;
        if (!this.closed) this.setData({removingId: null});
      }
    });
    this.removeTask = task;
    await task;
    if (!this.closed && !this.data.cards.length && this.data.nextCursor && !this.refreshTask) await this.fetchPage();
  }
});
