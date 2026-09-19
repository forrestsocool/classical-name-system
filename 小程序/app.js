const config = require('./config');
App({
  onLaunch() {
    this.selectedCard = null;
    this.namePreferences = {surname: '', gender: 'any'};
    if (wx.cloud && config.envId) wx.cloud.init({env:config.envId, traceUser:true});
  },
  async session() {
    if (!this.sessionPromise) {
      const {call} = require('./utils/api');
      this.sessionPromise=call('session.get',{}).then(data=>{this.userId=data.user_id;return data.user_id;}).catch(e=>{this.sessionPromise=null;throw e;});
    }
    return this.sessionPromise;
  }
});
