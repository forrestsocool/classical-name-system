const config=require('../config');
async function call(action,data={}) {
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
