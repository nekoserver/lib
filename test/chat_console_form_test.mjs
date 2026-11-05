import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
const source=readFileSync(new URL('../chat/app.mjs',import.meta.url),'utf8');
const handler=source.slice(source.indexOf("$('console-form').addEventListener('submit'"),source.indexOf("$('console-revoke').addEventListener"));
for (const [status,data,message,cleared] of [
 [200,{accepted:true},'送信しました。この会話に応答が届きます。',true],
 [200,{accepted:true,queued:true},'この会話の送信待ちに追加しました。現在の処理後に応答が届きます。',true],
 [409,{error:'console_in_use'},'この会話は別のCodexで使用中のため、ここから直接送信できません。',false],
 [200,{accepted:false},'送信を受理できませんでした。',false],
]) {
 test(`actual stream form handles HTTP ${status} accepted=${data.accepted} error=${data.error}`,async()=>{
  const elements=new Map();let submit;const calls=[];
  const $=id=>{if(!elements.has(id)) elements.set(id,{value:id==='console-prompt'?'test prompt':'',textContent:'',addEventListener:(_,fn)=>{submit=fn;}});return elements.get(id);};
  const context={$,consoleBusy:false,consoleAuthorized:true,consoleToken:'isolated-test-token',TextEncoder,
   updateConsoleSection(){},async fetch(path,options){calls.push([path,options]);return {ok:status<400,status,async json(){return data;}};},Error};
  vm.runInNewContext(handler,context);let prevented=false;
  await submit({preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assert.equal(calls.length,1);assert.equal(calls[0][0],'/lib/api/chat/console');
  assert.equal(JSON.parse(calls[0][1].body).prompt,'test prompt');
  assert.equal($('console-status').textContent,message);
  assert.equal($('console-prompt').value,cleared?'':'test prompt');assert.equal(context.consoleBusy,false);
 });
}
