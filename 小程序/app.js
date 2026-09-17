const config = require('./config');
App({
  onLaunch() {
    this.selectedCard = null;
    if (wx.cloud && config.envId) wx.cloud.init({env:config.envId});
  },
  async session() {
    if (!wx.cloud || !config.envId) throw new Error('请先配置小程序云环境');
    if (!this.sessionPromise) {
      const {call} = require('./utils/api');
      this.sessionPromise=call('session.get',{}).then(data=>{this.userId=data.user_id;return data.user_id;}).catch(e=>{this.sessionPromise=null;throw e;});
    }
    return this.sessionPromise;
  }
});
