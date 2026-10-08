const {call, preferenceKey} = require('../../utils/api');
const {cleanCharacters, normalizeFilters, filterError} = require('../../utils/filters');
const build = require('../../utils/build');
const {readCache, writeCache} = require('../../utils/pageCache');

Page({
  data: {
    required: '', excluded: '', sources: [], sourceCount: 0, enabledCount: 0, sourceLoading: true,
    sourceError: '', inputError: '', savedNotice: '', ready: false, showCharacterFilters: true, buildVersion: build.version
  },
  async onShow() {
    if (this.getTabBar && this.getTabBar()) this.getTabBar().setData({selected: 2});
    this.restoreCache(getApp().userId);
    const catalogTask = call('sources.list');
    // Observe rejection immediately while identity/preferences are being loaded.
    catalogTask.catch(() => {});
    try {
      this.user = await getApp().session();
      const saved = wx.getStorageSync(preferenceKey(this.user)) || {};
      this.filters = normalizeFilters(saved);
      this.setData({required: this.filters.required, excluded: this.filters.excluded,
        ready: true, inputError: '', savedNotice: ''});
      this.renderSources();
      this.restoreCache(this.user);
      await this.loadSources(true, catalogTask);
    } catch (error) {
      this.setData({sourceLoading: false, sourceError: this.catalog ? '' : error.message || '暂时没有连接上，请重试'});
    }
  },
  restoreCache(user) {
    if (!user) return;
    if (this.catalogUser && this.catalogUser !== user) {
      this.catalog = null;
      this.renderSources();
    }
    this.catalogUser = user;
    const cached = readCache('sources', user);
    if (!Array.isArray(cached)) return;
    this.filters = normalizeFilters(wx.getStorageSync(preferenceKey(user)) || {});
    this.catalog = cached;
    this.renderSources();
    this.setData({sourceLoading: false, sourceError: ''});
  },
  async loadSources(silent = false, catalogTask) {
    if (!this.user) return this.onShow();
    if (this.sourcePending) return this.sourcePending;
    silent = silent === true;
    this.setData({sourceLoading: !this.catalog, sourceError: ''});
    this.sourcePending = (catalogTask || call('sources.list')).then(result => {
      this.catalog = result.sources || [];
      writeCache('sources', this.user, this.catalog);
      this.renderSources();
    }).catch(error => {
      if (!(silent && this.catalog)) this.setData({sourceError: error.message || '来源暂时没加载成功，请重试'});
    }).finally(() => {
      this.sourcePending = null;
      this.setData({sourceLoading: false});
    });
    return this.sourcePending;
  },
  renderSources() {
    const disabled = new Set((this.filters || {}).excluded_sources || []);
    const sources = (this.catalog || []).map(source => ({...source, enabled: !disabled.has(source.name)}));
    this.setData({sources, sourceCount: sources.length, enabledCount: sources.filter(source => source.enabled).length});
  },
  saveFilters(next) {
    if (!this.user) return false;
    const filters = normalizeFilters(next);
    try {
      const preferences = {...(wx.getStorageSync(preferenceKey(this.user)) || {}), ...filters};
      wx.setStorageSync(preferenceKey(this.user), preferences);
      getApp().namePreferences = preferences;
      this.filters = filters;
      this.setData({savedNotice: '已保存，返回首页即生效'});
      return true;
    } catch {
      wx.showToast({title: '设置未保存，请重试', icon: 'none'});
      return false;
    }
  },
  characterInput(event) {
    const field = event.currentTarget.dataset.field;
    if (!['required', 'excluded'].includes(field)) return;
    const value = cleanCharacters(event.detail.value, field === 'required' ? 2 : 32);
    this.setData({[field]: value});
    const next = {...this.filters, required: this.data.required, excluded: this.data.excluded};
    const inputError = filterError(next);
    this.setData({inputError, savedNotice: ''});
    if (!inputError) this.saveFilters(next);
    return value;
  },
  sourceChange(event) {
    const name = event.currentTarget.dataset.name;
    if (!(this.catalog || []).some(source => source.name === name)) return;
    const disabled = new Set(this.filters.excluded_sources);
    if (event.detail.value) disabled.delete(name); else disabled.add(name);
    this.saveFilters({...this.filters, excluded_sources: [...disabled]});
    this.renderSources();
  },
  chooseNames() {
    if (this.data.inputError) return wx.showToast({title: '请先解决用字冲突', icon: 'none'});
    wx.switchTab({url: '/pages/discover/index'});
  }
});
