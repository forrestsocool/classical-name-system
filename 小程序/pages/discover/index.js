const {call, requestId, storageKey, preferenceKey} = require('../../utils/api');
const {normalizeCard, normalizeCards} = require('../../utils/view');
const {dragState, releaseDirection} = require('../../utils/swipe');

const GENDERS = ['any', 'male', 'female'];
const GENDER_LABELS = ['不限', '男孩', '女孩'];
const GENDER_ICONS = ['users', 'male', 'female'];

function emptyPool() { return {cards: [], pending: null, retryAt: 0, loading: false, error: ''}; }
function poolKey(length, gender) { return `${gender}:${length}`; }
function newPools() {
  const pools = {};
  for (const gender of GENDERS) for (const length of [1, 2]) pools[poolKey(length, gender)] = emptyPool();
  return pools;
}
function cleanSurname(value) { return String(value || '').replace(/[^\u3400-\u9fff]/g, '').slice(0, 2); }
const restStyle = 'transform:translate3d(0px,0px,0) rotate(0deg);transition:none;';

Page({
  data: {
    statusBarHeight: 0, navHeight: 44, surname: '', gender: 'any', genderIndex: 0,
    genderLabel: '不限', genderIcon: 'users', genderLabels: GENDER_LABELS,
    nameLength: 2, current: null, next: null, ready: false, loading: true,
    animating: false, saving: false, error: '', cooldown: 0,
    cardStyle: restStyle, stackStyle: '', likeOpacity: 0, skipOpacity: 0
  },

  async onLoad() {
    this.pools = newPools();
    this.pulls = {};
    this.visible = true;
    this.updateLayout();
    await this.connect();
  },
  updateLayout() {
    const info = wx.getWindowInfo ? wx.getWindowInfo() : wx.getSystemInfoSync();
    const statusBarHeight = info.statusBarHeight || 0;
    const capsule = wx.getMenuButtonBoundingClientRect && wx.getMenuButtonBoundingClientRect();
    this.windowWidth = info.windowWidth || 375;
    // Align the compact wordmark with the native capsule on each device.
    const navHeight = capsule && capsule.bottom > statusBarHeight
      ? capsule.bottom - statusBarHeight + 8 : 44;
    this.setData({statusBarHeight, navHeight});
  },
  onResize() { this.updateLayout(); },
  onShow() {
    this.visible = true;
    if (this.getTabBar && this.getTabBar()) this.getTabBar().setData({selected: 0});
    this.consumePendingFavorite();
    this.startTicker();
  },
  onHide() {
    this.visible = false;
    clearInterval(this.ticker);
    if (!this.data.animating) this.resetDrag();
  },
  onUnload() { this.closed = true; clearInterval(this.ticker); },

  activeKey(length = this.data.nameLength, gender = this.data.gender) { return poolKey(length, gender); },
  async connect() {
    if (this.connecting) return;
    this.connecting = true;
    this.setData({loading: true, error: ''});
    try {
      this.user = await getApp().session();
      const preferences = wx.getStorageSync(preferenceKey(this.user)) || {};
      const surname = cleanSurname(preferences.surname);
      const gender = GENDERS.includes(preferences.gender) ? preferences.gender : 'any';
      const genderIndex = GENDERS.indexOf(gender);
      getApp().namePreferences = {surname, gender};
      this.setData({surname, gender, genderIndex, genderLabel: GENDER_LABELS[genderIndex], genderIcon: GENDER_ICONS[genderIndex]});

      const saved = wx.getStorageSync(storageKey(this.user));
      if (saved && saved.version === 3) {
        for (const key of Object.keys(this.pools)) {
          const pool = saved.pools && saved.pools[key];
          if (!pool) continue;
          const length = Number(key.slice(-1));
          const poolGender = key.split(':')[0];
          this.pools[key].cards = normalizeCards(pool.cards).filter(card => card && card.id && card.item.name.length === length);
          this.pools[key].pending = pool.pending && pool.pending.name_length === length && pool.pending.gender === poolGender ? pool.pending : null;
          this.pools[key].retryAt = Math.min(Number(pool.retryAt) || 0, Date.now() + 60000);
        }
        if (saved.selectedLength === 1 || saved.selectedLength === 2) this.setData({nameLength: saved.selectedLength});
      }
      if (this.closed) return;
      this.setData({ready: true});
      this.render();
      this.startTicker();
      await this.refill(this.data.nameLength, this.data.gender);
      this.consumePendingFavorite(true);
    } catch (error) {
      if (!this.closed) this.setData({loading: false, error: error.message || '暂时没有连接上，请重试'});
    } finally { this.connecting = false; }
  },

  startTicker() {
    clearInterval(this.ticker);
    this.ticker = setInterval(() => {
      if (!this.visible || !this.data.ready || this.closed) return;
      const pool = this.pools[this.activeKey()];
      const cooldown = Math.max(0, Math.ceil((pool.retryAt - Date.now()) / 1000));
      if (cooldown !== this.data.cooldown) this.setData({cooldown});
      if (!cooldown && !pool.cards.length && !pool.loading && !pool.error) this.refill();
    }, 1000);
  },
  persistPreferences() {
    if (!this.user) return;
    const preferences = {surname: this.data.surname, gender: this.data.gender};
    getApp().namePreferences = preferences;
    wx.setStorageSync(preferenceKey(this.user), preferences);
  },
  persist() {
    if (!this.user) return;
    const pools = {};
    for (const key of Object.keys(this.pools)) {
      const pool = this.pools[key];
      pools[key] = {cards: pool.cards, pending: pool.pending, retryAt: pool.retryAt};
    }
    wx.setStorageSync(storageKey(this.user), {version: 3, selectedLength: this.data.nameLength, pools});
  },
  render() {
    if (this.closed) return;
    const pool = this.pools[this.activeKey()];
    this.setData({
      current: normalizeCard(pool.cards[0] || null, this.data.surname),
      next: normalizeCard(pool.cards[1] || null, this.data.surname),
      loading: pool.loading, error: pool.error,
      cooldown: Math.max(0, Math.ceil((pool.retryAt - Date.now()) / 1000))
    });
  },

  refill(length = this.data.nameLength, gender = this.data.gender, force = false) {
    if (!this.user || this.closed) return Promise.resolve();
    const key = this.activeKey(length, gender);
    if (this.pulls[key]) return this.pulls[key];
    const pool = this.pools[key];
    if (!force && (pool.cards.length > 3 || pool.retryAt > Date.now() || pool.error)) return Promise.resolve();
    pool.loading = true;
    pool.error = '';
    if (!pool.pending) pool.pending = {name_length: length, gender, count: 8, request_id: requestId()};
    this.persist();
    if (key === this.activeKey()) this.render();
    const request = pool.pending;
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
        delete this.pulls[key];
        this.persist();
        if (key === this.activeKey() && !this.data.animating) {
          this.render();
          this.consumePendingFavorite(true);
        }
      }
    });
    this.pulls[key] = pending;
    return pending;
  },
  async retry() {
    if (!this.user) return this.connect();
    return this.refill(this.data.nameLength, this.data.gender, true);
  },
  onSurnameInput(event) {
    const surname = cleanSurname(event.detail.value);
    this.setData({surname});
    this.persistPreferences();
    this.render();
    return surname;
  },
  async genderChange(event) {
    const genderIndex = Number(event.detail.value);
    if (!GENDERS[genderIndex] || GENDERS[genderIndex] === this.data.gender || this.data.animating) return;
    this.resetDrag();
    this.setData({gender: GENDERS[genderIndex], genderIndex, genderLabel: GENDER_LABELS[genderIndex], genderIcon: GENDER_ICONS[genderIndex]});
    this.persistPreferences();
    this.render();
    await this.refill();
  },
  async lengthChange(event) {
    const length = Number(event.currentTarget.dataset.length);
    if (![1, 2].includes(length) || length === this.data.nameLength || this.data.animating) return;
    this.resetDrag();
    this.setData({nameLength: length});
    this.render();
    this.persist();
    await this.refill();
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
    this.setData(dragState(dx, dy, this.windowWidth));
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
    return this.dismiss(direction, direction > 0);
  },
  skip() { return this.dismiss(-1, false); },
  favorite() { return this.dismiss(1, true); },
  next() { return this.dismiss(1, false); },
  async dismiss(direction, shouldFavorite) {
    if (this.data.animating || !this.data.current) return;
    const key = this.activeKey(), pool = this.pools[key], card = pool.cards[0];
    this.touch = null;
    const outgoingStyle = `transform:translate3d(${direction * this.windowWidth * 1.35}px,-24px,0) rotate(${direction * 23}deg);transition:transform 280ms cubic-bezier(.2,.65,.25,1);`;
    this.setData({animating: true, saving: shouldFavorite, error: '',
      cardStyle: shouldFavorite ? restStyle : outgoingStyle,
      stackStyle: shouldFavorite ? 'opacity:0;' : 'transform:translateY(0) scale(1);opacity:1;',
      likeOpacity: 0, skipOpacity: direction < 0 ? 1 : 0});
    const save = shouldFavorite ? call('favorites.add', {material_id: card.id}).then(() => null, error => error) : Promise.resolve(null);
    if (!shouldFavorite) await new Promise(resolve => setTimeout(resolve, 290));
    let error = await save;
    if (error) {
      this.resetDrag(true);
      if (!this.closed) this.setData({error: '收藏没有保存成功，名字已留在原位，请重试。', saving: false});
      await new Promise(resolve => setTimeout(resolve, 270));
    } else {
      if (shouldFavorite) {
        this.setData({cardStyle: outgoingStyle, stackStyle: 'opacity:0;'});
        await new Promise(resolve => setTimeout(resolve, 290));
      }
      if (pool.cards[0] && pool.cards[0].id === card.id) pool.cards.shift();
      this.persist();
      this.resetDrag();
      this.render();
      if (shouldFavorite && this.visible && !this.closed) wx.vibrateShort({type: 'light'});
    }
    if (!this.closed) this.setData({animating: false, saving: false});
    if (!error) this.refill();
  },
  consumePendingFavorite(allowMiss = false) {
    const pending = getApp().pendingFavorite;
    if (!pending) return;
    const removed = this.completeFavoriteFromDetail(pending.id);
    if (removed || allowMiss) getApp().pendingFavorite = null;
  },
  completeFavoriteFromDetail(id) {
    if (!this.pools || this.closed) return;
    let target = null;
    for (const key of Object.keys(this.pools)) {
      const pool = this.pools[key];
      const index = pool.cards.findIndex(card => String(card.id) === String(id));
      if (index >= 0) { target = {key, pool, index}; break; }
    }
    if (!target) return false;
    target.pool.cards.splice(target.index, 1);
    this.persist();
    if (target.key === this.activeKey() && target.index === 0) {
      this.resetDrag();
      this.render();
      this.refill();
    }
    return true;
  },
  detail() {
    if (!this.data.current || this.data.animating || Date.now() < (this.ignoreTapUntil || 0)) return;
    getApp().selectedCard = this.data.current;
    getApp().selectedSurname = this.data.surname;
    wx.navigateTo({url: '/pages/detail/index'});
  }
});
