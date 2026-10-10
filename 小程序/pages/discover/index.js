const {call, requestId, storageKey, preferenceKey} = require('../../utils/api');
const {normalizeCard, normalizeCards} = require('../../utils/view');
const {shareName, prepareShare} = require('../../utils/share');
const {dragState, releaseDirection} = require('../../utils/swipe');
const {normalizeFilters, filterKey, filterError, matchesCard} = require('../../utils/filters');
const {warmNameFont} = require('../../utils/nameFont');

const GENDERS = ['any', 'male', 'female'];
const GENDER_LABELS = ['不限', '男孩', '女孩'];
const GENDER_ICONS = ['users', 'male', 'female'];

function emptyRequest() { return {pending: null, retryAt: 0, loading: false, error: ''}; }
function emptyPool() { return {cards: [], requests: {}}; }
function poolKey(length, gender) { return `${gender}:${length}`; }
function newPools() {
  const pools = {};
  for (const gender of GENDERS) for (const length of [1, 2]) pools[poolKey(length, gender)] = emptyPool();
  return pools;
}
// Keep the native input's raw maxlength generous enough for pinyin composition;
// enforce the semantic surname limit only after the IME commits Chinese text.
function cleanSurname(value) { return String(value || '').replace(/[^\u3400-\u9fff]/g, '').slice(0, 4); }
const restStyle = 'transform:translate3d(0px,0px,0) rotate(0deg);transition:none;';

