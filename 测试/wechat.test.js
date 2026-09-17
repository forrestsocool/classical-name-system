'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const crypto=require('node:crypto');
const {createHandler,signedHeaders}=require('../云函数/nameGateway/gateway');
const env={CORE_API_URL:'https://core.example.com',GATEWAY_SECRET:'test-gateway-secret-2026-32-characters',WECHAT_APP_ID:'wx1234567890abcdef'};
const context={APPID:env.WECHAT_APP_ID,OPENID:'trusted-user'};

test('gateway forwards only trusted platform identity to fixed endpoint',async()=>{
  let seen;
  const handler=createHandler({getContext:()=>context,env,transport:async(url,body,headers)=>{seen={url,body,headers};return{status:200,data:{cards:[]}};}});
  const result=await handler({action:'feed.pull',data:{surname:'李'},openid:'victim',appid:'wrong',url:'https://evil.example',headers:{'X-Admin-Key':'bad'}});
  assert.equal(result.ok,true);assert.equal(seen.url.href,'https://core.example.com/internal/v1/dispatch');
  assert.deepEqual(JSON.parse(seen.body),{appid:context.APPID,openid:'trusted-user',action:'feed.pull',data:{surname:'李'}});
  assert.equal(seen.headers['Content-Length'],Buffer.byteLength(seen.body));assert.equal(seen.headers['X-Admin-Key'],undefined);
  const digest=crypto.createHash('sha256').update(seen.body).digest('hex');
  const expected=crypto.createHmac('sha256',env.GATEWAY_SECRET).update(`v1\n${seen.headers['X-Gateway-Timestamp']}\n${seen.headers['X-Gateway-Nonce']}\n${digest}`).digest('hex');
  assert.equal(seen.headers['X-Gateway-Signature'],expected);
});
test('gateway rejects missing identity, unexpected app, admin actions and oversized input',async()=>{
  const transport=()=>{throw new Error('must not forward');};
  assert.equal((await createHandler({getContext:()=>({}),env,transport})({action:'session.get'})).status,401);
  assert.equal((await createHandler({getContext:()=>({...context,APPID:'another'}),env,transport})({action:'session.get'})).status,401);
  const handler=createHandler({getContext:()=>context,env,transport});
  assert.equal((await handler({action:'admin.metrics'})).status,404);
  assert.equal((await handler({action:'feed.pull',data:{x:'字'.repeat(10000)}})).status,413);
  assert.equal((await handler({action:'feed.pull',data:[]})).status,422);
});
test('gateway rejects redirects/config errors and hides upstream secrets',async()=>{
  for(const url of ['http://core.example.com','https://user:pass@core.example.com','https://core.example.com/path','https://core.example.com?target=evil']){
    assert.equal((await createHandler({getContext:()=>context,env:{...env,CORE_API_URL:url}})({action:'session.get'})).status,503);
  }
  for(const status of [302,500]){
    const handler=createHandler({getContext:()=>context,env,transport:async()=>({status,data:{detail:'secret-db-url'}})});
    const result=await handler({action:'session.get'});assert.equal(result.status,503);assert.ok(!result.message.includes('secret'));
  }
});
test('signature changes with body and timestamp',()=>{
  const a=signedHeaders('中文',env.GATEWAY_SECRET,'1789640000','a'.repeat(32));
  const b=signedHeaders('中文 ',env.GATEWAY_SECRET,'1789640000','a'.repeat(32));
  assert.notEqual(a['X-Gateway-Signature'],b['X-Gateway-Signature']);
});

function pageHarness(call,user='user-A',saved={}){
  let page;const storage=new Map(Object.entries(saved));const app={session:async()=>user};
  const wx={getStorageSync:key=>storage.get(key),setStorageSync:(key,value)=>storage.set(key,JSON.parse(JSON.stringify(value))),showToast(){},navigateTo(){}};
  const sandbox={Page:p=>{page=p;},getApp:()=>app,wx,require:()=>({call,requestId:()=>crypto.randomUUID(),storageKey:u=>'cache:'+u}),setInterval:()=>1,clearInterval(){},console};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../小程序/pages/discover/index.js'),'utf8'),sandbox);
  page.data=JSON.parse(JSON.stringify(page.data));page.setData=patch=>Object.assign(page.data,patch);
  return{page,storage};
}
test('mini app keeps request ID across failed pull and retries',async()=>{
  const ids=[];let fail=true;
  const {page,storage}=pageHarness(async(action,data)=>{ids.push(data.request_id);if(fail){fail=false;throw new Error('offline');}return{cards:[{id:1,item:{姓名:'李清和'}}]};});
  await page.onLoad();page.setData({surname:'李'});await page.start();
  assert.ok(page.pending);assert.equal(storage.get('cache:user-A').pending.request_id,ids[0]);
  await page.load();assert.equal(ids[0],ids[1]);assert.equal(page.data.current.id,1);assert.equal(page.pending,null);
});
test('mini app keeps current card when favorite fails and blocks double clicks',async()=>{
  let finish,calls=0;const {page}=pageHarness(()=>{calls++;return new Promise((resolve,reject)=>{finish=reject;});});
  await page.onLoad();page.cards=[{id:1,item:{姓名:'李清和'}}];page.showCard();
  const first=page.favorite();await page.favorite();assert.equal(calls,1);finish(new Error('offline'));await first;
  assert.equal(page.data.current.id,1);assert.equal(page.data.busy,false);
});
test('mini app cache is scoped to authenticated user and rejects contradictory filters',async()=>{
  let calls=0;const {page}=pageHarness(async()=>{calls++;return{cards:[]};},'user-B',{'cache:user-A':{conditions:{surname:'王',name_length:2},cards:[{id:99}]}});
  await page.onLoad();assert.equal(page.data.current,null);assert.equal(page.data.surname,'');
  page.setData({surname:'李',required:'清',excluded:'清'});await page.start();assert.equal(calls,0);assert.ok(page.data.error);
});
test('changing conditions clears cached cards and pending request',async()=>{
  let requested;const {page}=pageHarness(async(action,data)=>{requested=data;return{cards:[]};});
  await page.onLoad();page.setData({surname:'李'});page.activeConditions=page.conditions();page.cards=[{id:1}];page.pending={request_id:'old'};
  page.edit();page.setData({surname:'王'});await page.start();assert.equal(requested.surname,'王');assert.notEqual(requested.request_id,'old');assert.equal(page.cards.length,0);
});
