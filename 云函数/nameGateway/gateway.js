'use strict';
const crypto = require('node:crypto');
const https = require('node:https');
const ACTIONS = new Set([
  'session.get', 'sources.list', 'feed.pull', 'names.analyze', 'names.detail',
  'favorites.list', 'favorites.add', 'favorites.remove', 'feedback.save'
]);
const SESSION_SECONDS = 12 * 60 * 60;

function signedHeaders(body, secret, timestamp = String(Math.floor(Date.now() / 1000)), nonce = crypto.randomBytes(16).toString('hex')) {
  const digest = crypto.createHash('sha256').update(body).digest('hex');
  const signature = crypto.createHmac('sha256', secret).update(`v1\n${timestamp}\n${nonce}\n${digest}`).digest('hex');
  return {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
    'X-Gateway-Timestamp': timestamp,
    'X-Gateway-Nonce': nonce,
    'X-Gateway-Signature': signature
  };
}

function forward(url, body, headers = {}, method = 'POST') {
  return new Promise((resolve, reject) => {
    const isGet = method === 'GET' || body === null || body === undefined;
    const reqHeaders = isGet ? headers : {
      'Content-Type': 'application/json',
      'Content-Length': Buffer.byteLength(body),
      ...headers
    };
    const request = https.request(url, { method: isGet ? 'GET' : 'POST', headers: reqHeaders }, response => {
      let size = 0;
      const chunks = [];
      response.on('data', chunk => {
        size += chunk.length;
        if (size > 512 * 1024) { response.destroy(); request.destroy(new Error('response too large')); }
        else chunks.push(chunk);
      });
      response.on('error', reject);
      response.on('end', () => {
        try { resolve({ status: response.statusCode, data: JSON.parse(Buffer.concat(chunks).toString('utf8')) }); }
        catch { reject(new Error('invalid upstream response')); }
      });
    });
    const timer = setTimeout(() => request.destroy(new Error('upstream timeout')), 10000);
    request.on('error', reject);
    request.on('close', () => clearTimeout(timer));
    request.end(isGet ? undefined : body);
  });
}

async function exchangeCode(code, env, transport = forward) {
  if (typeof code !== 'string' || !/^[A-Za-z0-9_-]{8,512}$/.test(code)) return null;
  const url = new URL('https://api.weixin.qq.com/sns/jscode2session');
  url.search = new URLSearchParams({
    appid: env.WECHAT_APP_ID,
    secret: env.WECHAT_APP_SECRET,
    js_code: code,
    grant_type: 'authorization_code'
  }).toString();
  const response = await transport(url, null, {}, 'GET');
  const openid = response?.data?.openid;
  if (response?.status !== 200 || response?.data?.errcode || typeof openid !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(openid)) {
    return null;
  }
  return openid;
}

function issueToken(openid, env, now = Date.now()) {
  const payload = Buffer.from(JSON.stringify({
    v: 1, appid: env.WECHAT_APP_ID, openid, exp: Math.floor(now / 1000) + SESSION_SECONDS
  })).toString('base64url');
  const signature = crypto.createHmac('sha256', env.GATEWAY_SECRET).update(payload).digest('base64url');
  return `${payload}.${signature}`;
}

function verifyToken(token, env, now = Date.now()) {
  if (typeof token !== 'string' || token.length > 512 || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(token)) return null;
  const [payload, signature] = token.split('.');
  const expected = crypto.createHmac('sha256', env.GATEWAY_SECRET).update(payload).digest();
  const received = Buffer.from(signature, 'base64url');
  if (received.length !== expected.length || !crypto.timingSafeEqual(received, expected)) return null;
  try {
    const data = JSON.parse(Buffer.from(payload, 'base64url').toString('utf8'));
    if (data.v !== 1 || data.appid !== env.WECHAT_APP_ID || !Number.isSafeInteger(data.exp) ||
        data.exp <= Math.floor(now / 1000) || data.exp > Math.floor(now / 1000) + SESSION_SECONDS ||
        typeof data.openid !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(data.openid)) return null;
    return data.openid;
  } catch { return null; }
}

function createHandler({ getContext = () => ({}), transport = forward, env = process.env, codeExchange = exchangeCode } = {}) {
  return async event => {
    try {
      let req = event || {};
      if (typeof event?.body === 'string') {
        try {
          const raw = event.isBase64Encoded ? Buffer.from(event.body, 'base64').toString('utf8') : event.body;
          req = JSON.parse(raw);
        } catch {
          return { ok: false, status: 400, message: '请求格式不正确' };
        }
      }

      if (!req || !ACTIONS.has(req.action)) return { ok: false, status: 404, message: '操作不存在' };
      if (req.data !== undefined && (!req.data || typeof req.data !== 'object' || Array.isArray(req.data))) {
        return { ok: false, status: 422, message: '参数格式不正确' };
      }
      if (!/^wx[a-f0-9]{16}$/.test(env.WECHAT_APP_ID || '') ||
          !/^[\x21-\x7e]{32,}$/.test(env.WECHAT_APP_SECRET || '') ||
          !/^[\x21-\x7e]{32,}$/.test(env.GATEWAY_SECRET || '')) throw new Error('configuration');

      let openid = null;
      const appid = env.WECHAT_APP_ID;
      try {
        const ctx = getContext();
        if (ctx && ctx.OPENID && ctx.APPID === env.WECHAT_APP_ID) {
          openid = ctx.OPENID;
        }
      } catch {}

      const isLoginCode = req.action === 'session.get' && typeof req.code === 'string';
      if (!openid) {
        if (isLoginCode) {
          openid = await codeExchange(req.code, env, transport);
        } else if (req.sessionToken) {
          openid = verifyToken(req.sessionToken, env);
        }
      }

      if (!openid) {
        return { ok: false, status: 401, message: '请从已配置的小程序访问' };
      }

      if (!env.CORE_API_URL) throw new Error('configuration');
      const url = new URL(env.CORE_API_URL);
      if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash || url.pathname !== '/') throw new Error('configuration');
      url.pathname = '/internal/v1/dispatch';

      const body = JSON.stringify({ appid, openid, action: req.action, data: req.data || {} });
      if (Buffer.byteLength(body) > 16384) return { ok: false, status: 413, message: '请求过大' };

      const result = await transport(url, body, signedHeaders(body, env.GATEWAY_SECRET));
      if (result.status >= 200 && result.status < 300) {
        let data = result.data;
        if (req.action === 'session.get' && data && typeof data === 'object' && !Array.isArray(data)) {
          data = { ...data, openid };
          const token = isLoginCode ? issueToken(openid, env) : req.sessionToken;
          if (token) data.sessionToken = token;
        }
        return { ok: true, data };
      }
      const safeStatus = [401, 403, 404, 409, 413, 422, 429].includes(result.status) ? result.status : 503;
      return { ok: false, status: safeStatus, message: safeStatus === 503 ? '服务暂时不可用，请稍后重试' : String(result.data?.detail || '操作未完成').slice(0, 120) };
    } catch {
      return { ok: false, status: 503, message: '服务暂时不可用，请稍后重试' };
    }
  };
}

module.exports = { createHandler, signedHeaders, forward, exchangeCode, issueToken, verifyToken };
