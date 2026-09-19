const {preferenceKey} = require('../../utils/api');

Page({
  data: {surname: '未设置', gender: '不限', loading: true},
  async onShow() {
    if (this.getTabBar && this.getTabBar()) this.getTabBar().setData({selected: 2});
    try {
      const user = await getApp().session();
      const saved = wx.getStorageSync(preferenceKey(user)) || {};
      const gender = {male: '男孩', female: '女孩', any: '不限'}[saved.gender] || '不限';
      this.setData({surname: saved.surname || '未设置', gender, loading: false});
    } catch (error) {
      this.setData({loading: false});
    }
  },
  chooseNames() { wx.switchTab({url: '/pages/discover/index'}); },
  showPrivacy() {
    wx.showModal({title: '隐私说明', content: '无需填写手机号或创建帐号。微信云开发会提供当前小程序内的匿名 OPENID，用于同步收藏和避免重复展示名字。', showCancel: false, confirmText: '知道了'});
  }
});
