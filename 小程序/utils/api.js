const config = require('../config');

// Share one WeChat login between simultaneous page requests. Keep the session
// in memory so that changing CloudBase environments cannot reuse an old token.
let sessionToken = '';
let sessionData = null;
let loginPromise = null;

function wxLogin() {
  return new Promise((resolve, reject) => {
    if (!wx.login) return reject(new Error('wx.login 不可用'));
    wx.login({
      success: res => res.code ? resolve(res.code) : reject(new Error('获取微信登录态失败')),
      fail: () => reject(new Error('获取微信登录态失败'))
    });
  });
}

function requestHttp(payload) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: config.httpUrl,
      method: 'POST',
      data: payload,
      header: { 'Content-Type': 'application/json' },
      timeout: 15000,
      success: res => {
        const body = res.data;
        if (res.statusCode < 200 || res.statusCode >= 300 || !body || !body.ok) {
          const error = new Error(body?.message || '服务暂时不可用，请稍后重试');
          error.status = body?.status || res.statusCode;
          reject(error);
          return;
        }
        resolve(body.data);
      },
      fail: () => reject(new Error('连接失败，请检查网络后重试'))
    });
  });
}

function login(force = false) {
  if (!force && sessionToken && sessionData) return Promise.resolve(sessionData);
  if (loginPromise) return loginPromise;
  loginPromise = (async () => {
    const code = await wxLogin();
    const data = await requestHttp({ action: 'session.get', code, data: {} });
    if (!data || !data.sessionToken || !data.user_id) throw new Error('登录结果不完整，请重试');
    sessionToken = data.sessionToken;
    sessionData = data;
    return data;
  })().finally(() => { loginPromise = null; });
  return loginPromise;
}

async function callHttp(action, data = {}) {
  if (action === 'session.get') return login();
  if (!sessionToken) await login();
  const token = sessionToken;
  try {
    return await requestHttp({ action, sessionToken: token, data });
  } catch (error) {
    if (error.status !== 401) throw error;
    if (sessionToken === token) {
      sessionToken = '';
      sessionData = null;
      await login(true);
    }
    return requestHttp({ action, sessionToken, data });
  }
}

async function callCloud(action, data = {}) {
  if (!wx.cloud || !config.envId) throw new Error('请先配置小程序云环境');
  let response;
  try {
    response = await wx.cloud.callFunction({
      name: config.gateway,
      data: { action, data },
      config: { env: config.envId }
    });
  } catch {
    throw new Error('连接失败，请检查网络后重试');
  }
  const result = response.result;
  if (!result || !result.ok) {
    const e = new Error(result?.message || '服务暂时不可用');
    e.status = result?.status;
    throw e;
  }
  return result.data;
}

function call(action, data = {}) {
  return config.mode === 'http' ? callHttp(action, data) : callCloud(action, data);
}

function requestId() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.floor(Math.random() * 16);
    return (c === 'x' ? r : (r & 3) | 8).toString(16);
  });
}
function storageKey(user) { return 'qianqianjiaming-v3:' + user; }
function preferenceKey(user) { return 'qianqianjiaming-preferences-v1:' + user; }

module.exports = { call, requestId, storageKey, preferenceKey, callHttp, callCloud };
