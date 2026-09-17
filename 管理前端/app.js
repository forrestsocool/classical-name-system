'use strict';
let key = '';
const $ = s => document.querySelector(s);
const statuses = {passages:['待核验','已核验','不采用'],elements:['待复核','已核验','不采用'],issues:['待处理','已处理','忽略']};
function message(text, error=false){$('#message').textContent=text;$('#message').className=error?'error':'';}
async function api(path, method='GET', data){
  const response=await fetch('/api/admin/'+path,{method,headers:{'X-Admin-Key':key,'Content-Type':'application/json'},body:data?JSON.stringify(data):undefined});
  const result=await response.json();if(!response.ok)throw new Error(result.detail||'操作失败');return result;
}
function el(tag,text){const node=document.createElement(tag);if(text!==undefined)node.textContent=String(text);return node;}
function table(target,rows,fields,action){
  const t=el('table'),head=el('tr');fields.forEach(([label])=>head.append(el('th',label)));if(action)head.append(el('th','操作'));t.append(head);
  for(const row of rows){const tr=el('tr');fields.forEach(([,name])=>tr.append(el('td',row[name]??'—')));if(action){const cell=el('td');cell.append(action(row));tr.append(cell);}t.append(tr);}
  target.replaceChildren(rows.length?t:el('p','暂无记录'));
}
async function refresh(){
  const [m,p,c,f]=await Promise.all([api('metrics'),api('profiles'),api('model-config'),api('feedback')]);
  $('#metrics').replaceChildren(...Object.entries(m.totals).map(([name,value])=>{const n=el('div');n.className='stat';n.append(el('span',name),el('strong',value));return n;}));
  $('#worker').textContent=`生产进程：${m.worker?(m.worker.alive?m.worker.status:'心跳中断'):'尚未启动'} · 今日批次 ${m.today_batches} / ${m.daily_limit}${m.worker?.last_error?' · '+m.worker.last_error:''}`;
  table($('#sources'),m.sources,[['姓氏','surname'],['字数','name_length'],['来源','book'],['批次','batches'],['入库','accepted'],['连续失败','failures'],['异常','last_error']]);
  table($('#profiles'),p,[['姓氏','surname'],['字数','name_length'],['库存','stock'],['启用','enabled']],row=>{const b=el('button',row.enabled?'暂停':'启用');b.onclick=()=>work(b,async()=>{await api('profiles','PUT',{surname:row.surname,name_length:row.name_length,enabled:!row.enabled});await refresh();});return b;});
  for(const name of ['地址','模型','超时秒数'])$('#model').elements[name].value=c[name];$('#modelStatus').textContent=c.已配置?'模型已配置':'尚未配置模型';
  table($('#feedback'),f,[['姓名','full_name'],['来源','book'],['类型','kind'],['内容','comment'],['时间','created_at']]);
}
async function work(button,fn){if(button.disabled)return;button.disabled=true;try{await fn();message('操作完成');}catch(e){message(e.message,true);}finally{button.disabled=false;}}
$('#login').onsubmit=e=>{e.preventDefault();key=$('#adminKey').value;$('#adminKey').value='';work(e.submitter,async()=>{await refresh();$('#console').hidden=false;});};
$('#logout').onclick=()=>{key='';$('#console').hidden=true;$('#model').reset();$('#reviews').replaceChildren();message('已退出');};
$('#refresh').onclick=e=>work(e.target,refresh);
$('#profile').onsubmit=e=>{e.preventDefault();const f=e.target.elements;work(e.submitter,async()=>{await api('profiles','PUT',{surname:f.surname.value.trim(),name_length:Number(f.name_length.value),enabled:true});await refresh();});};
$('#model').onsubmit=e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));data.超时秒数=Number(data.超时秒数);work(e.submitter,async()=>{await api('model-config','PUT',data);e.target.elements['密钥'].value='';await refresh();});};
function updateStatuses(){const select=$('#reviewStatus');select.replaceChildren(...statuses[$('#reviewKind').value].map(s=>{const n=el('option',s);n.value=s;return n;}));}
$('#reviewKind').onchange=updateStatuses;updateStatuses();
$('#reviewFilter').onsubmit=e=>{e.preventDefault();work(e.submitter,async()=>{
  const kind=$('#reviewKind').value;const rows=await api(`review/${kind}?status=${encodeURIComponent($('#reviewStatus').value)}`);
  $('#reviews').replaceChildren(...rows.map(row=>{const card=el('article');card.className='review';card.append(el('h3',row.book||row.char||row.issue_type),el('pre',row.text||row.note||row.detail||''));
    const note=el('textarea');note.placeholder='复核备注';card.append(note);
    for(const status of statuses[kind]){const b=el('button',status);b.className='secondary';b.onclick=()=>work(b,async()=>{const reviewer=$('#reviewer').value.trim();if(!reviewer)throw new Error('请填写复核人');await api(`review/${kind}/${encodeURIComponent(row.id??row.char)}`,'POST',{status,reviewer,note:note.value,method:row.method||''});card.remove();});card.append(b);}return card;}));
  if(!rows.length)$('#reviews').append(el('p','该状态下暂无资料'));
});};
