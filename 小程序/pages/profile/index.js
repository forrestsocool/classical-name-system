const {call, preferenceKey} = require('../../utils/api');
const {cleanCharacters, normalizeFilters, filterError} = require('../../utils/filters');
const build = require('../../utils/build');

Page({
  data: {
    required: '', excluded: '', sources: [], sourceCount: 0, enabledCount: 0, sourceLoading: true,
    sourceError: '', inputError: '', savedNotice: '', ready: false, buildVersion: build.version
  },
  async onShow() {
    if (this.getTabBar && this.getTabBar()) this.getTabBar().setData({selected: 2});
    try {
      this.user = await getApp().session();
      const saved = wx.getStorageSync(preferenceKey(this.user)) || {};
      this.filters = normalizeFilters(saved);
      this.setData({required: this.filters.required, excluded: this.filters.excluded,
        ready: true, inputError: '', savedNotice: ''});
      this.renderSources();
      await this.loadSources();
    } catch (error) {
      this.setData({sourceLoading: false, sourceError: error.message || '暂时没有连接上，请重试'});
    }
  },
  async loadSources() {
    if (!this.user) return this.onShow();
    if (this.sourcePending) return this.sourcePending;
    this.setData({sourceLoading: true, sourceError: ''});
    this.sourcePending = call('sources.list').then(result => {
      this.catalog = result.sources || [];
      this.renderSources();
    }).catch(error => {
      this.setData({sourceError: error.message || '来源暂时没加载成功，请重试'});
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
