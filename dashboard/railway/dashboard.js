'use strict';
const $ = id => document.getElementById(id);
const endpoint = '/lib/dashboard/railway/status.rb';
let snapshot = null;
let filter = 'all';
let busy = false;
let key = '';
const states = {running:'稼働中',stopped:'停止',degraded:'応答異常',unknown:'確認不可'};
function node(tag, text, className) { const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(className)n.className=className; return n; }
function size(bytes) { return (bytes / 1073741824).toFixed(2)+' GiB'; }
function duration(seconds) { if(seconds===null)return '—';const d=Math.floor(seconds/86400),h=Math.floor(seconds%86400/3600),m=Math.floor(seconds%3600/60);return d?`${d}日 ${h}時間` : h?`${h}時間 ${m}分` : `${m}分`; }
function badge(state) { return node('span',states[state]||state,'pill '+state); }
function render() {
  if(!snapshot)return;
  const s=snapshot.services,r=snapshot.resources;
  const stopped=s.filter(x=>x.state==='stopped').length, issues=s.filter(x=>['degraded','unknown'].includes(x.state)).length;
  $('running').textContent=`${s.filter(x=>x.process_count>0).length} / ${s.length}`;
  $('service-summary').textContent=`停止 ${stopped} · 応答異常 / 確認不可 ${issues}`;
  $('memory').textContent=size(r.memory_available_bytes);
  $('memory-note').textContent=`全体 ${size(r.memory_total_bytes)} · Swap 使用 ${size(r.swap_used_bytes)}`;
  $('memory-bar').style.width=`${100*r.memory_available_bytes/r.memory_total_bytes}%`;
  $('disk').textContent=size(r.disk_available_bytes);
  $('disk-note').textContent=`/app · 全体 ${size(r.disk_total_bytes)}`;
  $('disk-bar').style.width=`${100*r.disk_available_bytes/r.disk_total_bytes}%`;
  $('uptime').textContent=duration(r.uptime_seconds);
  $('load').textContent=`負荷平均 ${r.load_average.map(x=>x.toFixed(2)).join(' / ')}（1 / 5 / 15分）`;
  const checked=new Date(snapshot.checked_at);
  $('checked-at').textContent=`確認 ${checked.toLocaleString('ja-JP', {hour12:false})}`;
  const age=Math.max(0,Math.floor((Date.now()-checked.getTime())/1000));
  const stale=snapshot.stale||age>60;
  $('live-dot').className='dot '+(stale?'warning':'live');
  $('freshness').textContent=stale?`データが古くなっています（${age}秒前）。現在の状態は未確認です。`:`${snapshot.scope} · ${age}秒前の確認結果`;
  const rows=s.filter(x=>filter==='all'||x.state!=='running');
  $('services').replaceChildren();
  for(const item of rows){
    const tr=node('tr'),name=node('td');name.append(node('div',item.name,'service-name'),node('div',item.purpose,'service-purpose'));tr.append(name);
    const state=node('td');state.append(badge(item.state));tr.append(state);
    const detail=node('td',undefined,'detail');detail.append(node('div',item.detail));if(item.latency_ms!==undefined)detail.append(node('div',`${item.latency_ms} ms`,'secondary'));tr.append(detail);
    tr.append(node('td',duration(item.uptime_seconds),'secondary'));
    const pid=node('td',item.pids.join(', ')||'—','pid secondary');pid.title=item.pids.join(', ');tr.append(pid);$('services').append(tr);
  }
  if(!rows.length){const tr=node('tr'),td=node('td','要確認のサービスはありません。','empty');td.colSpan=5;tr.append(td);$('services').append(tr);}
  const docker=s.find(x=>x.key==='docker');$('containers').replaceChildren();
  const containers=docker?.containers;
  $('container-count').textContent=containers?containers.length:'未確認';
  if(!containers){$('containers').append(node('p','コンテナ一覧は取得できていません。'+(docker?.detail||''),'empty'));}
  else if(!containers.length){$('containers').append(node('p','コンテナは0件です。Docker デーモンは稼働しています。','empty'));}
  else for(const c of containers){const row=node('div',undefined,'container'),info=node('div');info.append(node('strong',c.name),node('div',c.image,'secondary'));row.append(info,node('span',c.state,'pill '+(c.state==='running'?'running':'stopped')),node('span',c.status,'secondary'));$('containers').append(row);}
}
async function signedHeaders(){
  if(!key)return {};
  const enc=new TextEncoder();
  const hex=b=>Array.from(new Uint8Array(b),x=>x.toString(16).padStart(2,'0')).join('');
  const ts=Math.floor(Date.now()/1000).toString();
  const bodyHash=hex(await crypto.subtle.digest('SHA-256',enc.encode('')));
  const signingKey=await crypto.subtle.importKey('raw',enc.encode(key),{name:'HMAC',hash:'SHA-256'},false,['sign']);
  const signature=hex(await crypto.subtle.sign('HMAC',signingKey,enc.encode(`GET\n${endpoint}\n${ts}\n${bodyHash}`)));
  return {'X-Timestamp':ts,'X-Signature':signature};
}
async function refresh(){
  if(busy)return;busy=true;$('refresh').disabled=true;
  try{
    const response=await fetch(endpoint,{headers:await signedHeaders(),cache:'no-store',signal:AbortSignal.timeout(8000)});
    if(response.status===401){$('auth').hidden=false;throw new Error('認証が必要です。許可された接続元、または HMAC キーで接続してください。');}
    if(!response.ok)throw new Error(`稼働データの取得に失敗しました（HTTP ${response.status}）。`);
    const data=await response.json();
    if(!Array.isArray(data.services)||!data.resources||!data.checked_at)throw new Error('稼働データの形式が不正です。');
    snapshot=data;$('error').hidden=true;$('auth').hidden=true;render();
  }catch(error){
    $('error').textContent=(error.name==='TimeoutError'?'稼働データの取得がタイムアウトしました。':error.message)+(snapshot?' 表示は前回の取得結果です。':'');$('error').hidden=false;
    $('live-dot').className='dot warning';$('freshness').textContent='最新の状態を取得できていません';
  }finally{busy=false;$('refresh').disabled=false;}
}
$('refresh').addEventListener('click',refresh);
$('auth').addEventListener('submit',e=>{e.preventDefault();key=$('secret').value.trim();$('secret').value='';refresh();});
for(const button of document.querySelectorAll('[data-filter]'))button.addEventListener('click',()=>{filter=button.dataset.filter;for(const b of document.querySelectorAll('[data-filter]'))b.setAttribute('aria-pressed',String(b===button));render();});
setInterval(()=>{if($('auto').checked&&!document.hidden)refresh();},15000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden){if(snapshot)render();if($('auto').checked)refresh();}});
refresh();