Page({
  data: {
    statusBarHeight: 0, navHeight: 44, surname: '', gender: 'any', genderIndex: 0,
    genderLabel: '不限', genderIcon: 'users', genderLabels: GENDER_LABELS,
    nameLength: 2, current: null, next: null, ready: false, loading: true,
    animating: false, saving: false, error: '', cooldown: 0, hasFilters: false, filterMessage: '',
    cardStyle: restStyle, stackStyle: '', likeOpacity: 0, skipOpacity: 0
  },

  async onLoad() {
    this.pools = newPools();
    this.analysisCache = Object.create(null);
    this.analysisRequests = new Set();
    this.filters = normalizeFilters();
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
    if (this.data.ready) this.syncFilters();
    this.consumePendingFavorite();
    this.startTicker();
  },
  onHide() {
    this.visible = false;
    clearInterval(this.ticker);
    if (!this.data.animating) this.resetDrag();
  },
  onUnload() { this.closed = true; clearInterval(this.ticker); clearTimeout(this.surnameTimer); },

  activeKey(length = this.data.nameLength, gender = this.data.gender) { return poolKey(length, gender); },
  requestState(pool, filters = this.filters) {
    const key = filterKey(filters);
    if (!pool.requests[key]) pool.requests[key] = emptyRequest();
    return pool.requests[key];
  },
  matchingCards(pool) { return pool.cards.filter(card => matchesCard(card, this.filters)); },
  syncFilters() {
    const next = normalizeFilters(wx.getStorageSync(preferenceKey(this.user)) || {});
    if (filterKey(next) === filterKey(this.filters)) return;
    this.filters = next;
    this.resetDrag();
    this.render();
    return this.refill();
  },
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
      this.filters = normalizeFilters(preferences);
      getApp().namePreferences = {...preferences, surname, gender, ...this.filters};
      this.setData({surname, gender, genderIndex, genderLabel: GENDER_LABELS[genderIndex], genderIcon: GENDER_ICONS[genderIndex]});

      const saved = wx.getStorageSync(storageKey(this.user));
      if (saved && (saved.version === 3 || saved.version === 4)) {
        for (const key of Object.keys(this.pools)) {
          const pool = saved.pools && saved.pools[key];
          if (!pool) continue;
          const length = Number(key.slice(-1));
          const poolGender = key.split(':')[0];
          this.pools[key].cards = normalizeCards(pool.cards).filter(card => card && card.id && card.item.name.length === length);
          const requests = saved.version === 3 ? {[filterKey(pool.pending || {})]: pool} : (pool.requests || {});
          for (const signature of Object.keys(requests)) {
            const state = requests[signature];
            const pending = state.pending;
            this.pools[key].requests[signature] = {...emptyRequest(),
              pending: pending && pending.name_length === length && pending.gender === poolGender && filterKey(pending) === signature ? pending : null,
              retryAt: Math.min(Number(state.retryAt) || 0, Date.now() + 60000)};
          }
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
      const state = this.requestState(pool);
      const cooldown = Math.max(0, Math.ceil((state.retryAt - Date.now()) / 1000));
      if (cooldown !== this.data.cooldown) this.setData({cooldown});
      if (!cooldown && !this.matchingCards(pool).length && !state.loading && !state.error) this.refill();
    }, 1000);
  },
  persistPreferences() {
    if (!this.user) return;
    const preferences = {...(wx.getStorageSync(preferenceKey(this.user)) || {}), surname: this.data.surname, gender: this.data.gender};
    getApp().namePreferences = preferences;
    wx.setStorageSync(preferenceKey(this.user), preferences);
  },
  persist() {
    if (!this.user) return;
    const pools = {};
    for (const key of Object.keys(this.pools)) {
      const pool = this.pools[key];
      const requests = {};
      for (const signature of Object.keys(pool.requests)) {
        const state = pool.requests[signature];
        // Successful requests need no retained receipt; uncertain failures must replay.
        if (state.pending || state.retryAt > Date.now()) requests[signature] = {pending: state.pending, retryAt: state.retryAt};
      }
      pools[key] = {cards: pool.cards, requests};
    }
    wx.setStorageSync(storageKey(this.user), {version: 4, selectedLength: this.data.nameLength, pools});
  },
  render() {
    if (this.closed) return;
    const pool = this.pools[this.activeKey()];
    const state = this.requestState(pool);
    const cards = this.matchingCards(pool);
    const surname = this.data.surname;
    const visible = cards.slice(0, 2).map(card => {
      const analysis = this.analysisCache[`${card.id}|${surname}`];
      return normalizeCard(analysis ? {...card, item: {...card.item, wuxing: analysis}} : card, surname);
    });
    const filterMessage = filterError(this.filters) || (this.filters.required.length > this.data.nameLength ? '必含字有两个，请切换双字名或调整用字' : '');
    this.setData({
      current: visible[0] || null,
      next: visible[1] || null,
      loading: state.loading, error: state.error, filterMessage,
      hasFilters: !!(this.filters.required || this.filters.excluded || this.filters.excluded_sources.length),
      cooldown: Math.max(0, Math.ceil((state.retryAt - Date.now()) / 1000))
    });
    if (visible[0] && warmNameFont) warmNameFont(this);
    if (prepareShare && visible[0]) {
      if (wx.showShareMenu) wx.showShareMenu({menus: ['shareAppMessage']});
      visible.forEach(card => prepareShare(card, this).catch(() => {}));
    }
    const missing = visible.filter(card => card.item.wuxing.version !== 'server-v1' &&
      !this.analysisRequests.has(`${card.id}|${surname}`));
    if (missing.length && this.user && !this.analysisSuspended) this.refreshAnalysis(missing, surname);
  },

  async refreshAnalysis(cards, surname) {
    const ids = cards.map(card => card.id);
    const keys = ids.map(id => `${id}|${surname}`);
    keys.forEach(key => this.analysisRequests.add(key));
    try {
      const response = await call('names.analyze', {material_ids: ids, surname});
      const results = Array.isArray(response.results) ? response.results : [];
      for (const card of cards) {
        const found = results.find(item => String(item.id) === String(card.id));
        if (found && found.wuxing && found.wuxing.analyzed_name === card.item.displayName) {
          this.analysisCache[`${card.id}|${surname}`] = found.wuxing;
        } else {
          this.analysisCache[`${card.id}|${surname}`] = {...card.item.wuxing, version: 'server-v1',
            status: '五行资料暂不可用', explanation: '五行资料暂时无法读取，请稍后重新打开小程序。'};
        }
      }
    } catch (error) {
      for (const card of cards) this.analysisCache[`${card.id}|${surname}`] = {
        ...card.item.wuxing, version: 'server-v1', status: '五行资料暂不可用',
        explanation: '五行资料暂时无法读取，请稍后重新打开小程序。'};
    } finally {
      keys.forEach(key => this.analysisRequests.delete(key));
      if (!this.closed) this.render();
    }
  },

  refill(length = this.data.nameLength, gender = this.data.gender, force = false) {
    if (!this.user || this.closed) return Promise.resolve();
    if (filterError(this.filters) || this.filters.required.length > length) return Promise.resolve();
    const key = this.activeKey(length, gender);
    const signature = filterKey(this.filters);
    const pullKey = key + '|' + signature;
    if (this.pulls[pullKey]) return this.pulls[pullKey];
    const pool = this.pools[key];
    const state = this.requestState(pool);
    if (!force && (this.matchingCards(pool).length > 3 || state.retryAt > Date.now() || state.error)) return Promise.resolve();
    state.loading = true;
    state.error = '';
    if (!state.pending) {
      state.pending = {name_length: length, gender, count: 8, request_id: requestId()};
      for (const field of ['required', 'excluded', 'excluded_sources']) {
        if (this.filters[field].length) state.pending[field] = this.filters[field];
      }
    }
    this.persist();
    if (key === this.activeKey()) this.render();
    const request = state.pending;
    const pending = Promise.resolve().then(async () => {
      try {
        const result = await call('feed.pull', request);
        const received = normalizeCards(result.cards);
        const ids = new Set(pool.cards.map(card => card.id));
        for (const card of received) {
          if (!ids.has(card.id)) { pool.cards.push(card); ids.add(card.id); }
        }
        state.pending = null;
        state.retryAt = received.length ? 0 : Date.now() + Math.max(5, Math.min(60, result.retry_after || 15)) * 1000;
      } catch (error) {
        if (error.status === 409 || error.status === 422) state.pending = null;
        state.error = error.message || '新名字暂时没送到，点一下重试';
      } finally {
        state.loading = false;
        delete this.pulls[pullKey];
        this.persist();
        if (key === this.activeKey() && !this.data.animating) {
          this.render();
          this.consumePendingFavorite(true);
        }
      }
    });
    this.pulls[pullKey] = pending;
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
    this.analysisSuspended = true;
    this.render();
    clearTimeout(this.surnameTimer);
    this.surnameTimer = setTimeout(() => {
      this.analysisSuspended = false;
      if (!this.closed) this.render();
    }, 400);
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
    const key = this.activeKey(), pool = this.pools[key], card = this.data.current;
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
      const index = pool.cards.findIndex(item => item.id === card.id);
      if (index >= 0) pool.cards.splice(index, 1);
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
    if (target.key === this.activeKey()) {
      this.resetDrag();
      this.render();
      this.refill();
    }
    return true;
  },
  editFilters() { wx.switchTab({url: '/pages/profile/index'}); },
  detail() {
    if (!this.data.current || this.data.animating || Date.now() < (this.ignoreTapUntil || 0)) return;
    getApp().selectedCard = this.data.current;
    getApp().selectedSurname = this.data.surname;
    wx.navigateTo({url: '/pages/detail/index'});
  },
  onShareAppMessage() {
    return shareName(this.data.current, this);
  }
});
