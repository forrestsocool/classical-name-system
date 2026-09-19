const {call, requestId, storageKey} = require('../../utils/api');
const {normalizeCards} = require('../../utils/view');
const {dragState, releaseDirection} = require('../../utils/swipe');

function emptyPool() { return {cards: [], pending: null, retryAt: 0, loading: false, error: ''}; }
const restStyle = 'transform:translate3d(0px,0px,0) rotate(0deg);transition:none;';

Page({
  data: {
    nameLength: 2, current: null, next: null, ready: false, loading: true,
    animating: false, saving: false, error: '', cooldown: 0,
    cardStyle: restStyle, stackStyle: '', likeOpacity: 0, skipOpacity: 0
  },

  async onLoad() {
    this.pools = {1: emptyPool(), 2: emptyPool()};
    this.pulls = {};
    this.visible = true;
    this.windowWidth = (wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync()).windowWidth || 375;
    await this.connect();
  },
  onShow() { this.visible = true; this.startTicker(); },
  onHide() {
    this.visible = false;
    clearInterval(this.ticker);
    if (!this.data.animating) this.resetDrag();
  },
  onUnload() { this.closed = true; clearInterval(this.ticker); },

  async connect() {
    if (this.connecting) return;
    this.connecting = true;
    this.setData({loading: true, error: ''});
    try {
      this.user = await getApp().session();
      const saved = wx.getStorageSync(storageKey(this.user));
      if (saved && saved.version === 2) {
        for (const length of [1, 2]) {
          const pool = saved.pools && saved.pools[length];
          if (!pool) continue;
          this.pools[length].cards = normalizeCards(pool.cards).filter(card => card && card.id && card.item.name.length === length);
          this.pools[length].pending = pool.pending && pool.pending.name_length === length ? pool.pending : null;
          this.pools[length].retryAt = Math.min(Number(pool.retryAt) || 0, Date.now() + 60000);
        }
        if (saved.selectedLength === 1 || saved.selectedLength === 2) this.setData({nameLength: saved.selectedLength});
      }
      if (this.closed) return;
      this.setData({ready: true});
      this.render();
      this.startTicker();
      await this.refill(this.data.nameLength);
    } catch (error) {
      if (!this.closed) this.setData({loading: false, error: error.message || '暂时没有连接上，请重试'});
    } finally { this.connecting = false; }
  },

  startTicker() {
    clearInterval(this.ticker);
    this.ticker = setInterval(() => {
      if (!this.visible || !this.data.ready || this.closed) return;
      const pool = this.pools[this.data.nameLength];
      const cooldown = Math.max(0, Math.ceil((pool.retryAt - Date.now()) / 1000));
      if (cooldown !== this.data.cooldown) this.setData({cooldown});
      if (!cooldown && !pool.cards.length && !pool.loading && !pool.error) this.refill(this.data.nameLength);
    }, 1000);
  },
  persist() {
    if (!this.user) return;
    const pools = {};
    for (const length of [1, 2]) {
      const pool = this.pools[length];
      pools[length] = {cards: pool.cards, pending: pool.pending, retryAt: pool.retryAt};
    }
    wx.setStorageSync(storageKey(this.user), {version: 2, selectedLength: this.data.nameLength, pools});
  },
  render() {
    if (this.closed) return;
    const pool = this.pools[this.data.nameLength];
    this.setData({
      current: pool.cards[0] || null, next: pool.cards[1] || null,
      loading: pool.loading, error: pool.error,
      cooldown: Math.max(0, Math.ceil((pool.retryAt - Date.now()) / 1000))
    });
  },

  refill(length, force = false) {
    if (!this.user || this.closed) return Promise.resolve();
    if (this.pulls[length]) return this.pulls[length];
    const pool = this.pools[length];
    if (!force && (pool.cards.length > 3 || pool.retryAt > Date.now() || pool.error)) return Promise.resolve();
    pool.loading = true;
    pool.error = '';
    if (!pool.pending) pool.pending = {name_length: length, count: 8, request_id: requestId()};
    this.persist();
    if (length === this.data.nameLength) this.render();
    const request = pool.pending;
    // Register the in-flight promise before a synchronously failing transport can finish.
    const pending = Promise.resolve().then(async () => {
      try {
        const result = await call('feed.pull', request);
        const received = normalizeCards(result.cards);
        const ids = new Set(pool.cards.map(card => card.id));
        for (const card of received) {
          if (!ids.has(card.id)) { pool.cards.push(card); ids.add(card.id); }
        }
        pool.pending = null;
        pool.retryAt = received.length ? 0 : Date.now() + Math.max(5, Math.min(60, result.retry_after || 15)) * 1000;
      } catch (error) {
        if (error.status === 409 || error.status === 422) pool.pending = null;
        pool.error = error.message || '新名字暂时没送到，点一下重试';
      } finally {
        pool.loading = false;
        delete this.pulls[length];
        this.persist();
        if (length === this.data.nameLength && !this.data.animating) this.render();
      }
    });
    this.pulls[length] = pending;
    return pending;
  },
  async retry() {
    if (!this.user) return this.connect();
    return this.refill(this.data.nameLength, true);
  },
  async lengthChange(event) {
    const length = Number(event.currentTarget.dataset.length);
    if (![1, 2].includes(length) || length === this.data.nameLength || this.data.animating) return;
    this.resetDrag();
    this.setData({nameLength: length});
    this.render();
    this.persist();
    await this.refill(length);
  },

  resetDrag(animated = false) {
    this.touch = null;
    if (this.closed) return;
    this.setData({cardStyle: animated ? restStyle.replace('none', 'transform 260ms cubic-bezier(.2,.8,.2,1)') : restStyle,
      stackStyle: '', likeOpacity: 0, skipOpacity: 0});
  },
  touchStart(event) {
    if (this.data.animating || !this.data.current || event.touches.length !== 1) return;
    const point = event.touches[0];
    this.touch = {x: point.clientX, y: point.clientY, time: event.timeStamp || Date.now(), axis: null, lastPaint: 0};
  },
  touchMove(event) {
    if (!this.touch || this.data.animating) return;
    if (event.touches.length !== 1) return this.resetDrag(true);
    const point = event.touches[0];
    const dx = point.clientX - this.touch.x, dy = point.clientY - this.touch.y;
    if (!this.touch.axis && Math.max(Math.abs(dx), Math.abs(dy)) > 8) this.touch.axis = Math.abs(dx) > Math.abs(dy) * 1.1 ? 'x' : 'y';
    if (this.touch.axis !== 'x') return;
    this.ignoreTapUntil = Date.now() + 350;
    const now = Date.now();
    if (now - this.touch.lastPaint < 16) return;
    this.touch.lastPaint = now;
    const state = dragState(dx, dy, this.windowWidth);
    this.setData(state);
  },
  touchCancel() { if (!this.data.animating) this.resetDrag(true); },
  touchEnd(event) {
    if (!this.touch || this.data.animating) return;
    const start = this.touch, point = event.changedTouches[0];
    this.touch = null;
    if (!point) return this.resetDrag(true);
    const dx = point.clientX - start.x, dy = point.clientY - start.y;
    const elapsed = (event.timeStamp || Date.now()) - start.time;
    const direction = start.axis === 'y' ? 0 : releaseDirection(dx, dy, elapsed, this.windowWidth);
    if (!direction) return this.resetDrag(true);
    this.ignoreTapUntil = Date.now() + 350;
    return this.swipe(direction);
  },
  skip() { return this.swipe(-1); },
  favorite() { return this.swipe(1); },
  async swipe(direction) {
    if (this.data.animating || !this.data.current) return;
    const length = this.data.nameLength, pool = this.pools[length], card = pool.cards[0];
    this.touch = null;
    this.setData({animating: true, saving: direction > 0, error: '',
      cardStyle: `transform:translate3d(${direction * this.windowWidth * 1.35}px,-24px,0) rotate(${direction * 23}deg);transition:transform 280ms cubic-bezier(.2,.65,.25,1);`,
      stackStyle: 'transform:translateY(0) scale(1);opacity:1;',
      likeOpacity: direction > 0 ? 1 : 0, skipOpacity: direction < 0 ? 1 : 0});
    // Capture a rejection immediately while the outgoing card is animating.
    const save = direction > 0 ? call('favorites.add', {material_id: card.id}).then(() => null, error => error) : Promise.resolve(null);
    await new Promise(resolve => setTimeout(resolve, 290));
    const error = await save;
    if (error) {
      this.resetDrag(true);
      if (!this.closed) this.setData({error: '收藏没有保存成功，名字已留在原位，请重试。', saving: false});
      await new Promise(resolve => setTimeout(resolve, 270));
    } else {
      if (pool.cards[0] && pool.cards[0].id === card.id) pool.cards.shift();
      this.persist();
      this.resetDrag();
      this.render();
      if (direction > 0 && this.visible && !this.closed) wx.vibrateShort({type: 'light'});
    }
    if (!this.closed) this.setData({animating: false, saving: false});
    if (!error) this.refill(length);
  },
  detail() {
    if (!this.data.current || this.data.animating || Date.now() < (this.ignoreTapUntil || 0)) return;
    getApp().selectedCard = this.data.current;
    wx.navigateTo({url: '/pages/detail/index'});
  }
});
