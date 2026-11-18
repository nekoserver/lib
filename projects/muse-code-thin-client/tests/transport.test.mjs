import test from 'node:test';
import assert from 'node:assert/strict';
import { SdkTransport } from '../src/transport.ts';

const input = { requestId: 'test-1', prompt: 'Read the workspace' };
const env = { SDK_TARGET_URL: 'http://muse-vm:8082/agent/code/run', SDK_API_TOKEN: 'test-only' };
function node(reply, state = 'Running') {
  const calls = [];
  return { calls, status: () => JSON.stringify({ state }), fetch: async r => { calls.push(r); return reply; } };
}
function response(status, body) {
  let read = false;
  return { status, read: async () => read ? null : (read = true, new TextEncoder().encode(JSON.stringify(body))), cancel() {} };
}
test('fixed SDK target, body and authentication; no native or bridge fallback', async () => {
  const n = node(response(200, { requestId: input.requestId, status: 'completed', terminal: 'completed', reply: 'ok' }));
  const r = await new SdkTransport(n, env).run(input);
  assert.equal(r.status, 'completed');
  assert.equal(n.calls.length, 1);
  assert.equal(n.calls[0].url, env.SDK_TARGET_URL);
  assert.equal(n.calls[0].headers.find(([k]) => k === 'Authorization')[1], 'Bearer test-only');
  assert.equal(JSON.parse(new TextDecoder().decode(n.calls[0].body)).requestId, input.requestId);
});
test('HTTP success without confirmed SDK terminal is not execution success', async () => {
  const n = node(response(200, { choices: [{ message: { content: 'bridge reply' } }] }));
  const r = await new SdkTransport(n, env).run(input);
  assert.equal(r.status, 'delivery_unknown');
  assert.equal(n.calls.length, 1);
});
test('transport failure after dispatch is unknown and is never resent', async () => {
  const n = node(null); n.fetch = async r => { n.calls.push(r); throw Error('disconnected'); };
  assert.equal((await new SdkTransport(n, env).run(input)).status, 'delivery_unknown');
  assert.equal(n.calls.length, 1);
});
test('offline or missing configuration does not dispatch', async () => {
  for (const [state, config] of [['NeedsLogin', env], ['Running', {}]]) {
    const n = node(null, state);
    assert.equal((await new SdkTransport(n, config).run(input)).status, 'failed');
    assert.equal(n.calls.length, 0);
  }
});
test('API rejects targets that are the model bridge or a public destination', async () => {
  for (const target of ['http://muse-vm:8080/v1/chat/completions', 'https://example.com/agent/code/run']) {
    const n = node(null);
    assert.equal((await new SdkTransport(n, { ...env, SDK_TARGET_URL: target }).run(input)).status, 'failed');
    assert.equal(n.calls.length, 0);
  }
});
test('SDK authentication and permission failures retain structured failure, not success', async () => {
  const n = node(response(401, { error: 'auth_required', status: 'failed' }));
  assert.deepEqual(await new SdkTransport(n, env).run(input), { status: 'failed', error: 'auth_required' });
});
