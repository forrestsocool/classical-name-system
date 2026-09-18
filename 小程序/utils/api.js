const config=require('../config');
function request(url, options={}) {
  return new Promise((resolve, reject) => wx.request({...options, url, timeout:10000,
    success:resolve, fail:reject}));
}
async function testSession() {
  const login = await new Promise((resolve, reject) => wx.login({success:resolve, fail:reject}));
  if (!login.code) throw new Error('微信登录失败，请重新打开小程序');
  const response = await request(config.coreBaseUrl + '/api/test/session', {
    method:'POST', data:{code:login.code}, header:{'content-type':'application/json'}
  });
  if (response.statusCode < 200 || response.statusCode >= 300 || !response.data?.token) {
    throw new Error(response.data?.detail || '微信登录失败，请重新打开小程序');
  }
  wx.setStorageSync('test-session-token', response.data.token);
  return response.data.token;
}
async function testCall(action, data) {
  let token = wx.getStorageSync('test-session-token');
  for (let attempt=0; attempt<2; attempt++) {
    if (!token) token = await testSession();
    const response = await request(config.coreBaseUrl + '/api/test/dispatch', {
      method:'POST', data:{action,data}, header:{'content-type':'application/json','Authorization':'Bearer '+token}
    });
    if (response.statusCode === 401 && attempt === 0) { wx.removeStorageSync('test-session-token'); token=''; continue; }
    const result = response.data;
    if (response.statusCode < 200 || response.statusCode >= 300 || !result?.ok) {
      const e = new Error(result?.detail || result?.message || '服务暂时不可用'); e.status=result?.status || response.statusCode; throw e;
    }
    return result.data;
  }
}
async function call(action,data={}) {
  if (config.mode === 'test-http') return testCall(action, data);
  if(!wx.cloud || !config.envId) throw new Error('请先配置小程序云环境');
  let response;
  try {response=await wx.cloud.callFunction({name:config.gateway,data:{action,data},config:{env:config.envId}});}
  catch {throw new Error('连接失败，请检查网络后重试');}
  const result=response.result;
  if(!result || !result.ok){const e=new Error(result?.message||'服务暂时不可用');e.status=result?.status;throw e;}
  return result.data;
}
// Used solely for idempotency, never as identity or a credential.
function requestId(){return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,c=>{const r=Math.floor(Math.random()*16);return(c==='x'?r:(r&3)|8).toString(16);});}
function storageKey(user){return 'classical-names-v1:'+user;}
module.exports={call,requestId,storageKey};
