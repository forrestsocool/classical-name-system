'use strict';
const crypto = require('node:crypto');
const https = require('node:https');
const ACTIONS = new Set(['session.get','feed.pull','favorites.list','favorites.add','favorites.remove','favorites.compare','feedback.save']);

function signedHeaders(body, secret, timestamp = String(Math.floor(Date.now()/1000)), nonce = crypto.randomBytes(16).toString('hex')) {
  const digest = crypto.createHash('sha256').update(body).digest('hex');
  const signature = crypto.createHmac('sha256',secret).update(`v1\n${timestamp}\n${nonce}\n${digest}`).digest('hex');
  return {'Content-Type':'application/json','Content-Length':Buffer.byteLength(body),
    'X-Gateway-Timestamp':timestamp,'X-Gateway-Nonce':nonce,'X-Gateway-Signature':signature};
}

function forward(url, body, headers) {
  return new Promise((resolve,reject) => {
    const request = https.request(url,{method:'POST',headers},response => {
      let size=0;const chunks=[];
      response.on('data',chunk=>{size+=chunk.length;if(size>512*1024){response.destroy();request.destroy(new Error('response too large'));}else chunks.push(chunk);});
      response.on('error',reject);
      response.on('end',()=>{
        try {resolve({status:response.statusCode,data:JSON.parse(Buffer.concat(chunks).toString('utf8'))});}
        catch {reject(new Error('invalid upstream response'));}
      });
    });
    // Absolute deadline, including DNS and TLS; never follow redirects.
    const timer=setTimeout(()=>request.destroy(new Error('upstream timeout')),10000);
    request.on('error',reject);request.on('close',()=>clearTimeout(timer));request.end(body);
  });
}

function createHandler({getContext, transport=forward, env=process.env}) {
  return async event => {
    try {
      const {OPENID,APPID}=getContext();
      if(!OPENID || !APPID || APPID!==env.WECHAT_APP_ID) return {ok:false,status:401,message:'请从已配置的小程序访问'};
      if(!event || !ACTIONS.has(event.action)) return {ok:false,status:404,message:'操作不存在'};
      if(event.data !== undefined && (!event.data || typeof event.data!=='object' || Array.isArray(event.data))) return {ok:false,status:422,message:'参数格式不正确'};
      if(!env.CORE_API_URL || !/^[\x21-\x7e]{32,}$/.test(env.GATEWAY_SECRET||'')) throw new Error('configuration');
      const url=new URL(env.CORE_API_URL);
      if(url.protocol!=='https:' || url.username || url.password || url.search || url.hash || url.pathname!=='/') throw new Error('configuration');
      url.pathname='/internal/v1/dispatch';
      // Never accept caller-supplied identity, headers, target URL or method.
      const body=JSON.stringify({appid:APPID,openid:OPENID,action:event.action,data:event.data||{}});
      if(Buffer.byteLength(body)>16384) return {ok:false,status:413,message:'请求过大'};
      const result=await transport(url,body,signedHeaders(body,env.GATEWAY_SECRET));
      if(result.status>=200 && result.status<300) return {ok:true,data:result.data};
      const safeStatus=[401,403,404,409,413,422,429].includes(result.status)?result.status:503;
      return {ok:false,status:safeStatus,message:safeStatus===503?'服务暂时不可用，请稍后重试':String(result.data.detail||'操作未完成').slice(0,120)};
    } catch {return {ok:false,status:503,message:'服务暂时不可用，请稍后重试'};}
  };
}
module.exports={createHandler,signedHeaders,forward};
