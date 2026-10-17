import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac, webcrypto } from 'node:crypto';
import { ChatSocket } from '../chat/socket.mjs';

class FakeSocket {
  static instance;
  constructor() { FakeSocket.instance = this; this.sent = []; }
  send(value) { this.sent.push(JSON.parse(value)); }
  close() { this.closed = true; }
  message(data) { return this.onmessage({ data: JSON.stringify(data) }); }
}
const setup = () => new ChatSocket('wss://chat.example/lib/api/chat/ws', { WebSocketClass: FakeSocket, crypto: webcrypto });

test('authenticates before submitting and delivers final answer', async () => {
  const client = setup(), updates = [], request = { type: 'submit', engine: 'codex', prompt: 'hello' };
  const result = client.watch('test-secret', request, data => updates.push(data));
  const ws = FakeSocket.instance, nonce = 'a'.repeat(64);
  await ws.message({ type: 'challenge', nonce });
  assert.deepEqual(ws.sent, [{ type: 'auth', signature: createHmac('sha256', 'test-secret').update(`WS\n/lib/api/chat/ws\n${nonce}`).digest('hex') }]);
  await ws.message({ type: 'authenticated' });
  assert.deepEqual(ws.sent[1], request);
  await ws.message({ type: 'job', ask_status: 'running', ask_id: 'id' });
  await ws.message({ type: 'job', ask_status: 'done', reply: '<script>plain text</script>' });
  await result;
  assert.equal(updates.length, 2);
  assert.equal(client.socket, null);
});

test('disconnect does not resend a prompt', async () => {
  const client = setup();
  const result = client.watch('secret', { type: 'submit' }, () => {});
  const assertion = assert.rejects(result, /接続が切れ/);
  const ws = FakeSocket.instance;
  ws.onclose({ code: 1006 });
  await assertion;
  assert.equal(ws.sent.length, 0);
  assert.equal(client.socket, null);
});

test('resume request never sends a submit', async () => {
  const client = setup(), request = { type: 'resume', ask_id: 'existing' };
  const result = client.watch('secret', request, () => {});
  const ws = FakeSocket.instance;
  await ws.message({ type: 'challenge', nonce: 'b'.repeat(64) });
  await ws.message({ type: 'authenticated' });
  assert.deepEqual(ws.sent[1], request);
  await ws.message({ type: 'job', ask_status: 'done', reply: 'answer' });
  await result;
});

test('bad authentication closes and frees the connection', async () => {
  const client = setup();
  const result = client.watch('wrong', { type: 'submit' }, () => {});
  const assertion = assert.rejects(result, /認証に失敗/);
  FakeSocket.instance.onclose({ code: 1008, reason: 'authentication_failed' });
  await assertion;
  assert.equal(client.socket, null);
});

test('observation session reconnects with an empty key without invoking WebCrypto', async () => {
  const client = new ChatSocket('wss://chat.example/lib/api/chat/ws', {
    WebSocketClass: FakeSocket,
    crypto: { subtle: { importKey() { throw new Error('must not import an empty HMAC key'); } } },
  });
  const updates = [];
  const result = client.watch('', { type: 'observe' }, data => updates.push(data), 'observer-token');
  const assertion = assert.rejects(result, /受信を停止/);
  const ws = FakeSocket.instance;
  await ws.message({ type: 'challenge', nonce: 'a'.repeat(64) });
  assert.deepEqual(ws.sent[0], { type: 'session_auth', token: 'observer-token' });
  await ws.message({ type: 'authenticated' });
  assert.deepEqual(ws.sent[1], { type: 'observe' });
  await ws.message({ type: 'conversation', messages: [] });
  assert.equal(updates[0].type, 'conversation');
  ws.onclose({ code: 1000, reason: 'stop_watching' });
  await assertion;
});

for (const withErrorFrame of [true, false]) {
  test(`observer outage preserves authentication (error frame: ${withErrorFrame})`, async () => {
    const client = setup(), updates = [];
    const result = client.watch('', { type: 'observe' }, data => updates.push(data), 'valid-token');
    const rejected = assert.rejects(result, error => error.code === (withErrorFrame ? 'worker_unavailable' : 'disconnected'));
    const ws = FakeSocket.instance;
    await ws.message({ type: 'challenge', nonce: 'a'.repeat(64) });
    await ws.message({ type: 'authenticated' });
    if (withErrorFrame) await ws.message({ type: 'error', error: 'worker_unavailable' });
    ws.onclose({ code: 1008, reason: 'worker_unavailable' });
    await rejected;
    assert.equal(updates.some(data => data.type === 'session_expired'), false);
  });
}

test('pasted key whitespace matches the server normalization', async () => {
  const client = setup();
  const result = client.watch('  test-secret \n', { type: 'submit' }, () => {});
  const ws = FakeSocket.instance, nonce = 'a'.repeat(64);
  await ws.message({ type: 'challenge', nonce });
  assert.equal(ws.sent[0].signature, createHmac('sha256', 'test-secret').update(`WS\n/lib/api/chat/ws\n${nonce}`).digest('hex'));
  await ws.message({ type: 'authenticated' });
  await ws.message({ type: 'job', ask_status: 'done' });
  await result;
});
