import test from 'node:test';
import assert from 'node:assert/strict';
import { ObserveReconnect, reconnectStatus } from '../chat/reconnect.mjs';

test('retry status preserves the observer failure instead of reporting a generic disconnect', () => {
  const error = new Error('会話の配信サーバーに接続できません。');
  assert.equal(reconnectStatus(error, 2000), '会話の配信サーバーに接続できません。 2秒後に再接続します。');
});

test('read-only observation reconnects with bounded backoff and resets after data', () => {
  const timers = [], calls = [];
  const retry = new ObserveReconnect(() => calls.push('observe'), { setTimer: (fn, delay) => { timers.push({fn,delay}); return timers.length; }, clearTimer() {} });
  retry.begin();
  for (const delay of [1000,2000,4000,8000,15000]) {
    assert.equal(retry.schedule({code:'observer_unavailable'}, true), delay);
    timers.at(-1).fn();
  }
  assert.equal(calls.length,5);
  retry.reset();
  assert.equal(retry.schedule({code:'disconnected'},true),1000);
});

test('stopping, missing auth and permanent errors never restart observation', () => {
  const timers = [], cleared = [];
  const retry = new ObserveReconnect(() => {}, {setTimer:(fn,delay)=>{timers.push(delay);return 42;},clearTimer:id=>cleared.push(id)});
  retry.begin();
  assert.equal(retry.schedule({code:'auth_rejected'},true),null);
  assert.equal(retry.schedule({code:'invalid_request'},true),null);
  assert.equal(retry.schedule({code:'disconnected'},false),null);
  assert.equal(retry.schedule({code:'disconnected'},true),1000);
  retry.stop();
  assert.deepEqual(cleared,[42]);
  assert.equal(retry.schedule({code:'disconnected'},true),null);
  assert.deepEqual(timers,[1000]);
});

test('browser timers are called with their global receiver', () => {
  const originalSet = globalThis.setTimeout, originalClear = globalThis.clearTimeout;
  try {
    globalThis.setTimeout = function () { assert.equal(this, globalThis); return 7; };
    globalThis.clearTimeout = function (id) { assert.equal(this, globalThis); assert.equal(id, 7); };
    const retry = new ObserveReconnect(() => {});
    retry.begin();
    assert.equal(retry.schedule({code:'disconnected'},true),1000);
    retry.stop();
  } finally { globalThis.setTimeout = originalSet; globalThis.clearTimeout = originalClear; }
});
