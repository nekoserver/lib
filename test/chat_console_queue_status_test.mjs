import test from 'node:test';
import assert from 'node:assert/strict';
import {renderConsoleQueue} from '../chat/console-queue.mjs';
test('updates waiting count as queue drains without promising a model reply',()=>{
 const element={textContent:'queued'};
 for(const pending of [3,1,0]){
  renderConsoleQueue({available:true,pending,hasMore:false},element);
  assert.ok(element.textContent.includes(String(pending)));
  assert.ok(!element.textContent.includes('応答が届きます'));
 }
 assert.ok(element.textContent.includes('会話欄で確認'));
});
test('failure and malformed state are never shown as drained or sent',()=>{
 for(const state of [null,{}, {available:false}, {available:true,pending:-1}, {available:true,pending:'0'}]){
  const element={textContent:'old waiting'};renderConsoleQueue(state,element);
  assert.ok(element.textContent.includes('確認できません'));assert.ok(!element.textContent.includes('0件'));
 }
});
